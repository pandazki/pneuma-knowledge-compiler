"""Compile worker (architecture.md §5): consumes the PG compile queue serially.

Single process, per-user serial (the JobQueue's `FOR UPDATE SKIP LOCKED` + "no second
in-flight job per user" rule is the single-writer guarantee for the git canonical
layer). For each claimed job it loads the supplied NormalizedSources, runs the pure
`run_compile` (which commits to git on success), then persists the mechanically-derived
events to PG, synchronizes the derived claim delta, stamps the sources digested, and
marks the job done. An aborted compile
(gate still failing after one repair) completes with ok=False + the violation detail;
the canonical layer is untouched (runner made no commit).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict

from pneuma_knowledge_core.compile.brief import generate_brief
from pneuma_knowledge_core.compile.runner import CompileResult, run_compile
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.intake import IntakePlan
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.components import notify_source_indexed
from pneuma_knowledge_core.domain.time_context import time_context_for
from pneuma_knowledge_core.ingest.source_types import describe_source, first_party_type
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill.version import SkillVersion
from langchain_core.language_models.chat_models import BaseChatModel

from ..evolve_service import (
    adopt_evolve_job,
    maybe_trigger_evolve,
    run_evolve_job,
)
from ..challenge_service import (
    CHALLENGE_JOB_KIND,
    maybe_trigger_challenge,
    run_challenge_job,
)
from ..access_stats import (
    RECALL_PROJECTION_JOB_KIND,
    RECALL_REBUILD_JOB_KIND,
    run_recall_projection_job,
    run_recall_rebuild_job,
)
from ..groom_service import GROOM_JOB_KIND, maybe_trigger_rollover, run_groom_job
from ..ingest_document import _summary_chunks
from ..projection import sync_projection
from ..settings import Settings, get_settings
from ..skills import skill_for_user
from ..wiring import (
    AppContext,
    build_chat_model_for,
    build_context,
    embed_l2_chunks,
    full_l2_chunks,
    llm_call_config,
    resolve_image_mode,
    resolve_model_name,
)

log = logging.getLogger(__name__)


def _projection_detail(projection: object) -> str:
    return "projection:" + json.dumps(
        asdict(projection), sort_keys=True, separators=(",", ":")
    )


def resolve_compile_image_mode(settings: Settings, model: object) -> str:
    """Resolve `auto` from the model actually used by the compile role."""
    return resolve_image_mode(
        settings.compile_image_mode,
        model,
        resolve_model_name(settings, "compile"),
    )


async def _native_image_payloads(
    ctx: AppContext, user_id: UserId, sources: list[NormalizedSource]
) -> dict[str, bytes]:
    if ctx.media is None:
        raise RuntimeError("native image compile requires a media store")
    payloads: dict[str, bytes] = {}
    for source in sources:
        for block in source.blocks:
            for image in block.images:
                data = await ctx.media.get(user_id, image.storage_key)
                if len(data) != image.size_bytes:
                    raise ValueError(
                        f"stored image {image.image_id!r} size no longer matches L0 manifest"
                    )
                if hashlib.sha256(data).hexdigest() != image.sha256:
                    raise ValueError(
                        f"stored image {image.image_id!r} digest no longer matches L0 manifest"
                    )
                payloads[image.storage_key] = data
    return payloads


def _search_knowledge_port(ctx: AppContext, user_id: UserId):
    """`search_knowledge(query)` → already-compiled L3 claims, WITH their anchors.

    The anchor is the point: without it the model can see that a subject is already recorded
    but has no way to address the claim, so `edit_claim` is unusable and it creates a parallel
    document instead. Lexical only — the semantic claim face needs an embedding round trip per
    call, and the lexical face already keys on the vocabulary the compiler is holding."""

    async def search_knowledge(query: str) -> str:
        try:
            hits = await ctx.lexical.search_claims(user_id, query, limit=12)
        except Exception as exc:  # noqa: BLE001 — retrieval is context, never fatal
            return prompt("compile.worker.search_failed", error=exc)
        if not hits:
            return prompt("compile.worker.knowledge_empty", query=query)
        return "\n".join(
            f"- [{h.document_path} c:{h.anchor}] {h.text.strip()[:220]}" for h in hits
        )

    return search_knowledge


def _search_source_port(ctx: AppContext, user_id: UserId):
    """`search_source(query)` → raw L0 blocks via the L1/L2 fused face, for cross-source
    evidence. Only THIS job's sources are citable, so hits outside them are context only."""
    from pneuma_knowledge_core.recall.rag import rag_recall

    async def search_source(query: str) -> str:
        try:
            hits = await rag_recall(
                user_id,
                query,
                lexical=ctx.lexical,
                vectors=ctx.vectors,
                embeddings=ctx.embeddings,
                limit=8,
            )
        except Exception as exc:  # noqa: BLE001
            return prompt("compile.worker.search_failed", error=exc)
        if not hits:
            return prompt("compile.worker.source_empty", query=query)
        # 600, not 220: rag_recall merges neighbouring blocks into one window, so a hit can
        # span many blocks. A short truncation cut the very line being looked up out of the
        # answer (e.g. a roster entry sitting mid-window), making lookups silently useless.
        return "\n".join(
            f"- [{h.source_id} ¶{h.block_start}-{h.block_end}] {h.text.strip()[:600]}"
            for h in hits
        )

    return search_source


