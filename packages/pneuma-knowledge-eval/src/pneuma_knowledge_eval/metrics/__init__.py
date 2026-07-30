"""The six metric groups. Every function here is pure: artifacts in, numbers out.

One group per module, one entry point per group (`*_metrics`), each returning a
JSON-serializable dict with an explicit `status` and — for every rate — the denominator it
was computed over. A rate without its denominator is not auditable, and a group that could
not be computed says `unavailable` with a reason instead of returning zeros that read like
findings.
"""

from __future__ import annotations

from .admission import admission_metrics
from .evolution import evolution_metrics
from .grounded import grounded_metrics
from .layering import layering_metrics
from .navigability import navigability_metrics

__all__ = [
    "admission_metrics",
    "evolution_metrics",
    "grounded_metrics",
    "layering_metrics",
    "navigability_metrics",
]
