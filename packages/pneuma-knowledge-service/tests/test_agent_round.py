"""The unattended round: what the worker does when a coding agent is the compile executor.

The launcher is a double here, and that is the point — every branch of the round is a
decision about the DRAFT STORE, not about a subprocess. A launch either left the draft gone
(the harness ran `pkc draft finish`), still open (it stopped), or open in repair (its finish
was refused), and the runner's whole job is that the round ends exactly once whichever it is.
The subprocess itself is tested against fake binaries in `test_agent_launcher.py`.

The double is not a stub: it drives the SAME `pkc draft` functions a harness would type, over
the same in-memory stores, so "the harness wrote two claims and finished" is two real tool
calls and a real gate run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import build_compile_tool_face
from pneuma_knowledge_core.compile.session import DraftSession
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.cli import draft as draft_cmd
from pneuma_knowledge_service.coding_agent.backends import CODEX
from pneuma_knowledge_service.coding_agent.launcher import LaunchRequest, LaunchResult
from pneuma_knowledge_service.coding_agent.round_runner import (
    COMMITTED_BY_HARNESS,
    FINISHED_BY_WORKER,
    HARNESS_UNAVAILABLE,
    REPAIRED,
    AgentRoundOpenRefused,
    AgentRoundRunner,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker

from test_draft_cli import CALLS, PERSON, harness, source  # noqa: E402

USAGE = {"input_tokens": 900, "output_tokens": 250, "total_tokens": 1150}


# ─────────────────────────────────────────────────────────── the harness, as a double


@dataclass
class FakeHarness:
    """A launcher double that types `pkc draft` commands the way a real harness would.

    One list of actions per launch. An action is `(name, args)` for a tool call, the literal
    `"finish"`, `"nothing"` for a harness that stopped, or a callable for the awkward states
    a scripted sequence cannot reach.
    """

    rt: draft_cmd.DraftRuntime
    scripts: list[list[Any]]
    requests: list[LaunchRequest] = field(default_factory=list)
    codes: list[int] = field(default_factory=list)
    result: Callable[[], LaunchResult] | None = None

    async def __call__(self, request: LaunchRequest) -> LaunchResult:
        self.requests.append(request)
        script = self.scripts.pop(0) if self.scripts else []
        for action in script:
            if action == "nothing":
                continue
            if action == "finish":
                self.codes.append(await draft_cmd.cmd_finish(self.rt))
                continue
            if callable(action):
                await action(self.rt)
                continue
            name, args = action
            self.codes.append(await draft_cmd.run_tool(self.rt, name, args))
        if self.result is not None:
            return self.result()
        return LaunchResult(
            exit_code=0,
            stdout="",
            stderr="",
            usage=dict(USAGE),
            session_id="sess-1",
        )


async def never_resumes(manifest) -> bool:  # noqa: ANN001
    return False


def runner(fake: FakeHarness, tmp_path, **kwargs) -> AgentRoundRunner:  # noqa: ANN001
    base = {
        "manifest": CODEX,
        "project_dir": str(tmp_path),
        "timeout_s": 30.0,
        "launcher": fake,
        "can_resume": never_resumes,
    }
    return AgentRoundRunner(**{**base, **kwargs})


async def uncited_claim(rt: draft_cmd.DraftRuntime) -> None:
    """Leave the draft in a state the GATE rejects but no single write could be refused for.

    A write command post-checks the page it touched and rolls back, so a Steward cannot reach
    this state one command at a time — which is exactly why the state has to be reachable in a
    test: a component tool, a legacy page, or a future verb can produce a draft the final gate
    refuses, and what the round does then is what is under test. The tool called here is the
    real one; only the post-check is skipped.
    """
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    state = await rt.drafts.get(rt.user_id, job_id)
    draft = PatchDraft.from_state(state["draft"])
    session = DraftSession.from_state(state["session"])
    sources = await rt.load_sources(session.source_ids)
    tools = {t.name: t for t in build_compile_tool_face(draft, sources=sources)}
    tools["append_block"].func(path=PERSON, heading="承诺", text="他会在下周交付。")
    await rt.drafts.put(
        rt.user_id, job_id, {"draft": draft.to_state(), "session": session.to_state()}
    )
    UNCITED_ANCHOR[job_id] = re.findall(r"c:([0-9a-f]+)", draft.read(PERSON).body)[-1]


#: The anchor `uncited_claim` minted, so the repair action can address it.
UNCITED_ANCHOR: dict[str, str] = {}


# ─────────────────────────────────────────────────────── the harness finished the round


async def test_a_harness_that_finishes_the_round_leaves_nothing_for_the_worker_to_do(tmp_path):
    """The normal case, and the one the finish/finalize cut is about.

    `pkc draft finish` inside the harness's session committed the round, completed the job and
    deleted the draft. The worker must recognise that and add nothing: one commit, one job
    completion, no second finalize.
    """
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == COMMITTED_BY_HARNESS
    assert result.launches == 1
    assert len(h.store.commits) == 1, "the round was finalized more than once"
    assert len(h.jobs.completed) == 1
    assert h.jobs.completed[0]["ok"] is True
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


async def test_the_round_is_opened_for_the_harness_and_names_where_it_starts(tmp_path):
    """The one thing the unattended task says that the interactive one does not: the draft is
    already open, so start at step 3 — and the path to run `pkc` by, because the working
    directory is empty."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    (request,) = fake.requests
    assert h.job_id in request.task_text
    assert "already open" in request.task_text
    assert "step 3" in request.task_text
    assert str(tmp_path) in request.task_text  # the shim, absolute
    # The system text is the round's contract, unchanged, and it is NOT in the task.
    assert request.system_text
    assert request.system_text not in request.task_text


