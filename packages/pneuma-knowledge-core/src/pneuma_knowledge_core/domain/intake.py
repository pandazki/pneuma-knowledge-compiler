"""IntakePolicy: NormalizedSource shape → IntakePlan (two knobs).

architecture.md §4: the plan governs only L2/L3 (canonical_treatment,
semantic_indexing); L0/L1 are unconditional invariants (I3) and never appear in
the vocabulary. v1 判定 is purely mechanical — declared adapter default + volume
thresholds. No LLM classifier (discipline 1: mechanism over persuasion); that is
deferred until real misclassification samples exist.

The plan is a proposal: UI previews it, the user may override, the choice is
audited (`user_confirmed`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
# 论文/邮件/纪要/手册/简历/收据/幻灯…) but *processing intent*: a named preset of
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
        label="精读归档",
        summary="全量 compile 进知识库",
        examples="手写笔记、工作产物、重要短文",
        canonical_treatment="full",
        semantic_indexing="full",
    ),
    IntakeArchetype(
        key="distill",
        label="要点蒸馏",
        summary="关键信息进 canonical，正文外置可检索",
        examples="合同、报告、规格",
        canonical_treatment="distill",
        semantic_indexing="full",
    ),
    IntakeArchetype(
        key="archive",
        label="存目索引",
        summary="只留卡片+元信息，正文仍可达",
        examples="书籍、长篇资料",
        canonical_treatment="card",
        semantic_indexing="summary",
    ),
    IntakeArchetype(
        key="searchable",
        label="仅可检索",
        summary="不 compile、不做语义，仅保底全文检索",
        examples="任何只想存着能搜到的东西",
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
        rationale=f"处理意图「{archetype.label}」：{archetype.summary}",
        user_confirmed=False,
    )


def archetype_of(plan: IntakePlan) -> str | None:
    """Reverse lookup by the (canonical_treatment, semantic_indexing) pair. Returns the
    matching archetype key, or None for a knob-pair that matches no archetype (e.g.
    distill/summary — a "custom" plan)."""
    return _ARCHETYPE_BY_KNOBS.get((plan.canonical_treatment, plan.semantic_indexing))


def propose_intake(
    kind: Literal["conversation", "document", "structured"],
    source_class: Literal["workstream", "reference"],
    char_count: int,
    declared_type: str | None,
) -> IntakePlan:
    """Mechanical v1 intake proposal. Every branch states its matrix basis."""
    # First-party conversation or handwritten note: everything matters, compile fully.
    if kind == "conversation" or declared_type == "note":
        return IntakePlan(
            canonical_treatment="full",
            semantic_indexing="full",
            rationale=(
                "first-party conversation/note (matrix row 上下文流/手写 note): "
                "都重要，全 compile + 全语义索引"
            ),
        )

    # Structured streams (calendar/notifications, future): distill facts periodically,
    # do not index raw flow.
    if kind == "structured":
        return IntakePlan(
            canonical_treatment="distill",
            semantic_indexing="summary",
            rationale=(
                "structured stream (matrix row 结构化流): 周期蒸馏成事实，"
                "不索原始流水，摘要级语义"
            ),
        )

    # Documents.
    if kind == "document":
        # A declared novel is card/summary regardless of size (matrix row 小说等大部头):
        # even a short excerpt of a big-work is treated as a card + metadata only.
        if declared_type == "novel":
            return IntakePlan(
                canonical_treatment="card",
                semantic_indexing="summary",
                rationale=(
                    "declared novel (matrix row 小说等大部头): 只留卡片与元信息，"
                    "正文仍 L0/L1 可达，摘要级语义"
                ),
            )
        # A declared contract is a distilled reference document (matrix row 合同类重要文书).
        if declared_type == "contract":
            return IntakePlan(
                canonical_treatment="distill",
                semantic_indexing="full",
                rationale=(
                    "declared contract (matrix row 合同类重要文书): "
                    "关键信息蒸馏进 canonical，正文外置为可检索资料，全语义索引"
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
                        "matrix row 小说等大部头): 只留卡片与元信息，正文仍 L0/L1 可达"
                    ),
                )
            # Contract-scale reference: distill key info into canonical, keep body external.
            return IntakePlan(
                canonical_treatment="distill",
                semantic_indexing="full",
                rationale=(
                    "reference document (matrix row 合同类重要文书): "
                    "关键信息蒸馏进 canonical，正文外置为可检索资料，全语义索引"
                ),
            )
        # Workstream document (first-party work product, not a note): main path.
        return IntakePlan(
            canonical_treatment="full",
            semantic_indexing="full",
            rationale=(
                "first-party workstream document: 主路径工作产物，全 compile + 全语义索引"
            ),
        )

    raise ValueError(f"unhandled intake shape: kind={kind!r} class={source_class!r}")
