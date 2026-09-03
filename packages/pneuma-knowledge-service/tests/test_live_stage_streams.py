"""The live face of every answering lane: `stage` and `token` frames while it runs.

Three routes are covered here — `/recall/stream` (fast, deep and rag), `/briefings/stream`,
and `/briefings/{id}/ask/stream`. Each one is the SSE twin of a plain POST, and the claim
being pinned is the same in all of them:

**The `done` frame is the answer the plain route returns.** Not "similar to", not "a superset
of" — the same projection, asserted by calling both and comparing the payloads with only the
measured timings removed (a second run of the same lane cannot report the same milliseconds,
and pretending otherwise would be a test of the clock, not the route).

**A stage is announced while it is running.** Enforced by a handshake, never a threshold: the
fake lane emits a `start`, then blocks on an event the test only sets after it has pulled
that frame out of the generator. An implementation that buffered until the lane returned
could not satisfy both halves — it would deadlock rather than fail slowly.

The routes are invoked directly and their `body_iterator` drained, for the reason the deep
stream's own test gives: `httpx.ASGITransport` buffers the whole body, so through it a route
that streamed and one that accumulated are indistinguishable — it cannot see the only
property that matters.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from pneuma_knowledge_core.recall.stage_timing import StageEvent, StageRecorder

from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import (
    AskIn,
    BriefingBuildIn,
    RecallIn,
    ask_briefing,
    ask_briefing_stream,
    post_briefing,
    post_briefing_stream,
    recall,
    recall_stream,
)

_TIMEOUT = 5.0


# ------------------------------------------------------------------ fake lanes


@dataclass
class _FakeFastAnswer:
    """Everything `_fast_answer_out` reads. A field missing here would surface as an `error`
    frame and read like a streaming bug, so the stub carries the whole projection surface."""

    answer: str = "林薇负责采购"
    answer_text: str = "林薇负责采购"
    used_claims: tuple = ()
    used_episode_summaries: tuple = ()
    used_component_evidence: tuple = ()
    route_offered: tuple = ()
    route_chosen: tuple = ()
    route_degraded: str | None = None
    stages: tuple = ()
    used_windows: tuple = ()
    citation_handles: dict = field(default_factory=dict)
    glance_chars: int = 0
    expanded_documents: tuple = ()
    glance_degraded: str | None = None
    evidence_strategy: str = "ranked"
    evidence_selection_degraded: str | None = None
    claim_candidates: int = 0
    episode_summary_candidates: int = 0
    window_candidates: int = 0
    model_selected_claims: int = 0
    model_selected_episode_summaries: int = 0
    model_selected_windows: int = 0
    model_selected_component_items: int = 0
    answer_format: str = "text"
    answer_kind: str | None = None
    answer_format_degraded: str | None = None
    image_count: int = 0
    image_mode: str = "caption"
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 11})


@dataclass
class _FakeBriefing:
    system_prefix: str = "contract\npack"
    claims_count: int = 2
    source_count: int = 1
    char_count: int = 13
    stages: tuple = ()
    pack_manifest: tuple = ()


@dataclass
class _FakeAskAnswer:
    answer: str = "先排期再谈价"
    citations: tuple = ()
    verbatim_fetches: tuple = ()
    citation_handles: dict = field(default_factory=dict)
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 5})
    stages: tuple = ()


class _FakeStore:
    """The two briefing calls the routes make, and nothing else."""

    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.row = {
            "briefing_id": "b-live",
            "snapshot_ref": "ref-live",
            "system_prefix": "contract\npack",
            "scope": {"source_ids": []},
            "created_at": None,
            "stages": [],
        }

    async def create_briefing(  # noqa: ANN001
        self, user, briefing_id, scope, ref, prefix, stages=None, pack_manifest=None
    ):
        self.created.append((str(user), briefing_id, scope, ref, stages))

    async def get_briefing(self, user, briefing_id):  # noqa: ANN001
        return self.row if briefing_id == "b-live" else None


async def _no_snapshots(user):  # noqa: ANN001
    return []


async def _no_profile(user):  # noqa: ANN001
    raise RuntimeError("no profile provider in this test")


def _request(store: _FakeStore | None = None) -> SimpleNamespace:
    ctx = SimpleNamespace(
        canonical=SimpleNamespace(
            snapshots=_no_snapshots, list=lambda user, at=None: _empty_docs()
        ),
        user_info=SimpleNamespace(get_profile=_no_profile),
        langfuse_handler=lambda: None,
        lexical=None,
        vectors=None,
        embeddings=None,
        media=object(),
        store=store or _FakeStore(),
        get_chat_model=lambda role="default": None,
        get_reranker=lambda: None,
        settings=SimpleNamespace(
            recall_answer_style="conversational",
            recall_evidence_strategy="ranked",
            recall_all_context_chars=120_000,
            recall_answer_format="text",
            recall_claim_cap=6,
            recall_claim_candidate_cap=12,
            recall_window_cap=4,
            recall_window_candidate_cap=8,
            recall_episode_summary_cap=3,
            recall_selection_reasoning_effort="",
            recall_plan_queries=0,
            recall_rerank_candidates=0,
            recall_component_paths=False,
            recall_component_budget_chars=4000,
            answer_reasoning_effort="",
            briefing_citation_alias=False,
            llm_model="scripted:live-stage-test",
            openrouter_api_key="",
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


async def _empty_docs():
    return []


def _frame(raw: str) -> tuple[str, dict]:
    lines = raw.strip().splitlines()
    assert lines[0].startswith("event: "), raw
    assert lines[1].startswith("data: "), raw
    return lines[0][7:], json.loads(lines[1][6:])


async def _drain(response) -> list[tuple[str, dict]]:
    return [_frame(chunk) async for chunk in response.body_iterator]


def _timeless(payload: dict) -> dict:
    """The payload minus everything a clock decides. Two runs of one lane cannot report the
    same milliseconds, so comparing them raw would test the machine, not the route."""
    out = dict(payload)
    out.pop("stages", None)
    out.pop("as_of", None)
    return out


def _glance_free(monkeypatch) -> None:
    async def no_glance(ctx, user, at=None, **_kwargs):  # noqa: ANN001
        return {}

    monkeypatch.setattr(v1_module, "_glance_inputs", no_glance)


# ------------------------------------------------------------------ fast recall


async def test_a_fast_stage_reaches_the_client_while_the_lane_is_still_running(monkeypatch):
    """The complaint this whole feature answers: the timings used to arrive afterwards.

    The handshake is load-bearing. `released` is set only after the test has pulled the first
    `stage` frame out of the generator, so a route that accumulated frames until `fast_recall`
    returned would deadlock here rather than quietly pass."""
    _glance_free(monkeypatch)
    released = asyncio.Event()

    async def fake_fast_recall(*_args, on_event=None, on_token=None, **_kwargs):
        on_event(StageEvent(name="plan", phase="start", key="plan", at_ms=0))
        await asyncio.wait_for(released.wait(), _TIMEOUT)
        on_event(
            StageEvent(name="plan", phase="end", key="plan", at_ms=40, ms=40)
        )
        recorder = StageRecorder()
        recorder.record("plan", 40.0)
        return _FakeFastAnswer(stages=recorder.emit())

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    response = await recall_stream(
        "u-live", RecallIn(query="q", mode="fast"), _request()
    )
    frames = response.body_iterator

    kind, payload = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert kind == "stage"
    assert (payload["name"], payload["phase"], payload["ms"]) == ("plan", "start", None)
    assert not released.is_set()

    released.set()
    rest = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in rest][-1] == "done"
    ends = [p for k, p in rest if k == "stage" and p["phase"] == "end"]
    assert ends[-1]["name"] == "plan" and ends[-1]["ms"] == 40


async def test_the_fast_done_frame_is_the_answer_the_plain_route_returns(monkeypatch):
    _glance_free(monkeypatch)

    async def fake_fast_recall(*_args, on_event=None, on_token=None, **_kwargs):
        return _FakeFastAnswer()

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    body = RecallIn(query="q", mode="fast")
    plain = await recall("u-live", body, _request())
    streamed = await _drain(await recall_stream("u-live", body, _request()))

    assert [k for k, _ in streamed] == ["done"]
    assert _timeless(streamed[-1][1]) == _timeless(plain.model_dump())


async def test_the_fast_answer_text_streams_as_token_frames(monkeypatch):
    _glance_free(monkeypatch)

    async def fake_fast_recall(*_args, on_event=None, on_token=None, **_kwargs):
        for piece in ("林薇", "负责", "采购"):
            on_token(piece)
        return _FakeFastAnswer()

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="fast"), _request())
    )
    tokens = [p["text"] for k, p in frames if k == "token"]
    assert tokens == ["林薇", "负责", "采购"]
    assert "".join(tokens) == frames[-1][1]["answer"]


async def test_a_stage_preview_rides_the_end_frame_and_the_stages_that_land_with_done(
    monkeypatch,
):
    """A duration says a stage was slow; the preview says what it was slow AT — and it has to
    arrive while the reader is still waiting, not only in the finished breakdown.

    One recorder produces both, so the object on the live `end` frame and the one in `stages`
    are the same fact rather than two that could drift."""
    _glance_free(monkeypatch)

    async def fake_fast_recall(*_args, on_event=None, on_token=None, **_kwargs):
        recorder = StageRecorder(on_event=on_event)
        with recorder.measure("plan"):
            recorder.preview("plan", {"queries": ["林薇 职务", "林薇 采购"], "cap": 2})
        return _FakeFastAnswer(stages=recorder.emit())

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="fast"), _request())
    )
    stages = [p for k, p in frames if k == "stage"]
    assert [p["preview"] for p in stages if p["phase"] == "start"] == [None]
    live = next(p["preview"] for p in stages if p["phase"] == "end")
    assert live == {"queries": ["林薇 职务", "林薇 采购"], "cap": 2}
    done = {s["name"]: s for s in frames[-1][1]["stages"]}
    assert done["plan"]["preview"] == live
    # A stage that never ran previews nothing — "did not happen" is not an empty panel.
    assert done["answer"]["preview"] is None


async def test_a_fast_lane_that_fails_closes_with_an_error_frame(monkeypatch):
    """The status line is long gone by the time the lane runs, so a raise can only be
    narrated. A stream that ended without a terminal frame would hang the client."""
    _glance_free(monkeypatch)

    async def boom(*_args, on_event=None, on_token=None, **_kwargs):
        on_event(StageEvent(name="plan", phase="start", key="plan", at_ms=0))
        raise RuntimeError("meilisearch unreachable")

    monkeypatch.setattr(v1_module, "fast_recall", boom)
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="fast"), _request())
    )
    assert [k for k, _ in frames] == ["stage", "error"]
    assert "meilisearch unreachable" in frames[-1][1]["detail"]


async def test_the_deep_lane_now_speaks_stage_events_too(monkeypatch):
    """One event vocabulary across both lanes: deep keeps its `step` records AND gains the
    `stage` frames fast has, so a client renders one strip either way."""
    _glance_free(monkeypatch)

    async def fake_deep_recall(*_args, on_step=None, on_event=None, on_token=None, **_kwargs):
        on_event(StageEvent(name="turn:1", phase="start", key="turn:1#1", at_ms=0))
        on_step({"tool": "search_claims", "hits": 2, "ms": 40})
        on_event(
            StageEvent(name="turn:1", phase="end", key="turn:1#1", at_ms=90, ms=90)
        )
        return SimpleNamespace(
            answer="答案",
            used_claims=(),
            used_windows=(),
            stages=(),
            trail=[],
            glance_chars=0,
            read_documents=(),
            image_count=0,
            image_mode="caption",
            token_usage={"total_tokens": 3},
        )

    monkeypatch.setattr(v1_module, "deep_recall", fake_deep_recall)
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="deep"), _request())
    )
    assert [k for k, _ in frames] == ["stage", "step", "stage", "done"]
    assert frames[0][1]["key"] == frames[2][1]["key"]


async def test_an_unknown_mode_is_a_status_code_not_a_narrated_failure():
    """Everything decidable before the lane starts must be a status code: once the body is
    open the status line is already sent, and a 400 can only be described."""
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await recall_stream("u-live", RecallIn(query="q", mode="sideways"), _request())
    assert raised.value.status_code == 400


# ------------------------------------------------------------------- rag recall


def _fake_rag(hold: asyncio.Event | None = None):
    """A rag lane that measures the real vocabulary against the recorder it is handed.

    It goes through `StageRecorder.measure` rather than fabricating events, because the
    property under test is that the route's own recorder is what reaches the wire."""

    async def fake_rag_recall(*_args, stages=None, **_kwargs):
        from pneuma_knowledge_core.recall.rag import RecallHit
        from pneuma_knowledge_core.recall.stage_timing import child_name

        with stages.measure("embed"):
            if hold is not None:
                await asyncio.wait_for(hold.wait(), _TIMEOUT)
        with stages.measure("retrieve"):
            with stages.measure(child_name("lexical")):
                pass
            with stages.measure(child_name("vector")):
                pass
        with stages.measure("fuse"):
            pass
        with stages.measure("expand"):
            pass
        return [
            RecallHit(
                source_id="s-1",
                block_start=2,
                block_end=3,
                text="付款条款",
                paths=("lexical", "vector"),
                score=0.5,
            )
        ]

    return fake_rag_recall


