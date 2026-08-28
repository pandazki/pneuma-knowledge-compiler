"""Stage timing as it HAPPENS — the live face of `recall/stage_timing.py`.

Every lane already reports what each stage cost once it is over. That answer arrives with the
answer, which is precisely when nobody is waiting for it any more. So the same measure sites
now ANNOUNCE themselves: a `StageEvent` when a stage begins and one when it settles.

The property that makes this trustworthy — and what most of this file pins — is that there is
ONE CLOCK. The events are not a second, parallel instrumentation that could drift from the
result; they are emitted from inside `StageRecorder` / `AgentTimings` themselves, out of the
same accumulated state `emit()` / `stages()` read at the end. So:

- for a lane with a fixed vocabulary (fast recall, the briefing build), the LAST `end` event
  per key is exactly that stage's final entry — same ms, same status, same reason;
- for an agentic lane (deep recall, a briefing ask), where the order IS the measurement and a
  tool may be called twice, the `end` events in order ARE the final list minus `total`.

The two need different rules because the two lanes mean different things by a stage name, and
that is why `StageEvent` carries a `key`: the recorder accumulates by name (`rerank` is two
sequential passes reported as one stage, so its key is its name and a later end supersedes an
earlier one), while an agentic run appends (two `search_claims` calls are two steps, so each
mints its own key). A consumer keys on `key` and prints `name` and is correct for both
without knowing which lane it is watching.

Durations are asserted with floors only — a 60 ms sleep cannot report 20 ms — never with
ceilings: a loaded machine is allowed to be slow, and a test that failed when it was would be
measuring the box rather than the code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.agentic import AgentTimings, run_agent_loop, timed_tools
from pneuma_knowledge_core.recall.briefing import BriefingScope, briefing_ask, build_briefing
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.recall.stage_timing import (
    StageEvent,
    StageRecorder,
    child_name,
)

from test_deep_recall import FakeContent, ScriptedToolModel, _model, _tool_call
from test_fast_recall import (
    ClaimStub,
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
)
from test_fast_stage_timing import _Model, _PersonPath, _SlowClaimIndex

_USER = UserId("u-stage-events")
_AS_OF = datetime(2026, 8, 26, 9, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ helpers


class Watcher:
    """Collects events the way a stream route does — synchronously, never blocking."""

    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    def __call__(self, event: StageEvent) -> None:
        self.events.append(event)

    @property
    def starts(self) -> list[StageEvent]:
        return [e for e in self.events if e.phase == "start"]

    @property
    def ends(self) -> list[StageEvent]:
        return [e for e in self.events if e.phase == "end"]

    def settled(self) -> dict[str, StageEvent]:
        """Last `end` per key — the rule a consumer of a fixed-vocabulary lane follows."""
        out: dict[str, StageEvent] = {}
        for event in self.ends:
            out[event.key] = event
        return out


def _mirrors_recorder_lane(watcher: Watcher, stages) -> None:
    """The recorder contract: settled ends == the final stages that actually ran."""
    settled = watcher.settled()
    ran = {s.name: s for s in stages if s.status != "skipped"}
    assert set(settled) == set(ran), (sorted(settled), sorted(ran))
    for name, stage in ran.items():
        event = settled[name]
        assert event.name == name
        assert event.ms == stage.ms, name
        assert event.status == stage.status, name
        assert event.detail == stage.detail, name
    # A stage that never ran never announced itself: "did not happen" is the absence of an
    # event, exactly as it is `status="skipped"` in the emitted list.
    assert not (set(settled) & {s.name for s in stages if s.status == "skipped"})


def _every_end_has_a_start(watcher: Watcher) -> None:
    opened: set[str] = set()
    for event in watcher.events:
        if event.phase == "start":
            opened.add(event.key)
        else:
            assert event.key in opened, f"{event.key} ended without ever starting"
            assert event.ms is not None
    for start in watcher.starts:
        assert start.ms is None, "a start has measured nothing yet"


# ------------------------------------------------------------ the recorder itself


def test_a_start_precedes_every_end_and_the_end_carries_the_settled_value():
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    with recorder.measure("plan"):
        pass
    recorder.record("answer", 30.0)
    assert [(e.name, e.phase) for e in watcher.events] == [
        ("plan", "start"),
        ("plan", "end"),
        ("answer", "start"),
        ("answer", "end"),
    ]
    assert watcher.settled()["answer"].ms == 30
    _mirrors_recorder_lane(watcher, recorder.emit())


def test_a_repeated_stage_reopens_under_one_key_and_the_last_end_is_the_total():
    """`rerank` is genuinely two sequential passes. The events grow the SAME node rather
    than inventing a second one, which is why the recorder's key is the name."""
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    recorder.record("rerank", 10.0)
    recorder.record("rerank", 15.0)
    ends = [e for e in watcher.ends if e.name == "rerank"]
    assert [e.ms for e in ends] == [10, 25]
    assert len({e.key for e in ends}) == 1
    _mirrors_recorder_lane(watcher, recorder.emit())