async def test_what_the_harness_reported_spending_lands_on_the_job(tmp_path):
    """The unattended posture DOES see usage: the launcher read it out of the harness's own
    JSON, one process out. Step 2's "absent" rule was about a process that measured nothing,
    and this one measured something."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.usage == USAGE


async def test_a_harness_that_reported_no_usage_reports_none_rather_than_zero(tmp_path):
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    fake.result = lambda: LaunchResult(exit_code=0, stdout="", stderr="", usage=None)
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.usage is None
    assert result.cost_usd is None


# ────────────────────────────────────────────────── the harness stopped without finishing


async def test_a_harness_that_stops_mid_round_has_its_round_finished_by_the_worker(tmp_path):
    """Unattended means nobody will come back to it. The worker finishes the draft through the
    SAME `cmd_finish` the CLI calls, so the gate judges what was written — a round that wrote
    good claims and lost its process is committed, not thrown away."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS]])  # wrote, never finished
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == FINISHED_BY_WORKER
    assert result.launches == 1
    assert len(h.store.commits) == 1
    assert h.jobs.completed[0]["ok"] is True
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


async def test_a_harness_that_did_nothing_at_all_still_ends_its_job(tmp_path):
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [["nothing"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.outcome == FINISHED_BY_WORKER
    assert h.jobs.completed, "the job was left claimed"
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


# ──────────────────────────────────────────────────── the launch that never became a round


#: What Codex prints when the Owner's plan is spent, as it printed it the night this branch
#: was written. The hour is in it, which is the whole reason the worker can wait exactly.
USAGE_LIMIT = (
    "stream error: You've hit your usage limit. "
    "Please try again at Sep 15th, 2026 9:23 AM."
)


def refused(**kwargs) -> LaunchResult:
    base = {"exit_code": 1, "stdout": "", "stderr": USAGE_LIMIT, "rate_limited": True}
    return LaunchResult(**{**base, **kwargs})


async def test_a_rate_limited_launch_is_not_a_round_and_is_neither_finished_nor_abandoned(
    tmp_path,
):
    """The night this exists for: 296 compile jobs recorded `done ok=true` with nothing in
    them, because a launch that never ran was read as a round that wrote nothing.

    The harness was told no before it read anything. There is no work to judge, so the runner
    reports that and touches neither `finish` nor `abandon` — the draft, the job and the
    library are exactly as they were, and it is the worker that decides what happens next.
    """
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [["nothing"]], result=refused)
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == HARNESS_UNAVAILABLE
    assert result.rate_limited and result.exit_code == 1
    assert "usage limit" in result.output
    assert h.store.commits == [], "an empty round was committed"
    assert h.jobs.completed == [], "the runner decided an outcome it has no business deciding"
    assert await h.drafts.get(h.rt.user_id, h.job_id) is not None, "the draft was abandoned"
    job = await h.jobs.get_job(h.rt.user_id, h.job_id)
    assert job.status == "claimed", "the job was released or ended by the runner"


async def test_a_turn_the_harness_declared_failed_at_exit_zero_is_the_same_thing(tmp_path):
    """`Selected model is at capacity` — a `turn.failed` event, and an exit code of 0.

    The launcher is what reads it (`_is_rate_limited`, gated on the harness's own protocol);
    what this pins is that the runner treats the flag identically however it was raised.
    """
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    event = (
        '{"type":"turn.failed","error":{"message":'
        '"Selected model is at capacity. Please try a different model."}}'
    )
    fake = FakeHarness(h.rt, [["nothing"]], result=lambda: LaunchResult(
        exit_code=0, stdout=event, stderr="", rate_limited=True,
    ))
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.outcome == HARNESS_UNAVAILABLE
    assert "at capacity" in result.output
    assert h.jobs.completed == [] and h.store.commits == []


async def test_a_harness_that_finished_the_round_stays_finished_whatever_it_exited_with(
    tmp_path,
):
    """The branch this must not swallow: `pkc draft finish` committed, the draft is gone, and
    the process then exited non-zero for reasons of its own. The round HAPPENED."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]], result=lambda: LaunchResult(
        exit_code=1, stdout="", stderr="the harness fell over on its way out",
    ))
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.outcome == COMMITTED_BY_HARNESS
    assert len(h.store.commits) == 1 and h.jobs.completed[0]["ok"] is True


async def test_a_refusal_that_arrived_mid_round_leaves_the_written_work_to_the_gate(tmp_path):
    """A rate limit is not a reason to throw away claims that were already typed.

    The harness wrote its round and then hit the limit. That is a round — the worker finishes
    it through the same `cmd_finish` a Steward would, and the gate judges what is there.
    """
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS]], result=refused)
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.outcome == FINISHED_BY_WORKER
    assert len(h.store.commits) == 1 and h.jobs.completed[0]["ok"] is True


# ───────────────────────────────────────────────────────────── reading the harness's clock


def test_the_deadline_codex_names_is_read_in_the_deployments_own_timezone():
    """`try again at Sep 15th, 2026 9:23 AM` is a LOCAL wall clock with no offset on it, so
    the zone has to come from the deployment (`PNEUMA_KNOWLEDGE_DEFAULT_TIMEZONE`)."""
    from zoneinfo import ZoneInfo

    from pneuma_knowledge_service.coding_agent.backends import (
        CODEX,
        usage_limit_deadline,
    )

    shanghai = usage_limit_deadline(
        USAGE_LIMIT, timezone_name="Asia/Shanghai", patterns=CODEX.usage_limit_patterns
    )
    assert shanghai == datetime(2026, 9, 15, 9, 23, tzinfo=ZoneInfo("Asia/Shanghai"))
    # The same sentence, a different deployment: a different instant, six hours apart.
    utc = usage_limit_deadline(USAGE_LIMIT, timezone_name="UTC")
    assert utc == datetime(2026, 9, 15, 9, 23, tzinfo=ZoneInfo("UTC"))
    assert shanghai != utc


@pytest.mark.parametrize(
    "text",
    [
        "",
        "stream error: 429 Too Many Requests; retry later",
        '{"type":"turn.failed","error":{"message":"Selected model is at capacity."}}',
        "try again at Nevermber 40th, 2026 9:23 AM",
    ],
)
def test_an_unparsable_refusal_names_no_deadline_rather_than_guessing_one(text):
    """None is the honest answer, and the one the worker's doubling cooldown is for. A
    half-read date would be a worker that came back at the wrong hour and looked broken."""
    from pneuma_knowledge_service.coding_agent.backends import usage_limit_deadline

    assert usage_limit_deadline(text, timezone_name="Asia/Shanghai") is None


# ───────────────────────────────────────────────────────────────────── the repair round


async def test_a_rejected_finish_gets_one_repair_round_carrying_the_gates_own_words(tmp_path):
    """The gate refused the harness's `finish`; the draft is open in `repair` with the
    findings on it. The second launch's task is `render_violations` — the same text the
    langchain repair round is fed and the same one `pkc draft finish` printed."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None

    async def repair(rt: draft_cmd.DraftRuntime) -> None:
        # Give the uncited claim the citation the gate named, then finish again.
        await draft_cmd.run_tool(
            rt,
            "edit_claim",
            {
                "path": PERSON,
                "anchor_id": UNCITED_ANCHOR[h.job_id],
                "new_text": "他会在下周交付。[cite: s01 ¶4]",
            },
        )
        await draft_cmd.cmd_finish(rt)

    fake = FakeHarness(h.rt, [[*CALLS, uncited_claim, "finish"], [repair]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.launches == 2
    assert result.outcome == REPAIRED
    first, second = fake.requests
    assert "provenance" in second.task_text or "citation" in second.task_text
    assert PERSON in second.task_text
    assert h.jobs.completed[0]["ok"] is True
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None
    # Two launches, two lots of usage — summed, exactly as the loop sums its two rounds.
    assert result.usage == {k: v * 2 for k, v in USAGE.items()}


async def test_a_second_rejection_aborts_the_job_and_leaves_canonical_untouched(tmp_path):
    """One repair round, as the langchain executor gets. A second failure is a report."""
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, uncited_claim, "finish"], ["nothing"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.launches == 2
    assert h.store.commits == [], "an aborted round must not commit"
    assert h.jobs.completed[0]["ok"] is False
    assert "citation" in (h.jobs.completed[0]["detail"] or "")
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


async def test_a_repair_round_resumes_the_first_rounds_session_where_the_harness_can(tmp_path):
    async def always_resumes(manifest) -> bool:  # noqa: ANN001
        return True

    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    fake = FakeHarness(h.rt, [[*CALLS, uncited_claim, "finish"], ["nothing"]])
    await runner(fake, tmp_path, can_resume=always_resumes).run_job(h.rt, h.job_id)
    assert fake.requests[1].resume_session == "sess-1"

    h2 = await harness([source()])
    assert await h2.jobs.claim(h2.rt.user_id, h2.job_id) is not None
    fake2 = FakeHarness(h2.rt, [[*CALLS, uncited_claim, "finish"], ["nothing"]])
    await runner(fake2, tmp_path).run_job(h2.rt, h2.job_id)
    assert fake2.requests[1].resume_session == "", "a CLI without resume gets a fresh process"


# ──────────────────────────────────────────────────────────── the trailer audit on `open`


class TrailerCanonicalStore:
    """A canonical store that answers the three questions the audit asks."""

    def __init__(self, snapshots: list[SnapshotRef], trailers: dict[str, str]) -> None:
        self._snapshots = snapshots
        self._trailers = trailers
        self.commits: list[dict[str, str]] = []
        self.messages: list[str] = []

    async def list(self, user_id, *, at=None):  # noqa: ANN001
        return []

    async def snapshots(self, user_id):  # noqa: ANN001
        return list(self._snapshots)

    async def commit_trailer(self, user_id, ref, key: str):  # noqa: ANN001
        return self._trailers.get(getattr(ref, "ref", str(ref)))

    async def commit_patch(self, user_id, files, *, message):  # noqa: ANN001
        self.commits.append(dict(files))
        self.messages.append(message)
        return SnapshotRef(ref=f"commit-{len(self.commits)}")


async def _open_over(store) -> tuple[int, str]:  # noqa: ANN001
    h = await harness([source()])
    h.rt.canonical = store
    code = await draft_cmd.cmd_open(h.rt, h.job_id)
    return code, h.err()


async def test_a_head_written_outside_the_gate_is_detected_and_named():
    """§8's detection, and what makes the skill's "a commit that arrived by another route is
    detected at the next compile and named" a true sentence rather than a hope."""
    code, err = await _open_over(
        TrailerCanonicalStore(
            [SnapshotRef(ref="deadbeef", label="fix a typo by hand")], trailers={}
        )
    )
    assert code == draft_cmd.EXIT_REFUSED
    assert "deadbeef" in err
    assert "fix a typo by hand" in err
    assert "outside the gate" in err


async def test_a_head_this_framework_wrote_opens_normally():
    code, err = await _open_over(
        TrailerCanonicalStore(
            [SnapshotRef(ref="c0", label="compile j-1")],
            trailers={"c0": "personal-knowledge@v1"},
        )
    )
    assert code == draft_cmd.EXIT_OK, err


async def test_a_library_with_no_commits_opens_normally():
    """A fresh library is not a library written by someone else. The git adapter's `_repo`
    runs `git init` and makes no bootstrap commit, so "no commits" is the only exempt state
    there is — and it is exempt."""
    code, err = await _open_over(TrailerCanonicalStore([], trailers={}))
    assert code == draft_cmd.EXIT_OK, err


async def test_a_store_that_cannot_read_trailers_is_not_interrogated():
    """The audit reports what it can see. Inventing a finding out of an absent capability
    would be worse than the finding it looks for."""
    h = await harness([source()])
    assert not hasattr(h.rt.canonical, "commit_trailer")
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK, h.err()


async def test_the_unattended_round_refuses_to_start_on_a_library_it_cannot_attribute(tmp_path):
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    h.rt.canonical = TrailerCanonicalStore(
        [SnapshotRef(ref="deadbeef", label="hand edit")], trailers={}
    )
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    with pytest.raises(AgentRoundOpenRefused) as refused:
        await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert fake.requests == [], "no harness was launched on an un-attributable library"
    # The reason travels on the exception, because the drain writes it onto the job row.
    assert "deadbeef" in str(refused.value)


# ───────────────────────────────────────────────────────────────── the worker's two postures


def worker_settings(**kwargs) -> Settings:
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "agent:codex",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
    }
    return Settings(**{**base, **kwargs})


class WorkerCtx:
    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        from pneuma_knowledge_service.wiring import executor_for

        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


async def _drain(config: Settings, monkeypatch) -> tuple[InMemoryJobQueue, str, list[str]]:
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(UserId("u-agent"), "compile", {"source_ids": ["src-01"]})
    ran: list[str] = []

    async def fake_agent(ctx, user_id, job):  # noqa: ANN001
        ran.append(job.job_id)
        await ctx.store.complete(
            user_id, job.job_id, ok=True, detail="committed", executor="agent:codex"
        )

    monkeypatch.setattr(compile_worker, "process_agent_job", fake_agent)
    ctx = WorkerCtx(config, jobs)
    await compile_worker.drain_user(ctx, None, SimpleNamespace(), UserId("u-agent"))
    return jobs, job_id, ran


async def test_a_worker_is_unattended_by_default_and_runs_the_compile_job_itself(monkeypatch):
    """A worker is by definition unattended — nobody is at a terminal where it runs — so a
    compile job under an agent executor is claimed and handed to a launched harness (§9)."""
    jobs, job_id, ran = await _drain(worker_settings(), monkeypatch)
    assert ran == [job_id]
    assert (await jobs.get_job(UserId("u-agent"), job_id)).status == "done"


async def test_with_the_unattended_posture_off_the_job_waits_for_a_steward(monkeypatch):
    """Step 2's behaviour, preserved and now selectable: the Owner's own session opens it."""
    jobs, job_id, ran = await _drain(
        worker_settings(agent_unattended=False), monkeypatch
    )
    assert ran == []
    assert (await jobs.get_job(UserId("u-agent"), job_id)).status == "queued"


def test_the_posture_is_one_question_asked_in_one_place():
    ctx = WorkerCtx(worker_settings(), InMemoryJobQueue())
    assert compile_worker.unattended(ctx)
    assert not compile_worker.unattended(
        WorkerCtx(worker_settings(agent_unattended=False), InMemoryJobQueue())
    )
    # Under a model executor the question does not arise, whatever the setting says.
    model = worker_settings(llm_model_compile="openrouter:x/compile")
    assert not compile_worker.unattended(WorkerCtx(model, InMemoryJobQueue()))


# ──────────────────────────────────── the library somebody else is editing, unattended


async def test_a_dirty_library_ends_the_unattended_round_by_refusing_the_commit(tmp_path):
    """Nobody is at the terminal, so the refusal has to reach the JOB ROW.

    The harness typed its writes and stopped; the worker runs the same `cmd_finish` a Steward
    would, and the canonical adapter refuses because the working tree holds uncommitted
    changes this framework did not make. The error carries the detail out of `run_job` — the
    drain writes it onto the job, which is where an operator looks.
    """
    from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError

    from test_draft_cli import DIRTY, DirtyCanonicalStore  # noqa: E402

    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None

    async def somebody_edits_the_tree(rt) -> None:  # noqa: ANN001
        rt.canonical = DirtyCanonicalStore(h.store._docs)

    fake = FakeHarness(rt=h.rt, scripts=[[*CALLS, somebody_edits_the_tree]])
    with pytest.raises(CanonicalDirtyError) as caught:
        await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert caught.value.detail == f"canonical_dirty:{DIRTY[0]}"
    # Nothing was written, and the draft is still there for the next attempt.
    assert h.store.commits == []
    assert await h.drafts.get(h.rt.user_id, h.job_id) is not None


async def test_the_drain_records_a_dirty_library_on_the_job_rather_than_a_worker_error(
    monkeypatch,
):
    """The agent job kind reaches the worker's own `CanonicalDirtyError` arm, so the process
    view names the paths — the same `ok=False, detail=exc.detail` every other job kind that
    commits records, and not `worker error: …` with the fault buried in it."""
    from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError

    jobs = InMemoryJobQueue()
    user = UserId("u-agent")
    job_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})

    async def refuses(ctx, user_id, job):  # noqa: ANN001
        raise CanonicalDirtyError(("data/canonical/u-agent/work/aurora.md",))

    monkeypatch.setattr(compile_worker, "process_agent_job", refuses)
    await compile_worker.drain_user(
        WorkerCtx(worker_settings(), jobs), None, SimpleNamespace(), user
    )
    done = jobs.completed[-1]
    assert done["job_id"] == job_id
    assert done["ok"] is False
    assert done["detail"] == "canonical_dirty:data/canonical/u-agent/work/aurora.md"