async def test_a_rag_stage_reaches_the_client_while_the_lane_is_still_running(monkeypatch):
    """The same handshake the fast lane gets. rag has no model, so without this the reader
    of a slow Meili/Qdrant round trip is back to staring at a spinner."""
    released = asyncio.Event()
    monkeypatch.setattr(v1_module, "rag_recall", _fake_rag(released))
    response = await recall_stream("u-live", RecallIn(query="q", mode="rag"), _request())
    frames = response.body_iterator

    kind, payload = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert kind == "stage"
    assert (payload["name"], payload["phase"], payload["ms"]) == ("embed", "start", None)
    assert not released.is_set()

    released.set()
    rest = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in rest][-1] == "done"
    # The children are announced INSIDE the parent: sequential awaits, not a gather.
    order = [(p["name"], p["phase"]) for k, p in rest if k == "stage"]
    assert order[:5] == [
        ("embed", "end"),
        ("retrieve", "start"),
        ("retrieve.lexical", "start"),
        ("retrieve.lexical", "end"),
        ("retrieve.vector", "start"),
    ]


async def test_the_rag_done_frame_is_the_hit_list_the_plain_route_returns(monkeypatch):
    monkeypatch.setattr(v1_module, "rag_recall", _fake_rag())
    body = RecallIn(query="q", mode="rag")
    plain = await recall("u-live", body, _request())
    streamed = await _drain(await recall_stream("u-live", body, _request()))

    assert streamed[-1][0] == "done"
    assert _timeless(streamed[-1][1]) == _timeless(plain.model_dump())
    assert plain.mode == "rag"
    # Same vocabulary either way, and the stream's `end` events are the final list.
    names = [st["name"] for st in streamed[-1][1]["stages"]]
    assert names == [st.name for st in plain.stages]
    assert names == [
        "embed",
        "retrieve",
        "retrieve.lexical",
        "retrieve.vector",
        "fuse",
        "expand",
        "total",
    ]


