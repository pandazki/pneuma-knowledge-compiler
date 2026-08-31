"""The supplementary internet path: the adapter, and the two answers that gate it.

Keyless and offline throughout. The adapter is exercised against a FAKE SSE server — an
`httpx.MockTransport` speaking the Responses stream the reference implementation reads,
annotations and usage included — because the real endpoint charges per call and a test that
could reach it would eventually reach it by accident.

The other half is the clamp: a client asks for the internet path and the DEPLOYMENT answers.
Both transports run the request through one function, and the `ready` frame echoes what was
granted rather than what was asked, so a client that was told no has been told mechanically.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pneuma_knowledge_core.domain.suggestion import ResolvedSuggestion, WebCitation
from pneuma_knowledge_core.recall.live_pipeline import PipelineResult

from pneuma_knowledge_service.adapters.openrouter_web_search import (
    OpenRouterWebSearch,
    _answer_from,
)
from pneuma_knowledge_service.api.routes import live_context as live_module

PATH = "/v1/users/u-web/live-context/ws"


# --------------------------------------------------------------- the fake SSE server


def sse(*events: dict) -> bytes:
    """The Responses stream as bytes, exactly the framing the reference reads."""
    lines = [f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


COMPLETED = {
    "type": "response.completed",
    "response": {
        "id": "resp_test",
        "output": [
            {
                "content": [
                    {
                        "text": "DeepSeek harness 是 2026-08-24 发布的开源评测运行器。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "Release notes",
                                "url": "https://example.test/dsh",
                            },
                            {
                                "type": "url_citation",
                                "title": "Release notes (again)",
                                "url": "https://example.test/dsh",
                            },
                            {"type": "file_citation", "url": "https://example.test/ignored"},
                        ],
                    }
                ]
            }
        ],
        "usage": {"cost": 0.0141, "server_tool_use_details": {"web_search_requests": 2}},
    },
}

DELTAS = (
    {"type": "response.output_text.delta", "delta": "DeepSeek "},
    {"type": "response.output_text.delta", "delta": "harness…"},
)


def transport(*events: dict, seen: list | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(
            200, content=sse(*events), headers={"content-type": "text/event-stream"}
        )

    return httpx.MockTransport(handle)


def adapter(*events: dict, seen: list | None = None) -> OpenRouterWebSearch:
    return OpenRouterWebSearch(
        "test-key", "openai/gpt-5.6-luna", transport=transport(*events, seen=seen)
    )


# ------------------------------------------------------------------------ the adapter


async def test_the_adapter_reads_the_answer_the_urls_the_searches_and_the_cost():
    seen: list = []
    search = adapter(*DELTAS, COMPLETED, seen=seen)
    try:
        answer = await search.search("DeepSeek harness", max_results=3)
    finally:
        await search.aclose()

    assert answer.text == "DeepSeek harness 是 2026-08-24 发布的开源评测运行器。"
    # De-duplicated by URL, and a citation that is not a `url_citation` is not one.
    assert [(c.title, c.url) for c in answer.citations] == [
        ("Release notes", "https://example.test/dsh")
    ]
    assert answer.searches == 2
    assert answer.cost == pytest.approx(0.0141)

    (payload,) = seen
    assert payload["provider"] == {
        "only": ["openai"],
        "ignore": ["openai/flex", "openai/fast"],
        "allow_fallbacks": False,
    }, "the provider pin is what stops a silent fall-back to a reseller with no native search"
    assert payload["tools"] == [
        {"type": "openrouter:web_search", "parameters": {"engine": "native"}}
    ]
    assert payload["stream"] is True and payload["max_tool_calls"] == 3
    assert "DeepSeek harness" in payload["input"]


async def test_a_stream_that_never_completes_is_an_error_that_says_not_to_retry():
    """The charge has already been incurred, whichever way the stream ended.

    So the failure names itself as one nobody should paper over with a retry — and there is
    no retry in the adapter to find. The lane treats this as a degraded face."""
    search = adapter(*DELTAS)
    try:
        with pytest.raises(RuntimeError, match="do not retry"):
            await search.search("q")
    finally:
        await search.aclose()


async def test_an_error_frame_ends_the_search_rather_than_producing_a_bare_answer():
    search = adapter({"type": "response.failed", "error": {"message": "provider down"}})
    try:
        with pytest.raises(RuntimeError, match="web search failed"):
            await search.search("q")
    finally:
        await search.aclose()


def test_availability_needs_both_a_key_and_a_model():
    assert not OpenRouterWebSearch("", "openai/gpt-5.6-luna").available()
    assert not OpenRouterWebSearch("k", "").available()
    assert OpenRouterWebSearch("k", "openai/gpt-5.6-luna").available()


def test_an_answer_with_no_page_still_parses_and_is_refused_later_by_core():
    """The adapter reports what came back; admitting it is core's decision.

    Splitting it that way keeps one place where a candidate is admitted — the same place
    every library candidate is admitted — instead of two gates that could disagree."""
    parsed = _answer_from({"output": [{"content": [{"text": "probably"}]}], "usage": {}})
    assert parsed.text == "probably" and parsed.citations == ()


# ----------------------------------------------------------------------- the clamp


class FakeSettings:
    def __init__(self, on: bool) -> None:
        self.live_web_search = on


class FakeCtx:
    def __init__(self, on: bool) -> None:
        self.settings = FakeSettings(on)


async def _no_profile(ctx, user):  # noqa: ANN001
    return None


@pytest.fixture
def client_factory(monkeypatch):
    monkeypatch.setattr(live_module, "_render_profile", _no_profile)

    def build(*, enabled: bool) -> TestClient:
        app = FastAPI()
        app.include_router(live_module.router)
        app.include_router(live_module.root_router)
        app.state.ctx = FakeCtx(enabled)
        return TestClient(app)

    return build


def test_the_ready_frame_echoes_what_was_granted_not_what_was_asked(client_factory):
    """Asking is not granting, and the client is told so in the field it asked in."""
    with client_factory(enabled=False).websocket_connect(PATH) as ws:
        assert ws.receive_json()["web_search"] is False
        ws.send_json({"type": "config", "web_search": True})
        assert ws.receive_json()["web_search"] is False, "the deployment said no"

    with client_factory(enabled=True).websocket_connect(PATH) as ws:
        assert ws.receive_json()["web_search"] is False, "off until a client asks"
        ws.send_json({"type": "config", "web_search": True})
        assert ws.receive_json()["web_search"] is True
        ws.send_json({"type": "config", "web_search": False})
        assert ws.receive_json()["web_search"] is False, "and the client can take it back"


def test_the_granted_toggle_is_what_reaches_the_evaluation_plan(client_factory, monkeypatch):
    """The plan is what the engine reads to decide whether to hand core a search at all."""
    plans: list = []

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        plans.append(plan.web_search)
        return PipelineResult(token_usage={}, skipped="small_talk")

    monkeypatch.setattr(live_module, "run_evaluation", fake_eval)

    with client_factory(enabled=True).websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "web_search": True, "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json({"type": "turn", "speaker": "me", "text": "DeepSeek harness?", "role": "owner"})
        assert ws.receive_json()["type"] == "stats"

    with client_factory(enabled=False).websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "web_search": True, "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json({"type": "turn", "speaker": "me", "text": "DeepSeek harness?", "role": "owner"})
        assert ws.receive_json()["type"] == "stats"

    assert plans == [True, False]


def test_the_one_shot_transport_clamps_the_same_way(client_factory, monkeypatch):
    plans: list = []

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        plans.append(plan.web_search)
        return PipelineResult(token_usage={}, skipped="small_talk")

    monkeypatch.setattr(live_module, "run_evaluation", fake_eval)
    body = {
        "turns": [{"speaker": "me", "text": "DeepSeek harness?", "role": "owner"}],
        "web_search": True,
    }
    for enabled in (True, False):
        response = client_factory(enabled=enabled).post(
            "/v1/users/u-web/live-context/stream", json=body
        )
        assert response.status_code == 200
        assert "event: done" in response.text
    assert plans == [True, False]


def test_a_web_card_reaches_the_client_with_its_pages_and_no_source_spans(
    client_factory, monkeypatch
):
    """Core pins the substance; this pins the WIRE.

    Both citation fields are always present as lists, so a client tests a field rather than
    sniffing for one — and a web card fills exactly one of them."""

    async def fake_eval(_ctx, _user, _plan, **kwargs):  # noqa: ANN001
        return PipelineResult(
            suggestions=(
                ResolvedSuggestion(
                    kind="web",
                    title="DeepSeek harness",
                    body="It shipped last week.",
                    trigger="what is the DeepSeek harness",
                    confidence=9,
                    evidence="An open evaluation runner released on 2026-08-24.",
                    web_citations=[
                        WebCitation(title="Release notes", url="https://example.test/dsh")
                    ],
                ),
            ),
            token_usage={},
        )

    monkeypatch.setattr(live_module, "run_evaluation", fake_eval)
    with client_factory(enabled=True).websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "web_search": True, "quiet_period": 0})
        ws.receive_json()
        ws.send_json({"type": "turn", "speaker": "me", "text": "DeepSeek harness?", "role": "owner"})
        frame = ws.receive_json()

    assert frame["type"] == "suggestion"
    card = frame["suggestion"]
    assert card["kind"] == "web"
    assert card["citations"] == []
    assert card["web_citations"] == [
        {"title": "Release notes", "url": "https://example.test/dsh"}
    ]
