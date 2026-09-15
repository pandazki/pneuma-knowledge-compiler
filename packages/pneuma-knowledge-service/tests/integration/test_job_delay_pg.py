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


async def test_a_parked_job_keeps_its_row_and_is_held_back_by_the_wait_it_states(pg_store):
    """PG-TIER ON PURPOSE. `park` is one UPDATE whose whole correctness is in its predicates:
    the row goes back to `queued` with the claim dropped, `completed_at` and `ok` untouched
    (so nothing that counts finished work counts it), and it refuses a job that has already
    ended. A Python dict would agree with any of those, written or not."""
    from pneuma_knowledge_service.job_retry import park

    user = UserId(f"u-it-park-{uuid.uuid4().hex[:8]}")
    job_id = await pg_store.enqueue(user, "index", {"source_id": "s-1"})
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == job_id

    parked = await park(
        pg_store, user, job_id, payload=dict(claimed.payload),
        reason="worker error: 402 payment required", claimed_by="worker",
    )
    assert parked.attempts == 1
    (row,) = await pg_store.list_jobs(user)
    assert row["status"] == "queued" and row["completed_at"] is None and row["ok"] is None
    assert row["detail"] == parked.detail
    assert row["payload"]["retry"]["attempts"] == 1 and row["payload"]["source_id"] == "s-1"
    assert await pg_store.claim_next(user) is None, "a job that is waiting was handed out"

    # A job that DID end is never resurrected by a late failure path.
    ended = await pg_store.enqueue(user, "index", {"source_id": "s-2"})
    await pg_store.complete(user, ended, ok=True, detail="indexed")
    await park(pg_store, user, ended, payload={}, reason="too late")
    done = next(r for r in await pg_store.list_jobs(user) if r["job_id"] == ended)
    assert done["status"] == "done" and done["ok"] is True and done["detail"] == "indexed"


async def test_the_summary_counts_four_disjoint_states_and_groups_what_is_waiting(pg_store):
    """The counts and the grouping are SQL — `FILTER (WHERE …)` over `now()`, and a bounded
    read of the waiting rows — so they are pinned where they are written."""
    from pneuma_knowledge_service.job_retry import park

    user = UserId(f"u-it-summary-{uuid.uuid4().hex[:8]}")
    ready = await pg_store.enqueue(user, "index", {"source_id": "s-0"})
    for source, reason in (("s-1", "402 payment required"), ("s-2", "402 payment required"),
                           ("s-3", "codex provider refused")):
        job_id = await pg_store.enqueue(user, "index", {"source_id": source})
        await park(pg_store, user, job_id, payload={}, reason=reason)
    finished = await pg_store.enqueue(user, "index", {"source_id": "s-4"})
    await pg_store.complete(user, finished, ok=False, detail="unknown_kind: …")

    summary = await pg_store.job_summary(user)
    assert summary["queued"] == 1 and summary["claimed"] == 0
    assert summary["failed"] == 1 and summary["succeeded"] == 0
    assert summary["waiting"]["count"] == 3
    assert [(r["reason"], r["count"]) for r in summary["waiting"]["reasons"]] == [
        ("402 payment required", 2), ("codex provider refused", 1),
    ]
    assert all(r["next_retry_at"] > datetime.now(timezone.utc)
               for r in summary["waiting"]["reasons"])

    # And the one row that is claimable right now is the one nothing happened to.
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == ready


async def test_a_job_out_of_schedule_pauses_and_only_a_resume_starts_it_again(pg_store):
    """PG-TIER ON PURPOSE. The pause is a status nothing else in the queue's SQL mentions:
    the claim takes `status = 'queued'` rows and the self-heal requeues `status = 'claimed'`
    ones, so a paused row is invisible to both WITHOUT either of them naming it. That is the
    property worth pinning against the real statements, and it is one a Python dict would
    agree with whether or not the SQL said so."""
    from pneuma_knowledge_service.job_retry import PAUSED_STATUS, RETRY_BACKOFF_S, park

    user = UserId(f"u-it-pause-{uuid.uuid4().hex[:8]}")
    job_id = await pg_store.enqueue(user, "index", {"source_id": "s-1"})
    ready = await pg_store.enqueue(user, "index", {"source_id": "s-2"})
    said = "worker error: 402 payment required"

    for attempt in range(1, len(RETRY_BACKOFF_S) + 2):
        async with pg_store._pool.connection() as conn:
            await conn.execute(
                "UPDATE compile_jobs SET not_before = NULL WHERE id = %s", (job_id,)
            )
        row = next(r for r in await pg_store.list_jobs(user) if r["job_id"] == job_id)
        parked = await park(pg_store, user, job_id, payload=dict(row["payload"]), reason=said)
        assert parked.attempts == attempt

    row = next(r for r in await pg_store.list_jobs(user) if r["job_id"] == job_id)
    assert row["status"] == PAUSED_STATUS and row["not_before"] is None
    assert row["completed_at"] is None and row["ok"] is None, "a pause ended the job"
    assert row["detail"].startswith(f"paused: {said}; 7 attempts over ")
    assert row["payload"]["retry"]["attempts"] == 7

    # Neither the claim nor the self-heal will touch it; the job behind it still drains.
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == ready
    await pg_store.complete(user, ready, ok=True, detail="indexed")
    assert await pg_store.claim_next(user) is None
    assert await pg_store.claim(user, job_id) is None
    assert await pg_store.requeue_claimed_jobs(draft_ttl=0, tenants=(str(user),)) == 0
    still = next(r for r in await pg_store.list_jobs(user) if r["job_id"] == job_id)
    assert still["status"] == PAUSED_STATUS

    # …and the material is not offered to `POST /compile` either: this row IS its compile.
    summary = await pg_store.job_summary(user)
    assert summary["paused"]["count"] == 1 and summary["queued"] == 0
    (reason,) = summary["paused"]["reasons"]
    assert (reason["reason"], reason["count"]) == (said, 1)
    assert reason["since"] is not None

    # One resume, and the schedule starts over.
    assert await pg_store.resume_jobs(user, reason_like="402") == 1
    back = next(r for r in await pg_store.list_jobs(user) if r["job_id"] == job_id)
    assert back["status"] == "queued" and back["not_before"] is None
    assert back["payload"]["retry"]["attempts"] == 0
    assert len(back["payload"]["retry"]["history"]) == 7, "the history was cleared"
    assert back["detail"] == "resumed after 7 attempts"
    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == job_id