@pytest.mark.parametrize("harness_finishes", [True, False])
async def test_the_unattended_last_message_becomes_the_missing_brief(tmp_path, harness_finishes):
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    briefs = {}

    async def record(job_id, text):
        if any(c["job_id"] == job_id and c["ok"] and c["snapshot_ref"] for c in h.jobs.completed):
            briefs.setdefault(job_id, text)

    h.rt.record_brief = record
    actions = [*CALLS, *(["finish"] if harness_finishes else [])]
    fake = FakeHarness(h.rt, [actions], result=lambda: LaunchResult(
        exit_code=0, stdout="", stderr="", last_message="Recorded the synthetic delivery commitments."
    ))
    await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert briefs == {h.job_id: "Recorded the synthetic delivery commitments."}


async def test_a_finish_brief_wins_over_the_harness_last_message(tmp_path):
    h = await harness([source()])
    assert await h.jobs.claim(h.rt.user_id, h.job_id) is not None
    briefs = {}

    async def record(job_id, text):
        briefs.setdefault(job_id, text)

    async def finish(rt):
        assert await draft_cmd.cmd_finish(rt, brief="The Steward's explicit brief.") == 0

    h.rt.record_brief = record
    fake = FakeHarness(h.rt, [[*CALLS, finish]], result=lambda: LaunchResult(
        exit_code=0, stdout="", stderr="", last_message="The harness's final message."
    ))
    await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert briefs == {h.job_id: "The Steward's explicit brief."}


