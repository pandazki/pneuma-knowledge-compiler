"""Per-step wall-clock for the agentic lanes (recall/agentic.py + recall/deep.py).

The fast lane emits a FIXED vocabulary (`stage_timing.STAGE_ORDER`); an agentic run cannot —
how many turns it took and which tools it reached for is precisely what is being measured. So
what is pinned here is the other kind of guarantee: the ORDER IS THE MEASUREMENT (turns and
tool calls interleave exactly as they happened, `total` last), every step's `ms` really is
that step's wall-clock (each is asserted against a delay injected into the step itself), a
failure is a `degraded` stage naming its reason rather than a fast success, and the trail
record a UI receives LIVE already carries its own `ms`.

What is deliberately not asserted: an upper bound on any individual stage. These are real
clocks on a shared machine; the only arithmetic invariant is `total >= every stage`, which
holds by construction because every stage is measured strictly inside the loop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool, ToolException

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.agentic import (
    AgentTimings,
    run_agent_loop,
    timed_tools,
)
from pneuma_knowledge_core.recall.deep import _TimedTrail, _trail_watch, deep_recall

from test_deep_recall import FakeContent, _model, _tool_call
from test_fast_recall import (
    ClaimStub,
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
)

_AS_OF = datetime(2026, 8, 26, 9, 0, 0)
_USER = UserId("u-agentic-timing")


def _names(stages) -> list[str]:
    return [s.name for s in stages]


def _by_name(stages) -> dict:
    return {s.name: s for s in stages}


def _slow_tool(name: str, delay_ms: float, *, fail: bool = False) -> StructuredTool:
    """A tool that costs a known amount of wall-clock, and optionally raises."""

    async def probe(query: str) -> str:
        await asyncio.sleep(delay_ms / 1000.0)
        if fail:
            raise ToolException("probe exploded")
        return f"{name} saw {query}"

    probe.__name__ = name
    return StructuredTool.from_function(coroutine=probe, name=name, description=name)


async def _run(model, tools, *, tool_budget: int = 4) -> AgentTimings:
    timings = AgentTimings()
    await run_agent_loop(
        model,
        timed_tools(tools, timings),
        system_prompt="contract",
        human="question",
        tool_budget=tool_budget,
        run_name="test.agentic",
        timings=timings,
    )
    return timings


async def test_turns_and_tool_calls_interleave_in_the_order_they_happened():
    """Two turns around two tool calls read back as the run's own sequence, total last."""
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("alpha", {"query": "a"}, "c1")]),
        AIMessage(content="", tool_calls=[_tool_call("beta", {"query": "b"}, "c2")]),
        AIMessage(content="the answer"),
    )
    timings = await _run(model, [_slow_tool("alpha", 40), _slow_tool("beta", 60)])
    assert _names(timings.stages()) == [
        "turn:1",
        "tool:alpha",
        "turn:2",
        "tool:beta",
        "turn:3",
        "total",
    ]
    stages = _by_name(timings.stages())
    # Each tool's clock is its OWN coroutine's, not the batch's and not the turn's.
    assert stages["tool:alpha"].ms >= 40
    assert stages["tool:beta"].ms >= 60
    assert timings.turns == 3
    # `total` wraps the loop, so it bounds every step measured inside it.
    assert all(stages["total"].ms >= s.ms for s in timings.stages())


def _deep_fakes():
    claims = [
        ClaimStub(
            anchor="c:aaaa",
            document_path="notes/one.md",
            section_path=("Notes",),
            text="A compiled claim.",
        )
    ]
    return {
        "claim_lexical": FakeClaimIndex(claims),
        "claim_vectors": FakeClaimIndex(claims),
        "embeddings": FakeEmbeddings(),
        "content": FakeContent(),
        "lexical": FakeLexical([]),
        "vectors": FakeVector([]),
    }


async def test_a_raising_tool_is_measured_and_named_before_the_exception_travels_on():
    """A tool that raises still cost time and still happened.

    langgraph's tool node re-raises anything but a schema error, so this run does not survive
    — which is exactly why the stage has to be recorded on the way past rather than on the way
    out. `total` still closes, because the loop seals it in a `finally`."""
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("boom", {"query": "x"}, "c1")]),
        AIMessage(content="never reached"),
    )
    timings = AgentTimings()
    with pytest.raises(ToolException):
        await run_agent_loop(
            model,
            timed_tools([_slow_tool("boom", 30, fail=True)], timings),
            system_prompt="contract",
            human="question",
            tool_budget=4,
            run_name="test.agentic",
            timings=timings,
        )
    boom = _by_name(timings.stages())["tool:boom"]
    assert boom.status == "degraded"
    assert "probe exploded" in (boom.detail or "")
    assert boom.ms >= 30
    assert timings.stages()[-1].name == "total" and timings.total >= boom.ms


async def test_a_tool_that_swallows_its_failure_still_reads_as_a_degraded_stage():
    """The shape deep's own tools actually take: `fetch_verbatim` answers a bad source id with
    a stated failure instead of raising, so the loop keeps going. The stage must not then read
    as a fast success — the trail record's `error` is what makes it degraded."""

    class MissingContent:
        async def fetch(self, user_id, source_id, locator):  # noqa: ANN001, ARG002
            raise KeyError(str(source_id))

        async def get(self, user_id, source_id):  # noqa: ANN001
            raise KeyError(source_id)

    model = _model(
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "fetch_verbatim",
                    {"source_id": "src-gone", "locator": {"block_start": 1, "block_end": 2}},
                    "c1",
                )
            ],
        ),
        AIMessage(content="answered without it"),
    )
    da = await deep_recall(
        _USER, "q", as_of=_AS_OF, model=model, **{**_deep_fakes(), "content": MissingContent()}
    )
    fetch = _by_name(da.stages)["tool:fetch_verbatim"]
    assert fetch.status == "degraded" and "src-gone" in (fetch.detail or "")
    assert da.trail[0]["ms"] >= 0


