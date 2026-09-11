"""Compile worker (architecture.md §5): consumes the PG compile queue, one job per lane.

Single process, per-user serial PER LANE (`job_lanes.py`): the JobQueue's `FOR UPDATE SKIP
LOCKED` plus "no second in-flight job per user in this lane" is the single-writer guarantee
for the git canonical layer, and the canonical lane's half of it is byte-for-byte the rule
the whole queue used to have. Two lane tasks drain a tenant at once — one job that can write
the library, one that cannot (index, episodes, the recall projections) — so at most one
coding-agent round per lane, two in the process. For each claimed job it loads the supplied
NormalizedSources, runs the pure
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
import os
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from pneuma_knowledge_core.compile.brief import generate_brief
from pneuma_knowledge_core.compile.runner import CompileResult, run_compile
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.intake import IntakePlan
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.components import notify_source_indexed
from pneuma_knowledge_core.domain.time_context import time_context_for
from pneuma_knowledge_core.ingest.source_types import describe_source, first_party_type
from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError
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
from ..archive_service import ARCHIVE_JOB_KIND
from .archive_job import run_archive_job
from ..groom_service import GROOM_JOB_KIND, maybe_trigger_rollover, run_groom_job
from ..infra_faults import InfraFault, InfrastructureInterrupted, infrastructure_fault
from ..ingest_document import _summary_chunks
from ..job_lanes import CANONICAL_LANE, LANES, lane_of
from ..projection import sync_projection
from ..settings import Settings, get_settings
from ..skills import skill_for_user
from ..wiring import (
    CONNECTION_ROLE,
    AppContext,
    build_chat_model_for,
    build_context,
    connection_role_as,
    can_build_chat_model,
    embed_l2_chunks,
    executor_for,
    full_l2_chunks,
    agent_judgement,
    llm_call_config,
    resolve_image_mode,
    resolve_model_name,
)

log = logging.getLogger(__name__)

#: The job kind whose body is a compile round. Named because the worker has to be able to
#: leave it alone: under an agent executor the round belongs to the Steward, and this is the
#: kind a drain skips over (docs/design/coding-agent-mode.md §9, "The worker").
COMPILE_JOB_KIND = "compile"

#: The harness round this body is running, per `(tenant, lane)`. The bound it states is the
#: lane rule itself — at most one agent round per lane, so at most two harness processes for
#: one library — and it states it where a person would otherwise have to trust it: a second
#: launch in one lane means the claim let two jobs of that lane fly at once, which is the
#: single-writer bug, and it fails loudly here instead of quietly running two harnesses over
#: one draft. Cleared in a `finally`, so a failed round frees its lane.
_AGENT_ROUNDS: dict[tuple[str, str], str] = {}

#: What each lane holds right now: lane → `(user_id, job_id)`, set the moment `claim_next`
#: hands a row over and cleared once that job's completion is written. It is the drain's OWN
#: account of what it is holding, and it exists because the recovery used to read that fact
#: off the exception instead: a failure inside the claim or the completion carried the job id
#: (`InfrastructureInterrupted`), and a failure anywhere else — the work that FOLLOWS a round,
#: an episodes job's vector write — carried nothing, so the outage recovery requeued nothing
#: and the claim outlived the outage. One live library sat with 542 jobs pending behind such a
#: claim for half an hour, until a person restarted the engine. Whatever raises between the
#: claim and the completion, the job is named here, so `ride_out` can put it back.
#:
#: It is also what the periodic self-heal must NOT touch (`in_flight_jobs`): those claims are
#: this body's work in flight, not anybody's orphan.
_IN_FLIGHT: dict[str, tuple[str, str]] = {}

#: Held across a claim and across the periodic self-heal, so that a row cannot be claimed
#: between the sweep reading `in_flight_jobs()` and the sweep deciding on that row. Without
#: it the skip list is a snapshot with a window behind it: a claim landing inside that window
#: is not in the list and carries nothing on its row that says it is alive, so the sweep would
#: hand a second body the job this one is running. Both sides are short — one statement and
#: one sweep a minute — and only this process's own bodies take it; every other body is
#: excluded by the queue's own advisory locks.
_CLAIM_GATE = asyncio.Lock()


def _lane_key(lane: str | None) -> str:
    """The `_IN_FLIGHT` key for a drain of `lane` (`None` = the whole queue, one loop)."""
    return lane or "*"


def in_flight_jobs() -> tuple[str, ...]:
    """Every job id this process holds a claim on right now, across its lanes."""
    return tuple(job_id for _user, job_id in _IN_FLIGHT.values())


#: Which (role, reason) pairs this process has already said the skip sentence about. The
#: reason is a deployment fact, not a per-job event — a keyless library under an agent
#: executor crossed the evolve threshold forty times in one real run, and forty identical
#: lines teach the reader to skip the line. Keyed on the reason too, so a configuration that
#: changes under a long-lived process speaks again.
_OPTIONAL_ROLE_SKIPPED: set[tuple[str, str]] = set()


#: Per tenant: when this body may next claim a job a HARNESS would have to run, and the
#: words that say why. In memory on purpose — one engine process serves one library here, and
#: a restart that tries once and cools again costs one launch, whereas a cooling period
#: persisted in a second place would be a second answer to a question the queue already holds
#: (the re-queued job's `not_before` is the durable one; this only saves the sweeps in
#: between from claiming the jobs behind it).
_COOLING: dict[str, tuple[datetime, str]] = {}

#: How many rate limits this tenant has hit with no round in between. The cooldown doubles
#: on it, and the first round that actually runs forgets it.
_RATE_LIMIT_HITS: dict[str, int] = {}
#: The same count for a model at capacity, kept apart: the two refusals double on their own
#: clocks (`AGENT_UNAVAILABLE_COOLDOWN_S` vs `AGENT_RATE_LIMIT_COOLDOWN_S`), so a capacity
#: dip never lengthens the next usage-limit guess, nor the other way round.
_CAPACITY_HITS: dict[str, int] = {}

#: How much of a refusing harness's own output is kept on the job row (`harness_output`).
#: Enough to hold the failure and the lines around it; small enough that a job listing which
#: selects the column is still a listing. The words themselves are the launcher's, scrubbed.
HARNESS_OUTPUT_CHARS = 2000

#: How the drain waits out an infrastructure outage: the first retry after this many
#: seconds, doubling to `INFRA_BACKOFF_MAX_S`. Bounded both ways — quick enough that a
#: Postgres restart costs seconds, slow enough that a stack that is down for an hour is asked
#: once a minute rather than hammered.
INFRA_BACKOFF_START_S = 2.0
INFRA_BACKOFF_MAX_S = 60.0
#: The pause between sweeps of an idle queue.
IDLE_SWEEP_S = 2.0
#: How many times one job may be interrupted by an infrastructure failure and put back. An
#: outage is not the job's fault, so it is not failed for one; but a job that meets the same
#: "transient" error on every attempt while the stack answers every probe is not meeting an
#: outage, and after this many it is failed as any other error fails it.
INFRA_JOB_INTERRUPTIONS = 3
_INFRA_STRIKES: dict[str, int] = {}


def agent_cooling(user_id: UserId) -> tuple[datetime, str] | None:
    """This tenant's cooling window — `(until, reason)` — or None once it has passed."""
    entry = _COOLING.get(str(user_id))
    if entry is None:
        return None
    if entry[0] <= datetime.now(timezone.utc):
        _COOLING.pop(str(user_id), None)
        return None
    return entry


def agent_path_kinds(ctx: AppContext) -> tuple[str, ...]:
    """The job kinds that need a launched harness in THIS deployment.

    What a cooling worker must not claim, and nothing else: index, projection, groom and
    archive jobs run no harness at all, so a spent subscription never stops them.
    """
    kinds: list[str] = []
    if executor_for(ctx.settings, "compile").is_agent:
        kinds += [COMPILE_JOB_KIND, "episodes"]
    if executor_for(ctx.settings, "evolve").is_agent:
        kinds.append("evolve")
    return tuple(kinds)


def optional_role_runnable(settings: Settings, role: str) -> bool:
    """May this deployment ENQUEUE work for an optional role — saying once why not.

    Evolve under an agent executor has its own draft door and is always runnable. For an
    API executor, the passive evolve trigger and post-compile challenge need the role's
    model. When this deployment cannot build that model, enqueueing it manufactures a failure:
    the job is claimed, dies on `openrouter:<model> requires OPENROUTER_API_KEY`, and lands
    in the Owner's health page and tray as breakage of a library that is in fact perfectly
    healthy. So the question is asked HERE, mechanically, at the moment of enqueue.

    Nothing is recorded when the answer is no — no job, no failed row, and (for evolve) no
    evolve task. That last one is what keeps the accounting honest: `maybe_trigger_evolve`
    measures its window from the last evolve TASK, so a skipped crossing consumes nothing
    and the increment keeps accruing — the first crossing after a key appears enqueues.

    Compile is never asked. A compile is the work itself, and under an agent executor its
    job is claimed by a Steward rather than by a model.
    """
    if role == "evolve" and executor_for(settings, role).is_agent:
        return True
    if role == "challenge" and executor_for(settings, "compile").is_agent:
        ok, reason = False, "challenge is skipped under an agent executor"
    else:
        ok, reason = can_build_chat_model(settings, role)
    if ok:
        return True
    if (role, reason) not in _OPTIONAL_ROLE_SKIPPED:
        _OPTIONAL_ROLE_SKIPPED.add((role, reason))
        log.warning("[compile-worker] %s skipped: %s", role, reason)
    return False