async def test_a_brief_store_failure_does_not_leave_a_committed_draft_open():
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    for verb, args in CALLS:
        assert await draft_cmd.run_tool(h.rt, verb, args) == 0

    async def unavailable(job, text):
        raise OSError("synthetic narration store outage")

    h.rt.record_brief = unavailable
    assert await draft_cmd.cmd_finish(h.rt, brief="The synthetic version was compiled.") == 0
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None
    assert h.jobs.completed[-1]["ok"] and h.jobs.completed[-1]["snapshot_ref"]


@pytest.mark.parametrize("brief", ["", " \n ", "b" * (draft_cmd.BRIEF_MAX_CHARS + 1)])
async def test_finish_refuses_a_blank_or_unbounded_brief_without_finishing(brief):
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    assert await draft_cmd.cmd_finish(h.rt, brief=brief) == draft_cmd.EXIT_REFUSED
    assert await h.drafts.get(h.rt.user_id, h.job_id) is not None
    assert not h.jobs.completed and not h.store.commits


async def test_finish_reads_its_brief_from_a_file_or_stdin(tmp_path, monkeypatch):
    import io
    from pneuma_knowledge_service.cli import _draft_command, build_parser

    for name in ("brief.md", "-"):
        h = await harness([source()])
        await draft_cmd.cmd_open(h.rt, h.job_id)
        for verb, args in CALLS:
            assert await draft_cmd.run_tool(h.rt, verb, args) == 0
        recorded = []

        async def record(job, text):
            recorded.append(text)

        h.rt.record_brief = record
        text = "Synthetic commitments were recorded.\n"
        path = tmp_path / name
        if name == "-":
            monkeypatch.setattr("sys.stdin", io.StringIO(text))
            filename = "-"
        else:
            path.write_text(text)
            filename = str(path)
        args = build_parser().parse_args(["draft", "finish", "--brief", filename])
        assert await _draft_command(h.rt, args, []) == 0
        assert recorded == [text]


