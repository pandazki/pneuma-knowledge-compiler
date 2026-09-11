"""`pkc index episodes`: a persisted retrieval judgement over one source's L0 blocks.

The compile door owns the command transaction, budget, claim, TTL and abandonment. This
door supplies the interval gates and publishes a kept manifest plus derived L2 vectors.

A source too long for one round's input is judged in WINDOWS of whole blocks
(`agent_episodes_window_chars`): one episodes job per window, each round shown only its
window and gated to it, each judgement a kept record of its own. The source has L2 chunks
once every window of it is recorded, and not before.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, replace

from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import first_round_budget, repair_round_budget
from pneuma_knowledge_core.compile.session import DraftSession, content_sha256, handles_for
from pneuma_knowledge_core.domain.authorship import block_authorship
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.ingest.episodes import (
    episode_rules, episode_windows, parse_episode_proposal, uncovered_blocks,
)
from pneuma_knowledge_core.ingest.semantic import (
    OVERLAP_SMART, blocks_content_digest, chunk_result_digest, encode_manifest_episodes,
)
from pneuma_knowledge_core.prompts import prompt

from ..coding_agent.backends import backend
from ..coding_agent.install import installed_hash, steward_skill_hash
from ..wiring import (
    agent_judgement, agent_record_matches, chunks_from_agent_manifest,
    chunks_from_agent_manifests, embed_l2_chunks, executor_for,
)
from . import draft as shared

log = logging.getLogger(__name__)


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


def _block_entries(source) -> list[dict]:
    roles = {row["index"]: row for row in block_authorship(source.raw)}
    return [
        {**block.model_dump(mode="json"), **roles.get(block.index, {})}
        for block in sorted(source.blocks, key=lambda b: b.index)
    ]


def _source_surface(source, window: tuple[int, int] | None = None, *, entries=None) -> str:
    """The material a round judges: the whole source, or one window of it.

    A window carries its own blocks and the sections that reach into it, in the source's
    own numbering, so every boundary proposed there is already a source coordinate (I4).
    """
    entries = _block_entries(source) if entries is None else entries
    structure = source.structure.model_dump(mode="json")
    if window is None:
        return json.dumps({
            "source_id": str(source.raw.source_id),
            "source_context": source.raw.retrieval_context_lines(),
            "structure": structure,
            "blocks": entries,
        }, ensure_ascii=False, indent=2)
    start, end = window
    return json.dumps({
        "source_id": str(source.raw.source_id),
        "source_context": source.raw.retrieval_context_lines(),
        "window": {"start": start, "end": end},
        "structure": {**structure, "sections": [
            s for s in structure.get("sections", [])
            if s["start_block"] <= end and s["end_block"] >= start
        ]},
        "blocks": [e for e in entries if start <= e["index"] <= end],
    }, ensure_ascii=False, indent=2)


def _window_task(source, window: tuple[int, int], budget: int, *, entries=None) -> str:
    indices = sorted(b.index for b in source.blocks)
    return prompt(
        "steward.episodes.window_task", source=_source_surface(source, window, entries=entries),
        budget=budget, start=window[0], end=window[1], first=indices[0], last=indices[-1],
    )


def _rendered(value, depth: int) -> int:
    """What `value` adds to the surface as one list element `depth` levels deep (indent=2)."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return len(text) + 2 * depth * (text.count("\n") + 1) + 2


def source_windows(source, bound: int) -> list[tuple[int, int]]:
    """The windows this source is judged in under `bound` characters of task; one = whole.

    Measured on what a task carries — each block's rendered entry and each section's, plus the
    task's fixed frame — rather than on the bare text: a chat of many short blocks is mostly
    JSON framing, and it is the framed task that has to fit the harness's input.
    """
    if not source.blocks:
        return []
    entries = _block_entries(source)
    costs = {e["index"]: _rendered(e, 2) for e in entries}
    if bound <= 0:
        return episode_windows(list(costs.items()), 0)
    order = sorted(costs)
    sections = [
        (s.start_block, s.end_block, _rendered(s.model_dump(mode="json"), 3))
        for s in source.structure.sections
    ]
    for start, end, cost in sections:
        home = next((i for i in order if start <= i <= end), None)
        if home is not None:
            costs[home] += cost

    def opening(index: int) -> int:
        # A window that opens inside a section repeats it in its own structure map.
        return sum(cost for start, end, cost in sections if start < index <= end)

    # The fixed frame: the task with no block and no section in it, at the widest numbers.
    last = order[-1]
    empty = source.model_copy(update={"structure": source.structure.model_copy(update={"sections": []})})
    frame = len(_window_task(empty, (last, last), 10**6, entries=[]))
    return episode_windows(list(costs.items()), max(1, bound - frame), opening=opening)


