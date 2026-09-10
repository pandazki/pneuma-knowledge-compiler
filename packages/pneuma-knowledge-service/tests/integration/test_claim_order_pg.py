"""The claim order against real Postgres — rank by kind, then place, never more than one.

PG-TIER ON PURPOSE, for the same reason as `test_job_delay_pg.py`: the whole mechanism is one
ORDER BY inside the claim query and one column (`order_at`) that has to exist on a database
created before it. The in-memory queue re-implements the ordering in Python and would pass
whether or not the SQL was ever written.

What it protects: a sync of N sources queues index1, compile1, index2, compile2, … — and an
index job must not wait a compile round per source it stands behind (I3), nor may the
episodes judgement an index job queues land behind every compile already waiting.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pneuma_knowledge_core.domain.ids import UserId


def _user(tag: str) -> UserId:
    return UserId(f"u-it-claim-{tag}-{uuid.uuid4().hex[:8]}")


async def _claim_all(store, user) -> list[tuple[str, str]]:  # noqa: ANN001
    order: list[tuple[str, str]] = []
    while (job := await store.claim_next(user)) is not None:
        payload = job.payload
        order.append((job.kind, str(payload.get("source_id") or payload["source_ids"][0])))
        await store.complete(user, job.job_id, ok=True, detail="done")
    return order


async def test_index_jobs_are_claimed_ahead_of_compile_rounds_and_compiles_stay_fifo(pg_store):
    user = _user("rank")
    for sid in ("s1", "s2", "s3"):
        await pg_store.enqueue(user, "index", {"source_id": sid})
        await pg_store.enqueue(user, "compile", {"source_ids": [sid]})
    await pg_store.enqueue(user, "recall_projection", {"source_id": "c1"})
    assert await _claim_all(pg_store, user) == [
        ("index", "s1"), ("index", "s2"), ("index", "s3"), ("recall_projection", "c1"),
        ("compile", "s1"), ("compile", "s2"), ("compile", "s3"),
    ]


async def test_an_episodes_job_at_its_index_jobs_place_precedes_that_sources_compile(pg_store):
    user = _user("episodes")
    for sid in ("s1", "s2"):
        await pg_store.enqueue(user, "index", {"source_id": sid})
        await pg_store.enqueue(user, "compile", {"source_ids": [sid]})
    order: list[tuple[str, str]] = []
    while (job := await pg_store.claim_next(user)) is not None:
        payload = job.payload
        order.append((job.kind, str(payload.get("source_id") or payload["source_ids"][0])))
        if job.kind == "index":
            # What `process_index_job` does under an agent executor: the judgement is
            # written NOW, after the compile, at the index job's own place.
            await pg_store.enqueue(user, "episodes", {"source_id": payload["source_id"]},
                                   order_at=job.order_at)
        await pg_store.complete(user, job.job_id, ok=True, detail="done")
    assert order == [
        ("index", "s1"), ("index", "s2"),
        ("episodes", "s1"), ("compile", "s1"),
        ("episodes", "s2"), ("compile", "s2"),
    ]


async def test_an_inherited_place_wins_a_tie_and_created_at_is_never_rewritten(pg_store):
    user = _user("tie")
    compile_id = await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    async with pg_store._pool.connection() as conn:
        at = (await (await conn.execute(
            "SELECT created_at FROM compile_jobs WHERE id = %s", (compile_id,)
        )).fetchone())[0]
    episodes_id = await pg_store.enqueue(user, "episodes", {"source_id": "s1"}, order_at=at)
    assert await _claim_all(pg_store, user) == [("episodes", "s1"), ("compile", "s1")]
    async with pg_store._pool.connection() as conn:
        rows = dict(await (await conn.execute(
            "SELECT id, created_at > %s FROM compile_jobs WHERE id = ANY(%s)",
            (at, [compile_id, episodes_id]),
        )).fetchall())
    assert rows == {compile_id: False, episodes_id: True}, "created_at stays the write record"


async def test_a_requeued_job_keeps_its_place_and_not_before_still_gates_it(pg_store):
    user = _user("requeue")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "compile", {"source_ids": ["s2"]})
    first = await pg_store.claim_next(user)
    await pg_store.complete(user, first.job_id, ok=False, detail="harness_failed: exit 1")
    later = datetime.now(timezone.utc) + timedelta(hours=6)
    retry = await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]},
                                   not_before=later, order_at=first.order_at)
    assert await _claim_all(pg_store, user) == [("compile", "s2")], "a job on ice ran"
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_jobs SET not_before = now() - interval '1 second' WHERE id = %s",
            (retry,),
        )
    claimed = await pg_store.claim_next(user)
    assert claimed.job_id == retry and claimed.order_at == first.order_at


async def test_the_rank_leaves_the_single_claim_and_the_kind_filter_as_they_were(pg_store):
    user = _user("serial")
    await pg_store.enqueue(user, "compile", {"source_ids": ["s1"]})
    await pg_store.enqueue(user, "index", {"source_id": "s1"})
    job = await pg_store.claim_next(user, exclude_kinds=("index",))
    assert job.kind == "compile"
    assert await pg_store.claim_next(user) is None, "a second job flew for one user"
