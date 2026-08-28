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
- **Unparseable calls answered.** `create_agent` routes on `tool_calls` alone, so a call
  whose arguments were not valid JSON (`invalid_tool_calls`) would ride to the provider
  declared and unanswered and get the next turn rejected. One `wrap_model_call` middleware
  answers each inside the model node — see `AnswerInvalidToolCalls`.
- **Usage passthrough.** Token usage (incl. provider cache fields) is summed over every
  AIMessage the run produced.
- **Per-step wall-clock.** Every model turn and the forced finalize are measured and land on
  an `AgentTimings` in the order they happened; `timed_tools` measures each tool call onto
  the same object, so one ordered interleaving (`turn:1`, `tool:x`, `turn:2`, …, `finalize`,
  `total`) reaches the result. `total` wraps THIS loop — whatever seed retrieval a caller did
  before calling in is not a loop stage.

I5 holds: `system_prompt` is the caller's byte-stable contract (create_agent prepends
it verbatim as the SystemMessage on every model call); everything volatile rides the
Human turn and the ToolMessages.

The graph is driven with `astream` and the forced finalize with `ainvoke`, so a tool
round never blocks the event loop. Callers therefore pass tools whose implementation is
a coroutine (`StructuredTool.from_function(coroutine=...)`) — langgraph awaits those
directly instead of pushing them onto a thread.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from functools import wraps

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError

from ..prompts import prompt
from .fast import add_usage, extract_usage, invoke_config, message_text, zero_usage
from .stage_timing import (
    PREVIEW_RESULT_CHARS,
    StageEvent,
    StageEventSink,
    StagePhase,
    StageStatus,
    StageTiming,
    bound_preview,
    call_line,
    preview_head,
)

#: The agentic vocabulary. Unlike the fast lane's, it is NOT a fixed list: how many turns a
#: run took and which tools it reached for is what the timing is being asked. Only the
#: spelling is fixed, so every surface splits a name the same way (I4's habit, applied to a
#: telemetry name rather than a citation).
TURN_PREFIX = "turn:"
TOOL_PREFIX = "tool:"
FINALIZE = "finalize"
TOTAL = "total"

#: The only reason a forced finalize ever happens — the run hit the tool budget. Carried as
#: the `finalize` stage's `detail` so a reader sees WHY there was an extra closing call.
BUDGET = "budget"


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