def langchain_executor(settings: Settings) -> str:
    """What a job record says when the worker's own loop ran the round."""
    return f"langchain:{resolve_model_name(settings, 'compile')}"


def agent_executor(settings: Settings) -> str:
    """What a job record says when a coding agent typed the calls through `pkc draft`.

    The backend is whatever launched the session (`PNEUMA_KNOWLEDGE_EXECUTOR_BACKEND`, set by
    the unattended launcher and by the console's bridge). A terminal session the Owner opened
    themselves sets nothing, and the record then says `agent` and stops there — which is the
    true statement. Neither form carries token usage: the harness's counters belong to the
    Owner's subscription, and a zero would be a claim that the round was free (story 2.15).
    """
    backend = (settings.executor_backend or "").strip()
    return f"agent:{backend}" if backend else "agent"


def _projection_detail(projection: object) -> str:
    return "projection:" + json.dumps(
        asdict(projection), sort_keys=True, separators=(",", ":")
    )


def _with_run_facts(detail: str, result: object) -> str:
    """Append what this compile RUN cost and refused to the job's completion detail.

    Two facts, both of which the outcome's own detail cannot carry, appended after it and
    never substituted for it — the projection figures and the gate's violations are what the
    detail already means:

    - `rounds:<n>` — one round, or two because the first failed the gate and the repair round
      ran. On EVERY branch, including `aborted`: a repair that was attempted and still could
      not pass is the most expensive shape a compile has, and it is invisible next to a
      one-round abort unless the number is written down. It sits beside `token_usage` in
      what a finished job can say about what it cost.
    - `archive_refusals:[…]` — the one moment the framework learns that new material was
      about a subject the owner RETIRED. The compile was stopped from writing it, and
      without this the owner would never hear that it was attempted
      (docs/design/archive.md §2.1). It is not a compile event: events are derived from the
      file diff, and a refusal wrote no file. So it rides the detail column instead, and
      `GET /jobs` shows it beside the compile that hit it. Omitted entirely when empty, so a
      library with no archive never sees the field.
    """
    parts = [detail] if detail else []
    rounds = getattr(result, "rounds", None)
    if rounds is not None:
        parts.append(f"rounds:{rounds}")
    refusals = getattr(result, "archive_refusals", None) or []
    if refusals:
        parts.append(
            "archive_refusals:"
            + json.dumps(
                refusals, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        )
    return "; ".join(parts)


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


@dataclass(frozen=True)
class CompileInputs:
    """Everything one compile job supplies to a round, resolved from the job row.

    Extracted from `process_job` because a compile round now has two possible bodies, and the
    material a round is given must not depend on which one drives it (ruling 2 of
    docs/design/coding-agent-mode.md). The langchain worker and `pkc draft open` resolve their
    inputs through this one function, which is what makes "the same job renders the same task
    bytes under either executor" a property of the code rather than a hope about two call
    sites.
    """

    sources: list[NormalizedSource]
    source_ids: list[str]
    treatments: dict[str, str]
    source_guidance: dict[str, str]
    source_preamble: dict[str, str]
    owner: object | None
    owner_name: str
    retrieved: str
    time: object
    known_source_bounds: dict[str, int]
    image_mode: str
    image_payloads: dict[str, bytes]
    commit_message: str
    image_count: int


async def compile_inputs(
    ctx: AppContext,
    user_id: UserId,
    job: object,
    *,
    chat_model: BaseChatModel | None = None,
    image_mode: str | None = None,
) -> CompileInputs:
    """Resolve one claimed compile job into the material and the frame a round runs on.

    `image_mode` states the delivery when the caller knows it (the CLI executor reads a
    terminal, so it asks for captions); otherwise it is resolved against the model that will
    receive the message, exactly as before.
    """
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

    # What the OWNER said this statement was about (`pkc owner say --about`, §5.3). It rides
    # the per-source guidance because that is where "how to read this round's material" is
    # already said, and it is a POINTER and not a permission: it names the pages the
    # statement concerns so the round opens them, and the gate asks exactly what it asked
    # before. Carried on the job payload rather than on the source, because it is a fact
    # about this hand-over and not about the bytes in L0.
    about_paths = [str(p).strip() for p in (payload.get("about_paths") or []) if str(p).strip()]
    if about_paths:
        line = prompt("compile.task.about_pages", paths=", ".join(about_paths))
        for src in sources:
            sid = str(src.raw.source_id)
            existing = source_guidance.get(sid)
            source_guidance[sid] = f"{existing}\n{line}" if existing else line

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
    mode = image_mode or resolve_compile_image_mode(ctx.settings, chat_model)
    image_payloads = (
        await _native_image_payloads(ctx, user_id, sources)
        if mode == "native" and image_count
        else {}
    )
    return CompileInputs(
        sources=sources,
        source_ids=source_ids,
        treatments=treatments,
        source_guidance=source_guidance,
        source_preamble=source_preamble,
        owner=owner,
        owner_name=owner_name,
        retrieved=retrieved,
        time=time,
        known_source_bounds=await ctx.store.block_counts(user_id),
        image_mode=mode,
        image_payloads=image_payloads,
        commit_message=f"compile {job_id}",
        image_count=image_count,
    )


async def persist_compile_result(
    ctx: AppContext,
    user_id: UserId,
    job_id: str,
    job_payload: dict,
    inputs: CompileInputs,
    result: CompileResult,
    *,
    executor: str | None = None,
) -> None:
    """Everything that happens AFTER a compile round produced its result, whoever drove it.

    Events, the L3 projection delta, digestion, the job row and its token usage, the rollover
    and evolve and challenge triggers, the post-compile brief — and the two other endings, a
    canonical noop and an abort. It was the tail of `process_job` and is now called from there
    and from `pkc draft finish`, because what a committed compile means to the derived layers
    cannot depend on which executor typed the tool calls.

    `executor` is the one thing that does depend on it, and it is a label on the job row:
    `langchain:<model spec>` from the worker, `agent:<backend>` from the CLI. None leaves the
    column as it was — a caller that does not know who ran the round says nothing rather than
    guessing.
    """
    # Bookkeeping timestamps stay UTC instants (storage is UTC everywhere); only rendered
    # calendar days go through the TimeContext. Reuse its instant so the whole job is
    # stamped from one clock read.
    now = inputs.time.now_utc
    sources = inputs.sources
    source_ids = inputs.source_ids
    owner_name = inputs.owner_name
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
            detail=_with_run_facts(_projection_detail(projection), result),
            snapshot_ref=result.snapshot.ref,
            token_usage=result.token_usage,
            executor=executor,
        )
        # Mechanical rollover trigger: a document this compile WROTE that is now over the
        # size threshold gets a groom job on this same per-user queue. Size only — no LLM, no
        # git read — and only over the paths this compile actually changed.
        await maybe_trigger_rollover(
            ctx, user_id, result.files, {e.path for e in result.events}
        )
        # Passive schema-evolve trigger (schema-evolve §2.1): once committed events land,
        # enqueue an evolve job if the whole-KB doc/anchor increment cleared the threshold —
        # and only if this deployment can actually run the evolve role at all.
        # The deployment's own switch is asked FIRST (and again inside the trigger, which is
        # where it belongs): a deployment that turned the trigger off is not one that cannot
        # run the role, and it must not be told that it is.
        if ctx.settings.evolve_auto_trigger and optional_role_runnable(ctx.settings, "evolve"):
            await maybe_trigger_evolve(ctx, user_id)
        # Optional post-compile coverage challenge (never on a compensation compile).
        if ctx.settings.challenge_enabled and optional_role_runnable(ctx.settings, "challenge"):
            await maybe_trigger_challenge(ctx, user_id, job_payload, source_ids)
        # Optional derived narration over the recorded events (brief_enabled). LAST on
        # purpose: it is display copy, and a model call ahead of `complete` would hold an
        # already-committed job open — a process killed mid-narration would leave the job
        # claimed with derived stores behind canonical, for a caption. Here the job is
        # durable and the brief only fills one column of it. Its input is the mechanical
        # record alone; `describe_source` is recomputed rather than reusing
        # `source_preamble`, which may carry challenge guidance. Any failure is a warning.
        # The brief is not a job, so a keyless deployment loses only a caption here — but it
        # loses it once per compile, through an exception and a stack trace. The same
        # question, asked once, is the cheaper and quieter answer.
        if (
            ctx.settings.brief_enabled
            and not (executor or "").startswith("agent")
            and not executor_for(ctx.settings, "compile").is_agent
            and result.events
            and optional_role_runnable(ctx.settings, "brief")
        ):
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
            user_id,
            job_id,
            ok=True,
            detail=_with_run_facts(detail, result),
            token_usage=result.token_usage,
            executor=executor,
        )
        if (
            refs
            and ctx.settings.evolve_auto_trigger
            and optional_role_runnable(ctx.settings, "evolve")
        ):
            await maybe_trigger_evolve(ctx, user_id)
    else:  # aborted
        detail = "; ".join(v.render() for v in result.violations)
        # An aborted round spent its tokens too — arguably the spend most worth seeing.
        await ctx.store.complete(
            user_id,
            job_id,
            ok=False,
            detail=_with_run_facts(detail, result),
            token_usage=result.token_usage,
            executor=executor,
        )


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
    inputs = await compile_inputs(ctx, user_id, job, chat_model=chat_model)

    trace_cfg = llm_call_config(
        ctx,
        operation="compile",
        user_id=str(user_id),
        extra={
            "skill_version": skill.version,
            "skill_id": skill.skill_id,
            "job_id": str(job_id),
            "source_count": len(inputs.sources),
            "image_count": inputs.image_count,
            "image_mode": inputs.image_mode,
        },
    )
    from ..source_authorship import load_owner_authored_blocks

    result = await run_compile(
        user_id=user_id,
        model=chat_model,
        store=ctx.canonical,
        sources=inputs.sources,
        skill=skill,
        treatments=inputs.treatments,
        source_guidance=inputs.source_guidance,
        known_source_bounds=inputs.known_source_bounds,
        owner_authored_blocks=await load_owner_authored_blocks(ctx.store, user_id, skill),
        source_preamble=inputs.source_preamble,
        owner=inputs.owner,
        retrieved=inputs.retrieved,
        search_knowledge=_search_knowledge_port(ctx, user_id),
        search_source=_search_source_port(ctx, user_id),
        time=inputs.time,
        commit_message=inputs.commit_message,
        image_mode=inputs.image_mode,
        image_payloads=inputs.image_payloads,
        call_timeout=ctx.settings.compile_call_timeout,
        max_tool_calls=ctx.settings.compile_max_tool_calls,
        overview_budget_chars=ctx.settings.overview_budget_chars,
        overview_required_after_claims=ctx.settings.overview_required_after_claims,
        **trace_cfg,
    )
    await persist_compile_result(
        ctx,
        user_id,
        job_id,
        payload,
        inputs,
        result,
        executor=langchain_executor(ctx.settings),
    )
    return result


