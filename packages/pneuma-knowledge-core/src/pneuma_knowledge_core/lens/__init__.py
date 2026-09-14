"""The STRUCTURE LENS — tier three of docs/design/structure-lens.md: what only the whole shows.

The Steward works inside the library, one source at a time, and every compile can be right
while the sum drifts. Some of that drift a write can refuse and some of it a Steward can find
by checking the page against the contract — and those belong to the tiers that can see them.
What is left is what the library is BECOMING: whether it is walkable as a body, where
knowledge piles up, how much of it is a log of sessions rather than knowledge about subjects,
whether it ever corrects itself, whether the structure its accumulating knowledge implies
exists yet, and whether what it holds is what people ask it.

This package is that reading. Six dimensions, each with a band chosen by named thresholds, one
statement, one direction naming a lever — a contract clause, an evolve, a groom, a review
round, never a page — and its metrics with their movement since the previous reading. It
lists no page and carries no score: a page-level finding is the check's, and the six bands and
their movement are the whole summary.

Everything is derived and model-free: canonical documents, the contract's path templates and
the kept consultation records in, a `LensReading` out, writing nothing.
"""

from __future__ import annotations

from .dimensions import (
    Consultation,
    Observation,
    read_demand_supply,
    read_dimensions,
    read_knowledge_vs_log,
    read_liveness,
    read_shape,
    read_type_structure,
    read_walkability,
)
from .model import DIMENSION_BANDS, DIMENSION_IDS, Dimension, LensReading, Metric
from .reading import (
    build_reading,
    dimension_of,
    render_direction,
    render_statement,
)

__all__ = [
    "DIMENSION_BANDS",
    "DIMENSION_IDS",
    "Consultation",
    "Dimension",
    "LensReading",
    "Metric",
    "Observation",
    "build_reading",
    "dimension_of",
    "read_demand_supply",
    "read_dimensions",
    "read_knowledge_vs_log",
    "read_liveness",
    "read_shape",
    "read_type_structure",
    "read_walkability",
    "render_direction",
    "render_statement",
]
