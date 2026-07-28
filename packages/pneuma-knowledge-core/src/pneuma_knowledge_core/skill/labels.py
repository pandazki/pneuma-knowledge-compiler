"""Claim labels: the skill-declared controlled vocabulary for承诺/关系强度前缀标签.

The compile contract (v2/v3 §5) asks承诺类与关系类 claim 用受控前缀标签`【强】/【中】/【弱】`
起头。That字面前缀 is machinery the projection layer should LIFT out of the prose into a
structured badge — but the *vocabulary* is the skill's to declare, not the frontend's to
hardcode. This module is that declaration surface: a skill version → the list of labels it
promises to produce, so the service can ship the词表 and the UI renders a generic mechanism.

Detection is MECHANICAL over the skill's content (contract rules + instructions), never a
`version == "..."` switch: the strength-prefix clause lives in v2's contract_rules and in
v3's §5 instructions body, and a composed per-user skill (version `v3+packs.<hash>`) folds
that body forward — so any skill whose content carries the clause lights up, including future
bases and composed variants, with no per-version table to maintain.

This is a pure declaration read off an existing SkillVersion — it touches neither the
SkillVersion model nor `content_hash` (invariant I5): the labels are derived, never stamped
into the version's identity.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .version import SkillVersion

# The clause that marks a skill as producing强度前缀标签. Present verbatim in v2's
# contract_rules AND in v2/v3's §5 instructions — matched as text so the condition is
# content-driven (composed `v3+packs.*` inherits the body) rather than version-string bound.
_STRENGTH_CLAUSE_MARKER = "强度前缀标签"


class ClaimLabel(BaseModel):
    """One declared claim-prefix label. Frozen: it is a stable vocabulary entry, and a
    label list rides read paths (skill panel + dataset meta) that must not mutate it."""

    model_config = ConfigDict(frozen=True)

    label: str  # the字面 prefix, e.g. "强" (WITHOUT the【】brackets)
    name: str  # human display name, e.g. "已确立"
    description: str  # tooltip semantics — one sentence, incl. the前向升降档 rule
    tier: Literal["solid", "outline", "muted"]  # presentation weight hint for the badge


# The three-tier strength vocabulary declared by §5. Order is强→中→弱 (descending
# certainty). Descriptions each name the前向升降档 semantics (证据变化时前向调整，不改写历史).
_STRENGTH_LABELS: tuple[ClaimLabel, ...] = (
    ClaimLabel(
        label="强",
        name="已确立",
        description=(
            "责任人、条件/时间明确，或双方已确认的关系与决定。"
            "随证据前向升降档，保留旧档不静默抹去。"
        ),
        tier="solid",
    ),
    ClaimLabel(
        label="中",
        name="进行中",
        description=(
            "方向清楚但缺一个关键槽位（时间待定 / 待书面确认 / 口头同意未落实）。"
            "关键槽位补齐后随证据前向升为已确立。"
        ),
        tier="outline",
    ),
    ClaimLabel(
        label="弱",
        name="仅提及",
        description=(
            "一次性想法、假设、他人转述或未接受的提议。"
            "获得支撑后随证据前向升档，拿不准时降一档而非升一档。"
        ),
        tier="muted",
    ),
)


def _declares_strength_labels(skill: SkillVersion) -> bool:
    """True when this skill's content carries the strength-prefix clause — mechanical, so
    v2 (clause in contract_rules), v3 (clause in §5 instructions), and any composed
    `v3+packs.*` (instructions folded forward) all match without a version table."""
    if any(_STRENGTH_CLAUSE_MARKER in rule for rule in skill.contract_rules):
        return True
    return _STRENGTH_CLAUSE_MARKER in skill.instructions


def claim_labels_for(skill: SkillVersion) -> list[ClaimLabel]:
    """The claim-prefix labels this skill version promises to emit.

    A skill that declares the强度前缀标签 clause → the three-tier强/中/弱 vocabulary; any
    other skill (e.g. v1, which has no §5) → an empty list. A fresh list per call so a
    caller can never mutate the module-level tuple's backing."""
    if _declares_strength_labels(skill):
        return list(_STRENGTH_LABELS)
    return []