def unattended(ctx: AppContext, role: str = "compile") -> bool:
    """Does THIS worker run compile jobs through the coding agent itself?

    Two postures, one question (§8, §9). A worker is by definition unattended — nobody is at
    a terminal where it runs — so under an agent executor it claims a compile job, opens its
    draft and hands it to a launched harness. Turning `AGENT_UNATTENDED` off restores the
    interactive posture step 2 shipped: compile jobs stay queued and the Owner's own session
    opens them with `pkc draft open`. Under a model executor the question does not arise.
    """
    return bool(executor_for(ctx.settings, role).is_agent and ctx.settings.agent_unattended)


#: The package sha256 this process last installed under a `(project, backend)`. A verify is a
#: byte comparison over a handful of small files, so it is paid once per claimed agent job;
#: what the cache buys is that a drift already answered once is not re-installed — and not
#: logged — on every job after it.
_skill_package_installed: dict[tuple[str, str], str] = {}

#: One installer at a time in this process. Two lanes start rounds independently, and two
#: coroutines rendering the same package into the same directory would interleave their
#: writes; the round that read it would then be taught half of each.
_skill_install_lock = asyncio.Lock()


async def ensure_skill_package(
    settings: Settings, user_id: UserId, *, project_dir: str, backend: str
) -> None:
    """`_ensure_skill_package`, one caller at a time in this process.

    Two lanes open their rounds independently, so two coroutines can arrive here at the same
    instant; the lock is what keeps them from interleaving their writes into one package
    directory, and the cache inside means the second one finds nothing left to do."""
    async with _skill_install_lock:
        await _ensure_skill_package(
            settings, user_id, project_dir=project_dir, backend=backend
        )


async def _ensure_skill_package(
    settings: Settings, user_id: UserId, *, project_dir: str, backend: str
) -> None:
    """Re-render the project's installed skill package when it has drifted, before the round.

    The package is a rendering of the deployment — the contract, the wording, the components,
    and the Owner's own profile — and several of those are written AFTER the install a cold
    start does: the profile is seeded once the engine is up, the per-user schema manifest is
    materialized by the first compile. So the words a harness reads go stale within minutes
    of a setup, and the round runs on a package no `pkc skill verify` recognises — while the
    commit's `Executor-Skill:` trailer says the executor read what this deployment renders.
    Verified here, with the same function `pkc skill verify --project` exits 4 on, and
    re-installed with the same function `pkc skill install` writes.

    A refresh, never a decision: a project with no `skill-version.json` for this backend is
    one nobody installed into, and it is left alone. A verify that cannot run at all — a
    deployment that renders nothing — must never cost the round either: it is logged and the
    round goes on with what is installed.
    """
    from ..coding_agent.backends import backend as backend_manifest
    from ..coding_agent.deployment import (
        SkillRenderError,
        default_parser,
        packages,
        resolve_deployment,
    )
    from ..coding_agent.install import (
        SkillWriteRefused,
        install_skill_package,
        installed_hash,
        verify_skill_package,
    )

    key = (os.path.abspath(project_dir), backend)
    try:
        manifest = backend_manifest(backend)
        # A REFRESH, never a decision: `skill-version.json` is the record that this project
        # chose to have a package, and a directory without one is a directory nobody
        # installed into — a worker started somewhere else, a checkout under test. Read
        # first, so nothing below can write a package into it.
        previous = installed_hash(project_dir, manifest)
        if not previous:
            return
        deployment = await resolve_deployment(
            settings, user=str(user_id), parser_for=default_parser
        )
        ((_, package),) = packages(deployment, [backend], project=project_dir)
        if not verify_skill_package(project_dir, manifest, package):
            return
        if _skill_package_installed.get(key) == package.sha256:
            # These exact bytes were written once already and the disk still disagrees:
            # something outside this process rewrites them, and re-installing per job would
            # be a loop with a log line in it.
            return
        install_skill_package(project_dir, manifest, package, deployment.framework_version)
        _skill_package_installed[key] = package.sha256
        print(
            f"[compile-worker] skill package re-rendered for {backend} "
            f"({previous[:8]} → {package.sha256[:8]})",
            flush=True,
        )
    except (SkillRenderError, SkillWriteRefused, OSError, LookupError, ValueError) as exc:
        log.warning(
            "could not verify the %s skill package in %s: %s", backend, project_dir, exc
        )


def agent_round_effort(settings: object, kind: str) -> str:
    """How hard the harness is told to think for one job of `kind`.

    An episodes round (L2 boundaries for one source) is a simple judgement that costs a
    compile round's context when it thinks at a compile's effort, so it may be stated on its
    own; empty inherits the effort every other agent round runs at.
    """
    if kind == "episodes":
        episodes = str(getattr(settings, "agent_reasoning_effort_episodes", "") or "")
        if episodes:
            return episodes
    return str(getattr(settings, "agent_reasoning_effort", "") or "")


async def process_agent_job(ctx: AppContext, user_id: UserId, job: object) -> None:
    """One claimed compile job, run through a launched coding agent (§9), one per lane.

    `run_compile` is deliberately NOT used: the round's body is another process typing `pkc
    draft` commands, and the draft it works on lives in the store. What ends the round is the
    same `cmd_finish` the CLI calls, whether the harness ran it or the runner did — one code
    path finishes a draft (`coding_agent/round_runner.py` states the cut).

    The job row is written by that finish. What this adds afterwards is the one thing the
    finish could not know: what the harness's own counters said the round cost, which the
    launcher read from its JSON one process out. Absent stays absent — a round whose harness
    reported nothing records nothing, never a zero.

    The lane this job drains in is held for the length of the round (`_AGENT_ROUNDS`): two
    lanes may each have a harness process out at once, and neither lane may have two.
    """
    kind = getattr(job, "kind", "compile")
    role = "evolve" if kind == "evolve" else "compile"
    executor = executor_for(ctx.settings, role)
    job_id = getattr(job, "job_id")
    slot = (str(user_id), lane_of(kind))
    running = _AGENT_ROUNDS.get(slot)
    if running is not None:
        raise RuntimeError(
            f"job {job_id} would be a second {slot[1]}-lane harness round for {user_id} "
            f"while job {running} holds that lane"
        )
    _AGENT_ROUNDS[slot] = str(job_id)
    try:
        await _run_agent_job(ctx, user_id, job, kind=kind, role=role, executor=executor)
    finally:
        _AGENT_ROUNDS.pop(slot, None)


