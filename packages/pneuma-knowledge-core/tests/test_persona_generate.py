"""persona: one-sentence → ProfileDraft structured-output call + enum discipline.

Fully keyless — a fake model whose `.with_structured_output` yields a fixed draft stands
in for the real provider call, so the assembly discipline (fixed System + sentence Human) and
the enum constraint are asserted without a provider key or the network.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.domain.user import INDUSTRIES, LEVELS, ROLES
from pneuma_knowledge_core.persona import ProfileDraft, synthesize_profile_draft
from pneuma_knowledge_core.persona.generate import _PROFILE_INSTRUCTION
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError


def _draft() -> ProfileDraft:
    return ProfileDraft(
        display_name="林知远 Lin Zhiyuan",
        gender="male",
        birth_year=1992,
        industry="tech",
        role="engineering",
        level="senior",
        occupation="AI 产品独立开发者",
        bio="我在杭州独立开发 AI 产品，用 agent 协作完成研究、工程和运营。",
        interests=["开源", "智能体", "产品实验"],
        locale={
            "city": "杭州",
            "country": "中国",
            "timezone": "Asia/Shanghai",
            "language": "zh-CN",
        },
        preferences={
            "response_language": "zh-CN",
            "units": "metric",
            "privacy_level": "standard",
        },
        workspace={
            "operating_mode": "opc",
            "primary_stack": "TypeScript + Python",
            "automation_level": "agentic",
            "active_since": "2024-05-01",
        },
        user_id="u-opc-lin",
    )


class _FakeStructured:
    """The runnable `with_structured_output` returns — records the invoke and yields a
    fixed draft."""

    def __init__(self, draft: ProfileDraft) -> None:
        self._draft = draft
        self.messages = None
        self.config = None

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.messages = messages
        self.config = config
        return self._draft


class _FakeModel:
    """A BaseChatModel stand-in: `with_structured_output(schema)` returns a runnable."""

    def __init__(self, draft: ProfileDraft) -> None:
        self._draft = draft
        self.schema = None
        self.structured = None

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schema = schema
        self.structured = _FakeStructured(self._draft)
        return self.structured


async def test_synthesize_assembles_messages_and_returns_draft():
    draft = _draft()
    model = _FakeModel(draft)

    out = await synthesize_profile_draft(model, "杭州做 AI 产品的独立开发者")

    # The draft flows straight through, unchanged.
    assert out is draft
    # Structured output is bound to ProfileDraft (the enum-carrying schema).
    assert model.schema is ProfileDraft
    # [SystemMessage(fixed instruction), HumanMessage(sentence)] — nothing else.
    msgs = model.structured.messages
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage) and msgs[0].content == _PROFILE_INSTRUCTION
    assert isinstance(msgs[1], HumanMessage) and msgs[1].content == "杭州做 AI 产品的独立开发者"
    # invoke_config wiring: run_name + empty callbacks/metadata on the keyless path.
    assert model.structured.config["run_name"] == "profile.generate"
    assert model.structured.config["callbacks"] == []
    assert model.structured.config["metadata"] == {}


async def test_run_name_and_trace_metadata_pass_through():
    model = _FakeModel(_draft())
    cb = object()
    await synthesize_profile_draft(
        model,
        "东京的软件工程师",
        callbacks=[cb],
        trace_metadata={"operation": "profile.generate"},
        run_name="custom.run",
    )
    cfg = model.structured.config
    assert cfg["run_name"] == "custom.run"
    assert cfg["callbacks"] == [cb]
    assert cfg["metadata"] == {"operation": "profile.generate"}


def test_draft_enums_track_the_domain_tuples():
    # The Literal-from-tuple constraint carries the exact domain enum into the schema.
    props = ProfileDraft.model_json_schema()["properties"]
    assert props["industry"]["enum"] == list(INDUSTRIES)
    assert props["role"]["enum"] == list(ROLES)
    assert props["level"]["enum"] == list(LEVELS)


@pytest.mark.parametrize(
    "field, bad",
    [
        ("industry", "aerospace"),
        ("role", "cto"),
        ("level", "godlike"),
    ],
)
def test_out_of_enum_rejected(field: str, bad: str):
    payload = _draft().model_dump()
    payload[field] = bad
    with pytest.raises(ValidationError):
        ProfileDraft.model_validate(payload)
