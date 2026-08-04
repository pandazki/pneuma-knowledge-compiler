"""claim_labels_for: the skill-declared claim-prefix vocabulary (labels.py).

The reference contract declares the strength-prefix clause → the three-tier vocabulary;
a skill without that clause declares nothing; a composed `v1+packs.*` inherits the body →
the same three. Detection is mechanical over content, so no per-version table needs
upkeep."""

from __future__ import annotations

from pneuma_knowledge_core.skill import ClaimLabel, claim_labels_for, load_skill_base
from pneuma_knowledge_core.skill.pack import SchemaPack, compose_skill


def test_clauseless_skill_declares_no_labels() -> None:
    base = load_skill_base("v1")
    from pneuma_knowledge_core.skill import SkillVersion

    bare = SkillVersion.from_parts(
        skill_id=base.skill_id,
        version="bare",
        instructions="# minimal\n\nNothing about strength here.",
        path_templates=base.path_templates,
    )
    assert claim_labels_for(bare) == []


def test_reference_declares_three_tier_strength_labels() -> None:
    labels = claim_labels_for(load_skill_base("v1"))
    assert [x.label for x in labels] == ["firm", "forming", "loose"]
    assert [x.tier for x in labels] == ["solid", "outline", "muted"]
    assert all(isinstance(x, ClaimLabel) for x in labels)
    # names + non-empty semantics ride each entry (drives the badge + tooltip).
    assert [x.name for x in labels] == ["Established", "In progress", "Mentioned only"]
    assert all(x.description.strip() for x in labels)
    # label is the bare prefix — no【】brackets bleed into the vocabulary.
    assert all("【" not in x.label and "】" not in x.label for x in labels)


def test_composed_reference_plus_packs_inherits_the_labels() -> None:
    base = load_skill_base("v1")
    pack = SchemaPack(
        pack_id="role-engineering",
        origin="matrix",
        extra_instructions="工程领域：架构决策、事故复盘值得长期归档。",
        extra_path_templates=["memory/decisions/{slug}.md"],
    )
    composed = compose_skill(base, [pack])
    assert composed.version.startswith("v1+packs.")
    assert [x.label for x in claim_labels_for(composed)] == ["firm", "forming", "loose"]


def test_labels_call_returns_a_fresh_list() -> None:
    skill = load_skill_base("v1")
    a = claim_labels_for(skill)
    a.append(a[0])
    # mutating one call's list must not leak into the next.
    assert len(claim_labels_for(skill)) == 3
