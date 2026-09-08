"""Do not enqueue an optional role's job a deployment cannot run.

A keyless personal library under an agent executor (`agent:codex` for compile, no
OPENROUTER_API_KEY) compiles perfectly well: the Steward types the tool calls, and the
compile role never asks for a chat model. Every OTHER role still falls back to the base
model, and evolve is the one that is ENQUEUED — so each threshold crossing put a job on
the queue that died on `openrouter:<model> requires OPENROUTER_API_KEY`. Forty of them,
in one real run, read by the Owner as forty failures of a healthy library.

The guard is asked at the moment of enqueue, mechanically, off the same resolution the
worker would use — and it says so once per process, not once per job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import can_build_chat_model
from pneuma_knowledge_service.workers import compile_worker


# ───────────────────────────────────────────────────────────── the dry resolution


def _settings(key: str, **over) -> Settings:
    """Settings with the key pinned, whatever the environment around the test says.

    `openrouter_api_key` reads an alias (OPENROUTER_API_KEY, no prefix), so it is pinned
    after construction rather than passed in — that also keeps a developer's own `.env`
    out of a test about the keyless state.
    """
    over.setdefault("llm_model", "openrouter:anthropic/claude-sonnet-5")
    base = Settings(**over)
    return base.model_copy(update={"openrouter_api_key": key})


def _keyless_agent(**over) -> Settings:
    """A real deployment shape: compile runs on a coding agent, nobody set a key."""
    return _settings("", llm_model_compile="agent:codex", **over)


def _keyed(**over) -> Settings:
    return _settings("sk-test", **over)


def test_evolve_inherits_the_agent_and_does_not_build_a_chat_model():
    ok, reason = can_build_chat_model(_keyless_agent(), "evolve")
    assert ok is False
    assert "coding-agent executor" in reason


def test_a_key_makes_the_same_role_runnable():
    assert can_build_chat_model(_keyed(), "evolve") == (True, "")


def test_a_role_stating_an_agent_spec_in_its_own_field_is_not_a_chat_model():
    ok, reason = can_build_chat_model(
        _keyed(llm_model_evolve="agent:claude-code"), "evolve"
    )
    assert ok is False
    assert "coding-agent executor" in reason


def test_a_scripted_run_stays_runnable_without_any_key():
    assert can_build_chat_model(_settings("", llm_model="scripted:/x.json"), "evolve")[0]


# ───────────────────────────────────────────────────── the guard at the enqueue point


@dataclass
class _Projection:
    claims: int = 0


class _Store:
    """Just enough queue for `persist_compile_result`'s noop ending plus the evolve trigger."""

    def __init__(self, events):
        self._events = events
        self.enqueued: list[tuple[str, dict]] = []
        self.completed: list[dict] = []

    async def mark_digested(self, user, source_ids, now):  # noqa: ARG002
        return None

    async def record_compile_events(self, user, job_id, ref, events):  # noqa: ARG002
        return None

    async def complete(self, user, job_id, **kw):  # noqa: ARG002
        self.completed.append(kw)

    async def list_evolve_tasks(self, user):  # noqa: ARG002
        return []

    async def list_compile_events(self, user):  # noqa: ARG002
        return self._events

    async def list_jobs(self, user):  # noqa: ARG002
        return []

    async def enqueue(self, user, kind, payload):  # noqa: ARG002
        self.enqueued.append((kind, payload))
        return f"job-{len(self.enqueued)}"


def _cleared_threshold_events(n_docs: int = 5, per_doc: int = 6):
    """Whole-KB growth well past both evolve thresholds (5 new docs, 30 new anchors)."""
    now = datetime.now(timezone.utc)
    return [
        {"type": "claim_added", "path": f"memory/topics/t{d}.md", "created_at": now}
        for d in range(n_docs)
        for _ in range(per_doc)
    ]


def _ctx(settings: Settings, store: _Store):
    return SimpleNamespace(
        settings=settings,
        store=store,
        canonical=SimpleNamespace(
            snapshots_page=_snapshots_page,
        ),
    )


async def _snapshots_page(user, limit=1):  # noqa: ARG001
    return [SimpleNamespace(ref="deadbeef")], None, None


