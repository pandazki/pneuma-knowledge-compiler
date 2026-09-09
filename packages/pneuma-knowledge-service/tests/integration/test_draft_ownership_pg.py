"""Run the ownership scenarios against real PG locks, timestamps and queue transitions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.ports.draft_store import DraftOwnershipError
from pneuma_knowledge_service.adapters.postgres import PostgresDraftStore
from pneuma_knowledge_service.cli import draft

from test_draft_cli import harness
from test_draft_ownership import (  # noqa: F401 — collected again over the PG fixture below
    other,
    test_only_the_same_executor_resumes_and_every_command_checks_ownership,
    test_simultaneous_open_has_one_owner,
    test_takeover_requires_grace_and_records_who_took_it_and_why,
    test_self_heal_spares_a_live_worker_even_past_takeover_grace,
    test_full_ttl_can_expire_a_live_worker_draft,
    test_a_dead_worker_can_be_taken_over_before_grace,
    test_a_finished_job_cannot_be_claimed_reopened_or_overwritten,
    test_the_worker_skips_a_steward_draft_and_logs_once,
    test_worker_return_after_takeover_does_not_finish_the_replacement,
    test_worker_return_after_finish_does_not_touch_the_next_job,
    test_live_launch_is_protected_between_attaching_and_opening_its_draft,
    test_recovery_drops_a_terminal_jobs_leftover_draft_without_reopening_it,
    test_disabled_ttl_removes_a_legacy_draft_when_requeuing_its_job,
    test_worker_failure_drops_its_own_draft_and_releases_the_tenant,
    test_a_late_launch_cannot_supply_a_replacements_finished_version_brief,
)


@pytest.fixture
async def owned(pg_store, user):
    h = await harness([])
    rt = h.rt
    rt.user_id, rt.jobs, rt.drafts = user, pg_store, PostgresDraftStore(pg_store)
    rt.draft_executor, rt.worker_posture = "steward:session-a", "interactive"
    rt.compile_draft_ttl = 3600
    job_id = await pg_store.enqueue(user, "compile", {"source_ids": []})

    async def age(seconds):
        async with pg_store._pool.connection() as conn:
            await conn.execute(
                "UPDATE compile_drafts SET updated_at = now() - make_interval(secs => %s) "
                "WHERE user_id = %s AND job_id = %s", (float(seconds), str(user), job_id),
            )

    return SimpleNamespace(rt=rt, job_id=job_id, age=age)


async def test_queue_refuses_a_requeued_row_while_the_steward_still_holds_its_draft(owned):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    # Reproduce a stale recovery decision: the draft itself must reserve the tenant, even
    # when its queue row no longer does. No claim/release cycle may join this draft.
    async with rt.jobs._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_jobs SET status='queued', claimed_at=NULL, claimed_by=NULL "
            "WHERE user_id = %s AND id = %s", (str(rt.user_id), job),
        )
    assert await rt.jobs.claim_next(rt.user_id) is None
    assert await rt.jobs.claim(rt.user_id, job) is None
    assert (await rt.drafts.owner(rt.user_id, job)).executor == rt.draft_executor


async def test_late_completion_records_the_failure_and_completion_blocks_claim(owned):
    """A job can be completed twice: the round's finish writes the real record, and the
    worker's catch-all writes a second one when something AFTER the commit raised. The
    second keeps what the round measured (the usage test pins that) and records the failure
    where an operator looks. What a finished job must never be is re-claimed."""
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    assert await draft.cmd_finish(rt) == 0
    before = (await rt.jobs.list_jobs(rt.user_id))[0]
    await rt.jobs.complete(rt.user_id, job, ok=False, detail="worker error: late")
    after = (await rt.jobs.list_jobs(rt.user_id))[0]
    assert after["ok"] is False and after["detail"].startswith("worker error:")
    assert after["executor"] == before["executor"]
    # Even an old recovery writer changing status alone cannot resurrect a finished job.
    async with rt.jobs._pool.connection() as conn:
        await conn.execute("UPDATE compile_jobs SET status='queued' WHERE user_id = %s AND id = %s",
                           (str(rt.user_id), job))
    assert await rt.jobs.claim(rt.user_id, job) is None
    assert await rt.jobs.claim_next(rt.user_id) is None


async def test_store_rejects_foreign_writes_and_tenant_probes(owned):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    state = await rt.drafts.get(rt.user_id, job)
    impostor = {**state, "session": {**state["session"], "executor": "steward:session-b"}}
    with pytest.raises(DraftOwnershipError, match="steward:session-a"):
        await rt.drafts.put(rt.user_id, job, impostor)
    with pytest.raises(DraftOwnershipError, match="steward:session-a"):
        await rt.drafts.delete(rt.user_id, job, executor="steward:session-b")
    assert await rt.drafts.owner("synthetic-other-tenant", job) is None
    assert await rt.drafts.get(rt.user_id, job) == state


async def test_takeover_and_recovery_cannot_interrupt_a_command_inside_finish(owned):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    await owned.age(400)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = rt.load_bounds

    async def waiting_bounds():
        entered.set()
        await finish.wait()
        return await original()

    rt.load_bounds = waiting_bounds
    command = asyncio.create_task(draft.cmd_finish(rt))
    await asyncio.wait_for(entered.wait(), 5)
    second = replace(other(rt), drafts=PostgresDraftStore(rt.jobs))
    takeover = asyncio.create_task(draft.cmd_abandon(second, take_over=True))
    try:
        await asyncio.sleep(0.05)
        assert not takeover.done()
        # Startup recovery uses a nonblocking lock and leaves a command in flight alone.
        assert await rt.jobs.requeue_claimed_jobs(draft_ttl=1, tenants=[str(rt.user_id)]) == 0
    finally:
        finish.set()
        results = await asyncio.wait_for(asyncio.gather(command, takeover), 5)
    assert results == [0, 1]
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
