"""One live harness session per Owner, bridged to the console (§5.6, ruling 13).

The unattended launcher runs a ROUND: one process, one task, an exit code. This runs a
CONVERSATION: one process that stays up, many turns, and a browser watching. What the two
share is the harness's environment — the hermetic config home seeded by symlink, the backend
label, `CLAUDECODE` unset — so that half is `launcher.harness_env` and `launcher.
seed_config_home`, called from here rather than written twice.

What is only here:

* **the project directory is the working directory.** Unattended, the harness is put in an
  empty `mkdtemp` so its file tools reach nothing; interactively it sits in the project,
  because that is where `AGENTS.md` / `CLAUDE.md` and the installed skill are, and the Owner
  is watching every command it runs. `PNEUMA_KNOWLEDGE_PROJECT_DIR` names it.
* **the session outlives the tab.** Closing a browser tab is not ending a conversation. The
  process stays up for `STEWARD_SESSION_IDLE` after the last socket detaches and a reconnect
  re-attaches to it; past that the process GROUP is reaped TERM→KILL. A harness that died on
  its own is reported as `session_exited` and never silently restarted into a fresh session
  that has forgotten everything.
* **one session per Owner, and a second attach JOINS it.** Not a refusal: two tabs on one
  library are one person at two windows, and they watch the same conversation — the snapshot
  repaints each of them and every event reaches both. What is not allowed is two harnesses
  compiling one library at once, and that is exactly what a single session prevents.
* **the Owner's turn is recorded BEFORE the harness sees it.** `steward_turns` is written
  first, so `pkc owner say` can never be handed a session whose transcript is one turn behind
  the conversation the Steward is acting on (ruling 13).
* **a mid-turn message is queued, never steered.** Claude's streaming input carries no turn
  id, so a second turn written into a running one would race it. The bridge holds the text
  until `turn_finished` and tells the client it did. A protocol race fails explicitly; it is
  never an interrupt and a resend.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pneuma_knowledge_core.domain.ids import UserId

from .backends import MODEL, PROJECT_DIR, SESSION, BackendManifest, render_argv
from .install import SKILL_HASH_ENV, installed_hash
from .launcher import KILL_AFTER_S, harness_env, seed_config_home
from .probe import terminate_group
from .steward_events import (
    QUEUED,
    Notice,
    SessionExited,
    SessionStarted,
    StewardEvent,
    TurnFinished,
)
from .steward_turns import (
    SESSION_ENV,
    InMemoryStewardTurnStore,
    PairedStewardTurnStore,
)

log = logging.getLogger(__name__)

#: How many events a reconnecting tab is repainted with. A conversation's whole history lives
#: in the harness's own session; what the bridge holds is enough to redraw the screen.
SNAPSHOT_LIMIT = 200

#: What a session's config home is called, so a leftover is recognisable in `/tmp`.
CONFIG_HOME_PREFIX = "pkc-steward-"

#: How much stdout is read at a time. Whole lines are the adapter's problem, not this one's.
READ_CHUNK = 65536

#: How long the pump waits for the exit code after the harness closed its stdout. A process
#: whose stream is done is a process that is about to be gone; past this the exit is reported
#: without a code rather than held open on one.
EXIT_WAIT_S = 5.0


class NoCodingAgent(RuntimeError):
    """This deployment compiles with a model, so there is no Steward to talk to."""


@dataclass
class StewardSession:
    """One harness process, its adapter, its subscribers and its transcript."""

    user_id: UserId
    manifest: BackendManifest
    project_dir: str
    #: Both halves of the transcript: in memory, and in Postgres where one is wired.
    turns: PairedStewardTurnStore
    model: str = ""
    idle_s: float = 30 * 60.0
    #: Injected so the tests can drive a session without a harness on `PATH`.
    spawn: Any = None

    session_id: str = field(default_factory=lambda: f"stw-{uuid.uuid4().hex[:12]}")
    adapter: Any = None
    process: Any = None
    events: deque = field(default_factory=lambda: deque(maxlen=SNAPSHOT_LIMIT))
    subscribers: set = field(default_factory=set)
    exited: bool = False
    exit_code: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)
    _queued: list[str] = field(default_factory=list)
    _config_home: str = ""
    _tasks: set = field(default_factory=set)
    _idle_task: Any = None
    _write_lock: Any = None

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def argv(self) -> list[str]:
        """The interactive argv: the binary, then the manifest's template, filled.

        Same substitution rule as the unattended launcher's — a flag whose placeholder
        resolves empty drops with the flag before it — so "no model named" is one template
        rather than two.
        """
        values = {
            MODEL: self.model or "",
            PROJECT_DIR: str(Path(self.project_dir).expanduser().resolve()),
            SESSION: "",
        }
        return [self.manifest.binary, *render_argv(self.manifest.interactive_command, values)]

    def env(self, config_home: str) -> dict[str, str]:
        """What the session is told: the harness's own variables, plus the two the `pkc`
        commands it runs will read back — which harness typed them, and which session they
        belong to (that last one is the whole of how `pkc owner say` finds the transcript)."""
        extra = {SESSION_ENV: self.session_id}
        digest = installed_hash(self.project_dir, self.manifest)
        if digest:
            extra[SKILL_HASH_ENV] = digest
        return harness_env(self.manifest, config_home=config_home, extra=extra)

    async def start(self) -> None:
        """Spawn the harness in the project, and start reading it."""
        if self.manifest.interactive_adapter is None:
            raise NoCodingAgent(
                f"{self.manifest.display_label} has no interactive posture in this version"
            )
        self._write_lock = asyncio.Lock()
        home = Path(tempfile.mkdtemp(prefix=CONFIG_HOME_PREFIX))
        self._config_home = str(home)
        seed_config_home(self.manifest, home)
        project = str(Path(self.project_dir).expanduser().resolve())
        self.adapter = self.manifest.interactive_adapter(
            project_dir=project, model=self.model
        )
        argv = self.argv()
        log.info(
            "starting a %s Steward session for %s in %s: %s",
            self.manifest.display_label,
            self.user_id,
            project,
            " ".join(argv),
        )
        spawn = self.spawn or asyncio.create_subprocess_exec
        self.process = await spawn(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project,
            env=self.env(self._config_home),
            # Its own group, so the whole tree is reaped and not just the parent — a harness
            # spawns helpers, and killing the parent alone leaves them holding the
            # subscription.
            start_new_session=True,
        )
        self._track(asyncio.create_task(self._pump()))
        self._track(asyncio.create_task(self._drain_stderr()))
        self.adapter.start()
        await self._flush()

    def _track(self, task) -> None:  # noqa: ANN001
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @property
    def live(self) -> bool:
        return not self.exited and self.process is not None

    @property
    def agent_session_id(self) -> str:
        return getattr(self.adapter, "agent_session_id", "") or ""

    # ── the wire ─────────────────────────────────────────────────────────────────────────

    async def _flush(self) -> None:
        """Write whatever the adapter has queued, and broadcast whatever it produced."""
        writes = self.adapter.take_writes() if self.adapter else []
        if writes and self.process is not None and self.process.stdin is not None:
            async with self._write_lock:
                for frame in writes:
                    self.process.stdin.write(frame)
                with contextlib.suppress(Exception):
                    await self.process.stdin.drain()
        self._emit(self.adapter.take_events() if self.adapter else [])

    async def _pump(self) -> None:
        """Read the harness's stdout until it closes, then report the exit — once.

        The exit bookkeeping is deliberately NOT in a `finally`. On cancellation this task is
        being torn down by `close`, which owns both the reaping and the report; awaiting the
        process's exit on the way out would be a task that never finishes and an interpreter
        that never shuts down.
        """
        stdout = self.process.stdout
        try:
            while True:
                chunk = await stdout.read(READ_CHUNK)
                if not chunk:
                    break
                self.adapter.feed(chunk.decode("utf-8", "replace"))
                await self._flush()
                await self._pending_turn()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a broken pipe ends the session, never the API
            log.warning("the Steward session's stream failed", exc_info=True)
        if self.adapter is not None:
            self.adapter.eof()
        with contextlib.suppress(Exception):
            self.exit_code = int(await asyncio.wait_for(self.process.wait(), EXIT_WAIT_S))
        self._finish_exit()

    async def _drain_stderr(self) -> None:
        """The harness's own complaints, into the service log and nowhere else."""
        stderr = self.process.stderr
        if stderr is None:
            return
        with contextlib.suppress(Exception):
            while True:
                line = await stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", "replace").strip()
                if text:
                    log.info("%s: %s", self.manifest.display_label, text[:500])

    def _finish_exit(self) -> None:
        if self.exited:
            return
        self.exited = True
        self._emit([SessionExited(exit_code=int(self.exit_code or 0))])

    async def _pending_turn(self) -> None:
        """A turn just ended and something is waiting: send it now, in the order it arrived."""
        if not self._queued or self.adapter.busy or self.exited:
            return
        text = self._queued.pop(0)
        self.adapter.user_turn(text)
        await self._flush()

    # ── what the route calls ─────────────────────────────────────────────────────────────

    async def send_user_turn(self, text: str) -> bool:
        """Record the Owner's turn, then hand it to the harness. True when it was QUEUED.

        Recording first is the mechanism ruling 13 rests on: `pkc owner say` runs INSIDE the
        turn it is quoting, so a transcript written after the harness saw the text would be
        one turn behind exactly when it is read.
        """
        await self.turns.append(self.user_id, self.session_id, text)
        self.last_active = time.monotonic()
        if self.exited:
            self._emit([Notice(code="session_exited", detail="the harness is not running")])
            return False
        if self.adapter.busy:
            self._queued.append(text)
            self._emit([Notice(code=QUEUED, detail=text[:200])])
            return True
        self.adapter.user_turn(text)
        await self._flush()
        return False

    def attach(self) -> asyncio.Queue:
        """Subscribe one socket. Cancels the idle clock: somebody is watching again."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self.subscribers.add(queue)
        self.last_active = time.monotonic()
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        return queue

    def detach(self, queue: asyncio.Queue) -> None:
        """Unsubscribe, and start the idle clock when the last socket goes."""
        self.subscribers.discard(queue)
        self.last_active = time.monotonic()
        if self.subscribers or self.exited:
            return
        self._idle_task = asyncio.create_task(self._expire())

    async def _expire(self) -> None:
        try:
            if self.idle_s > 0:
                await asyncio.sleep(self.idle_s)
            if self.subscribers:
                return
            log.info(
                "the Steward session for %s went idle for %.0fs; reaping it",
                self.user_id,
                self.idle_s,
            )
            await self.close(detail="idle")
        except asyncio.CancelledError:
            pass

    def snapshot(self) -> list[dict[str, Any]]:
        """Everything a reconnecting tab needs to repaint, bounded by `SNAPSHOT_LIMIT`."""
        return [event.payload() for event in self.events]

    async def close(self, *, detail: str = "") -> None:
        """End the session: reap the group, drop the transcript, drop the config home."""
        self.exited = True
        if self.process is not None:
            with contextlib.suppress(Exception):
                await terminate_group(self.process, grace_s=KILL_AFTER_S)
            if self.exit_code is None:
                self.exit_code = getattr(self.process, "returncode", None)
        for task in list(self._tasks):
            task.cancel()
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        # The conversation is the harness's, not the library's: when the session is over the
        # transcript is over with it (ruling 13).
        with contextlib.suppress(Exception):
            await self.turns.clear(self.user_id, self.session_id)
        if self._config_home:
            shutil.rmtree(self._config_home, ignore_errors=True)
            self._config_home = ""
        self._emit([SessionExited(exit_code=int(self.exit_code or 0), detail=detail)])

    # ── broadcasting ─────────────────────────────────────────────────────────────────────

    def _emit(self, events: Iterable[StewardEvent]) -> None:
        for event in events:
            if isinstance(event, SessionExited) and any(
                isinstance(e, SessionExited) for e in self.events
            ):
                continue
            self.events.append(event)
            if isinstance(event, (TurnFinished, SessionStarted)):
                self.last_active = time.monotonic()
            frame = event.payload()
            for queue in list(self.subscribers):
                try:
                    queue.put_nowait(frame)
                except asyncio.QueueFull:
                    # A socket that cannot keep up loses its oldest frame rather than
                    # stalling the harness everybody else is watching.
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(frame)


@dataclass
class StewardSessions:
    """Every live Steward session in this API process, one per Owner.

    Held in the API process exactly as the live-context socket holds its run: the library's
    authority is still Postgres and canonical, and what is here is a handle to a process.
    """

    sessions: dict[str, StewardSession] = field(default_factory=dict)

    def get(self, user_id: UserId | str) -> StewardSession | None:
        return self.sessions.get(str(user_id))

    async def open(
        self,
        user_id: UserId,
        *,
        manifest: BackendManifest,
        project_dir: str,
        idle_s: float,
        turn_store: Any = None,
        model: str = "",
        spawn: Any = None,
        restart: bool = False,
    ) -> StewardSession:
        """The session for this Owner, joining a live one or starting a new one.

        A session whose harness DIED is not silently replaced: it is handed back as it is, so
        the console can show the exit and offer a fresh start, and only an explicit `restart`
        (the Owner pressing that button) removes it.
        """
        existing = self.sessions.get(str(user_id))
        if existing is not None and not restart:
            # Live: two tabs watch one conversation. Dead: handed back as it is, so the
            # console shows the exit and offers a fresh start instead of getting one silently.
            return existing
        if existing is not None:
            await existing.close(detail="restarted")
            self.sessions.pop(str(user_id), None)
        session = StewardSession(
            user_id=user_id,
            manifest=manifest,
            project_dir=project_dir,
            turns=PairedStewardTurnStore(
                memory=InMemoryStewardTurnStore(), durable=turn_store
            ),
            model=model,
            idle_s=idle_s,
            spawn=spawn,
        )
        self.sessions[str(user_id)] = session
        await session.start()
        return session

    async def end(self, user_id: UserId | str, *, detail: str = "") -> None:
        session = self.sessions.pop(str(user_id), None)
        if session is not None:
            await session.close(detail=detail)

    async def aclose(self) -> None:
        """API shutdown: no harness outlives the process that owns it."""
        for user_id in list(self.sessions):
            await self.end(user_id, detail="shutdown")


__all__ = [
    "CONFIG_HOME_PREFIX",
    "NoCodingAgent",
    "SNAPSHOT_LIMIT",
    "StewardSession",
    "StewardSessions",
]
