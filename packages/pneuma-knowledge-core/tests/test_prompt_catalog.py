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
    LEGACY_PROMPT_KEYS,
    catalog,
    default_catalog,
    override_prompt,
    override_prompts,
    prompt,
    prompt_overlay_hash,
    reset_prompt_overrides,
    resolve_or_verbatim,
    resolve_prompt_key,
    template_fields,
)
from pneuma_knowledge_core.skill import (
    SkillVersion,
    load_skill_base,
    register_skill_base,
    registered_skill_bases,
    render_system_contract,
    reset_skill_bases,
)
from pneuma_knowledge_core.skill.version import STRENGTH_LABEL_RULE
from pneuma_knowledge_strategies import list_strategies


def register_reference_skill_bases() -> dict[str, SkillVersion]:
    """The startup wiring an application does, spelled out because this module tests it.

    The suite's root conftest does the same thing for everyone else; here it is inline so
    the reset-then-register sequence these tests depend on is visible in one file.
    """
    bases = {
        s.version: SkillVersion.from_parts(
            skill_id=s.skill_id,
            version=s.version,
            instructions=s.read_text(),
            path_templates=s.path_templates,
            contract_rules=s.contract_rules,
        )
        for s in list_strategies("personal-knowledge")
    }
    for version, skill in bases.items():
        register_skill_base(version, skill)
    return bases


@pytest.fixture(autouse=True)
def _clean_registries():
    """Both registries back to a known state around every test in this module.

    The skill registry is emptied and then re-wired with the suite's reference bases,
    rather than merely emptied: nothing is built in any more, so an empty registry means
    `load_skill_base` raises and these tests would have no contract to render at all. The
    re-registration is what an application does at startup — and it also has to happen
    AFTER the reset, which is why this fixture owns both halves.
    """
    reset_prompt_overrides()
    reset_skill_bases()
    reference = register_reference_skill_bases()
    yield reference
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


# ------------------------------------------------------------------- renamed keys


def test_an_overlay_written_against_a_renamed_key_still_applies():
    """A deployment's `prompts/overlays.yaml` outlives a catalog rename.

    The key is the address a person wrote down, and `override_prompt` refuses an unknown
    one on purpose — so without the legacy map a rename would turn every overlay naming
    the old spelling into a startup failure in somebody else's repository.
    """
    override_prompts({"gate.archive_frozen": "this volume is closed."})
    assert prompt("gate.volume_closed") == "this volume is closed."
    # ...and it lands as ONE surface: nothing downstream ever sees the retired spelling.
    assert list(catalog())  # smoke: the catalog still resolves
    assert "gate.archive_frozen" not in catalog()


def test_every_legacy_key_names_a_surface_that_actually_exists_and_is_itself_retired():
    """A legacy entry pointing at nothing would be an override that silently does nothing —
    the exact failure the unknown-key rejection exists to prevent."""
    defaults = default_catalog()
    for old, new in LEGACY_PROMPT_KEYS.items():
        assert new in defaults, old
        assert old not in defaults, old
        assert resolve_prompt_key(old) == new


def test_a_live_key_is_never_translated_by_the_legacy_map():
    assert resolve_prompt_key("gate.volume_closed") == "gate.volume_closed"
    assert resolve_prompt_key("not.a.key.at.all") == "not.a.key.at.all"


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
    v1 = load_skill_base("v1")
    assert STRENGTH_LABEL_RULE in v1.contract_rules
    contract = render_system_contract(v1)
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
    skill = load_skill_base("v1")
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
    contract = render_system_contract(load_skill_base("v1"), owner=_Owner())
    assert "# 二、为谁编译" in contract
    assert "- **姓名**：Owner Name" in contract


# -------------------------------------------------------- mechanism B: skill bases


def test_register_skill_base_replaces_a_version_and_leaves_the_others_alone():
    reference = load_skill_base("v1")
    aux = SkillVersion.from_parts(
        skill_id=reference.skill_id,
        version="aux",
        instructions=reference.instructions,
        path_templates=reference.path_templates,
        contract_rules=reference.contract_rules,
    )
    register_skill_base("aux", aux)
    body = "# 五、领域判断（业务全文版）\n\n强度前缀标签用【强】/【中】/【弱】。"
    mine = SkillVersion.from_parts(
        skill_id=reference.skill_id,
        version="v1",
        instructions=body,
        path_templates=reference.path_templates,
        contract_rules=reference.contract_rules,
    )
    register_skill_base("v1", mine)
    loaded = load_skill_base("v1")
    assert loaded is mine
    assert "业务全文版" in render_system_contract(loaded)
    assert registered_skill_bases()["v1"] is mine
    # other versions are untouched by a v1 registration
    assert load_skill_base("aux") is aux
    assert "业务全文版" not in load_skill_base("aux").instructions
    # and there is nothing underneath: a reset leaves no packaged body to fall back to.
    reset_skill_bases()
    with pytest.raises(LookupError):
        load_skill_base("v1")


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

    skill = load_skill_base("v1")
    assert "Prompt-Overlay-Hash:" not in _with_skill_trailer("compile", skill)
    override_prompt("compile.rules_header", "## 覆盖")
    trailer = _with_skill_trailer("compile", skill)
    assert f"Prompt-Overlay-Hash: {prompt_overlay_hash()}" in trailer