async def _recall_related_claims(
    ctx: AppContext, user_id: UserId, sources: list[NormalizedSource], *, per_source: int = 6
) -> str:
    """Pre-load the existing claims most related to THIS job's sources.

    Default context, replacing the old whole-knowledge-base dump: the model should start
    already knowing which of its own prior conclusions this material touches, without having
    to spend a tool round to find out. Queried per source by title (the cheapest signal that
    is about the source rather than about one line inside it), then deduped by anchor.
    """
    seen: dict[str, str] = {}
    for source in sources:
        # Query from the material itself, not the title. Titles are often near-contentless
        # (a room name and a date), which recalled same-room noise instead of same-subject
        # knowledge. The owner's own turns are the strongest signal for what this source is
        # about; fall back to the opening blocks when he did not speak.
        owner_prefix = prompt(
            "ingest.turn_line", label=prompt("ingest.owner_label"), text=""
        ).rstrip()
        own = [b.text for b in source.blocks if b.text.startswith(owner_prefix)]
        body = " ".join(own or [b.text for b in source.blocks[:4]])
        query = f"{source.raw.title or ''} {body}".strip()[:400]
        if not query:
            continue
        try:
            hits = await ctx.lexical.search_claims(user_id, query, limit=per_source)
        except Exception:  # noqa: BLE001 — absent recall degrades to the outline alone
            continue
        for hit in hits:
            seen.setdefault(
                hit.anchor, f"- [{hit.document_path} c:{hit.anchor}] {hit.text.strip()[:220]}"
            )
    return "\n".join(seen.values())


