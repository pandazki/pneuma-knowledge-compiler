"""The bridge: one harness process per Owner, and the six things it owes the console (§5.6).

Two fixtures, on purpose. Most of what a session must get right is about ORDER and
LIFECYCLE — the transcript written before the harness sees the turn, a mid-turn message held
rather than raced, a dead harness reported rather than replaced — and none of that needs a
subprocess, so it runs against a stub process this module drives frame by frame. The last two
tests run the real thing: the fake `codex` and `claude` from `tests/fake_harness/`, speaking
their real interactive wires, spawned by the shipped code exactly as the route spawns them.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.coding_agent.backends import CLAUDE_CODE, CODEX
from pneuma_knowledge_service.coding_agent.launcher import BACKEND_ENV
from pneuma_knowledge_service.coding_agent.steward_session import (
    StewardSession,
    StewardSessions,
)
from pneuma_knowledge_service.coding_agent.steward_turns import (
    SESSION_ENV,
    InMemoryStewardTurnStore,
)

FAKE_DIR = Path(__file__).parent / "fake_harness"
USER = UserId("u-steward")


# ── a process that is not one ──────────────────────────────────────────────────────────────


class StubStdin:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.frames.append(data)

    async def drain(self) -> None:
        return None


class StubProcess:
    """Enough of an asyncio subprocess to drive a session by hand."""

    pid = None

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = StubStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self._exit: asyncio.Future = asyncio.get_event_loop().create_future()
        self.argv: tuple = ()
        self.kwargs: dict = {}

    async def wait(self) -> int:
        return await self._exit

    def say(self, frame: dict) -> None:
        self.stdout.feed_data((json.dumps(frame) + "\n").encode("utf-8"))

    def die(self, code: int = 0) -> None:
        self.returncode = code
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        if not self._exit.done():
            self._exit.set_result(code)

    def sent(self) -> list[dict]:
        return [json.loads(f.decode("utf-8")) for f in self.stdin.frames]


def stub_spawn(process: StubProcess):
    async def spawn(*argv, **kwargs):
        process.argv = argv
        process.kwargs = kwargs
        return process

    return spawn


async def settle(times: int = 4) -> None:
    """Let the pump task run. The session is event-driven; this is its heartbeat."""
    for _ in range(times):
        await asyncio.sleep(0)


async def open_stub(
    process: StubProcess, *, manifest=CODEX, turns=None, idle_s: float = 60.0
) -> StewardSession:
    from pneuma_knowledge_service.coding_agent.steward_turns import PairedStewardTurnStore

    session = StewardSession(
        user_id=USER,
        manifest=manifest,
        project_dir=os.getcwd(),
        turns=PairedStewardTurnStore(
            memory=InMemoryStewardTurnStore(), durable=turns
        ),
        idle_s=idle_s,
        spawn=stub_spawn(process),
    )
    await session.start()
    await settle()
    return session


async def codex_thread(session: StewardSession, process: StubProcess) -> None:
    """Answer the handshake, so the session has a thread to start turns on."""
    start_id = process.sent()[2]["id"]
    process.say({"id": start_id, "result": {"thread": {"id": "thr-1"}, "model": "gpt-fake"}})
    await settle()


# ── what the session spawns ────────────────────────────────────────────────────────────────


async def test_a_session_runs_the_manifests_interactive_command_in_the_project():
    process = StubProcess()
    session = await open_stub(process, manifest=CLAUDE_CODE)
    try:
        assert list(process.argv[:2]) == ["claude", "--print"]
        assert "--input-format" in process.argv and "stream-json" in process.argv
        # Unattended rounds run in an empty mkdtemp; a console session sits in the PROJECT,
        # because that is where AGENTS.md/CLAUDE.md and the installed skill are.
        assert process.kwargs["cwd"] == str(Path(os.getcwd()).resolve())
        assert process.kwargs["start_new_session"] is True
        env = process.kwargs["env"]
        assert env[BACKEND_ENV] == "claude-code"
        assert env[SESSION_ENV] == session.session_id
        assert env["CLAUDE_CONFIG_DIR"] and env["CLAUDE_CONFIG_DIR"] != os.path.expanduser("~/.claude")
        # A Claude session that finds this set believes it is nested and short-circuits.
        assert "CLAUDECODE" not in env
    finally:
        await session.close()


async def test_the_owner_turn_is_recorded_before_the_harness_sees_it():
    """Ruling 13's whole mechanism: `pkc owner say` runs INSIDE the turn it quotes."""
    process = StubProcess()
    seen: list[int] = []

    class SpyStore(InMemoryStewardTurnStore):
        async def append(self, user_id, session_id, text, seq=None):  # noqa: ANN001
            seen.append(len(process.stdin.frames))
            return await super().append(user_id, session_id, text)

    store = SpyStore()
    session = await open_stub(process, turns=store)
    try:
        await codex_thread(session, process)
        boot = len(process.stdin.frames)
        await session.send_user_turn("Li left the supplier in June")
        await settle()
        assert seen == [boot]  # written BEFORE the turn frame went down the pipe
        assert len(process.stdin.frames) == boot + 1
        assert await store.list(USER, session.session_id) == ["Li left the supplier in June"]
    finally:
        await session.close()