@dataclass(frozen=True)
class EpisodesSplit:
    windows: list[tuple[int, int]]
    created: list[str]
    detail: str


def _job_window(payload: dict) -> tuple[int, int] | None:
    """The job's `window` — an inclusive block span, like every block span (I4) — or None."""
    raw = payload.get("window")
    if raw is None:
        return None
    start, end = (raw.get("start"), raw.get("end")) if isinstance(raw, dict) else (None, None)
    if type(start) is not int or type(end) is not int or end < start:
        raise ValueError(f"episodes.window: malformed window {raw!r}")
    return start, end


async def split_oversized(ctx, jobs, user_id, job) -> EpisodesSplit | None:
    """Replace an unwindowed episodes job over a source too long for one round.

    None when the job stays one round: it already names a window, its source is gone (the
    ordinary path says so), or the source fits. Otherwise one windowed job per window not
    already recorded or queued, every one at the original's place in the queue so they stay
    ahead of the source's compile, and the original completed `ok` with what it became. This
    is also what migrates an unwindowed job queued before windows existed.
    """
    payload = dict(getattr(job, "payload", {}) or {})
    if payload.get("window") is not None:
        return None
    try:
        source_id = SourceId(str(payload["source_id"]))
        source = await ctx.store.get(user_id, source_id)
    except (KeyError, ValueError):
        return None
    bound = int(ctx.settings.agent_episodes_window_chars)
    windows = source_windows(source, bound)
    if len(windows) < 2:
        return None
    recorded = {
        (int(row["window_start"]), int(row["window_end"]))
        for row in await ctx.store.get_chunk_manifest_windows(user_id, source_id)
        if agent_record_matches(ctx, row, source.blocks)
    }
    pending = set()
    for row in await jobs.list_jobs(user_id):
        window = (row.get("payload") or {}).get("window")
        if (row["kind"] == "episodes" and row["status"] in ("queued", "claimed")
                and row["payload"].get("source_id") == str(source_id) and isinstance(window, dict)):
            pending.add((window.get("start"), window.get("end")))
    created: list[str] = []
    for start, end in windows:
        if (start, end) in recorded or (start, end) in pending:
            continue
        created.append(await jobs.enqueue(
            user_id, "episodes",
            {"source_id": str(source_id), "window": {"start": start, "end": end}},
            order_at=getattr(job, "order_at", None),
        ))
    skipped = len(windows) - len(created)
    detail = f"episodes: split into {len(windows)} windows" + (
        f"; {skipped} already recorded or queued" if skipped else ""
    )
    await jobs.complete(user_id, job.job_id, ok=True, detail=detail)
    log.info(
        "episodes job %s for %s: %d blocks over the %d-character window bound, split into "
        "%d windows (%d queued, %d already recorded or queued)",
        job.job_id, source_id, len(source.blocks), bound, len(windows), len(created), skipped,
    )
    return EpisodesSplit(windows=windows, created=created, detail=detail)


async def _recorded(rt, source_id, window: tuple[int, int] | None) -> dict | None:
    """The kept record this round publishes to: the source's manifest, or its window's."""
    if window is None:
        return await rt.ctx.store.get_chunk_manifest(rt.user_id, source_id)
    for row in await rt.ctx.store.get_chunk_manifest_windows(rt.user_id, source_id):
        if int(row["window_start"]) == window[0]:
            return row
    return None