async def process_job(
    ctx: AppContext,
    chat_model: BaseChatModel,
    skill: SkillVersion,
    user_id: UserId,
    job: object,
) -> CompileResult:
    """Run one claimed compile job to completion (commit + events + digest, or abort)."""
    payload = getattr(job, "payload", {}) or {}
    job_id = getattr(job, "job_id")
    source_ids: list[str] = [str(s) for s in payload.get("source_ids", [])]

    sources: list[NormalizedSource] = []
    for sid in source_ids:
        try:
            sources.append(await ctx.store.get(user_id, SourceId(sid)))
        except KeyError:
            continue  # source deleted since enqueue; skip it

    # Per-source treatment: payload override, else the source's stored IntakePlan.
    payload_treatments = payload.get("treatments") or {}
    treatments = {
        str(s.raw.source_id): payload_treatments.get(
            str(s.raw.source_id),
            (s.raw.intake_plan or {}).get("canonical_treatment", "full"),
        )
        for s in sources
    }

    # Per-source first-party compile guidance (data-context + app-intent), by origin.
    # A generic upload has no first-party type → no guidance. `context_stream_compile_guidance
    # =False` disables injection deployment-wide (deep-heavy: the sharp frame can tip deep
    # into over-assertion — see settings + docs/first-party-context-stream.md).
    source_guidance: dict[str, str] = {}
    if ctx.settings.context_stream_compile_guidance:
        for s in sources:
            fp = first_party_type(s.raw.origin)
            g = fp.compile_guidance() if fp else None
            if g:
                source_guidance[str(s.raw.source_id)] = g.render()

    # The knowledge subject. compile used to never learn who it was compiling FOR — the
    # profile was consumed once by schema-pack selection and then dropped, so every judgment
    # about "is this HIS commitment / is this useful to HIM" had no referent. A provider
    # failure degrades to the "subject unknown" contract, never to a wrong subject.
    owner = None
    try:
        owner = await ctx.user_info.get_profile(user_id)
    except Exception:  # noqa: BLE001 — identity is context, never a hard dependency
        owner = None
    owner_name = getattr(owner, "display_name", "") or prompt(
        "source.preamble.owner_default"
    )

    # Per-source provenance sentence (whose material, when, owner's role in it). Built here
    # because it needs the profile; `describe_source` reads the source's OWN metadata for the
    # occurrence time — never `raw.created_at`, which is the ingest wall-clock.
    source_preamble = {
        str(s.raw.source_id): describe_source(s.raw, len(s.blocks), owner_name)
        for s in sources
    }
    # A compensation compile (post-challenge) carries the confirmed gap list as guidance.
    # It rides the per-source preamble — plain context for the model; the writes it leads
    # to still pass the ordinary citation gate.
    challenge_guidance = str(payload.get("challenge_guidance") or "")
    if challenge_guidance:
        source_preamble = {
            sid: f"{text}\n\n{challenge_guidance}" for sid, text in source_preamble.items()
        }

    # Context the model starts with: the outline (rendered in core from base_docs) plus the
    # claims actually related to this job's material. Both replace the former practice of
    # inlining every existing canonical document into the prompt.
    retrieved = await _recall_related_claims(ctx, user_id, sources)

    # The job's clock: one instant plus the subject's timezone, resolved once from the
    # profile (or a registered TimeZoneProvider, or this deployment's default) and used for
    # every calendar-day render below. It replaces a bare `datetime.now(timezone.utc)`, which
    # made "today" a UTC day while the sections in the material had been cut in the subject's
    # own day. The resolution's PROVENANCE travels with it, because the contract declares
    # which of the three answered rather than presenting them as one fact.
    time = time_context_for(
        user_id, owner, default_timezone=ctx.settings.default_timezone
    )

    image_count = sum(len(block.images) for source in sources for block in source.blocks)
    image_mode = resolve_compile_image_mode(ctx.settings, chat_model)
    image_payloads = (
        await _native_image_payloads(ctx, user_id, sources)
        if image_mode == "native" and image_count
        else {}
    )

    trace_cfg = llm_call_config(
        ctx,
        operation="compile",
        user_id=str(user_id),
        extra={
            "skill_version": skill.version,
            "skill_id": skill.skill_id,
            "job_id": str(job_id),
            "source_count": len(sources),
            "image_count": image_count,
            "image_mode": image_mode,
        },
    )
    result = await run_compile(
        user_id=user_id,
        model=chat_model,
        store=ctx.canonical,
        sources=sources,
        skill=skill,
        treatments=treatments,
        source_guidance=source_guidance,
        known_source_bounds=await ctx.store.block_counts(user_id),
        source_preamble=source_preamble,
        owner=owner,
        retrieved=retrieved,
        search_knowledge=_search_knowledge_port(ctx, user_id),
        search_source=_search_source_port(ctx, user_id),
        time=time,
        commit_message=f"compile {job_id}",
        image_mode=image_mode,
        image_payloads=image_payloads,
        call_timeout=ctx.settings.compile_call_timeout,
        max_tool_calls=ctx.settings.compile_max_tool_calls,
        overview_budget_chars=ctx.settings.overview_budget_chars,
        overview_required_after_claims=ctx.settings.overview_required_after_claims,
        **trace_cfg,
    )

    # Bookkeeping timestamps stay UTC instants (storage is UTC everywhere); only rendered
    # calendar days go through the TimeContext. Reuse its instant so the whole job is
    # stamped from one clock read.
    now = time.now_utc
    if result.status == "committed":
        assert result.snapshot is not None
        await ctx.store.record_compile_events(
            user_id, job_id, result.snapshot.ref, [asdict(e) for e in result.events]
        )
        # L3 projection: synchronize the frozen snapshot delta. The explicit full
        # rebuild remains available for repair/strategy migration. Digestion lands
        # only after every derived store succeeds, so a projection outage remains
        # retryable through the normal POST /compile flow.
        projection = await sync_projection(ctx, user_id, result.snapshot.ref)
        await ctx.store.mark_digested(user_id, source_ids, now)
        # `token_usage` rides the SAME write that ends the job — compile is the biggest
        # spender in the system, and a finished job row that cannot say what it cost is
        # where most of a knowledge base's money would go unaccounted. It is the loop's own
        # sum (first round plus repair round); the money over it is derived on read from the
        # declared rates, never stored here.
        await ctx.store.complete(
            user_id,
            job_id,
            ok=True,
            detail=_projection_detail(projection),
            snapshot_ref=result.snapshot.ref,
            token_usage=result.token_usage,
        )
        # Mechanical rollover trigger: a document this compile WROTE that is now over the
        # size threshold gets a groom job on this same per-user queue. Size only — no LLM, no
        # git read — and only over the paths this compile actually changed.
        await maybe_trigger_rollover(
            ctx, user_id, result.files, {e.path for e in result.events}
        )
        # Passive schema-evolve trigger (schema-evolve §2.1): once committed events land,
        # enqueue an evolve job if the whole-KB doc/anchor increment cleared the threshold.
        await maybe_trigger_evolve(ctx, user_id)
        # Optional post-compile coverage challenge (never on a compensation compile).
        await maybe_trigger_challenge(ctx, user_id, payload, source_ids)
        # Optional derived narration over the recorded events (brief_enabled). LAST on
        # purpose: it is display copy, and a model call ahead of `complete` would hold an
        # already-committed job open — a process killed mid-narration would leave the job
        # claimed with derived stores behind canonical, for a caption. Here the job is
        # durable and the brief only fills one column of it. Its input is the mechanical
        # record alone; `describe_source` is recomputed rather than reusing
        # `source_preamble`, which may carry challenge guidance. Any failure is a warning.
        if ctx.settings.brief_enabled and result.events:
            try:
                brief = await generate_brief(
                    model=ctx.get_chat_model("brief"),
                    events=result.events,
                    source_lines=[
                        describe_source(s.raw, len(s.blocks), owner_name)
                        for s in sources
                    ],
                    call_timeout=ctx.settings.compile_call_timeout,
                    **llm_call_config(
                        ctx,
                        operation="brief",
                        user_id=str(user_id),
                        extra={"job_id": str(job_id)},
                    ),
                )
                if brief:
                    await ctx.store.record_compile_brief(user_id, job_id, brief)
            except Exception:  # noqa: BLE001 — narration is display copy, never fatal
                log.warning("brief generation failed for job %s", job_id, exc_info=True)
    elif result.status == "noop":
        # A retry after canonical commit + projection failure is a canonical noop.
        # Reconcile HEAD before digestion so the same normal retry repairs derived
        # stores instead of silently accepting a partial projection.
        refs, _, _ = await ctx.canonical.snapshots_page(user_id, limit=1)
        detail = "noop"
        if refs:
            projection = await sync_projection(ctx, user_id, refs[0].ref)
            detail = _projection_detail(projection)
        await ctx.store.mark_digested(user_id, source_ids, now)
        await ctx.store.complete(
            user_id, job_id, ok=True, detail=detail, token_usage=result.token_usage
        )
        if refs:
            await maybe_trigger_evolve(ctx, user_id)
    else:  # aborted
        detail = "; ".join(v.render() for v in result.violations)
        # An aborted round spent its tokens too — arguably the spend most worth seeing.
        await ctx.store.complete(
            user_id, job_id, ok=False, detail=detail, token_usage=result.token_usage
        )
    return result


