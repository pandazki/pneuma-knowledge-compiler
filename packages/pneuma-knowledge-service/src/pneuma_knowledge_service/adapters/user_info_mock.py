"""Keyless, business-neutral UserInfoProvider fallback.

Every id receives a deterministic generic profile derived only from its hash. Product
examples persist their own profiles before ingestion; the framework adapter therefore
does not own a named persona, customer, occupation strategy or example storyline.
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


# --------------------------------------------------------- deterministic synthesis pools

# Names are invented and selected deterministically from the user id. The surrounding
# profile stays deliberately generic; example applications replace it with persisted data.
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
        "occupations": ["independent software developer"],
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
            "I use this workspace to organize technical projects, decisions and "
            "collaboration notes."
        ),
        interests=interests,
        workspace=WorkspaceProfile(
            operating_mode="independent",
            primary_stack=_pick(_PRIMARY_STACKS, "stack", user_id),
            automation_level="assisted",
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
    """Injected test personas plus deterministic generic synthesis for other ids."""

    def __init__(self, personas: dict[str, UserProfile] | None = None) -> None:
        self._personas = {} if personas is None else dict(personas)

    async def get_profile(self, user_id: UserId) -> UserProfile:
        # async to satisfy the port; the body is pure in-memory lookup + hash synthesis,
        # so there is nothing to await and no thread hop is warranted.
        uid = str(user_id)
        exact = self._personas.get(uid)
        if exact is not None:
            return exact
        return _synthesize(uid)
