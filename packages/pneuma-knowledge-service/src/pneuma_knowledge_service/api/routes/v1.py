"""API surface: /v1/users/{user_id}/… (architecture.md §3, §7).

Every route is scoped by user_id in the path (invariant I1). recall supports four
modes: `rag` (dual-path L1+L2 RRF), `fast` (claims + body windows), `deep` (bounded
agentic search) and briefing ask.

Every lane that costs a user real seconds also has an SSE twin that narrates it while it
runs — `/recall/stream` (fast and deep), `/briefings/stream`, `/briefings/{id}/ask/stream`.
They speak one event vocabulary (`stage`, `token`, deep's `step`, then `done` / `error`) and
each one's `done` frame is built by the same projection its plain POST returns, so the two
cannot drift. The plain routes are untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

from pneuma_knowledge_core.components import registered_components
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.intake import INTAKE_ARCHETYPES, IntakeArchetype
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import ConversationTurn, SourceOrigin
from pneuma_knowledge_core.domain.time_context import time_context_for
from pneuma_knowledge_core.ingest.source_contracts import SourceContract
from pneuma_knowledge_core.domain.user import INDUSTRIES, LEVELS, ROLES, UserProfile
from pneuma_knowledge_core.persona import synthesize_profile_draft
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.briefing import (
    DEFAULT_TOOL_NAMES,
    Briefing,
    BriefingScope,
    briefing_ask,
    build_briefing,
)
from pneuma_knowledge_core.recall.citation_alias import strip_citations
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.recall.rag import (
    RAG_RETRIEVE_CHILDREN,
    RAG_STAGE_ORDER,
    rag_recall,
)
from pneuma_knowledge_core.recall.scope import SnapshotScope
from pneuma_knowledge_core.recall.stage_timing import StageRecorder
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, RootModel

from ... import kb_snapshots
from ...adapters.user_info_mock import _synthesize
from ...dataset import build_dataset
from ...ingest import ingest_conversation
from ...ingest_document import ingest_document, preview_document
from ...ingest_sources import ingest_source_contract
from ...kb_snapshots import KbSnapshot, SnapshotNotFound, SnapshotNotReady
from ...pagination import CursorError, decode_cursor, encode_cursor
from ...skills import packs_for_user, skill_for_user
from ...snapshot_tenant import assert_writable
from ...wiring import AppContext, llm_call_config

# Valid user_id shape — external key, keep it filesystem/URL-safe (mirrors the web
# USER_ID_RE in ProfileCard.tsx). Used to accept/derive the AI-generated persona's id.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_snapshot(
    ctx: AppContext, user: UserId, snapshot: str | None
) -> str:
    """A snapshot ref: the given one, else the current HEAD sha (empty if no canonical)."""
    if snapshot:
        return snapshot
    snaps = await ctx.canonical.snapshots(user)
    return snaps[0].ref if snaps else ""

# User-scoped surface (invariant I1: first path segment is users/{user_id}).
router = APIRouter(prefix="/v1/users/{user_id}")
# Root /v1 surface for the (non-user-scoped) user directory — the UI switcher's
# data source. Returns only the id set, never any user's content.
root_router = APIRouter(prefix="/v1")


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


class ConversationIn(BaseModel):
    turns: list[ConversationTurn]
    title: str = "conversation"
    meta: dict[str, Any] | None = None
    # 'context_stream' = first-party diarized meeting transcript (turns carry role/
    # speaker_id → owner-aware compile path); 'upload' = generic conversation.
    origin: SourceOrigin = "upload"


class SourceOut(BaseModel):
    source_id: str
    kind: str
    origin: str
    source_class: str
    title: str
    created_at: str
    # The day the MATERIAL happened, in the subject's own zone (`meta["occurred_on"]`,
    # stamped at ingest). `created_at` is the ingest wall clock and cannot answer it: a
    # backfill of six months of capture all carries today's date. null = the source never
    # got one, and the reader is expected to say so rather than pretend.
    occurred_on: str | None = None
    intake_plan: dict[str, Any] | None
    block_count: int
    # M3b: null = not yet compiled into canonical; set once the worker digests it.
    digested_at: str | None = None


class PageMetaOut(BaseModel):
    limit: int
    total: int
    next_cursor: str | None


class SourcePageOut(BaseModel):
    items: list[SourceOut]
    page: PageMetaOut


class ActivityDayOut(BaseModel):
    date: str
    count: int
    kinds: dict[str, int]


class ActivityCalendarOut(BaseModel):
    days: list[ActivityDayOut]


class WorkspaceSummaryOut(BaseModel):
    sources: int
    #: Every job this workspace has ever enqueued, and — beside it — the ones that finished
    #: without committing (`done ∧ ok=false`, the same set `GET /jobs?status=failed` lists).
    #: A total alone cannot tell a healthy workspace from one whose every compile aborted at
    #: the gate, because both are `done`.
    jobs: int
    jobs_failed: int
    documents: int
    claims: int
    snapshots: int


class DerivedMediaTextOut(BaseModel):
    kind: str
    text: str
    producer: str


class BlockImageOut(BaseModel):
    image_id: str
    mime_type: str
    sha256: str
    size_bytes: int
    derived: list[DerivedMediaTextOut]
    metadata: dict[str, Any]
    url: str


class BlockOut(BaseModel):
    index: int
    text: str
    section_path: list[str]
    images: list[BlockImageOut]


class SourceDetailOut(BaseModel):
    source_id: str
    kind: str
    origin: str
    source_class: str
    title: str
    mime: str
    created_at: str
    meta: dict[str, Any]
    intake_plan: dict[str, Any] | None
    structure: dict[str, Any]
    blocks: list[BlockOut]


class IngestOut(BaseModel):
    source_id: str
    intake_plan: dict[str, Any]
    deduplicated: bool


class OfficialImportOut(BaseModel):
    contract_schema: str
    sources: list[IngestOut]


class OfficialSourceIn(RootModel[SourceContract]):
    """Bare discriminated union body for OpenAPI and runtime validation."""


class RecallIn(BaseModel):
    query: str
    mode: str = "rag"
    limit: int = 10
    # fast/deep: relative-time answers resolve against this (server injects now if null).
    as_of: str | None = None
    # A frozen knowledge-base snapshot to answer over: its id or its label. null = the live
    # base (HEAD), which is byte-for-byte the pre-snapshot behavior on every lane.
    snapshot: str | None = None
    # fast/deep: answer-style preset override for this call; null = the deployment's
    # PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE.
    answer_style: Literal["concise", "conversational", "detailed"] | None = None
    # Fast-only, per-call composition overrides. null uses the deployment's engine setting.
    # Keeping these separate from `mode` makes the trade-off explicit without multiplying
    # lane names or changing rag/deep semantics.
    evidence_strategy: Literal["ranked", "select", "all"] | None = None
    answer_format: Literal["text", "structured"] | None = None
    include_original_modalities: list[Literal["image"]] = Field(
        default_factory=list,
        description=(
            "Original multimodal evidence to include from selected source windows in "
            "fast/deep answering modes. "
            "Currently supports 'image'; request it only when answering requires direct "
            "visual inspection (for example objects, colours, layout, or whether something "
            "appears in an image). Leave the list empty for textual facts such as dates, "
            "names, plans, and events. Labelled derived representations remain available "
            "when their original modality is omitted."
        ),
    )


class SnapshotScopeOut(BaseModel):
    """Which read plane actually answered — echoed so a client can never be in doubt."""

    snapshot_id: str
    label: str
    canonical_ref: str
    created_at: str | None


class RecallHitOut(BaseModel):
    source_id: str
    block_start: int
    block_end: int
    text: str
    paths: list[str]
    score: float


class UsedClaimOut(BaseModel):
    anchor: str
    document_path: str
    section_path: list[str]
    text: str
    citations: list[dict[str, Any]]
    paths: list[str]
    score: float
    # Mechanical labels, never prose: the ones a component path attached to its own item
    # ("current", "superseded"), plus `via:<path>` on a RANKED claim that a lookup also
    # returned — corroboration shown where the claim already is, instead of a second copy
    # in the component face.
    labels: list[str] = Field(default_factory=list)


class ComponentEvidenceOut(BaseModel):
    """fast only: one routed component lookup — the path, the arguments the router chose,
    and what it contributed (its own evidence face; never fused into the ranked pool)."""

    path: str
    args: dict[str, Any]
    claims: list[UsedClaimOut] = Field(default_factory=list)
    windows: list["RecallHitOut"] = Field(default_factory=list)
    degraded: str | None = None
    # What the cap and the character budget did not show — the total, and the same omission
    # described per section (claims) or per day/source (windows), so a truncated lookup is
    # recoverable rather than merely reported.
    dropped: int = 0
    dropped_summary: list[tuple[str, int]] = Field(default_factory=list)
    # How many of this lookup's results the ranked faces already carry: hidden here rather
    # than shown twice, and stated so the reader knows the lookup corroborated them.
    already_shown: int = 0


class StageTimingOut(BaseModel):
    """One stage's measured wall-clock — every lane, one shape, its own vocabulary.

    **fast** (core `recall/stage_timing.py`) sends the whole FIXED vocabulary every time, in
    order: a stage that did not run is present with `status="skipped"` and `ms=0`, so a client
    lays out a stable strip and can tell "did not happen" from "was free". Children of the
    retrieval gather carry a dotted name (`retrieve.claims`, `retrieve.path:person`) and
    report their OWN duration, so they sum to more than their parent — the parent is the
    gather's wall-clock.

    **deep** (core `recall/agentic.py`) has no fixed vocabulary to send: how many turns the
    agentic loop took and which tools it reached for is precisely what is being reported. The
    list is therefore the run's own sequence — `turn:N` per model turn, `tool:<name>` per tool
    call (the same call the matching `trail` record carries `ms` for), `finalize` when the
    budget forced a closing call — and nothing is `skipped`, because there is no list of
    stages that could have run. `total` wraps the agentic LOOP; the seed retrieval that
    precedes it is not a loop stage and is not inside that total.

    **rag** (core `recall/rag.py`) is a fixed vocabulary too, and the smallest one: `embed`,
    `retrieve` with its `retrieve.lexical` / `retrieve.vector` children, `fuse`, `expand`,
    `total`. Its children run SEQUENTIALLY rather than in a gather, so unlike fast's they sum
    to their parent instead of exceeding it. There is no model in the lane, so there is no
    answer stage and the stream carries no `token` frames.

    The one arithmetic guarantee, in every lane, is `total >= every other stage`.
    """

    name: str
    ms: int
    status: str = "ran"
    #: The lane's existing degraded reason ("timeout", "error", "invalid_args", …) when the
    #: stage ran and fell back; null otherwise.
    detail: str | None = None
    #: A BOUNDED glance at what the stage was handed and what it produced — the queries a
    #: plan wrote, how many hits a face returned and the first few addresses, the tool calls
    #: a routing turn chose, the characters each assembled section carries. Never full text:
    #: core caps the serialized object at ~1 KB in one place (`bound_preview`), so no lane
    #: and no component can widen it. Null when the stage offered none — an older service, a
    #: stage with nothing worth previewing, or a stage that did not run. Keys belong to the
    #: stage, not to this model: a client renders whatever rows it is given.
    preview: dict | None = None


class StageEventOut(BaseModel):
    """One stage crossing a boundary, sent the moment it does — the LIVE face of the strip.

    The non-streaming routes report `stages` once, with the answer. That is the wrong moment:
    the reader wants to know which stage is running while it is running. The stream routes
    therefore send one of these when a stage BEGINS (`phase="start"`, `ms` null) and one when
    it settles (`phase="end"`, `ms` measured). They come from the same measure sites the final
    `stages` list comes from — one clock — so the picture drawn live and the breakdown that
    arrives with `done` cannot disagree.

    `key` is what identifies a NODE, and it belongs to the lane, not the reader. A fixed
    vocabulary (fast recall, the briefing build) accumulates by name, so `key == name` and a
    later `end` supersedes the earlier one for that key. An agentic lane appends — two calls
    to one tool are two steps — so it mints a fresh key per step. A client keys on `key` and
    prints `name` and is right about both without knowing which lane it is watching.

    `at_ms` is elapsed milliseconds since the LANE began, on the server's clock: it places the
    event on the lane's timeline. It is NOT what a client counter should tick from — a stage
    that opens three seconds into a lane has been running for zero — so a live counter measures
    from the frame's arrival and `at_ms` orders the events.
    """

    name: str
    phase: Literal["start", "end"]
    key: str
    at_ms: int
    #: null on a `start` — nothing has been measured yet — and the settled duration on an `end`.
    ms: int | None = None
    status: str = "ran"
    detail: str | None = None
    #: The stage's bounded preview (`StageTimingOut.preview`), on `end` frames only — a
    #: `start` has nothing to preview yet, and the same key's entry in the `stages` that
    #: arrive with `done` carries the same object, because both are read off one recorder.
    preview: dict | None = None


class EpisodeSummaryOut(BaseModel):
    """One generated L2 episode description actually shown to the answer model."""

    source_id: str
    block_start: int
    block_end: int
    text: str
    score: float
    source_title: str
    source_occurred_on: str
    section_path: list[str]
    # Mechanical truth labels keep a generic client from presenting generated compression
    # as source text, even if it ignores the field name or surrounding UI copy.
    derived: Literal[True] = True
    verbatim: Literal[False] = False


class RecallAnswerOut(BaseModel):
    """fast/deep recall result — an answer over claims, L2 summaries and body windows."""

    mode: str
    answer: str
    # Citation-free semantic answer for automation and evaluation. `answer` remains the
    # cited rendering used by interactive clients.
    answer_text: str
    as_of: str
    used_claims: list[UsedClaimOut]
    # fast only: generated L2 episode descriptions used as dense context. These are
    # source-addressed but explicitly not verbatim excerpts.
    used_episode_summaries: list[EpisodeSummaryOut] = Field(default_factory=list)
    # fast only: routed component lookups (core recall/paths.py). Which paths the routing
    # turn chose, with arguments, and why it contributed nothing when it did not.
    used_component_evidence: list[ComponentEvidenceOut] = Field(default_factory=list)
    # Per-stage wall-clock for this answer, in each lane's own vocabulary (see
    # StageTimingOut): fast's fixed stage list, or deep's agentic turn/tool interleaving.
    stages: list[StageTimingOut] = Field(default_factory=list)
    route_offered: list[str] = Field(default_factory=list)
    route_chosen: list[str] = Field(default_factory=list)
    route_degraded: str | None = None
    # L1/L2 body windows fused into the answer — uncompiled content, drill-downable.
    used_windows: list[RecallHitOut] = []
    # deep only: the agentic search trace — one record per tool call, execution order.
    trail: list[dict[str, Any]] = []
    # {handle: real_source_id} for the query-local `sNN` citation handles in `answer` —
    # the UI reverse-binds each `[cite: sNN]` to its real source (fast lane).
    citation_handles: dict[str, str] = {}
    # Size of the knowledge base glance carried in the prompt; 0 when canonical was empty or
    # unreadable. The in-presence signal, without re-rendering the prompt to check.
    glance_chars: int = 0
    # Canonical documents read in full for this answer: fast's glance selection, deep's
    # read_document walk. Drill-downable provenance for the parts of the answer that came from
    # a whole document rather than a retrieved fragment.
    documents_read: list[str] = []
    # fast only: why the glance selection pass contributed nothing ("timeout"/"error"), or
    # null — which includes the normal case of it running and selecting nothing.
    glance_degraded: str | None = None
    # Fast context/answer telemetry. Degraded markers distinguish a normal empty selection
    # from a provider/schema failure that fell back to the historical path.
    evidence_strategy: str = "ranked"
    evidence_selection_degraded: str | None = None
    claim_candidates: int = 0
    episode_summary_candidates: int = 0
    window_candidates: int = 0
    model_selected_claims: int = 0
    model_selected_episode_summaries: int = 0
    model_selected_windows: int = 0
    # `select` only: how many component-lookup items the selector took from the pool it was
    # offered. 0 on the ranked path, where the component face is rendered rather than
    # selected from. Unlike the three counts above, the SIZE of that pool
    # (`FastAnswer.component_candidates`) is not echoed on the wire today.
    model_selected_component_items: int = 0
    answer_format: str = "text"
    answer_kind: str | None = None
    answer_format_degraded: str | None = None
    # The answering call's own evidence review, when the schema asked for one (the `all`
    # strategy under `structured`). Null everywhere else. It is model output about the
    # evidence, never evidence itself and never a substitute for a citation.
    deliberation: str | None = None
    # The frozen snapshot this answer was scoped to, or null for the live base.
    snapshot: SnapshotScopeOut | None = None
    # Query-local original-media delivery telemetry, kept generic so adding audio/video does
    # not change the public tool shape.
    included_original_modalities: list[Literal["image"]] = Field(default_factory=list)
    original_modality_counts: dict[str, int] = Field(default_factory=dict)
    token_usage: dict[str, int]


class RagRecallOut(BaseModel):
    """rag recall — the fused hit list, and what finding it cost.

    An OBJECT rather than the bare array this route used to return, for one reason: the hits
    alone cannot say where the seconds went, and every other lane reports that. `hits` is
    byte-for-byte the list that was the whole body before.
    """

    mode: Literal["rag"] = "rag"
    hits: list[RecallHitOut]
    #: `RAG_STAGE_ORDER`, complete — see `StageTimingOut`. A stage that did not run (an
    #: `embed` a caller supplied the vector for) is present and marked `skipped`.
    stages: list[StageTimingOut] = Field(default_factory=list)


def _recall_hit_out(h: Any) -> RecallHitOut:
    return RecallHitOut(
        source_id=str(h.source_id),
        block_start=h.block_start,
        block_end=h.block_end,
        text=h.text,
        paths=list(h.paths),
        score=h.score,
    )


def _used_claim_out(c: Any) -> UsedClaimOut:
    return UsedClaimOut(
        anchor=str(c.anchor),
        document_path=c.document_path,
        section_path=list(c.section_path),
        text=c.text,
        citations=[
            {
                "source_id": str(cit.source_id),
                "block_start": cit.block_start,
                "block_end": cit.block_end,
            }
            for cit in c.citations
        ],
        paths=list(c.paths),
        score=c.score,
        labels=list(getattr(c, "labels", ()) or ()),
    )


def _component_evidence_out(e: Any) -> ComponentEvidenceOut:
    return ComponentEvidenceOut(
        path=e.path,
        args=dict(e.args),
        claims=[_used_claim_out(c) for c in e.claims],
        windows=[_recall_hit_out(w) for w in e.windows],
        degraded=e.degraded,
        dropped=e.dropped,
        dropped_summary=[(group, count) for group, count in (e.dropped_summary or ())],
        already_shown=getattr(e, "already_shown", 0),
    )


def _stage_timing_out(stage: Any) -> StageTimingOut:
    return StageTimingOut(
        name=stage.name,
        ms=stage.ms,
        status=stage.status,
        detail=stage.detail,
        preview=getattr(stage, "preview", None),
    )


def _stage_event_out(event: Any) -> StageEventOut:
    return StageEventOut(
        name=event.name,
        phase=event.phase,
        key=event.key,
        at_ms=event.at_ms,
        ms=event.ms,
        status=event.status,
        detail=event.detail,
        preview=getattr(event, "preview", None),
    )


def _stored_stages_out(stored: Any) -> list[StageTimingOut]:
    """Stages read back from a persisted row (briefings) — dicts in the wire shape, not
    dataclasses. A row written before the column existed is an empty list and stays one:
    "not recorded" is a different fact from "took no time" and is never faked into zeros."""
    return [StageTimingOut(**dict(s)) for s in (stored or [])]


def _episode_summary_out(summary: Any) -> EpisodeSummaryOut:
    return EpisodeSummaryOut(
        source_id=str(summary.source_id),
        block_start=summary.block_start,
        block_end=summary.block_end,
        text=summary.text,
        score=summary.score,
        source_title=summary.source_title,
        source_occurred_on=summary.source_occurred_on,
        section_path=list(summary.section_path),
    )


class FetchIn(BaseModel):
    locator: dict[str, Any]


@router.post("/sources/conversation", response_model=IngestOut, deprecated=True)
async def post_conversation(
    user_id: str, body: ConversationIn, request: Request
) -> IngestOut:
    result = await ingest_conversation(
        _ctx(request),
        UserId(user_id),
        body.turns,
        title=body.title,
        meta=body.meta,
        origin=body.origin,
    )
    return IngestOut(
        source_id=str(result.source_id),
        intake_plan=result.intake_plan.model_dump(),
        deduplicated=result.deduplicated,
    )


@router.post("/sources/import", response_model=OfficialImportOut)
async def post_official_source(
    user_id: str, body: OfficialSourceIn, request: Request
) -> OfficialImportOut:
    """Import one meeting, document-library, IM or email v1 contract.

    Bundles expand at citable boundaries (note, conversation or mail thread), so the
    response may contain more than one stored source.
    """

    result = await ingest_source_contract(
        _ctx(request), UserId(user_id), body.root
    )
    return OfficialImportOut(
        contract_schema=result.contract_schema,
        sources=[
            IngestOut(
                source_id=str(item.source_id),
                intake_plan=item.intake_plan.model_dump(),
                deduplicated=item.deduplicated,
            )
            for item in result.sources
        ],
    )


@root_router.get("/users", response_model=list[str])
async def list_users(request: Request) -> list[str]:
    """Distinct user_ids with data — the UI user switcher's data source."""
    return await _ctx(request).store.list_users()


