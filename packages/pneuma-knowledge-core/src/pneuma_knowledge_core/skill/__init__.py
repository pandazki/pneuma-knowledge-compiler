"""Vertical skill (slug form) + compact system-contract rendering.

architecture.md §1, §8. The package carries NO domain contract: deployments register a
complete domain strategy through the public registration seam, and `load_skill_base` fails
loudly rather than substituting one. `render_system_contract` projects a SkillVersion into
a byte-stable SystemMessage (I5).

  contract file format and judgement: `docs/guides/compile-contract.md` (repository root)
  reference contracts:  `packages/pneuma-knowledge-strategies/`
"""

from __future__ import annotations

from .contract import render_system_contract
from .labels import ClaimLabel, claim_labels_for
from .pack import (
    SchemaPack,
    compose_skill,
    derive_pack,
    derive_pack_contract,
    matrix_packs,
    packs_for_profile,
)
from .version import (
    CITATION_GRANULARITY_RULE,
    CITATION_SHAPE_RULE,
    STRENGTH_LABEL_RULE,
    SkillVersion,
    load_skill_base,
    register_skill_base,
    registered_skill_bases,
    reset_skill_bases,
)

__all__ = [
    "SkillVersion",
    "CITATION_GRANULARITY_RULE",
    "CITATION_SHAPE_RULE",
    "STRENGTH_LABEL_RULE",
    "load_skill_base",
    "register_skill_base",
    "registered_skill_bases",
    "reset_skill_bases",
    "render_system_contract",
    "ClaimLabel",
    "claim_labels_for",
    "SchemaPack",
    "compose_skill",
    "matrix_packs",
    "packs_for_profile",
    "derive_pack",
    "derive_pack_contract",
]
