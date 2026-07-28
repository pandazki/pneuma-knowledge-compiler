"""SkillVersion loading + byte-stable system contract (I5)."""

from pneuma_knowledge_core.skill import SkillVersion, load_builtin_skill, render_system_contract


def test_load_builtin_skill_is_immutable_with_hash():
    skill = load_builtin_skill()
    assert skill.skill_id == "opc-developer-knowledge"
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
        skill.skill_id, skill.version, skill.instructions, skill.path_templates
    )
    # frozen model.
    try:
        skill.version = "v2"  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_contract_is_byte_stable():
    a = render_system_contract(load_builtin_skill())
    b = render_system_contract(load_builtin_skill())
    assert a == b


def test_contract_contains_mechanics_and_no_volatile_content():
    contract = render_system_contract(load_builtin_skill())
    # Write mechanics present.
    assert "edit_claim" in contract and "append_block" in contract
    assert "create_document" in contract and "finish_compile" in contract
    assert "[cite: <source_id> ¶<start>-<end>]" in contract
    # Path ownership templates present.
    assert "memory/people/{slug}.md" in contract
    # Skill instructions folded in.
    assert "长期可追溯个人记忆" in contract
    assert "一人公司" in contract
    assert "实验" in contract and "产品" in contract
    # I5: no timestamp/ISO date leaked into the byte-stable contract.
    assert "2026-" not in contract
    # No YAML dump of the skill object.
    assert "content_hash:" not in contract and "path_templates:" not in contract


# --- M5: skill version governance (v1/v2 coexistence, forward-only upgrade) ---------


def test_v1_and_v2_have_distinct_stable_content_hashes():
    v1 = load_builtin_skill("v1")
    v2 = load_builtin_skill("v2")
    assert v1.version == "v1" and v2.version == "v2"
    # A real evolution, not a copy: instructions differ, hashes differ.
    assert v1.instructions != v2.instructions
    assert v1.content_hash != v2.content_hash
    # Each hash is stable (recompute + reload agree — content-addressed identity).
    assert v1.content_hash == load_builtin_skill("v1").content_hash
    assert v2.content_hash == load_builtin_skill("v2").content_hash
    assert v2.content_hash == SkillVersion.compute_hash(
        v2.skill_id, v2.version, v2.instructions, v2.path_templates, v2.contract_rules
    )
    # Path ownership base is shared across versions (a v2 modeling change must not
    # orphan v1's anchors by moving the file layout).
    assert v1.path_templates == v2.path_templates


def test_v2_evolves_status_time_and_adds_strength_tiering():
    v2 = load_builtin_skill("v2")
    # §4 sharpened: relative time must be normalized to an absolute date.
    assert "归一为绝对日期" in v2.instructions
    # New section: commitment/relationship strength tiering that shapes projection.
    assert "强度分级" in v2.instructions
    assert "【强】" in v2.instructions and "【中】" in v2.instructions


def test_unknown_skill_version_rejected():
    try:
        load_builtin_skill("v99")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_v2_contract_adds_rules_and_is_byte_stable():
    c1 = render_system_contract(load_builtin_skill("v1"))
    c2a = render_system_contract(load_builtin_skill("v2"))
    c2b = render_system_contract(load_builtin_skill("v2"))
    # v2's contract carries the added presentation rules; v1's does not.
    assert "本版本附加呈现规则" in c2a
    assert "强度前缀标签" in c2a
    assert "本版本附加呈现规则" not in c1
    # Still byte-stable per version (I5): same version renders identically each call.
    assert c2a == c2b
    # v2 still carries the immutable write mechanics.
    assert "edit_claim" in c2a and "[cite: <source_id> ¶<start>-<end>]" in c2a
    # No timestamp leaked (I5).
    assert "2026-" not in c2a