@router.get("/profile", response_model=UserProfile)
async def get_profile(user_id: str, request: Request) -> UserProfile:
    """The user's picture. Persisted (user-filled) picture wins; otherwise a
    named persona for known ids or a deterministic synthesis. UI reads display_name/
    avatar from here."""
    return await _ctx(request).user_info.get_profile(UserId(user_id))


class LocaleIn(BaseModel):
    city: str | None = None
    country: str | None = None
    timezone: str | None = None
    language: str | None = None


class PreferencesIn(BaseModel):
    response_language: str | None = None
    units: str | None = None
    privacy_level: str | None = None


class WorkspaceIn(BaseModel):
    operating_mode: str | None = None
    primary_stack: str | None = None
    automation_level: str | None = None
    active_since: str | None = None


class ProfileUpdateIn(BaseModel):
    """The editable subset of the user picture (onboarding form). Every field is
    optional: only the fields present in the body are merged onto the current picture
    (persisted or mock-synthesized); everything else is preserved."""

    display_name: str | None = None
    gender: str | None = None
    birth_year: int | None = None
    industry: str | None = None
    industry_other: str | None = None
    role: str | None = None
    role_other: str | None = None
    level: str | None = None
    locale: LocaleIn | None = None
    occupation: str | None = None
    bio: str | None = None
    interests: list[str] | None = None
    preferences: PreferencesIn | None = None
    workspace: WorkspaceIn | None = None


