"""Claim labels: the skill-declared controlled vocabulary for commitment/relationship
strength prefix labels.

The compile contract (v2/v3 §5) asks commitment and relationship claims to open with a
controlled prefix label `【firm】/【forming】/【loose】`. That literal prefix is machinery the
projection layer should LIFT out of the prose into a structured badge — but the *vocabulary*
is the skill's to declare, not the frontend's to hardcode. This module is that declaration
surface: a skill version → the list of labels it promises to produce, so the service can
ship the vocabulary and the UI renders a generic mechanism.

Detection is MECHANICAL over the skill's content (contract rules + instructions), never a
`version == "..."` switch: the strength-prefix clause lives in v2/v3's contract_rules (as
the catalog key `contract.rule.strength_labels`) and in v2/v3's §5 instructions body, and a
composed per-user skill (version `v3+packs.<hash>`) folds that body forward — so any skill
whose content carries the clause lights up, including future bases and composed variants,
with no per-version table to maintain.

Both the marker phrase and the three labels resolve through the prompt catalog, so a
deployment that overrides the strength clause and registers its own skill body keeps
detection and the badge vocabulary in step with the prose the model actually saw.

This is a pure declaration read off an existing SkillVersion — it touches neither the
SkillVersion model nor `content_hash` (invariant I5): the labels are derived, never stamped
into the version's identity.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..prompts import prompt, resolve_or_verbatim
from .version import STRENGTH_LABEL_RULE, SkillVersion


class ClaimLabel(BaseModel):
    """One declared claim-prefix label. Frozen: it is a stable vocabulary entry, and a
    label list rides read paths (skill panel + dataset meta) that must not mutate it."""

    model_config = ConfigDict(frozen=True)

    label: str  # the literal prefix, e.g. "firm" (WITHOUT the 【】 brackets)
    name: str  # human display name, e.g. "Established"
    description: str  # tooltip semantics — one sentence, incl. the forward re-tiering rule
    tier: Literal["solid", "outline", "muted"]  # presentation weight hint for the badge


# The three-tier strength vocabulary declared by §5, strongest first (descending certainty).
# Each description names the forward re-tiering semantics (adjust forward as evidence
# changes, never rewrite history).
_STRENGTH_TIERS: tuple[tuple[str, Literal["solid", "outline", "muted"]], ...] = (
    ("strong", "solid"),
    ("medium", "outline"),
    ("weak", "muted"),
)


def _strength_labels() -> tuple[ClaimLabel, ...]:
    return tuple(
        ClaimLabel(
            label=prompt(f"skill.claim_label.{key}.label"),
            name=prompt(f"skill.claim_label.{key}.name"),
            description=prompt(f"skill.claim_label.{key}.description"),
            tier=tier,
        )
        for key, tier in _STRENGTH_TIERS
    )


def _declares_strength_labels(skill: SkillVersion) -> bool:
    """True when this skill's content carries the strength-prefix clause — mechanical, so
    v2/v3 (the clause key in contract_rules), v3 (the clause in §5 instructions), and any
    composed `v3+packs.*` (instructions folded forward) all match without a version table.

    A business-authored version that writes the clause as a literal rule instead of the
    catalog key still matches, because each rule is resolved before being scanned."""
    marker = prompt("skill.claim_label.clause_marker")
    for rule in skill.contract_rules:
        if rule == STRENGTH_LABEL_RULE or marker in resolve_or_verbatim(rule):
            return True
    return marker in skill.instructions


def claim_labels_for(skill: SkillVersion) -> list[ClaimLabel]:
    """The claim-prefix labels this skill version promises to emit.

    A skill that declares the strength-prefix clause → the three-tier vocabulary; any other
    skill (e.g. v1, which has no §5) → an empty list. A fresh list per call so a caller can
    never mutate the module-level backing, and so a startup-registered override is picked
    up."""
    if _declares_strength_labels(skill):
        return list(_strength_labels())
    return []