async def test_the_rag_stream_never_sends_a_token_frame(monkeypatch):
    """Not omitted — absent. There is no model in this lane to write an answer."""
    monkeypatch.setattr(v1_module, "rag_recall", _fake_rag())
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="rag"), _request())
    )
    assert {k for k, _ in frames} == {"stage", "done"}


async def test_the_rag_stream_runs_on_a_keyless_deployment(monkeypatch):
    """rag reaches no model, so it is exactly as available as browsing is. A 503 here would
    take search away from a deployment that deliberately runs without a key."""
    monkeypatch.setattr(v1_module, "rag_recall", _fake_rag())
    request = _request()
    request.app.state.ctx.settings.llm_model = "openrouter:some/model"
    request.app.state.ctx.settings.openrouter_api_key = ""
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="rag"), request)
    )
    assert frames[-1][0] == "done"


async def test_a_rag_lane_that_fails_closes_with_an_error_frame(monkeypatch):
    async def boom(*_args, stages=None, **_kwargs):
        with stages.measure("embed"):
            pass
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(v1_module, "rag_recall", boom)
    frames = await _drain(
        await recall_stream("u-live", RecallIn(query="q", mode="rag"), _request())
    )
    assert [k for k, _ in frames][-1] == "error"
    assert "qdrant unreachable" in frames[-1][1]["detail"]


