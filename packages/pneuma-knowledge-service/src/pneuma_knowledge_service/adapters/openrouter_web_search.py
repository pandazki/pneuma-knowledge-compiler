"""The shipped `WebSearch`: OpenRouter's Responses API with a provider-native search.

Ported from the reference the owner supplied, with three deliberate differences:

* **Async, one client.** The sample opens a synchronous client per run; this is a long-lived
  adapter on the API process's own loop, so it holds one `httpx.AsyncClient` and closes it
  with the rest of the context.
* **No retry, ever.** The sample says why and it is the reason worth repeating: a retried
  POST to this endpoint is a SECOND CHARGE. A failed search is a degraded face in the tick
  record and nothing else — the lane is built to lose it, and paying twice to avoid losing
  it would be the wrong trade for a supplement. There is no retry here and none is wanted.
* **No post-hoc audit.** The sample follows delivery with a `GET /generation` that confirms
  the search ran natively on the pinned provider. That is an audit AFTER the answer, its
  metadata takes tens of seconds to appear, and it cannot gate anything the reader has
  already been shown — so it is not a delivery gate and it is not here. What IS enforced
  is the request: the provider is pinned with `allow_fallbacks: false`, so a request that
  could not be served by the named provider fails rather than landing quietly on a reseller.

The provider pin, the model and the tool declaration are the sample's, verbatim in shape.
The instruction the question is wrapped in is a catalog key, so a deployment can rewrite it
the way it rewrites every other model-visible sentence in this repository.

Citations come off `annotations[type=url_citation]`, which is where the Responses API puts
what a native search actually read. An answer with none of them still returns here — the
refusal to build a card out of it belongs to core (`candidate_from_web`), because that is
where every other candidate is admitted or not.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from pneuma_knowledge_core.domain.suggestion import WebCitation
from pneuma_knowledge_core.ports.web_search import WebSearchAnswer
from pneuma_knowledge_core.prompts import prompt

logger = logging.getLogger(__name__)

#: OpenRouter's OpenAI-compatible root. The Responses API hangs off `responses`.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/"

#: The provider pin, exactly as the reference states it: serve on OpenAI itself, never on
#: the flex/fast tiers, and never fall back. Without `allow_fallbacks: false` a request that
#: OpenAI could not serve would land on some other provider of the same model — which may
#: not have a native search at all, and would answer from memory while looking identical.
PROVIDER_PIN: dict[str, Any] = {
    "only": ["openai"],
    "ignore": ["openai/flex", "openai/fast"],
    "allow_fallbacks": False,
}

#: Reasoning is LOW for the same reason the whole Live Context lane is small: this call sits
#: inside a tick that must not be noticed. Output is bounded because the card body is.
REASONING_EFFORT = "low"
MAX_OUTPUT_TOKENS = 2048

#: Connect and total budgets for the HTTP call itself. The LANE's own 15s bound is the one
#: that protects the tick; this is the floor under a socket that never answers at all.
HTTP_TIMEOUT = httpx.Timeout(75.0, connect=15.0)


class OpenRouterWebSearch:
    """One supplementary internet lookup, over OpenRouter's native web search."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._base_url = base_url
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ the port

    def available(self) -> bool:
        """Key AND model. Either one missing means the `web` lookup is never offered."""
        return bool(self._api_key and self._model)

    async def search(self, question: str, *, max_results: int = 3) -> WebSearchAnswer:
        """One POST, streamed, read to `response.completed`. NEVER retried — see the
        module docstring: a retry is a second charge."""
        if not self.available():
            raise RuntimeError("web search is not configured")
        payload = {
            "model": self._model,
            "provider": PROVIDER_PIN,
            "input": prompt("recall.live.web.instruction", question=question),
            "tools": [
                {"type": "openrouter:web_search", "parameters": {"engine": "native"}}
            ],
            "reasoning": {"effort": REASONING_EFFORT},
            "tool_choice": "auto",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_tool_calls": max(1, int(max_results)),
            "stream": True,
        }
        response = await self._read_stream(payload)
        return _answer_from(response)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ internals

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
                transport=self._transport,
            )
        return self._client

    async def _read_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Drain the SSE stream and hand back the completed response object.

        Only `response.completed` carries the output and the usage, so a stream that ends
        without one is an error rather than an empty answer — and the error says not to
        retry, because the charge has already been incurred either way."""
        completed: dict[str, Any] | None = None
        async with self._http().stream("POST", "responses", json=payload) as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    event = json.loads(data)
                except ValueError:  # pragma: no cover - a malformed frame is not an answer
                    continue
                kind = event.get("type")
                if kind == "response.completed":
                    completed = event.get("response") or {}
                elif kind in ("error", "response.failed", "response.incomplete") or event.get(
                    "error"
                ):
                    raise RuntimeError(
                        f"web search failed: {json.dumps(event, ensure_ascii=False)[:400]}"
                    )
        if completed is None:
            raise RuntimeError(
                "web search stream ended with no response.completed; do not retry blindly"
            )
        return completed


def _answer_from(response: dict[str, Any]) -> WebSearchAnswer:
    """The completed Responses object → the port's shape. Pure, so the parse is testable.

    Citations are de-duplicated by URL in the order the answer named them: the same page
    annotated twice is one source, and the order it was read in is the only ranking there is.
    """
    text_parts: list[str] = []
    citations: list[WebCitation] = []
    seen: set[str] = set()
    for item in response.get("output") or []:
        for part in item.get("content") or []:
            chunk = part.get("text")
            if isinstance(chunk, str) and chunk:
                text_parts.append(chunk)
            for annotation in part.get("annotations") or []:
                url = str(annotation.get("url") or "").strip()
                if annotation.get("type") != "url_citation" or not url or url in seen:
                    continue
                seen.add(url)
                citations.append(
                    WebCitation(title=str(annotation.get("title") or ""), url=url)
                )
    usage = response.get("usage") or {}
    details = usage.get("server_tool_use_details") or {}
    return WebSearchAnswer(
        text="".join(text_parts).strip(),
        citations=tuple(citations),
        searches=int(details.get("web_search_requests") or 0),
        cost=float(usage.get("cost") or 0.0),
    )