async def test_a_message_sent_mid_turn_is_queued_and_sent_when_the_turn_ends():
    """Never an interrupt and a resend: a protocol race fails explicitly (steer-in §invariants)."""
    process = StubProcess()
    session = await open_stub(process)
    queue = session.attach()
    try:
        await codex_thread(session, process)
        await session.send_user_turn("first")
        await settle()
        sent = len(process.sent())

        queued = await session.send_user_turn("second, while the first runs")
        await settle()
        assert queued is True
        assert len(process.sent()) == sent  # nothing was written into the running turn
        frames = drain(queue)
        assert any(f["type"] == "notice" and f["code"] == "queued" for f in frames)

        process.say({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
        await settle()
        turns = [f for f in process.sent() if f.get("method") == "turn/start"]
        assert [t["params"]["input"][0]["text"] for t in turns] == [
            "first",
            "second, while the first runs",
        ]
    finally:
        await session.close()


def drain(queue: asyncio.Queue) -> list[dict]:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


async def test_a_reconnect_repaints_from_the_snapshot():
    process = StubProcess()
    session = await open_stub(process)
    first = session.attach()
    try:
        await codex_thread(session, process)
        await session.send_user_turn("what came in this week?")
        await settle()
        process.say({"method": "item/agentMessage/delta", "params": {"delta": "two jobs"}})
        await settle()
        seen = [f["type"] for f in drain(first)]
        assert seen == ["session_started", "turn_started", "text_delta"]

        # The tab closes; the session stays up, and a second socket repaints from the tail.
        session.detach(first)
        second = session.attach()
        assert [e["type"] for e in session.snapshot()] == seen
        # Both sockets are one conversation: a new event reaches the one that is attached.
        process.say({"method": "item/agentMessage/delta", "params": {"delta": " so far"}})
        await settle()
        assert [f["type"] for f in drain(second)] == ["text_delta"]
    finally:
        await session.close()


async def test_a_dead_harness_is_reported_and_never_silently_restarted():
    process = StubProcess()
    registry = StewardSessions()
    session = StewardSession(
        user_id=USER,
        manifest=CODEX,
        project_dir=os.getcwd(),
        turns=__import__(
            "pneuma_knowledge_service.coding_agent.steward_turns",
            fromlist=["PairedStewardTurnStore"],
        ).PairedStewardTurnStore(memory=InMemoryStewardTurnStore()),
        spawn=stub_spawn(process),
    )
    registry.sessions[str(USER)] = session
    await session.start()
    await settle()
    queue = session.attach()

    process.die(3)
    await settle(8)
    assert session.exited is True
    assert [f["type"] for f in drain(queue)] == ["session_exited"]

    # A second attach gets the SAME dead session — the console shows the exit and offers a
    # fresh start; nothing restarts behind the Owner's back.
    again = await registry.open(
        USER, manifest=CODEX, project_dir=os.getcwd(), idle_s=60, spawn=stub_spawn(process)
    )
    assert again is session and again.exited

    # …and only an explicit restart makes a new one.
    fresh_process = StubProcess()
    fresh = await registry.open(
        USER,
        manifest=CODEX,
        project_dir=os.getcwd(),
        idle_s=60,
        spawn=stub_spawn(fresh_process),
        restart=True,
    )
    assert fresh is not session and fresh.live
    await registry.aclose()


async def test_an_idle_session_is_reaped_and_its_transcript_goes_with_it():
    process = StubProcess()
    store = InMemoryStewardTurnStore()
    session = await open_stub(process, turns=store, idle_s=0.0)
    queue = session.attach()
    await codex_thread(session, process)
    await session.send_user_turn("something the owner said")
    await settle()
    assert await store.list(USER, session.session_id) == ["something the owner said"]

    session.detach(queue)  # the last tab closed
    await settle(10)
    assert session.exited is True
    # The conversation is the harness's, not the library's: it ends with the session.
    assert await store.list(USER, session.session_id) == []


async def test_shutdown_reaps_every_session_this_process_holds():
    process = StubProcess()
    registry = StewardSessions()
    await registry.open(
        USER,
        manifest=CODEX,
        project_dir=os.getcwd(),
        idle_s=60,
        spawn=stub_spawn(process),
    )
    await settle()
    await registry.aclose()
    assert registry.sessions == {}


async def test_a_second_attach_joins_the_one_session_rather_than_starting_a_second():
    process = StubProcess()
    registry = StewardSessions()
    kwargs = dict(
        manifest=CODEX, project_dir=os.getcwd(), idle_s=60, spawn=stub_spawn(process)
    )
    one = await registry.open(USER, **kwargs)
    two = await registry.open(USER, **kwargs)
    assert one is two
    await registry.aclose()


# ── the real wire, against a harness that is not one ───────────────────────────────────────


@pytest.fixture
def fake_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", f"{FAKE_DIR}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PKC_FAKE_LOG", str(tmp_path / "invocations.jsonl"))
    monkeypatch.delenv("PKC_FAKE_MODE", raising=False)
    monkeypatch.setenv("PKC_FAKE_COMMAND", "pkc draft finish")
    return tmp_path


async def collect(queue: asyncio.Queue, *, until: str, limit: float = 10.0) -> list[dict]:
    """Frames up to and including the one named. A deadline, because a hang is a failure."""
    out: list[dict] = []
    async with asyncio.timeout(limit):
        while True:
            frame = await queue.get()
            out.append(frame)
            if frame["type"] == until:
                return out


@pytest.mark.parametrize("manifest", [CODEX, CLAUDE_CODE], ids=["codex", "claude-code"])
async def test_a_real_process_speaks_its_own_wire_into_the_one_vocabulary(
    fake_path, manifest
):
    registry = StewardSessions()
    session = await registry.open(
        USER, manifest=manifest, project_dir=os.getcwd(), idle_s=60
    )
    queue = session.attach()
    try:
        await session.send_user_turn("what came in this week?")
        frames = await collect(queue, until="turn_finished")
        kinds = [f["type"] for f in frames]
        assert "session_started" in kinds
        assert "step_started" in kinds and "step_finished" in kinds
        assert "text_delta" in kinds
        step = next(f for f in frames if f["type"] == "step_started")
        assert step["command"] == "pkc draft finish"
        end = next(f for f in frames if f["type"] == "turn_finished")
        assert end["usage"]  # both fakes report their own counters
        assert session.agent_session_id
    finally:
        await registry.aclose()


async def test_a_harness_that_will_not_start_is_reported_as_an_exit(fake_path, monkeypatch):
    monkeypatch.setenv("PKC_FAKE_MODE", "fail")
    registry = StewardSessions()
    session = await registry.open(
        USER, manifest=CODEX, project_dir=os.getcwd(), idle_s=60
    )
    queue = session.attach()
    try:
        frames = await collect(queue, until="session_exited")
        assert frames[-1]["exit_code"] == 1
        assert session.live is False
    finally:
        await registry.aclose()