class AgentTimings:
    """Per-step wall-clock for one agentic run, in the order the steps happened.

    Three kinds of step land here — a model turn (`turn:N`), a tool call (`tool:<name>`,
    recorded by `timed_tools`, which is why a caller can attach its own tool face to the same
    object) and the forced finalize (`finalize`) — and `stages()` closes the list with
    `total`, the loop's own wall-clock.

    The ORDER IS THE MEASUREMENT. Nothing is sorted or bucketed on the way out: an agentic
    run has no fixed vocabulary to emit against (that is the difference from
    `StageRecorder`), so the interleaving as it happened is the only faithful record of what
    the loop did. A stage that "did not run" therefore has no entry rather than a `skipped`
    one — in this lane there is no list of stages that could have run.

    I5: nothing measured here reaches a SystemMessage. Timings live on the result.
    """

    def __init__(self, *, on_event: StageEventSink | None = None) -> None:
        self._stages: list[StageTiming] = []
        #: How many model turns have been measured. Also what numbers the next `turn:N`.
        self.turns = 0
        #: The loop's own wall-clock in ms, 0 until `close`. Bounds every other stage by
        #: construction — each one is measured strictly inside it, and rounding is monotonic.
        self.total = 0
        self._on_event = on_event
        self._started = time.perf_counter()
        #: Mints the per-step keys. An agentic lane APPENDS (two calls to the same tool are
        #: two steps), so a name cannot identify a node the way it does for `StageRecorder`.
        self._seq = 0

    # ------------------------------------------------------------------ live events

    def _at(self) -> int:
        return int(round(max((time.perf_counter() - self._started) * 1000.0, 0.0)))

    def _announce(
        self,
        name: str,
        phase: StagePhase,
        key: str,
        at_ms: int,
        *,
        ms: int | None = None,
        status: StageStatus = "ran",
        detail: str | None = None,
        preview: dict | None = None,
    ) -> None:
        if self._on_event is None:
            return
        self._on_event(
            StageEvent(
                name=name,
                phase=phase,
                key=key,
                at_ms=at_ms,
                ms=ms,
                status=status,
                detail=detail,
                preview=preview,
            )
        )

    def begin(self, name: str) -> str:
        """Announce a step that has JUST STARTED; returns the key to close it with.

        This is the half that makes an agentic lane watchable: a model turn or a tool call is
        the long wait, and a consumer told about it only once it finished would show nothing
        during exactly the seconds it is being asked about."""
        self._seq += 1
        key = f"{name}#{self._seq}"
        self._announce(name, "start", key, self._at())
        return key

    def begin_tool(self, name: str) -> str:
        """`begin` for a tool call, in the tool vocabulary."""
        return self.begin(f"{TOOL_PREFIX}{name}")

    def next_turn_name(self) -> str:
        """What the turn about to run will be called. `turn` is what advances the count."""
        return f"{TURN_PREFIX}{self.turns + 1}"

    def _close_step(
        self,
        name: str,
        ms: float,
        key: str | None,
        status: StageStatus,
        detail: str | None,
        preview: Mapping | None = None,
    ) -> None:
        """Append the settled step and announce its `end` — back-dating a `start` when the
        caller never opened one, so `every end has a start` holds by construction.

        A step is appended, never accumulated, so its preview is whatever THIS step reported;
        there is nothing to merge it with. It goes through the same bound as every other."""
        rounded = int(round(max(ms, 0.0)))
        bounded = bound_preview(preview)
        self._stages.append(
            StageTiming(
                name=name, ms=rounded, status=status, detail=detail, preview=bounded
            )
        )
        if self._on_event is None:
            return
        at = self._at()
        if key is None:
            self._seq += 1
            key = f"{name}#{self._seq}"
            self._announce(name, "start", key, max(at - rounded, 0))
        self._announce(
            name,
            "end",
            key,
            at,
            ms=rounded,
            status=status,
            detail=detail,
            preview=bounded,
        )

    def turn(
        self, ms: float, *, key: str | None = None, preview: Mapping | None = None
    ) -> None:
        """One model turn of the graph (the agent node's step)."""
        self.turns += 1
        self._close_step(f"{TURN_PREFIX}{self.turns}", ms, key, "ran", None, preview)

    def tool(
        self,
        name: str,
        ms: float,
        *,
        key: str | None = None,
        status: StageStatus = "ran",
        detail: str | None = None,
        preview: Mapping | None = None,
    ) -> None:
        """One tool call, by tool name. `detail` is the failure the call reported — whether
        it raised or the tool swallowed it into its own record."""
        self._close_step(f"{TOOL_PREFIX}{name}", ms, key, status, detail, preview)

    def finalize(
        self, ms: float, *, key: str | None = None, detail: str | None = BUDGET
    ) -> None:
        """The tool-less closing call. It exists only because the budget ran dry, so it is
        reported as a degraded step naming that reason rather than as an ordinary turn."""
        self._close_step(
            FINALIZE, ms, key, "degraded" if detail else "ran", detail
        )

    def close(self, ms: float) -> None:
        """Seal the run's total. Called once, in a `finally`, so a raised run still totals."""
        self.total = int(round(max(ms, 0.0)))
        if self._on_event is None:
            return
        at = self._at()
        self._seq += 1
        key = f"{TOTAL}#{self._seq}"
        self._announce(TOTAL, "start", key, max(at - self.total, 0))
        self._announce(TOTAL, "end", key, at, ms=self.total)

    def stages(self) -> tuple[StageTiming, ...]:
        """The ordered interleaving, `total` last."""
        return (*self._stages, StageTiming(name=TOTAL, ms=self.total))


#: `watch(name, started)` → a `finish()` the wrapper calls when the coroutine returns.
#: `finish` returns the failure the tool swallowed into its own record, or None. It is how a
#: caller that keeps a per-call record of its own (deep's `trail`) learns when the call
#: started — early enough to stamp the duration on a record appended MID-CALL and streamed
#: live — and how a failure a tool handled instead of raising still reads as degraded.
ToolWatch = Callable[[str, float], Callable[[], str | None]]


