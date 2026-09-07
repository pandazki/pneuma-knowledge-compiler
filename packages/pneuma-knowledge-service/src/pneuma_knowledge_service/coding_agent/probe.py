"""Is this harness actually usable — asked as liveness, never as presence (§8, ruling 9).

Three failure modes a deployment must be able to tell apart before it starts, and one that
must never happen:

* **not installed** — nothing on `PATH` by that name.
* **installed but not logged in** — the worst of the three, because a CLI in this state
  often drops into an interactive login flow and waits forever. That is why the probe is a
  real non-interactive invocation under a HARD deadline rather than a `--version`.
* **installed and live** — the command answered 0 inside the deadline.

And the thing that must never happen: the probe hanging. It runs the child in its own
process group, TERMs the group at the deadline and KILLs it 300 ms later, so a harness that
would have waited for a keypress costs the deadline and not the worker.

A version number is NEVER compared (ruling 9). What a version would tell us — whether a flag
exists — is a question the launcher answers by running the command and reading the result,
which stays true when the harness ships a new one tomorrow.

Nothing is cached across processes. The probe is about the state of an installation right
now, and a cached "live" from an hour ago is exactly the answer that would be wrong.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from dataclasses import dataclass

from .backends import BackendManifest

log = logging.getLogger(__name__)

#: How long the group gets between TERM and KILL. Long enough for a CLI to unwind its
#: terminal state, short enough that a probe's whole cost stays the deadline plus a blink.
GRACE_S = 0.3

#: The default deadline for one probe, in seconds. A live CLI answers well inside it; an
#: unauthenticated one is killed at the boundary and reported with its reason.
DEFAULT_DEADLINE_S = 20.0


@dataclass(frozen=True)
class ProbeResult:
    """What one probe found. `reason` is prose for a person; `ok` is the fact."""

    backend: str
    ok: bool
    reason: str
    binary_path: str = ""

    def render(self) -> str:
        where = f" ({self.binary_path})" if self.binary_path else ""
        return f"{self.backend}: {'live' if self.ok else 'unusable'}{where} — {self.reason}"


async def _run_detached(
    argv: list[str], *, deadline_s: float, env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Run `argv` in its own process group under a hard deadline. Returns (code, output).

    stdin is `/dev/null`, deliberately: a command that decides to ask a question gets EOF
    instead of a person, which turns "hangs forever" into "exits non-zero".
    """
    with open(os.devnull, "rb") as null:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=null,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), deadline_s)
        return process.returncode or 0, (stdout or b"").decode("utf-8", "replace")
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await terminate_group(process)
        raise


def signal_group(process, signum: int) -> bool:  # noqa: ANN001
    """Send `signum` to the child's whole process GROUP. False when it is already gone.

    The group, not the child: a harness spawns its own helpers, and killing only the parent
    leaves them holding the terminal and the subscription. `start_new_session=True` at spawn
    is what makes the group addressable.
    """
    pid = getattr(process, "pid", None)
    if pid is None or process.returncode is not None:
        return False
    try:
        os.killpg(os.getpgid(pid), signum)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


async def terminate_group(process, *, grace_s: float = GRACE_S) -> None:  # noqa: ANN001
    """TERM the group, wait `grace_s`, KILL what is left, and reap it.

    Shielded from cancellation: this IS the cancellation path, and a second cancel arriving
    mid-kill would leave the very process it was called to reap.
    """
    if not signal_group(process, signal.SIGTERM):
        return
    try:
        await asyncio.shield(asyncio.wait_for(process.wait(), grace_s))
        return
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    signal_group(process, signal.SIGKILL)
    try:
        await asyncio.shield(asyncio.wait_for(process.wait(), grace_s * 4))
    except (asyncio.TimeoutError, asyncio.CancelledError):
        log.warning("harness process %s survived SIGKILL", getattr(process, "pid", "?"))


def reap_now(process) -> None:  # noqa: ANN001
    """KILL the group without awaiting anything — the interpreter-exit path.

    At `atexit` there is no loop left to await on, so the grace period is skipped: the only
    thing worse than not asking politely is leaving a harness running after the worker is
    gone.
    """
    signal_group(process, signal.SIGKILL)


async def probe(
    manifest: BackendManifest, *, deadline_s: float = DEFAULT_DEADLINE_S
) -> ProbeResult:
    """PATH lookup, then the manifest's liveness command under `deadline_s`."""
    binary = shutil.which(manifest.binary)
    if binary is None:
        return ProbeResult(
            manifest.name,
            False,
            f"{manifest.binary!r} is not on PATH — install {manifest.display_label} first",
        )
    if not manifest.probe_command:
        return ProbeResult(
            manifest.name,
            False,
            f"{manifest.display_label} states no liveness command, so this deployment "
            "cannot tell whether it is usable",
            binary,
        )
    argv = [binary, *manifest.probe_command]
    try:
        code, output = await _run_detached(argv, deadline_s=deadline_s)
    except asyncio.TimeoutError:
        return ProbeResult(
            manifest.name,
            False,
            f"`{' '.join(manifest.probe_command)}` did not answer within {deadline_s:g}s — "
            f"{manifest.display_label} is installed but not responding (an unfinished login "
            "looks exactly like this)",
            binary,
        )
    except OSError as exc:
        return ProbeResult(manifest.name, False, f"{manifest.binary} could not be run: {exc}", binary)
    if code == 0:
        return ProbeResult(manifest.name, True, "answered its liveness command", binary)
    detail = " ".join(output.split())[:200]
    return ProbeResult(
        manifest.name,
        False,
        f"`{' '.join(manifest.probe_command)}` exited {code}"
        + (f": {detail}" if detail else "")
        + f" — {manifest.display_label} is installed but not logged in",
        binary,
    )


async def supports(
    manifest: BackendManifest,
    command: tuple[str, ...],
    *,
    deadline_s: float = DEFAULT_DEADLINE_S,
) -> bool:
    """Does the installed CLI have this surface at all? Asked by running it, not by version.

    Used for the repair round's resume: an installed CLI that has no `resume` answers
    non-zero, and the launcher runs a fresh process instead of a resumed one.
    """
    if not command:
        return True
    binary = shutil.which(manifest.binary)
    if binary is None:
        return False
    try:
        code, _ = await _run_detached([binary, *command], deadline_s=deadline_s)
    except (asyncio.TimeoutError, OSError):
        return False
    return code == 0


__all__ = [
    "DEFAULT_DEADLINE_S",
    "GRACE_S",
    "ProbeResult",
    "probe",
    "reap_now",
    "signal_group",
    "supports",
    "terminate_group",
]
