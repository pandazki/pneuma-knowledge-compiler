"""`pkc index episodes`: a persisted retrieval judgement over one source's L0 blocks.

The compile door owns the command transaction, budget, claim, TTL and abandonment. This
door supplies the interval gates and publishes a kept manifest plus derived L2 vectors.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace

from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import first_round_budget, repair_round_budget
from pneuma_knowledge_core.compile.session import DraftSession, content_sha256, handles_for
from pneuma_knowledge_core.domain.authorship import block_authorship
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.ingest.episodes import episode_rules, parse_episode_proposal, uncovered_blocks
from pneuma_knowledge_core.ingest.semantic import (
    OVERLAP_SMART, blocks_content_digest, chunk_result_digest, encode_manifest_episodes,
)
from pneuma_knowledge_core.prompts import prompt

from ..coding_agent.backends import backend
from ..coding_agent.install import installed_hash, steward_skill_hash
from ..wiring import chunks_from_agent_manifest, embed_l2_chunks, executor_for
from . import draft as shared


@dataclass
class EpisodesRuntime(shared.DraftRuntime):
    ctx: object = None


async def build_runtime(ctx, user_id, *, executor=None) -> EpisodesRuntime:
    from .runtime import build_runtime as compile_runtime

    rt = await compile_runtime(ctx, user_id, executor=executor, kind="episodes")
    selected = executor_for(ctx.settings, "compile")
    digest = steward_skill_hash()
    if not digest and selected.is_agent:
        digest = installed_hash(os.getcwd(), backend(selected.backend))
    return EpisodesRuntime(**{**vars(rt), "executor_skill": digest}, ctx=ctx)


def _source_surface(source) -> str:
    roles = {row["index"]: row for row in block_authorship(source.raw)}
    return json.dumps({
        "source_id": str(source.raw.source_id),
        "source_context": source.raw.retrieval_context_lines(),
        "structure": source.structure.model_dump(mode="json"),
        "blocks": [
            {**block.model_dump(mode="json"), **roles.get(block.index, {})}
            for block in sorted(source.blocks, key=lambda b: b.index)
        ],
    }, ensure_ascii=False, indent=2)


@shared.draft_command
async def open_round(rt: EpisodesRuntime, job_id: str, *, claim=True) -> tuple[int, str, str]:
    await shared.require_open_slot(rt, job_id)
    existing = await rt.drafts.get(rt.user_id, job_id)
    if existing is not None:
        if existing.get("kind") != "episodes":
            print("this job has a different kind of draft", file=rt.err)
            return shared.EXIT_REFUSED, "", ""
        context = existing["session"]["context"]
        await rt.drafts.put(rt.user_id, job_id, existing)
        return shared.EXIT_OK, context["system_text"], context["task_text"]
    job = await rt.jobs.get_job(rt.user_id, job_id)
    if job is None:
        print(f"no such job for this user: {job_id}", file=rt.err)
        return shared.EXIT_NOTHING, "", ""
    if job.kind != "episodes":
        print(f"job {job_id} is not an episodes job", file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    selected = executor_for(rt.ctx.settings, "compile")
    if not selected.is_agent:
        print(prompt("steward.episodes.executor_required"), file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    job = await rt.jobs.claim(rt.user_id, job_id, claimed_by=rt.draft_executor) if claim else job
    if job is None or job.status != "claimed":
        print(f"job {job_id} could not be claimed; this user may have work in flight", file=rt.err)
        return (shared.EXIT_NOTHING if claim else shared.EXIT_REFUSED), "", ""
    if not claim and getattr(job, "claimed_by", "worker") not in ("worker", rt.draft_executor):
        raise shared.DraftOwnershipError(f"job {job_id} is claimed by {job.claimed_by}; cannot join its round")
    try:
        source_id = SourceId(str(job.payload["source_id"]))
        source = await rt.ctx.store.get(rt.user_id, source_id)
        budget = first_round_budget(1, rt.max_tool_calls)
        system = episode_rules()
        task = prompt("steward.episodes.task", source=_source_surface(source), budget=budget)
        context = {
            "system_text": system, "task_text": task,
            "content_digest": blocks_content_digest(source.blocks),
            "block_indices": sorted(b.index for b in source.blocks),
            "model": selected.spec, "executor": rt.executor,
            "Executor-Skill": rt.executor_skill,
            "chunk_size": rt.ctx.settings.chunk_size,
            "chunk_overlap": rt.ctx.settings.chunk_overlap,
        }
        recorded = await rt.ctx.store.get_chunk_manifest(rt.user_id, source_id)
        if recorded and isinstance(recorded["segments"], dict) and recorded["segments"].get("job_id") == job_id:
            # A crash after publishing the record must resume its judgement, never author
            # a replacement. Rebuilding vectors is the only remaining work.
            context["manifest"] = recorded
            context["proposal"] = recorded["segments"]["episodes"]
            context["content_digest"] = recorded["content_digest"]
        session = DraftSession(
            user_id=str(rt.user_id), job_id=job_id, kind="episodes", context=context,
            **shared.ownership_fields(rt),
            handle_by_real=handles_for([str(source_id)]), budget=budget,
            max_tool_calls=rt.max_tool_calls, task_sha256=content_sha256(task),
            skill_id=rt.skill.skill_id, skill_version=rt.skill.version,
            skill_content_hash=rt.skill.content_hash,
        )
        await shared._store(rt, PatchDraft.from_canonical([], []), session)
    except (KeyError, ValueError) as exc:
        await rt.jobs.release(rt.user_id, job_id)
        print(str(exc), file=rt.err)
        return shared.EXIT_REFUSED, "", ""
    return shared.EXIT_OK, system, task


async def cmd_open(rt: EpisodesRuntime, job_id: str) -> int:
    code, system, task = await open_round(rt, job_id)
    if code == shared.EXIT_OK:
        shared._print_round(rt, system, task)
    return code


def _residue(session: DraftSession) -> str:
    proposal = session.context.get("proposal")
    if proposal is None:
        return prompt("steward.episodes.proposal_required")
    indices = session.context["block_indices"]
    episodes = parse_episode_proposal(proposal, indices)
    return prompt("steward.episodes.no_episode", blocks=json.dumps(uncovered_blocks(episodes, indices)))


async def _published_manifest(rt: EpisodesRuntime, session: DraftSession) -> dict | None:
    """The record is the publication boundary, even if the following draft write crashed."""
    manifest = await rt.ctx.store.get_chunk_manifest(rt.user_id, SourceId(session.source_ids[0]))
    if manifest and isinstance(manifest["segments"], dict) and manifest["segments"].get("job_id") == session.job_id:
        return manifest
    return None


@shared.draft_command
async def cmd_status(rt: EpisodesRuntime) -> int:
    loaded = await shared._load(rt)
    if loaded is None:
        return shared.EXIT_NOTHING
    _, session = loaded
    print(f"job: {session.job_id}\nround: {session.round}\nbudget: {session.remaining} of {session.budget} calls remain", file=rt.out)
    print(_residue(session), file=rt.out)
    return shared.EXIT_OK


async def cmd_propose(rt: EpisodesRuntime, *, file: str = "-") -> int:
    async def execute(draft, session):
        if "manifest" in session.context or await _published_manifest(rt, session):
            raise ValueError(prompt("steward.episodes.recorded"))
        # Reading/parsing is inside the shared transaction: even malformed JSON spends a
        # call and cannot disturb the last accepted selection.
        try:
            value = shared.read_json_arg(None, file)
        except shared.TextArgError as exc:
            raise ValueError(str(exc)) from None
        episodes = parse_episode_proposal(value, session.context["block_indices"])
        session.context["proposal"] = [asdict(episode) for episode in episodes]
        return _residue(session)

    return await shared.apply_call(rt, "episodes.propose", execute, owed=lambda d, s: [_residue(s)])


@shared.draft_command
async def cmd_finish(rt: EpisodesRuntime) -> int:
    loaded = await shared._load(rt)
    if loaded is None:
        return shared.EXIT_NOTHING
    draft, session = loaded
    data = session.context
    published = await _published_manifest(rt, session)
    if published is not None:
        data["manifest"] = published
        data["proposal"] = published["segments"]["episodes"]
        data["content_digest"] = published["content_digest"]
    source_id = SourceId(session.source_ids[0])
    try:
        try:
            source = await rt.ctx.store.get(rt.user_id, source_id)
        except KeyError:
            raise ValueError(prompt("steward.episodes.source_changed")) from None
        if blocks_content_digest(source.blocks) != data["content_digest"]:
            raise ValueError(prompt("steward.episodes.source_changed"))
        if "proposal" not in data:
            raise ValueError(prompt("steward.episodes.proposal_required"))
        episodes = parse_episode_proposal(data["proposal"], [b.index for b in source.blocks])
    except ValueError as exc:
        session = session.spend()
        if session.round == "first":
            session = replace(
                session, round="repair", spent=0, noticed=False,
                budget=repair_round_budget(1, first_round_budget(1, session.max_tool_calls)),
                violations=(("episodes", str(source_id), str(exc)),),
            )
            await shared._store(rt, draft, session)
        else:
            await rt.jobs.complete(rt.user_id, session.job_id, ok=False, detail=str(exc), executor=rt.executor)
            await rt.drafts.delete(rt.user_id, session.job_id, executor=rt.draft_executor)
        print(str(exc), file=rt.err)
        return shared.EXIT_GATE
    manifest = data.get("manifest")
    if manifest is None:
        digest = data["Executor-Skill"] or rt.executor_skill
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            print(prompt("steward.episodes.skill_required"), file=rt.err)
            return shared.EXIT_REFUSED
        envelope = encode_manifest_episodes(episodes, overlap=OVERLAP_SMART)
        envelope.update({
            "producer": "agent", "coverage": "partial", "Executor-Skill": digest,
            "executor": data["executor"], "job_id": session.job_id,
            "chunk_size": data["chunk_size"], "chunk_overlap": data["chunk_overlap"],
        })
        manifest = {
            "strategy": "semantic", "model": data["model"],
            "content_digest": data["content_digest"], "segments": envelope,
        }
    chunks = await chunks_from_agent_manifest(rt.ctx, source_id, source.blocks, source.structure, manifest)
    if "manifest" not in data:
        manifest["result_digest"] = chunk_result_digest(chunks)
        await rt.ctx.store.put_chunk_manifest(rt.user_id, source_id, **manifest)
        data["manifest"] = manifest
        await shared._store(rt, draft, session.spend())
    if rt.ctx.settings.semantic_retrieval == "on":
        embedded = await embed_l2_chunks(rt.ctx, chunks, source) if chunks else []
        await rt.ctx.vectors.delete_source_chunks(rt.user_id, source_id)
        if embedded:
            await rt.ctx.vectors.upsert_chunks(rt.user_id, embedded, archived=source.raw.archived_at is not None)
    await rt.jobs.complete(rt.user_id, session.job_id, ok=True, detail=f"episodes: {len(episodes)}", executor=data["executor"])
    await rt.drafts.delete(rt.user_id, session.job_id, executor=rt.draft_executor)
    print(prompt("steward.episodes.finished", count=len(episodes)), file=rt.out)
    print(_residue(session), file=rt.out)
    return shared.EXIT_OK
