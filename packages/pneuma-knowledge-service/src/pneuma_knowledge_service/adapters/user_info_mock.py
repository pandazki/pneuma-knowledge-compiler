"""Keyless UserInfoProvider for the public OPC project.

The one named persona is the repository's fictional Chinese solo developer. Any
other id receives a deterministic OPC-shaped profile derived only from its hash,
so tests and first-run flows stay stable without unrelated built-in profiles.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import (
    LEVELS,
    Avatar,
    Locale,
    Preferences,
    UserProfile,
    WorkspaceProfile,
)

# Soft, muted palette — avatar tile background, chosen deterministically from the id.
_PALETTE = [
    "#6C8EBF",  # dusty blue
    "#7FB069",  # sage green
    "#E8A87C",  # warm apricot
    "#C38D9E",  # mauve
    "#8E7CC3",  # soft violet
    "#4FA1A6",  # teal
    "#D9A05B",  # ochre
    "#A0785A",  # taupe
]

_BASE_JOIN = date(2024, 1, 1)  # fixed epoch; synthesized join dates derive from it.


def _digest(*parts: str) -> int:
    """A stable non-negative int from a salted id hash (deterministic, no random)."""
    h = hashlib.sha256(":".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def _color_for(user_id: str) -> str:
    return _PALETTE[_digest("color", user_id) % len(_PALETTE)]


# --------------------------------------------------------------------- named personas


def _persona(
    user_id: str,
    *,
    display_name: str,
    initial: str,
    gender: str | None,
    birth_year: int,
    city: str,
    country: str,
    timezone: str,
    language: str,
    industry: str,
    role: str,
    level: str,
    occupation: str,
    bio: str,
    interests: list[str],
    primary_stack: str,
    automation_level: str,
    active_since: str,
    units: str,
    privacy_level: str,
    joined_at: str,
) -> UserProfile:
    return UserProfile(
        user_id=UserId(user_id),
        display_name=display_name,
        avatar=Avatar(initial=initial, color=_color_for(user_id)),
        gender=gender,
        birth_year=birth_year,
        locale=Locale(city=city, country=country, timezone=timezone, language=language),
        industry=industry,
        role=role,
        level=level,
        occupation=occupation,
        bio=bio,
        interests=interests,
        workspace=WorkspaceProfile(
            operating_mode=(
                "opc"
                if role in {"engineering", "product_management", "design", "marketing"}
                else "independent"
            ),
            primary_stack=primary_stack,
            automation_level=automation_level,
            active_since=active_since,
        ),
        preferences=Preferences(
            response_language=language, units=units, privacy_level=privacy_level
        ),
        joined_at=joined_at,
        source="mock",
    )


def _build_personas() -> dict[str, UserProfile]:
    return {
        # Default synthetic protagonist: an AI-native one-person-company developer.
        "u-opc-lin": _persona(
            "u-opc-lin",
            display_name="Ada Lindqvist",
            initial="A",
            gender="female",
            birth_year=1992,
            city="Lisbon",
            country="Portugal",
            timezone="Europe/Lisbon",
            language="en-GB",
            industry="tech",
            role="engineering",
            level="senior",
            occupation="independent AI product developer",
            bio=(
                "I build AI products as a one-person company, using several agents to cover "
                "research, engineering, content and operations; I care about reproducible "
                "experiments, open-source feedback and cash-flow discipline."
            ),
            interests=[
                "open source",
                "agents",
                "product experiments",
                "developer tools",
                "long-distance running",
            ],
            primary_stack="TypeScript + Python",
            automation_level="agentic",
            active_since="2024-03-12",
            units="metric",
            privacy_level="standard",
            joined_at="2024-03-10",
        ),
    }


_PERSONAS: dict[str, UserProfile] = _build_personas()


# --------------------------------------------------------- deterministic synthesis pools

# The public fallback deliberately stays inside the same fictional one-person-company world
# as the named demo. Names are invented and selected deterministically from the user id.
_BUCKETS = [
    {
        "language": "en-GB",
        "units": "metric",
        "names": [
            ("Mira Halloran", "M", "female"),
            ("Tobias Rennick", "T", "male"),
            ("Sanne Vermeer", "S", "female"),
            ("Owen Castellan", "O", "male"),
            ("Priya Ravel", "P", "female"),
            ("Nils Aakerlund", "N", "male"),
        ],
        "cities": [
            ("Lisbon", "Portugal", "Europe/Lisbon"),
            ("Tallinn", "Estonia", "Europe/Tallinn"),
            ("Bristol", "United Kingdom", "Europe/London"),
            ("Valencia", "Spain", "Europe/Madrid"),
            ("Wellington", "New Zealand", "Pacific/Auckland"),
        ],
        "occupations": ["AI-native independent developer"],
        "interests": [
            "open source",
            "agents",
            "product experiments",
            "developer tools",
            "local-first software",
            "technical writing",
            "running",
            "photography",
        ],
    },
]

_PRIMARY_STACKS = [
    "Python + TypeScript",
    "TypeScript + Rust",
    "Python + Go",
    "React + FastAPI",
]
_PRIVACY = ["standard", "standard", "strict"]  # weighted toward standard


def _pick(pool: list, salt: str, user_id: str):
    return pool[_digest(salt, user_id) % len(pool)]


def _iso(base: date, salt: str, user_id: str, span: int) -> str:
    return (base + timedelta(days=_digest(salt, user_id) % span)).isoformat()


def _synthesize(user_id: str) -> UserProfile:
    """Build a deterministic, idempotent picture from the id alone."""
    bucket = _pick(_BUCKETS, "bucket", user_id)
    display_name, initial, gender = _pick(bucket["names"], "name", user_id)
    city, country, timezone = _pick(bucket["cities"], "city", user_id)
    occupation = _pick(bucket["occupations"], "occ", user_id)
    language = bucket["language"]

    # Two-to-three distinct interests, order-stable, derived from the id.
    pool = bucket["interests"]
    idx0 = _digest("int0", user_id) % len(pool)
    idx1 = (idx0 + 1 + _digest("int1", user_id) % (len(pool) - 1)) % len(pool)
    idx2 = (idx1 + 1 + _digest("int2", user_id) % (len(pool) - 1)) % len(pool)
    interests = list(dict.fromkeys([pool[idx0], pool[idx1], pool[idx2]]))

    joined_at = _iso(_BASE_JOIN, "join", user_id, 500)
    active_at = (
        _BASE_JOIN
        + timedelta(days=_digest("join", user_id) % 500)
        + timedelta(days=2 + _digest("pair", user_id) % 30)
    ).isoformat()

    return UserProfile(
        user_id=UserId(user_id),
        display_name=display_name,
        avatar=Avatar(initial=initial, color=_color_for(user_id)),
        gender=gender,
        birth_year=1962 + _digest("birth", user_id) % 46,  # ~18–64 y in 2026
        locale=Locale(city=city, country=country, timezone=timezone, language=language),
        industry="tech",
        role="engineering",
        level=_pick(list(LEVELS), "level", user_id),
        occupation=occupation,
        bio=(
            "I build AI products as a one-person company, using agents to cover research, "
            "engineering and operations."
        ),
        interests=interests,
        workspace=WorkspaceProfile(
            operating_mode="opc",
            primary_stack=_pick(_PRIMARY_STACKS, "stack", user_id),
            automation_level="agentic",
            active_since=active_at,
        ),
        preferences=Preferences(
            response_language=language,
            units=bucket["units"],
            privacy_level=_pick(_PRIVACY, "priv", user_id),
        ),
        joined_at=joined_at,
        source="mock",
    )


class MockUserInfoProvider:
    """One named OPC persona plus deterministic OPC synthesis for every other id."""

    def __init__(self, personas: dict[str, UserProfile] | None = None) -> None:
        self._personas = _PERSONAS if personas is None else dict(personas)

    async def get_profile(self, user_id: UserId) -> UserProfile:
        # async to satisfy the port; the body is pure in-memory lookup + hash synthesis,
        # so there is nothing to await and no thread hop is warranted.
        uid = str(user_id)
        exact = self._personas.get(uid)
        if exact is not None:
            return exact
        return _synthesize(uid)