async def process_index_job(
    ctx: AppContext, user_id: UserId, job: object
) -> None:
    """Run one claimed "index" job: the L1/L2 indexing that used to run inline in ingest.

    Loads the stored NormalizedSource + its intake_plan, then:
      - L1 (unconditional, I3): lexical.index_blocks over the blocks.
      - L2 (by semantic_indexing): full → full_l2_chunks (configured model when enabled, else the
        mechanical sentence fallback); summary → _summary_chunks; none → no chunks.
        Then embed + vectors.upsert_chunks.

    Idempotent: L1/L2 upsert by deterministic ids, so a retried index job is safe. The
    chat model for semantic chunking is fetched from ctx inside full_l2_chunks.
    """
    payload = getattr(job, "payload", {}) or {}
    job_id = getattr(job, "job_id")
    source_id_str = str(payload.get("source_id", ""))

    try:
        ns = await ctx.store.get(user_id, SourceId(source_id_str))
    except KeyError:
        # source deleted since enqueue — nothing to index; mark done so it doesn't re-loop.
        await ctx.store.complete(user_id, job_id, ok=True, detail="source gone")
        return

    source_id = ns.raw.source_id
    plan = (
        IntakePlan.model_validate(ns.raw.intake_plan) if ns.raw.intake_plan else None
    )
    semantic = plan.semantic_indexing if plan else "full"

    # L1: unconditional (I3).
    await ctx.lexical.index_blocks(user_id, source_id, ns.blocks)

    # L2: by IntakePlan (semantic_indexing knob).
    if semantic == "full":
        chunks = await full_l2_chunks(
            ctx, source_id, ns.blocks, ns.structure, user_id, raw=ns.raw
        )
    elif semantic == "summary":
        chunks = _summary_chunks(source_id, ns)
    else:
        chunks = []
    if chunks:
        embedded = await embed_l2_chunks(ctx, chunks, ns)
        await ctx.vectors.upsert_chunks(user_id, embedded)

    # The projection channel: an enabled component may keep a derived index of its own (the
    # `time` component's per-block calendar rows), and this is where it learns a source is
    # ready. Fail-soft per component, inside `notify_source_indexed`: what a component
    # derives is rebuildable, so a component that raises costs a stale projection until the
    # next `rebuild_derived` — never a failed index job, and never an L1/L2 redo.
    await notify_source_indexed(str(user_id), ns)

    await ctx.store.complete(user_id, job_id, ok=True, detail="indexed")


