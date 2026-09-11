"""Two lanes against real Postgres: they claim at once, and each is still serial.

PG-TIER ON PURPOSE. The whole mechanism is SQL — three predicates narrowed by one array
parameter in two polarities, two advisory locks keyed by lane, and one skip that walks a
compile's `source_ids` looking for a queued index or episodes job. The in-memory queue re-implements
all of it in Python and would pass whether or not the SQL was ever written; only a real
database says whether the correlated subqueries resolve, whether `jsonb_array_elements_text`
is asked the right question, and whether two lanes actually run at the same time rather than
waiting on one lock — which the last test drives through the worker's own `drain_user`.
"""

from __future__ import annotations

import asyncio
import uuid

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.postgres import PostgresDraftStore
from pneuma_knowledge_service.job_lanes import CANONICAL_LANE, DERIVED_LANE


def _user(tag: str) -> UserId:
    return UserId(f"u-it-lane-{tag}-{uuid.uuid4().hex[:8]}")


async def test_one_canonical_job_and_one_derived_job_are_in_flight_at_once(pg_store):
    user = _user("both")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "index", {"source_id": "s2"})
    await pg_store.enqueue(user, "groom", {"path": "p"})
    await pg_store.enqueue(user, "recall_projection", {"source_id": "c1"})

    writer = await pg_store.claim_next(user, lane=CANONICAL_LANE)
    derived = await pg_store.claim_next(user, lane=DERIVED_LANE)
    assert (writer.kind, derived.kind) == ("compile", "index")
    assert await pg_store.claim_next(user, lane=CANONICAL_LANE) is None
    assert await pg_store.claim_next(user, lane=DERIVED_LANE) is None
    # A claim that names no lane is about the whole tenant, as every ops path still means it.
    assert await pg_store.claim_next(user) is None


async def test_the_two_lanes_claim_concurrently_rather_than_serializing_on_one_lock(pg_store):
    """Both claims issued at the same moment: with one lock per tenant the second would wait
    for the first, and with one lock per lane neither waits."""
    user = _user("race")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "index", {"source_id": "s2"})
    first, second = await asyncio.gather(
        pg_store.claim_next(user, lane=CANONICAL_LANE),
        pg_store.claim_next(user, lane=DERIVED_LANE),
    )
    assert {first.kind, second.kind} == {"compile", "index"}


async def test_two_claimers_of_one_lane_hand_out_one_job(pg_store):
    user = _user("same")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "groom", {"path": "p"})
    both = await asyncio.gather(
        pg_store.claim_next(user, lane=CANONICAL_LANE),
        pg_store.claim_next(user, lane=CANONICAL_LANE),
    )
    assert len([job for job in both if job is not None]) == 1, "two writers in one lane"


async def test_a_draft_reserves_its_own_lane_and_not_the_other(pg_store):
    user = _user("draft")
    drafts = PostgresDraftStore(pg_store)
    episodes = await pg_store.enqueue(user, "episodes", {"source_id": "s-draft"})
    executor = "worker:codex:lane-test"
    assert await pg_store.claim(user, episodes, claimed_by=executor) is not None
    await drafts.put(
        user, episodes,
        {"kind": "episodes", "session": {"executor": executor, "kind": "episodes"}},
    )
    await pg_store.enqueue(user, "compile", {"source_ids": ["s-other"]})
    # A different source: a compile also waits for the derived lane's work on its OWN
    # sources (`test_a_compile_waits_for_its_own_sources_index_job_too`).
    await pg_store.enqueue(user, "index", {"source_id": "s-third"})

    claimed = await pg_store.claim_next(user, lane=CANONICAL_LANE)
    assert claimed is not None and claimed.kind == "compile"
    assert await pg_store.claim_next(user, lane=DERIVED_LANE) is None, (
        "the episodes draft must still reserve the derived lane"
    )
    assert await pg_store.attach_executor(user, claimed.job_id, "worker:codex:other") is True
    await drafts.delete(user, episodes, executor=executor)


async def test_a_compile_waits_for_its_own_sources_index_job_too(pg_store):
    """The index job is what commissions the episodes judgement, so a compile that waited
    only for a queued episodes job would overtake the index job of its own source."""
    user = _user("indexgate")
    await pg_store.enqueue(user, "index", {"source_id": "s1"})
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    assert await pg_store.claim_next(user, lane=CANONICAL_LANE) is None
    index = await pg_store.claim_next(user, lane=DERIVED_LANE)
    assert index.kind == "index"
    await pg_store.complete(user, index.job_id, ok=True, detail="indexed")
    assert (await pg_store.claim_next(user, lane=CANONICAL_LANE)).kind == "compile"


