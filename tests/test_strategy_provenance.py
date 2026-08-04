"""The `Skill-Content-Hash` values the shipped reference contracts resolve to.

A canonical commit carries `Skill-Version` and `Skill-Content-Hash` trailers, and the hash
is computed from five inputs: `skill_id`, `version`, the contract body, `path_templates`,
`contract_rules`. These pins exist so a contract-text change can never happen silently:
editing a reference contract fails this test until the change is acknowledged here, in a
commit that says why.

Acknowledged lineage:

- 2026-08-03 (pre-release, no external tenants): the three-generation v1/v2/v3 catalog
  was collapsed into a single contract, republished as `v1`. Mechanism prose was
  stripped (the gate enforces it; restating it in the prompt is dead weight —
  docs/guides/compile-contract.md §4), first-class beginnings and obligation chains
  were added per the same guide. Different user types are served by ADDING strategies,
  not by stacking versions. Hashes of the retired generations, still valid for trailers
  written under them:
  v1 2b49f0d6a7cb83d25d832457833ad4436fada35a5a1f608bb64fd14f664abdc3,
  v2 f30445fad2a0c25e542fc6528f3495df6ca06650e5e0487bb0f0fc17c609b9cd,
  v3 fee20edb143a511a4007f1e42225d2810601e6fd98828d84490aea1959f2588c.

This also covers the seam end to end: a shipped strategy reconstitutes into exactly the
SkillVersion the framework hands out, with no framework-side domain knowledge left.
"""

from __future__ import annotations

from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_strategies import get_strategy, list_strategies

PINNED_CONTENT_HASH = {
    "v1": "4318897b183649a1aee85d6751c10a2d7a91120b4e9319605765471f56e057ab",
}


def _skill(version: str) -> SkillVersion:
    strategy = get_strategy("personal-knowledge", version)
    return SkillVersion.from_parts(
        skill_id=strategy.skill_id,
        version=strategy.version,
        instructions=strategy.read_text(),
        path_templates=strategy.path_templates,
        contract_rules=strategy.contract_rules,
    )


def test_reference_contract_text_cannot_change_silently():
    for version, expected in PINNED_CONTENT_HASH.items():
        assert _skill(version).content_hash == expected, version


def test_every_shipped_generation_is_covered_by_a_pinned_hash():
    """A new generation added without a pinned hash would slip through the check above."""
    versions = {s.version for s in list_strategies("personal-knowledge")}
    assert versions == set(PINNED_CONTENT_HASH)


def test_skill_id_still_reads_personal_knowledge():
    """The skill_id is hashed too — renaming the domain would break the trailers as surely
    as editing the body."""
    assert get_strategy("personal-knowledge", "v1").skill_id == "personal-knowledge"
