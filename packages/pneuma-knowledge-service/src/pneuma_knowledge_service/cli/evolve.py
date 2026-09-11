"""The evolve draft door: one persisted judgement, then gated structural commands.

The session, command transaction, budget, rollback, abandonment and exit codes are the
compile door's machinery. This sibling supplies only evolve's inputs, verbs and gate.
Nothing becomes live until the Owner adopts the ordinary evolve review record.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.compile.patch import PatchDraft, history_volume_owner
from pneuma_knowledge_core.compile.runner import render_violations
from pneuma_knowledge_core.compile.session import DraftSession, content_sha256
from pneuma_knowledge_core.components import collect_evolve_evidence, component_job
from pneuma_knowledge_core.domain.archive import is_archive_record, live_documents, restructurable_documents
from pneuma_knowledge_core.domain.ids import extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.evolve.contracts import phase1_contract, phase2_contract
from pneuma_knowledge_core.evolve.gate import run_evolve_gate
from pneuma_knowledge_core.evolve.propose import EvolveProposal, _propose_human, proposal_payload
from pneuma_knowledge_core.evolve.runner import EvolveResult, MAX_TOOL_CALLS, repair_round_budget
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import SchemaPack
from pneuma_knowledge_core.skill.contract import render_system_contract
from pneuma_knowledge_core.skill.version import SkillVersion

from ..evolve_service import get_task_with_expiry, persist_evolve_result, _source_bounds_port
from ..job_lanes import CANONICAL_LANE
from ..skills import (
    compose_manifest_skill, manifest_base, read_manifest,
    manifest_skill,
)
from . import draft as shared


@dataclass
class EvolveRuntime(shared.DraftRuntime):
    ctx: object = None


async def build_runtime(ctx, user_id, *, executor=None) -> EvolveRuntime:
    from .runtime import build_runtime as compile_runtime

    rt = await compile_runtime(ctx, user_id, executor=executor, kind="evolve")
    return EvolveRuntime(**vars(rt), ctx=ctx)


def _proposal(session: DraftSession) -> EvolveProposal | None:
    value = session.context.get("proposal")
    return EvolveProposal.model_validate(value) if value is not None else None


def _plan(session: DraftSession) -> tuple[SkillVersion, str]:
    """Recompute a proposal with pinned inputs; no store, clock or model is consulted."""
    data = session.context
    base = SkillVersion.model_validate(data["base_skill"])
    proposal = _proposal(session)
    packs = [SchemaPack.model_validate(p) for p in data["packs"]]
    if proposal is not None:
        known = {p.pack_id for p in packs}
        unknown = (set(proposal.retire_packs) | set(proposal.rename_packs)) - known
        if unknown:
            raise ValueError(f"unknown packs: {', '.join(sorted(unknown))}")
        if set(proposal.retire_packs) & set(proposal.rename_packs):
            raise ValueError("a pack cannot be both retired and renamed")
        packs = [
            p.model_copy(update={"pack_id": proposal.rename_packs.get(p.pack_id, p.pack_id)})
            for p in packs if p.pack_id not in proposal.retire_packs
        ] + proposal.packs
        names = [p.pack_id for p in packs]
        if any(not name.strip() for name in names) or len(set(names)) != len(names):
            raise ValueError("pack names must be non-blank and unique")
    text = data.get("contract_text")
    if text is not None:
        base = SkillVersion.from_parts(
            skill_id=base.skill_id,
            version=f"evolve-{content_sha256(base.content_hash + text)[:16]}",
            instructions=text,
            path_templates=base.path_templates,
            contract_rules=base.contract_rules,
            owner_voice_templates=base.owner_voice_templates,
        )
    templates = data.get("contract_templates", data.get("path_templates"))
    if templates is not None and proposal is not None:
        templates = [*templates, *(t for p in proposal.packs for t in p.extra_path_templates)]
    if proposal is not None and proposal.path_templates is not None:
        templates = proposal.path_templates
    skill = compose_manifest_skill(base, packs, templates)
    manifest = {
        "base_version": base.version,
        "base_contract": base.model_dump(mode="json"),
        "packs": [p.model_dump() for p in packs],
        "content_hash": skill.content_hash,
        "agent_evolved": True,
    }
    if templates is not None:
        manifest["path_templates"] = templates
    return skill, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@shared.draft_command
async def open_round(
    rt: EvolveRuntime, job_id: str, *, claim: bool = True, from_proposal: str = "",
) -> tuple[int, str, str]:
    await shared.require_open_slot(rt, job_id)
    existing = await rt.drafts.get(rt.user_id, job_id)
    if existing is not None:
        if existing.get("kind", "compile") != "evolve":
            print("this job has a compile draft; use `pkc draft`", file=rt.err)
            return shared.EXIT_REFUSED, "", ""
        session = DraftSession.from_state(existing["session"])
        await rt.drafts.put(rt.user_id, job_id, existing)
        return shared.EXIT_OK, session.context["system_text"], session.context["task_text"]
    outside = await shared.outside_write(rt)
    if outside:
        print(outside, file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    job = await rt.jobs.get_job(rt.user_id, job_id)
    if job is None:
        print(f"no such job for this user: {job_id}", file=rt.err)
        return shared.EXIT_NOTHING, "", ""
    if job.kind != "evolve":
        print(f"job {job_id} is not an evolve job", file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    seed = None
    if from_proposal:
        seed = await get_task_with_expiry(rt.ctx, rt.user_id, from_proposal)
        if seed is None or seed["status"] != "draft":
            print("--from must name this user's live evolve proposal", file=rt.err)
            return shared.EXIT_REFUSED, "", ""
    job = await rt.jobs.claim(rt.user_id, job_id, claimed_by=rt.draft_executor) if claim else job
    if job is None or getattr(job, "status", "claimed") != "claimed":
        print(f"job {job_id} could not be claimed; this user may have work in flight", file=rt.err)
        return (shared.EXIT_NOTHING if claim else shared.EXIT_REFUSED), "", ""
    if not claim and getattr(job, "claimed_by", "worker") not in ("worker", rt.draft_executor):
        raise shared.DraftOwnershipError(f"job {job_id} is claimed by {job.claimed_by}; cannot join its round")
    try:
        snapshots = await rt.canonical.snapshots(rt.user_id)
        base_ref = seed["base_ref"] if seed else snapshots[0].ref if snapshots else ""
        docs = live_documents(await rt.canonical.list(rt.user_id, at=SnapshotRef(ref=base_ref))
                              if base_ref else await rt.canonical.list(rt.user_id))
        if seed:
            raw = await rt.canonical.read_meta_at(rt.user_id, "skill/manifest.json", base_ref)
            manifest = json.loads(raw) if raw else {}
        else:
            manifest = await read_manifest(rt.ctx, rt.user_id) or {}
        base, _ = manifest_base(rt.ctx.settings, manifest)
        current = manifest_skill(rt.ctx.settings, manifest) if manifest else rt.skill
        packs = manifest.get("packs", []) if rt.ctx.settings.user_schema_packs or manifest.get("agent_evolved") else []
        tasks = await rt.ctx.store.list_evolve_tasks(rt.user_id)
        baseline = tasks[0]["created_at"] if tasks else None
        events = await rt.ctx.store.list_compile_events(rt.user_id)
        recent = [e for e in events if baseline is None or e["created_at"] > baseline]
        async with component_job(str(rt.user_id)):
            demand = await collect_evolve_evidence(str(rt.user_id))
        task_text = _propose_human(
            current, recent, [d.path for d in restructurable_documents(docs)], demand,
        ) + "\n\n" + prompt("steward.evolve.packs", packs=json.dumps(packs, ensure_ascii=False))
        system_text = "\n\n".join((
            render_system_contract(current), phase1_contract(), phase2_contract(),
            prompt("steward.skill.evolve"),
        ))
        data = {
            "task_id": uuid.uuid4().hex,
            "base_ref": base_ref,
            "base_skill": base.model_dump(mode="json"),
            "current_templates": current.path_templates,
            "packs": packs,
            "path_templates": manifest.get("path_templates"),
            "system_text": system_text,
            "task_text": task_text,
        }
        draft = PatchDraft.from_canonical(docs, current.path_templates)
        session = DraftSession(
            user_id=str(rt.user_id), job_id=job_id, kind="evolve", context=data,
            **shared.ownership_fields(rt),
            budget=rt.max_tool_calls or MAX_TOOL_CALLS,
            max_tool_calls=rt.max_tool_calls or MAX_TOOL_CALLS,
            task_sha256=content_sha256(task_text),
            skill_id=current.skill_id, skill_version=current.version,
            skill_content_hash=current.content_hash,
        )
        if seed:
            data["proposal"] = seed["proposal"]
            raw = await rt.canonical.read_meta_at(rt.user_id, "skill/manifest.json", seed["branch"])
            seeded_manifest = json.loads(raw) if raw else {}
            # A copied draft retains its exact revised contract/pack plan and branch files.
            if seeded_manifest.get("base_contract"):
                seeded_base = SkillVersion.model_validate(seeded_manifest["base_contract"])
                if seeded_base.instructions != base.instructions:
                    data["contract_text"] = seeded_base.instructions
            if "path_templates" in seeded_manifest:
                data["path_templates"] = seeded_manifest["path_templates"]
            seeded_docs = live_documents(await rt.canonical.list(rt.user_id, at=SnapshotRef(ref=seed["branch"])))
            seeded = PatchDraft.from_canonical(seeded_docs, current.path_templates)
            state = draft.to_state()
            state["working"] = seeded.to_state()["working"]
            draft = PatchDraft.from_state(state)
            skill, _ = _plan(session)
            draft.path_templates = list(dict.fromkeys([*current.path_templates, *skill.path_templates]))
        await shared._store(rt, draft, session)
    except (ValueError, KeyError) as exc:
        await rt.jobs.release(rt.user_id, job_id)
        print(str(exc), file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    return shared.EXIT_OK, system_text, task_text


@shared.draft_command
async def cmd_open(rt: EvolveRuntime, job_id: str = "", *, new=False, from_proposal="") -> int:
    if new:
        # The canonical lane's open rounds only: a derived-lane round (an episodes judgement
        # the worker is running) shares nothing with an evolve round (`job_lanes.py`).
        if await shared.open_drafts_in_lane(rt, CANONICAL_LANE):
            print("a draft is already open; finish or abandon it first", file=rt.err)
            return shared.EXIT_REFUSED
        job_id = await rt.jobs.enqueue(rt.user_id, "evolve", {})
    code, system, task = await open_round(rt, job_id, from_proposal=from_proposal)
    if code == shared.EXIT_OK:
        shared._print_round(rt, system, task)
    return code


async def _gate(rt: EvolveRuntime, draft: PatchDraft, session: DraftSession):
    skill, _ = _plan(session)
    # These existing paths are carried through as frozen knowledge, outside the revised
    # family's writable templates. Giving the gate exact paths grants no write capability:
    # records have its own read-only check; volumes are compared against the pinned base.
    original_templates = session.context.get("current_templates", rt.skill.path_templates)
    volumes = {
        path: doc for path, doc in draft.base_documents().items()
        if history_volume_owner(path, original_templates) is not None
    }
    frozen_paths = [*volumes, *(
        path for path, doc in draft.base_documents().items() if is_archive_record(doc)
    )]
    violations, dropped = await run_evolve_gate(
        draft, source_bounds=_source_bounds_port(rt.ctx, rt.user_id),
        path_templates=[*skill.path_templates, *frozen_paths],
    )
    for path, base in volumes.items():
        if draft.documents().get(path) != base:
            violations.append(Violation("volume_closed", path, prompt(
                "gate.volume_closed", owner=history_volume_owner(path, original_templates),
            )))
    proposal = _proposal(session)
    named = {a.removeprefix("c:") for a in proposal.dropped_anchors} if proposal else set()
    violations += [
        Violation("anchor_continuity", d.old_path, prompt("steward.evolve.unnamed_drop", anchor=d.anchor))
        for d in dropped if d.anchor not in named
    ]
    if proposal is None:
        violations.append(Violation("proposal", "", prompt("steward.evolve.proposal_required")))
    return violations, dropped


@shared.draft_command
async def cmd_status(rt: EvolveRuntime) -> int:
    loaded = await shared._load(rt)
    if loaded is None:
        return shared.EXIT_NOTHING
    draft, session = loaded
    print(f"job: {session.job_id}\nround: {session.round}\nbudget: {session.remaining} of {session.budget} calls remain", file=rt.out)
    print("proposal: " + ("supplied" if _proposal(session) else "owed"), file=rt.out)
    await cmd_check(rt)
    return shared.EXIT_OK


async def run_command(rt: EvolveRuntime, name: str, **args) -> int:
    async def execute(draft: PatchDraft, session: DraftSession) -> str:
        async with component_job(str(rt.user_id)):
            baseline, _ = await _gate(rt, draft, session)
            if name == "propose":
                value = shared.read_json_arg(None, args.get("file"))
                proposal = EvolveProposal.model_validate(value)
                if not proposal.rationale.strip():
                    raise ValueError("proposal rationale must cite the evidence and be non-blank")
                session.context["proposal"] = proposal_payload(proposal)
            elif name == "contract":
                text = shared.read_text_arg(args.get("file"))
                if not text.strip() or len(text) > 100_000:
                    raise ValueError("contract must be non-blank and at most 100000 characters")
                if text.startswith("---\n"):
                    from pneuma_knowledge_core.compile.documents import parse_document
                    meta, body = parse_document(text)
                    if not body.strip():
                        raise ValueError("contract instructions must be non-blank")
                    if "path_templates" in meta:
                        session.context["contract_templates"] = meta["path_templates"]
                    text = body
                session.context["contract_text"] = text
            else:
                if _proposal(session) is None:
                    raise AnchorToolError(prompt("steward.evolve.proposal_required"))
                if name == "move-claim":
                    if args["to_path"] not in draft.documents():
                        source = draft.read(args["from_path"])
                        title = args["to_path"].rsplit("/", 1)[-1].removesuffix(".md")
                        draft.create_document(args["to_path"], {"type": source.frontmatter["type"], "slug": title}, f"# {title}\n")
                    draft.move_claim(args["from_path"], args["anchor"], args["to_path"], "Claims")
                elif name == "rename":
                    draft.rename_document(args["path"], args["new_path"])
                elif name == "retire":
                    draft.retire_document(args["path"])
                else:
                    raise ValueError(f"unknown evolve draft command: {name}")
            skill, _ = _plan(session)
            # Transitioning a family needs both the old and new paths while commands run.
            # Finish checks the final set only, so a retired family cannot survive adopt.
            draft.path_templates = list(dict.fromkeys([*draft.path_templates, *skill.path_templates]))
            violations, _ = await _gate(rt, draft, session)
            previous = {(v.kind, v.path, v.detail) for v in baseline}
            broke = [v for v in violations if (v.kind, v.path, v.detail) not in previous]
            if name in ("propose", "contract"):
                broke = [v for v in broke if v.kind != "path"]
            if broke:
                raise AnchorToolError("\n".join(v.render() for v in broke))
        return f"{name}: accepted"

    return await shared.apply_call(rt, name, execute, owed=lambda d, s: [
        prompt("steward.evolve.proposal_required")
    ] if _proposal(s) is None else [])


@shared.draft_command
async def cmd_check(rt: EvolveRuntime) -> int:
    loaded = await shared._load(rt)
    if loaded is None:
        return shared.EXIT_NOTHING
    async with component_job(str(rt.user_id)):
        violations, dropped = await _gate(rt, *loaded)
    print(render_violations(violations) if violations else "gate: clean.", file=rt.out)
    for item in dropped:
        print(f"dropped: c:{item.anchor} ({item.old_path})", file=rt.out)
    return shared.EXIT_GATE if violations else shared.EXIT_OK


@shared.draft_command
async def cmd_finish(rt: EvolveRuntime) -> int:
    loaded = await shared._load(rt)
    if loaded is None:
        return shared.EXIT_NOTHING
    draft, session = loaded
    async with component_job(str(rt.user_id)):
        violations, dropped = await _gate(rt, draft, session)
    session = session.spend()
    if violations and session.round == "first":
        budget = repair_round_budget(len(violations), session.max_tool_calls)
        session = replace(session, round="repair", budget=budget, spent=0, noticed=False,
                          cut_off=session.remaining == 0,
                          violations=tuple((v.kind, v.path, v.detail) for v in violations))
        await shared._store(rt, draft, session)
        print(render_violations(violations, next_budget=budget), file=rt.err)
        return shared.EXIT_GATE
    proposal = _proposal(session)
    if proposal is None:
        await rt.jobs.complete(rt.user_id, session.job_id, ok=False, detail="evolve proposal missing", executor=rt.executor)
    else:
        skill, manifest = _plan(session)
        changed = draft.is_dirty() or skill.content_hash != session.skill_content_hash
        result = EvolveResult(
            status="aborted" if violations else "completed" if changed else "noop",
            files=draft.to_files(), dropped=dropped,
            removed_paths=tuple(sorted(set(draft.base_documents()) - set(draft.documents()))),
            summary=_summary(draft, dropped),
            tool_calls=session.spent, token_usage={},
        )
        await persist_evolve_result(
            rt.ctx, rt.user_id, session.job_id, session.context["task_id"], proposal, result,
            manifest, base_ref=session.context["base_ref"], executor=rt.executor,
        )
    await rt.drafts.delete(rt.user_id, session.job_id, executor=rt.draft_executor)
    if violations:
        print(render_violations(violations), file=rt.err)
        return shared.EXIT_GATE
    print(f"evolve proposal: {session.context['task_id']}; adopt is the Owner's decision", file=rt.out)
    return shared.EXIT_OK


def _summary(draft: PatchDraft, dropped) -> dict:
    old_paths = {
        anchor: path for path, doc in draft.base_documents().items()
        for anchor in extract_anchors(doc.body)
    }
    adopted: dict[str, int] = {}
    for path, doc in draft.documents().items():
        for anchor in extract_anchors(doc.body):
            if anchor in old_paths and old_paths[anchor] != path:
                adopted[path] = adopted.get(path, 0) + 1
    return {
        "new_documents": len(set(draft.documents()) - set(draft.base_documents())),
        "moved_claims": sum(adopted.values()),
        "merged_claims": len(dropped),
        "adopted_by_document": adopted,
    }


async def cmd_adopt(ctx, user_id, task_id: str, *, out, err) -> int:
    task = await get_task_with_expiry(ctx, user_id, task_id)
    if task is None or task["status"] != "draft":
        print("no live evolve proposal for this user", file=err)
        return shared.EXIT_NOTHING
    jobs = await ctx.store.list_jobs(user_id)
    if any(j["kind"] == "evolve_adopt" and j["status"] in ("queued", "claimed")
           and j["payload"].get("task_id") == task_id for j in jobs):
        print("this proposal already has an adopt job", file=err)
        return shared.EXIT_REFUSED
    job_id = await ctx.store.enqueue(user_id, "evolve_adopt", {"task_id": task_id})
    print(f"evolve adopt queued: {job_id}", file=out)
    return shared.EXIT_OK
