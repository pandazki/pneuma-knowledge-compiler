"""`not_before` against real Postgres — the wait that is a row rather than a sleeping worker.

PG-TIER ON PURPOSE. The whole mechanism is one predicate inside the claim query and one
column that has to exist on a database created before it. Neither is visible to the in-memory
queue: a dict comparison in Python would pass whether or not the SQL was ever written, and an
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` that was never applied only fails here.

What it protects: a job whose harness could not run must come back and must not come back
immediately. Expressed on the row, nothing sleeps, nothing holds a claim while it waits, and
a restarted process reads exactly the answer the process that wrote it would have.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pneuma_knowledge_core.domain.ids import UserId

from test_pg import _normalized  # noqa: E402 — the same L0 fixture the PG store tests use


async def test_a_job_asked_to_wait_is_not_handed_out_until_it_may_be(pg_store):
    user = UserId(f"u-it-delay-{uuid.uuid4().hex[:8]}")
    later = datetime.now(timezone.utc) + timedelta(hours=6)
    held = await pg_store.enqueue(
        user, "compile", {"source_ids": ["s-1"], "cooling_reason": "codex usage limit"},
        not_before=later,
    )
    assert await pg_store.claim_next(user) is None, "a job on ice was handed out"

    # …and a job with no `not_before` at all is claimed exactly as it always was, including
    # every row written before the column existed.
    now_id = await pg_store.enqueue(user, "index", {"source_id": "s-1"})
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == now_id
    await pg_store.complete(user, now_id, ok=True, detail="indexed")

    # The deadline passing is the whole of what changes: the same row, now claimable.
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_jobs SET not_before = %s WHERE id = %s", (past, held)
        )
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == held


async def test_the_cooling_window_is_read_from_the_rows_and_not_from_any_process(pg_store):
    """The API that answers "why is nothing moving" is not the worker that stopped. So the
    answer lives where both can see it: the earliest queued job that is still waiting, and
    the reason the worker wrote into its payload."""
    user = UserId(f"u-it-cool-{uuid.uuid4().hex[:8]}")
    assert await pg_store.queue_cooling(user) is None

    later = (datetime.now(timezone.utc) + timedelta(hours=6)).replace(microsecond=0)
    soonest = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    await pg_store.enqueue(user, "compile", {"cooling_reason": "codex usage limit"},
                           not_before=later)
    await pg_store.enqueue(user, "episodes", {"cooling_reason": "codex at capacity"},
                           not_before=soonest)

    until, reason = await pg_store.queue_cooling(user)
    assert until == soonest, "the window ends when the FIRST job may run, not the last"
    assert reason == "codex at capacity"


async def test_digestion_can_be_withdrawn_for_material_no_round_actually_compiled(pg_store):
    """`mark_undigested` is the inverse `pkc jobs requeue` needs: a stamp that says canonical
    holds this material, made by a round that wrote nothing, has to come off with the job."""
    user = UserId(f"u-it-undigest-{uuid.uuid4().hex[:8]}")
    tag = uuid.uuid4().hex[:8]
    source_id = await pg_store.add(user, _normalized(user, f"sid-{tag}", f"chk-{tag}"))
    await pg_store.mark_digested(user, [str(source_id)], datetime.now(timezone.utc))
    assert (await pg_store.digested_map(user, [str(source_id)]))[str(source_id)] is not None

    await pg_store.mark_undigested(user, [str(source_id)])
    assert (await pg_store.digested_map(user, [str(source_id)]))[str(source_id)] is None
