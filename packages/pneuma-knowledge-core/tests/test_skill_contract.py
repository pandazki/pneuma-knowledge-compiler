"""SkillVersion loading + byte-stable system contract (I5).

The bases these tests load are the reference `personal-knowledge` contracts the suite's
root `conftest.py` registers, standing in for an application's startup wiring — the
framework itself ships none, which `test_nothing_is_registered_by_default` pins directly.
"""

import pytest
from pneuma_knowledge_core.skill import (
    SkillVersion,
    load_skill_base,
    register_skill_base,
    reset_skill_bases,
    render_system_contract,
)


def test_load_skill_base_is_immutable_with_hash():
    skill = load_skill_base("v1")
    assert skill.skill_id == "personal-knowledge"
    assert skill.version == "v1"
    assert skill.instructions.strip()
    assert skill.path_templates == [
        "memory/profile.md",
        "memory/people/{slug}.md",
        "work/products/{slug}.md",
        "work/experiments/{slug}.md",
        "work/operations/{slug}.md",
        "memory/topics/{slug}.md",
        "materials/{slug}.md",
    ]
    assert skill.content_hash == SkillVersion.compute_hash(
        skill.skill_id,
        skill.version,
        skill.instructions,
        skill.path_templates,
        skill.contract_rules,
    )
    # frozen model.
    try:
        skill.version = "v2"  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_contract_is_byte_stable():
    a = render_system_contract(load_skill_base("v1"))
    b = render_system_contract(load_skill_base("v1"))
    assert a == b


def test_contract_contains_mechanics_and_no_volatile_content():
    contract = render_system_contract(load_skill_base("v1"))
    # Write mechanics present.
    assert "edit_claim" in contract and "append_block" in contract
    assert "create_document" in contract and "finish_compile" in contract
    assert "[cite: <source_id> ¶<start>-<end>]" in contract
    # Path ownership templates present.
    assert "memory/people/{slug}.md" in contract
    # Skill instructions folded in.
    assert "long-term, traceable knowledge" in contract
    assert "one-person company" not in contract
    assert "experiment" in contract and "product" in contract
    # I5 is byte-stability, asserted in test_contract_is_byte_stable; the contract body
    # may legitimately contain dates inside its own worked examples (stable bytes).
    # No YAML dump of the skill object.
    assert "content_hash:" not in contract and "path_templates:" not in contract


# --- M5: skill version governance (content-addressed identity, forward-only upgrade) --


def test_version_identity_is_content_addressed():
    v1 = load_skill_base("v1")
    assert v1.version == "v1"
    variant = SkillVersion.from_parts(
        skill_id=v1.skill_id,
        version="v1-local",
        instructions=v1.instructions + "\n\nAn extra clause.",
        path_templates=v1.path_templates,
        contract_rules=v1.contract_rules,
    )
    # A real evolution, not a copy: instructions differ, hashes differ.
    assert variant.content_hash != v1.content_hash
    # Each hash is stable (recompute + reload agree — content-addressed identity).
    assert v1.content_hash == load_skill_base("v1").content_hash
    assert variant.content_hash == SkillVersion.compute_hash(
        variant.skill_id,
        variant.version,
        variant.instructions,
        variant.path_templates,
        variant.contract_rules,
    )


def test_reference_contract_carries_time_and_strength_tiering():
    v1 = load_skill_base("v1")
    # Relative time must be normalized to an absolute date.
    assert "normalized to an absolute date" in v1.instructions
    # Commitment/relationship strength tiering that shapes projection.
    assert "strength tiering" in v1.instructions
    assert "【firm】" in v1.instructions and "【forming】" in v1.instructions


def test_unknown_skill_version_rejected():
    with pytest.raises(LookupError):
        load_skill_base("v99")


# --- the framework ships no domain contract ------------------------------------------


def test_nothing_is_registered_by_default():
    """An unwired process has no contract at all — not even a "neutral" one.

    `load_skill_base()` used to default to a packaged personal-knowledge body, so a caller
    who never chose still got one, and it looked like it had been chosen. Whatever the
    harness registered is dropped here first, so this asserts the framework's own state.
    """
    reset_skill_bases()
    with pytest.raises(LookupError):
        load_skill_base("v1")
    with pytest.raises(LookupError):
        load_skill_base("v3")


def test_missing_registration_names_the_doc_and_the_reference_contracts():
    """The failure has to be actionable: a bare "not found" leaves a caller nowhere."""
    reset_skill_bases()
    with pytest.raises(LookupError) as excinfo:
        load_skill_base("")
    message = str(excinfo.value)
    assert "register_skill_base" in message
    assert "settings.user_schema_base_version" in message
    assert "docs/guides/compile-contract.md" in message
    assert "packages/pneuma-knowledge-strategies/" in message


def test_registered_versions_are_listed_in_the_failure():
    reset_skill_bases()
    register_skill_base(
        "mine-v1",
        SkillVersion.from_parts(
            skill_id="mine",
            version="mine-v1",
            instructions="body",
            path_templates=["notes/{slug}.md"],
        ),
    )
    with pytest.raises(LookupError) as excinfo:
        load_skill_base("v3")
    assert "registered versions: mine-v1" in str(excinfo.value)


def test_from_parts_computes_the_same_hash_as_the_hand_rolled_call():
    """`from_parts` is the provenance-safe spelling; it must not be a different hash."""
    parts = dict(
        skill_id="mine",
        version="x1",
        instructions="body\n",
        path_templates=["notes/{slug}.md", "people/{slug}.md"],
        contract_rules=("a literal clause",),
    )
    built = SkillVersion.from_parts(**parts)  # type: ignore[arg-type]
    assert built.content_hash == SkillVersion.compute_hash(
        "mine", "x1", "body\n", ["notes/{slug}.md", "people/{slug}.md"], ("a literal clause",)
    )
    assert built.contract_rules == ("a literal clause",)


def test_contract_rules_render_and_are_byte_stable():
    with_rules = load_skill_base("v1")
    bare = SkillVersion.from_parts(
        skill_id=with_rules.skill_id,
        version="bare",
        instructions=with_rules.instructions,
        path_templates=with_rules.path_templates,
    )
    c1 = render_system_contract(bare)
    c2a = render_system_contract(with_rules)
    c2b = render_system_contract(with_rules)
    # The rule-carrying contract renders the added presentation rules; the bare one does not.
    assert "extra presentation rules of this version" in c2a
    assert "strength prefix label" in c2a
    assert "extra presentation rules of this version" not in c1
    # Still byte-stable (I5): the same skill renders identically each call.
    assert c2a == c2b
    # The immutable write mechanics ride along.
    assert "edit_claim" in c2a and "[cite: <source_id> ¶<start>-<end>]" in c2a
