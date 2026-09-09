"""Declared owner profile. A tenant may have no stated personal information."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from .ids import UserId
from .time_context import TimezoneChange

# Onboarding enums for the business-neutral developer profile. These are NOT free text —
# they feed recall to tune answer style. Store the enum key; UI renders the label.
INDUSTRIES = (
    "tech",
    "finance",
    "sports",
    "creative",
    "education",
    "healthcare",
    "marketing",
    "other",
)
ROLES = (
    "engineering",
    "marketing",
    "product_management",
    "sales",
    "design",
    "support",
    "admin",
    "other",
)
# Seniority slider 1→6 (order-significant); each level carries an answer-style
# directive — the product semantics of `level` (it decides how the AI answers).
LEVEL_STYLES: dict[str, str] = {
    "entry": "Prefers thorough, step-by-step explanations with definitions.",
    "junior": "Prefers clear explanations with examples and some guidance.",
    "mid": "Prefers balanced answers with rationale and practical detail.",
    "senior": "Prefers concise, context-aware answers that focus on trade-offs and impact.",
    "staff": "Prefers high-signal answers emphasizing systemic implications and edge cases.",
    "principal": "Prefers terse, decision-oriented answers assuming deep expertise.",
}
LEVELS = tuple(LEVEL_STYLES)

# The stable, registration-level profile fields the Steward can write. Dotted names are
# leaves, so confirming one locale value never confirms its neighbouring fields.
PROFILE_FIELDS: tuple[str, ...] = (
    "display_name", "occupation", "bio", "interests", "industry", "role", "level",
    "locale.city", "locale.country", "locale.timezone", "locale.language",
    "preferences.response_language",
)
PLACEHOLDER_NAMES = frozenset({"", "someone", "owner"})
ProfileProvenance = Literal[
    "inferred", "owner", "placeholder", "profile", "deployment_default", "unstated"
]
LOCALE_PROVENANCE_ALIASES = {
    "locale.timezone": "timezone",
    "locale.language": "language",
    "locale.city": "region",
    "locale.country": "region",
}


class Avatar(BaseModel):
    """UI-generated avatar seed (no image asset): a letter tile on a soft color."""

    initial: str  # first letter / character of the display name
    color: str  # hex, e.g. "#6C8EBF" — soft palette, deterministic from the id


class Locale(BaseModel):
    city: str
    country: str
    timezone: str  # IANA tz, e.g. "Asia/Shanghai"
    language: str  # BCP-47, e.g. zh-CN / en-US / ja-JP
    # Forward-only record of timezone transitions, appended by the profile update path and
    # never edited by the client. Dates already compiled under an earlier zone are NOT
    # rewritten (canonical is the non-rebuildable layer); this history is what lets the
    # compile time frame say which zone those older dates were normalized under.
    timezone_history: list[TimezoneChange] = Field(default_factory=list)


class WorkspaceProfile(BaseModel):
    """How the user operates; no hardware or vendor semantics live here."""

    operating_mode: str  # deployment-defined mode, e.g. "independent" | "team"
    primary_stack: str  # concise human-readable stack, e.g. "Python + TypeScript"
    automation_level: str  # "manual" | "assisted" | "agentic"
    active_since: str  # ISO date, e.g. "2024-05-01"


class Preferences(BaseModel):
    response_language: str  # BCP-47; the language the assistant answers in
    units: str  # "metric" | "imperial"
    privacy_level: str  # "standard" | "strict"


class UserProfile(BaseModel):
    """A complete user picture keyed by user_id (core domain object)."""

    user_id: UserId
    display_name: str
    avatar: Avatar
    gender: str | None = None
    birth_year: int | None = None
    locale: Locale
    # Structured onboarding core (feeds recall answer-style tuning) — enum keys, not
    # free text. See INDUSTRIES / ROLES / LEVEL_STYLES.
    industry: str  # one of INDUSTRIES
    industry_other: str | None = None  # free text when industry == "other"
    role: str  # one of ROLES
    role_other: str | None = None  # free text when role == "other"
    level: str  # one of LEVELS (seniority) — drives AI answer style
    occupation: str  # optional free-text supplement to industry/role
    bio: str
    interests: list[str] = Field(default_factory=list)
    workspace: WorkspaceProfile
    preferences: Preferences
    joined_at: str  # ISO date
    source: str = "unstated"  # provenance; mock providers must opt in explicitly
    provenance: dict[str, ProfileProvenance] = Field(default_factory=dict)

    @classmethod
    def unstated(cls, user_id: UserId) -> "UserProfile":
        """An addressable profile without fabricated identity, location or biography."""
        return cls(
            user_id=user_id, display_name="", avatar=Avatar(initial="?", color="#6C8EBF"),
            locale=Locale(city="", country="", timezone="", language=""),
            industry="", role="", level="", occupation="", bio="", interests=[],
            workspace=WorkspaceProfile(operating_mode="", primary_stack="",
                                       automation_level="", active_since=""),
            preferences=Preferences(response_language="", units="", privacy_level=""),
            joined_at="", source="unstated",
        )

    @model_validator(mode="after")
    def complete_provenance(self) -> UserProfile:
        """Old records remain readable; every editable leaf gets an explicit provenance."""
        for key in PROFILE_FIELDS:
            if self.source == "unstated":
                self.provenance[key] = "placeholder"
                continue
            marker = self.provenance.get(key)
            if marker is None:
                marker = self.provenance.get(LOCALE_PROVENANCE_ALIASES.get(key))
            value: object = self
            for part in key.split("."):
                value = getattr(value, part)
            stated = any(x.strip() for x in value) if isinstance(value, list) else bool(str(value).strip())
            if key == "display_name" and self.display_name.strip().casefold() in PLACEHOLDER_NAMES:
                stated = False
            if marker == "profile":
                marker = "owner" if stated else "placeholder"
            elif marker in {"unstated", "deployment_default"}:
                marker = "placeholder"
            self.provenance[key] = marker or ("owner" if stated else "placeholder")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def level_style(self) -> str:
        """The answer-style directive for this seniority level (product semantics)."""
        return LEVEL_STYLES.get(self.level, "")
