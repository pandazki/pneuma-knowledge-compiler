"""The per-user claim order: derived-only work first, then everything else in queue order.

A sync ingests N sources, and each queues an `index` job and a `compile` job at the same
moment. Under a strict `ORDER BY created_at` the index job of source 40 waited behind 39
compile rounds of ~156 s each: lexical search (I3, unconditional) waited hours behind
compilation, and every `episodes` judgement an index job queued landed behind every compile
already waiting, so nearly every round compiled a source whose semantic episodes did not
exist yet. The claim now ranks by kind (`CLAIM_FIRST_KINDS`) and orders by place
(`COALESCE(order_at, created_at)`), and an index job hands its own place to the episodes
job it queues.

Keyless: the in-memory queue implements the same ORDER BY; the Postgres tier re-checks it
against real SQL (`tests/integration/test_claim_order_pg.py`). The real `process_index_job`
and `_harness_unavailable` are driven in `test_episodes_door.py` and `test_agent_round.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.adapters.postgres import CLAIM_FIRST_KINDS
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import executor_for
from pneuma_knowledge_service.workers import compile_worker

USER = UserId("u-claim-order")


async def _claim_all(jobs: InMemoryJobQueue, user=USER) -> list[tuple[str, str]]:
    """Claim and finish until nothing is claimable: the (kind, source) sequence handed out."""
    order: list[tuple[str, str]] = []
    while (job := await jobs.claim_next(user)) is not None:
        payload = job.payload
        order.append((job.kind, str(payload.get("source_id") or payload["source_ids"][0])))
        await jobs.complete(user, job.job_id, ok=True)
    return order


async def _sync(jobs: InMemoryJobQueue, sources: list[str]) -> None:
    """What `ingest_source` does per source: the index job, then the compile job."""
    for sid in sources:
        await jobs.enqueue(USER, "index", {"source_id": sid})
        await jobs.enqueue(USER, "compile", {"source_ids": [sid]})


def test_the_claim_first_kinds_are_the_derived_only_ones():
    assert set(CLAIM_FIRST_KINDS) == {"index", "recall_projection", "recall_rebuild"}
    for writer in ("compile", "episodes", "evolve", "evolve_adopt", "groom", "archive",
                   "challenge"):
        assert writer not in CLAIM_FIRST_KINDS


async def test_every_index_job_is_claimed_before_any_compile_round():
    jobs = InMemoryJobQueue()
    await _sync(jobs, ["s1", "s2", "s3"])
    assert await _claim_all(jobs) == [
        ("index", "s1"), ("index", "s2"), ("index", "s3"),
        ("compile", "s1"), ("compile", "s2"), ("compile", "s3"),
    ]


async def test_the_recall_projection_kinds_also_go_first():
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "groom", {"source_id": "doc"})
    await jobs.enqueue(USER, "recall_projection", {"source_id": "c1"})
    await jobs.enqueue(USER, "recall_rebuild", {"source_id": "-"})
    assert [kind for kind, _ in await _claim_all(jobs)] == [
        "recall_projection", "recall_rebuild", "compile", "groom",
    ]


async def test_everything_that_is_not_claim_first_stays_fifo():
    """Canonical writers are never reordered among themselves."""
    jobs = InMemoryJobQueue()
    for kind, sid in [("compile", "s1"), ("groom", "g"), ("compile", "s2"),
                      ("archive", "a"), ("evolve_adopt", "e"), ("compile", "s3")]:
        await jobs.enqueue(USER, kind, {"source_id": sid, "source_ids": [sid]})
    assert await _claim_all(jobs) == [
        ("compile", "s1"), ("groom", "g"), ("compile", "s2"),
        ("archive", "a"), ("evolve_adopt", "e"), ("compile", "s3"),
    ]


async def test_an_episodes_job_at_its_index_jobs_place_precedes_that_sources_compile():
    """One source: index → episodes → compile. The episodes job is written AFTER the compile
    (the index job queues it when it runs), and still sorts ahead of it."""
    jobs = InMemoryJobQueue()
    await _sync(jobs, ["s1", "s2"])
    index = await jobs.claim_next(USER)
    assert (index.kind, index.payload["source_id"]) == ("index", "s1")
    await jobs.enqueue(USER, "episodes", {"source_id": "s1"}, order_at=index.order_at)
    await jobs.complete(USER, index.job_id, ok=True)
    assert await _claim_all(jobs) == [
        ("index", "s2"), ("episodes", "s1"), ("compile", "s1"), ("compile", "s2"),
    ]


async def test_an_inherited_place_wins_a_tie_with_a_row_written_at_that_instant():
    """The compile of a source is written after its index job, so it is never EARLIER; if a
    clock ever makes the two equal, the episodes job that inherited the index job's place
    still goes first."""
    jobs = InMemoryJobQueue()
    at = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]}, order_at=None)
    jobs.jobs[-1].order_at = at  # a compile written at exactly the index job's instant
    await jobs.enqueue(USER, "episodes", {"source_id": "s1"}, order_at=at)
    assert [kind for kind, _ in await _claim_all(jobs)] == ["episodes", "compile"]


async def test_a_requeued_job_keeps_its_place_and_not_before_still_gates_it():
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "compile", {"source_ids": ["s2"]})
    first = await jobs.claim_next(USER)
    await jobs.complete(USER, first.job_id, ok=False, detail="harness_failed: exit 1")
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]}, order_at=first.order_at)
    assert await _claim_all(jobs) == [("compile", "s1"), ("compile", "s2")]

    # A retry the provider asked to wait: its place is kept, but it is not claimable yet.
    await jobs.enqueue(USER, "compile", {"source_ids": ["s3"]})
    held = await jobs.claim_next(USER)
    await jobs.complete(USER, held.job_id, ok=False, detail="rate_limited")
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    retry = await jobs.enqueue(USER, "compile", {"source_ids": ["s3"]},
                               not_before=later, order_at=held.order_at)
    await jobs.enqueue(USER, "compile", {"source_ids": ["s4"]})
    assert await _claim_all(jobs) == [("compile", "s4")]
    (await jobs.get_job(USER, retry)).not_before = datetime.now(timezone.utc)
    assert await _claim_all(jobs) == [("compile", "s3")]


async def test_the_rank_does_not_touch_serialization_or_the_kind_filter():
    jobs = InMemoryJobQueue()
    await _sync(jobs, ["s1"])
    compile_first = await jobs.claim_next(USER, exclude_kinds=("index",))
    assert compile_first.kind == "compile"
    assert await jobs.claim_next(USER) is None, "a second job was handed out while one flew"


# ───────────────────────────────────────────── the worker, driven end to end


class _Ctx:
    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


async def test_a_drain_over_two_synced_sources_claims_index_episodes_compile(monkeypatch):
    """The live shape, keyless: an unattended agent executor, two sources synced. Each index
    job queues its source's episodes judgement at its own place, so the claimed sequence is
    both indexes, then each source's episodes ahead of its compile."""
    jobs = InMemoryJobQueue()
    await _sync(jobs, ["s1", "s2"])
    claimed: list[tuple[str, str]] = []

    async def indexed(ctx, user_id, job):  # noqa: ANN001
        sid = job.payload["source_id"]
        claimed.append(("index", sid))
        await ctx.store.enqueue(user_id, "episodes", {"source_id": sid},
                                order_at=getattr(job, "order_at", None))
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    async def agent(ctx, user_id, job):  # noqa: ANN001
        payload = job.payload
        claimed.append((job.kind, payload.get("source_id") or payload["source_ids"][0]))
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="done")

    monkeypatch.setattr(compile_worker, "process_index_job", indexed)
    monkeypatch.setattr(compile_worker, "process_agent_job", agent)
    # These sources are names in a queue, not L0: none is long enough to be windowed.
    from pneuma_knowledge_service.cli import episodes

    async def never_split(*args):  # noqa: ANN001, ANN002
        return None

    monkeypatch.setattr(episodes, "split_oversized", never_split)
    config = Settings(llm_model_compile="agent:codex", agent_unattended=True)
    await compile_worker.drain_user(_Ctx(config, jobs), None, SimpleNamespace(), USER)
    assert claimed == [
        ("index", "s1"), ("index", "s2"),
        ("episodes", "s1"), ("compile", "s1"),
        ("episodes", "s2"), ("compile", "s2"),
    ]