@router.put("/profile", response_model=UserProfile)
async def put_profile(
    user_id: str, body: ProfileUpdateIn, request: Request
) -> UserProfile:
    """Persist the user's onboarding-edited picture. Merges the provided fields
    onto the current picture (base = persisted picture if any, else the mock synthesis):
    fields absent from the body keep their base value; nested objects
    (locale/preferences/workspace) merge sub-field by sub-field. Validates
    industry/role/level against the enums,
    stamps source="user", upserts to PG, and returns the full profile."""
    ctx = _ctx(request)
    user = UserId(user_id)

    base = (await ctx.user_info.get_profile(user)).model_dump()
    patch = body.model_dump(exclude_unset=True)
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = {**base[key], **value}
        else:
            merged[key] = value

    # Forward-only timezone history. The subject's timezone is a compile input, and every
    # date already in canonical was normalized under whatever it was at the time. Those
    # dates are never rewritten (canonical is the non-rebuildable layer), so a move is
    # recorded here instead and the compile time frame states it. Server-maintained: the
    # request body has no `timezone_history` field to forge.
    base_locale = base.get("locale") or {}
    new_locale = merged.get("locale") or {}
    old_zone, new_zone = base_locale.get("timezone"), new_locale.get("timezone")
    if old_zone and new_zone and old_zone != new_zone:
        merged["locale"] = {
            **new_locale,
            "timezone_history": [
                *(base_locale.get("timezone_history") or []),
                {
                    "changed_at": _now(),
                    "from_zone": old_zone,
                    "to_zone": new_zone,
                },
            ],
        }

    invalid: list[str] = []
    if merged.get("industry") not in INDUSTRIES:
        invalid.append(f"industry must be one of {list(INDUSTRIES)}")
    if merged.get("role") not in ROLES:
        invalid.append(f"role must be one of {list(ROLES)}")
    if merged.get("level") not in LEVELS:
        invalid.append(f"level must be one of {list(LEVELS)}")
    if invalid:
        raise HTTPException(status_code=422, detail="; ".join(invalid))

    # The path id is the source of truth for identity; provenance is now user-filled.
    merged["user_id"] = str(user)
    merged["source"] = "user"
    # Avatar color is stable per user, while its letter is semantic display-name
    # state and must never drift after onboarding edits.
    merged["avatar"] = {
        **base["avatar"],
        "initial": _initial_of(str(merged.get("display_name") or "")),
    }
    profile = UserProfile.model_validate(merged)
    # mode="json": the profile now holds datetimes (locale.timezone_history[].changed_at) and
    # the store hands the dict straight to a jsonb parameter, which cannot serialize one.
    await ctx.store.upsert_user_profile(user, profile.model_dump(mode="json"))
    return profile


class ProfileGenerateIn(BaseModel):
    """AI-generated persona: one sentence → a full UserProfile draft. Not user-scoped —
    a brand-new picture has no user_id yet; the client may pin one it already typed."""

    sentence: str
    user_id: str | None = None


def _resolve_generated_id(explicit: str | None, draft_id: str | None) -> str:
    """The id an AI-generated picture lands on: the client's typed id wins, else the
    model's suggested slug, else a random `u-xxxxxx` — each only if URL/fs-safe."""
    for candidate in (explicit, draft_id):
        slug = (candidate or "").strip()
        if slug and _USER_ID_RE.match(slug):
            return slug
    return f"u-{secrets.token_hex(3)}"


def _initial_of(display_name: str) -> str:
    """The avatar tile letter: the first non-space character of the display name."""
    stripped = display_name.strip()
    return stripped[0] if stripped else "?"


@root_router.post("/profile/generate", response_model=UserProfile)
async def post_profile_generate(body: ProfileGenerateIn, request: Request) -> UserProfile:
    """Expand one sentence into a complete, self-consistent UserProfile via the configured model.

    The LLM fills only the SEMANTIC subset (ProfileDraft); the non-semantic scaffolding
    (avatar color, joined_at) comes from the deterministic mock base `_synthesize(id)`, so
    the model never invents it. The draft's enum-typed fields guarantee a valid picture.
    NOT persisted — the client reviews it in the create form and the existing PUT flow
    materializes it."""
    ctx = _ctx(request)
    model = ctx.get_chat_model("recall")
    draft = await synthesize_profile_draft(
        model,
        body.sentence,
        **llm_call_config(
            ctx,
            operation="profile.generate",
            user_id=body.user_id or "(new)",
        ),
    )

    resolved_id = _resolve_generated_id(body.user_id, draft.user_id)

    # Base = the deterministic mock picture for this id (avatar color and joined_at).
    # Overlay every semantic field the draft provides; recompute the avatar
    # initial from the draft name; keep the base avatar color.
    base = _synthesize(resolved_id).model_dump()
    merged: dict[str, Any] = dict(base)
    merged.update(
        {
            "user_id": resolved_id,
            "display_name": draft.display_name,
            "gender": draft.gender,
            "birth_year": draft.birth_year,
            "locale": draft.locale.model_dump(),
            "industry": draft.industry,
            "industry_other": draft.industry_other,
            "role": draft.role,
            "role_other": draft.role_other,
            "level": draft.level,
            "occupation": draft.occupation,
            "bio": draft.bio,
            "interests": list(draft.interests),
            "preferences": draft.preferences.model_dump(),
            "workspace": draft.workspace.model_dump(),
            "source": "ai",
        }
    )
    merged["avatar"] = {**base["avatar"], "initial": _initial_of(draft.display_name)}
    return UserProfile.model_validate(merged)


def _occurred_on(meta: dict[str, Any] | None) -> str | None:
    """`meta["occurred_on"]` as a plain day string, or None when the source has none."""
    value = str((meta or {}).get("occurred_on") or "").strip()
    return value or None


@router.get("/sources", response_model=SourcePageOut)
async def list_sources(
    user_id: str,
    request: Request,
    # The ceiling is a catalogue-crawl budget, not a page size: a reader that wants to
    # search and filter its whole inventory client-side pulls it in a handful of round
    # trips instead of sixty. The row shape is small and the page query is keyset.
    limit: int = Query(default=25, ge=1, le=500),
    cursor: str | None = None,
    query: str | None = Query(default=None, max_length=200),
    kind: str | None = Query(default=None, max_length=80),
) -> SourcePageOut:
    ctx = _ctx(request)
    user = UserId(user_id)
    normalized_query = query.strip() if query and query.strip() else None
    filters = {"query": normalized_query, "kind": kind}
    before: tuple[datetime, str] | None = None
    if cursor:
        try:
            position = decode_cursor(
                cursor,
                collection="sources",
                user_id=user_id,
                filters=filters,
            )
            before = (
                datetime.fromisoformat(position["created_at"]),
                position["id"],
            )
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    raws, total, has_more = await ctx.store.list_sources_page(
        user,
        limit=limit,
        before=before,
        query=normalized_query,
        kind=kind,
    )
    source_ids = [str(raw.source_id) for raw in raws]
    counts = await ctx.store.block_counts(user, source_ids)
    digested = await ctx.store.digested_map(user, source_ids)
    items = [
        SourceOut(
            source_id=str(r.source_id),
            kind=r.kind,
            origin=r.origin,
            source_class=r.source_class,
            title=r.title,
            created_at=r.created_at.isoformat(),
            occurred_on=_occurred_on(r.meta),
            intake_plan=r.intake_plan,
            block_count=counts.get(str(r.source_id), 0),
            digested_at=digested.get(str(r.source_id)),
        )
        for r in raws
    ]
    next_cursor = None
    if has_more and raws:
        last = raws[-1]
        next_cursor = encode_cursor(
            collection="sources",
            user_id=user_id,
            filters=filters,
            position={
                "created_at": last.created_at.isoformat(),
                "id": str(last.source_id),
            },
        )
    return SourcePageOut(
        items=items,
        page=PageMetaOut(limit=limit, total=total, next_cursor=next_cursor),
    )


