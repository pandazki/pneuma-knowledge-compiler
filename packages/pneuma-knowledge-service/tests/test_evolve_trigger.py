"""Passive schema-evolve trigger (schema-evolve §2.1, C5): the post-compile threshold gate,
driven off a fake store (compile_events only, no git / no docker).

Fires only when BOTH the new-doc count (across ALL families — evolve reorganizes the whole
KB, so whole-KB growth is what warrants it, not memory/topics/ growth alone) AND the
new-anchor count clear their thresholds since the last evolve task, and nothing
evolve-shaped is already in flight."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_service.evolve_service import maybe_trigger_evolve
from pneuma_knowledge_service.settings import Settings


class _FakeStore:
    def __init__(self, events, *, tasks=None, jobs=None):
        self._events = events
        self._tasks = tasks or []
        self._jobs = jobs or []
        self.enqueued: list[tuple[str, dict]] = []

    async def list_evolve_tasks(self, user):  # noqa: ARG002
        return self._tasks

    async def list_compile_events(self, user):  # noqa: ARG002
        return self._events

    async def list_jobs(self, user):  # noqa: ARG002
        return self._jobs

    async def enqueue(self, user, kind, payload):  # noqa: ARG002
        self.enqueued.append((kind, payload))
        return "job-x"


def _events(n_docs: int, per_doc: int, family: str = "memory/topics"):
    now = datetime.now(timezone.utc)
    out = []
    for d in range(n_docs):
        for _ in range(per_doc):
            out.append(
                {
                    "type": "claim_added",
                    "path": f"{family}/t{d}.md",
                    "created_at": now,
                }
            )
    return out


def _ctx(store, **over):
    return SimpleNamespace(settings=Settings(**over), store=store)


async def test_fires_when_both_thresholds_cleared():
    store = _FakeStore(_events(5, 6))  # 5 new topic docs, 30 new anchors
    job_id = await maybe_trigger_evolve(_ctx(store), "u-x")
    assert job_id == "job-x"
    assert store.enqueued == [("evolve", {})]


async def test_no_fire_below_doc_threshold():
    store = _FakeStore(_events(4, 10))  # only 4 new docs (40 claims)
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []


async def test_fires_on_non_topic_family_growth():
    # A corpus whose contract files under work/products/ + memory/people/ (zero topics)
    # must be able to trigger: 3 + 2 = 5 new docs, 18 + 12 = 30 new anchors.
    events = _events(3, 6, family="work/products") + _events(
        2, 6, family="memory/people"
    )
    store = _FakeStore(events)
    job_id = await maybe_trigger_evolve(_ctx(store), "u-x")
    assert job_id == "job-x"
    assert store.enqueued == [("evolve", {})]


async def test_no_fire_below_threshold_non_topic_families():
    # Same families, below both bars: 4 docs / 24 anchors — stays silent.
    events = _events(2, 6, family="work/products") + _events(
        2, 6, family="memory/people"
    )
    store = _FakeStore(events)
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []


async def test_no_fire_below_claim_threshold():
    store = _FakeStore(_events(6, 4))  # 6 topic docs but only 24 claims
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []


async def test_no_fire_when_draft_pending():
    store = _FakeStore(_events(5, 6), tasks=[{"status": "draft", "created_at": None}])
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []


async def test_no_fire_when_evolve_job_queued():
    store = _FakeStore(
        _events(5, 6),
        jobs=[{"kind": "evolve", "status": "queued"}],
    )
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []


async def test_auto_trigger_off_never_fires():
    store = _FakeStore(_events(5, 6))
    assert await maybe_trigger_evolve(_ctx(store, evolve_auto_trigger=False), "u-x") is None
    assert store.enqueued == []


async def test_only_window_events_after_last_task_counted():
    now = datetime.now(timezone.utc)
    old = now.replace(year=now.year - 1)
    # A prior evolve task sets the baseline; pre-baseline events must NOT count.
    events = []
    for d in range(5):
        events.append({"type": "claim_added", "path": f"memory/topics/t{d}.md", "created_at": old})
    store = _FakeStore(events, tasks=[{"status": "adopted", "created_at": now}])
    # All 5 topic events predate the last task → nothing in the window → no fire.
    assert await maybe_trigger_evolve(_ctx(store), "u-x") is None
    assert store.enqueued == []
