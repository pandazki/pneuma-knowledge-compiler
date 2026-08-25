"""Post-compile brief: derived narration constrained to the mechanical record."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.compile.brief import (
    BRIEF_CHAR_BUDGET,
    CLAIM_CHAR_BUDGET,
    MAX_RECORD_CLAIMS,
    generate_brief,
    render_brief_record,
)
from pneuma_knowledge_core.compile.transitions import CompileEvent
from pneuma_knowledge_core.prompts import prompt


def _event(
    path: str = "projects/opc/decisions.md",
    after: str = "Release moved to September. [cite: src_1 ¶45-52] <!-- c:ab12 -->",
    type_: str = "claim_added",
) -> CompileEvent:
    return CompileEvent(type=type_, path=path, anchor="ab12", before=None, after=after)


def _model(answer: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=answer)]))


async def test_empty_events_yield_none_without_a_model_call():
    # An exhausted message iterator raises on any call, so a None here proves no call.
    model = GenericFakeChatModel(messages=iter([]))
    assert (
        await generate_brief(model=model, events=[], source_lines=["a meeting"]) is None
    )


async def test_happy_path_returns_normalized_text():
    model = _model("  Release delay and budget were\nrecorded.  ")
    brief = await generate_brief(
        model=model, events=[_event()], source_lines=["weekly meeting, 2 blocks"]
    )
    assert brief == "Release delay and budget were recorded."


async def test_record_strips_anchors_and_citations_and_names_documents():
    record = render_brief_record([_event()], ["weekly meeting, 2 blocks"])
    assert "projects/opc/decisions.md" in record
    assert "Release moved to September." in record
    assert "weekly meeting, 2 blocks" in record
    assert "cite" not in record
    assert "c:ab12" not in record


def test_record_caps_claims_and_states_the_remainder():
    events = [
        _event(after=f"claim number {i} " + "x" * 500)
        for i in range(MAX_RECORD_CLAIMS + 7)
    ]
    record = render_brief_record(events, [])
    assert "…and 7 further change(s) not shown." in record
    # Per-claim bodies are bounded too.
    longest = max(len(line) for line in record.splitlines())
    assert longest <= CLAIM_CHAR_BUDGET + len("- revised: ")


async def test_brief_is_mechanically_bounded():
    model = _model("word " * 1000)
    brief = await generate_brief(model=model, events=[_event()], source_lines=[])
    assert brief is not None and len(brief) <= BRIEF_CHAR_BUDGET


def test_system_prompt_is_byte_stable():
    # I5: the system message renders from the catalog with no interpolation slots, so
    # two renders are byte-identical and carry no volatile content.
    assert prompt("compile.brief.system") == prompt("compile.brief.system")
    assert "{" not in prompt("compile.brief.system")