def test_a_reason_that_arrives_after_the_stage_ended_corrects_it_with_a_second_end():
    """The lanes call `degrade` just after the `measure` block that produced the reason, so
    a stage that already ended is corrected in place — last end wins."""
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    with recorder.measure("plan"):
        pass
    recorder.degrade("plan", "timeout")
    ends = [e for e in watcher.ends if e.name == "plan"]
    assert [e.status for e in ends] == ["ran", "degraded"]
    assert ends[-1].detail == "timeout"
    _mirrors_recorder_lane(watcher, recorder.emit())


def test_a_reason_for_a_stage_that_never_ran_announces_nothing():
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    recorder.degrade("route", "timeout")
    assert watcher.events == []
    assert {s.name: s.status for s in recorder.emit()}["route"] == "skipped"


async def test_an_after_the_fact_record_is_back_dated_to_where_the_work_actually_was():
    """`record` is handed a duration someone else measured. Placing its start `ms` earlier
    is what stops a 40 ms path from rendering as an instant at the end of the lane.

    The back-dating is clamped at the lane's own start: a stage cannot have begun before the
    lane it is a stage of, so a path longer than everything measured so far opens at zero."""
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    await asyncio.sleep(0.06)  # let the lane clock advance past the path's own duration
    recorder.record_path("person", 40.0)
    start, end = watcher.events
    assert start.phase == "start" and end.phase == "end"
    assert end.at_ms - start.at_ms == 40
    assert start.at_ms > 0
    assert end.name == child_name("path:person")


def test_a_recorder_with_no_watcher_emits_nothing_at_all():
    """The whole feature is opt-in: no callback, no events, no branch a caller can observe."""
    recorder = StageRecorder()
    with recorder.measure("plan"):
        pass
    recorder.record_path("person", 5.0, detail="timeout")
    recorder.degrade("plan", "error")
    assert {s.name for s in recorder.emit() if s.status != "skipped"} == {
        "plan",
        child_name("path:person"),
    }


# ------------------------------------------------------------------ the fast lane


def _fast_kwargs(model, **extra):
    index = extra.pop(
        "index",
        FakeClaimIndex(
            [
                ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责恒印印刷的对接"),
                ClaimStub("b2d0", "memory/people/lin-wei.md", "林薇先给排期再谈价"),
            ]
        ),
    )
    return dict(
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=model,
        **extra,
    )


async def test_the_fast_lane_events_mirror_the_stages_it_finally_reports():
    watcher = Watcher()
    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        fast_paths=(),
        on_event=watcher,
        **_fast_kwargs(_Model(answer="A")),
    )
    _every_end_has_a_start(watcher)
    _mirrors_recorder_lane(watcher, fa.stages)
    # `total` is the last thing announced, as it is the last thing emitted: it wraps the run.
    assert watcher.ends[-1].name == "total"