async def _run_agent_job(
    ctx: AppContext, user_id: UserId, job: object, *, kind: str, role: str, executor: object
) -> None:
    """The body of one agent round, once its lane is held (`process_agent_job`)."""
    from ..coding_agent.backends import backend as backend_manifest
    from ..coding_agent.round_runner import (
        ABANDONED,
        HARNESS_UNAVAILABLE,
        ROUND_INCOMPLETE,
        AgentRoundRunner,
    )
    from ..cli.runtime import build_runtime

    job_id = getattr(job, "job_id")
    if role == "evolve":
        from ..cli.evolve import build_runtime
    elif kind == "episodes":
        from ..cli.episodes import build_runtime
    # Before anything is launched: the package the harness is about to be taught by must be
    # what this deployment renders today, or the round reads words nobody wrote for it.
    await ensure_skill_package(
        ctx.settings, user_id, project_dir=os.getcwd(), backend=str(executor.backend)
    )
    rt = await build_runtime(ctx, user_id, executor=executor.spec)
    runner = AgentRoundRunner(
        manifest=backend_manifest(str(executor.backend)),
        # The project the shim and the installed skill live in is the directory the worker
        # was started from — the same convention `pkc` itself uses to find a deployment.
        project_dir=os.getcwd(),
        timeout_s=float(ctx.settings.compile_call_timeout),
        # WHICH model runs the round and how hard it thinks. Empty leaves both to the harness,
        # which means the Owner's own global harness configuration — the deployment states
        # them here when the library's rounds are not to inherit the Owner's terminal. The
        # effort is chosen by the job's kind: an episodes round may state its own.
        model=str(ctx.settings.agent_model),
        reasoning_effort=agent_round_effort(ctx.settings, kind),
        retries=int(ctx.settings.agent_retries),
        keep_workdir=bool(ctx.settings.agent_keep_workdir),
        # Which library. The harness runs in an empty working directory with no project
        # `.env` in it, so the stack it reaches is stated by the worker rather than
        # resolved by the child (`launcher.CONNECTION_SETTINGS`).
        settings=ctx.settings,
    )
    try:
        result = await runner.run_job(rt, job_id)
    except Exception as exc:
        # The drain's error tail must still name this launch after the lease closes.
        exc.draft_executor = runner.executor
        exc.draft_runtime = rt
        raise
    log.info(
        "job %s: %s (%d launch(es)%s)",
        job_id,
        result.outcome,
        result.launches,
        ", timed out" if result.timed_out else "",
    )
    if result.outcome == HARNESS_UNAVAILABLE:
        # A round that never ran. Nothing is judged, nothing is digested, and the job comes
        # back — held off the queue until the subscription can answer it.
        await _harness_unavailable(
            ctx,
            user_id,
            job,
            result,
            rt=rt,
            executor=runner.executor,
            manifest=runner.manifest,
        )
        return
    # A round DID run: the doubling starts over, and any cooling this tenant was under is
    # over by definition — this body just claimed and ran one of its jobs.
    _RATE_LIMIT_HITS.pop(str(user_id), None)
    _CAPACITY_HITS.pop(str(user_id), None)
    _COOLING.pop(str(user_id), None)
    if result.outcome == ROUND_INCOMPLETE:
        # It ran, but it did not reach the end of its material and nothing was committed:
        # a failure to report and a job to bring back, never a success.
        await _round_incomplete(ctx, user_id, job, result, executor=runner.executor)
    if result.usage and result.outcome not in (ABANDONED, "draft ownership lost"):
        await ctx.store.record_job_usage(
            user_id, job_id, token_usage=result.usage, executor=executor.spec
        )


async def _harness_unavailable(
    ctx: AppContext,
    user_id: UserId,
    job: object,
    result: object,
    *,
    rt: object,
    executor: str,
    manifest: object,
) -> None:
    """End a job whose harness never ran it, and queue the same work for later.

    Three things happen here and each of them is the opposite of what happened the night this
    was written, when a spent quota produced 296 compile jobs recorded `done ok=True` with
    nothing written and their sources stamped digested:

    1. the job is completed `ok=False`, naming the harness's own refusal;
    2. its sources are NOT marked digested — nothing was compiled, so nothing is claimed;
    3. the same payload is queued again as a new row, held back by `not_before` until the
       provider said the room comes back (or a doubling cooldown when it said nothing).

    And one more, which is what keeps the other three from being paid for 315 times: the
    tenant is put on ice, so this body stops claiming work no harness can run.

    **What the ice is for, and what it is not for** (`round_runner.UNAVAILABLE_*`). A spent
    subscription and a model at capacity are facts about the PROVIDER: nothing else this
    tenant has queued can run either, so the tenant waits and the job comes back behind a
    `not_before`. A harness that simply died is a fact about THIS JOB. Cooling on it was a
    real bug with a real cost: an `agent-session/v1` part of 24,439 blocks killed every
    launch it was given, and each failure re-queued itself behind a fifteen-minute wall and
    wrote `cooling_reason` onto the row the API reads — so the console announced a cooling
    tenant that the drain was not honouring (the ice was never laid: `_COOLING` was only ever
    set on the rate-limit branch), and every retry pushed the wall out again. A failure now
    cools nothing, states the harness's own first line on the job, and is retried at most
    `AGENT_RETRIES` times before the row is left failed for a person to read.
    """
    from ..coding_agent.backends import unavailable_reason, usage_limit_deadline
    from ..coding_agent.round_runner import (
        UNAVAILABLE_AT_CAPACITY,
        UNAVAILABLE_FAILED,
        UNAVAILABLE_RATE_LIMITED,
        failure_line,
    )

    job_id = getattr(job, "job_id")
    kind = getattr(job, "kind", COMPILE_JOB_KIND)
    payload = dict(getattr(job, "payload", {}) or {})
    now = datetime.now(timezone.utc)
    label = getattr(manifest, "display_label", "") or getattr(manifest, "name", "harness")
    backend_name = getattr(manifest, "name", "harness")
    # What the harness said, bounded and already scrubbed by the runner. Kept on the row
    # because `exit 1` is not a diagnosis, and the words that were a diagnosis lived only in
    # a worker process that has since moved on.
    harness_output = (getattr(result, "output", "") or "")[-HARNESS_OUTPUT_CHARS:]
    # The runner classifies; this only falls back for a caller that predates the field.
    refusal = str(getattr(result, "harness_reason", "") or "") or (
        UNAVAILABLE_RATE_LIMITED if getattr(result, "rate_limited", False)
        else UNAVAILABLE_FAILED
    )
    requeue = True

    if refusal in (UNAVAILABLE_RATE_LIMITED, UNAVAILABLE_AT_CAPACITY):
        capacity = refusal == UNAVAILABLE_AT_CAPACITY
        counter = _CAPACITY_HITS if capacity else _RATE_LIMIT_HITS
        hits = counter.get(str(user_id), 0) + 1
        counter[str(user_id)] = hits
        output = getattr(result, "output", "") or ""
        # WHICH refusal it was, in the provider's own vocabulary — a spent subscription and a
        # model with no capacity are one fact to this code and two sentences to a person.
        said = unavailable_reason(output, manifest) or "usage limit"
        # The provider's own answer first. A parsed deadline is a fact; the cooldown below is
        # a guess, and a guess that runs short is what turns one rate limit into a night of
        # them. Only a usage limit ever names an hour; capacity never does.
        stated = None if capacity else usage_limit_deadline(
            output,
            timezone_name=str(ctx.settings.default_timezone),
            patterns=tuple(getattr(manifest, "usage_limit_patterns", ()) or ()),
        )
        if stated is not None and stated > now:
            not_before = stated
            detail = f"rate_limited: {label} {said}; retry after {stated.isoformat()}"
        else:
            # A spent subscription is a guess about hours; a model at capacity is back within
            # minutes more often than not, and waiting it out like a quota kept the tenant off
            # the air long after the model had room. Each doubles on its own base and ceiling.
            if capacity:
                base = int(ctx.settings.agent_unavailable_cooldown_s)
                ceiling = int(ctx.settings.agent_unavailable_cooldown_max_s)
            else:
                base = int(ctx.settings.agent_rate_limit_cooldown_s)
                ceiling = int(ctx.settings.agent_rate_limit_cooldown_max_s)
            seconds = min(base * (2 ** (hits - 1)), ceiling)
            not_before = now + timedelta(seconds=seconds)
            detail = (
                f"rate_limited: {label} {said}; retry after "
                f"{not_before.isoformat()} (cooldown {seconds}s)"
            )
        reason = f"{backend_name} {said}"
        started = agent_cooling(user_id) is None
        _COOLING[str(user_id)] = (not_before, reason)
    else:
        # A harness that died for its own reasons. No ice, no wall: one launch failing is
        # evidence about this job and about nothing else in the queue. It comes straight back
        # a bounded number of times, and then it stays failed — a job that cannot run is a
        # thing to read, not a thing to retry forever.
        attempts = int(payload.get("harness_failures", 0) or 0) + 1
        bound = max(1, int(ctx.settings.agent_retries))
        requeue = attempts < bound
        not_before = None
        reason = ""
        started = False
        said = failure_line(harness_output)
        detail = f"harness_failed: exit {getattr(result, 'exit_code', 0)}"
        if not requeue:
            detail += f" after {attempts} attempt{'s' if attempts != 1 else ''}"
        if said:
            detail += f" — {said}"
        if requeue:
            payload["harness_failures"] = attempts
        # A cooling reason left by an earlier rate limit is not this row's; the queue reads
        # it back as the tenant's wait and this job states no wait at all.
        payload.pop("cooling_reason", None)

    await ctx.store.complete(
        user_id, job_id, ok=False, detail=detail, claimed_by=executor,
        harness_output=harness_output or None,
    )
    # The draft this launch opened reserves the tenant's whole queue while it exists, and it
    # holds a round nobody is going to continue. Dropped here, under the same lock the error
    # tail uses, and only while this launch still owns it.
    drafts = getattr(rt, "drafts", None)
    if drafts is not None:
        async with drafts.lock(user_id):
            owner = await drafts.owner(user_id, job_id)
            current = await ctx.store.get_job(user_id, job_id)
            if owner is not None and owner.executor == executor and (
                current is not None and getattr(current, "status", "") == "done"
            ):
                await drafts.delete(user_id, job_id, executor=executor)

    if requeue:
        if reason:
            payload["cooling_reason"] = reason
        # Back at the ORIGINAL job's place, not at the end: a round that never ran has not
        # had its turn. `not_before`, when the provider named one, still gates it.
        await ctx.store.enqueue(
            user_id, kind, payload, not_before=not_before,
            order_at=getattr(job, "order_at", None),
        )
    else:
        log.warning("[compile-worker] job %s is not coming back: %s", job_id, detail)

    if started:
        waiting = sum(
            1
            for row in await ctx.store.list_jobs(user_id)
            if row.get("status") == "queued" and row.get("kind") in agent_path_kinds(ctx)
        )
        log.warning(
            "[compile-worker] %s: cooling until %s; %d job(s) wait",
            reason,
            not_before.isoformat(),
            waiting,
        )


