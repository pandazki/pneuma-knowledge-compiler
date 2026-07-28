"""Byte-stable loaders for the two evolve-phase System contracts (schema-evolve §2).

Stage S authored `skill/assets/evolve/phase1_contract.md` / `phase2_contract.md`; the
mechanism only loads them. `lru_cache` reads each file at most once per process, so the
loaded text is byte-stable from module load onward (no re-read, no drift) — the same I5
stability the recall contracts get from module-level string constants.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_EVOLVE_ASSETS = (
    Path(__file__).resolve().parents[1] / "skill" / "assets" / "evolve"
)


@lru_cache(maxsize=None)
def phase1_contract() -> str:
    """The schema-draft (phase 1) System contract — verbatim asset text."""
    return (_EVOLVE_ASSETS / "phase1_contract.md").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def phase2_contract() -> str:
    """The whole-KB reorganization (phase 2) System contract — verbatim asset text."""
    return (_EVOLVE_ASSETS / "phase2_contract.md").read_text(encoding="utf-8")
