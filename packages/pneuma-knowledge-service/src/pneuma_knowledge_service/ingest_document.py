"""Document intake service flow (architecture.md §4, milestone M3b).

Two-step, because the IntakePlan is a proposal (§4): `preview_document` normalizes and
proposes with NO side effects (the UI shows the section tree + the two knobs, the user
may override); `ingest_document` then executes with the confirmed plan — L0/L1
unconditional, L2 by `semantic_indexing` (summary = embed only each section's heading +
first block), and enqueues a compile job carrying per-source `treatment` when
`canonical_treatment != none`.

The document adapter is the only type-aware layer (§4 discipline); everything below it
is the same closed execution path the conversation flow uses.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.intake import (
    IntakePlan,
    archetype_of,
    plan_for_archetype,
    propose_intake,
)
from pneuma_knowledge_core.domain.source import NormalizedSource, RawSource
from pneuma_knowledge_core.ingest.adapters import MarkdownDocumentAdapter, PlainDocumentInput

from .ingest import IngestResult
from .wiring import AppContext

DeclaredType = Literal["contract", "novel", "note", "other"]
SourceClass = Literal["workstream", "reference"]


@dataclass(frozen=True)
class SectionNode:
    path: list[str]
    start_block: int
    end_block: int
    block_count: int


@dataclass(frozen=True)
class DocumentPreview:
    section_tree: list[SectionNode]
    block_count: int
    char_count: int
    proposed_plan: IntakePlan
    # Which archetype the proposed plan corresponds to (None = a custom knob-pair).
    proposed_archetype: str | None


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _default_source_class(
    declared_type: str | None, source_class: str | None
) -> SourceClass:
    if source_class in ("workstream", "reference"):
        return source_class  # type: ignore[return-value]
    # A handwritten note is first-party workstream; uploaded files default to reference.
    if declared_type == "note":
        return "workstream"
    return "reference"


def _normalize(
    user_id: UserId,
    title: str,
    text: str,
    *,
    declared_type: str | None,
    source_class: SourceClass,
    source_id: SourceId,
    meta: dict[str, Any] | None = None,
) -> NormalizedSource:
    raw = RawSource(
        source_id=source_id,
        user_id=user_id,
        kind="document",
        source_class=source_class,
        title=title,
        mime="text/markdown",
        checksum=_checksum(text),
        created_at=datetime.now(timezone.utc),
        # Caller metadata (author, occurrence time, workspace, parent doc …) is preserved:
        # it is what the compile preamble textualizes into "这是 X 于 … 创建的一篇 …".
        # Without this passthrough a document source reached compile with provenance
        # stripped, so authorship and time could only be guessed from the prose.
        meta={**(meta or {}), **({"declared_type": declared_type} if declared_type else {})},
    )
    adapter = MarkdownDocumentAdapter()
    return adapter.normalize(PlainDocumentInput(raw=raw, text=text))


def _propose(
    normalized: NormalizedSource,
    *,
    declared_type: str | None,
    source_class: SourceClass,
) -> IntakePlan:
    char_count = sum(len(b.text) for b in normalized.blocks)
    return propose_intake("document", source_class, char_count, declared_type)


def _resolve_plan(
    normalized: NormalizedSource,
    *,
    declared_type: str | None,
    source_class: SourceClass,
    intake_archetype: str | None,
    plan_override: dict[str, Any] | None,
    confirm: bool,
) -> IntakePlan:
    """Resolve the IntakePlan by the intake precedence (§4: plan is a proposal):

    plan_override (raw knobs, advanced) > intake_archetype (named intent) >
    declared_type+size mechanical propose_intake (auto). The rationale reflects the path.
    `confirm=True` (the ingest path) marks a deliberately chosen plan user_confirmed.
    """
    if intake_archetype:
        base = plan_for_archetype(intake_archetype)  # ValueError on unknown key
    else:
        base = _propose(normalized, declared_type=declared_type, source_class=source_class)

    if plan_override:
        return IntakePlan(
            canonical_treatment=plan_override.get(
                "canonical_treatment", base.canonical_treatment
            ),
            semantic_indexing=plan_override.get(
                "semantic_indexing", base.semantic_indexing
            ),
            rationale=base.rationale,
            user_confirmed=True,
        )
    if confirm and intake_archetype:
        return base.model_copy(update={"user_confirmed": True})
    return base


def preview_document(
    title: str,
    text: str,
    *,
    declared_type: str | None = None,
    source_class: str | None = None,
    intake_archetype: str | None = None,
) -> DocumentPreview:
    """Normalize + propose an IntakePlan with no side effects (§4: plan is a proposal)."""
    cls = _default_source_class(declared_type, source_class)
    normalized = _normalize(
        UserId("u-preview"),
        title,
        text,
        declared_type=declared_type,
        source_class=cls,
        source_id=SourceId("preview"),
    )
    plan = _resolve_plan(
        normalized,
        declared_type=declared_type,
        source_class=cls,
        intake_archetype=intake_archetype,
        plan_override=None,
        confirm=False,
    )
    tree = [
        SectionNode(
            path=list(s.path),
            start_block=s.start_block,
            end_block=s.end_block,
            block_count=s.end_block - s.start_block + 1,
        )
        for s in normalized.structure.sections
    ]
    return DocumentPreview(
        section_tree=tree,
        block_count=len(normalized.blocks),
        char_count=sum(len(b.text) for b in normalized.blocks),
        proposed_plan=plan,
        proposed_archetype=archetype_of(plan),
    )


def _summary_chunks(source_id: SourceId, normalized: NormalizedSource) -> list:
    """Summary-level L2 material: one chunk per section = heading path + its first block
    (architecture.md §4 semantic=summary: 只 embed 标题+各节首块)."""
    by_index = {b.index: b.text for b in normalized.blocks}
    chunks = []
    from pneuma_knowledge_core.ingest.chunking import Chunk, join_blocks

    # Char span = the section's first block's range in the source-global joined string,
    # so each summary chunk still has a unique (char_start, char_end) point id even
    # though its rendered text is heading + first block (not a verbatim substring).
    _, ranges = join_blocks(normalized.blocks)
    for sec in normalized.structure.sections:
        head = " / ".join(sec.path)
        first = by_index.get(sec.start_block, "")
        text = f"{head}\n{first}".strip() if head else first
        if not text:
            continue
        char_lo, char_hi = ranges.get(sec.start_block, (0, 0))
        chunks.append(
            Chunk(
                source_id=source_id,
                block_start=sec.start_block,
                block_end=sec.start_block,
                text=text,
                char_start=char_lo,
                char_end=char_hi,
            )
        )
    return chunks


async def ingest_document(
    ctx: AppContext,
    user_id: UserId,
    *,
    title: str,
    text: str,
    declared_type: str | None = None,
    source_class: str | None = None,
    intake_archetype: str | None = None,
    plan_override: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> IngestResult:
    """Execute document intake with the confirmed plan (may be user-overridden).

    Plan precedence (§4): plan_override (raw knobs) > intake_archetype (named intent) >
    declared_type+size mechanical propose_intake (auto).
    """
    source_id = SourceId(uuid.uuid4().hex)
    cls = _default_source_class(declared_type, source_class)
    normalized = _normalize(
        user_id,
        title,
        text,
        declared_type=declared_type,
        source_class=cls,
        source_id=source_id,
        meta=meta,
    )

    plan = _resolve_plan(
        normalized,
        declared_type=declared_type,
        source_class=cls,
        intake_archetype=intake_archetype,
        plan_override=plan_override,
        confirm=True,
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
    # the HTTP request never touches Meili/Qdrant/the configured model. Enqueue an "index" job carrying just
    # the source_id; the worker re-reads the stored NormalizedSource + its intake_plan to run
    # L1 (unconditional) and L2 (by semantic_indexing). Enqueued BEFORE the compile job so
    # recall (L1/L2) drains first — claim_next orders by created_at (§5).
    await ctx.store.enqueue(user_id, "index", {"source_id": str(source_id)})

    # Compile job: only when the plan asks for canonical treatment. Payload carries the
    # per-source treatment so the worker renders the right instruction segment (§4).
    if plan.canonical_treatment != "none":
        await ctx.store.enqueue(
            user_id,
            "compile",
            {
                "source_ids": [str(source_id)],
                "treatments": {str(source_id): plan.canonical_treatment},
            },
        )

    return IngestResult(source_id, plan, deduplicated=False)