def failure_reason(exc: BaseException) -> str:
    """What a job row says about `exc`: its own words, or its class when it has none.

    `httpx.ReadError()` carries an empty message, and `f"worker error: {exc}"` wrote exactly
    `worker error: ` onto a real job row — a failure with no reason on it, for a windowed
    episodes job, with nothing in the log either. A class name is a poor diagnosis and an
    infinitely better one than a blank."""
    text = str(exc).strip()
    if text:
        return text
    name = type(exc).__qualname__
    package = type(exc).__module__.split(".", 1)[0]
    return name if package in ("builtins", "__main__") else f"{package}.{name}"


def _interrupting_fault(job_id: str, exc: BaseException) -> InfraFault | None:
    """The infrastructure fault that interrupted this job, while it may still be put back.

    Counts the interruptions per job: the first `INFRA_JOB_INTERRUPTIONS` are an outage and
    the job goes back; one more means the error is not an outage at all, and the job is
    failed like any other (None)."""
    fault = infrastructure_fault(exc)
    if fault is None:
        return None
    strikes = _INFRA_STRIKES.get(job_id, 0) + 1
    _INFRA_STRIKES[job_id] = strikes
    if strikes > INFRA_JOB_INTERRUPTIONS:
        _INFRA_STRIKES.pop(job_id, None)
        return None
    return fault


async def _fail_or_interrupt(
    ctx: AppContext, user_id: UserId, job: object, exc: Exception, detail: str
) -> None:
    """Fail the job — unless recording the failure is what the outage stopped.

    The completion that records a failure is a database write like any other. When the
    database is what is gone, the job is left to the outage recovery (which writes the kept
    completion once it can: `PostgresStore.write_unwritten_completions`) instead of taking
    the drain down with it."""
    job_id = getattr(job, "job_id")
    try:
        await _fail_job(ctx, user_id, job_id, exc, detail)
    except Exception as fail_exc:
        fault = infrastructure_fault(fail_exc)
        if fault is None:
            raise
        raise InfrastructureInterrupted(fault, user_id=str(user_id), job_id=job_id) from fail_exc


async def _round_incomplete(
    ctx: AppContext, user_id: UserId, job: object, result: object, *, executor: str
) -> None:
    """End a round that did not run to its end and committed nothing, and queue it again.

    What happened the night this was written: a 940k-character source's round timed out,
    the worker's finish found nothing to commit, and the job was recorded `ok=True`,
    `projection:{…"upserted":0…}; rounds:1`, its sources stamped digested — success reported
    about a round that never reached the end of its material. Here the job fails with the
    reason, its sources stay undigested (nothing called `persist_compile_result`), and the
    same payload comes back at the job's own place, a bounded number of times — the same
    `harness_failures` counter and `AGENT_RETRIES` bound as a harness that died.
    """
    from ..cli.draft import ROUND_INCOMPLETE_DETAIL

    job_id = getattr(job, "job_id")
    kind = getattr(job, "kind", COMPILE_JOB_KIND)
    payload = dict(getattr(job, "payload", {}) or {})
    why = str(getattr(result, "incomplete", "") or "") or (
        "timed out" if getattr(result, "timed_out", False)
        else f"exit {getattr(result, 'exit_code', 0)}"
    )
    detail = ROUND_INCOMPLETE_DETAIL.format(why=why)
    attempts = int(payload.get("harness_failures", 0) or 0) + 1
    requeue = attempts < max(1, int(ctx.settings.agent_retries))
    harness_output = (getattr(result, "output", "") or "")[-HARNESS_OUTPUT_CHARS:]
    await ctx.store.complete(
        user_id, job_id, ok=False, detail=detail, claimed_by=executor,
        harness_output=harness_output or None,
    )
    if requeue:
        payload["harness_failures"] = attempts
        payload.pop("cooling_reason", None)
        await ctx.store.enqueue(
            user_id, kind, payload, order_at=getattr(job, "order_at", None)
        )
    else:
        log.warning(
            "[compile-worker] job %s is not coming back: %s (%d attempts)",
            job_id, detail, attempts,
        )


async def _fail_job(ctx: AppContext, user_id: UserId, job_id: str, exc: Exception, detail: str) -> None:
    rt = getattr(exc, "draft_runtime", None)
    executor = getattr(exc, "draft_executor", "")
    if rt is None or not executor:
        await ctx.store.complete(user_id, job_id, ok=False, detail=detail)
        return
    async with rt.drafts.lock(user_id):
        await ctx.store.complete(user_id, job_id, ok=False, detail=detail, claimed_by=executor)
        job = await ctx.store.get_job(user_id, job_id)
        owner = await rt.drafts.owner(user_id, job_id)
        if job is not None and job.status == "done" and owner and owner.executor == executor:
            await rt.drafts.delete(user_id, job_id, executor=executor)


_DRAFT_HOLD_LOGGED: dict[tuple[str, str | None], tuple[str, str]] = {}


async def _steward_holds_draft(
    ctx: AppContext, user_id: UserId, lane: str | None = None
) -> bool:
    """Is somebody outside this body holding this tenant's open round in `lane`?

    Per lane, because a library holds one round per lane: a Steward's compile round at a
    terminal reserves the canonical lane and says so, and the derived lane goes on indexing
    and judging episodes behind it rather than standing still for it."""
    peek = getattr(ctx.store, "held_draft", None)
    held = await peek(user_id, lane=lane) if peek is not None else None
    key = (str(user_id), lane)
    if held is None or held[1].executor.startswith("worker:"):
        _DRAFT_HOLD_LOGGED.pop(key, None)
        return False
    job_id, owner = held
    seen = (job_id, owner.executor)
    if _DRAFT_HOLD_LOGGED.get(key) != seen:
        log.info("job %s for %s is held by %s; the worker is not claiming this tenant's "
                 "%s-lane work",
                 job_id, user_id, owner.executor or "legacy:unknown", lane or "queued")
        _DRAFT_HOLD_LOGGED[key] = seen
    return True


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
    semantic = (plan.semantic_indexing_requested or plan.semantic_indexing) if plan else "full"
    if getattr(ctx.settings, "semantic_retrieval", "on") == "off":
        semantic = "none"

    # L1: unconditional (I3) — an archived source is indexed exactly like a live one and
    # simply carries the flag, so it stays reachable by an `include_archived` search and a
    # re-index of it never silently re-enters the default candidate pool.
    archived = ns.raw.archived_at is not None
    await ctx.lexical.index_blocks(user_id, source_id, ns.blocks, archived=archived)

    # L2: by IntakePlan (semantic_indexing knob).
    replace_selection = False
    if semantic != "none" and executor_for(ctx.settings, "compile").is_agent:
        # The whole-source manifest, or every window of a source judged in several.
        judgement = await agent_judgement(ctx, user_id, source_id, ns.blocks)
        replace_selection = judgement is not None
        if judgement is None:
            # Index jobs are serialized per tenant. Retrying L1 must not enqueue the same
            # unmade judgement twice; a kept judgement is replayed, never commissioned again.
            pending = await ctx.store.list_jobs(user_id)
            if not any(j["kind"] == "episodes" and j["status"] in ("queued", "claimed")
                       and j["payload"].get("source_id") == str(source_id) for j in pending):
                # At THIS job's place in the queue. The compile of this source was queued
                # after its index job, so the judgement lands ahead of that compile — rather
                # than behind every compile already waiting, which left nearly every round
                # compiling a source whose semantic episodes did not exist yet.
                await ctx.store.enqueue(
                    user_id, "episodes", {"source_id": str(source_id)},
                    order_at=getattr(job, "order_at", None),
                )
        chunks = await full_l2_chunks(ctx, source_id, ns.blocks, ns.structure, user_id, raw=ns.raw)
    elif semantic == "full":
        chunks = await full_l2_chunks(
            ctx, source_id, ns.blocks, ns.structure, user_id, raw=ns.raw
        )
    elif semantic == "summary":
        chunks = _summary_chunks(source_id, ns)
    else:
        chunks = []
    if chunks:
        embedded = await embed_l2_chunks(ctx, chunks, ns)
        if replace_selection:
            await ctx.vectors.delete_source_chunks(user_id, source_id)
        await ctx.vectors.upsert_chunks(user_id, embedded, archived=archived)
    elif replace_selection:
        await ctx.vectors.delete_source_chunks(user_id, source_id)

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


