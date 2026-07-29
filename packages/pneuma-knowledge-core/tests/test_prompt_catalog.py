"""The prompt-overlay mechanism itself: resolution, validation, hashing, reset.

Every model-visible surface in the framework routes through `prompts.prompt`, so these
tests cover the seam rather than any one surface: an unknown key fails loud, an override
may not invent placeholders, the overlay hash is stable and order-independent, the compile
contract picks up an override and stays byte-stable, contract-rule keys resolve while a
literal clause passes through, and `register_skill_base` swaps the skill body.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.prompts import (
    catalog,
    default_catalog,
    override_prompt,
    override_prompts,
    prompt,
    prompt_overlay_hash,
    reset_prompt_overrides,
    resolve_or_verbatim,
    template_fields,
)
from pneuma_knowledge_core.skill import (
    SkillVersion,
    load_builtin_skill,
    register_skill_base,
    registered_skill_bases,
    render_system_contract,
    reset_skill_bases,
)
from pneuma_knowledge_core.skill.version import STRENGTH_LABEL_RULE


@pytest.fixture(autouse=True)
def _clean_registries():
    reset_prompt_overrides()
    reset_skill_bases()
    yield
    reset_prompt_overrides()
    reset_skill_bases()


# ------------------------------------------------------------------------- resolution


def test_unknown_key_raises_rather_than_emitting_nothing():
    """A typo must fail loud: a silently empty surface reaches the model as a gap in the
    contract, and nothing downstream would notice."""
    with pytest.raises(KeyError):
        prompt("compile.write_contract.typo")


def test_no_fields_returns_the_template_verbatim_so_literal_braces_are_safe():
    """The deep contract teaches a JSON locator shape; formatting it would explode."""
    text = prompt("recall.deep.contract_head")
    assert '{"blocks": [start, end]}' in text


def test_only_named_fields_are_substituted_and_other_braces_survive():
    """The write contract interpolates {owner}/{templates} while TEACHING `{slug}` in its
    own prose — a whole-template str.format would either raise or need brace escaping that
    an override author has to remember to reproduce."""
    rendered = prompt(
        "compile.write_contract", owner="OWNER-SECTION\n\n", templates="  - a/{slug}.md"
    )
    assert "OWNER-SECTION" in rendered
    assert "  - a/{slug}.md" in rendered
    assert "{owner}" not in rendered and "{templates}" not in rendered
    # the taught placeholder is still there, unformatted
    assert "`{slug}` is a stable ASCII" in rendered


def test_catalog_is_enumerable_and_covers_every_documented_prefix():
    keys = set(catalog())
    assert keys == set(default_catalog())
    for prefix in (
        "compile.",
        "gate.",
        "source.",
        "ingest.",
        "recall.",
        "persona.",
        "skill.",
        "evolve.",
        "contract.rule.",
    ):
        assert any(k.startswith(prefix) for k in keys), prefix


# ------------------------------------------------------------------------- validation


def test_override_of_unknown_key_is_rejected():
    """A silent no-op override is the worst outcome: framework wording keeps reaching the
    model while the deployment believes it does not."""
    with pytest.raises(ValueError, match="unknown prompt key"):
        override_prompt("gate.no_such_violation", "whatever")


def test_override_may_not_invent_placeholders_the_default_lacks():
    with pytest.raises(ValueError, match="placeholders the default does not declare"):
        override_prompt("gate.frontmatter_missing", "missing {key} of {document}")


def test_override_may_drop_a_field_the_default_declares():
    """A subset is legal — an override that does not want to render a field is fine."""
    override_prompt("gate.frontmatter_missing", "frontmatter incomplete")
    assert prompt("gate.frontmatter_missing", key="type") == "frontmatter incomplete"


def test_template_fields_reports_named_placeholders_only():
    assert template_fields("a {x} b {y} c {} d {\"k\": 1}") == frozenset({"x", "y"})


# ------------------------------------------------------------------------ overlay hash


def test_overlay_hash_is_none_without_overrides_and_order_independent_with_them():
    assert prompt_overlay_hash() is None
    override_prompts(
        {"gate.frontmatter_missing": "A {key}", "compile.rules_header": "B"}
    )
    first = prompt_overlay_hash()
    assert first is not None
    reset_prompt_overrides()
    override_prompts(
        {"compile.rules_header": "B", "gate.frontmatter_missing": "A {key}"}
    )
    assert prompt_overlay_hash() == first
    # a different overlay is a different hash (this is the audit axis)
    override_prompt("compile.rules_header", "C")
    assert prompt_overlay_hash() != first


def test_reset_restores_the_english_defaults():
    english = prompt("compile.rules_header")
    override_prompt("compile.rules_header", "## 本版本附加呈现规则")
    assert prompt("compile.rules_header") == "## 本版本附加呈现规则"
    reset_prompt_overrides()
    assert prompt("compile.rules_header") == english
    assert prompt_overlay_hash() is None


# --------------------------------------------------------------- resolve_or_verbatim


def test_resolve_or_verbatim_resolves_a_key_and_passes_a_literal_through():
    assert resolve_or_verbatim("contract.rule.citation_shape") == prompt(
        "contract.rule.citation_shape"
    )
    assert resolve_or_verbatim("a business-authored literal clause") == (
        "a business-authored literal clause"
    )


def test_contract_rules_hold_catalog_keys_and_render_resolved():
    """Mechanism C: the per-version clause is a key, so it is overridable — but the
    rendered contract must contain the PROSE, never the key."""
    v3 = load_builtin_skill("v3")
    assert STRENGTH_LABEL_RULE in v3.contract_rules
    contract = render_system_contract(v3)
    assert STRENGTH_LABEL_RULE not in contract
    assert prompt(STRENGTH_LABEL_RULE) in contract


def test_business_authored_literal_clause_still_renders_verbatim():
    skill = SkillVersion(
        skill_id="biz",
        version="x1",
        instructions="body",
        path_templates=["memory/topics/{slug}.md"],
        contract_rules=("Always cite the ticket id.",),
        content_hash="0" * 64,
    )
    assert "Always cite the ticket id." in render_system_contract(skill)


# ------------------------------------------------------- the contract, end to end


def test_override_reaches_the_rendered_contract_and_stays_byte_stable():
    """The acceptance shape of the whole task: a business registers one Chinese override at
    startup, the compile contract carries it, and two renders are byte-identical (I5)."""
    skill = load_builtin_skill("v3")
    before = render_system_contract(skill)
    override_prompt("compile.rules_header", "## 要可呈现 → 本版本附加呈现规则")
    after_a = render_system_contract(skill)
    after_b = render_system_contract(skill)
    assert "## 要可呈现 → 本版本附加呈现规则" in after_a
    assert after_a == after_b
    assert after_a != before
    reset_prompt_overrides()
    assert render_system_contract(skill) == before


def test_owner_section_and_field_labels_are_overridable_together():
    class _Owner:
        display_name = "Owner Name"
        occupation = "engineer"
        industry = "tech"
        role = "engineering"

    override_prompts(
        {
            "compile.owner_section": "# 二、为谁编译\n\n{lines}\n\n",
            "compile.owner_field.name": "- **姓名**：{value}",
        }
    )
    contract = render_system_contract(load_builtin_skill("v1"), owner=_Owner())
    assert "# 二、为谁编译" in contract
    assert "- **姓名**：Owner Name" in contract


# -------------------------------------------------------- mechanism B: skill bases


def test_register_skill_base_replaces_the_packaged_asset():
    packaged = load_builtin_skill("v3")
    mine = SkillVersion(
        skill_id=packaged.skill_id,
        version="v3",
        instructions="# 五、领域判断（业务全文版）\n\n强度前缀标签用【强】/【中】/【弱】。",
        path_templates=list(packaged.path_templates),
        contract_rules=packaged.contract_rules,
        content_hash=SkillVersion.compute_hash(
            packaged.skill_id,
            "v3",
            "# 五、领域判断（业务全文版）\n\n强度前缀标签用【强】/【中】/【弱】。",
            list(packaged.path_templates),
            packaged.contract_rules,
        ),
    )
    register_skill_base("v3", mine)
    loaded = load_builtin_skill("v3")
    assert loaded is mine
    assert "业务全文版" in render_system_contract(loaded)
    assert registered_skill_bases() == {"v3": mine}
    # other versions are untouched by a v3 registration
    assert load_builtin_skill("v1").version == "v1"
    assert "业务全文版" not in load_builtin_skill("v1").instructions
    reset_skill_bases()
    assert load_builtin_skill("v3").instructions == packaged.instructions


def test_registered_base_keeps_claim_labels_working_under_a_chinese_overlay():
    """Detection is content-driven, so a Chinese body + a Chinese clause marker still
    lights up the badge vocabulary — the UI mechanism must not depend on English."""
    from pneuma_knowledge_core.skill import claim_labels_for

    override_prompts(
        {
            "skill.claim_label.clause_marker": "强度前缀标签",
            "skill.claim_label.strong.label": "强",
            "skill.claim_label.medium.label": "中",
            "skill.claim_label.weak.label": "弱",
        }
    )
    skill = SkillVersion(
        skill_id="biz",
        version="zh1",
        instructions="承诺类 claim 用强度前缀标签起头。",
        path_templates=["memory/topics/{slug}.md"],
        contract_rules=(),
        content_hash="0" * 64,
    )
    assert [x.label for x in claim_labels_for(skill)] == ["强", "中", "弱"]


# -------------------------------------------------------------- trailer integration


def test_overlay_hash_rides_the_commit_trailer_only_when_something_is_overridden():
    from pneuma_knowledge_core.compile.runner import _with_skill_trailer

    skill = load_builtin_skill("v3")
    assert "Prompt-Overlay-Hash:" not in _with_skill_trailer("compile", skill)
    override_prompt("compile.rules_header", "## 覆盖")
    trailer = _with_skill_trailer("compile", skill)
    assert f"Prompt-Overlay-Hash: {prompt_overlay_hash()}" in trailer
