"""IntakePolicy: NormalizedSource shape → IntakePlan (two knobs).

architecture.md §4: the plan governs only L2/L3 (canonical_treatment,
semantic_indexing); L0/L1 are unconditional invariants (I3) and never appear in
the vocabulary. The v1 decision is purely mechanical — declared adapter default + volume
thresholds. No LLM classifier (discipline 1: mechanism over persuasion); that is
deferred until real misclassification samples exist.

The plan is a proposal: UI previews it, the user may override, the choice is
audited (`user_confirmed`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .source import SourceKind

CanonicalTreatment = Literal["full", "distill", "card", "none"]
SemanticIndexing = Literal["full", "summary", "none"]

# Tunable policy constants — the closed vocabulary's only numeric knob.
BIG_DOCUMENT_CHARS = 80_000


class IntakePlan(BaseModel):
    canonical_treatment: CanonicalTreatment
    semantic_indexing: SemanticIndexing
    rationale: str
    user_confirmed: bool = False


# ------------------------------------------------------------ intake archetypes
#
# The user-facing intake axis is NOT content genre (an open, unenumerable set —
# papers/mail/minutes/manuals/CVs/receipts/slides…) but *processing intent*: a named preset of
# the two knobs (canonical_treatment × semantic_indexing). Genre demotes to mere
# `examples` text under each archetype. This registry is the single source of
# truth — the API imports it, the UI fetches it via GET /v1/intake/archetypes.
# Do NOT inline a second copy anywhere.


class IntakeArchetype(BaseModel):
    key: str
    label: str
    summary: str  # what happens to the doc under this intent
    examples: str  # genre examples, muted helper text only
    canonical_treatment: CanonicalTreatment
    semantic_indexing: SemanticIndexing


# Ordered; the four knob-pairs are all distinct, so archetype_of is unambiguous.
INTAKE_ARCHETYPES: list[IntakeArchetype] = [
    IntakeArchetype(
        key="digest",
        label="Study and file",
        summary="compiled into the knowledge base in full",
        examples="handwritten notes, work products, short but important pieces",
        canonical_treatment="full",
        semantic_indexing="full",
    ),
    IntakeArchetype(
        key="distill",
        label="Distil key points",
        summary="key information enters canonical, the body stays external and searchable",
        examples="contracts, reports, specifications",
        canonical_treatment="distill",
        semantic_indexing="full",
    ),
    IntakeArchetype(
        key="archive",
        label="Catalogue only",
        summary="a card plus metadata only, the body remains reachable",
        examples="books, long-form material",
        canonical_treatment="card",
        semantic_indexing="summary",
    ),
    IntakeArchetype(
        key="searchable",
        label="Searchable only",
        summary="no compile, no semantic indexing, just baseline full-text search",
        examples="anything you only want stored and findable",
        canonical_treatment="none",
        semantic_indexing="none",
    ),
]

_ARCHETYPE_BY_KEY = {a.key: a for a in INTAKE_ARCHETYPES}
_ARCHETYPE_BY_KNOBS = {
    (a.canonical_treatment, a.semantic_indexing): a.key for a in INTAKE_ARCHETYPES
}


def plan_for_archetype(key: str) -> IntakePlan:
    """The IntakePlan for a named processing intent. Raises ValueError on unknown key."""
    archetype = _ARCHETYPE_BY_KEY.get(key)
    if archetype is None:
        raise ValueError(f"unknown intake archetype: {key!r}")
    return IntakePlan(
        canonical_treatment=archetype.canonical_treatment,
        semantic_indexing=archetype.semantic_indexing,
        rationale=f"processing intent \"{archetype.label}\": {archetype.summary}",
        user_confirmed=False,
    )


def archetype_of(plan: IntakePlan) -> str | None:
    """Reverse lookup by the (canonical_treatment, semantic_indexing) pair. Returns the
    matching archetype key, or None for a knob-pair that matches no archetype (e.g.
    distill/summary — a "custom" plan)."""
    return _ARCHETYPE_BY_KNOBS.get((plan.canonical_treatment, plan.semantic_indexing))


def propose_intake(
    kind: SourceKind,
    source_class: Literal["workstream", "reference"],
    char_count: int,
    declared_type: str | None,
) -> IntakePlan:
    """Mechanical v1 intake proposal. Every branch states its matrix basis."""
    # First-party conversation or handwritten note: everything matters, compile fully.
    if kind in {"meeting", "im", "email", "conversation"} or declared_type == "note":
        return IntakePlan(
            canonical_treatment="full",
            semantic_indexing="full",
            rationale=(
                "first-party workstream/note (meeting, IM, email or handwritten note): "
                "compiled in full into personal work knowledge, with full semantic indexing"
            ),
        )

    # Structured streams (calendar/notifications, future): distill facts periodically,
    # do not index raw flow.
    if kind == "structured":
        return IntakePlan(
            canonical_treatment="distill",
            semantic_indexing="summary",
            rationale=(
                "structured stream (matrix row: structured streams): distilled into facts "
                "periodically, the raw flow is not indexed, summary-level semantics"
            ),
        )

    # Documents.
    if kind in {"document_library", "document"}:
        # A declared novel is card/summary regardless of size (matrix row: long works):
        # even a short excerpt of a big-work is treated as a card + metadata only.
        if declared_type == "novel":
            return IntakePlan(
                canonical_treatment="card",
                semantic_indexing="summary",
                rationale=(
                    "declared novel (matrix row: long works): a card plus metadata only, "
                    "the body stays reachable via L0/L1, summary-level semantics"
                ),
            )
        # A declared contract is a distilled reference document (matrix row: important
        # instruments such as contracts).
        if declared_type == "contract":
            return IntakePlan(
                canonical_treatment="distill",
                semantic_indexing="full",
                rationale=(
                    "declared contract (matrix row: important instruments): key information "
                    "distilled into canonical, the body externalized as searchable material, "
                    "full semantic indexing"
                ),
            )
        if source_class == "reference":
            if char_count > BIG_DOCUMENT_CHARS:
                # Novel-scale reference: card + metadata only; body stays L0/L1 reachable.
                return IntakePlan(
                    canonical_treatment="card",
                    semantic_indexing="summary",
                    rationale=(
                        f"large reference document (>{BIG_DOCUMENT_CHARS} chars, "
                        "matrix row: long works): a card plus metadata only, the body stays "
                        "reachable via L0/L1"
                    ),
                )
            # Contract-scale reference: distill key info into canonical, keep body external.
            return IntakePlan(
                canonical_treatment="distill",
                semantic_indexing="full",
                rationale=(
                    "reference document (matrix row: important instruments): key information "
                    "distilled into canonical, the body externalized as searchable material, "
                    "full semantic indexing"
                ),
            )
        # Workstream document (first-party work product, not a note): main path.
        return IntakePlan(
            canonical_treatment="full",
            semantic_indexing="full",
            rationale=(
                "first-party workstream document: a main-path work product, full compile + "
                "full semantic indexing"
            ),
        )

    raise ValueError(f"unhandled intake shape: kind={kind!r} class={source_class!r}")
