"""Stable profile provenance for display and model-visible identity, without persistence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.user import LOCALE_PROVENANCE_ALIASES, PROFILE_FIELDS


def profile_fields(profile: object) -> dict[str, Any]:
    """Every field the Steward may set, in the same order on every surface."""
    result = {}
    for key in PROFILE_FIELDS:
        value = profile
        for part in key.split("."):
            value = value.get(part) if isinstance(value, Mapping) else getattr(value, part, None)
        result[key] = value
    return result


def provenance_for(profile: object, key: str) -> str:
    provenance = (
        profile.get("provenance", {}) if isinstance(profile, Mapping)
        else getattr(profile, "provenance", {})
    ) or {}
    return provenance.get(key, provenance.get(LOCALE_PROVENANCE_ALIASES.get(key), "owner"))


def inferred_fields(profile: object) -> tuple[str, ...]:
    return tuple(key for key in PROFILE_FIELDS if provenance_for(profile, key) == "inferred")


def annotated_value(profile: object, key: str, value: str) -> str:
    """Confirmed values preserve the historical bytes; hypotheses name their provenance."""
    provenance = provenance_for(profile, key)
    if value and provenance == "inferred":
        return f"{value} ({provenance})"
    return value
