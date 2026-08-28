"""Per-stage timing on the wire, for both answering lanes.

Core measures it (`recall/stage_timing.py` for fast, `recall/agentic.py` for deep); the only
thing the service adds is a faithful echo. So what is pinned here is exactly that: the whole
fixed vocabulary survives the response model in order, a skipped stage stays a skipped stage
rather than collapsing into "0 ms", a degraded stage keeps the lane's own reason — and deep's
own vocabulary (`turn:N` / `tool:<name>` / `finalize`, `total` last) reaches the wire in the
order the run took, with each `trail` step carrying the `ms` its stage reports.
"""

from __future__ import annotations

import json

from pneuma_knowledge_core.recall.agentic import AgentTimings
from pneuma_knowledge_core.recall.fast import FastAnswer
from pneuma_knowledge_core.recall.stage_timing import (
    RETRIEVE_CHILDREN,
    STAGE_ORDER,
    StageRecorder,
    child_name,
)

from pneuma_knowledge_service.api.routes.v1 import RecallAnswerOut, _stage_timing_out


def _answer_with_stages() -> FastAnswer:
    recorder = StageRecorder()
    recorder.record("retrieve", 812.4)
    recorder.record(child_name("claims"), 640.2)
    recorder.record_path("person", 121.7)
    recorder.record("route", 210.0)
    recorder.record("rerank", 90.0)
    recorder.degrade("rerank", "timeout")
    recorder.record("assemble", 31.0)
    recorder.record("answer", 3120.6)
    recorder.record("total", 4001.9)
    return FastAnswer(
        answer="A", answer_text="A", used_claims=(), token_usage={}, stages=recorder.emit()
    )


def _out() -> RecallAnswerOut:
    fa = _answer_with_stages()
    return RecallAnswerOut(
        mode="fast",
        answer=fa.answer,
        answer_text=fa.answer_text,
        as_of="2026-08-26T00:00:00+00:00",
        used_claims=[],
        token_usage={},
        stages=[_stage_timing_out(s) for s in fa.stages],
    )


def test_the_whole_vocabulary_reaches_the_wire_in_order():
    payload = json.loads(_out().model_dump_json())
    assert [s["name"] for s in payload["stages"]] == [
        "plan",
        "retrieve",
        *(child_name(c) for c in RETRIEVE_CHILDREN),
        child_name("path:person"),
        "route",
        "rerank",
        "select",
        "assemble",
        "answer",
        "total",
    ]
    assert len(payload["stages"]) == len(STAGE_ORDER) + len(RETRIEVE_CHILDREN) + 1


def test_a_stage_that_did_not_run_stays_distinguishable_from_one_that_was_free():
    by_name = {s["name"]: s for s in json.loads(_out().model_dump_json())["stages"]}
    assert by_name["plan"] == {
        "name": "plan",
        "ms": 0,
        "status": "skipped",
        "detail": None,
        "preview": None,
    }
    assert by_name["select"]["status"] == "skipped"
    assert by_name[child_name("windows")]["status"] == "skipped"
    assert by_name["retrieve"] == {
        "name": "retrieve",
        "ms": 812,
        "status": "ran",
        "detail": None,
        "preview": None,
    }


def test_a_degraded_stage_carries_the_lanes_own_reason_and_the_time_it_cost():
    by_name = {s["name"]: s for s in json.loads(_out().model_dump_json())["stages"]}
    assert by_name["rerank"] == {
        "name": "rerank",
        "ms": 90,
        "status": "degraded",
        "detail": "timeout",
        "preview": None,
    }


def test_a_routed_paths_child_reports_its_own_duration_under_retrieve():
    by_name = {s["name"]: s for s in json.loads(_out().model_dump_json())["stages"]}
    child = by_name[child_name("path:person")]
    assert child["ms"] == 122 and child["status"] == "ran"
    # Children are their own clocks, so they may exceed nothing in particular — but `total`
    # wraps the lane and bounds them all.
    assert all(by_name["total"]["ms"] >= s["ms"] for s in by_name.values())


def _deep_out() -> RecallAnswerOut:
    """A deep answer the way the route builds one: core's agentic timings echoed as-is."""
    timings = AgentTimings()
    timings.turn(1200)
    timings.tool("search_claims", 340)
    timings.tool("fetch_verbatim", 12, status="degraded", detail="'src-gone'")
    timings.turn(900)
    timings.finalize(1100)
    timings.close(3560)
    return RecallAnswerOut(
        mode="deep",
        answer="A",
        answer_text="A",
        as_of="2026-08-26T00:00:00+00:00",
        used_claims=[],
        token_usage={},
        stages=[_stage_timing_out(s) for s in timings.stages()],
        trail=[
            {"tool": "search_claims", "query": "q", "hits": 2, "ms": 340},
            {"tool": "fetch_verbatim", "source_id": "src-gone", "error": "'src-gone'", "ms": 12},
        ],
    )


def test_the_deep_lane_now_carries_its_measured_stages_too():
    """This test used to pin deep's `stages` to `[]`.

    That WAS the honest answer while the lane measured nothing: an empty list said "not
    reported", and a fabricated one would have said something false. The lane now measures the
    agentic loop for real (`recall/agentic.py`), so the honest answer changed with it — the
    wire carries the run's own sequence, in the order it happened, and an empty list would now
    be the lie. What has not changed is that nothing is invented: no fixed vocabulary is
    padded in, because an agentic run has no list of stages that could have run."""
    payload = json.loads(_deep_out().model_dump_json())
    assert [s["name"] for s in payload["stages"]] == [
        "turn:1",
        "tool:search_claims",
        "tool:fetch_verbatim",
        "turn:2",
        "finalize",
        "total",
    ]
    by_name = {s["name"]: s for s in payload["stages"]}
    # Deep never sends `skipped`: every stage on the list is one the run actually took.
    assert not any(s["status"] == "skipped" for s in payload["stages"])
    assert by_name["tool:fetch_verbatim"]["status"] == "degraded"
    assert by_name["tool:fetch_verbatim"]["detail"] == "'src-gone'"
    # The forced finalize names why it exists at all.
    assert by_name["finalize"]["status"] == "degraded" and by_name["finalize"]["detail"] == "budget"
    assert all(by_name["total"]["ms"] >= s["ms"] for s in payload["stages"])


def test_a_deep_trail_step_carries_the_same_ms_its_stage_reports():
    """The trail is what a client renders LIVE, one step at a time, before any `stages` list
    exists. So the duration has to be on the step itself — and it has to be the same number
    the closing breakdown reports for that call, or the two readings disagree."""
    payload = json.loads(_deep_out().model_dump_json())
    by_name = {s["name"]: s for s in payload["stages"]}
    for step in payload["trail"]:
        assert step["ms"] == by_name[f"tool:{step['tool']}"]["ms"]