def worker_tenants(ctx: AppContext) -> tuple[str, ...]:
    """The tenants this body is allowed to touch; empty = every tenant (§11.7).

    One place reads the setting, because every queue call this module makes has to state the
    same restriction: a filter honoured by the drain but not by the startup self-heal would
    still reach into another engine's library."""
    return ctx.settings.worker_tenant_ids()


async def requeue_orphaned_jobs(
    ctx: AppContext, *, label: str = "compile-worker", skip_jobs: Sequence[str] = ()
) -> int:
    """Startup self-heal: return every job orphaned as 'claimed' to 'queued'.

    A process killed mid-job (typically during a long LLM call) leaves its row 'claimed'
    forever, and `claim_next` refuses to hand out any further job for that user while one
    is in flight — so the orphan silently blocks that user's whole queue. A later drain
    then processes 0 jobs and the caller reads that as "the batch failed".

    Every entrypoint that drains the queue must call this once BEFORE its first drain, not
    just the long-running worker: an experiment/demo script that reuses a tenant inherits
    the exact same orphan.

    Legacy model claims have no draft or launch lease to prove liveness. Recovery of those
    claims still assumes their worker has stopped; an unfiltered sweep can reclaim other
    tenants' model jobs too. Agent claims below carry their own mechanical liveness proof.

    Unless this body has a tenant filter (`WORKER_TENANTS`, §11.7), which is exactly the
    deployment where that blast radius stops being sound: two engine processes on one
    Postgres, one library each, and the other engine's claimed job is its work in flight
    rather than anybody's orphan. The sweep is then bounded to this worker's own tenants.

    Agent claims have stronger evidence (docs/design/coding-agent-mode.md §6): an interactive
    draft's timestamp, or an unattended launch's PG lease. A live launch is spared until
    the full `COMPILE_DRAFT_TTL` expires, independently of the much shorter takeover grace;
    a dead launch is reclaimed immediately. Recovery skips any command currently holding
    the tenant's draft lock, so it cannot interrupt gate/commit or a takeover in flight.

    A dead launch's draft that holds work is kept with its requeued job and continued by
    the next launch, rather than thrown away (`PostgresStore.requeue_claimed_jobs`).

    `skip_jobs` are the claims this very process is running right now (`in_flight_jobs`).
    Empty at startup, where nothing is in flight by definition; stated by the periodic sweep
    (`_selfheal_forever`), which applies these same rules WHILE the drain works — and a job
    whose body is running in this process is nobody's orphan, whatever evidence its row
    carries (an index job has no draft and no launch lease at all).

    Returns the number requeued and reports it on stdout (silence means nothing was stuck).
    """
    # The adapter checks the launch lease and timestamp under the command/queue locks.
    reclaimed = await ctx.store.requeue_claimed_jobs(
        draft_ttl=ctx.settings.compile_draft_ttl,
        tenants=worker_tenants(ctx),
        skip_jobs=tuple(skip_jobs),
    )
    if reclaimed:
        print(f"[{label}] reclaimed {reclaimed} orphaned claimed job(s) → requeued", flush=True)
    # The other thing an agent can walk away from: a `pkc recall --evidence` hand-over whose
    # answer never came (docs/design/coding-agent-mode.md §5.1). It is swept HERE and not on
    # a clock of its own, because it is the same fact about the same body — a round nobody
    # came back to — and one place to look is worth more than a second sweeper. Nothing is
    # lost by the deletion: a question the Steward never answered leaves no consultation, and
    # that is what happened.
    await sweep_recall_handoffs(ctx, label=label)
    return reclaimed


async def sweep_recall_handoffs(ctx: AppContext, *, label: str = "compile-worker") -> int:
    """Delete the recall hand-overs older than `RECALL_HANDOFF_TTL`; return how many.

    Best-effort and never fatal: a store that predates the table (or a deployment whose store
    does not offer the port at all) leaves the count at zero rather than stopping a worker
    from starting."""
    ttl = int(getattr(ctx.settings, "recall_handoff_ttl", 0) or 0)
    if ttl <= 0:
        return 0
    from ..adapters.postgres import PostgresRecallHandoffStore

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl)
    try:
        swept = await PostgresRecallHandoffStore(ctx.store).sweep(cutoff)
    except Exception:  # noqa: BLE001 — bookkeeping never blocks a worker's start
        return 0
    if swept:
        print(f"[{label}] swept {swept} expired recall handoff(s)", flush=True)
    return swept


def in_lane(kind: str, lane: str | None) -> bool:
    """Is a job of `kind` this drain's to run? True for every kind when no lane is named."""
    return lane is None or lane_of(kind) == lane


async def _waiting_for_steward(ctx: AppContext, user_id: UserId) -> int:
    """How many of this user's compile jobs are queued for the Steward to open.

    Asked once per drain, not once per job: under an agent executor the worker walks past
    these rows every sweep, and a line per row would say the same thing every two seconds.
    """
    lister = getattr(ctx.store, "list_jobs", None)
    if lister is None:
        return 0
    return sum(
        1
        for job in await lister(user_id)
        if job.get("status") == "queued" and job.get("kind") == COMPILE_JOB_KIND
    )


