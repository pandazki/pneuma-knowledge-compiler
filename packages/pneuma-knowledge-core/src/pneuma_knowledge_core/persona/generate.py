"""One-sentence → ProfileDraft via a structured-output LLM call (AI-generated persona).

The product form lets a user type ONE sentence describing a person and have the model
expand it into a complete, self-consistent picture that pre-fills the form. This module
owns the SEMANTIC half of that picture — the fields a human would actually fill — and
leaves the non-semantic scaffolding (avatar color and joined_at) to the
deterministic mock base the service overlays this draft onto.

Two discipline points, both mechanical:

1. **Enums cannot drift.** `industry`/`role`/`level` are typed as `Literal` built FROM
   the domain tuples (`INDUSTRIES`/`ROLES`/`LEVELS`), never a hand-copied second list.
   Subscripting `Literal` with a tuple is identical to spelling the members out, so the
   structured-output JSON schema carries the exact enum the domain declares, and an
   out-of-enum value is rejected at validation time.
2. **Prompt-cache friendly assembly.** The SystemMessage is a fixed instruction with no
   volatile content; the sentence rides the HumanMessage. Same shape as recall/fast.py.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..domain.user import INDUSTRIES, LEVELS, ROLES
from ..prompts import prompt
from ..recall.fast import invoke_config

# Literal built FROM the domain tuples — subscripting Literal with a tuple is the same as
# spelling the members out, so the enum can never drift from user.py (single source).
IndustryLiteral = Literal[INDUSTRIES]  # type: ignore[valid-type]
RoleLiteral = Literal[ROLES]  # type: ignore[valid-type]
LevelLiteral = Literal[LEVELS]  # type: ignore[valid-type]


class DraftLocale(BaseModel):
    city: str
    country: str
    timezone: str  # IANA tz, e.g. "Asia/Shanghai"
    language: str  # BCP-47, e.g. "zh-CN"


class DraftPreferences(BaseModel):
    response_language: str  # BCP-47; the language the assistant answers in
    units: Literal["metric", "imperial"]
    privacy_level: Literal["standard", "strict"]


class DraftWorkspace(BaseModel):
    operating_mode: Literal["opc", "independent", "team"]
    primary_stack: str
    automation_level: Literal["manual", "assisted", "agentic"]
    active_since: str  # ISO date, e.g. "2024-05-01"


class ProfileDraft(BaseModel):
    """The semantic subset of a UserProfile the LLM fills from one sentence.

    Non-semantic scaffolding (avatar color, joined_at) is deliberately absent — the
    service supplies it from the deterministic mock base so the model never invents it.
    """

    display_name: str
    gender: str | None = None
    birth_year: int | None = None
    industry: IndustryLiteral
    industry_other: str | None = None  # free text when industry == "other"
    role: RoleLiteral
    role_other: str | None = None  # free text when role == "other"
    level: LevelLiteral
    occupation: str
    bio: str
    interests: list[str] = Field(default_factory=list)
    locale: DraftLocale
    preferences: DraftPreferences
    workspace: DraftWorkspace
    # A URL/filesystem-safe slug derived from the persona, e.g. "u-opc-lin".
    user_id: str


# Fixed, byte-stable instruction resolved from the prompt catalog. No volatile content — the
# sentence is the only per-request payload and rides the HumanMessage.


async def synthesize_profile_draft(
    model: BaseChatModel,
    sentence: str,
    *,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "profile.generate",
) -> ProfileDraft:
    """Expand one sentence into a validated ProfileDraft via structured output.

    The model is injected (core stays middleware-free), so a test can pass a fake whose
    `.with_structured_output(ProfileDraft)` returns a runnable yielding a fixed draft.
    """
    messages = [
        SystemMessage(content=prompt("persona.profile_instruction")),
        HumanMessage(content=sentence),
    ]
    structured = model.with_structured_output(ProfileDraft)
    draft = await structured.ainvoke(
        messages,
        config=invoke_config(run_name, callbacks, trace_metadata),
    )
    return draft  # type: ignore[return-value]