async def _crossing(ctx, *, status: str = "committed"):
    """One compile ending, run through the worker's own post-compile tail.

    `committed` and `noop` are the two endings that ask the evolve question, and both go
    through the same guard.
    """
    now = datetime.now(timezone.utc)
    await compile_worker.persist_compile_result(
        ctx,
        "u-x",
        "job-compile",
        {},
        SimpleNamespace(
            time=SimpleNamespace(now_utc=now),
            sources=[],
            source_ids=["s-1"],
            owner_name="Owner",
        ),
        SimpleNamespace(
            status=status,
            token_usage={},
            events=[],
            files={},
            snapshot=SimpleNamespace(ref="deadbeef"),
            violations=[],
        ),
    )


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test is its own "process" for the once-only rule."""
    monkeypatch.setattr(compile_worker, "_OPTIONAL_ROLE_SKIPPED", set())

    async def _projection(ctx, user, ref):  # noqa: ARG001
        return _Projection()

    async def _rollover(ctx, user, files, paths):  # noqa: ARG001
        return None

    monkeypatch.setattr(compile_worker, "sync_projection", _projection)
    monkeypatch.setattr(compile_worker, "maybe_trigger_rollover", _rollover)


async def test_keyless_api_deployment_enqueues_no_evolve_job(caplog):
    store = _Store(_cleared_threshold_events())
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_settings(""), store))
    assert store.enqueued == []
    lines = [r.getMessage() for r in caplog.records if "skipped" in r.getMessage()]
    assert lines == [
        "[compile-worker] evolve skipped: openrouter:anthropic/claude-sonnet-5 "
        "requires OPENROUTER_API_KEY"
    ]


async def test_the_skip_records_nothing_as_failed():
    store = _Store(_cleared_threshold_events())
    await _crossing(_ctx(_settings(""), store))
    # The compile itself still ends, and it ends OK: a role this deployment cannot run is
    # not the compile's failure.
    assert [c["ok"] for c in store.completed] == [True]


async def test_the_line_is_said_once_across_two_crossings(caplog):
    store = _Store(_cleared_threshold_events())
    ctx = _ctx(_settings(""), store)
    with caplog.at_level(logging.WARNING):
        await _crossing(ctx)
        await _crossing(ctx)
    assert store.enqueued == []
    assert sum("evolve skipped" in r.getMessage() for r in caplog.records) == 1


async def test_a_keyed_deployment_enqueues_exactly_as_before(caplog):
    store = _Store(_cleared_threshold_events())
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_keyed(), store))
    assert store.enqueued == [("evolve", {})]
    assert not [r for r in caplog.records if "skipped" in r.getMessage()]


async def test_the_skipped_crossing_consumes_no_threshold_accounting():
    """The window is measured from the last evolve TASK, and a skip writes none.

    So the increment keeps accruing: the first crossing after a key appears enqueues,
    with the same events that were skipped while the deployment was keyless.
    """
    store = _Store(_cleared_threshold_events())
    await _crossing(_ctx(_settings(""), store))
    assert store.enqueued == []
    await _crossing(_ctx(_keyed(), store))  # a key appeared; nothing else changed
    assert store.enqueued == [("evolve", {})]


async def test_the_noop_ending_is_guarded_too(caplog):
    """The other ending that asks the same question (a retry after a projection failure)."""
    store = _Store(_cleared_threshold_events())
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_settings(""), store), status="noop")
    assert store.enqueued == []
    assert sum("evolve skipped" in r.getMessage() for r in caplog.records) == 1


async def test_the_challenge_job_is_guarded_the_same_way(caplog):
    store = _Store([])
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_keyless_agent(challenge_enabled=True), store))
    assert [k for k, _ in store.enqueued] == []
    assert sum("challenge skipped" in r.getMessage() for r in caplog.records) == 1


async def test_a_keyed_deployment_still_enqueues_the_challenge(caplog):
    store = _Store([])
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_keyed(challenge_enabled=True), store))
    assert [k for k, _ in store.enqueued] == ["challenge"]
    assert not [r for r in caplog.records if "skipped" in r.getMessage()]


@pytest.mark.parametrize("status", ["committed", "noop"])
async def test_a_keyless_agent_enqueues_evolve_without_a_model_key(status, caplog):
    store = _Store(_cleared_threshold_events())
    with caplog.at_level(logging.WARNING):
        await _crossing(_ctx(_keyless_agent(llm_model_evolve=""), store), status=status)
    assert store.enqueued == [("evolve", {})]
    assert not any("evolve skipped" in r.getMessage() for r in caplog.records)
