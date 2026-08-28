"""The agentic loop's half of the unparseable-tool-call fix (`recall/agentic.py`).

`create_agent` routes on `AIMessage.tool_calls` alone. A call whose arguments the model did
not emit as valid JSON lands in `invalid_tool_calls` instead — but the provider adapter puts
it back on the wire as a function call all the same, so a mixed batch would reach the next
model turn with two calls declared and one result, and be rejected outright (`400 … No tool
output found for function call …`). `AnswerInvalidToolCalls` answers each inside the model
node; these pin that the transcript the next turn receives is a legal exchange.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.agentic import run_agent_loop

from test_deep_recall import _model, _tool_call


def _probe() -> StructuredTool:
    async def probe(query: str) -> str:
        return f"probe saw {query}"

    return StructuredTool.from_function(coroutine=probe, name="probe", description="probe")


def _bad_call(name: str, cid: str) -> dict:
    return {
        "name": name,
        "args": '{"query": ',  # never parsed
        "id": cid,
        "error": "unterminated object",
        "type": "invalid_tool_call",
    }


async def _run(model) -> tuple[str, list]:
    answer, _usage, messages = await run_agent_loop(
        model,
        [_probe()],
        system_prompt="contract",
        human="question",
        tool_budget=4,
        run_name="test.agentic.invalid",
    )
    return answer, messages


async def test_a_mixed_batch_answers_the_unparseable_call_and_the_valid_one():
    """Both ids answered, the unparseable one first — it is answered in the model node,
    before the valid call has even reached the tool node."""
    bad = _bad_call("probe", "call-bad")
    good = _tool_call("probe", {"query": "atlas"}, "call-good")
    model = _model(
        AIMessage(content="", tool_calls=[good], invalid_tool_calls=[bad]),
        AIMessage(content="the answer"),
    )
    answer, messages = await _run(model)

    assert answer == "the answer"
    # The history the SECOND model call was handed — the one a provider would reject.
    second_turn = model.seen[1]
    answered = [m.tool_call_id for m in second_turn if isinstance(m, ToolMessage)]
    assert answered == ["call-bad", "call-good"]
    [refusal] = [
        m for m in second_turn if isinstance(m, ToolMessage) and m.tool_call_id == "call-bad"
    ]
    assert str(refusal.content) == prompt(
        "compile.tool.invalid_call", name="probe", error="unterminated object"
    )


async def test_a_turn_of_only_unparseable_calls_still_closes_on_the_models_own_text():
    """`create_agent` reads `tool_calls == 0` as the model ending its turn, and this seam
    does not overrule the routing edge — so the run ends here. What it must NOT do is hand
    back the refusal as if it were the answer: the answer is the assistant's own text."""
    bad = _bad_call("probe", "call-only-bad")
    model = _model(AIMessage(content="all I have", invalid_tool_calls=[bad]))
    answer, messages = await _run(model)

    assert answer == "all I have"
    assert [m.tool_call_id for m in messages if isinstance(m, ToolMessage)] == [
        "call-only-bad"
    ]