def timed_tools(tools: list, timings: AgentTimings, *, watch: ToolWatch | None = None) -> list:
    """Wrap each tool so its wall-clock lands on `timings` as `tool:<name>`.

    Failures included, in both shapes a tool can fail. A tool that RAISES is measured and
    recorded degraded on the way past, before the exception travels on (langgraph re-raises
    anything but a schema error, so there is no "on the way out" left to record it in). A tool
    that SWALLOWS its failure into its own record — the shape deep's tools take, so a bad
    source id costs one round rather than the run — is named through `watch`'s `finish`.

    A tool with no coroutine face is returned untouched: this loop's callers pass coroutine
    tools by contract (see the module docstring), and silently rewriting a sync tool into an
    async one would be the larger lie.

    The wrapper carries `functools.wraps`, so langchain's signature inspection (injected
    `RunnableConfig`, callbacks) still sees the real tool's parameters through `__wrapped__`.
    """
    return [_timed_tool(tool, timings, watch) for tool in tools]


#: langchain injects these into a tool coroutine; they are plumbing, not what the model asked
#: for, and a preview of the call means the ARGUMENTS the model chose.
_INJECTED_ARGS = frozenset({"config", "callbacks", "run_manager", "callback_manager"})


def _call_line(name: str, kwargs: dict) -> str:
    """What the model asked this tool for, as the call it wrote: `search_claims(query="…")`.
    Positional args are not named and are not shown — every tool in these lanes is called by
    keyword, which is how langchain calls them."""
    return call_line(name, {k: v for k, v in kwargs.items() if k not in _INJECTED_ARGS})


def _result_preview(out: object) -> dict:
    """How much came back and what it SAYS at the top. A bounded head plus the size, never
    the result: a tool result is evidence, and evidence belongs in the answer's citations, not
    in a telemetry frame that every stage of every lane carries.

    The head is display text rather than the raw first line, because a tool's first line is
    usually its addressing (`c:1a2b docs/product/pricing.md`) and a reader who wanted that
    already has the citation."""
    text = out if isinstance(out, str) else str(getattr(out, "content", out))
    return {
        "result_chars": len(text),
        "result": preview_head(text, PREVIEW_RESULT_CHARS),
    }


def _timed_tool(tool, timings: AgentTimings, watch: ToolWatch | None):
    inner = getattr(tool, "coroutine", None)
    if inner is None:
        return tool
    name = getattr(tool, "name", None) or getattr(inner, "__name__", "tool")

    @wraps(inner)
    async def timed(*args, **kwargs):
        started = time.perf_counter()
        # Announced BEFORE the await, not after: a tool call is one of the two long waits in
        # an agentic run, and a watcher told about it only once it returned would show
        # nothing during exactly the seconds it is being asked about.
        key = timings.begin_tool(name)
        finish = watch(name, started) if watch is not None else None
        call = _call_line(name, kwargs)
        try:
            out = await inner(*args, **kwargs)
        except Exception as exc:
            if finish is not None:
                finish()
            timings.tool(
                name,
                _ms(started),
                key=key,
                status="degraded",
                detail=str(exc),
                preview={"call": call},
            )
            raise
        detail = finish() if finish is not None else None
        timings.tool(
            name,
            _ms(started),
            key=key,
            status="degraded" if detail else "ran",
            detail=detail,
            preview={"call": call, **_result_preview(out)},
        )
        return out

    return tool.model_copy(update={"coroutine": timed})


def _budget_notice() -> str:
    """The forced-finalize nudge injected at the budget edge."""
    return prompt("recall.agentic.budget_notice")


def _invalid_call_answer(call: dict) -> ToolMessage:
    """The result an unparseable tool call gets — the same line the compile loop uses."""
    return ToolMessage(
        content=prompt(
            "compile.tool.invalid_call",
            name=call.get("name") or "?",
            error=call.get("error") or "?",
        ),
        tool_call_id=call.get("id"),
    )