async def _resolve_user_skill(
    ctx: AppContext,
    user_id: UserId,
    cache: dict[str, SkillVersion] | None,
) -> SkillVersion:
    """This user's per-job skill, memoized in a per-sweep cache to avoid re-reading git."""
    key = str(user_id)
    if cache is not None and key in cache:
        return cache[key]
    skill = await skill_for_user(ctx, user_id)
    if cache is not None:
        cache[key] = skill
    return skill


async def requeue_orphaned_jobs(ctx: AppContext, *, label: str = "compile-worker") -> int:
    """Startup self-heal: return every job orphaned as 'claimed' to 'queued'.

    A process killed mid-job (typically during a long LLM call) leaves its row 'claimed'
    forever, and `claim_next` refuses to hand out any further job for that user while one
    is in flight — so the orphan silently blocks that user's whole queue. A later drain
    then processes 0 jobs and the caller reads that as "the batch failed".

    Every entrypoint that drains the queue must call this once BEFORE its first drain, not
    just the long-running worker: an experiment/demo script that reuses a tenant inherits
    the exact same orphan.

    Blast radius: the underlying store call is global (the JobQueue port has no per-user
    variant), so it also requeues other tenants' claimed jobs. That is sound for this
    single-worker queue — while no worker is running nothing is legitimately in flight —
    but it does mean a script calling this alongside a LIVE compile worker would yank that
    worker's in-flight job back into the queue. Don't run the two concurrently.

    Returns the number requeued and reports it on stdout (silence means nothing was stuck).
    """
    reclaimed = await ctx.store.requeue_claimed_jobs()
    if reclaimed:
        print(f"[{label}] reclaimed {reclaimed} orphaned claimed job(s) → requeued", flush=True)
    return reclaimed


async def drain_user(
    ctx: AppContext,
    chat_model: BaseChatModel,
    skill: SkillVersion | None,
    user_id: UserId,
    *,
    skill_cache: dict[str, SkillVersion] | None = None,
) -> int:
    """Claim + process this user's queued jobs until the queue is empty.

    Kind-agnostic claim (claim_next orders by created_at): dispatch by job.kind —
    "index" → process_index_job (L1/L2), "evolve"/"evolve_adopt" → the schema-evolve flow,
    "groom" → one document rollover, "recall_projection"/"recall_rebuild" → the use-side
    ledger (no model, no skill), anything else ("compile") → process_job.

    `skill` is the per-USER skill for this drain: pass an explicit SkillVersion to force
    one (upgrade/version tests), or None to load it per-job via `skill_for_user` (the
    worker's default — each owner compiles with their own composed skill). It resolves
    lazily on the first compile job (index jobs need no skill) and is memoized here + in
    `skill_cache` for the rest of the sweep."""
    resolved = skill
    processed = 0
    while True:
        job = await ctx.store.claim_next(user_id)
        if job is None:
            return processed
        try:
            kind = getattr(job, "kind", "compile")
            if kind == "index":
                await process_index_job(ctx, user_id, job)
            elif kind == "evolve":
                await run_evolve_job(ctx, user_id, job)
            elif kind == "evolve_adopt":
                await adopt_evolve_job(ctx, user_id, job)
            elif kind == GROOM_JOB_KIND:
                await run_groom_job(ctx, user_id, job)
            elif kind == RECALL_PROJECTION_JOB_KIND:
                await run_recall_projection_job(ctx, user_id, job)
            elif kind == RECALL_REBUILD_JOB_KIND:
                await run_recall_rebuild_job(ctx, user_id, job)
            elif kind == CHALLENGE_JOB_KIND:
                if resolved is None:
                    resolved = await _resolve_user_skill(ctx, user_id, skill_cache)
                await run_challenge_job(
                    ctx, ctx.get_chat_model("challenge"), resolved, user_id, job
                )
            else:
                if resolved is None:
                    resolved = await _resolve_user_skill(ctx, user_id, skill_cache)
                await process_job(ctx, chat_model, resolved, user_id, job)
        except Exception as exc:  # noqa: BLE001 — never leave a job stuck 'claimed'
            await ctx.store.complete(
                user_id, job.job_id, ok=False, detail=f"worker error: {exc}"
            )
        finally:
            # Short-lived per-job trace flush: a worker sweep may exit right after, so
            # never rely on the background batch surviving process end.
            await ctx.flush_traces()
        processed += 1


