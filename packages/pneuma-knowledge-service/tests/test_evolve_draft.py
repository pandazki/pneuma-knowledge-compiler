"""The structure door over real git; the same round also runs against Postgres."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import with_skill_trailer
from pneuma_knowledge_core.compile.session import DraftSession
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.prompts import override_prompts, reset_prompt_overrides
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore, InMemoryJobQueue
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore
from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.cli import draft, evolve
from pneuma_knowledge_service.evolve_service import adopt_evolve_job
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.skills import skill_for_user, composed_skill_readonly, path_templates_for

A = "memory/topics/aurora.md"
B = "memory/topics/harbour.md"
C = "memory/topics/delivery.md"
CLAIM = "- Aurora ships in June. [cite: synthetic-evolve ¶0] <!-- c:aa11 -->\n"
OTHER = "- Harbour owns delivery. [cite: synthetic-evolve ¶1] <!-- c:bb22 -->\n"
PROPOSAL = {"packs": [], "rationale": f"The claims in {A} and {B} describe one delivery; consolidate them."}


class MemoryEvolveStore(InMemoryJobQueue):
    def __init__(self):
        super().__init__()
        self._pool = None
        self.tasks = {}
        self.events = []

    async def list_evolve_tasks(self, user):
        return [t for (u, _), t in reversed(self.tasks.items()) if str(user) == u]

    async def get_evolve_task(self, user, task_id):
        return self.tasks.get((str(user), task_id))

    async def create_evolve_task(self, user, task_id, *, status, **fields):
        self.tasks[str(user), task_id] = {
            "task_id": task_id, "status": status, "created_at": datetime.now(timezone.utc),
            "branch": None, "base_ref": None, "proposal": None, "summary": None,
            "dropped": None, "detail": None, **fields,
        }

    async def decide_evolve_task(self, user, task_id, status, **fields):
        self.tasks[str(user), task_id].update(status=status, **fields)

    async def update_evolve_detail(self, user, task_id, detail):
        self.tasks[str(user), task_id]["detail"] = detail

    async def list_compile_events(self, user):
        return self.events

    async def block_counts(self, user):
        return {"synthetic-evolve": 2}


async def make_runtime(tmp_path, store=None, user=None):
    user = user or UserId("u-evolve-door")
    store = store or MemoryEvolveStore()
    settings = Settings(
        canonical_root=str(tmp_path / "canonical"), llm_model="openrouter:synthetic/base",
        llm_model_compile="agent:codex", llm_model_evolve="", user_schema_packs=False,
        evolve_auto_trigger=False, agent_probe_on_start=False,
    )
    canonical = GitCanonicalStore(settings.canonical_root)
    skill = load_skill_base(settings.user_schema_base_version)
    await canonical.commit_patch(user, {
        A: render_document({"doc_id": "d-aurora", "type": "topic", "slug": "aurora"}, "# Aurora\n\n" + CLAIM),
        B: render_document({"doc_id": "d-harbour", "type": "topic", "slug": "harbour"}, "# Harbour\n\n" + OTHER),
    }, message=with_skill_trailer("synthetic evolve seed", skill))
    ctx = SimpleNamespace(settings=settings, store=store, canonical=canonical)
    rt = await evolve.build_runtime(ctx, user, executor="agent:codex")
    if isinstance(store, MemoryEvolveStore):
        rt.drafts = InMemoryDraftStore(store)
    rt.out, rt.err = io.StringIO(), io.StringIO()
    return rt


async def propose(rt, tmp_path, payload=None):
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(payload if payload is not None else PROPOSAL), encoding="utf-8")
    return await evolve.run_command(rt, "propose", file=str(path))


async def round_trip(rt, tmp_path, monkeypatch):
    before = (await rt.canonical.snapshots(rt.user_id))[0].ref
    assert await evolve.cmd_open(rt, new=True) == 0, rt.err.getvalue()
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    state = await rt.drafts.get(rt.user_id, job_id)
    assert state["kind"] == "evolve"
    assert "phase" not in state["session"]["context"]
    assert await propose(rt, tmp_path) == 0, rt.err.getvalue()
    assert await evolve.run_command(rt, "rename", path=A, new_path=C) == 0, rt.err.getvalue()
    assert await evolve.run_command(rt, "move-claim", from_path=B, anchor="bb22", to_path=C) == 0, rt.err.getvalue()
    assert await evolve.run_command(rt, "retire", path=B) == 0, rt.err.getvalue()
    assert await evolve.cmd_check(rt) == 0, rt.out.getvalue()
    contract = tmp_path / "contract.md"
    contract.write_text("Record delivery plans with their evidence and distinguish planned from completed work.\n", encoding="utf-8")
    assert await evolve.run_command(rt, "contract", file=str(contract)) == 0, rt.err.getvalue()
    old_skill = await skill_for_user(rt.ctx, rt.user_id)
    assert await evolve.cmd_finish(rt) == 0, rt.err.getvalue()
    assert await rt.drafts.get(rt.user_id, job_id) is None
    assert (await rt.jobs.get_job(rt.user_id, job_id)).status == "done"
    assert (await rt.canonical.snapshots(rt.user_id))[0].ref == before
    task = (await rt.ctx.store.list_evolve_tasks(rt.user_id))[0]
    assert task["status"] == "draft"
    assert task["summary"]["moved_claims"] == 2
    assert task["summary"]["adopted_by_document"] == {C: 2}
    branch_docs = await rt.canonical.list(rt.user_id, at=SnapshotRef(ref=task["branch"]))
    assert {d.path for d in branch_docs} == {C}
    assert CLAIM.strip() in branch_docs[0].body and OTHER.strip() in branch_docs[0].body
    out, err = io.StringIO(), io.StringIO()
    args = build_parser().parse_args(["--user", str(rt.user_id), "evolve", "show", task["task_id"], "--json"])
    assert await dispatch(rt.ctx, args, out=out, err=err) == 0
    assert json.loads(out.getvalue())["proposal"]["rationale"] == PROPOSAL["rationale"]
    assert (await skill_for_user(rt.ctx, rt.user_id)).content_hash == old_skill.content_hash
    out.seek(0); out.truncate()
    args = build_parser().parse_args(["--user", str(rt.user_id), "evolve", "adopt", task["task_id"]])
    assert await dispatch(rt.ctx, args, out=out, err=err) == 0
    job = await rt.jobs.claim_next(rt.user_id)
    assert job.kind == "evolve_adopt"
    rebuilt = []

    async def rebuild(ctx, user, ref):
        rebuilt.append((str(user), ref))

    monkeypatch.setattr("pneuma_knowledge_service.evolve_service.rebuild_projection", rebuild)
    await adopt_evolve_job(rt.ctx, rt.user_id, job)
    assert {d.path for d in await rt.canonical.list(rt.user_id)} == {C}
    assert (await rt.ctx.store.get_evolve_task(rt.user_id, task["task_id"]))["status"] == "adopted"
    skill = await skill_for_user(rt.ctx, rt.user_id)
    assert skill.instructions == contract.read_text()
    assert skill.version != old_skill.version and rebuilt
    assert (await composed_skill_readonly(rt.ctx.settings, rt.canonical, rt.user_id)) == skill
    assert await path_templates_for(rt.ctx.settings, rt.canonical, rt.user_id) == skill.path_templates
    assert (await rt.canonical.commit_trailer(rt.user_id, (await rt.canonical.snapshots(rt.user_id))[0], "Skill-Version"))


async def test_round_trip_into_the_existing_review_and_adopt_flow(tmp_path, monkeypatch):
    await round_trip(await make_runtime(tmp_path), tmp_path, monkeypatch)


async def test_refusals_restore_the_entire_draft_and_spend_budget(tmp_path, monkeypatch):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    before = await rt.drafts.get(rt.user_id, job_id)
    assert await propose(rt, tmp_path, {"packs": "not-a-list", "rationale": "evidence"}) == 2
    after = await rt.drafts.get(rt.user_id, job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["context"] == before["session"]["context"]
    assert after["session"]["spent"] == 1
    assert await propose(rt, tmp_path) == 0
    assert await evolve.run_command(rt, "retire", path=A) == 2
    assert "unnamed" in rt.err.getvalue()
    before = await rt.drafts.get(rt.user_id, job_id)
    # A damaged/future move implementation loses an anchor: post-check detects the loss.
    original = PatchDraft.move_claim

    def loses_anchor(self, from_path, anchor_id, to_path, heading):
        result = original(self, from_path, anchor_id, to_path, heading)
        self.delete_claim(to_path, anchor_id)
        return result

    monkeypatch.setattr(PatchDraft, "move_claim", loses_anchor)
    assert await evolve.run_command(rt, "move-claim", from_path=A, anchor="aa11", to_path=B) == 2
    after = await rt.drafts.get(rt.user_id, job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1


async def test_explicit_drops_are_visible_and_user_isolation_holds(tmp_path):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    assert await propose(rt, tmp_path, {**PROPOSAL, "dropped_anchors": ["c:aa11"]}) == 0
    assert await evolve.run_command(rt, "retire", path=A) == 0
    assert await evolve.cmd_finish(rt) == 0
    task = (await rt.jobs.list_evolve_tasks(rt.user_id))[0]
    assert task["dropped"][0]["anchor"] == "aa11"
    assert task["dropped"][0]["text"].strip() == CLAIM.strip()
    assert await rt.jobs.get_evolve_task(UserId("another-user"), task["task_id"]) is None
    assert await rt.drafts.list_open(UserId("another-user")) == []
    other_skill = await composed_skill_readonly(rt.ctx.settings, rt.canonical, UserId("another-user"))
    assert other_skill == load_skill_base("v1")


async def test_budget_and_abandon_use_the_compile_session_lifecycle(tmp_path):
    rt = await make_runtime(tmp_path)
    rt.max_tool_calls = 1
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    assert await propose(rt, tmp_path, {"packs": 4}) == 2
    assert await propose(rt, tmp_path) == draft.EXIT_BUDGET
    assert await draft.cmd_abandon(rt) == 0
    assert await rt.drafts.get(rt.user_id, job_id) is None
    assert (await rt.jobs.get_job(rt.user_id, job_id)).status == "queued"


async def test_the_two_doors_cannot_consume_each_others_drafts(tmp_path):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    rt.kind = "compile"
    assert await draft.cmd_finish(rt) == 1
    assert await draft.cmd_open(rt, job_id) == 2
    assert await rt.drafts.get(rt.user_id, job_id) is not None


async def test_proposals_and_component_evidence_never_enter_the_system_message(tmp_path, monkeypatch):
    rt = await make_runtime(tmp_path)
    job_id = await rt.jobs.enqueue(rt.user_id, "evolve", {})

    async def evidence(user):
        return "Synthetic request: find all delivery owners."

    monkeypatch.setattr(evolve, "collect_evolve_evidence", evidence)
    code, system, task = await evolve.open_round(rt, job_id)
    assert code == 0
    assert "Synthetic request" in task and "Synthetic request" not in system
    await propose(rt, tmp_path)
    rt.jobs.events.append({"path": "work/another.md", "type": "claim_added"})
    assert await evolve.open_round(rt, job_id) == (code, system, task)
    await draft.cmd_abandon(rt)
    code2, system2, task2 = await evolve.open_round(rt, job_id)
    assert code2 == 0 and system == system2 and task != task2


async def test_new_families_moves_and_contract_only_no_change(tmp_path):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    templates = ["work/delivery/{slug}.md", B]
    assert await propose(rt, tmp_path, {**PROPOSAL, "path_templates": templates}) == 0
    assert await evolve.cmd_check(rt) == 4
    assert await evolve.run_command(rt, "move-claim", from_path=A, anchor="aa11", to_path="work/delivery/aurora.md") == 0, rt.err.getvalue()
    assert await evolve.run_command(rt, "retire", path=A) == 0
    assert await evolve.cmd_finish(rt) == 0


async def test_from_proposal_keeps_its_reorganization(tmp_path):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    await propose(rt, tmp_path)
    await evolve.run_command(rt, "rename", path=A, new_path=C)
    await evolve.cmd_finish(rt)
    seed = (await rt.jobs.list_evolve_tasks(rt.user_id))[0]
    assert await evolve.cmd_open(rt, new=True, from_proposal=seed["task_id"]) == 0, rt.err.getvalue()
    assert await evolve.cmd_check(rt) == 0
    assert await evolve.cmd_finish(rt) == 0
    copied = (await rt.jobs.list_evolve_tasks(rt.user_id))[0]
    assert copied["task_id"] != seed["task_id"]
    assert {d.path for d in await rt.canonical.list(rt.user_id, at=SnapshotRef(ref=copied["branch"]))} == {B, C}


async def test_no_change_preserves_the_judgement(tmp_path):
    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    assert await propose(rt, tmp_path) == 0
    assert await evolve.cmd_finish(rt) == 0
    task = (await rt.jobs.list_evolve_tasks(rt.user_id))[0]
    assert task["status"] == "no_change"
    assert task["proposal"]["rationale"] == PROPOSAL["rationale"]


async def test_pack_revisions_and_later_additions_preserve_the_adopted_contract(tmp_path):
    from pneuma_knowledge_core.skill import SchemaPack
    from pneuma_knowledge_service.evolve_service import _compose_new_skill
    from pneuma_knowledge_service.skills import manifest_skill, packs_for_user

    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    pack = SchemaPack(pack_id="delivery", origin="evolved", extra_instructions="Track delivery owners.")
    state = await rt.drafts.get(rt.user_id, job_id)
    state["session"]["context"]["packs"] = [pack.model_dump()]
    await rt.drafts.put(rt.user_id, job_id, state)
    assert await propose(rt, tmp_path, {**PROPOSAL, "rename_packs": {"delivery": "owners"}}) == 0
    _, session = await draft._load(rt)
    _, raw = evolve._plan(session)
    assert json.loads(raw)["packs"][0]["pack_id"] == "owners"
    assert await propose(rt, tmp_path, {**PROPOSAL, "retire_packs": ["missing"]}) == 2
    assert await propose(rt, tmp_path, {**PROPOSAL, "retire_packs": ["delivery"], "path_templates": [A, B]}) == 0
    _, session = await draft._load(rt)
    _, raw = evolve._plan(session)
    assert json.loads(raw)["packs"] == []
    await draft.cmd_abandon(rt)
    await rt.canonical.commit_patch(rt.user_id, {"skill/manifest.json": raw}, message=with_skill_trailer(
        "synthetic adopted manifest", manifest_skill(rt.ctx.settings, json.loads(raw)),
    ))
    new_pack = SchemaPack(pack_id="projects", origin="evolved", extra_instructions="Track projects.",
                          extra_path_templates=["work/projects/{slug}.md"])
    skill, manifest = await _compose_new_skill(rt.ctx, rt.user_id, [new_pack])
    assert skill.path_templates == [A, B, "work/projects/{slug}.md"]
    assert manifest_skill(rt.ctx.settings, json.loads(manifest)) == skill
    assert await evolve.cmd_open(rt, new=True) == 0, rt.err.getvalue()
    assert await propose(rt, tmp_path, {**PROPOSAL, "packs": [new_pack.model_dump()]}) == 0
    _, session = await draft._load(rt)
    assert evolve._plan(session)[0] == skill
    await draft.cmd_abandon(rt)
    await rt.canonical.commit_patch(rt.user_id, {"skill/manifest.json": manifest},
                                    message=with_skill_trailer("synthetic pack adoption", skill))
    assert await packs_for_user(rt.ctx, rt.user_id) == [new_pack]
    assert await packs_for_user(rt.ctx, UserId("another-user")) == []


async def test_closed_volumes_survive_an_evolve_and_refuse_mutation(tmp_path):
    rt = await make_runtime(tmp_path)
    volume = A.removesuffix(".md") + "/a01.md"
    body = "# Earlier delivery\n\n- Earlier plan. [cite: synthetic-evolve ¶0] <!-- c:cc33 -->\n"
    await rt.canonical.commit_patch(rt.user_id, {
        volume: render_document({"doc_id": "d-volume", "type": "topic", "slug": "aurora-a01", "archived_from": A}, body),
    }, message=with_skill_trailer("synthetic closed volume", rt.skill))
    before = await rt.canonical.read_meta(rt.user_id, volume)
    assert await evolve.cmd_open(rt, new=True) == 0
    assert await propose(rt, tmp_path) == 0
    assert await evolve.run_command(rt, "rename", path=A, new_path=C) == 2
    assert await evolve.run_command(rt, "retire", path=volume) == 2
    assert await evolve.run_command(rt, "move-claim", from_path=volume, anchor="cc33", to_path=B) == 2
    assert await evolve.run_command(rt, "rename", path=B, new_path=C) == 0
    assert await evolve.cmd_check(rt) == 0, rt.out.getvalue()
    working, session = await draft._load(rt)
    working.read(volume).body += "A forbidden volume edit.\n"
    violations, _ = await evolve._gate(rt, working, session)
    assert "volume_closed" in {v.kind for v in violations}
    assert await evolve.cmd_finish(rt) == 0
    task = (await rt.jobs.list_evolve_tasks(rt.user_id))[0]
    assert await rt.canonical.read_meta_at(rt.user_id, volume, task["branch"]) == before


@pytest.mark.parametrize("failure", ["citation", "component"])
async def test_structural_postcheck_rolls_back_citation_and_component_violations(tmp_path, monkeypatch, failure):
    from pneuma_knowledge_core.compile.gate import Violation

    rt = await make_runtime(tmp_path)
    await evolve.cmd_open(rt, new=True)
    await propose(rt, tmp_path)
    job_id = (await rt.drafts.list_open(rt.user_id))[0]
    before = await rt.drafts.get(rt.user_id, job_id)
    if failure == "citation":
        original = PatchDraft.move_claim

        def corrupts_citation(self, *args):
            doc = original(self, *args)
            doc.body = doc.body.replace("synthetic-evolve ¶0", "invented-source ¶99")
            return doc

        monkeypatch.setattr(PatchDraft, "move_claim", corrupts_citation)
    else:
        def component_check(docs, base):
            if "aa11" in docs[B].body:
                return [Violation("component", B, "synthetic identity collision")]
            return []

        monkeypatch.setattr("pneuma_knowledge_core.evolve.gate.component_gate_checks", component_check)
    assert await evolve.run_command(rt, "move-claim", from_path=A, anchor="aa11", to_path=B) == 2
    after = await rt.drafts.get(rt.user_id, job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1


@pytest.mark.parametrize("attended", [False, True])
async def test_worker_agent_evolve_uses_the_door_and_never_the_model(tmp_path, monkeypatch, attended):
    from pneuma_knowledge_service.coding_agent.launcher import LaunchResult
    from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner
    from pneuma_knowledge_service.workers import compile_worker
    from pneuma_knowledge_service.wiring import executor_for

    rt = await make_runtime(tmp_path)
    rt.ctx.settings.agent_unattended = not attended
    rt.ctx.compile_executor = executor_for(rt.ctx.settings, "compile")
    rt.ctx.get_chat_model = lambda *a, **kw: pytest.fail("an agent evolve requested an API model")
    called = []

    async def runtime(ctx, user, **kw):
        assert user == rt.user_id and kw["executor"] == "agent:codex"
        return rt

    async def launch(request):
        called.append(request)
        assert "pkc evolve draft finish" in request.task_text
        assert "already open" in request.task_text
        assert str(tmp_path) in request.task_text or "/coding-agent-mode/" in request.task_text
        assert await propose(rt, tmp_path) == 0
        assert await evolve.run_command(rt, "rename", path=A, new_path=C) == 0
        assert await evolve.cmd_finish(rt) == 0
        return LaunchResult(exit_code=0, stdout="", stderr="")

    async def flush():
        return None

    def factory(**kwargs):
        return AgentRoundRunner(**kwargs, launcher=launch)

    rt.ctx.flush_traces = flush
    monkeypatch.setattr(evolve, "build_runtime", runtime)
    monkeypatch.setattr("pneuma_knowledge_service.coding_agent.round_runner.AgentRoundRunner", factory)
    monkeypatch.setattr("pneuma_knowledge_service.evolve_service.propose_evolution", lambda **kw: pytest.fail("model propose called"))
    job_id = await rt.jobs.enqueue(rt.user_id, "evolve", {})
    count = await compile_worker.drain_user(rt.ctx, None, None, rt.user_id)
    assert count == (0 if attended else 1)
    assert len(called) == (0 if attended else 1)
    assert (await rt.jobs.get_job(rt.user_id, job_id)).status == ("queued" if attended else "done")


async def test_worker_api_evolve_keeps_the_existing_model_path(tmp_path, monkeypatch):
    from pneuma_knowledge_service.workers import compile_worker
    from pneuma_knowledge_service.wiring import executor_for

    rt = await make_runtime(tmp_path)
    rt.ctx.settings.llm_model_compile = "openrouter:synthetic/compile"
    rt.ctx.compile_executor = executor_for(rt.ctx.settings, "compile")
    called = []

    async def model_path(ctx, user, job):
        called.append(job.job_id)
        await ctx.store.complete(user, job.job_id)

    async def flush():
        return None

    rt.ctx.flush_traces = flush
    monkeypatch.setattr(compile_worker, "run_evolve_job", model_path)
    monkeypatch.setattr(compile_worker, "process_agent_job", lambda *a: pytest.fail("API job used harness"))
    job_id = await rt.jobs.enqueue(rt.user_id, "evolve", {})
    assert await compile_worker.drain_user(rt.ctx, None, None, rt.user_id) == 1
    assert called == [job_id]


async def test_evolve_unattended_stopped_round_gets_one_repair(tmp_path):
    from pneuma_knowledge_service.coding_agent.backends import CODEX
    from pneuma_knowledge_service.coding_agent.launcher import LaunchResult
    from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner

    rt = await make_runtime(tmp_path)
    job_id = await rt.jobs.enqueue(rt.user_id, "evolve", {})
    await rt.jobs.claim(rt.user_id, job_id)
    requests = []

    async def launch(request):
        requests.append(request)
        if len(requests) == 2:
            assert "phase-1" in request.task_text
            assert "pkc evolve draft finish" in request.task_text
            await propose(rt, tmp_path)
        return LaunchResult(exit_code=0, stdout="", stderr="")

    async def resume(manifest):
        return False

    runner = AgentRoundRunner(CODEX, str(tmp_path), 10, launcher=launch, can_resume=resume)
    result = await runner.run_job(rt, job_id)
    assert result.launches == 2
    assert await rt.drafts.get(rt.user_id, job_id) is None
    assert (await rt.jobs.list_evolve_tasks(rt.user_id))[0]["status"] == "no_change"
