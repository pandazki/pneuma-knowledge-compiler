"""OpenRouter reranker adapter: payload shape, score parsing, over-length splicing."""

from __future__ import annotations

import httpx
import pytest

from pneuma_knowledge_service.adapters.llm_rerank import _CLIP_MARKER
from pneuma_knowledge_service.adapters.openrouter_rerank import OpenRouterReranker


def _reranker_with_transport(handler) -> OpenRouterReranker:
    reranker = OpenRouterReranker("cohere/rerank-4-pro", "test-key")
    reranker._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return reranker


async def test_rerank_sends_clipped_documents_and_parses_sorted_scores():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.2},
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": "bad"},  # malformed row → skipped
                ]
            },
        )

    reranker = _reranker_with_transport(handler)
    results = await reranker.rerank("q", ["a", "B" * 60_000], top_n=2)
    assert [(r.index, r.score) for r in results] == [(0, 0.9), (1, 0.2)]
    assert seen["top_n"] == 2
    assert seen["documents"][0] == "a"
    assert _CLIP_MARKER in seen["documents"][1]  # over-long doc spliced, not sent whole
    assert len(seen["documents"][1]) < 60_000
    await reranker.aclose()


async def test_rerank_raises_on_provider_error_for_the_caller_to_degrade():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    reranker = _reranker_with_transport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await reranker.rerank("q", ["a"], top_n=1)
    await reranker.aclose()


async def test_empty_documents_short_circuit_without_a_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    reranker = _reranker_with_transport(handler)
    assert await reranker.rerank("q", [], top_n=5) == []
    await reranker.aclose()
