"""`POST /v1/users/{id}/live-context/stream` — the one-shot SSE endpoint.

Tested the same way `test_recall_stream.py` tests its sibling, and for the same reason:
**the route is invoked directly and its `body_iterator` is drained**, never driven through
`httpx.ASGITransport`. ASGITransport buffers the entire response body before handing it
back, so through it an endpoint that streams frame by frame and one that accumulates
everything and flushes at the end are indistinguishable — it cannot observe the only
property this endpoint has.

`run_evaluation` is monkeypatched throughout. The subject is the streaming machinery —
frame shapes, terminal events, producer cleanup — not the suggestion evaluation, which
`packages/pneuma-knowledge-core/tests/test_live_context.py` covers against fake ports.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.suggestion import ResolvedSuggestion
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.live_pipeline import PipelineResult
from pneuma_knowledge_service.api.routes import live_context as suggestion_module
from pneuma_knowledge_service.api.routes.live_context import LiveContextStreamIn, live_context_stream
from fastapi import HTTPException

_TIMEOUT = 5.0
SRC = "11111111-1111-1111-1111-111111111111"


def resolved(title: str, confidence: int = 9) -> ResolvedSuggestion:
    return ResolvedSuggestion(
        kind="concept",
        title=title,
        body="解释",
        trigger="触发",
        confidence=confidence,
        citations=[Citation(source_id=SourceId(SRC), block_start=3, block_end=5)],
    )


def _result(*suggestions: ResolvedSuggestion) -> PipelineResult:
    return PipelineResult(
        suggestions=tuple(suggestions),
        token_usage={"total_tokens": 21},
        dropped={"unparsed": 0, "repeat": 0, "uncited": 1, "low_confidence": 0, "capped": 0},
    )


async def _no_profile(ctx, user):  # noqa: ANN001
    return None


def _request() -> SimpleNamespace:
    ctx = SimpleNamespace(store=None, get_chat_model=lambda role="default": None)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


def _frame(raw: str) -> tuple[str, dict]:
    lines = raw.strip().splitlines()
    assert lines[0].startswith("event: "), raw
    assert lines[1].startswith("data: "), raw
    # Exactly one event per yielded chunk. A generator that accumulated frames and flushed
    # them together would put several `event:` lines in one chunk and fail here.
    assert len(lines) == 2, raw
    return lines[0][7:], json.loads(lines[1][6:])


async def _start(**kwargs):
    body = LiveContextStreamIn(turns=[{"text": "我们在聊 RAG", "role": "owner"}], **kwargs)
    response = await live_context_stream("u-suggestion", body, _request())
    assert response.media_type == "text/event-stream"
    # nginx buffers proxied responses by default; this header is what turns that off.
    assert response.headers["x-accel-buffering"] == "no"
    return response, response.body_iterator


@pytest.fixture(autouse=True)
def _patch_profile(monkeypatch):
    monkeypatch.setattr(suggestion_module, "_render_profile", _no_profile)


async def test_the_response_is_returned_while_the_evaluation_is_still_running(monkeypatch):
    """The handshake: the route hands back a response BEFORE the evaluation finishes.

    The fake blocks on `released`, which the test sets only after it already holds the
    response object. An implementation that awaited the evaluation before constructing the
    StreamingResponse could not satisfy both halves — it would deadlock here rather than
    fail on a timing threshold."""
    entered = asyncio.Event()
    released = asyncio.Event()

    async def fake(*_args, **_kwargs):
        entered.set()
        await asyncio.wait_for(released.wait(), _TIMEOUT)
        return _result(resolved("RAG"), resolved("HNSW"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake)
    _response, frames = await _start()

    await asyncio.wait_for(entered.wait(), _TIMEOUT)
    assert not released.is_set()  # load-bearing: we have the response, it has not returned
    released.set()

    # Pulled ONE AT A TIME: each `__anext__` must yield exactly one complete SSE frame
    # (enforced inside `_frame`), so cards are not batched into a single flush.
    first = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert first == ("suggestion", first[1])
    assert first[1]["title"] == "RAG"
    assert first[1]["citations"] == [
        {"source_id": SRC, "block_start": 3, "block_end": 5}
    ]

    rest = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in rest] == ["suggestion", "done"]
    assert rest[0][1]["title"] == "HNSW"
    done = rest[-1][1]
    assert done["count"] == 2
    assert done["token_usage"] == {"total_tokens": 21}
    assert done["dropped"]["uncited"] == 1  # gate accounting reaches the client


async def test_silence_streams_a_done_event_and_nothing_else(monkeypatch):
    """Zero suggestions is the steady state, not an error: the stream must terminate cleanly with
    a `done` carrying count 0 rather than hanging or erroring."""

    async def fake(*_args, **_kwargs):
        return _result()

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake)
    _response, frames = await _start()
    collected = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in collected] == ["done"]
    assert collected[0][1]["count"] == 0


async def test_failure_surfaces_as_a_terminal_error_event(monkeypatch):
    """The status line is already on the wire by the time the evaluation runs, so a raise
    cannot become an HTTP error — it has to arrive as a terminal `error` frame or the
    client waits forever."""

    async def boom(*_args, **_kwargs):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(suggestion_module, "run_evaluation", boom)
    _response, frames = await _start()
    collected = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in collected] == ["error"]
    assert "qdrant unreachable" in collected[0][1]["detail"]


async def test_client_disconnect_cancels_the_producer(monkeypatch):
    """A client that walks away mid-stream must not leave an evaluation running: without
    the generator's `finally: task.cancel()` every abandoned stream leaks a task that keeps
    burning LLM calls with nobody left to read the answer."""
    cancelled = asyncio.Event()

    async def slow(*_args, **_kwargs):
        try:
            await asyncio.sleep(600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _result()  # pragma: no cover - the sleep never completes

    monkeypatch.setattr(suggestion_module, "run_evaluation", slow)
    _response, frames = await _start()

    # The client is waiting on the first frame (the generator is suspended on the queue),
    # then goes away. Cancelling the pending read is what a dropped connection looks like
    # from in here — it unwinds the generator through its `finally`.
    pending = asyncio.create_task(frames.__anext__())
    await asyncio.sleep(0.01)
    pending.cancel()

    await asyncio.wait_for(cancelled.wait(), _TIMEOUT)


async def test_an_unknown_focus_is_a_400_not_a_silent_default(monkeypatch):
    """The vocabulary is closed. Falling back to `general` would suggestion under an attention
    direction the caller did not ask for and never tell them."""

    async def never(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("evaluation ran despite an invalid focus")

    monkeypatch.setattr(suggestion_module, "run_evaluation", never)
    with pytest.raises(HTTPException) as exc:
        await _start(focus="everyone")
    assert exc.value.status_code == 400
    assert "unknown suggestion focus" in exc.value.detail


async def test_the_briefing_pack_is_loaded_and_passed_as_the_evidence(monkeypatch):
    """briefing scope = zero retrieval: the frozen pack IS the evidence, so the route must
    resolve it and hand it to the engine rather than letting retrieval run."""
    seen: dict = {}

    async def fake_pack(_ctx, _user, briefing_id):  # noqa: ANN001
        seen["briefing_id"] = briefing_id
        return "# 冻结知识包"

    async def fake(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        seen["pack"] = kwargs.get("pack")
        return _result()

    monkeypatch.setattr(suggestion_module, "load_briefing_pack", fake_pack)
    monkeypatch.setattr(suggestion_module, "run_evaluation", fake)
    _response, frames = await _start(briefing_id="bf-7")
    [_frame(chunk) async for chunk in frames]

    assert seen == {"briefing_id": "bf-7", "pack": "# 冻结知识包"}


# ───────────────────────────── the glance short-circuit on the one-shot stream
#
# SSE has one event stream and no seq to upgrade into, so the provisional card goes on it
# the moment it exists — and the `done` event this stream always ends with is what settles
# it: `glance.outcome` says which ending happened.


async def test_the_provisional_card_streams_before_the_evaluation_returns(monkeypatch):
    """The whole claim of the mechanism is WHEN it lands, and this endpoint's own subject is
    streaming — so the two are asserted together: the card is pulled off the stream while
    the evaluation is still blocked."""
    released = asyncio.Event()

    async def fake(*_args, **kwargs):
        await kwargs["on_glance"](
            ResolvedSuggestion(
                kind="glance",
                title="Lumenlab",
                body="Lumenlab 是企业异构数据的记忆基础设施。",
                trigger="触发",
                confidence=10,
                citations=[Citation(source_id=SourceId(SRC), block_start=4, block_end=5)],
                subject="projects/lumenlab.md",
                subject_label="lumenlab",
                provisional=True,
            )
        )
        await asyncio.wait_for(released.wait(), _TIMEOUT)
        return PipelineResult(
            token_usage={"total_tokens": 4},
            glance_state="hit",
            glance_outcome="alone",
            glance_ms=37.0,
        )

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake)
    _response, frames = await _start()

    kind, card = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert kind == "suggestion"
    assert (card["kind"], card["provisional"]) == ("glance", True)
    assert card["citations"] == [{"source_id": SRC, "block_start": 4, "block_end": 5}]
    assert not released.is_set(), "delivered before the pipeline behind it finished"

    released.set()
    rest = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in rest] == ["done"]
    done = rest[-1][1]
    assert done["glance"] == {"state": "hit", "outcome": "alone", "ms": 37.0}
    assert done["count"] == 0, "the glance is not one of the settled suggestions"


async def test_a_tick_that_did_not_glance_says_so_on_the_done_event(monkeypatch):
    async def fake(*_args, **_kwargs):
        return _result(resolved("RAG"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake)
    _response, frames = await _start()
    frames_seen = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in frames_seen] == ["suggestion", "done"]
    assert frames_seen[0][1]["provisional"] is False
    assert frames_seen[-1][1]["glance"] == {"state": "miss", "outcome": "", "ms": 0.0}