async def test_the_concurrent_retrieval_children_interleave_instead_of_queueing():
    """The gather's children run at the same time, so their starts all precede their ends —
    the fact a strip is drawing when it shows three lanes lit at once."""
    watcher = Watcher()
    slow = _SlowClaimIndex(
        [ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责对接")], 0.06
    )
    await fast_recall(
        _USER,
        "林薇",
        fast_paths=(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        on_event=watcher,
        **_fast_kwargs(_Model(answer="A"), index=slow),
    )
    claims = child_name("claims")
    windows = child_name("windows")
    order = [e for e in watcher.events if e.name in (claims, windows)]
    phases = [(e.name, e.phase) for e in order]
    # Both children started before either finished — that is what concurrency looks like on
    # the wire, and a strip that rendered them sequentially would be reporting a lie.
    assert phases[0][1] == "start" and phases[1][1] == "start"
    assert {phases[0][0], phases[1][0]} == {claims, windows}
    # The parent gather opens before its children and closes after them.
    parent_start = next(i for i, e in enumerate(watcher.events) if e.name == "retrieve")
    assert parent_start < watcher.events.index(order[0])


async def test_a_routed_component_path_announces_itself_as_a_retrieve_child():
    watcher = Watcher()
    model = _Model(
        answer="A",
        route_calls=[{"name": "person", "args": {"alias": "林薇"}, "id": "call-1"}],
    )
    await fast_recall(
        _USER,
        "林薇",
        fast_paths=(_PersonPath(delay=0.04),),
        on_event=watcher,
        **_fast_kwargs(model),
    )
    path = child_name("path:person")
    assert [e.phase for e in watcher.events if e.name == path] == ["start", "end"]
    assert watcher.settled()[path].ms >= 40


async def test_the_fast_answer_streams_its_text_while_the_call_is_still_running():
    tokens: list[str] = []
    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        fast_paths=(),
        on_token=tokens.append,
        **_fast_kwargs(_StreamingModel(answer="林薇负责采购")),
    )
    # Every delta arrived separately, and joined they are the answer the result carries.
    assert len(tokens) > 1
    assert "".join(tokens) == fa.answer


async def test_the_fast_lane_without_a_token_sink_never_streams():
    """`on_token=None` must not quietly become "stream and re-join": the historical lane
    makes one `ainvoke`, and that is what a deployment that asked for nothing still gets."""
    model = _StreamingModel(answer="林薇负责采购")
    await fast_recall(_USER, "q", fast_paths=(), **_fast_kwargs(model))
    assert model.streamed == 0


# ------------------------------------------------------------ the briefing build


async def test_the_briefing_build_events_mirror_the_stages_it_reports():
    watcher = Watcher()
    index = FakeClaimIndex(
        [ClaimStub("a1f3", "memory/topics/print.md", "恒印印刷的报价流程")]
    )
    briefing = await build_briefing(
        _USER,
        BriefingScope(query="报价", source_ids=[], budget_chars=4000),
        snapshot_docs=[],
        snapshot=_snapshot_ref(),
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        on_event=watcher,
    )
    _every_end_has_a_start(watcher)
    _mirrors_recorder_lane(watcher, briefing.stages)
    assert watcher.ends[-1].name == "total"


def _snapshot_ref():
    from pneuma_knowledge_core.domain.snapshot import SnapshotRef

    return SnapshotRef(ref="ref-stage-events")


# ------------------------------------------------------------- the agentic lanes


def _agentic_ends(watcher: Watcher) -> list[tuple[str, int]]:
    return [(e.name, e.ms or 0) for e in watcher.ends]


async def test_an_agentic_run_announces_every_step_and_its_ends_are_the_final_list():
    """The agentic rule: ends IN ORDER are `stages()`. Nothing is deduped, because in this
    lane two calls to one tool are two steps and the order is the measurement."""
    watcher = Watcher()
    timings = AgentTimings(on_event=watcher)
    tools = timed_tools([_probe("look", 40)], timings)
    await run_agent_loop(
        _model(
            AIMessage(content="", tool_calls=[_tool_call("look", {"query": "a"}, "c1")]),
            AIMessage(content="", tool_calls=[_tool_call("look", {"query": "b"}, "c2")]),
            AIMessage(content="done"),
        ),
        tools,
        system_prompt="contract",
        human="question",
        tool_budget=4,
        run_name="test.events",
        timings=timings,
    )
    _every_end_has_a_start(watcher)
    stages = timings.stages()
    assert _agentic_ends(watcher) == [(s.name, s.ms) for s in stages]
    # Two calls to one tool are two nodes, distinguishable only by key.
    tool_ends = [e for e in watcher.ends if e.name == "tool:look"]
    assert len(tool_ends) == 2
    assert tool_ends[0].key != tool_ends[1].key


async def test_a_turn_is_announced_before_it_runs_not_after_it_finished():
    """The whole point of the live face: the long wait is the model turn, so the turn has to
    be announced when it BEGINS. A `turn:1` start that only appeared with its end would show
    a waiting reader nothing during exactly the seconds being reported."""
    watcher = Watcher()
    timings = AgentTimings(on_event=watcher)
    await run_agent_loop(
        _model(AIMessage(content="done")),
        timed_tools([_probe("look", 1)], timings),
        system_prompt="contract",
        human="question",
        tool_budget=2,
        run_name="test.events",
        timings=timings,
    )
    assert watcher.events[0].name == "turn:1"
    assert watcher.events[0].phase == "start"
    assert watcher.events[0].ms is None


async def test_a_tool_that_failed_announces_the_reason_it_failed():
    watcher = Watcher()
    timings = AgentTimings(on_event=watcher)
    timings.tool("fetch_verbatim", 12.0, status="degraded", detail="no such source")
    end = watcher.ends[-1]
    assert end.status == "degraded" and end.detail == "no such source"


async def test_deep_recall_announces_its_loop_and_mirrors_the_stages_it_returns():
    watcher = Watcher()
    index = FakeClaimIndex([ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责对接")])
    answer = await deep_recall(
        _USER,
        "林薇负责什么",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_model(
            AIMessage(
                content="",
                tool_calls=[_tool_call("search_claims", {"query": "林薇"}, "c1")],
            ),
            AIMessage(content="林薇负责对接"),
        ),
        content=FakeContent(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        on_event=watcher,
    )
    _every_end_has_a_start(watcher)
    assert _agentic_ends(watcher) == [(s.name, s.ms) for s in answer.stages]
    assert [e.name for e in watcher.ends][:2] == ["turn:1", "tool:search_claims"]


async def test_a_briefing_ask_announces_its_loop_and_mirrors_the_stages_it_returns():
    from pneuma_knowledge_core.recall.briefing import Briefing

    watcher = Watcher()
    briefing = Briefing(
        user_id=_USER,
        snapshot=_snapshot_ref(),
        system_prefix="contract\npack",
        tool_names=("search_knowledge", "fetch_verbatim"),
        source_ids=(),
    )
    answer = await briefing_ask(
        briefing,
        "报价怎么走",
        as_of=_AS_OF,
        model=_model(AIMessage(content="先排期再谈价")),
        content=FakeContent(),
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        on_event=watcher,
    )
    _every_end_has_a_start(watcher)
    assert _agentic_ends(watcher) == [(s.name, s.ms) for s in answer.stages]


async def test_a_briefing_ask_streams_its_answer_text():
    from pneuma_knowledge_core.recall.briefing import Briefing

    tokens: list[str] = []
    briefing = Briefing(
        user_id=_USER,
        snapshot=_snapshot_ref(),
        system_prefix="contract\npack",
        tool_names=("search_knowledge", "fetch_verbatim"),
        source_ids=(),
    )
    answer = await briefing_ask(
        briefing,
        "报价怎么走",
        as_of=_AS_OF,
        model=_StreamingToolModel(turns=[AIMessage(content="先排期再谈价")], seen=[]),
        content=FakeContent(),
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        on_token=tokens.append,
    )
    assert len(tokens) > 1
    assert "".join(tokens) == answer.answer


# ------------------------------------------------------------------ streaming fakes


def _probe(name: str, delay_ms: float):
    from langchain_core.tools import StructuredTool

    async def probe(query: str) -> str:
        await asyncio.sleep(delay_ms / 1000.0)
        return f"{name} saw {query}"

    probe.__name__ = name
    return StructuredTool.from_function(coroutine=probe, name=name, description=name)


class _StreamingModel(_Model):
    """The fast lane's answering model, with a real streaming face.

    It hands the answer back one character at a time, which is what makes "the deltas joined
    equal the answer" a claim about the plumbing rather than about a single-chunk shortcut.
    `streamed` counts how many times anything asked it to stream, so a test can pin that the
    no-callback path never does."""

    streamed: int = 0

    async def _astream(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ARG002
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        self.streamed += 1
        await asyncio.sleep(self.delay)
        pieces = list(self.answer) or [""]
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=piece,
                    usage_metadata=(
                        {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
                        if last
                        else None
                    ),
                )
            )


class _StreamingToolModel(ScriptedToolModel):
    """The agentic lanes' scripted model, with a streaming face for its text turns.

    langgraph's `messages` stream mode carries whatever the model streams, so a model with no
    `_astream` would make the token test pass vacuously (one chunk, one delta). Splitting the
    turn into characters is what proves the deltas travelled."""

    async def _astream(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ARG002
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        text = turn.content if isinstance(turn.content, str) else ""
        pieces = list(text) or [""]
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=piece,
                    tool_calls=list(turn.tool_calls) if last and turn.tool_calls else [],
                    usage_metadata=(
                        {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
                        if last
                        else None
                    ),
                )
            )
