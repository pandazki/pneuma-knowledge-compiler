"""One executor owns a round, including the race between finish and a late worker return.

The Postgres tier imports these same scenarios with a real queue/draft store fixture.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pneuma_knowledge_service.cli import draft
from pneuma_knowledge_service.coding_agent.backends import CODEX
from pneuma_knowledge_service.coding_agent.launcher import LaunchResult
from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner, AgentRoundOpenRefused
from pneuma_knowledge_service.workers import compile_worker

from test_agent_round import WorkerCtx, worker_settings
from test_draft_cli import harness


@pytest.fixture
async def owned():
    h = await harness([])
    h.rt.draft_executor = "steward:session-a"
    h.rt.worker_posture = "interactive"
    h.rt.compile_draft_ttl = 3600

    async def age(seconds):
        key = (str(h.rt.user_id), h.job_id)
        h.drafts._stamps[key] -= timedelta(seconds=seconds)

    return SimpleNamespace(rt=h.rt, job_id=h.job_id, age=age)


def other(rt):
    return replace(rt, draft_executor="steward:session-b", out=io.StringIO(), err=io.StringIO())


async def test_only_the_same_executor_resumes_and_every_command_checks_ownership(owned):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    state = await rt.drafts.get(rt.user_id, job)
    since = (await rt.drafts.owner(rt.user_id, job)).since
    second = other(rt)
    await owned.age(7)
    assert await draft.cmd_open(second, job) == 2
    message = second.err.getvalue()
    assert "draft held by steward:session-a since " in message
    assert "idle 7s" in message and "abandon --take-over" in message
    assert "worker posture: interactive" in message
    assert await draft.cmd_status(second) == 2
    assert await draft.cmd_check(second) == 2
    assert await draft.run_tool(second, "list_documents", {}) == 2
    assert await draft.cmd_finish(second) == 2
    assert await draft.cmd_abandon(second) == 2
    assert await rt.drafts.get(rt.user_id, job) == state
    assert await draft.cmd_open(rt, job) == 0
    assert (await rt.drafts.owner(rt.user_id, job)).since == since
    assert (await rt.drafts.owner(rt.user_id, job)).idle_seconds == 0


async def test_simultaneous_open_has_one_owner(owned):
    rt, job = owned.rt, owned.job_id
    second = other(rt)
    codes = await asyncio.gather(draft.cmd_open(rt, job), draft.cmd_open(second, job))
    assert sorted(codes) == [0, 2]
    winner = rt if codes[0] == 0 else second
    assert (await rt.drafts.owner(rt.user_id, job)).executor == winner.draft_executor


@pytest.mark.parametrize("ttl,grace", [(30, 60), (3600, 300)])
async def test_takeover_requires_grace_and_records_who_took_it_and_why(owned, ttl, grace):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    second = replace(other(rt), compile_draft_ttl=ttl)
    assert await draft.cmd_abandon(second, take_over=True) == 2
    assert f"within {grace}s grace" in second.err.getvalue()
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"
    await owned.age(grace + 2)
    assert await draft.cmd_abandon(second, take_over=True) == 0
    released = await rt.jobs.get_job(rt.user_id, job)
    assert released.status == "queued"
    audit = released.payload["draft_takeovers"][-1]
    assert audit["executor"] == second.draft_executor
    assert audit["previous_executor"] == rt.draft_executor
    assert "idle" in audit["reason"] and audit["at"]
    assert await rt.drafts.get(rt.user_id, job) is None
    assert await draft.cmd_open(second, job) == 0
    assert await draft.cmd_finish(rt) == 2
    assert await rt.canonical.list(rt.user_id) == []


async def test_self_heal_spares_a_live_worker_even_past_takeover_grace(owned):
    rt, job = owned.rt, owned.job_id
    rt.draft_executor = "worker:codex:synthetic-live-launch"
    rt.worker_posture = "unattended"
    async with rt.drafts.launch(rt.user_id, rt.draft_executor):
        assert await draft.cmd_open(rt, job) == 0
        second = other(rt)
        assert await draft.cmd_open(second, job) == 2
        assert "worker posture: unattended" in second.err.getvalue()
        assert await draft.cmd_abandon(second, take_over=True) == 2
        await owned.age(400)  # More than the takeover grace; less than the full TTL.
        assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 0
        assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"
        assert await rt.drafts.get(rt.user_id, job) is not None
    assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 1
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "queued"
    assert await rt.drafts.get(rt.user_id, job) is None


async def test_full_ttl_can_expire_a_live_worker_draft(owned):
    rt, job = owned.rt, owned.job_id
    rt.draft_executor = "worker:codex:synthetic-expired-launch"
    async with rt.drafts.launch(rt.user_id, rt.draft_executor):
        assert await draft.cmd_open(rt, job) == 0
        await owned.age(3601)
        assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 1
        assert await rt.drafts.get(rt.user_id, job) is None


async def test_a_dead_worker_can_be_taken_over_before_grace(owned):
    rt, job = owned.rt, owned.job_id
    rt.draft_executor = "worker:codex:synthetic-dead-launch"
    async with rt.drafts.launch(rt.user_id, rt.draft_executor):
        assert await draft.cmd_open(rt, job) == 0
    second = other(rt)
    assert await draft.cmd_abandon(second, take_over=True) == 0
    audit = (await rt.jobs.get_job(rt.user_id, job)).payload["draft_takeovers"][-1]
    assert audit["reason"] == "owning worker launch is gone"


async def test_a_finished_job_cannot_be_claimed_reopened_or_overwritten(owned, tmp_path):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    assert await draft.cmd_finish(rt) == 0
    await rt.jobs.release(rt.user_id, job)
    await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)])
    await rt.jobs.complete(rt.user_id, job, ok=False, detail="late worker failure")
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
    assert await rt.jobs.claim(rt.user_id, job) is None
    assert await rt.jobs.claim_next(rt.user_id) is None
    assert (await draft.open_round(rt, job, claim=False))[0] == 2
    assert await rt.drafts.get(rt.user_id, job) is None
    runner = AgentRoundRunner(manifest=CODEX, project_dir=str(tmp_path), timeout_s=1)
    with pytest.raises(AgentRoundOpenRefused):
        await runner.run_job(rt, job)


async def test_the_worker_skips_a_steward_draft_and_logs_once(owned, caplog):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    ctx = WorkerCtx(worker_settings(), rt.jobs)
    compile_worker._DRAFT_HOLD_LOGGED.clear()
    with caplog.at_level("INFO", logger=compile_worker.__name__):
        for _ in range(2):
            assert await compile_worker.drain_user(ctx, None, None, rt.user_id) == 0
    assert caplog.text.count(f"held by {rt.draft_executor}") == 1
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"


async def test_worker_return_after_takeover_does_not_finish_the_replacement(owned, tmp_path):
    rt, job = owned.rt, owned.job_id
    assert await rt.jobs.claim(rt.user_id, job) is not None
    second = other(rt)

    async def launcher(request):
        assert request.env["PKC_DRAFT_EXECUTOR"] == rt.draft_executor
        assert (await rt.drafts.owner(rt.user_id, job)).executor == rt.draft_executor
        await owned.age(400)
        assert await draft.cmd_abandon(second, take_over=True) == 0
        assert await draft.cmd_open(second, job) == 0
        return LaunchResult(exit_code=0, stdout="", stderr="")

    runner = AgentRoundRunner(manifest=CODEX, project_dir=str(tmp_path), timeout_s=1, launcher=launcher)
    result = await runner.run_job(rt, job)
    assert result.outcome == "draft ownership lost"
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"
    assert (await rt.drafts.owner(rt.user_id, job)).executor == second.draft_executor
    await rt.jobs.complete(rt.user_id, job, ok=False, claimed_by=runner.executor)
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"


async def test_worker_return_after_finish_does_not_touch_the_next_job(owned, tmp_path):
    rt, job = owned.rt, owned.job_id
    assert await rt.jobs.claim(rt.user_id, job) is not None
    next_job = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": []})
    second = other(rt)

    async def launcher(request):
        assert await draft.cmd_finish(rt) == 0
        assert await draft.cmd_open(second, next_job) == 0
        return LaunchResult(exit_code=0, stdout="", stderr="")

    runner = AgentRoundRunner(manifest=CODEX, project_dir=str(tmp_path), timeout_s=1, launcher=launcher)
    await runner.run_job(rt, job)
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
    assert (await rt.jobs.get_job(rt.user_id, next_job)).status == "claimed"
    assert (await rt.drafts.owner(rt.user_id, next_job)).executor == second.draft_executor


async def test_live_launch_is_protected_between_attaching_and_opening_its_draft(owned):
    rt, job = owned.rt, owned.job_id
    executor = "worker:codex:synthetic-starting-launch"
    assert await rt.jobs.claim(rt.user_id, job) is not None
    async with rt.drafts.launch(rt.user_id, executor):
        assert await rt.jobs.attach_executor(rt.user_id, job, executor)
        assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 0
        assert (await rt.jobs.get_job(rt.user_id, job)).status == "claimed"
    assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 1


def test_identity_is_stable_per_session_and_explicit_executor_wins(monkeypatch):
    monkeypatch.delenv("PKC_DRAFT_EXECUTOR", raising=False)
    monkeypatch.setenv("PKC_STEWARD_SESSION", "synthetic-thread-a")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH", "synthetic-skill")
    first = draft.draft_executor()
    monkeypatch.setattr(draft.os, "getpid", lambda: 101)
    assert draft.draft_executor() == first
    monkeypatch.setenv("PKC_STEWARD_SESSION", "synthetic-thread-b")
    assert draft.draft_executor() != first
    monkeypatch.setenv("PKC_DRAFT_EXECUTOR", "worker:codex:synthetic-launch")
    assert draft.draft_executor() == "worker:codex:synthetic-launch"
    for key in ("PKC_DRAFT_EXECUTOR", "PKC_STEWARD_SESSION", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(draft.socket, "gethostname", lambda: "synthetic-host")
    # No session token: every `pkc` command is its own process, so the identity must not
    # depend on the pid — a Steward's second command would otherwise be another executor.
    tokenless = draft.draft_executor()
    assert tokenless.startswith("steward:")
    monkeypatch.setattr(draft.os, "getpid", lambda: 202)
    assert draft.draft_executor() == tokenless


async def test_recovery_drops_a_terminal_jobs_leftover_draft_without_reopening_it(owned):
    rt, job = owned.rt, owned.job_id
    assert await draft.cmd_open(rt, job) == 0
    await rt.jobs.complete(rt.user_id, job, ok=False, detail="synthetic worker failure")
    assert await rt.drafts.get(rt.user_id, job) is not None
    assert await rt.jobs.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(rt.user_id)]) == 0
    assert await rt.drafts.get(rt.user_id, job) is None
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
    next_job = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": []})
    assert (await rt.jobs.claim_next(rt.user_id)).job_id == next_job


async def test_disabled_ttl_removes_a_legacy_draft_when_requeuing_its_job(owned):
    rt, job = owned.rt, owned.job_id
    assert await rt.jobs.claim(rt.user_id, job) is not None
    await rt.drafts.put(rt.user_id, job, {"draft": {}, "session": {}})
    assert await rt.jobs.requeue_claimed_jobs(draft_ttl=0, tenants=[str(rt.user_id)]) == 1
    assert await rt.drafts.get(rt.user_id, job) is None
    assert (await rt.jobs.claim_next(rt.user_id)).job_id == job


async def test_worker_failure_drops_its_own_draft_and_releases_the_tenant(owned):
    rt, job = owned.rt, owned.job_id
    rt.draft_executor = "worker:codex:synthetic-failing-launch"
    assert await draft.cmd_open(rt, job) == 0
    error = RuntimeError("synthetic harness failure")
    error.draft_executor, error.draft_runtime = rt.draft_executor, rt
    await compile_worker._fail_job(SimpleNamespace(store=rt.jobs), rt.user_id, job, error, str(error))
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
    assert await rt.drafts.get(rt.user_id, job) is None
    next_job = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": []})
    assert (await rt.jobs.claim_next(rt.user_id)).job_id == next_job


async def test_a_late_launch_cannot_supply_a_replacements_finished_version_brief(owned, tmp_path):
    rt, job = owned.rt, owned.job_id
    assert await rt.jobs.claim(rt.user_id, job) is not None
    second = other(rt)
    briefs = []

    async def record(job_id, text):
        briefs.append((job_id, text))

    rt.record_brief = record

    async def launcher(request):
        await owned.age(400)
        assert await draft.cmd_abandon(second, take_over=True) == 0
        assert await draft.cmd_open(second, job) == 0
        assert await draft.cmd_finish(second) == 0
        return LaunchResult(exit_code=0, stdout="", stderr="", last_message="Old worker narration.")

    runner = AgentRoundRunner(manifest=CODEX, project_dir=str(tmp_path), timeout_s=1, launcher=launcher)
    result = await runner.run_job(rt, job)
    assert result.outcome == "draft ownership lost"
    assert briefs == []
    assert (await rt.jobs.get_job(rt.user_id, job)).claimed_by == second.draft_executor
