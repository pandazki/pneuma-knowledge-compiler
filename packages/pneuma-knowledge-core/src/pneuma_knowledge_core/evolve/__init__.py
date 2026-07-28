"""Schema evolve (schema-evolve §2): phase-1 proposal + evolve gate + phase-2 runner.

Pure core, zero middleware — ports (search / fetch / source-bounds) are injected. The
service (Stage C) supplies them, drives the two phases, and owns the branch commit; the
core commits nothing.
"""

from __future__ import annotations

from .contracts import phase1_contract, phase2_contract
from .gate import DroppedAnchor, run_evolve_gate
from .propose import EvolveProposal, ProposeReason, propose_evolution
from .runner import EvolveResult, run_evolve

__all__ = [
    "phase1_contract",
    "phase2_contract",
    "EvolveProposal",
    "ProposeReason",
    "propose_evolution",
    "DroppedAnchor",
    "run_evolve_gate",
    "EvolveResult",
    "run_evolve",
]
