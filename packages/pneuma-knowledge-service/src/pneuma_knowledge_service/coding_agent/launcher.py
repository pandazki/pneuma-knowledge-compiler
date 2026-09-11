"""The unattended launcher: one harness process, run as a round the worker can trust (§8).

A harness is built for a person at a terminal. Nobody there means seven things nobody else
will do, and this module is all seven:

1. **the prompt is never in argv.** The system text and the task are files in a working
   directory made for this launch and holding nothing else; the task file is stdin. A
   process list on a shared machine is not a place a library's material belongs.
2. **the working directory is empty.** `mkdtemp`, deleted afterwards. The harness's file
   tools therefore reach nothing of the project by accident; the one hand it has is the
   `pkc` shim named in the task.
3. **the config home is per JOB.** `CODEX_HOME` / `CLAUDE_CONFIG_DIR` point at a directory
   the caller owns, so a round never writes a session file into the Owner's real home — and
   the repair round can resume the first round's session, because that directory outlives
   the launch that made it.
4. **there is a wall clock.** `COMPILE_CALL_TIMEOUT`, reused: a hung harness is invisible to
   every other guardrail exactly as a hung provider connection was, and the job would sit
   `claimed` until a worker restart.
5. **the process group is reaped.** Spawned with `start_new_session=True`, TERMed at the
   deadline and KILLed a second later — and the same on the worker's own cancellation and at
   interpreter exit, so a killed worker never leaves a harness running.
6. **a rate limit is waited out, not failed on.** The manifest says which exit codes and
   which words mean it; the launcher backs off with jitter, bounded by a setting and a
   ceiling, and logs every wait. It does not work around a limit — the terms are the
   provider's (§13).
7. **usage is read from the harness's own report.** Which is why the unattended posture CAN
   say what a round cost when the interactive one cannot: absent means nothing measured it,
   never zero.

`asyncio.create_subprocess_exec`, not `to_thread`: this is real async I/O with a real
cancellation story, and a thread holding `communicate()` could not be interrupted at all.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import random
import re
import shutil
import tempfile
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from .backends import (
    HIDDEN_SKILLS,
    MODEL,
    OUTPUT_FILE,
    PROJECT_DIR,
    REASONING_EFFORT,
    SESSION,
    SKILL_NAME,
    SYSTEM_FILE,
    SYSTEM_PROMPT_FILE,
    BackendManifest,
    render_argv,
    unavailable_reason,
)
from .harness_output import HarnessReport
from .install import SKILL_HASH_ENV
from .probe import reap_now, supports, terminate_group

log = logging.getLogger(__name__)

#: The env var the launcher sets so a `pkc` command run by the harness records WHICH harness
#: typed it (`workers.compile_worker.agent_executor`). The same name `Settings` reads.
BACKEND_ENV = "PNEUMA_KNOWLEDGE_EXECUTOR_BACKEND"

#: What one launch's temp directory is called, so a leftover is recognisable in `/tmp`.
WORKDIR_PREFIX = "pkc-round-"

#: The file names inside it. Fixed, because they are named in log lines a person reads.
SYSTEM_FILENAME = "system.txt"
TASK_FILENAME = "task.txt"
LAST_MESSAGE_FILENAME = "last-message.txt"

#: The longest a backoff wait may grow to, whatever the attempt number. A subscription's
#: window is measured in minutes; waiting an hour inside a claimed job would be worse than
#: failing the job and letting it be re-queued.
BACKOFF_CEILING_S = 120.0
#: The first wait, doubled per attempt, with up to ±25% jitter so several workers coming off
#: the same limit do not return in lockstep.
BACKOFF_BASE_S = 5.0
BACKOFF_JITTER = 0.25
#: The waits before each relaunch when the MODEL is at capacity, with the same jitter.
#: Wider than a rate limit's, and on purpose: capacity was seen to come and go within
#: seconds-to-minutes, so relaunching five seconds later mostly meets the same refusal, and
#: four quick refusals then cooled the whole tenant. Spread across a minute and a half, a
#: brief dip is usually absorbed inside this one launch.
CAPACITY_BACKOFF_S: tuple[float, ...] = (15.0, 30.0, 60.0)

#: How long after TERM the group gets before KILL, per §8 ("reaped TERM→KILL").
KILL_AFTER_S = 1.0

#: What `scrub` replaces a credential with. A marker rather than deletion, because a line
#: that lost a word silently reads as the harness having said something it did not.
REDACTED = "«redacted»"

#: What a credential looks like in a harness's own output. Two families: a value stated
#: after a name that says what it is (`OPENAI_API_KEY=sk-…`, `"authorization": "Bearer …"`),
#: and a token whose SHAPE is the whole tell (`sk-…`, a JWT). Neither list is a guarantee —
#: nothing can be — but the output of a failed launch travels onto a job row and out of a
#: `pkc jobs --json`, and a launcher that carried the environment's secrets there would have
#: made the failure report the leak.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b([A-Za-z0-9_.\-]*(?:api[_-]?key|apikey|secret|token|password|passwd|"
        r"credential)[A-Za-z0-9_.\-]*)\s*([=:]\s*)[\"']?([^\s\"',]{6,})",
    ),
    re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._\-+/=]{12,})"),
    re.compile(r"\b(sk|rk|pk|xoxb|xoxp|ghp|gho|ghu|ghs|github_pat)[-_][A-Za-z0-9_\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+"),
)


def scrub(text: str, *, secrets: Sequence[str] = ()) -> str:
    """A harness's own words with anything credential-shaped taken out of them.

    One function, because there is one rule: output that leaves this process — onto a job
    row, into a log line, through the jobs API — is scrubbed at the boundary rather than
    wherever somebody remembers to. `secrets` are exact values the caller already knows
    (a resolved setting's key), masked literally; the patterns catch the rest by shape.
    """
    if not text:
        return ""
    out = text
    for value in secrets:
        if value and len(str(value)) >= 6:
            out = out.replace(str(value), REDACTED)
    out = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    out = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)} {REDACTED}", out)
    for pattern in _SECRET_PATTERNS[2:]:
        out = pattern.sub(REDACTED, out)
    return out


#: Every live harness process this interpreter spawned, so exit can reap them. A weak set:
#: a finished process must not be kept alive by the bookkeeping that watches it.
_LIVE: "weakref.WeakSet" = weakref.WeakSet()


def _reap_all() -> None:
    for process in list(_LIVE):
        reap_now(process)


atexit.register(_reap_all)


@dataclass(frozen=True)
class LaunchResult:
    """What one launch did — including the two ways it did not finish."""

    exit_code: int
    stdout: str
    stderr: str
    #: The harness's own token counts, or None when its output reported none. NEVER zero.
    usage: dict[str, int] | None = None
    #: What the harness said the round cost in money, when it prices itself at all.
    cost_usd: float | None = None
    timed_out: bool = False
    #: The launch failed for a reason that waiting fixes — the subscription is out of room,
    #: or the model has no capacity. One flag for both because the launcher and the worker do
    #: the same thing about them; `backends.unavailable_reason` is what tells them apart when
    #: a person has to be told which it was.
    rate_limited: bool = False
    #: The session the round ran under, when the harness names one — what a repair round
    #: resumes.
    session_id: str = ""
    #: How many times the harness was launched, backoff included. 1 is the normal round.
    attempts: int = 1
    #: The harness's final message, when it writes one to a file rather than to stdout.
    last_message: str = ""
    #: The working directory, when a setting said to keep it; "" when it was deleted.
    workdir: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class LaunchRequest:
    """One round's inputs, as the launcher needs them.

    A record rather than eight keyword arguments, because the round runner builds it once
    and the repair round rebuilds it with two fields changed.
    """

    manifest: BackendManifest
    system_text: str
    task_text: str
    #: The project the shim and the installed skill live in. Named to the harness's file
    #: tools where the manifest asks for it; never the working directory.
    project_dir: str
    #: The per-JOB config home. The launcher creates it if absent and never deletes it — its
    #: life is the job's, because the repair round resumes what the first round wrote there.
    config_home: str
    timeout_s: float
    model: str = ""
    #: How hard the harness is told to think. Carried only by a harness whose manifest states
    #: the flags for it; empty is the harness's own default.
    reasoning_effort: str = ""
    #: Resume this session instead of starting a new one, when the manifest can.
    resume_session: str = ""
    #: `SKILL.md` paths of the copies of this framework's skill the round must not see
    #: (`foreign_skill_copies`). Carried only by a harness whose manifest can switch one off.
    hidden_skills: tuple[str, ...] = ()
    #: Extra environment for the child, on top of the inherited one.
    env: dict[str, str] = field(default_factory=dict)
    #: The worker's own resolved `Settings`, so the child's `pkc` reaches the SAME stack this
    #: worker does. None = state nothing and let the child resolve for itself.
    settings: object | None = None
    retries: int = 3
    keep_workdir: bool = False


#: Which `Settings` fields a launched harness's `pkc` must be told, and under which name.
#: Every one of them is a CONNECTION, never a strategy knob: WHAT a round compiles is the
#: engine's business, while WHICH library it compiles into cannot be left to a fallback. The
#: child runs in an empty working directory and so has no project `.env` to read — before
#: this, its `pkc` fell back to the framework's own development ports and stood in a
#: different library than the worker that launched it.
CONNECTION_SETTINGS: tuple[tuple[str, str], ...] = (
    ("PNEUMA_KNOWLEDGE_PG_DSN", "pg_dsn"),
    ("PNEUMA_KNOWLEDGE_QDRANT_URL", "qdrant_url"),
    ("PNEUMA_KNOWLEDGE_QDRANT_COLLECTION", "qdrant_collection"),
    ("PNEUMA_KNOWLEDGE_MEILI_URL", "meili_url"),
    ("PNEUMA_KNOWLEDGE_MEILI_KEY", "meili_key"),
    ("PNEUMA_KNOWLEDGE_CANONICAL_ROOT", "canonical_root"),
    ("PNEUMA_KNOWLEDGE_ENGINE_DIR", "engine_dir"),
    ("PNEUMA_KNOWLEDGE_MEDIA_S3_ENDPOINT_URL", "media_s3_endpoint_url"),
    ("PNEUMA_KNOWLEDGE_MEDIA_S3_BUCKET", "media_s3_bucket"),
    ("PNEUMA_KNOWLEDGE_MEDIA_S3_ACCESS_KEY", "media_s3_access_key"),
    ("PNEUMA_KNOWLEDGE_MEDIA_S3_SECRET_KEY", "media_s3_secret_key"),
)

#: The two of them that are PATHS, made absolute before they travel: the child's working
#: directory is a `mkdtemp`, and `./data/canonical` resolved there is an empty library it
#: would happily create.
_PATH_SETTINGS = frozenset({"canonical_root", "engine_dir"})


def connection_env(settings: object | None) -> dict[str, str]:
    """The connection half of `settings`, as environment for a child process."""
    if settings is None:
        return {}
    out: dict[str, str] = {}
    for name, field_name in CONNECTION_SETTINGS:
        value = getattr(settings, field_name, None)
        if value is None or str(value).strip() == "":
            continue
        text = str(value)
        if field_name in _PATH_SETTINGS:
            text = str(Path(text).expanduser().resolve())
        out[name] = text
    return out


def harness_env(
    manifest: BackendManifest,
    *,
    config_home: str,
    extra: Mapping[str, str] | None = None,
    settings: object | None = None,
) -> dict[str, str]:
    """The environment a harness process runs under: inherited, then stated, then subtracted.

    PATH is inherited on purpose — the harness is an installed program and finding it is the
    system's job. What is added is the hermetic config home, the backend label every `pkc`
    command in the session will record, and the skill hash the shim would otherwise have to
    read. What is REMOVED is the nesting flag: a Claude Code session that believes it is
    nested short-circuits, and a worker started from inside one would launch rounds that do
    nothing.

    One function for both postures. The unattended round below and the console's Steward
    session (`steward_session.py`) spawn different processes for different reasons, but a
    harness's environment is a property of the HARNESS, and two copies of it would drift on
    the day a third variable matters.

    `settings` is the third thing added: WHICH library the child's `pkc` reaches. Handed the
    worker's own resolved settings, so a harness cannot resolve a different stack than the
    process that launched it (`CONNECTION_SETTINGS`).
    """
    env = dict(os.environ)
    if manifest.config_home_env:
        env[manifest.config_home_env] = config_home
    env[BACKEND_ENV] = manifest.name
    # A console session's config home is unique and survives reconnects. Unattended rounds
    # override this with their own PKC_DRAFT_EXECUTOR, shared by runner and child commands.
    env["PKC_STEWARD_SESSION"] = config_home
    env.pop("PKC_DRAFT_EXECUTOR", None)
    # Which library. Stated before `extra` so a caller may still override one field, and
    # stated at all because the child has no project `.env` to fall back on.
    env.update(connection_env(settings))
    env.update(extra or {})
    for name in manifest.unset_env:
        env.pop(name, None)
    if not env.get(SKILL_HASH_ENV):
        env.pop(SKILL_HASH_ENV, None)
    return env


def _child_env(request: LaunchRequest) -> dict[str, str]:
    """One round's environment — `harness_env` with the request's own fields."""
    return harness_env(
        request.manifest,
        config_home=request.config_home,
        extra=request.env,
        settings=request.settings,
    )


def foreign_skill_copies(manifest: BackendManifest, project_dir: str) -> tuple[str, ...]:
    """Every copy of this framework's skill a round would see besides the library's own.

    The per-job config home hides the Owner's global copy under `~/.codex` / `~/.claude`,
    because the round's config home is not the Owner's. It cannot hide a copy in a root the
    harness reads from HOME regardless (`manifest.home_skill_roots`) — and a round that lists
    two `pkc-steward` skills may read the global router instead of its library's package. So
    each copy found there is named, by the path as reached and by its resolved target (the
    root may be a symlink), for the launch to switch off. The library's own package is never
    among them, whichever way it is reached.
    """
    own = (Path(project_dir).expanduser() / manifest.skill_dir / "SKILL.md").resolve()
    found: list[str] = []
    for root in manifest.home_skill_roots:
        skill = Path(root).expanduser() / SKILL_NAME / "SKILL.md"
        if not skill.is_file() or skill.resolve() == own:
            continue
        for path in (str(skill), str(skill.resolve())):
            if path not in found:
                found.append(path)
    return tuple(found)


def seed_config_home(manifest: BackendManifest, home: Path) -> None:
    """Make a per-job config home the harness can actually log in from.

    Moving `CODEX_HOME` / `CLAUDE_CONFIG_DIR` moves the harness's whole world, credentials
    included — an empty one is a harness that is suddenly logged out, and the round would die
    on an auth error rather than on anything about the library. So the manifest names the
    files that must be there and they are LINKED from the Owner's real home: no secret is
    copied into a temporary directory, and a token the round refreshes is refreshed where the
    Owner's own sessions will find it. Everything else the harness writes — sessions, logs,
    caches — lands in the per-job directory and dies with the job, which was the point.

    Best effort by design: a file that is not there is a file this installation does not use
    (a harness authenticating through the system keychain has none), and a link that cannot be
    made is left for the harness to complain about in its own words.
    """
    home.mkdir(parents=True, exist_ok=True)
    if not manifest.default_config_home:
        return
    source_root = Path(manifest.default_config_home).expanduser()
    for name in manifest.config_seed:
        source = source_root / name
        target = home / name
        if not source.exists() or target.exists():
            continue
        try:
            target.symlink_to(source)
        except OSError:
            log.debug("could not link %s into the round's config home", source, exc_info=True)


def build_argv(request: LaunchRequest, workdir: Path) -> list[str]:
    """The full argv for one launch: the binary, then the manifest's template, filled.

    The prompt is not among them and cannot be: no placeholder carries it, because the task
    is stdin (§8).
    """
    manifest = request.manifest
    template = manifest.launch_command
    if request.resume_session and manifest.resume_command:
        template = manifest.resume_command
    values = {
        MODEL: request.model or "",
        # A harness that states no effort flags is a harness that takes no effort: the value
        # is dropped here rather than at the template, so a deployment that configured one
        # cannot reach a CLI that would exit on it. Read off the manifest, never off a name.
        REASONING_EFFORT: (request.reasoning_effort or "") if manifest.effort_flags else "",
        SYSTEM_FILE: str(workdir / SYSTEM_FILENAME),
        OUTPUT_FILE: str(workdir / LAST_MESSAGE_FILENAME),
        PROJECT_DIR: str(Path(request.project_dir).expanduser().resolve()),
        SESSION: request.resume_session or "",
        HIDDEN_SKILLS: (
            manifest.render_hidden_skills(request.hidden_skills)
            if request.hidden_skills and manifest.render_hidden_skills
            else ""
        ),
    }
    return [manifest.binary, *render_argv(template, values)]


def stdin_text(request: LaunchRequest) -> str:
    """What the task file holds — the whole prompt, and the system text when it must ride it.

    Codex has no system channel, so the degradation is stated rather than hidden: the system
    text heads the file, one blank line, then the task. I5 still holds — those are the same
    bytes the system channel would have carried, in the same order.
    """
    if request.manifest.system_text_channel == SYSTEM_PROMPT_FILE:
        return request.task_text
    system = request.system_text.strip("\n")
    return f"{system}\n\n{request.task_text}" if system else request.task_text


def _is_rate_limited(
    manifest: BackendManifest, code: int, output: str, *, failed: bool = False
) -> bool:
    """Did this launch fail for a reason that WAITING fixes?

    Two families, one answer: the Owner's subscription is out of room (`rate_limit_markers`)
    or the model itself has none (`unavailable_markers`). Both are transient, both are worth
    a backoff, and neither is anything the framework can work around — the terms are the
    provider's (§13).

    `failed` is the harness's own protocol saying the turn did not complete, and it is what
    lets the scan run at exit code 0. That case is real: `codex exec` printed
    `{"type":"turn.failed" … "Selected model is at capacity"}` on stdout with no tool calls
    and a return code a launcher would have read as success. The scan is still gated on it
    rather than run unconditionally, because the same words can appear in a round's own
    output — a library about a venue at capacity is not a library whose harness is down.
    """
    if code in manifest.rate_limit_exit_codes:
        return True
    if code == 0 and not failed:
        return False
    haystack = output.lower()
    return any(
        marker.lower() in haystack
        for marker in (*manifest.rate_limit_markers, *manifest.unavailable_markers)
    )


def backoff_wait(attempt: int, *, rng: random.Random | None = None) -> float:
    """The wait before attempt `attempt` (1-based), exponential with jitter and a ceiling."""
    picker = rng or random
    base = min(BACKOFF_BASE_S * (2 ** max(attempt - 1, 0)), BACKOFF_CEILING_S)
    return max(0.0, base * (1.0 + picker.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)))


def capacity_wait(attempt: int, *, rng: random.Random | None = None) -> float:
    """The wait before attempt `attempt` (1-based) when the model is at capacity: the
    `CAPACITY_BACKOFF_S` step for that attempt (the last one repeats), with jitter."""
    picker = rng or random
    base = CAPACITY_BACKOFF_S[min(max(attempt - 1, 0), len(CAPACITY_BACKOFF_S) - 1)]
    return max(0.0, base * (1.0 + picker.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)))


def _at_capacity(manifest: BackendManifest, result: "LaunchResult") -> bool:
    """Was this transient refusal the model having no room, rather than a spent quota? The
    same words `round_runner.classify_refusal` reads, off the same output."""
    said = unavailable_reason(f"{result.stderr}\n{result.stdout}", manifest)
    return said in ("at capacity", "unavailable")


async def _run_once(request: LaunchRequest, workdir: Path) -> LaunchResult:
    """One harness process, start to finish, under the wall clock."""
    manifest = request.manifest
    (workdir / SYSTEM_FILENAME).write_text(request.system_text, encoding="utf-8")
    task_file = workdir / TASK_FILENAME
    task_file.write_text(stdin_text(request), encoding="utf-8")
    (workdir / LAST_MESSAGE_FILENAME).write_text("", encoding="utf-8")

    argv = build_argv(request, workdir)
    env = _child_env(request)
    log.info(
        "launching %s round in %s: %s",
        manifest.display_label,
        workdir,
        " ".join(argv),
    )
    with task_file.open("rb") as stdin:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=env,
            start_new_session=True,
        )
    _LIVE.add(process)
    timed_out = False
    try:
        out, err = await asyncio.wait_for(
            process.communicate(), request.timeout_s or None
        )
    except asyncio.TimeoutError:
        timed_out = True
        await terminate_group(process, grace_s=KILL_AFTER_S)
        out, err = b"", b""
        log.warning(
            "%s round exceeded %.0fs and its process group was reaped",
            manifest.display_label,
            request.timeout_s,
        )
    except asyncio.CancelledError:
        # The worker is going away. Reap the group before the frame does, or the harness
        # outlives the process that owns it.
        await terminate_group(process, grace_s=KILL_AFTER_S)
        raise
    finally:
        _LIVE.discard(process)

    stdout = (out or b"").decode("utf-8", "replace")
    stderr = (err or b"").decode("utf-8", "replace")
    last_message = ""
    message_file = workdir / LAST_MESSAGE_FILENAME
    if message_file.is_file():
        last_message = message_file.read_text(encoding="utf-8", errors="replace")
    code = -1 if timed_out else (process.returncode or 0)
    try:
        report = manifest.read_output(stdout, last_message)
    except Exception:  # noqa: BLE001 — an unknown protocol surface degrades, never raises
        log.warning(
            "could not read %s's own report of the round; usage is unknown",
            manifest.display_label,
            exc_info=True,
        )
        report = HarnessReport()
    return LaunchResult(
        exit_code=code,
        stdout=stdout,
        stderr=stderr,
        usage=report.usage,
        cost_usd=report.cost_usd,
        timed_out=timed_out,
        # stdout as well as stderr, and deliberately: Codex states a failed turn as a JSON
        # event on stdout, and a scan that read only stderr would see nothing at all.
        rate_limited=_is_rate_limited(
            manifest,
            code,
            f"{stdout}\n{stderr}\n{report.failure_message}",
            failed=report.failed,
        ),
        session_id=report.session_id,
        last_message=report.last_message or last_message,
    )


async def launch_round(
    request: LaunchRequest, *, sleep=asyncio.sleep, rng: random.Random | None = None
) -> LaunchResult:
    """Run one round, retrying only what a retry can fix: a rate limit.

    A non-zero exit that is not a rate limit is REPORTED, not retried — a harness that
    refused the task will refuse it again, and the draft it left behind is what the worker
    reads next. A timeout is not retried either: the wall clock is the statement that this
    round is over.
    """
    attempts = max(1, int(request.retries) + 1)
    seed_config_home(request.manifest, Path(request.config_home))
    result: LaunchResult | None = None
    for attempt in range(1, attempts + 1):
        workdir = Path(tempfile.mkdtemp(prefix=WORKDIR_PREFIX))
        try:
            result = await _run_once(request, workdir)
        finally:
            if request.keep_workdir:
                log.info("kept the round's working directory at %s", workdir)
            else:
                shutil.rmtree(workdir, ignore_errors=True)
        result = replace(
            result,
            attempts=attempt,
            workdir=str(workdir) if request.keep_workdir else "",
        )
        if not result.rate_limited or attempt >= attempts:
            return result
        capacity = _at_capacity(request.manifest, result)
        wait = capacity_wait(attempt, rng=rng) if capacity else backoff_wait(attempt, rng=rng)
        log.warning(
            "%s reported %s on attempt %d/%d; waiting %.1fs before the next",
            request.manifest.display_label,
            "the model at capacity" if capacity else "a rate limit",
            attempt,
            attempts,
            wait,
        )
        await sleep(wait)
    assert result is not None  # the loop runs at least once
    return result


async def resume_supported(manifest: BackendManifest) -> bool:
    """Can this installed CLI continue a session? Asked once, by running it.

    Cached for the life of the process because it is a property of the installation, not of
    the round — and not across processes, for the same reason the probe is not.
    """
    if not manifest.resume_command:
        return False
    cached = _RESUME_SUPPORT.get(manifest.name)
    if cached is None:
        cached = await supports(manifest, manifest.resume_probe_command)
        _RESUME_SUPPORT[manifest.name] = cached
    return cached


_RESUME_SUPPORT: dict[str, bool] = {}


__all__ = [
    "BACKEND_ENV",
    "BACKOFF_BASE_S",
    "BACKOFF_CEILING_S",
    "CAPACITY_BACKOFF_S",
    "KILL_AFTER_S",
    "LaunchRequest",
    "LaunchResult",
    "backoff_wait",
    "build_argv",
    "connection_env",
    "harness_env",
    "launch_round",
    "scrub",
    "foreign_skill_copies",
    "seed_config_home",
    "resume_supported",
    "stdin_text",
]