async def test_a_compile_whose_source_still_has_an_episodes_job_is_skipped(pg_store):
    user = _user("gate")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "compile", {"source_ids": ["s2"]})
    await pg_store.enqueue(user, "episodes", {"source_id": "s1"})

    second = await pg_store.claim_next(user, lane=CANONICAL_LANE)
    assert second.payload["source_ids"] == ["s2"], "a compile overtook its own episodes job"
    await pg_store.complete(user, second.job_id, ok=True, detail="done")

    judgement = await pg_store.claim_next(user, lane=DERIVED_LANE)
    assert judgement.kind == "episodes"
    assert await pg_store.claim_next(user, lane=CANONICAL_LANE) is None, (
        "the lane must idle until the derived lane clears the judgement"
    )
    await pg_store.complete(user, judgement.job_id, ok=True, detail="done")
    first = await pg_store.claim_next(user, lane=CANONICAL_LANE)
    assert first.payload["source_ids"] == ["s1"]


async def test_a_compile_payload_without_source_ids_blocks_on_nothing(pg_store):
    """The skip is total: a payload that names no source cannot raise out of the query."""
    user = _user("nosources")
    await pg_store.enqueue(user, "compile", {})
    await pg_store.enqueue(user, "episodes", {"source_id": "s1"})
    claimed = await pg_store.claim_next(user, lane=CANONICAL_LANE)
    assert claimed is not None and claimed.kind == "compile"


async def test_the_worker_drains_both_lanes_at_once_against_real_postgres(
    pg_store, settings, monkeypatch
):
    """Two `drain_user` loops, one per lane, over one tenant's queue on the real database:
    both jobs are in flight at the same moment, and each lane drains its own rest."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pneuma_knowledge_service.wiring import executor_for
    from pneuma_knowledge_service.workers import compile_worker

    user = _user("drain")
    queued = [
        await pg_store.enqueue(user, "index", {"source_id": "s1"}),
        await pg_store.enqueue(user, "groom", {"path": "p"}),
        await pg_store.enqueue(user, "index", {"source_id": "s2"}),
        await pg_store.enqueue(user, "archive", {"proposal_id": "a"}),
    ]
    both = asyncio.Event()
    live: set[str] = set()
    peak = 0

    async def body(ctx, user_id, job):  # noqa: ANN001
        nonlocal peak
        live.add(job.kind)
        peak = max(peak, len(live))
        if len(live) == 2:
            both.set()
        # Wait for the other lane, but never longer than the test: a lane that cannot get
        # its own slot must still drain, and the assertion below is what says it did.
        try:
            await asyncio.wait_for(both.wait(), timeout=10)
        except TimeoutError:
            pass
        live.discard(job.kind)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="done")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    monkeypatch.setattr(compile_worker, "run_groom_job", body)
    monkeypatch.setattr(compile_worker, "run_archive_job", body)
    config = settings.model_copy(update={
        "worker_tenants": str(user),
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
    })
    ctx = SimpleNamespace(
        settings=config, store=pg_store, vectors=None, lexical=None, media=None,
        compile_executor=executor_for(config, "compile"), flush_traces=AsyncMock(),
    )
    counts = await asyncio.gather(
        compile_worker.drain_user(ctx, None, None, user, lane=CANONICAL_LANE),
        compile_worker.drain_user(ctx, None, None, user, lane=DERIVED_LANE),
    )
    assert peak == 2, "the two lanes never had a job in flight at the same time"
    assert sorted(counts) == [2, 2]
    rows = {r["job_id"]: r["status"] for r in await pg_store.list_jobs(user)}
    assert all(rows[job_id] == "done" for job_id in queued)


async def test_the_self_heal_reclaims_across_both_lanes(pg_store):
    user = _user("heal")
    canonical = await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    derived = await pg_store.enqueue(user, "index", {"source_id": "s2"})
    assert await pg_store.claim_next(user, lane=CANONICAL_LANE) is not None
    assert await pg_store.claim_next(user, lane=DERIVED_LANE) is not None
    assert await pg_store.requeue_claimed_jobs(draft_ttl=3600, tenants=(str(user),)) == 2
    rows = {r["job_id"]: r["status"] for r in await pg_store.list_jobs(user)}
    assert rows[canonical] == "queued" and rows[derived] == "queued"
