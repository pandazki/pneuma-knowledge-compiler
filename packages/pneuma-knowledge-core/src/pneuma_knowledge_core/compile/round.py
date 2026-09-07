"""One compile round, and the seam that lets a different body drive it.

`run_compile` owns everything AROUND a round — the aliasing, the components' window, the
draft, the gate, the commit — and one thing inside it: the loop that spends a budget of tool
calls over the draft's tool face. That loop is the only part of a compile that differs between
executors (docs/design/coding-agent-mode.md ruling 2, §9), so it is the only part behind a
protocol.

`RoundRunner` is that protocol, with exactly one method. `LangchainRoundRunner` is the loop as
it has always been: bind the tools to a `BaseChatModel`, invoke, dispatch each call, charge the
budget, answer every declared call, deliver the low-water notice once, stop when the model
finishes or the budget is gone. Nothing about the bytes the model sees changes by being here —
the messages are the caller's list, mutated in place exactly as before.

Where the second body plugs in: an agent executor's runner writes the draft to the
`DraftStore`, spawns the harness, waits for it to drive `pkc draft` commands, and reads the
draft back (§9, "`RoundRunner` in core"). Core knows the protocol and the draft's state form;
the subprocess is the service's business, and it arrives with the unattended launcher (§11
step 5). Interactively there is no runner at all — the Steward IS the round, and the CLI is
its face.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from ..prompts import prompt
from .anchor_ops import AnchorToolError

# How much budget must be LEFT for the low-water notice to still be worth sending. Below a
# handful of calls the notice would name work the model can no longer do; above it the
# notice is noise in the middle of a round that has room. Rendered once per round.
BUDGET_NOTICE_REMAINING = 6


class CompileCallTimeout(TimeoutError):
    """A single model call in the compile loop exceeded its wall-clock budget.

    A provider connection that hangs is invisible to every other guardrail: the request is
    open, no error arrives, and the job stays `claimed` — one hung call held a worker for
    23 minutes, and orphan reclaim only runs on worker restart. The bound is per CALL, not
    per compile: a slow-but-alive model must not be killed, so the budget is generous and
    the guard is against hangs. Raising propagates out of `run_compile` before any commit,
    so the worker's "any exception completes the job as failed" path records the reason and
    the canonical layer is untouched."""


async def _call_model(coro, timeout: float | None):
    """Await one model call under `timeout` seconds; `None` / `0` = no bound."""
    if not timeout:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError as exc:
        raise CompileCallTimeout(
            f"compile model call timed out after {timeout:g}s"
        ) from exc


def _no_lines() -> Sequence[str]:
    return ()


@dataclass(frozen=True)
class RoundToolFace:
    """The draft, as one round is allowed to see it: the tools, and two questions.

    A runner never touches the `PatchDraft` itself. It calls tools and it asks the two
    questions whose answers can only be judged over the whole draft rather than over one
    call — what an ending round still owes (`finish_owed`, the overview floor the
    `finish_compile` tool states while the material is still in hand) and what the gate's own
    predicates already find owed (`owed_now`, the low-water notice's content). Both come from
    `compile/gate.py`, so the two executors' notices cannot name different work.
    """

    tools: Sequence[StructuredTool]
    finish_owed: Callable[[], Sequence[str]] = _no_lines
    owed_now: Callable[[], Sequence[str]] = _no_lines


class RoundOutcome(NamedTuple):
    """What one round did: `(spent, cut_off, usage)`.

    "Cut off" is REPORTED, never re-derived from `spent == budget`: a round whose last call is
    `finish_compile` at exactly the budget ended on its own, and telling the repair round
    otherwise would be a false statement about what happened. `usage` is this round's token
    counts alone; the caller sums the rounds. A runner that cannot know what it spent (an
    agent under a subscription) reports nothing rather than zero.
    """

    spent: int
    cut_off: bool
    usage: dict[str, int]


class RoundRunner(Protocol):
    """One round, driven by one body."""

    async def run_round(
        self,
        *,
        messages: list[BaseMessage],
        face: RoundToolFace,
        budget: int,
    ) -> RoundOutcome:
        """Spend at most `budget` tool calls over `face`, continuing `messages` in place."""
        ...


@dataclass
class LangchainRoundRunner:
    """The compile loop as it has always been: a `BaseChatModel` bound to the draft's tools.

    `config` is the per-invoke config the service assembles (`callbacks`, `metadata`,
    `run_name`) — core depends only on langchain's callback abstraction (architecture.md §2),
    and a keyless run passes an empty one.
    """

    model: BaseChatModel
    call_timeout: float | None = None
    config: dict[str, Any] = field(default_factory=dict)

    async def run_round(
        self,
        *,
        messages: list[BaseMessage],
        face: RoundToolFace,
        budget: int,
    ) -> RoundOutcome:
        tools = list(face.tools)
        bound = self.model.bind_tools(tools)
        by_name = {t.name: t for t in tools}
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        def accumulate(response: BaseMessage) -> None:
            meta = getattr(response, "usage_metadata", None) or {}
            for key in usage:
                usage[key] += int(meta.get(key, 0) or 0)

        def answer_unreached(calls: Sequence[dict], start: int, content: str) -> None:
            """Give every call from `start` on a ToolMessage saying it was not executed.

            A batch's AIMessage declares N tool calls and a provider REQUIRES N results: a
            round that returns mid-batch leaves the transcript with tool calls nothing
            answered, and the next `ainvoke` over that history is rejected outright. Silent
            until now only because the round that returned mid-batch was the last one that
            ever ran — the repair round could not enter its loop. Now that it can, the reply
            has to exist.
            """
            for call in calls[start:]:
                messages.append(ToolMessage(content=content, tool_call_id=call.get("id")))

        spent = 0
        noticed = False
        while spent < budget:
            response = await _call_model(
                bound.ainvoke(messages, config=self.config), self.call_timeout
            )
            messages.append(response)
            accumulate(response)
            calls = getattr(response, "tool_calls", None) or []
            # A call whose arguments the model did not emit as valid JSON never becomes a
            # `tool_calls` entry — langchain files it under `invalid_tool_calls` — but the
            # assistant message still carries it on the wire, so the provider REQUIRES a
            # result for it exactly as for a parsed one ("No tool output found for
            # function call …" on the next invoke otherwise). It is answered here, BEFORE
            # the batch's valid calls, and charged to the round budget like a refused
            # call: an unparseable call spent a turn, and a model that keeps emitting them
            # runs out of round rather than looping forever.
            invalid = getattr(response, "invalid_tool_calls", None) or []
            if not calls and not invalid:
                # model ended its turn without more tool calls
                return RoundOutcome(spent, False, usage)
            for call in invalid:
                spent += 1
                messages.append(
                    ToolMessage(
                        content=prompt(
                            "compile.tool.invalid_call",
                            name=call.get("name") or "?",
                            error=call.get("error") or "?",
                        ),
                        tool_call_id=call.get("id"),
                    )
                )
            if invalid and spent >= budget:
                # The invalid calls alone spent the round: the rest of the batch still
                # needs its results, or the repair round is rejected on the transcript.
                answer_unreached(
                    calls, 0, prompt("compile.budget.call_refused", budget=budget)
                )
                return RoundOutcome(spent, True, usage)
            if not calls:
                # A batch of nothing but unparseable calls is NOT the model ending its
                # turn — it is the model failing to speak. Loop (budget permitting) so it
                # can re-send them; the low-water notice below is skipped for this batch
                # because no tool ran and nothing about the draft changed, and the next
                # batch that does reach it will state the remaining budget then.
                continue
            for index, call in enumerate(calls):
                spent += 1
                name, args, cid = call["name"], call.get("args", {}), call.get("id")
                if name == "finish_compile":
                    # The one rule that can only be judged at the END: an overview a
                    # document owes is owed by the round as a whole, not by any single
                    # call. Said here, the model still holds the material and one
                    # `rewrite_overview` fixes it; said at the gate, it costs the round's
                    # only repair round — the same reason every other overview rule is
                    # stated at a tool face. The gate re-states it (4d) for a draft that
                    # reaches it without finishing, and the budget bounds the retries.
                    owed = list(face.finish_owed())
                    if owed:
                        messages.append(
                            ToolMessage(content="\n".join(owed), tool_call_id=cid)
                        )
                        continue
                    messages.append(ToolMessage(content="ok", tool_call_id=cid))
                    answer_unreached(calls, index + 1, prompt("compile.tool.round_ended"))
                    return RoundOutcome(spent, False, usage)
                tool = by_name.get(name)
                if tool is None:
                    content = prompt("compile.tool.unknown_tool", name=name)
                else:
                    fn = tool.coroutine or tool.func
                    try:
                        # Read ports are async; the write tools stay sync (pure in-memory
                        # PatchDraft mutation). Dispatch on the function, as evolve does.
                        content = (
                            await fn(**args)
                            if inspect.iscoroutinefunction(fn)
                            else fn(**args)
                        )
                    except AnchorToolError as exc:
                        content = str(exc)
                    except (TypeError, ValueError) as exc:
                        content = prompt("compile.tool.call_failed", name=name, error=exc)
                messages.append(ToolMessage(content=content, tool_call_id=cid))
                if spent >= budget:
                    answer_unreached(
                        calls,
                        index + 1,
                        prompt("compile.budget.call_refused", budget=budget),
                    )
                    return RoundOutcome(spent, True, usage)
            # The low-water notice: the budget is a number the model cannot see from
            # inside the loop, and a round that does not know it is nearly over spends
            # its last calls on exploration. It rides a HumanMessage AFTER the whole
            # batch has been answered — every tool call in the batch already has its
            # ToolMessage, so the pairing the provider checks is intact — and once per
            # round, because a line repeated every turn stops being read.
            if not noticed and budget - spent <= BUDGET_NOTICE_REMAINING:
                noticed = True
                owed = list(face.owed_now())
                messages.append(
                    HumanMessage(
                        content=prompt(
                            "compile.budget.notice",
                            remaining=budget - spent,
                            budget=budget,
                            owed="\n".join(owed) or prompt("compile.budget.owed_none"),
                        )
                    )
                )
        return RoundOutcome(spent, True, usage)


__all__ = [
    "BUDGET_NOTICE_REMAINING",
    "CompileCallTimeout",
    "LangchainRoundRunner",
    "RoundOutcome",
    "RoundRunner",
    "RoundToolFace",
]