@router.get("/sources/activity", response_model=ActivityCalendarOut)
async def get_source_activity(
    user_id: str,
    request: Request,
    offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> ActivityCalendarOut:
    days = await _ctx(request).store.source_activity(
        UserId(user_id), offset_minutes=offset_minutes
    )
    return ActivityCalendarOut(days=[ActivityDayOut(**day) for day in days])


@router.get("/summary", response_model=WorkspaceSummaryOut)
async def get_workspace_summary(
    user_id: str, request: Request
) -> WorkspaceSummaryOut:
    ctx = _ctx(request)
    user = UserId(user_id)
    counts = await ctx.store.workspace_counts(user)
    _, snapshot_total, _ = await ctx.canonical.snapshots_page(user, limit=1)
    return WorkspaceSummaryOut(
        **counts,
        snapshots=snapshot_total,
    )


@router.get("/sources/{source_id}", response_model=SourceDetailOut)
async def get_source(user_id: str, source_id: str, request: Request) -> SourceDetailOut:
    """Single source detail: meta + intake_plan + blocks + structure map (M2 UI)."""
    try:
        ns = await _ctx(request).store.get(UserId(user_id), SourceId(source_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raw = ns.raw
    return SourceDetailOut(
        source_id=str(raw.source_id),
        kind=raw.kind,
        origin=raw.origin,
        source_class=raw.source_class,
        title=raw.title,
        mime=raw.mime,
        created_at=raw.created_at.isoformat(),
        meta=raw.meta,
        intake_plan=raw.intake_plan,
        structure=ns.structure.model_dump(),
        blocks=[
            BlockOut(
                index=b.index,
                text=b.text,
                section_path=list(b.section_path),
                images=[
                    BlockImageOut(
                        image_id=image.image_id,
                        mime_type=image.mime_type,
                        sha256=image.sha256,
                        size_bytes=image.size_bytes,
                        derived=[
                            DerivedMediaTextOut(**derived.model_dump())
                            for derived in image.derived
                        ],
                        metadata=image.metadata,
                        url=(
                            f"/v1/users/{quote(user_id, safe='')}/sources/"
                            f"{quote(source_id, safe='')}/blocks/{b.index}/images/"
                            f"{quote(image.image_id, safe='')}"
                        ),
                    )
                    for image in b.images
                ],
            )
            for b in ns.blocks
        ],
    )


@router.get("/sources/{source_id}/blocks/{block_index}/images/{image_id}")
async def get_source_image(
    user_id: str,
    source_id: str,
    block_index: int,
    image_id: str,
    request: Request,
) -> Response:
    """Resolve a block-aligned image through the same tenant and citation address."""

    ctx = _ctx(request)
    user = UserId(user_id)
    try:
        source = await ctx.store.get(user, SourceId(source_id))
        block = next(item for item in source.blocks if item.index == block_index)
        image = next(item for item in block.images if item.image_id == image_id)
    except (KeyError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail="source image not found") from exc
    if ctx.media is None:
        raise HTTPException(status_code=503, detail="media store is not configured")
    data = await ctx.media.get(user, image.storage_key)
    if len(data) != image.size_bytes or hashlib.sha256(data).hexdigest() != image.sha256:
        raise HTTPException(status_code=500, detail="stored source image failed integrity check")
    return Response(
        content=data,
        media_type=image.mime_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"sha256:{image.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sources/{source_id}/fetch")
async def fetch_source(
    user_id: str, source_id: str, body: FetchIn, request: Request
) -> dict[str, str]:
    try:
        text = await _ctx(request).store.fetch(
            UserId(user_id), SourceId(source_id), body.locator
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"text": text}


async def _glance_inputs(ctx, user: UserId, at: SnapshotRef | None = None) -> dict:
    """The canonical layout inputs the recall lanes render their glance from.

    Three reads the answering side needs and never had: the documents at the answering
    snapshot (the shape), the composed skill (its declared families), and the raw packs (each
    family's one-line "what this collects"). Never fatal — the glance is context, so a failure
    to load it degrades to today's retrieval-only prompt rather than a 500.
    """
    try:
        documents = await ctx.canonical.list(user, at=at)
    except Exception:  # noqa: BLE001 — the glance is advisory context, never blocks recall
        return {}
    if not documents:
        return {}
    try:
        skill = await skill_for_user(ctx, user)
        packs = await packs_for_user(ctx, user)
    except Exception:  # noqa: BLE001 — families/blurbs are decoration on a real document list
        skill, packs = None, []
    return {"documents": documents, "skill": skill, "packs": packs}


@dataclass(frozen=True)
class ReadPlane:
    """Where one recall reads from — the whole of snapshot routing, in five fields.

    This is the entire read-path cost of snapshot support, and it is small because a snapshot
    is a frozen TENANT (kb_snapshots.py): `retrieval_user` swaps to that tenant and the L0/L1/
    L2/claim stack narrows by the per-user isolation it already enforced. Two things stay on
    the OWNER: canonical (git versions it, so `canonical_at` pins a ref in the owner's repo)
    and the profile (whose picture is being answered for does not freeze).
    """

    #: The tenant every L0/L1/L2/claim query runs against — owner, or the snapshot's tenant.
    retrieval_user: UserId
    #: The owner, always. Canonical + profile + skill reads use this.
    owner: UserId
    #: `at=` for canonical reads: the snapshot's pinned commit, or None = HEAD.
    canonical_at: SnapshotRef | None
    #: What the answering prompt states about the snapshot, or None for the live base.
    scope: SnapshotScope | None
    #: The registry row, when pinned — for the response echo and the trace metadata.
    snapshot: KbSnapshot | None

    @property
    def trace_ref(self) -> str | None:
        return self.snapshot.canonical_ref if self.snapshot else None


async def _resolve_plane(
    ctx: AppContext, owner: UserId, snapshot: str | None
) -> ReadPlane:
    """Resolve the requested snapshot (or HEAD) into the read plane a recall runs on.

    No snapshot requested → every field falls back to today's behavior exactly: the owner is
    the retrieval tenant, canonical reads HEAD, and no snapshot section is rendered.

    A named snapshot that does not resolve is an ERROR, not a fallback: quietly answering over
    the live base would present today's knowledge as history — the one outcome this feature
    exists to make impossible."""
    if not snapshot:
        return ReadPlane(
            retrieval_user=owner,
            owner=owner,
            canonical_at=None,
            scope=None,
            snapshot=None,
        )
    try:
        resolved = await kb_snapshots.resolve(ctx, owner, snapshot)
    except SnapshotNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SnapshotNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReadPlane(
        retrieval_user=resolved.tenant_id,
        owner=owner,
        canonical_at=resolved.canonical_at,
        scope=SnapshotScope(label=resolved.label, created_at=resolved.created_at),
        snapshot=resolved,
    )


def _snapshot_out(snapshot: KbSnapshot | None) -> SnapshotScopeOut | None:
    if snapshot is None:
        return None
    return SnapshotScopeOut(
        snapshot_id=snapshot.snapshot_id,
        label=snapshot.label,
        canonical_ref=snapshot.canonical_ref,
        created_at=snapshot.created_at.isoformat() if snapshot.created_at else None,
    )


async def _subject_zone(ctx, user: UserId) -> str:
    """The subject's IANA timezone for the fast lane's routing turn, resolved exactly as
    compile resolves it (provider → profile → the deployment default).

    A component path may take CALENDAR DAYS as arguments, and a calendar day only means
    anything in someone's zone; the routing model resolves "last quarter" against `as_of` in
    this one. Never fatal — an unreadable profile falls through to the deployment default,
    which is what the resolution chain does anyway."""
    profile = None
    try:
        profile = await ctx.user_info.get_profile(user)
    except Exception:  # noqa: BLE001 — advisory context, never blocks recall
        pass
    try:
        return time_context_for(
            user,
            profile,
            default_timezone=getattr(ctx.settings, "default_timezone", "UTC"),
        ).zone_name
    except Exception:  # noqa: BLE001 — a zone is context for one routing turn, not a gate
        return "UTC"


async def _render_profile(ctx, user: UserId) -> str | None:
    """Compact owner profile for the recall Human turn's top block: identity (helps the
    model resolve who/what a transcribed ask refers to) + the answer language. Never
    fatal — a lookup failure just drops the block (profile=None)."""
    try:
        p = await ctx.user_info.get_profile(user)
    except Exception:  # noqa: BLE001 — profile is advisory context, never blocks recall
        return None
    ind = p.industry_other if (p.industry == "other" and p.industry_other) else p.industry
    role = p.role_other if (p.role == "other" and p.role_other) else p.role
    lines = [prompt("recall.profile.name", value=p.display_name)]
    who = " / ".join(x for x in (ind, role, p.level) if x)
    if who:
        lines.append(prompt("recall.profile.industry_role", value=who))
    if p.occupation:
        lines.append(prompt("recall.profile.occupation", value=p.occupation))
    place = " · ".join(x for x in (p.locale.city, p.locale.country) if x)
    if place:
        lines.append(prompt("recall.profile.location", value=place))
    lines.append(
        prompt(
            "recall.profile.response_language",
            value=p.preferences.response_language,
        )
    )
    return "\n".join(lines)


def _recall_image_args(ctx: AppContext, body: RecallIn) -> dict[str, Any]:
    """Translate the generic tool field into today's image-specific core arguments."""

    if "image" not in body.include_original_modalities:
        return {"image_mode": "caption", "media": None}
    media = getattr(ctx, "media", None)
    if media is None:
        raise HTTPException(
            status_code=503,
            detail="original image recall was requested, but this deployment has no media store",
        )
    return {"image_mode": "native", "media": media}


def _original_modality_telemetry(answer: Any) -> dict[str, Any]:
    count = int(getattr(answer, "image_count", 0) or 0)
    native = getattr(answer, "image_mode", "caption") == "native"
    return {
        "included_original_modalities": ["image"] if native and count else [],
        "original_modality_counts": {"image": count} if native and count else {},
    }


# ------------------------------------------------ the answering lanes, once each
#
# Every lane below is reachable two ways — the plain POST that returns when it is done, and
# the SSE route that narrates it while it runs. The INPUTS a lane is given and the PAYLOAD it
# produces are written once here and used by both, so "the `done` frame is the same answer the
# non-stream route returns" is a structural fact rather than fifty lines that have to be kept
# in step by hand. What the two routes differ in is exactly what they should: the live sinks.


def _answering_preflight(ctx: AppContext, mode: str, body: RecallIn) -> None:
    """The checks both recall routes make before any work starts.

    Ordering matters for the streaming route: everything that can be a 4xx/5xx must be
    decided BEFORE the response starts, because once an SSE body is open the status line is
    already sent and a failure can only be narrated, not returned."""
    if mode not in ("rag", "fast", "deep"):
        raise HTTPException(status_code=400, detail=f"unknown mode {mode!r}")
    if mode != "fast" and (
        body.evidence_strategy is not None or body.answer_format is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="evidence_strategy and answer_format are available only in fast mode",
        )
    if mode == "rag" and body.include_original_modalities:
        raise HTTPException(
            status_code=400,
            detail=(
                "include_original_modalities is available only in fast/deep answering "
                "modes; rag returns text retrieval hits"
            ),
        )
    # rag reaches no model at all, so it is exactly as available as browsing is: a keyless
    # deployment must still be able to search, and must still be able to watch it run.
    if mode == "rag":
        return
    # A deployment may run keyless on purpose (browsing stays fully served); the answering
    # lanes are the one thing that cannot. Say so, instead of handing an empty model spec
    # to the model builder and 500ing on its TypeError.
    from ...wiring import usable_model_name

    required_roles = ("recall", "answer") if mode == "fast" else ("deep",)
    if any(not usable_model_name(ctx.settings, role) for role in required_roles):
        raise HTTPException(
            status_code=503,
            detail=(
                "recall needs a configured chat model — this deployment is running "
                "keyless (browsing only). Set OPENROUTER_API_KEY (or a "
                "PNEUMA_KNOWLEDGE_LLM_MODEL* spec) and restart."
            ),
        )


async def _fast_recall_kwargs(
    ctx: AppContext,
    body: RecallIn,
    plane: ReadPlane,
    *,
    user_id: str,
    as_of: datetime,
    snapshot_ref: str | None,
    glance_inputs: dict,
) -> dict[str, Any]:
    """Everything `fast_recall` is called with, minus the live sinks."""
    component_paths = bool(
        getattr(ctx.settings, "recall_component_paths", True)
    ) and bool(registered_components())
    return dict(
        as_of=as_of,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        content=ctx.store,
        **_recall_image_args(ctx, body),
        profile=await _render_profile(ctx, plane.owner),
        embeddings=ctx.embeddings,
        model=ctx.get_chat_model("recall"),
        answer_model=ctx.get_chat_model("answer"),
        scope=plane.scope,
        cap=ctx.settings.recall_claim_cap,
        claim_candidate_cap=ctx.settings.recall_claim_candidate_cap,
        window_cap=ctx.settings.recall_window_cap,
        window_candidate_cap=ctx.settings.recall_window_candidate_cap,
        episode_summary_cap=ctx.settings.recall_episode_summary_cap,
        evidence_strategy=(
            body.evidence_strategy or ctx.settings.recall_evidence_strategy
        ),
        all_context_chars=ctx.settings.recall_all_context_chars,
        selection_reasoning_effort=(
            ctx.settings.recall_selection_reasoning_effort or None
        ),
        answer_format=body.answer_format or ctx.settings.recall_answer_format,
        answer_style=body.answer_style or ctx.settings.recall_answer_style,
        plan_queries_cap=ctx.settings.recall_plan_queries,
        reranker=ctx.get_reranker(),
        rerank_candidates=ctx.settings.recall_rerank_candidates,
        reasoning_effort=ctx.settings.answer_reasoning_effort or None,
        # None = whatever the enabled components offer; () = the switch is off.
        fast_paths=None if component_paths else (),
        component_budget_chars=ctx.settings.recall_component_budget_chars,
        # Read only when a routing turn will actually happen: with no component enabled
        # the lane must cost nothing extra at all (not even a profile read), and `zone`
        # is consumed by that turn alone.
        zone=(await _subject_zone(ctx, plane.owner)) if component_paths else "UTC",
        **glance_inputs,
        **llm_call_config(
            ctx,
            operation="recall.fast",
            user_id=user_id,
            extra={
                "snapshot_ref": snapshot_ref,
                "kb_snapshot_id": plane.snapshot.snapshot_id if plane.snapshot else None,
            },
        ),
    )


def _fast_answer_out(fa: Any, *, as_of: datetime, plane: ReadPlane) -> RecallAnswerOut:
    return RecallAnswerOut(
        mode="fast",
        answer=fa.answer,
        answer_text=fa.answer_text,
        as_of=as_of.isoformat(),
        used_claims=[_used_claim_out(c) for c in fa.used_claims],
        used_episode_summaries=[
            _episode_summary_out(summary) for summary in fa.used_episode_summaries
        ],
        used_component_evidence=[
            _component_evidence_out(e)
            for e in getattr(fa, "used_component_evidence", ()) or ()
        ],
        route_offered=list(getattr(fa, "route_offered", ()) or ()),
        route_chosen=list(getattr(fa, "route_chosen", ()) or ()),
        route_degraded=getattr(fa, "route_degraded", None),
        stages=[_stage_timing_out(s) for s in getattr(fa, "stages", ()) or ()],
        used_windows=[_recall_hit_out(w) for w in fa.used_windows],
        citation_handles=fa.citation_handles,
        glance_chars=fa.glance_chars,
        documents_read=list(fa.expanded_documents),
        glance_degraded=fa.glance_degraded,
        evidence_strategy=fa.evidence_strategy,
        evidence_selection_degraded=fa.evidence_selection_degraded,
        claim_candidates=fa.claim_candidates,
        episode_summary_candidates=fa.episode_summary_candidates,
        window_candidates=fa.window_candidates,
        model_selected_claims=fa.model_selected_claims,
        model_selected_episode_summaries=fa.model_selected_episode_summaries,
        model_selected_windows=fa.model_selected_windows,
        model_selected_component_items=fa.model_selected_component_items,
        answer_format=fa.answer_format,
        answer_kind=fa.answer_kind,
        answer_format_degraded=fa.answer_format_degraded,
        deliberation=getattr(fa, "deliberation", None),
        snapshot=_snapshot_out(plane.snapshot),
        token_usage=fa.token_usage,
        **_original_modality_telemetry(fa),
    )


async def _deep_recall_kwargs(
    ctx: AppContext,
    body: RecallIn,
    plane: ReadPlane,
    *,
    user_id: str,
    as_of: datetime,
    snapshot_ref: str | None,
    glance_inputs: dict,
) -> dict[str, Any]:
    """Everything `deep_recall` is called with, minus the live sinks."""
    return dict(
        as_of=as_of,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        embeddings=ctx.embeddings,
        model=ctx.get_chat_model("deep"),
        content=ctx.store,
        **_recall_image_args(ctx, body),
        profile=await _render_profile(ctx, plane.owner),
        scope=plane.scope,
        answer_style=body.answer_style or ctx.settings.recall_answer_style,
        **glance_inputs,
        **llm_call_config(
            ctx,
            operation="recall.deep",
            user_id=user_id,
            extra={
                "snapshot_ref": snapshot_ref,
                "kb_snapshot_id": plane.snapshot.snapshot_id if plane.snapshot else None,
            },
        ),
    )


def _deep_answer_out(da: Any, *, as_of: datetime, plane: ReadPlane) -> RecallAnswerOut:
    return RecallAnswerOut(
        mode="deep",
        answer=da.answer,
        answer_text=strip_citations(da.answer),
        as_of=as_of.isoformat(),
        used_claims=[_used_claim_out(c) for c in da.used_claims],
        used_windows=[_recall_hit_out(w) for w in da.used_windows],
        stages=[_stage_timing_out(s) for s in getattr(da, "stages", ()) or ()],
        trail=list(da.trail),
        glance_chars=da.glance_chars,
        documents_read=list(da.read_documents),
        snapshot=_snapshot_out(plane.snapshot),
        token_usage=da.token_usage,
        **_original_modality_telemetry(da),
    )


def _sse_frame(kind: str, payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_response(events: asyncio.Queue, task: asyncio.Task) -> StreamingResponse:
    """Drain a producer's event queue onto the wire until it says `done` (or `error`).

    One generator for every stream route in this module: they differ in what they put on the
    queue, never in how it reaches the client. The `finally` is the part that matters — a
    client that walks away mid-answer must not leave the lane running forever on the loop."""

    async def stream():
        try:
            while True:
                kind, payload = await events.get()
                yield _sse_frame(kind, payload)
                if kind in ("done", "error"):
                    break
        finally:
            # Client disconnected mid-stream (or we broke out early): don't leak the task.
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _live_sinks(events: asyncio.Queue) -> dict[str, Any]:
    """The two live callbacks core takes, bound to one queue.

    CONTRACT: NEITHER MAY BLOCK. core calls them synchronously from inside the running lane —
    on THIS event loop, mid-await. Anything that blocks here (a socket write, a DB round trip,
    or `put` on a bounded queue that is full) stalls the whole loop: every other user's
    request, every WebSocket, the /healthz probe. `put_nowait` on an unbounded asyncio.Queue
    cannot block and cannot raise QueueFull, which is why the queue is unbounded on purpose.
    """
    return {
        "on_event": lambda event: events.put_nowait(
            ("stage", _stage_event_out(event).model_dump())
        ),
        "on_token": lambda text: events.put_nowait(("token", {"text": text})),
    }


async def _rag_out(
    ctx: AppContext, plane: ReadPlane, body: RecallIn, *, on_event=None
) -> RagRecallOut:
    """The rag lane, run and projected. ONE function behind both routes.

    The stream's `done` frame has to be the payload the plain POST returns, and the only way
    that cannot drift is for there to be nothing to drift: the plain route returns this, and
    the stream route puts this on the queue. `on_event` is the live sink — the same measure
    sites, so the diagram drawn while the lane runs and the `stages` that land with `done`
    are one measurement, not two."""
    timer = StageRecorder(RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN, on_event=on_event)
    hits = await rag_recall(
        plane.retrieval_user,
        body.query,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        embeddings=ctx.embeddings,
        limit=body.limit,
        stages=timer,
    )
    return RagRecallOut(
        hits=[_recall_hit_out(h) for h in hits],
        stages=[_stage_timing_out(st) for st in timer.emit()],
    )


@router.post("/recall")
async def recall(
    user_id: str, body: RecallIn, request: Request
) -> RagRecallOut | RecallAnswerOut:
    """rag → dual-path hit list with its breakdown; fast/deep → an answer over capped claims.

    `body.snapshot` pins the whole answer to a frozen snapshot (see `_read_plane`)."""
    ctx = _ctx(request)
    user = UserId(user_id)
    _answering_preflight(ctx, body.mode, body)
    if body.mode == "rag":
        return await _rag_out(ctx, await _resolve_plane(ctx, user, body.snapshot), body)

    plane = await _resolve_plane(ctx, user, body.snapshot)
    as_of = datetime.fromisoformat(body.as_of) if body.as_of else _now()
    snapshot_ref = (
        plane.trace_ref
        if plane.snapshot
        else (await _resolve_snapshot(ctx, user, None) or None)
    )
    glance_inputs = await _glance_inputs(ctx, plane.owner, plane.canonical_at)

    if body.mode == "fast":
        fa = await fast_recall(
            plane.retrieval_user,
            body.query,
            **await _fast_recall_kwargs(
                ctx,
                body,
                plane,
                user_id=user_id,
                as_of=as_of,
                snapshot_ref=snapshot_ref,
                glance_inputs=glance_inputs,
            ),
        )
        return _fast_answer_out(fa, as_of=as_of, plane=plane)

    da = await deep_recall(
        plane.retrieval_user,
        body.query,
        **await _deep_recall_kwargs(
            ctx,
            body,
            plane,
            user_id=user_id,
            as_of=as_of,
            snapshot_ref=snapshot_ref,
            glance_inputs=glance_inputs,
        ),
    )
    return _deep_answer_out(da, as_of=as_of, plane=plane)


async def _rag_stream(
    ctx: AppContext, plane: ReadPlane, body: RecallIn
) -> StreamingResponse:
    """The rag lane over SSE: `stage` frames, then `done` with the plain route's own payload.

    No `token` frames and no `step` frames — not omitted, ABSENT: there is no model writing
    an answer and no agentic loop taking steps, so `_live_sinks`' token half has nothing to
    bind to and is not passed."""
    events: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            out = await _rag_out(
                ctx,
                plane,
                body,
                on_event=lambda event: events.put_nowait(
                    ("stage", _stage_event_out(event).model_dump())
                ),
            )
            events.put_nowait(("done", out.model_dump()))
        except Exception as exc:  # noqa: BLE001 — surface any failure as a stream error event
            events.put_nowait(("error", {"detail": str(exc)}))

    return _sse_response(events, asyncio.create_task(produce()))


@router.post("/recall/stream")
async def recall_stream(user_id: str, body: RecallIn, request: Request) -> StreamingResponse:
    """rag, fast or deep recall as Server-Sent Events — the same result, narrated as it runs.

    Four event kinds, one vocabulary across the lanes — and a lane sends only the ones it
    has: rag reaches no model, so it sends `stage` and `done` and nothing else.

    - `stage` — one `StageEventOut` every time a stage BEGINS and every time it settles. This
      is what the route exists for: the non-streaming answer already reports what each stage
      cost, but it reports it at the one moment nobody is waiting any more.
    - `token` — the answer's text as the model writes it (`{"text": "…"}`, deltas to append).
    - `step` — deep only: one agentic tool call, complete with the result preview and its own
      measured `ms` (core stamps it on the trail record before appending, so a live trail
      shows a real duration rather than one timed from arrival gaps).
    - `done` — the full `RecallAnswerOut`, byte-for-byte the payload `POST /recall` returns
      for the same request. Both are built by the same projection, so they cannot drift.

    A failure mid-lane closes with an `error` event carrying the message. Everything that can
    be a status code — an unknown mode, a fast-only knob in deep, a keyless deployment — is
    decided BEFORE the response opens, because once the body is streaming the status line has
    already been sent and a 503 can only be narrated.
    """
    ctx = _ctx(request)
    _answering_preflight(ctx, body.mode, body)
    user = UserId(user_id)
    if body.mode == "rag":
        return await _rag_stream(ctx, await _resolve_plane(ctx, user, body.snapshot), body)
    as_of = datetime.fromisoformat(body.as_of) if body.as_of else _now()
    plane = await _resolve_plane(ctx, user, body.snapshot)
    snapshot_ref = (
        plane.trace_ref
        if plane.snapshot
        else (await _resolve_snapshot(ctx, user, None) or None)
    )
    glance_inputs = await _glance_inputs(ctx, plane.owner, plane.canonical_at)
    fast = body.mode == "fast"
    lane_kwargs = await (
        _fast_recall_kwargs if fast else _deep_recall_kwargs
    )(
        ctx,
        body,
        plane,
        user_id=user_id,
        as_of=as_of,
        snapshot_ref=snapshot_ref,
        glance_inputs=glance_inputs,
    )
    # Unbounded on purpose — see the non-blocking contract on `_live_sinks`.
    events: asyncio.Queue = asyncio.Queue()
    sinks = _live_sinks(events)

    async def produce() -> None:
        try:
            if fast:
                answer = _fast_answer_out(
                    await fast_recall(
                        plane.retrieval_user, body.query, **lane_kwargs, **sinks
                    ),
                    as_of=as_of,
                    plane=plane,
                )
            else:
                answer = _deep_answer_out(
                    await deep_recall(
                        plane.retrieval_user,
                        body.query,
                        # deep's third live face: the agentic trail, one record per tool call
                        # as it lands. Same non-blocking contract as the other two.
                        on_step=lambda step: events.put_nowait(("step", step)),
                        **lane_kwargs,
                        **sinks,
                    ),
                    as_of=as_of,
                    plane=plane,
                )
            events.put_nowait(("done", answer.model_dump()))
        except Exception as exc:  # noqa: BLE001 — surface any failure as a stream error event
            events.put_nowait(("error", {"detail": str(exc)}))

    # The recall runs as a sibling task on this loop (no worker thread): every port it
    # touches is async, so it yields to the loop on each await and the generator below
    # drains events as they land.
    return _sse_response(events, asyncio.create_task(produce()))


# ------------------------------------------------------------- document intake (M3b)


class DocumentPreviewIn(BaseModel):
    title: str
    text: str
    # Named processing intent (archetype key); the user-facing axis. Empty/null = auto.
    intake_archetype: str | None = None
    # Back-compat only (contract/novel still recognized on the auto path); no longer the
    # user-facing axis and the UI does not send it.
    declared_type: str | None = None  # contract | novel | note | other | null
    source_class: str | None = None


class SectionNodeOut(BaseModel):
    path: list[str]
    start_block: int
    end_block: int
    block_count: int


class DocumentPreviewOut(BaseModel):
    normalized: dict[str, Any]  # {section_tree, block_count, char_count}
    proposed_plan: dict[str, Any]
    # Which archetype the proposed plan maps to (None = a custom knob-pair).
    proposed_archetype: str | None = None


class DocumentIngestIn(DocumentPreviewIn):
    # user override of the two knobs (UI edited the proposed plan); None = accept proposal.
    plan_override: dict[str, Any] | None = None
    # Provenance the caller knows and the text does not carry (author, occurrence time,
    # source app, parent document). Persisted on the source and textualized into the
    # compile preamble; symmetric with ConversationIn.meta.
    meta: dict[str, Any] | None = None


@root_router.get("/intake/archetypes", response_model=list[IntakeArchetype])
async def list_intake_archetypes() -> list[IntakeArchetype]:
    """The intake archetype registry — the closed set of processing intents (core is the
    single source of truth; the UI fetches this rather than inlining a copy)."""
    return INTAKE_ARCHETYPES


@router.post("/sources/document/preview", response_model=DocumentPreviewOut)
async def post_document_preview(
    user_id: str, body: DocumentPreviewIn
) -> DocumentPreviewOut:
    """Normalize + propose an IntakePlan with NO side effects (§4: plan is a proposal)."""
    try:
        preview = preview_document(
            body.title,
            body.text,
            intake_archetype=body.intake_archetype or None,
            declared_type=body.declared_type,
            source_class=body.source_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DocumentPreviewOut(
        normalized={
            "section_tree": [
                SectionNodeOut(
                    path=s.path,
                    start_block=s.start_block,
                    end_block=s.end_block,
                    block_count=s.block_count,
                ).model_dump()
                for s in preview.section_tree
            ],
            "block_count": preview.block_count,
            "char_count": preview.char_count,
        },
        proposed_plan=preview.proposed_plan.model_dump(),
        proposed_archetype=preview.proposed_archetype,
    )


@router.post("/sources/document", response_model=IngestOut)
async def post_document(
    user_id: str, body: DocumentIngestIn, request: Request
) -> IngestOut:
    try:
        result = await ingest_document(
            _ctx(request),
            UserId(user_id),
            title=body.title,
            text=body.text,
            intake_archetype=body.intake_archetype or None,
            declared_type=body.declared_type,
            source_class=body.source_class,
            plan_override=body.plan_override,
            meta=body.meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IngestOut(
        source_id=str(result.source_id),
        intake_plan=result.intake_plan.model_dump(),
        deduplicated=result.deduplicated,
    )


# --------------------------------------------------------------- compile queue (M3b)


class JobOut(BaseModel):
    job_id: str
    kind: str
    status: str
    ok: bool | None
    detail: str | None
    snapshot_ref: str | None
    source_ids: list[str]
    created_at: str | None
    completed_at: str | None


class JobPageOut(BaseModel):
    items: list[JobOut]
    page: PageMetaOut


class HistoryCountsOut(BaseModel):
    patches: int
    jobs: int
    snapshots: int
    total: int


class HistoryItemOut(BaseModel):
    kind: str
    ref: str
    ts: str
    payload: dict[str, Any]


class HistoryPageOut(BaseModel):
    items: list[HistoryItemOut]
    page: PageMetaOut
    counts: HistoryCountsOut


class CompileOut(BaseModel):
    enqueued: list[str]
    source_ids: list[str]


@router.get("/jobs", response_model=JobPageOut)
async def list_jobs(
    user_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
    status: str | None = Query(default=None, max_length=80),
    kind: str | None = Query(default=None, max_length=80),
) -> JobPageOut:
    """One page of the job queue, newest first.

    `status` accepts the stored values (`queued`, `claimed`, `done`) plus the two halves of
    `done`: `succeeded` (`ok=true`) and `failed` (`ok=false`). "Failed" is not a stored status
    — a compile the gate rejected finishes `done` like any other job — so without those two
    names the one question an operator asks had no answer. `done` still means both halves.
    """
    filters = {"status": status, "kind": kind}
    before: tuple[datetime, str] | None = None
    if cursor:
        try:
            position = decode_cursor(
                cursor,
                collection="jobs",
                user_id=user_id,
                filters=filters,
            )
            before = (
                datetime.fromisoformat(position["created_at"]),
                position["id"],
            )
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows, total, has_more = await _ctx(request).store.list_jobs_page(
        UserId(user_id),
        limit=limit,
        before=before,
        status=status,
        kind=kind,
    )
    items = [
        JobOut(
            job_id=r["job_id"],
            kind=r["kind"],
            status=r["status"],
            ok=r["ok"],
            detail=r["detail"],
            snapshot_ref=r["snapshot_ref"],
            source_ids=[str(s) for s in (r["payload"] or {}).get("source_ids", [])],
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
            completed_at=r["completed_at"].isoformat() if r["completed_at"] else None,
        )
        for r in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            collection="jobs",
            user_id=user_id,
            filters=filters,
            position={
                "created_at": last["created_at"].isoformat(),
                "id": last["job_id"],
            },
        )
    return JobPageOut(
        items=items,
        page=PageMetaOut(limit=limit, total=total, next_cursor=next_cursor),
    )


@router.get("/history", response_model=HistoryPageOut)
async def list_history(
    user_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
    kind: Literal["patch", "job", "snapshot"] | None = None,
) -> HistoryPageOut:
    filters = {"kind": kind}
    before: tuple[datetime, str, str] | None = None
    if cursor:
        try:
            position = decode_cursor(
                cursor,
                collection="history",
                user_id=user_id,
                filters=filters,
            )
            before = (
                datetime.fromisoformat(position["ts"]),
                position["kind"],
                position["id"],
            )
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows, counts, has_more = await _ctx(request).store.list_history_page(
        UserId(user_id),
        limit=limit,
        before=before,
        kind=kind,
    )
    items = [
        HistoryItemOut(
            kind=row["kind"],
            ref=row["ref"],
            ts=row["ts"].isoformat(),
            payload=row["payload"],
        )
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            collection="history",
            user_id=user_id,
            filters=filters,
            position={
                "ts": last["ts"].isoformat(),
                "kind": last["kind"],
                "id": last["ref"],
            },
        )
    return HistoryPageOut(
        items=items,
        page=PageMetaOut(
            limit=limit,
            total=counts["total"],
            next_cursor=next_cursor,
        ),
        counts=HistoryCountsOut(**counts),
    )


@router.get("/history/activity", response_model=ActivityCalendarOut)
async def get_history_activity(
    user_id: str,
    request: Request,
    offset_minutes: int = Query(default=0, ge=-840, le=840),
    kind: Literal["patch", "job", "snapshot"] | None = None,
) -> ActivityCalendarOut:
    days = await _ctx(request).store.history_activity(
        UserId(user_id), offset_minutes=offset_minutes, kind=kind
    )
    return ActivityCalendarOut(days=[ActivityDayOut(**day) for day in days])


@router.post("/compile", response_model=CompileOut)
async def post_compile(user_id: str, request: Request) -> CompileOut:
    """Enqueue this user's undigested sources for compile (idempotent — a source with a
    treatment that is not yet digested is enqueued once)."""
    ctx = _ctx(request)
    user = UserId(user_id)
    assert_writable(user)  # compile writes canonical; a frozen snapshot has none of its own
    source_ids = await ctx.store.undigested_source_ids(user)
    enqueued: list[str] = []
    for sid in source_ids:
        job_id = await ctx.store.enqueue(user, "compile", {"source_ids": [sid]})
        enqueued.append(job_id)
    return CompileOut(enqueued=enqueued, source_ids=source_ids)


# ---------------------------------------------------- canonical read surface (M3b)


class SnapshotOut(BaseModel):
    ref: str
    label: str | None


class SnapshotPageOut(BaseModel):
    items: list[SnapshotOut]
    page: PageMetaOut


@router.get("/snapshots", response_model=SnapshotPageOut)
async def list_snapshots(
    user_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
) -> SnapshotPageOut:
    after_ref = None
    if cursor:
        try:
            position = decode_cursor(
                cursor,
                collection="snapshots",
                user_id=user_id,
                filters={},
            )
            after_ref = position["ref"]
            if not after_ref:
                raise ValueError("snapshot cursor ref must not be empty")
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        refs, total, has_more = await _ctx(request).canonical.snapshots_page(
            UserId(user_id),
            limit=limit,
            after_ref=after_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    next_cursor = None
    if has_more and refs:
        next_cursor = encode_cursor(
            collection="snapshots",
            user_id=user_id,
            filters={},
            position={
                "ref": refs[-1].ref,
            },
        )
    return SnapshotPageOut(
        items=[SnapshotOut(ref=r.ref, label=r.label) for r in refs],
        page=PageMetaOut(limit=limit, total=total, next_cursor=next_cursor),
    )


# ------------------------------------------- knowledge-base snapshots (frozen tenants)
#
# Distinct from `/snapshots` above, which pages the canonical GIT HISTORY — every commit,
# free, canonical-only, browse-only. A kb-snapshot is the whole base frozen: L0 rows, both
# retrieval indexes and the claim projection copied under a read-only tenant, so it can be
# ASKED, not just browsed. Two different objects, two different paths, no overloaded word
# (see kb_snapshots.py and the `kb_snapshots` table comment).


class KbSnapshotOut(BaseModel):
    snapshot_id: str
    label: str
    canonical_ref: str
    status: str  # creating | ready | failed
    # Post-copy scale {sources, blocks, claims, points}; empty while creating.
    counts: dict[str, int]
    created_at: str | None
    ready_at: str | None
    # Why a 'failed' snapshot failed; null otherwise.
    detail: str | None


class KbSnapshotCreateIn(BaseModel):
    # The human handle for this frozen state ("before the Q3 reorg"). Free text: the id is
    # what identifies a snapshot, the label is what a person recognizes.
    label: str


def _kb_snapshot_out(snapshot: KbSnapshot) -> KbSnapshotOut:
    return KbSnapshotOut(
        snapshot_id=snapshot.snapshot_id,
        label=snapshot.label,
        canonical_ref=snapshot.canonical_ref,
        status=snapshot.status,
        counts=snapshot.counts,
        created_at=snapshot.created_at.isoformat() if snapshot.created_at else None,
        ready_at=snapshot.ready_at.isoformat() if snapshot.ready_at else None,
        detail=snapshot.detail,
    )


@router.get("/kb-snapshots", response_model=list[KbSnapshotOut])
async def list_kb_snapshots(user_id: str, request: Request) -> list[KbSnapshotOut]:
    """This user's frozen knowledge-base snapshots, newest first, in every status.

    Unpaginated, and `creating`/`failed` rows are included: taking a snapshot is a deliberate
    low-frequency act, so the list is short, and hiding an in-progress or failed one would
    leave the user unable to see why their snapshot is not answerable."""
    return [
        _kb_snapshot_out(s)
        for s in await kb_snapshots.list_snapshots(_ctx(request), UserId(user_id))
    ]


@router.post("/kb-snapshots", response_model=KbSnapshotOut, status_code=202)
async def post_kb_snapshot(
    user_id: str, body: KbSnapshotCreateIn, request: Request
) -> KbSnapshotOut:
    """Freeze this user's knowledge base as it stands right now. 202 + status 'creating'.

    202, not 201: the row exists immediately but the copy pipeline (four stores) runs in the
    background, and the snapshot is not answerable until it reports `ready`. Poll the list.
    Only "now" can be frozen — see `kb_snapshots.create`."""
    ctx = _ctx(request)
    user = UserId(user_id)
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="label must not be empty")
    snapshot = await kb_snapshots.create(ctx, user, label)
    kb_snapshots.spawn_copy(ctx, user, snapshot)
    return _kb_snapshot_out(snapshot)


@router.delete("/kb-snapshots/{snapshot_id}")
async def delete_kb_snapshot(
    user_id: str, snapshot_id: str, request: Request
) -> dict[str, bool]:
    """Delete a snapshot: purge its tenant from all four stores, drop the registry row.

    The pinned canonical commit is NOT deleted — it is a commit in the owner's git history,
    which a snapshot deletion must never rewrite."""
    deleted = await kb_snapshots.delete(_ctx(request), UserId(user_id), snapshot_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"snapshot not found: {snapshot_id}"
        )
    return {"deleted": True}


@router.get("/dataset")
async def get_dataset(
    user_id: str,
    request: Request,
    at: str | None = None,
    audit: bool = True,
) -> dict[str, Any]:
    """Assemble canonical + PG audit into the M2 four-view dataset shape (dataset.py)."""
    return await build_dataset(_ctx(request), UserId(user_id), at=at, audit=audit)


# ------------------------------------------------------------------- briefings (M4)


class BriefingBuildIn(BaseModel):
    query: str | None = None
    source_ids: list[str] = []
    budget_chars: int = 24_000
    snapshot: str | None = None  # snapshot ref; null = current HEAD (frozen into briefing)


class BriefingOut(BaseModel):
    """A freshly built pack. `stages` is the BUILD's measured wall-clock — a fixed vocabulary
    (`retrieve` with its two lookups, `expand`, `pack`, `total`), so a half that did not run
    is present and marked `skipped` rather than missing. No model runs in a build: this is
    entirely retrieval, expansion and assembly time."""

    briefing_id: str
    snapshot_ref: str
    claims_count: int
    source_count: int
    char_count: int
    stages: list[StageTimingOut] = Field(default_factory=list)


class BriefingSummaryOut(BaseModel):
    briefing_id: str
    scope: dict[str, Any]
    snapshot_ref: str
    char_count: int
    created_at: str | None


class BriefingDetailOut(BaseModel):
    """One stored briefing read back whole — `text` is the literal system pack.

    `stages` is the build's breakdown as it was measured, persisted with the row: a briefing
    built before the column existed reads back as an empty list, which is "not recorded" and
    not "took no time" — a client shows nothing rather than a strip of zeros."""

    briefing_id: str
    snapshot_ref: str
    created_at: str | None
    char_count: int
    scope: dict[str, Any]
    text: str
    stages: list[StageTimingOut] = Field(default_factory=list)


class AskIn(BaseModel):
    question: str


class AskOut(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    verbatim_fetches: list[dict[str, Any]]
    # {handle: real_source_id} for the query-local `sNN` markers in `answer` (consumption
    # aliasing on) — the UI reverse-binds each `[cite: sNN]` to its real source.
    citation_handles: dict[str, str] = {}
    token_usage: dict[str, int]
    # The ask LOOP's per-step wall-clock, agentic-shaped like deep's: `turn:N`, `tool:<name>`
    # (the same call the matching `verbatim_fetches` record carries `ms` for), `finalize` when
    # the budget forced a closing call, `total` last. The pack is not inside that total — it
    # was built earlier, and its own breakdown rides `BriefingOut` / the detail endpoint.
    stages: list[StageTimingOut] = Field(default_factory=list)


async def _build_and_store_briefing(
    ctx: AppContext,
    user: UserId,
    body: BriefingBuildIn,
    *,
    on_event: Any = None,
) -> BriefingOut:
    """Build a pack, persist it, and project the result — the whole route, minus the route.

    Written once because both `/briefings` and `/briefings/stream` do exactly this and must
    produce exactly this: the streamed `done` frame is the same `BriefingOut` the plain POST
    returns, and the row is written BEFORE either says done, so a client that saw `done` can
    always ask for the briefing back."""
    resolved = await _resolve_snapshot(ctx, user, body.snapshot)
    snapshot_ref = SnapshotRef(ref=resolved) if resolved else SnapshotRef(ref="")
    at = SnapshotRef(ref=body.snapshot) if body.snapshot else None
    snapshot_docs = await ctx.canonical.list(user, at=at)

    scope = BriefingScope(
        query=body.query,
        source_ids=[SourceId(s) for s in body.source_ids],
        budget_chars=body.budget_chars,
    )
    # The glance's families/blurbs: same seam the fast and deep lanes use, minus the documents
    # (the briefing already loaded its own snapshot-pinned set above).
    layout = await _glance_inputs(ctx, user, at)
    briefing = await build_briefing(
        user,
        scope,
        snapshot=snapshot_ref,
        snapshot_docs=snapshot_docs,
        content=ctx.store,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        embeddings=ctx.embeddings,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        skill=layout.get("skill"),
        packs=layout.get("packs") or (),
        on_event=on_event,
    )
    briefing_id = uuid.uuid4().hex
    stages = [_stage_timing_out(s) for s in briefing.stages]
    await ctx.store.create_briefing(
        user,
        briefing_id,
        {
            "query": body.query,
            "source_ids": body.source_ids,
            "budget_chars": body.budget_chars,
        },
        resolved,
        briefing.system_prefix,
        # Stored in the wire shape, so reading it back is a parse and never a re-derivation:
        # the build happened once and cannot be re-measured after the fact.
        stages=[s.model_dump() for s in stages],
    )
    return BriefingOut(
        briefing_id=briefing_id,
        snapshot_ref=resolved,
        claims_count=briefing.claims_count,
        source_count=briefing.source_count,
        char_count=briefing.char_count,
        stages=stages,
    )


@router.post("/briefings", response_model=BriefingOut)
async def post_briefing(user_id: str, body: BriefingBuildIn, request: Request) -> BriefingOut:
    """Build a stable knowledge pack over a fixed snapshot and persist it (derived)."""
    return await _build_and_store_briefing(_ctx(request), UserId(user_id), body)


@router.post("/briefings/stream")
async def post_briefing_stream(
    user_id: str, body: BriefingBuildIn, request: Request
) -> StreamingResponse:
    """The same build, narrated: a `stage` event as each half of the build begins and ends,
    then `done` with the `BriefingOut` the plain POST would have returned.

    A build runs no model at all — it is retrieval, provenance expansion and assembly — which
    is exactly why watching it live is worth something: when a build takes nine seconds the
    whole question is which of those three it spent them in, and until now that answer only
    arrived once the waiting was over. The row is persisted before `done`, so nothing about
    the streamed build is less durable than the plain one."""
    ctx = _ctx(request)
    user = UserId(user_id)
    events: asyncio.Queue = asyncio.Queue()
    sinks = _live_sinks(events)

    async def produce() -> None:
        try:
            built = await _build_and_store_briefing(
                ctx, user, body, on_event=sinks["on_event"]
            )
            events.put_nowait(("done", built.model_dump()))
        except Exception as exc:  # noqa: BLE001 — surface any failure as a stream error event
            events.put_nowait(("error", {"detail": str(exc)}))

    return _sse_response(events, asyncio.create_task(produce()))


@router.get("/briefings", response_model=list[BriefingSummaryOut])
async def list_briefings(user_id: str, request: Request) -> list[BriefingSummaryOut]:
    rows = await _ctx(request).store.list_briefings(UserId(user_id))
    return [
        BriefingSummaryOut(
            briefing_id=r["briefing_id"],
            scope=r["scope"],
            snapshot_ref=r["snapshot_ref"],
            char_count=len(r["system_prefix"]),
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
        )
        for r in rows
    ]


@router.get("/briefings/{briefing_id}", response_model=BriefingDetailOut)
async def get_briefing(
    user_id: str, briefing_id: str, request: Request
) -> BriefingDetailOut:
    """Read one briefing back, text included — the pack the answers are grounded in.

    Same user-scoped read the ask route makes, so another user's briefing_id is simply not
    there: 404, never someone else's pack (I1).
    """
    row = await _ctx(request).store.get_briefing(UserId(user_id), briefing_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"briefing not found: {briefing_id}")
    created_at = row.get("created_at")
    return BriefingDetailOut(
        briefing_id=row["briefing_id"],
        snapshot_ref=row["snapshot_ref"],
        created_at=created_at.isoformat() if created_at else None,
        char_count=len(row["system_prefix"]),
        scope=row.get("scope") or {},
        text=row["system_prefix"],
        stages=_stored_stages_out(row.get("stages")),
    )


async def _ask_over_briefing(
    ctx: AppContext,
    user: UserId,
    briefing_id: str,
    row: dict,
    question: str,
    *,
    on_event: Any = None,
    on_token: Any = None,
) -> AskOut:
    """One question over one stored briefing — the lane both ask routes run.

    The live sinks are the only difference between them, which is what makes "the streamed
    `done` is the answer the plain POST returns" structural instead of a promise."""
    scope = row.get("scope") or {}
    source_ids = tuple(str(s) for s in (scope.get("source_ids") or []))
    briefing = Briefing(
        user_id=user,
        snapshot=SnapshotRef(ref=row["snapshot_ref"]),
        system_prefix=row["system_prefix"],
        tool_names=DEFAULT_TOOL_NAMES,
        source_ids=source_ids,
    )
    ans = await briefing_ask(
        briefing,
        question,
        as_of=_now(),
        model=ctx.get_chat_model("recall"),
        content=ctx.store,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        embeddings=ctx.embeddings,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        profile=await _render_profile(ctx, user),
        citation_alias=ctx.settings.briefing_citation_alias,
        on_event=on_event,
        on_token=on_token,
        **llm_call_config(
            ctx,
            operation="briefing.ask",
            user_id=str(user),
            extra={
                "snapshot_ref": row["snapshot_ref"],
                "briefing_id": briefing_id,
            },
        ),
    )
    return AskOut(
        answer=ans.answer,
        citations=[
            {
                "source_id": str(c.source_id),
                "block_start": c.block_start,
                "block_end": c.block_end,
            }
            for c in ans.citations
        ],
        verbatim_fetches=[dict(f) for f in ans.verbatim_fetches],
        citation_handles=ans.citation_handles,
        token_usage=ans.token_usage,
        stages=[_stage_timing_out(s) for s in getattr(ans, "stages", ()) or ()],
    )


async def _briefing_row(ctx: AppContext, user: UserId, briefing_id: str) -> dict:
    """The user-scoped read both ask routes make: another user's briefing_id is simply not
    there — 404, never someone else's pack (I1)."""
    row = await ctx.store.get_briefing(user, briefing_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"briefing not found: {briefing_id}")
    return row


@router.post("/briefings/{briefing_id}/ask", response_model=AskOut)
async def ask_briefing(
    user_id: str, briefing_id: str, body: AskIn, request: Request
) -> AskOut:
    """Ask over a stored briefing (as_of = server now, injected into the Human turn)."""
    ctx = _ctx(request)
    user = UserId(user_id)
    row = await _briefing_row(ctx, user, briefing_id)
    return await _ask_over_briefing(ctx, user, briefing_id, row, body.question)


@router.post("/briefings/{briefing_id}/ask/stream")
async def ask_briefing_stream(
    user_id: str, briefing_id: str, body: AskIn, request: Request
) -> StreamingResponse:
    """The same ask, narrated: `stage` events as each model turn and each tool call begins
    and ends, `token` events as the answer is written, then `done` with the `AskOut`.

    The 404 for an unknown (or another user's) briefing is resolved BEFORE the response
    opens: a missing pack is a status code, not a stream that opens successfully and then
    admits it has nothing to answer over."""
    ctx = _ctx(request)
    user = UserId(user_id)
    row = await _briefing_row(ctx, user, briefing_id)
    events: asyncio.Queue = asyncio.Queue()
    sinks = _live_sinks(events)

    async def produce() -> None:
        try:
            answered = await _ask_over_briefing(
                ctx, user, briefing_id, row, body.question, **sinks
            )
            events.put_nowait(("done", answered.model_dump()))
        except Exception as exc:  # noqa: BLE001 — surface any failure as a stream error event
            events.put_nowait(("error", {"detail": str(exc)}))

    return _sse_response(events, asyncio.create_task(produce()))


@router.delete("/briefings/{briefing_id}")
async def delete_briefing(
    user_id: str, briefing_id: str, request: Request
) -> dict[str, bool]:
    await _ctx(request).store.delete_briefing(UserId(user_id), briefing_id)
    return {"deleted": True}