class AnswerInvalidToolCalls(AgentMiddleware):
    """Give every tool call the model emitted with unparseable arguments a result.

    `create_agent` routes on `AIMessage.tool_calls` only, and a call whose arguments did not
    parse as JSON lands in `invalid_tool_calls` instead — but the provider adapter puts it
    back on the wire as a function call all the same. So a batch of one good call and one bad
    one reaches the tool node with the good one, comes back with one result for two declared
    calls, and the NEXT model turn is rejected outright ("No tool output found for function
    call …"). Answering the bad call here, inside the model node's own response, is what
    keeps the transcript a legal exchange; the good calls route on untouched.

    A turn of nothing BUT invalid calls still ends the graph — the routing edge reads
    `tool_calls == 0` as the model ending its turn, and this seam does not get to overrule
    it. The loop closes on the model's own text rather than crashing, which is the whole
    claim being made here.
    """

    @staticmethod
    def _answered(response):  # noqa: ANN001, ANN205
        result = getattr(response, "result", None)
        if result is None:  # a bare AIMessage short-circuit from an inner layer
            return response
        answered: list = []
        for message in result:
            answered.append(message)
            for call in getattr(message, "invalid_tool_calls", None) or []:
                answered.append(_invalid_call_answer(call))
        if len(answered) != len(result):
            response.result = answered
        return response

    def wrap_model_call(self, request, handler):  # noqa: ANN001, ANN201, D102
        return self._answered(handler(request))

    async def awrap_model_call(self, request, handler):  # noqa: ANN001, ANN201, D102
        return self._answered(await handler(request))


#: What a caller passes to watch the answer TEXT arrive delta by delta. Same non-blocking
#: contract as `StageEventSink`: it runs inside the generating loop, on that loop's thread.
#: `message_text` (the reader's text out of either content shape) is the fast lane's and is
#: imported rather than repeated — one spelling of "what a reader would read", not two.
TokenSink = Callable[[str], None]


async def _closing_call(
    model: BaseChatModel,
    messages: list[BaseMessage],
    *,
    config: dict,
    on_token: TokenSink | None,
) -> BaseMessage:
    """The forced finalize's one model call — streamed when someone is watching, invoked
    when nobody is. The streamed branch folds the chunks back into one message so everything
    downstream (usage extraction, the transcript) sees the shape it always saw."""
    if on_token is None:
        return await model.ainvoke(messages, config=config)
    merged: BaseMessage | None = None
    async for chunk in model.astream(messages, config=config):
        delta = message_text(chunk.content)
        if delta:
            on_token(delta)
        merged = chunk if merged is None else merged + chunk  # type: ignore[operator]
    return merged if merged is not None else AIMessage(content="")


def _text(content: object) -> str:
    return (content if isinstance(content, str) else str(content)).strip()


def _turn_preview(message: AIMessage) -> dict:
    """What a model turn DECIDED: the tools it called, by name and argument.

    A turn's duration says the model thought for four seconds; this says what it decided at
    the end of them, which is the only thing that explains the tool call that follows. A turn
    that called nothing says so explicitly — "none" is a finding (it is the closing turn),
    not an absence to leave blank."""
    calls = list(getattr(message, "tool_calls", None) or [])
    if not calls:
        return {"tool_calls": "none"}
    return {
        "tool_calls": [
            call_line(str(c.get("name") or "?"), c.get("args") or {}) for c in calls
        ]
    }