async def drain_user(
    ctx: AppContext,
    chat_model: BaseChatModel | None,
    skill: SkillVersion | None,
    user_id: UserId,
    *,
    skill_cache: dict[str, SkillVersion] | None = None,
    lane: str | None = None,
) -> int:
    """Claim + process this user's queued jobs of one lane until that lane is empty.

    Kind-agnostic claim WITHIN the lane — index and the recall projection kinds first, then
    everything else in queue order (`CLAIM_FIRST_KINDS`, adapters/postgres.py); dispatch by job.kind —
    "index" → process_index_job (L1/L2), "evolve"/"evolve_adopt" → the schema-evolve flow,
    "groom" → one document rollover, "archive" → one confirmed archive proposal (a move, no
    model), "recall_projection"/"recall_rebuild" → the use-side ledger (no model, no skill),
    anything else ("compile") → process_job.

    `skill` is the per-USER skill for this drain: pass an explicit SkillVersion to force
    one (upgrade/version tests), or None to load it per-job via `skill_for_user` (the
    worker's default — each owner compiles with their own composed skill). It resolves
    lazily on the first compile job (index jobs need no skill) and is memoized here + in
    `skill_cache` for the rest of the sweep.

    Under an AGENT executor the compile jobs are not this body's to run: the round belongs to
    the Steward, which opens it with `pkc draft open` (docs/design/coding-agent-mode.md §9).
    They are skipped at the CLAIM rather than after it — claiming one and putting it back
    would still have spent that user's single in-flight slot, and everything queued behind it
    (index, projection, groom) would wait on a round nobody in this process is going to run.
    Everything else drains exactly as it always has.

    A user this worker does not serve (`WORKER_TENANTS`, single-machine-edition.md §11.7) is
    refused at the same claim: the drain returns 0 without having held anything.

    `lane` (`job_lanes.py`) is which half of this tenant's queue this call drains — the
    canonical lane (everything that can write the library) or the derived one (index,
    episodes, the recall projections). The worker runs one of these per lane per tenant, at
    the same time, and the claim's serialization is per lane too, so the canonical writer
    stays exactly as single as it was. `None` drains the whole queue in one loop, which is
    what every caller that is not the worker's own sweep wants: an ops command, a scaffolded
    application's `compile` subcommand, a test that wants one ordering to assert.

    Between a claim and that claim's completion the job is named in `_IN_FLIGHT` under this
    lane. That mark is what the outage recovery puts back, so it survives the exception and
    is cleared by whoever recovered — never here, unless what ends this drain is not an
    outage at all."""
    resolved = skill
    processed = 0
    # Under an agent executor there are two postures, and they differ in exactly one place:
    # whether this body claims a compile job. Unattended, it does — and hands it to a
    # launched harness. Interactive, it does not, and the round waits for `pkc draft open`.
    steward_kinds = tuple(
        role for role in (COMPILE_JOB_KIND, "evolve")
        if executor_for(ctx.settings, role).is_agent and not unattended(ctx, role)
    )
    if not unattended(ctx):
        # Episodes always belong to the compile harness, even if the executor was changed
        # while some were queued. They must never reach the default compile dispatch.
        steward_kinds += ("episodes",)
    if COMPILE_JOB_KIND in steward_kinds and in_lane(COMPILE_JOB_KIND, lane):
        waiting = await _waiting_for_steward(ctx, user_id)
        if waiting:
            log.info(
                "%s compile job(s) for %s are waiting for the Steward "
                "(executor %s); the worker is not claiming them",
                waiting,
                user_id,
                ctx.compile_executor.spec,
            )
    while True:
        if await _steward_holds_draft(ctx, user_id, lane):
            return processed
        # A tenant on ice claims nothing a harness would have to run. Asked HERE and not once
        # before the loop, because the ice is usually laid DURING a drain — the first job of
        # a long queue is the one that meets the spent subscription, and a list computed
        # before it would let the other three hundred through behind it. Everything else —
        # index, projection, groom, archive — keeps flowing: the subscription is what is out
        # of room, not the library.
        skip = steward_kinds
        if agent_cooling(user_id) is not None:
            skip += tuple(k for k in agent_path_kinds(ctx) if k not in skip)
        try:
            # The claim and the mark it leaves are one step (`_CLAIM_GATE`): a row that
            # became this body's must never be a row the self-heal still reads as free.
            async with _CLAIM_GATE:
                job = await ctx.store.claim_next(
                    user_id, exclude_kinds=skip, tenants=worker_tenants(ctx), lane=lane
                )
                if job is not None:
                    # From here the row is this body's, and stays this body's until a
                    # completion is written for it. Everything between — the dispatch, a
                    # harness round, the derived work that FOLLOWS a round — is covered by
                    # the mark rather than by whichever call happened to raise.
                    _IN_FLIGHT[_lane_key(lane)] = (str(user_id), job.job_id)
        except Exception as exc:
            # A claim whose connection went after its UPDATE was sent may have landed. The
            # adapter names that job; it is this body's, so the recovery puts it back.
            unsettled = getattr(exc, "unsettled_claim", None)
            fault = infrastructure_fault(exc)
            if fault is not None and unsettled:
                raise InfrastructureInterrupted(
                    fault, user_id=unsettled[0], job_id=unsettled[1]
                ) from exc
            raise
        if job is None:
            return processed
        try:
            kind = getattr(job, "kind", "compile")
            if kind == "index":
                await process_index_job(ctx, user_id, job)
            elif kind == "episodes":
                from ..cli.episodes import split_oversized

                # A source too long for one round's input is not launched: the job becomes
                # one windowed job per window, at its own place, and the drain moves on.
                if await split_oversized(ctx, ctx.store, user_id, job) is None:
                    await process_agent_job(ctx, user_id, job)
            elif kind == "evolve":
                if unattended(ctx, "evolve"):
                    await process_agent_job(ctx, user_id, job)
                else:
                    await run_evolve_job(ctx, user_id, job)
            elif kind == "evolve_adopt":
                await adopt_evolve_job(ctx, user_id, job)
                resolved = None
                if skill_cache is not None:
                    skill_cache.pop(str(user_id), None)
            elif kind == GROOM_JOB_KIND:
                await run_groom_job(ctx, user_id, job)
            elif kind == ARCHIVE_JOB_KIND:
                await run_archive_job(ctx, user_id, job)
            elif kind == RECALL_PROJECTION_JOB_KIND:
                await run_recall_projection_job(ctx, user_id, job)
            elif kind == RECALL_REBUILD_JOB_KIND:
                await run_recall_rebuild_job(ctx, user_id, job)
            elif kind == CHALLENGE_JOB_KIND:
                if executor_for(ctx.settings, "compile").is_agent:
                    await ctx.store.complete(user_id, job.job_id, ok=True, detail="challenge skipped under an agent executor")
                    _IN_FLIGHT.pop(_lane_key(lane), None)
                    processed += 1
                    continue
                if resolved is None:
                    resolved = await _resolve_user_skill(ctx, user_id, skill_cache)
                await run_challenge_job(
                    ctx, ctx.get_chat_model("challenge"), resolved, user_id, job
                )
            elif kind == COMPILE_JOB_KIND and unattended(ctx):
                await process_agent_job(ctx, user_id, job)
            else:
                if resolved is None:
                    resolved = await _resolve_user_skill(ctx, user_id, skill_cache)
                await process_job(ctx, chat_model, resolved, user_id, job)
        except CanonicalDirtyError as exc:
            # STATED, not swallowed into "worker error: …". The canonical repository holds
            # somebody else's uncommitted changes, the adapter refused rather than discarding
            # them, and nothing was written — a fault an operator fixes in one command once
            # they can see it named. Every job kind that commits arrives here (compile,
            # groom, evolve adopt); the archive job states the same code in its own detail,
            # because it also has a proposal row to fail.
            await _fail_or_interrupt(ctx, user_id, job, exc, exc.detail)
        except Exception as exc:  # noqa: BLE001 — never leave a job stuck 'claimed'
            fault = _interrupting_fault(job.job_id, exc)
            if fault is not None:
                # The stack went away under this job. Not the job's failure: the drain stops,
                # waits for the stack, and puts this job back (`ride_out`).
                raise InfrastructureInterrupted(
                    fault, user_id=str(user_id), job_id=job.job_id
                ) from exc
            # The traceback, once, where an operator looks. A job row holds one sentence;
            # the stack that produced it lived only in a worker process that has since moved
            # on, and a job completed `worker error: ` with nothing logged anywhere left
            # nobody anything to read. Named by lane and job, because two lanes fail
            # independently.
            log.exception(
                "[compile-worker] %s lane: job %s failed",
                lane or "queued", job.job_id,
            )
            await _fail_or_interrupt(
                ctx, user_id, job, exc, f"worker error: {failure_reason(exc)}"
            )
        finally:
            # Short-lived per-job trace flush: a worker sweep may exit right after, so
            # never rely on the background batch surviving process end.
            await ctx.flush_traces()
        # Reached only when this job ended with a row of its own — completed by its body, by
        # the failure path, or re-queued by it. An exception on its way out (an outage above
        # all) skips this line on purpose: the claim is still open, and the mark is what says
        # so to the recovery.
        _INFRA_STRIKES.pop(job.job_id, None)
        _IN_FLIGHT.pop(_lane_key(lane), None)
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
    ctx: AppContext,
    chat_model: BaseChatModel | None,
    skill: SkillVersion | None = None,
    *,
    lane: str | None = None,
) -> int:
    """One sweep across every user with data; returns the job count processed.

    `skill=None` (the worker default) loads each user's own skill per job; a per-sweep
    cache keyed by user avoids re-reading a manifest from git once per job.

    `lane` drains one lane of every tenant (`job_lanes.py`); the worker runs one sweep loop
    per lane and they run at the same time. `None` sweeps the whole queue in one pass, which
    is what a caller outside the worker's own loop means."""
    total = 0
    cache: dict[str, SkillVersion] = {}
    for uid in await _users_with_jobs(ctx):
        total += await drain_user(
            ctx, chat_model, skill, UserId(uid), skill_cache=cache, lane=lane
        )
    return total


async def _users_with_jobs(ctx: AppContext) -> list[str]:
    """Every tenant whose queue this sweep must look at.

    L0 sources are no longer the only substrate a job can come from. A `recall_projection`
    job is enqueued in the same transaction as a consultation row, and a tenant can ask
    business questions before it has imported anything at all — so enumerating from
    `sources` alone left exactly that tenant's jobs queued forever, with nothing in the
    system able to notice.

    With a tenant filter set (`WORKER_TENANTS`, single-machine-edition.md §11.7) the answer
    is the filter itself: those tenants ARE the ones this worker serves, whether or not they
    have imported anything yet, and no other tenant's queue is this body's to look at. The
    claim query refuses the rest anyway — this only saves the sweep from asking.
    """
    tenants = worker_tenants(ctx)
    if tenants:
        return sorted(tenants)
    users = set(await ctx.store.list_users())
    lister = getattr(ctx.store, "list_consultation_users", None)
    if lister is not None:
        users |= set(await lister())
    return sorted(users)


