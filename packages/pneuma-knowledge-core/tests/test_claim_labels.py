"""claim_labels_for: the skill-declared claim-prefix vocabulary (labels.py).

v1 has no §5 → no labels; v2/v3 declare the strength-prefix clause → the three-tier
强/中/弱 vocabulary; a composed `v3+packs.*` inherits the body → the same three. Detection
is mechanical over content, so no per-version table needs upkeep."""

from __future__ import annotations

from pneuma_knowledge_core.skill import ClaimLabel, claim_labels_for, load_builtin_skill
from pneuma_knowledge_core.skill.pack import SchemaPack, compose_skill


def test_v1_declares_no_labels() -> None:
    assert claim_labels_for(load_builtin_skill("v1")) == []


def test_v3_declares_three_tier_strength_labels() -> None:
    labels = claim_labels_for(load_builtin_skill("v3"))
    assert [x.label for x in labels] == ["强", "中", "弱"]
    assert [x.tier for x in labels] == ["solid", "outline", "muted"]
    assert all(isinstance(x, ClaimLabel) for x in labels)
    # names + non-empty semantics ride each entry (drives the badge + tooltip).
    assert [x.name for x in labels] == ["已确立", "进行中", "仅提及"]
    assert all(x.description.strip() for x in labels)
    # label is the bare prefix — no【】brackets bleed into the vocabulary.
    assert all("【" not in x.label and "】" not in x.label for x in labels)


def test_v2_also_declares_the_three_labels() -> None:
    # v2 carries the clause in contract_rules; the same vocabulary results.
    assert [x.label for x in claim_labels_for(load_builtin_skill("v2"))] == ["强", "中", "弱"]


def test_composed_v3_plus_packs_inherits_the_labels() -> None:
    base = load_builtin_skill("v3")
    pack = SchemaPack(
        pack_id="role-engineering",
        origin="matrix",
        extra_instructions="工程领域：架构决策、事故复盘值得长期归档。",
        extra_path_templates=["memory/decisions/{slug}.md"],
    )
    composed = compose_skill(base, [pack])
    assert composed.version.startswith("v3+packs.")
    assert [x.label for x in claim_labels_for(composed)] == ["强", "中", "弱"]


def test_labels_call_returns_a_fresh_list() -> None:
    skill = load_builtin_skill("v3")
    a = claim_labels_for(skill)
    a.append(a[0])
    # mutating one call's list must not leak into the next.
    assert len(claim_labels_for(skill)) == 3
