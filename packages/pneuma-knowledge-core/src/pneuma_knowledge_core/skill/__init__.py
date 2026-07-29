"""Vertical skill (slug form) + compact system-contract rendering.

architecture.md §1, §8. The reworked smart-context clients skill's content is ported as a
packaged asset (`assets/opc_developer_v1.md`); Pneuma Compiler's contract/loader machine is not.
`render_system_contract` projects a SkillVersion into a byte-stable SystemMessage (I5).
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
    SkillVersion,
    load_builtin_skill,
    register_skill_base,
    registered_skill_bases,
    reset_skill_bases,
)

__all__ = [
    "SkillVersion",
    "load_builtin_skill",
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