def _in_flight(exc: BaseException) -> tuple[str, str] | None:
    """The `(user_id, job_id)` this body held when the outage hit it, if it held one."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, InfrastructureInterrupted):
            return current.user_id, current.job_id
        current = current.__cause__
    return None


async def _probe(ctx: AppContext, kind: str) -> None:
    """Ask the service that failed whether it is back. Raises the transient error while it
    is not; returns when it answers — with anything, since an answer that is not a connection
    failure means the service is there and whatever it said is the drain's to meet.

    A fault that names no service (`http`: a transport error that reached the drain without
    its client's wrapper) asks every peer this body holds. Which one went away is exactly
    what such an error does not say, and resuming on a probe of the wrong service is
    resuming on no evidence at all."""
    ports = {
        "postgres": getattr(ctx, "store", None),
        "qdrant": getattr(ctx, "vectors", None),
        "meilisearch": getattr(ctx, "lexical", None),
        "s3": getattr(ctx, "media", None),
    }
    targets = [ports[kind]] if kind in ports else list(ports.values())
    for target in targets:
        ping = getattr(target, "ping", None)
        if ping is None:
            continue
        try:
            await ping()
        except Exception as exc:
            if infrastructure_fault(exc) is not None:
                raise


async def _job_status(ctx: AppContext, user_id: str, job_id: str) -> str:
    """This job's status as the queue has it now, or "" when the store cannot say."""
    getter = getattr(ctx.store, "get_job", None)
    if getter is None:
        return ""
    return str(getattr(await getter(UserId(user_id), job_id), "status", "") or "")


async def _recover(ctx: AppContext, in_flight: tuple[str, str] | None) -> list[str]:
    """Put this body's own interrupted work back, on the startup self-heal's own terms.

    First the completions the outage kept from landing (a job whose work was done is
    completed, never run again); then the job that was in flight, if it is still claimed —
    requeued by the same `requeue_claimed_jobs` rules the self-heal applies (a live launch
    spared, a dead launch's draft with work kept), narrowed to that one job so no other
    body's claim is touched.

    Returns what it did, for the recovery line, and it always ends by saying what became of
    the in-flight job — requeued, completed, or there was none. The silence that used to
    stand for "nothing to do here" is exactly what hid a claim nobody put back."""
    done: list[str] = []
    writer = getattr(ctx.store, "write_unwritten_completions", None)
    if writer is not None:
        written = await writer()
        if written:
            done.append(f"{written} completion(s) written")
    if in_flight is None:
        done.append("no job in flight")
        return done
    user_id, job_id = in_flight
    requeued = await ctx.store.requeue_claimed_jobs(
        draft_ttl=ctx.settings.compile_draft_ttl, tenants=(user_id,), job_id=job_id
    )
    status = await _job_status(ctx, user_id, job_id)
    if requeued or status == "queued":
        done.append(f"job {job_id} requeued")
    elif status == "claimed":
        # The one case where the claim outlives the recovery on purpose: a launch whose lease
        # is still live holds it, and the self-heal's rules spare exactly that. Said out loud,
        # because the periodic sweep is what ends it and a person should know which it was.
        done.append(f"job {job_id} still claimed (a live launch holds it)")
    else:
        done.append(f"job {job_id} completed")
    return done


async def ride_out(
    ctx: AppContext,
    fault: InfraFault,
    in_flight: tuple[str, str] | None,
    *,
    label: str = "compile-worker",
    lane: str | None = None,
) -> None:
    """Wait out one infrastructure outage, then put back what it interrupted.

    One line when it starts, one when it ends, nothing in between: an outage is one event,
    and a log that printed every retry would bury it. The ending line always says what
    happened to the job this lane was holding — `(job <id> requeued)`, `(job <id> completed)`
    or `(no job in flight)` — because a resume line that said nothing is what let a leaked
    claim look like a recovery. A lane names itself in both, because
    each lane waits its own outage out — two lines mean two lanes are waiting, which is a
    different fact from one lane retrying twice. The wait doubles from
    `INFRA_BACKOFF_START_S` to `INFRA_BACKOFF_MAX_S`; each step probes the service that
    failed and then runs the recovery, which needs Postgres — so a probe that passes while
    Postgres is still away simply waits another step."""
    delay = INFRA_BACKOFF_START_S
    started = time.monotonic()
    where = f"[{label}] {lane} lane:" if lane else f"[{label}]"
    print(
        f"{where} infrastructure unavailable ({fault.describe()}); retrying in {delay:g}s",
        flush=True,
    )
    while True:
        await asyncio.sleep(delay)
        try:
            await _probe(ctx, fault.kind)
            done = await _recover(ctx, in_flight)
        except Exception as exc:
            if infrastructure_fault(exc) is None:
                raise
            delay = min(delay * 2, INFRA_BACKOFF_MAX_S)
            continue
        print(
            f"{where} infrastructure back after {time.monotonic() - started:.0f}s; resuming"
            f" ({', '.join(done)})",
            flush=True,
        )
        return


async def drain_forever(
    ctx: AppContext, chat_model: BaseChatModel | None, *, label: str = "compile-worker"
) -> None:
    """Sweep every lane until cancelled — one task per lane, running at the same time.

    Each lane is the loop this function used to be: sweep, wait out an outage in place
    (`ride_out`), let anything else propagate. They are separate loops on purpose — an
    outage the canonical lane meets is waited out by the canonical lane, and the derived lane
    goes on indexing while it waits (both pay the same backoff only if the outage is theirs
    too, which for a shared Postgres it will be). An error that is not an outage still stops
    the worker: it ends its lane, the gather re-raises it, and the sibling lane is cancelled
    on the way out, exactly as a single loop ended the worker before.

    Beside the lanes runs one more task, on a clock rather than on the work: the self-heal
    (`_selfheal_forever`), so a claim this process can no longer account for is returned
    within a minute instead of at the next process start.
    """
    print(
        f"[{label}] draining {len(LANES)} lanes ({', '.join(LANES)}): one job in flight per "
        f"lane per library — the {CANONICAL_LANE} lane is still the library's single writer, "
        "and at most one agent round runs per lane",
        flush=True,
    )
    tasks = [
        asyncio.create_task(
            _drain_lane_forever(ctx, chat_model, lane, label=label), name=f"{label}-{lane}"
        )
        for lane in LANES
    ]
    tasks.append(
        asyncio.create_task(_selfheal_forever(ctx, label=label), name=f"{label}-selfheal")
    )
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _drain_lane_forever(
    ctx: AppContext,
    chat_model: BaseChatModel | None,
    lane: str,
    *,
    label: str = "compile-worker",
) -> None:
    """One lane's sweep loop (`drain_forever`)."""
    key = _lane_key(lane)
    while True:
        try:
            n = await compile_pending(ctx, chat_model, lane=lane)
        except Exception as exc:
            fault = infrastructure_fault(exc)
            if fault is None:
                raise
            # The drain's own account of what it holds comes first; the exception's is the
            # fallback for the one failure that happens before the mark exists — a claim
            # whose commit was lost, which names the row it may have taken.
            await ride_out(
                ctx, fault, _IN_FLIGHT.get(key) or _in_flight(exc), label=label, lane=lane
            )
            _IN_FLIGHT.pop(key, None)
            continue
        if n:
            print(f"[{label}] {lane} lane: processed {n} job(s)")
        await asyncio.sleep(IDLE_SWEEP_S)


async def _selfheal_forever(ctx: AppContext, *, label: str = "compile-worker") -> None:
    """The startup self-heal, on a clock (`WORKER_SELFHEAL_S`, 0 turns it off).

    Same call, same rules, same evidence as the sweep `run_forever` runs before its first
    drain — a live launch lease spared, a `pkc` command's lock respected, a dead launch's
    draft with work kept — narrowed by the claims this process is running right now, which
    are not orphans.

    It exists because "the next process start" was the only thing that ended a leaked claim,
    and a claim blocks its lane for its whole library: a derived-lane claim nobody put back
    left 542 jobs pending for half an hour, canonical included, because every compile waits
    on its own source's derived work. A minute is short enough that a person does not notice
    and long enough that the sweep costs nothing.

    One line when it requeues something, nothing when it does not: this runs on a clock, and
    a clock that logs is a log nobody reads."""
    interval = float(getattr(ctx.settings, "worker_selfheal_s", 0) or 0)
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            # Under the same gate the claim takes, so "what this process holds" cannot change
            # between the question and the sweep that acts on the answer.
            async with _CLAIM_GATE:
                await requeue_orphaned_jobs(
                    ctx, label=f"{label} self-heal", skip_jobs=in_flight_jobs()
                )
        except Exception as exc:  # noqa: BLE001 — an outage is the lanes' to wait out
            if infrastructure_fault(exc) is None:
                raise
            # The stack is away. The lane that met it is already waiting it out with a line
            # of its own; a second voice saying the same thing every minute is noise.


async def run_forever(settings: Settings | None = None) -> None:
    if settings is None:
        settings = get_settings()
    # The engine starts this in a task already named `pkc-engine-worker`; the standalone
    # worker process names its connections `pkc-worker`.
    with connection_role_as(CONNECTION_ROLE.get() or "pkc-worker"):
        ctx = await build_context(settings)
    try:
        executor = executor_for(settings, "compile")
        # An agent executor has no chat model to build, and building one would raise: what runs
        # the round is a harness under the Owner's subscription, and the worker's part is to
        # leave its jobs alone (§9). Every other kind of job is drained as before.
        chat_model = None if executor.is_agent else build_chat_model_for(settings, "compile")
        # No single global skill: each job loads its user's own composed skill (skill=None).
        print(
            f"[compile-worker] executor={executor.kind} model={executor.spec} "
            f"canonical={settings.canonical_root} "
            f"agent_unattended={settings.agent_unattended} "
            f"posture={'unattended' if settings.agent_unattended else 'interactive'}"
        )
        # Stated once, at the start: a worker that silently ignores most of a shared queue
        # looks exactly like a worker that is stuck. An empty filter prints nothing, because
        # "every tenant" is what a worker has always been.
        tenants = settings.worker_tenant_ids()
        if tenants:
            print(
                f"[compile-worker] tenants={','.join(tenants)} — jobs of any other tenant "
                "on this store are neither claimed nor reclaimed"
            )
        if executor.is_agent and settings.agent_unattended:
            print(
                f"[compile-worker] compile jobs are claimed and handed to {executor.backend} "
                "(unattended); set PNEUMA_KNOWLEDGE_AGENT_UNATTENDED=false to leave them for a "
                "Steward at a terminal"
            )
        elif executor.is_agent:
            print(
                "[compile-worker] compile jobs are left queued for the Steward "
                "(`pkc draft open <job>`); index, projection and groom jobs drain as usual"
            )
        # Self-heal on startup: requeue any job orphaned as 'claimed' by a previous worker
        # that died mid-job (killed during an LLM call), which would otherwise block its
        # user's queue forever.
        await requeue_orphaned_jobs(ctx)
        await drain_forever(ctx, chat_model)
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