async def test_a_budget_forced_finalize_is_a_degraded_stage_named_budget():
    """The closing tool-less call exists only because the budget ran dry — so it is reported
    as its own step with that reason, not folded into an ordinary turn."""
    reaching = [
        AIMessage(content="", tool_calls=[_tool_call("alpha", {"query": str(i)}, f"c{i}")])
        for i in range(8)
    ]
    model = _model(*reaching, AIMessage(content="forced answer"))
    timings = await _run(model, [_slow_tool("alpha", 5)], tool_budget=1)
    names = _names(timings.stages())
    assert "finalize" in names
    assert names[-1] == "total"
    finalize = _by_name(timings.stages())["finalize"]
    assert finalize.status == "degraded" and finalize.detail == "budget"


async def test_an_untimed_loop_records_its_own_turns_and_totals():
    """`timings` is optional: a caller that wants none is not asked to pass one, and the loop
    still closes a total rather than growing a branch for the absent case."""
    model = _model(AIMessage(content="plain"))
    answer, _usage, _transcript = await run_agent_loop(
        model,
        [],
        system_prompt="contract",
        human="question",
        tool_budget=2,
        run_name="test.agentic",
    )
    assert answer == "plain"


async def test_deep_recall_carries_the_stages_and_stamps_ms_on_every_trail_step():
    """The wiring, end to end: deep wraps its own tools, so the interleaving reaches
    `DeepAnswer.stages`, and the trail record a UI streams already carries its `ms`."""
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("search_claims", {"query": "q"}, "c1")]),
        AIMessage(content="deep answer"),
    )
    live: list[dict] = []
    da = await deep_recall(
        _USER,
        "what happened?",
        as_of=_AS_OF,
        model=model,
        on_step=live.append,
        **_deep_fakes(),
    )
    assert _names(da.stages) == ["turn:1", "tool:search_claims", "turn:2", "total"]
    assert da.trail and all("ms" in step for step in da.trail)
    # The live callback fires from inside the tool, BEFORE the wrapper closes the call — the
    # `ms` has to be on the record by then or a streaming UI never sees it.
    assert live == list(da.trail)
    assert all(_by_name(da.stages)["total"].ms >= s.ms for s in da.stages)


async def test_the_fast_lanes_stage_vocabulary_is_untouched_by_the_agentic_one():
    """Deep's names are dynamic (`turn:N`, `tool:x`); fast's are the fixed `STAGE_ORDER`.
    Neither lane may borrow the other's vocabulary."""
    from pneuma_knowledge_core.recall.stage_timing import STAGE_ORDER, StageRecorder

    model = _model(AIMessage(content="deep answer"))
    da = await deep_recall(_USER, "q", as_of=_AS_OF, model=model, **_deep_fakes())
    assert not set(_names(da.stages)) & (set(STAGE_ORDER) - {"total"})
    assert _names(StageRecorder().emit())[: len(STAGE_ORDER)] != _names(da.stages)


@pytest.mark.parametrize("delay_ms", [50])
async def test_a_tool_stage_is_never_shorter_than_the_work_it_wrapped(delay_ms: int):
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("alpha", {"query": "a"}, "c1")]),
        AIMessage(content="done"),
    )
    timings = await _run(model, [_slow_tool("alpha", delay_ms)])
    assert _by_name(timings.stages())["tool:alpha"].ms >= delay_ms


async def test_two_tool_calls_in_one_turn_each_get_their_own_clock():
    """The reason the trail's start mark is a ContextVar and not an attribute.

    A model may reach for two tools in one turn, and langgraph's tool node runs them
    CONCURRENTLY, each in its own task. A shared start slot would let the second call's mark
    overwrite the first's, and the fast tool's record would report the slow tool's duration —
    silently, and only sometimes. Each task carries its own copy of the context, so the
    pairing of a start time to the record appended under it cannot be got wrong.

    Lower bounds only: these are real clocks, and what is being pinned is that each record was
    timed from ITS OWN start, not that the machine was quiet."""
    trail = _TimedTrail()
    timings = AgentTimings()

    def recording_tool(name: str, delay_ms: float) -> StructuredTool:
        async def probe(query: str) -> str:
            await asyncio.sleep(delay_ms / 1000.0)
            trail.append({"tool": name, "query": query})
            return name

        probe.__name__ = name
        return StructuredTool.from_function(coroutine=probe, name=name, description=name)

    model = _model(
        AIMessage(
            content="",
            tool_calls=[
                _tool_call("quick", {"query": "a"}, "c1"),
                _tool_call("slow", {"query": "b"}, "c2"),
            ],
        ),
        AIMessage(content="done"),
    )
    await run_agent_loop(
        model,
        timed_tools(
            [recording_tool("quick", 20), recording_tool("slow", 200)],
            timings,
            watch=_trail_watch,
        ),
        system_prompt="contract",
        human="question",
        tool_budget=4,
        run_name="test.agentic",
        timings=timings,
    )

    by_tool = {step["tool"]: step for step in trail}
    assert by_tool["quick"]["ms"] >= 20
    assert by_tool["slow"]["ms"] >= 200
    # The fast one was NOT charged the slow one's wall-clock — the failure a shared slot gives.
    assert by_tool["quick"]["ms"] < by_tool["slow"]["ms"]
    # Both calls sit between the turn that asked for them and the turn that read them back.
    assert _names(timings.stages()) == [
        "turn:1",
        "tool:quick",
        "tool:slow",
        "turn:2",
        "total",
    ]
