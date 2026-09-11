"""A round that did not really run is never reported as success, and a round a dead process
left behind is continued rather than thrown away.

One real job's life, the night this was written: launch 1 wrote a real draft (36 of 40
calls, 35 documents), Postgres crashed and took the engine down, the startup self-heal
requeued the job and DISCARDED that draft, the next round timed out at 600 s, the worker's
finish committed nothing — and the job was recorded `ok=True`, `projection:{…"upserted":0…};
rounds:1`, its source stamped digested. Success reported, nothing written.

Both halves are pinned here over the same doubles `test_agent_round.py` runs on: the launcher
is a double that types real `pkc draft` commands, the stores are the in-memory ones. The
kept-draft rules against real Postgres are in `test_draft_ownership.py`, which the PG tier
re-runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.cli import draft as draft_cmd
from pneuma_knowledge_service.coding_agent import round_runner
from pneuma_knowledge_service.coding_agent.launcher import LaunchResult
from pneuma_knowledge_service.coding_agent.round_runner import (
    COMMITTED_BY_HARNESS,
    FINISHED_BY_WORKER,
    ROUND_INCOMPLETE,
    AgentRoundResult,
)
from pneuma_knowledge_service.workers import compile_worker

from test_agent_round import FakeHarness, WorkerCtx, runner, worker_settings
from test_draft_cli import CALLS, PERSON, harness, source

INCOMPLETE = "round_incomplete: timed out; nothing was committed"


def timed_out() -> LaunchResult:
    return LaunchResult(exit_code=-1, stdout="", stderr="", timed_out=True)


def killed() -> LaunchResult:
    return LaunchResult(exit_code=137, stdout="", stderr="Killed")


async def _persisting(h) -> list[str]:  # noqa: ANN001
    """The runtime's `persist`, recorded: it is what digests sources and completes the job
    on a finish, so a round that must not be recorded as done must never reach it."""
    persisted: list[str] = []

    async def persist(job, result):  # noqa: ANN001
        persisted.append(result.status)
        await draft_cmd.complete_job(h.rt, job.job_id, result)

    h.rt.persist = persist
    return persisted


# ─────────────────────────────────────────── (a) a round that did not run to its end


@pytest.mark.parametrize("launch,why", [(timed_out, "timed out"), (killed, "exit 137")])
async def test_a_round_that_ended_badly_and_committed_nothing_is_not_a_success(
    tmp_path, launch, why
):
    h = await harness([source()])
    persisted = await _persisting(h)
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    # The harness read, then ran out of time (or was killed) before it wrote anything.
    fake = FakeHarness(h.rt, [[("list_documents", {})]], result=launch)
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == ROUND_INCOMPLETE
    assert result.incomplete == why
    assert persisted == [], "a round that never reached its end was recorded — and digested"
    assert h.store.commits == []
    assert h.jobs.completed == [], "the runner ended the job; that is the worker's to do"
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None
    assert (await h.jobs.get_job(h.rt.user_id, h.job_id)).status == "claimed"


async def test_a_clean_round_that_found_nothing_to_record_is_still_an_empty_round(tmp_path):
    """Exit 0 and no writes is a harness that read the material and decided: a judgement,
    recorded as it always was."""
    h = await harness([source()])
    persisted = await _persisting(h)
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[("list_documents", {})]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == FINISHED_BY_WORKER
    assert persisted == ["noop"]
    assert h.jobs.completed[-1]["ok"] is True


async def test_a_round_that_timed_out_after_writing_is_judged_on_what_it_wrote(tmp_path):
    """The rule is about a round that committed NOTHING. Work that was typed before the
    clock ran out goes to the gate exactly as before."""
    h = await harness([source()])
    persisted = await _persisting(h)
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS]], result=timed_out)
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == FINISHED_BY_WORKER
    assert persisted == ["committed"] and len(h.store.commits) == 1


async def _claimed(jobs, user, executor):  # noqa: ANN001
    job_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})
    job = await jobs.claim(user, job_id)
    assert job is not None and await jobs.attach_executor(user, job_id, executor)
    return job


async def test_the_worker_fails_an_incomplete_round_and_brings_the_work_back():
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    jobs.mark_digested = AsyncMock()
    ctx = WorkerCtx(worker_settings(agent_retries=3), jobs)
    job = await _claimed(jobs, user, "worker:codex:0001")
    result = AgentRoundResult(
        job_id=job.job_id, outcome=ROUND_INCOMPLETE, timed_out=True, exit_code=-1,
        incomplete="timed out",
    )
    await compile_worker._round_incomplete(ctx, user, job, result, executor="worker:codex:0001")

    done = jobs.completed[-1]
    assert done["job_id"] == job.job_id and done["ok"] is False
    assert done["detail"] == INCOMPLETE
    assert done["snapshot_ref"] is None
    jobs.mark_digested.assert_not_awaited()
    (queued,) = [r for r in await jobs.list_jobs(user) if r["status"] == "queued"]
    assert queued["payload"]["source_ids"] == ["src-01"]
    assert queued["payload"]["harness_failures"] == 1
    assert queued["not_before"] is None
    assert await jobs.claim_next(user) is not None


async def test_an_incomplete_round_stops_coming_back_after_the_bound():
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    ctx = WorkerCtx(worker_settings(agent_retries=3), jobs)
    job_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})
    details: list[str] = []
    while job_id is not None:
        job = await jobs.claim(user, job_id)
        executor = f"worker:codex:{len(details)}"
        assert await jobs.attach_executor(user, job_id, executor)
        result = AgentRoundResult(job_id=job_id, outcome=ROUND_INCOMPLETE, incomplete="exit 137")
        await compile_worker._round_incomplete(ctx, user, job, result, executor=executor)
        details.append(jobs.completed[-1]["detail"])
        queued = [r for r in await jobs.list_jobs(user) if r["status"] == "queued"]
        job_id = queued[0]["job_id"] if queued else None

    assert details == ["round_incomplete: exit 137; nothing was committed"] * 3
    assert [r["status"] for r in await jobs.list_jobs(user)] == ["done"] * 3


async def test_the_unattended_job_records_an_incomplete_round_as_a_failure(monkeypatch):
    """`process_agent_job`'s own branch: the runner said the round did not reach its end."""
    from pneuma_knowledge_service.cli import runtime as runtime_module

    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    jobs.mark_digested = AsyncMock()
    ctx = WorkerCtx(worker_settings(agent_retries=3), jobs)
    job_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})
    job = await jobs.claim(user, job_id)

    async def run_job(self, rt, jid):  # noqa: ANN001
        self.executor = "worker:codex:0002"
        assert await jobs.attach_executor(user, jid, self.executor)
        return AgentRoundResult(
            job_id=jid, outcome=ROUND_INCOMPLETE, timed_out=True, exit_code=-1,
            incomplete="timed out",
        )

    monkeypatch.setattr(compile_worker, "ensure_skill_package", AsyncMock())
    monkeypatch.setattr(runtime_module, "build_runtime", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(round_runner.AgentRoundRunner, "run_job", run_job)
    await compile_worker.process_agent_job(ctx, user, job)

    assert jobs.completed[-1]["job_id"] == job_id
    assert jobs.completed[-1]["ok"] is False
    assert jobs.completed[-1]["detail"] == INCOMPLETE
    jobs.mark_digested.assert_not_awaited()
    assert [r["status"] for r in await jobs.list_jobs(user)] == ["queued", "done"]


# ─────────────────────────────────────── (b) a crashed launch's round is continued


async def test_a_round_left_by_a_crashed_launch_is_finished_by_the_next_one(tmp_path):
    """The draft is in Postgres precisely so it survives the process that wrote it. The
    self-heal keeps it with the requeued job; the next launch adopts it, sees every call the
    dead one spent, and ends the round — here by finishing it, and the commit holds the dead
    launch's writes."""
    h = await harness([source()])
    rt = h.rt
    dead = "worker:codex:synthetic-crashed-launch"
    rt.draft_executor, rt.worker_posture = dead, "unattended"
    async with h.drafts.launch(rt.user_id, dead):
        assert await draft_cmd.cmd_open(rt, h.job_id) == 0
        for name, args in CALLS:
            assert await draft_cmd.run_tool(rt, name, args) == 0
    spent = (await h.drafts.get(rt.user_id, h.job_id))["session"]["spent"]
    assert spent > 0

    assert await h.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 1
    assert (await h.jobs.claim_next(rt.user_id)).job_id == h.job_id

    seen: list[int] = []

    async def look(current):  # noqa: ANN001
        seen.append((await h.drafts.get(current.user_id, h.job_id))["session"]["spent"])

    fake = FakeHarness(rt, [[look, "finish"]])
    result = await runner(fake, tmp_path).run_job(rt, h.job_id)

    assert result.outcome == COMMITTED_BY_HARNESS
    assert seen == [spent], "the next launch did not see the round as the dead one left it"
    assert len(h.store.commits) == 1
    assert any(PERSON in str(commit) for commit in h.store.commits)
    assert "continuing the round" in rt.err.getvalue()