# ------------------------------------------------------------- the briefing build


async def test_the_build_stream_persists_the_row_before_it_says_done(monkeypatch):
    """A client that saw `done` can always read the briefing back. Writing after `done` would
    open a window where the id it was just handed does not resolve."""
    _glance_free(monkeypatch)
    store = _FakeStore()

    async def fake_build(*_args, on_event=None, **_kwargs):
        recorder = StageRecorder(("retrieve", "expand", "pack", "total"), (), on_event=on_event)
        with recorder.measure("pack"):
            pass
        return _FakeBriefing(stages=recorder.emit())

    monkeypatch.setattr(v1_module, "build_briefing", fake_build)
    frames = await _drain(
        await post_briefing_stream(
            "u-live", BriefingBuildIn(query="报价"), _request(store)
        )
    )
    kinds = [k for k, _ in frames]
    assert kinds[-1] == "done"
    assert "stage" in kinds
    assert store.created and store.created[0][1] == frames[-1][1]["briefing_id"]


async def test_the_build_done_frame_is_what_the_plain_build_returns(monkeypatch):
    _glance_free(monkeypatch)

    async def fake_build(*_args, on_event=None, **_kwargs):
        return _FakeBriefing()

    monkeypatch.setattr(v1_module, "build_briefing", fake_build)
    body = BriefingBuildIn(query="报价")
    plain = await post_briefing("u-live", body, _request())
    streamed = await _drain(await post_briefing_stream("u-live", body, _request()))

    done = streamed[-1][1]
    # briefing_id is a fresh uuid per build, so it is the one field that cannot match.
    assert _timeless({**done, "briefing_id": ""}) == _timeless(
        {**plain.model_dump(), "briefing_id": ""}
    )


