"""Byte-stable loaders for the two evolve-phase System contracts (schema-evolve §2).

The editable form is the packaged asset (`skill/assets/evolve/phase1_contract.md` /
`phase2_contract.md`); the catalog keys `evolve.phase1_contract` / `evolve.phase2_contract`
default to those bytes, so a deployment replaces either contract wholesale through the same
seam as every other prompt surface. Resolution is a dict lookup, so the loaded text is
byte-stable from startup onward (no re-read, no drift) — the same I5 stability the recall
contracts get.
"""

from __future__ import annotations

from ..prompts import prompt


def phase1_contract() -> str:
    """The schema-draft (phase 1) System contract."""
    return prompt("evolve.phase1_contract")


def phase2_contract() -> str:
    """The whole-KB reorganization (phase 2) System contract."""
    return prompt("evolve.phase2_contract")