async def drain_index_jobs(ctx: AppContext, user_id: UserId) -> int:
    """Claim + process only this user's queued "index" jobs, leaving any compile job queued.

    For callers that must exercise recall (L1/L2 populated) without running compile — e.g.
    a test whose context has no real compile model / no throwaway canonical root. It peeks
    the queue (list_jobs, oldest-first) so a compile job is never claimed and left blocking
    the per-user single-in-flight slot.
    """
    processed = 0
    while True:
        jobs = await ctx.store.list_jobs(user_id)  # newest first
        queued = [j for j in reversed(jobs) if j["status"] == "queued"]  # oldest first
        if not queued or queued[0]["kind"] != "index":
            return processed
        job = await ctx.store.claim_next(user_id)
        if job is None or getattr(job, "kind", None) != "index":
            return processed
        try:
            await process_index_job(ctx, user_id, job)
        finally:
            await ctx.flush_traces()
        processed += 1


async def compile_pending(
    ctx: AppContext, chat_model: BaseChatModel, skill: SkillVersion | None = None
) -> int:
    """One sweep across every user with data; returns the job count processed.

    `skill=None` (the worker default) loads each user's own skill per job; a per-sweep
    cache keyed by user avoids re-reading a manifest from git once per job."""
    total = 0
    cache: dict[str, SkillVersion] = {}
    for uid in await _users_with_jobs(ctx):
        total += await drain_user(
            ctx, chat_model, skill, UserId(uid), skill_cache=cache
        )
    return total


async def _users_with_jobs(ctx: AppContext) -> list[str]:
    """Every tenant whose queue this sweep must look at.

    L0 sources are no longer the only substrate a job can come from. A `recall_projection`
    job is enqueued in the same transaction as a consultation row, and a tenant can ask
    business questions before it has imported anything at all — so enumerating from
    `sources` alone left exactly that tenant's jobs queued forever, with nothing in the
    system able to notice.
    """
    users = set(await ctx.store.list_users())
    lister = getattr(ctx.store, "list_consultation_users", None)
    if lister is not None:
        users |= set(await lister())
    return sorted(users)


async def run_forever() -> None:
    settings = get_settings()
    ctx = await build_context(settings)
    chat_model = build_chat_model_for(settings, "compile")
    # No single global skill: each job loads its user's own composed skill (skill=None).
    print(
        f"[compile-worker] model={resolve_model_name(settings, 'compile')} "
        f"canonical={settings.canonical_root}"
    )
    # Self-heal on startup: requeue any job orphaned as 'claimed' by a previous worker
    # that died mid-job (killed during an LLM call), which would otherwise block its
    # user's queue forever.
    await requeue_orphaned_jobs(ctx)
    try:
        while True:
            n = await compile_pending(ctx, chat_model)
            if n:
                print(f"[compile-worker] processed {n} job(s)")
            await asyncio.sleep(2.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("[compile-worker] stopped")
    finally:
        await ctx.aclose()


def main() -> None:
    """Process entrypoint — `python -m pneuma_knowledge_service.workers.compile_worker`.

    One `asyncio.run` owns the loop for the worker's whole life, so the PG pool and the
    Meili/Qdrant clients are created and closed on the same loop."""
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass  # Ctrl-C during shutdown; run_forever already printed its stop line


if __name__ == "__main__":
    main()