# ────────────────────────────────────────── the worker: a spent subscription costs one job


@pytest.fixture(autouse=True)
def _forget_cooling():
    """The cooling map is process state, and one test's rate limit is not another's."""
    compile_worker._COOLING.clear()
    compile_worker._RATE_LIMIT_HITS.clear()
    yield
    compile_worker._COOLING.clear()
    compile_worker._RATE_LIMIT_HITS.clear()


_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def usage_limit_saying(when: datetime) -> str:
    """Codex's own sentence, naming `when` — built rather than pasted, so a test that pins
    the WAIT does not start failing on the day the pasted date goes past."""
    hour = when.hour % 12 or 12
    meridiem = "AM" if when.hour < 12 else "PM"
    return (
        "stream error: You've hit your usage limit. Please try again at "
        f"{_MONTH_NAMES[when.month - 1]} {when.day}th, {when.year} "
        f"{hour}:{when.minute:02d} {meridiem}."
    )


class UnavailableLaunch(SimpleNamespace):
    """What `AgentRoundRunner` hands the worker when a launch never became a round."""

    def __init__(self, *, output: str, rate_limited: bool = True, exit_code: int = 1) -> None:
        super().__init__(output=output, rate_limited=rate_limited, exit_code=exit_code)


async def _refused(ctx, jobs, user, result, *, executor="worker:codex:0001", kind="compile"):
    """One agent-path job, claimed by a launch that then refused. Returns its id."""
    from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore

    job_id = await jobs.enqueue(user, kind, {"source_ids": ["src-01"]})
    job = await jobs.claim(user, job_id)
    assert job is not None
    assert await jobs.attach_executor(user, job_id, executor)
    await compile_worker._harness_unavailable(
        ctx, user, job, result,
        rt=SimpleNamespace(drafts=InMemoryDraftStore(jobs)),
        executor=executor,
        manifest=CODEX,
    )
    return job_id


