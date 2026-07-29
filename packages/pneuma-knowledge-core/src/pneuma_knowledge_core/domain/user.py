"""UserProfile — the user-picture core domain object (architecture.md §6).

user_id is the unique key of this core domain object; all sub-facets of a
user's picture hang off it. v1 is fed by a mock provider (service
adapters/user_info_mock.py); a real sync source replaces `source` later without
changing this shape. UI uses `display_name` / `avatar` everywhere instead of the
raw id.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

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

    operating_mode: str  # "opc" | "independent" | "team"
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
    source: str = "mock"  # provenance of this picture; "mock" until real sync lands

    @computed_field  # type: ignore[prop-decorator]
    @property
    def level_style(self) -> str:
        """The answer-style directive for this seniority level (product semantics)."""
        return LEVEL_STYLES.get(self.level, LEVEL_STYLES["mid"])