def _window(session: DraftSession) -> tuple[int, int] | None:
    window = session.context.get("window")
    return (int(window[0]), int(window[1])) if window else None


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
        window = _job_window(job.payload)
        if window is None and claim:
            # An attended open meets the same too-long source the worker splits at its
            # claim, and answers it the same way rather than rendering what cannot be sent.
            split = await split_oversized(rt.ctx, rt.jobs, rt.user_id, job)
            if split is not None:
                print(prompt("steward.episodes.split", count=len(split.windows),
                             jobs=" ".join(split.created) or "-"), file=rt.out)
                return shared.EXIT_NOTHING, "", ""
        blocks = source.blocks if window is None else [
            b for b in source.blocks if window[0] <= b.index <= window[1]
        ]
        if not blocks:
            raise ValueError(prompt("steward.episodes.window_empty", start=window[0], end=window[1]))
        budget = first_round_budget(1, rt.max_tool_calls)
        system = episode_rules()
        task = (
            prompt("steward.episodes.task", source=_source_surface(source), budget=budget)
            if window is None else _window_task(source, window, budget)
        )
        context = {
            "system_text": system, "task_text": task,
            "content_digest": blocks_content_digest(source.blocks),
            "block_indices": sorted(b.index for b in blocks),
            "model": selected.spec, "executor": rt.executor,
            "Executor-Skill": rt.executor_skill,
            "chunk_size": rt.ctx.settings.chunk_size,
            "chunk_overlap": rt.ctx.settings.chunk_overlap,
        }
        if window is not None:
            context["window"] = list(window)
        recorded = await _recorded(rt, source_id, window)
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
    episodes = parse_episode_proposal(proposal, indices, window=_window(session))
    return prompt("steward.episodes.no_episode", blocks=json.dumps(uncovered_blocks(episodes, indices)))


async def _published_manifest(rt: EpisodesRuntime, session: DraftSession) -> dict | None:
    """The record is the publication boundary, even if the following draft write crashed."""
    manifest = await _recorded(rt, SourceId(session.source_ids[0]), _window(session))
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
        episodes = parse_episode_proposal(value, session.context["block_indices"], window=_window(session))
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
    window = _window(session)
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
        indices = [b.index for b in source.blocks if window is None or window[0] <= b.index <= window[1]]
        episodes = parse_episode_proposal(data["proposal"], indices, window=window)
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
        if window is None:
            await rt.ctx.store.put_chunk_manifest(rt.user_id, source_id, **manifest)
        else:
            await rt.ctx.store.put_chunk_manifest_window(
                rt.user_id, source_id, window_start=window[0], window_end=window[1], **manifest,
            )
        data["manifest"] = manifest
        await shared._store(rt, draft, session.spend())
    complete = True
    if window is not None:
        # One window is a part of a judgement. The source's L2 is written from the whole of
        # it once the last window lands, and left alone until then.
        judged = await agent_judgement(rt.ctx, rt.user_id, source_id, source.blocks)
        complete = judged is not None
        if complete:
            chunks = await chunks_from_agent_manifests(rt.ctx, source_id, source.blocks, source.structure, judged)
    if complete and rt.ctx.settings.semantic_retrieval == "on":
        embedded = await embed_l2_chunks(rt.ctx, chunks, source) if chunks else []
        await rt.ctx.vectors.delete_source_chunks(rt.user_id, source_id)
        if embedded:
            await rt.ctx.vectors.upsert_chunks(rt.user_id, embedded, archived=source.raw.archived_at is not None)
    detail = f"episodes: {len(episodes)}"
    if window is not None:
        detail += f" in window ¶{window[0]}-{window[1]}; " + (
            "every window recorded" if complete else "the source awaits its other windows"
        )
    await rt.jobs.complete(rt.user_id, session.job_id, ok=True, detail=detail, executor=data["executor"])
    await rt.drafts.delete(rt.user_id, session.job_id, executor=rt.draft_executor)
    print(prompt("steward.episodes.finished", count=len(episodes)), file=rt.out)
    if window is not None:
        print(prompt("steward.episodes.window_complete") if complete else
              prompt("steward.episodes.window_pending", start=window[0], end=window[1]), file=rt.out)
    print(_residue(session), file=rt.out)
    return shared.EXIT_OK