async def test_a_refused_launch_fails_its_job_digests_nothing_and_comes_back_later(caplog):
    """The whole repair, in one job's life.

    What the night produced: `done ok=true`, `projection:{…"upserted":0…}`, sources digested,
    nothing written. What it produces now: a failed job naming the provider's refusal, the
    material still undigested, and the SAME payload queued again behind the hour the provider
    itself named.
    """
    user = UserId("u-agent")
    when = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(hours=9)
    when = when.replace(second=0, microsecond=0)
    jobs = InMemoryJobQueue()
    ctx = WorkerCtx(worker_settings(default_timezone="Asia/Shanghai"), jobs)
    with caplog.at_level(logging.WARNING):
        job_id = await _refused(
            ctx, jobs, user, UnavailableLaunch(output=usage_limit_saying(when))
        )

    done = jobs.completed[-1]
    assert done["job_id"] == job_id and done["ok"] is False
    assert done["detail"].startswith("rate_limited: Codex usage limit; retry after ")
    assert when.isoformat() in done["detail"], "the provider's own hour was not read"

    rows = await jobs.list_jobs(user)
    queued = [r for r in rows if r["status"] == "queued"]
    assert len(queued) == 1, "the work was dropped, or duplicated"
    assert queued[0]["payload"]["source_ids"] == ["src-01"]
    assert queued[0]["payload"]["cooling_reason"] == "codex usage limit"
    assert queued[0]["not_before"] == when

    # And the queue itself refuses to hand it out before then — the wait is a row, not a
    # sleeping worker, so nothing is spent while it lasts and a restart reads the same answer.
    assert await jobs.claim_next(user) is None

    lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert lines == [
        f"[compile-worker] codex usage limit: cooling until {when.isoformat()}; 1 job(s) wait"
    ]


