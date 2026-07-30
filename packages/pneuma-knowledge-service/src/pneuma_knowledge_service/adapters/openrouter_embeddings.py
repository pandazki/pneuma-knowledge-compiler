"""OpenRouter embeddings adapter (langchain-core `Embeddings`).

OpenRouter serves an OpenAI-compatible `/embeddings` endpoint (e.g.
`google/gemini-embedding-2`, 3072-dim), so real semantic vectors reuse the existing
`OPENROUTER_API_KEY` — no new key, no new service. We call the raw endpoint with a plain
`httpx` POST rather than langchain's `OpenAIEmbeddings`: the openai client defaults to
tokenizing input into token-id arrays and requesting base64 vectors, which gemini rejects
("No embedding data received"). Raw float output is unambiguous and fully under our control.

Kept behind the `Embeddings` port so core stays provider-agnostic (architecture.md §2);
`build_embeddings` selects this via the `openrouter:<model>` spec.

The async face (`aembed_query` / `aembed_documents`) is the one the service uses: it is a
real `httpx.AsyncClient` round trip, NOT langchain's default thread-pool delegation. The
sync face is kept working (a separate, lazily built `httpx.Client`) for offline scripts
that are not running inside an event loop; both share one retry/batching policy.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from langchain_core.embeddings import Embeddings

# Batch inputs per request so a large ingest (hundreds of chunks) doesn't send one giant
# body; OpenRouter returns `data` with per-input `index` we re-sort on.
_BATCH = 32
_TIMEOUT = 60.0

# Retry budget. 6 attempts with exponential backoff capped per sleep at 30s spends
# 2+4+8+16+30 = 60s of waiting before giving up. The previous budget (3 tries,
# 0.5/1.0s sleeps → 1.5s total) was shorter than a single ordinary network hiccup or
# provider rate-limit window, so a blip that a minute of patience would have absorbed
# failed a whole ingest instead. Minutes-scale patience here is cheap: the caller is a
# background compile/index job, not a user-facing request.
# Deliberately module constants rather than Settings: this is one internal policy number,
# not a per-deployment knob.
_RETRIES = 6
_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 30.0


def _backoff(attempt: int) -> float:
    """Seconds to wait after a failed attempt (0-based). Exponential, capped."""
    return min(_BACKOFF_CAP, _BACKOFF_BASE * 2**attempt)

# NOTE on provider stability: OpenRouter load-balances a model across providers at wildly
# different latencies (qwen3-embedding-8b measured ~1s on Nebius but 24-65s on DeepInfra).
# Single-provider models (e.g. openai/text-embedding-3-small → only OpenAI) sidestep this
# entirely, which is why we default to one. If a multi-provider model is ever needed, add a
# `"provider": {"order": [...], "allow_fallbacks": True}` field to the request body below.


class OpenRouterEmbeddings(Embeddings):
    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        if not api_key:
            raise RuntimeError("openrouter:<model> embeddings require OPENROUTER_API_KEY")
        self._model = model
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # Persistent client → keep-alive connection reuse across calls. Every recall embeds
        # the query, so a fresh connection (+ TCP/TLS handshake ~0.5-1s) per call was pure
        # overhead; the pooled client also removes the cold-start hit on the first embed.
        self._aclient = httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers)
        self._client: httpx.Client | None = None  # sync face, built on first use only

    # --- shared response shaping ---------------------------------------------

    def _body(self, inputs: list[str]) -> dict:
        return {"model": self._model, "input": inputs}

    @staticmethod
    def _vectors(payload: dict) -> list[list[float]]:
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    # --- async face (what the service uses) -----------------------------------

    async def _apost(self, inputs: list[str]) -> list[list[float]]:
        last: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                resp = await self._aclient.post(self._url, json=self._body(inputs))
                resp.raise_for_status()
                return self._vectors(resp.json())
            except Exception as exc:  # noqa: BLE001 — transient network/5xx: retry then raise
                last = exc
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_backoff(attempt))
        # Fail loud: the budget is spent, so this is no longer a blip. Never return a
        # partial/zero vector — a silently empty embedding corrupts the index.
        raise RuntimeError(f"OpenRouter embeddings failed after {_RETRIES} tries: {last}")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            out.extend(await self._apost(list(texts[i : i + _BATCH])))
        return out

    async def aembed_query(self, text: str) -> list[float]:
        return (await self._apost([text]))[0]

    # --- sync face (offline scripts outside an event loop) --------------------

    def _sync_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=_TIMEOUT, headers=self._headers)
        return self._client

    def _post(self, inputs: list[str]) -> list[list[float]]:
        last: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                resp = self._sync_client().post(self._url, json=self._body(inputs))
                resp.raise_for_status()
                return self._vectors(resp.json())
            except Exception as exc:  # noqa: BLE001 — transient network/5xx: retry then raise
                last = exc
                if attempt < _RETRIES - 1:
                    time.sleep(_backoff(attempt))
        # Same fail-loud contract as the async face (see `_apost`).
        raise RuntimeError(f"OpenRouter embeddings failed after {_RETRIES} tries: {last}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            out.extend(self._post(list(texts[i : i + _BATCH])))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._post([text])[0]
