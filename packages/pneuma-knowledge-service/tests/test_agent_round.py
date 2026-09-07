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

import re
from dataclasses import dataclass, field
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
    fake = FakeHarness(h.rt, [[*CALLS, "finish"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.usage == USAGE


async def test_a_harness_that_reported_no_usage_reports_none_rather_than_zero(tmp_path):
    h = await harness([source()])
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
    fake = FakeHarness(h.rt, [[*CALLS]])  # wrote, never finished
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)

    assert result.outcome == FINISHED_BY_WORKER
    assert result.launches == 1
    assert len(h.store.commits) == 1
    assert h.jobs.completed[0]["ok"] is True
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


async def test_a_harness_that_did_nothing_at_all_still_ends_its_job(tmp_path):
    h = await harness([source()])
    fake = FakeHarness(h.rt, [["nothing"]])
    result = await runner(fake, tmp_path).run_job(h.rt, h.job_id)
    assert result.outcome == FINISHED_BY_WORKER
    assert h.jobs.completed, "the job was left claimed"
    assert await h.drafts.get(h.rt.user_id, h.job_id) is None


# ───────────────────────────────────────────────────────────────────── the repair round


async def test_a_rejected_finish_gets_one_repair_round_carrying_the_gates_own_words(tmp_path):
    """The gate refused the harness's `finish`; the draft is open in `repair` with the
    findings on it. The second launch's task is `render_violations` — the same text the
    langchain repair round is fed and the same one `pkc draft finish` printed."""
    h = await harness([source()])

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
    fake = FakeHarness(h.rt, [[*CALLS, uncited_claim, "finish"], ["nothing"]])
    await runner(fake, tmp_path, can_resume=always_resumes).run_job(h.rt, h.job_id)
    assert fake.requests[1].resume_session == "sess-1"

    h2 = await harness([source()])
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