async def test_nothing_this_worker_did_claims_the_material_was_compiled():
    """Digestion is a claim about what canonical holds. A round that never ran holds none."""
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    stamped: list[tuple] = []
    jobs.mark_digested = lambda *a, **k: stamped.append(a)  # noqa: ARG005
    ctx = WorkerCtx(worker_settings(), jobs)
    await _refused(ctx, jobs, user, UnavailableLaunch(output="429 Too Many Requests"))
    assert stamped == []


async def test_a_refusal_with_no_hour_in_it_cools_for_longer_each_consecutive_time():
    """The fallback, and why it doubles: the guess that runs short is the expensive one."""
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    ctx = WorkerCtx(worker_settings(agent_rate_limit_cooldown_s=900), jobs)
    waits = []
    for _ in range(3):
        before = datetime.now(timezone.utc)
        await _refused(ctx, jobs, user, UnavailableLaunch(output="429 Too Many Requests"))
        row = [r for r in await jobs.list_jobs(user) if r["status"] == "queued"][0]
        waits.append(round((row["not_before"] - before).total_seconds()))
        # only the newest queued row is the one this iteration made
        row["status"] = "done"
    assert waits == [900, 1800, 3600]

    ceiling = WorkerCtx(
        worker_settings(agent_rate_limit_cooldown_s=900, agent_rate_limit_cooldown_max_s=1200),
        jobs,
    )
    before = datetime.now(timezone.utc)
    await _refused(ceiling, jobs, user, UnavailableLaunch(output="429 Too Many Requests"))
    row = [r for r in await jobs.list_jobs(user) if r["status"] == "queued"][0]
    assert round((row["not_before"] - before).total_seconds()) == 1200