async def run_agent_loop(
    model: BaseChatModel,
    tools: list,
    *,
    system_prompt: str,
    human: str | list[dict],
    tool_budget: int,
    run_name: str,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    timings: AgentTimings | None = None,
    on_token: TokenSink | None = None,
) -> tuple[str, dict[str, int], list[BaseMessage]]:
    """Run one bounded agentic exchange → (answer, token_usage, transcript).

    The transcript is the full message list of the run (sans system): the Human turn,
    every assistant/tool step, and the final answer — callers mine it for provenance.

    `timings` collects the run's per-step wall-clock. Pass the SAME object the caller wrapped
    its tools with (`timed_tools`) and the turns and the tool calls interleave in one ordered
    list; omit it and one is made here, so a caller that does not want timings is unchanged
    down to the branch count. Turns are read off `astream`'s value states: the state that ends
    in an AIMessage is the agent node's step, and the elapsed since the previous state is what
    that step cost. The tool node is deliberately NOT timed here — its wall-clock is the batch,
    while a reader wants the tools one by one, which is what `timed_tools` measures.

    `on_token` streams the model's TEXT as it is generated. Passing it switches the graph
    drive to langgraph's dual `["values", "messages"]` stream so the assistant's own deltas
    arrive alongside the state transitions, and switches the forced finalize from `ainvoke`
    to `astream`. Omit it and both stay exactly the call they were — one stream mode, one
    invoke — so a caller that does not want tokens pays nothing, not even a different code
    path through langgraph."""
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[AnswerInvalidToolCalls()],
    )
    config = {
        **invoke_config(run_name, callbacks, trace_metadata),
        "recursion_limit": 2 * tool_budget + 2,
    }
    timings = timings if timings is not None else AgentTimings()
    loop_started = time.perf_counter()

    state: dict | None = None
    try:
        mark = time.perf_counter()
        try:
            stream_mode = ["values", "messages"] if on_token is not None else "values"
            turn_key: str | None = None
            async for item in agent.astream(
                {"messages": [HumanMessage(content=human)]},
                config=config,
                stream_mode=stream_mode,
            ):
                if on_token is not None:
                    mode, payload = item
                    if mode == "messages":
                        chunk = payload[0] if isinstance(payload, tuple) else payload
                        if isinstance(chunk, AIMessageChunk):
                            delta = message_text(chunk.content)
                            if delta:
                                on_token(delta)
                        continue
                    state = payload
                else:
                    state = item
                now = time.perf_counter()
                streamed = (state or {}).get("messages") or []
                if streamed and isinstance(streamed[-1], AIMessage):
                    timings.turn(
                        (now - mark) * 1000.0,
                        key=turn_key,
                        preview=_turn_preview(streamed[-1]),
                    )
                    turn_key = None
                else:
                    # Anything that is not the agent node's own output — the input state, or
                    # a batch of tool results — means the model turn runs NEXT. Opening it
                    # here is what makes a waiting reader see `turn:2` while it is thinking.
                    turn_key = timings.begin(timings.next_turn_name())
                mark = now
            messages = list(state["messages"]) if state else []
            # The last message is normally the closing AIMessage. It is NOT when the closing
            # turn carried only unparseable tool calls: the middleware answered them, so the
            # transcript ends in those results and the answer is the assistant text under
            # them. Reading the last AIMessage says the same thing in every other case.
            answer = _text(
                next(
                    (m.content for m in reversed(messages) if isinstance(m, AIMessage)), ""
                )
            )
        except GraphRecursionError:
            # Budget dry with tool calls still pending: answer each pending call with the
            # budget notice (keeps the transcript provider-valid), then finalize tool-less.
            # The unparseable ones count too — they were declared to the provider all the
            # same, and the finalize invoke below is the call that would be rejected.
            messages = list(state["messages"]) if state else [HumanMessage(content=human)]
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
            for call in getattr(last_ai, "tool_calls", None) or []:
                if call["id"] not in answered:
                    messages.append(
                        ToolMessage(content=_budget_notice(), tool_call_id=call["id"])
                    )
            for call in getattr(last_ai, "invalid_tool_calls", None) or []:
                if call.get("id") not in answered:
                    messages.append(_invalid_call_answer(call))
            started = time.perf_counter()
            finalize_key = timings.begin(FINALIZE)
            final = await _closing_call(
                model,
                [SystemMessage(content=system_prompt), *messages],
                config=invoke_config(run_name, callbacks, trace_metadata),
                on_token=on_token,
            )
            timings.finalize(_ms(started), key=finalize_key, detail=BUDGET)
            messages.append(final)
            answer = _text(final.content)
    finally:
        timings.close(_ms(loop_started))

    usage = zero_usage()
    for m in messages:
        if isinstance(m, AIMessage):
            usage = add_usage(usage, extract_usage(m))
    return answer, usage, messages
