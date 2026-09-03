"""Coverage for `/v1/users/{id}/recall/stream` — the SSE deep-recall endpoint.

This endpoint had no automated test, which made it the riskiest thing the async migration
touched: it is the one route whose whole value is *timing* (steps must reach the UI while
the agentic loop is still running), and timing is exactly what a request/response test
cannot see. Its previous implementation was a worker thread plus a `queue.Queue`; it is now
a sibling `asyncio.Task` plus an `asyncio.Queue`.

Two deliberate choices about how this is tested:

**The route is invoked directly and its `body_iterator` is drained**, rather than going
through `httpx.ASGITransport`. ASGITransport buffers the entire response body before
returning it, so through that client an endpoint that streamed incrementally and one that
accumulated everything and flushed at the end are indistinguishable — it cannot observe the
only property that matters here. Incremental yielding lives in the generator, so the
generator is what gets driven.

**`deep_recall` is monkeypatched.** The subject is the endpoint's streaming machinery —
incremental delivery, wire format, terminal events, producer cleanup — not the recall,
which `packages/pneuma-knowledge-core/tests/test_deep_recall.py` covers against fake ports.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from pneuma_knowledge_core.recall.agentic import AgentTimings

from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import RecallIn, recall_stream

# Every await that could otherwise hang is wrapped in this. A generator that accumulated
# instead of yielding incrementally would deadlock the handshake below; failing on a
# timeout is a diagnosis, hanging forever is not.
_TIMEOUT = 5.0


@dataclass
class _FakeDeepAnswer:
    answer: str = "答案"
    used_claims: tuple = ()
    used_windows: tuple = ()
    trail: list = field(default_factory=list)
    # The glance fields the deep lane now returns: this stub carries them because the route
    # projects them into the `done` frame, and a stub missing a field the route reads would
    # fail as an "error" event and look like a streaming bug.
    glance_chars: int = 0
    read_documents: tuple = ()
    image_count: int = 0
    image_mode: str = "caption"
    # The agentic loop's per-step wall-clock (core `recall/agentic.py`), projected into the
    # closing `done` frame the same way the non-streaming route projects it.
    stages: tuple = ()
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 7})


async def _no_snapshots(user):  # noqa: ANN001
    return []


async def _no_documents(user, *, at=None):  # noqa: ANN001
    """An EMPTY library, and it has to be readable: since the archive pin, a canonical read
    that fails refuses the lane (`v1.CanonicalUnavailable` → 503) rather than degrading, so a
    stub that could not answer `list` would be testing the refusal instead of the lane."""
    return []


async def _no_profile(user):  # noqa: ANN001
    # `_render_profile` swallows any exception and drops the block, so raising here
    # exercises the same path a real profile-less user takes.
    raise RuntimeError("no profile provider in this test")


def _request() -> SimpleNamespace:
    """The only thing the route wants from a Request is `.app.state.ctx` (see `_ctx`)."""
    ctx = SimpleNamespace(
        canonical=SimpleNamespace(snapshots=_no_snapshots, list=_no_documents),
        user_info=SimpleNamespace(get_profile=_no_profile),
        langfuse_handler=lambda: None,
        lexical=None,
        vectors=None,
        embeddings=None,
        media=object(),
        store=None,
        get_chat_model=lambda role="default": None,
        # `scripted:` is the keyless deterministic spec: it satisfies the route's
        # answering-model preflight (a keyless deployment is a 503 BEFORE the body opens,
        # never a stream that narrates its own impossibility) without wiring a provider.
        settings=SimpleNamespace(
            recall_answer_style="conversational",
            llm_model="scripted:stream-test",
            openrouter_api_key="",
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


def _frame(raw: str) -> tuple[str, dict]:
    """One SSE frame `event: X\\ndata: {...}\\n\\n` -> (event, payload)."""
    lines = raw.strip().splitlines()
    assert lines[0].startswith("event: "), raw
    assert lines[1].startswith("data: "), raw
    return lines[0][7:], json.loads(lines[1][6:])


async def _start(query: str = "q", original_modalities: tuple[str, ...] = ()):
    """Invoke the route and hand back its response plus a fresh frame iterator."""
    response = await recall_stream(
        "u-sse",
        RecallIn(
            query=query,
            mode="deep",
            include_original_modalities=list(original_modalities),
        ),
        _request(),
    )
    assert response.media_type == "text/event-stream"
    # nginx buffers proxied responses by default, which would hold every step until the
    # run finished — the header is what disables it (docker/nginx.conf relies on this too).
    assert response.headers["x-accel-buffering"] == "no"
    return response, response.body_iterator


async def test_steps_are_delivered_before_the_recall_finishes(monkeypatch):
    """The property the endpoint exists for: a step reaches the client while the agentic
    loop is still running.

    Enforced with a handshake, not a timing threshold. The fake emits one step and then
    blocks on `released`, which the test sets only after it has actually pulled that step
    out of the generator. An implementation that accumulated frames until the handler
    returned could not satisfy both halves — it would deadlock."""
    released = asyncio.Event()

    async def fake_deep_recall(*_args, on_step=None, **_kwargs):
        on_step({"tool": "search_claims", "n": 1})
        await asyncio.wait_for(released.wait(), _TIMEOUT)
        on_step({"tool": "fetch_verbatim", "n": 2})
        return _FakeDeepAnswer()

    monkeypatch.setattr(v1_module, "deep_recall", fake_deep_recall)
    _response, frames = await _start()

    # Load-bearing: this resolves only if the first step was yielded while
    # `fake_deep_recall` was still suspended on `released`.
    kind, payload = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert (kind, payload) == ("step", {"tool": "search_claims", "n": 1})
    assert not released.is_set()

    released.set()
    rest = [_frame(chunk) async for chunk in frames]

    assert [k for k, _ in rest] == ["step", "done"]
    assert rest[0][1] == {"tool": "fetch_verbatim", "n": 2}
    done = rest[-1][1]
    assert done["mode"] == "deep"
    assert done["answer"] == "答案"
    assert done["token_usage"] == {"total_tokens": 7}


async def test_original_modality_choice_reaches_streaming_deep_recall(monkeypatch):
    seen: dict = {}

    async def fake_deep_recall(*_args, **kwargs):
        seen.update(kwargs)
        return _FakeDeepAnswer(image_count=1, image_mode=kwargs["image_mode"])

    monkeypatch.setattr(v1_module, "deep_recall", fake_deep_recall)
    _response, frames = await _start(original_modalities=("image",))
    messages = [_frame(chunk) async for chunk in frames]

    assert seen["image_mode"] == "native"
    assert seen["media"] is not None
    done = messages[-1][1]
    assert done["included_original_modalities"] == ["image"]
    assert done["original_modality_counts"] == {"image": 1}


async def test_failure_surfaces_as_a_terminal_error_event(monkeypatch):
    """The status line is already sent by the time recall runs, so a raise cannot become an
    HTTP error — it has to arrive as a terminal `error` frame or the client hangs."""

    async def boom(*_args, on_step=None, **_kwargs):
        on_step({"tool": "search_claims"})
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(v1_module, "deep_recall", boom)
    _response, frames = await _start()

    collected = [_frame(chunk) async for chunk in frames]
    assert [k for k, _ in collected] == ["step", "error"]
    assert "qdrant unreachable" in collected[-1][1]["detail"]


async def test_client_disconnect_cancels_the_producer(monkeypatch):
    """A client that walks away mid-stream must not leave the recall running.

    Without the generator's `finally: task.cancel()`, every abandoned stream would leak a
    task that keeps burning LLM calls with nobody left to read the answer."""
    cancelled = asyncio.Event()

    async def slow(*_args, on_step=None, **_kwargs):
        on_step({"tool": "search_claims"})
        try:
            await asyncio.sleep(_TIMEOUT)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _FakeDeepAnswer()

    monkeypatch.setattr(v1_module, "deep_recall", slow)
    _response, frames = await _start()

    kind, _ = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert kind == "step"
    await frames.aclose()  # the client walks away

    await asyncio.wait_for(cancelled.wait(), _TIMEOUT)


async def test_each_step_carries_its_own_ms_and_done_carries_the_whole_breakdown(monkeypatch):
    """Two readings of the same run, and both have to arrive.

    A step is rendered LIVE, long before any breakdown exists, so its duration has to ride the
    step itself — core stamps it on the trail record before appending (recall/deep.py), and
    the route forwards the record untouched. The closing `done` then carries the whole ordered
    interleaving, including the turns the steps sat between, which no sequence of step frames
    could tell a client on its own."""
    timings = AgentTimings()
    timings.turn(1200)
    timings.tool("search_claims", 340)
    timings.turn(900)
    timings.close(2440)

    async def fake_deep_recall(*_args, on_step=None, **_kwargs):
        on_step({"tool": "search_claims", "query": "q", "hits": 2, "ms": 340})
        return _FakeDeepAnswer(stages=timings.stages())

    monkeypatch.setattr(v1_module, "deep_recall", fake_deep_recall)
    _response, frames = await _start()
    collected = [_frame(chunk) async for chunk in frames]

    assert [k for k, _ in collected] == ["step", "done"]
    assert collected[0][1]["ms"] == 340
    done = collected[-1][1]
    assert [s["name"] for s in done["stages"]] == [
        "turn:1",
        "tool:search_claims",
        "turn:2",
        "total",
    ]
    by_name = {s["name"]: s for s in done["stages"]}
    assert by_name["tool:search_claims"]["ms"] == collected[0][1]["ms"]
    assert all(by_name["total"]["ms"] >= s["ms"] for s in done["stages"])