async def test_a_model_at_capacity_is_named_as_itself_and_not_as_a_spent_quota():
    """One mechanism, two sentences: an operator told their quota ran out when the model was
    merely busy would go looking for a bill."""
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    ctx = WorkerCtx(worker_settings(), jobs)
    await _refused(ctx, jobs, user, UnavailableLaunch(
        output='{"type":"turn.failed","error":{"message":"Selected model is at capacity."}}'
    ))
    assert "Codex at capacity" in jobs.completed[-1]["detail"]
    row = [r for r in await jobs.list_jobs(user) if r["status"] == "queued"][0]
    assert row["payload"]["cooling_reason"] == "codex at capacity"


async def test_one_launch_that_simply_died_does_not_take_the_tenant_off_the_air():
    """A harness that fell over is not a subscription with no room. The job comes back; the
    tenant does not go on ice, because one failure is no evidence about the next launch."""
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    ctx = WorkerCtx(worker_settings(), jobs)
    await _refused(
        ctx, jobs, user,
        UnavailableLaunch(output="fatal: no such file", rate_limited=False, exit_code=2),
    )
    assert jobs.completed[-1]["detail"] == "harness_failed: exit 2"
    assert compile_worker.agent_cooling(user) is None


async def test_a_cooling_tenant_still_drains_every_job_that_needs_no_harness(monkeypatch):
    """The subscription is what is out of room, not the library. Index, projection, groom and
    archive jobs run no harness at all and must keep flowing."""
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    compile_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})
    index_id = await jobs.enqueue(user, "index", {"source_id": "src-01"})
    compile_worker._COOLING[str(user)] = (
        datetime.now(timezone.utc) + timedelta(hours=2), "codex usage limit"
    )
    ran: list[str] = []

    async def indexed(ctx, user_id, job):  # noqa: ANN001
        ran.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    async def never(ctx, user_id, job):  # noqa: ANN001
        raise AssertionError("a cooling worker claimed a job that needs a harness")

    monkeypatch.setattr(compile_worker, "process_index_job", indexed)
    monkeypatch.setattr(compile_worker, "process_agent_job", never)
    await compile_worker.drain_user(
        WorkerCtx(worker_settings(), jobs), None, SimpleNamespace(), user
    )
    assert ran == [index_id]
    assert (await jobs.get_job(user, compile_id)).status == "queued"


async def test_the_ice_melts_and_the_tenant_is_claimed_again(monkeypatch):
    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(user, "compile", {"source_ids": ["src-01"]})
    compile_worker._COOLING[str(user)] = (
        datetime.now(timezone.utc) - timedelta(seconds=1), "codex usage limit"
    )
    ran: list[str] = []

    async def agent(ctx, user_id, job):  # noqa: ANN001
        ran.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="committed")

    monkeypatch.setattr(compile_worker, "process_agent_job", agent)
    await compile_worker.drain_user(
        WorkerCtx(worker_settings(), jobs), None, SimpleNamespace(), user
    )
    assert ran == [job_id]
    assert compile_worker.agent_cooling(user) is None


async def test_the_ice_is_laid_during_the_drain_and_stops_the_rest_of_the_queue(monkeypatch):
    """The shape of the actual night: one tenant, hundreds of queued compile jobs, and the
    FIRST one is what meets the spent subscription.

    An exclusion list computed once before the loop would let the other three hundred through
    behind it — which is what 853 jobs in four hours looks like from the inside.
    """
    from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore

    user = UserId("u-agent")
    jobs = InMemoryJobQueue()
    queued = [
        await jobs.enqueue(user, "compile", {"source_ids": [f"src-{n:02d}"]})
        for n in range(3)
    ]
    handed: list[str] = []

    async def refusing(ctx, user_id, job):  # noqa: ANN001
        handed.append(job.job_id)
        executor = f"worker:codex:{len(handed)}"
        assert await ctx.store.attach_executor(user_id, job.job_id, executor)
        await compile_worker._harness_unavailable(
            ctx, user_id, job,
            UnavailableLaunch(output="stream error: 429 Too Many Requests"),
            rt=SimpleNamespace(drafts=InMemoryDraftStore(ctx.store)),
            executor=executor,
            manifest=CODEX,
        )

    monkeypatch.setattr(compile_worker, "process_agent_job", refusing)
    ctx = WorkerCtx(worker_settings(), jobs)
    await compile_worker.drain_user(ctx, None, SimpleNamespace(), user)

    assert handed == [queued[0]], "the drain kept feeding a subscription that had no room"
    assert [(await jobs.get_job(user, j)).status for j in queued[1:]] == ["queued", "queued"]
