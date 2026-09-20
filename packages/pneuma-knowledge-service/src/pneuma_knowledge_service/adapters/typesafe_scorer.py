"""TypeSafe evidence scorer adapter (core `EvidenceScorer` port).

OpenRouter's decisions route serves a calibrated decision model: a state, a set of
questions about it, and one expected-level answer per question — no generation, no prose.
That is exactly the shape of `select`'s judgement when it is asked candidate by candidate:
"how useful is this one as evidence for answering the question", on a fixed four-level
rubric, which the port's contract divides into a 0–1 score. The keep/drop decision is not
here: it is a floor in `select_evidence_scored`.

The rubric lives in ONE module-level constant. A threshold and the words that define it
belong together in a place a human reviews, not scattered across per-call strings.

Fail-fast per shard, like the rerank adapters: the lane's `select` timeout is the outer
bound, so patience here would only stack delays under it. One retry covers the transient
(429, 5xx, a dropped connection); past that the shard's candidates come back unscored,
which the port defines as "neither kept nor dropped". Only a pass in which EVERY shard
failed raises — that is a provider outage, not a partial answer.

Candidate text is never logged. It is knowledge-base content, and a scorer is the one
place in the lane where it passes through code that has no other reason to hold it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Sequence

import httpx

from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScores

_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_RETRY_SLEEP_SECONDS = 0.25

#: The scale, in the words the model reads. Four ordered levels, so the expected level the
#: model returns is a number on a rubric rather than a taste: 0–3, divided by 3 to land on
#: the port's documented 0.0–1.0 contract (0.0 = a different subject, 1.0 = states the
#: asked-for fact). Change these words and the floor means something else — which is why
#: they are here, in one place, and not composed per request.
USEFULNESS_LEVELS: tuple[str, ...] = (
    "Irrelevant: a different subject, useless for answering",
    "Same subject but does not help answer the question",
    "Useful evidence: part of the answer or context it needs",
    "Directly answers the question",
)
_MAX_LEVEL = len(USEFULNESS_LEVELS) - 1


class TypeSafeEvidenceScorer:
    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        per_request: int = 50,
        max_chars: int = 24_000,
        concurrency: int = 16,
        call_timeout: float = 6.0,
        retries: int = 1,
    ) -> None:
        if not api_key:
            raise ValueError("TypeSafeEvidenceScorer requires an OPENROUTER_API_KEY")
        if not model:
            raise ValueError("TypeSafeEvidenceScorer requires a model")
        self._model = model
        self._api_key = api_key
        self._per_request = max(1, per_request)
        self._max_chars = max(1, max_chars)
        self._concurrency = max(1, concurrency)
        self._call_timeout = call_timeout
        self._retries = max(0, retries)
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._call_timeout)
        return self._client

    def _shards(self, candidates: Sequence[str]) -> list[list[tuple[int, str]]]:
        """Greedy shards, bounded by COUNT and by the characters they carry.

        A count bound alone lets one shard of fifty verbatim windows blow past the vendor's
        request budget while a shard of fifty short claims sits nearly empty, so both bounds
        run together and a single over-long candidate still gets its own shard rather than
        being dropped. The size measured is the CARD as it goes on the wire — escapes and
        all — because that is what the request budget actually counts."""
        shards: list[list[tuple[int, str]]] = []
        current: list[tuple[int, str]] = []
        chars = 0
        for index, text in enumerate(candidates):
            size = len(json.dumps({"text": text}, ensure_ascii=False))
            if current and (len(current) >= self._per_request or chars + size > self._max_chars):
                shards.append(current)
                current, chars = [], 0
            current.append((index, text))
            chars += size
        if current:
            shards.append(current)
        return shards

    def _body(self, question: str, shard: Sequence[tuple[int, str]]) -> dict[str, Any]:
        # Candidates are addressed by NAMED KEYS (`candidates.c17`), never by array index
        # (`candidates[16]`): measured on the same data, index addressing costs 0.06–0.07
        # AUROC because the model does not count reliably; named keys do not.
        state = {
            "question": question,
            "candidates": {f"c{index + 1}": {"text": text} for index, text in shard},
        }
        questions = {
            f"c{index + 1}": {
                "type": "score",
                "instructions": (
                    f"How useful is `candidates.c{index + 1}` as evidence for answering "
                    "`question`?"
                ),
                "criteria": list(USEFULNESS_LEVELS),
            }
            for index, _text in shard
        }
        return {"model": self._model, "state": state, "questions": questions}

    async def _post(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """One shard's payload, or None when it failed after its retry."""
        for attempt in range(self._retries + 1):
            retryable = False
            try:
                response = await self._ensure_client().post(
                    _ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    retryable = True
                    raise httpx.HTTPStatusError(
                        f"decisions route returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else None
            except httpx.HTTPStatusError:
                pass  # `retryable` already says which kind this was; a 4xx is final
            except httpx.HTTPError:
                retryable = True  # transport: connect, read, timeout
            except ValueError:
                pass  # a body that does not parse will not parse on a second try
            if not retryable or attempt >= self._retries:
                return None
            await asyncio.sleep(_RETRY_SLEEP_SECONDS)
        return None

    async def score(self, question: str, candidates: Sequence[str]) -> EvidenceScores:
        texts = list(candidates)
        if not texts:
            return EvidenceScores(scores=(), input_tokens=0)
        shards = self._shards(texts)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(shard: list[tuple[int, str]]):
            async with semaphore:
                return shard, await self._post(self._body(question, shard))

        results = await asyncio.gather(*(run(shard) for shard in shards))

        scores: list[float | None] = [None] * len(texts)
        input_tokens = 0
        answered = 0
        for shard, payload in results:
            if payload is None:
                continue  # a failed shard is unscored, not zero — the port says so
            answered += 1
            usage = payload.get("usage") or {}
            if isinstance(usage, dict):
                raw_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                try:
                    input_tokens += int(raw_tokens or 0)
                except (TypeError, ValueError):
                    pass
            answers = payload.get("answers") or {}
            if not isinstance(answers, dict):
                continue
            for index, _text in shard:
                row = answers.get(f"c{index + 1}")
                if not isinstance(row, dict):
                    continue
                try:
                    level = float(row["score"])
                except (KeyError, TypeError, ValueError):
                    continue  # a malformed row is unscored, never a fabricated 0
                scores[index] = min(max(level, 0.0), _MAX_LEVEL) / _MAX_LEVEL
        if shards and answered == 0:
            # Every shard failed: that is the provider being down, not a partial judgement,
            # and the caller's own fail-soft path is the honest place to land.
            raise RuntimeError("every evidence-scoring shard failed")
        return EvidenceScores(scores=tuple(scores), input_tokens=input_tokens)

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