# --------------------------------------------------------------- the briefing ask


async def test_the_ask_stream_narrates_turns_and_tokens_then_answers(monkeypatch):
    async def fake_ask(*_args, on_event=None, on_token=None, **_kwargs):
        on_event(StageEvent(name="turn:1", phase="start", key="turn:1#1", at_ms=0))
        on_token("先排期")
        on_token("再谈价")
        on_event(StageEvent(name="turn:1", phase="end", key="turn:1#1", at_ms=70, ms=70))
        return _FakeAskAnswer()

    monkeypatch.setattr(v1_module, "briefing_ask", fake_ask)
    frames = await _drain(
        await ask_briefing_stream(
            "u-live", "b-live", AskIn(question="报价怎么走"), _request()
        )
    )
    assert [k for k, _ in frames] == ["stage", "token", "token", "stage", "done"]
    assert "".join(p["text"] for k, p in frames if k == "token") == frames[-1][1]["answer"]


async def test_the_ask_done_frame_is_the_answer_the_plain_ask_returns(monkeypatch):
    async def fake_ask(*_args, on_event=None, on_token=None, **_kwargs):
        return _FakeAskAnswer()

    monkeypatch.setattr(v1_module, "briefing_ask", fake_ask)
    body = AskIn(question="报价怎么走")
    plain = await ask_briefing("u-live", "b-live", body, _request())
    streamed = await _drain(
        await ask_briefing_stream("u-live", "b-live", body, _request())
    )
    assert _timeless(streamed[-1][1]) == _timeless(plain.model_dump())


async def test_an_unknown_briefing_is_a_404_before_the_stream_opens():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await ask_briefing_stream(
            "u-live", "b-missing", AskIn(question="q"), _request()
        )
    assert raised.value.status_code == 404
