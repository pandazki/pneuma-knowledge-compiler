"""Shared bounded agentic loop for recall (deep / briefing ask).

The loop itself is langchain's `create_agent` (langgraph ReAct) — the mature harness,
not a hand-rolled tool loop. What this module adds is the recall-specific mechanics
(§0 discipline 1, all mechanical):

- **Budget as recursion_limit.** `tool_budget` tool rounds = `2 * budget + 2` as the
  limit: agent → tools per round (2 steps) plus the closing agent turn, and langgraph
  raises when the step count REACHES the limit, so the bound sits one past that total.
- **Forced finalize.** When the model is still reaching for tools at the budget edge
  (GraphRecursionError), pending tool calls are answered with a budget notice and ONE
  tool-less invoke closes the run — the loop always terminates with an answer.
- **Usage passthrough.** Token usage (incl. provider cache fields) is summed over every
  AIMessage the run produced.

I5 holds: `system_prompt` is the caller's byte-stable contract (create_agent prepends
it verbatim as the SystemMessage on every model call); everything volatile rides the
Human turn and the ToolMessages.

The graph is driven with `astream` and the forced finalize with `ainvoke`, so a tool
round never blocks the event loop. Callers therefore pass tools whose implementation is
a coroutine (`StructuredTool.from_function(coroutine=...)`) — langgraph awaits those
directly instead of pushing them onto a thread.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from ..prompts import prompt
from .fast import add_usage, extract_usage, invoke_config, zero_usage


def _budget_notice() -> str:
    """The forced-finalize nudge injected at the budget edge."""
    return prompt("recall.agentic.budget_notice")


def _text(content: object) -> str:
    return (content if isinstance(content, str) else str(content)).strip()


async def run_agent_loop(
    model: BaseChatModel,
    tools: list,
    *,
    system_prompt: str,
    human: str,
    tool_budget: int,
    run_name: str,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[str, dict[str, int], list[BaseMessage]]:
    """Run one bounded agentic exchange → (answer, token_usage, transcript).

    The transcript is the full message list of the run (sans system): the Human turn,
    every assistant/tool step, and the final answer — callers mine it for provenance."""
    agent = create_agent(model=model, tools=tools, system_prompt=system_prompt)
    config = {
        **invoke_config(run_name, callbacks, trace_metadata),
        "recursion_limit": 2 * tool_budget + 2,
    }

    state: dict | None = None
    try:
        async for state in agent.astream(
            {"messages": [HumanMessage(content=human)]}, config=config, stream_mode="values"
        ):
            pass
        messages = list(state["messages"]) if state else []
        answer = _text(messages[-1].content) if messages else ""
    except GraphRecursionError:
        # Budget dry with tool calls still pending: answer each pending call with the
        # budget notice (keeps the transcript provider-valid), then finalize tool-less.
        messages = list(state["messages"]) if state else [HumanMessage(content=human)]
        pending = getattr(messages[-1], "tool_calls", None) or []
        for call in pending:
            messages.append(ToolMessage(content=_budget_notice(), tool_call_id=call["id"]))
        final = await model.ainvoke(
            [SystemMessage(content=system_prompt), *messages],
            config=invoke_config(run_name, callbacks, trace_metadata),
        )
        messages.append(final)
        answer = _text(final.content)

    usage = zero_usage()
    for m in messages:
        if isinstance(m, AIMessage):
            usage = add_usage(usage, extract_usage(m))
    return answer, usage, messages
