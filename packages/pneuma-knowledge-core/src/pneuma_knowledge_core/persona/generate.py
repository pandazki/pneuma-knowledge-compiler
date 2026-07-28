"""One-sentence → ProfileDraft via a structured-output LLM call ("AI 生成人设").

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


# Fixed, byte-stable instruction (CJK-first product). No volatile content — the sentence
# is the only per-request payload and rides the HumanMessage.
_PROFILE_INSTRUCTION = """\
你是用户画像扩写器。根据用户给的一句话，合理扩展为一个完整、自洽、可信的用户画像。

规则：
- industry / role / level 必须从给定的枚举中选最贴切的一项；拿不准时 industry/role 选 other、level 选 mid。
- 其余字段据这句话合理设定并保持自洽：例如「上海销售」→ city 上海 / country 中国 / timezone Asia/Shanghai / language zh-CN。
- display_name 用符合该人物地域文化的自然姓名（如中文人物用中文名）。
- bio 用两三句、第一人称，具体不空泛。
- interests 给 3–5 个。
- user_id 用 `u-` 前缀加英文或拼音短 slug（仅字母、数字与连字符）。
- workspace 描述工作方式：一人公司用 operating_mode=opc；大量使用自主 agent 时 automation_level=agentic。
- timezone 用 IANA 时区名，language / response_language 用 BCP-47 标签，workspace.active_since 用 ISO 日期。
"""


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
        SystemMessage(content=_PROFILE_INSTRUCTION),
        HumanMessage(content=sentence),
    ]
    structured = model.with_structured_output(ProfileDraft)
    draft = await structured.ainvoke(
        messages,
        config=invoke_config(run_name, callbacks, trace_metadata),
    )
    return draft  # type: ignore[return-value]
