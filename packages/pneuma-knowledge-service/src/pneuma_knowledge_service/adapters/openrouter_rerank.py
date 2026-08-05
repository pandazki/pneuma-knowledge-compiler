"""OpenRouter reranker adapter (core `Reranker` port).

OpenRouter serves a Cohere-compatible `/rerank` endpoint (e.g. `cohere/rerank-4-pro`):
query + documents in, per-document relevance scores out. A dedicated cross-encoder reads the
texts and scores magnitudes — the judgement RRF cannot make. Head-to-head on
LoCoMo-refined it bought no score over the LLM provider or over no reranking at all and
bills per search unit, so it ships as the alternative provider behind `llm`, for
workloads (long-document candidates, latency-critical asks) where a purpose-built scorer
earns its fee.

Fail-fast by design: this adapter RAISES on transport/provider errors and does not retry —
it sits on the interactive ask path where the caller (`rerank_claims`) already degrades to
the fused order under its own timeout, so patience here would only stack delays. Contrast
with the embeddings adapter, whose background-job callers earn a minutes-scale retry
budget.
"""

from __future__ import annotations

import httpx

from pneuma_knowledge_core.ports.reranker import RerankResult

from .llm_rerank import clip_document

_ENDPOINT = "https://openrouter.ai/api/v1/rerank"
_TIMEOUT = 30.0

class OpenRouterReranker:
    def __init__(self, model: str, api_key: str, *, timeout: float = _TIMEOUT) -> None:
        if not api_key:
            raise ValueError("OpenRouterReranker requires an OPENROUTER_API_KEY")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def rerank(
        self, query: str, documents, *, top_n: int
    ) -> list[RerankResult]:
        if not documents:
            return []
        response = await self._ensure_client().post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "query": query,
                "documents": [clip_document(doc) for doc in documents],
                "top_n": min(top_n, len(documents)),
            },
        )
        response.raise_for_status()
        payload = response.json()
        results: list[RerankResult] = []
        for row in payload.get("results", []):
            try:
                results.append(
                    RerankResult(index=int(row["index"]), score=float(row["relevance_score"]))
                )
            except (KeyError, TypeError, ValueError):
                continue  # a malformed row degrades to "unscored", never to a crash
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
