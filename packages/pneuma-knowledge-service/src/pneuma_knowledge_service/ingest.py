"""Conversation intake service flow (architecture.md §4, milestone M1).

normalize → propose_intake → ContentStore.add → enqueue "index" job (L1/L2 done by the
worker, off the request) → enqueue "compile" job. Ingest is enqueue-only: the HTTP request
persists L0 and returns immediately; the background worker does the heavy indexing.
Dedup short-circuits synchronously: a content-identical re-post returns the existing
source_id and enqueues nothing (append-only).
"""

from __future__ import annotations

import hashlib
import uuid
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.intake import IntakePlan, propose_intake
from pneuma_knowledge_core.domain.source import ConversationTurn, RawSource, SourceOrigin
from pneuma_knowledge_core.domain.time_context import TimeContext, time_context_for
from pneuma_knowledge_core.ingest.adapters import CONTEXT_STREAM_MIME, PlainConversationInput
from pneuma_knowledge_core.ingest.source_types import first_party_type

from .wiring import AppContext


async def subject_time_context(
    ctx: AppContext, user_id: UserId, raw: RawSource | None = None
) -> TimeContext:
    """The knowledge subject's clock for an ingest boundary.

    Sectioning turns an instant into a calendar day, and that day has to be the subject's,
    so ingest needs the profile's timezone (or whatever a registered TimeZoneProvider says
    about this particular source). A profile lookup failure degrades to UTC — a timezone is
    context, never a hard dependency of accepting material.
    """
    profile = None
    try:
        profile = await ctx.user_info.get_profile(user_id)
    except Exception:  # noqa: BLE001 — no profile → UTC, never a failed ingest
        profile = None
    return time_context_for(user_id, profile, raw=raw)


@dataclass(frozen=True)
class IngestResult:
    source_id: SourceId
    intake_plan: IntakePlan
    deduplicated: bool


def _checksum(turns: list[ConversationTurn], origin: str) -> str:
    payload = json.dumps(
        {
            "origin": origin,
            "turns": [
                {
                    "speaker": t.speaker,
                    "text": t.text,
                    "at": t.at.isoformat() if t.at else None,
                    "role": t.role,
                    "speaker_id": t.speaker_id,
                }
                for t in turns
            ],
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def ingest_conversation(
    ctx: AppContext,
    user_id: UserId,
    turns: list[ConversationTurn],
    *,
    title: str,
    meta: dict[str, Any] | None = None,
    origin: SourceOrigin = "upload",
) -> IngestResult:
    # First-party context_stream carries diarized roles → route to the owner-aware adapter
    # (registered under the context_stream mime); a generic conversation uses the plain path.
    mime = CONTEXT_STREAM_MIME if origin == "context_stream" else "text/plain"
    source_id = SourceId(uuid.uuid4().hex)
    raw = RawSource(
        source_id=source_id,
        user_id=user_id,
        kind="conversation",
        source_class="workstream",
        origin=origin,
        title=title,
        mime=mime,
        checksum=_checksum(turns, origin),
        created_at=datetime.now(timezone.utc),
        meta=meta or {},
    )
    # First-party context_stream goes through its source-type plugin (load types the
    # diarization roles, format renders the owner/other blocks). `context_stream_render_roles
    # =False` disables the owner/other rendering (deep-heavy deployments): origin is still
    # recorded, but blocks are the plain verbatim form. Intake hints are identical either
    # way (kind=conversation), so the plain adapter supplies them.
    # Sections are cut by calendar day, so the subject's timezone decides which day each
    # turn belongs to — see domain/time_context.py. The adapter also stamps the derived
    # `meta["occurred_on"]` from it, unless the caller supplied one explicitly.
    time = await subject_time_context(ctx, user_id, raw)
    plain = ctx.registry.find("conversation")  # (conversation, None) → PlainConversationAdapter
    fp = first_party_type(origin)
    if fp is not None and ctx.settings.context_stream_render_roles:
        normalized = fp.format(raw, fp.load(turns), time=time)
    else:
        normalized = plain.normalize(
            PlainConversationInput(raw=raw, turns=turns), time=time
        )

    hints = plain.default_intake_hints()
    char_count = sum(len(b.text) for b in normalized.blocks)
    plan = propose_intake(
        hints["kind"], hints["source_class"], char_count, hints.get("declared_type")
    )
    normalized.raw.intake_plan = plan.model_dump()

    stored_id = await ctx.store.add(user_id, normalized)
    if stored_id != source_id:
        existing = await ctx.store.get(user_id, stored_id)
        existing_plan = (
            IntakePlan.model_validate(existing.raw.intake_plan)
            if existing.raw.intake_plan
            else plan
        )
        return IngestResult(stored_id, existing_plan, deduplicated=True)

    # Indexing (L1 + L2) is deferred to the background worker — ingest is enqueue-only so
    # the HTTP request never touches Meili/Qdrant/the configured model. Enqueue an "index" job first (the
    # worker re-reads the stored NormalizedSource + its intake_plan to run L1/L2), then the
    # compile job — claim_next orders by created_at so recall (L1/L2) drains before compile.
    await ctx.store.enqueue(user_id, "index", {"source_id": str(source_id)})
    await ctx.store.enqueue(user_id, "compile", {"source_ids": [str(source_id)]})

    return IngestResult(source_id, plan, deduplicated=False)
