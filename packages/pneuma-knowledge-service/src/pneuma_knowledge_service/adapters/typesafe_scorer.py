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
import hashlib
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Sequence

import httpx

from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScoreDetail, EvidenceScores, SourceClockDecision

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
_SCORE_INSTRUCTIONS = "How useful is `{candidate}` as evidence for answering `question`?"
_RUBRIC_ID = hashlib.sha256(json.dumps(
    [_SCORE_INSTRUCTIONS, USEFULNESS_LEVELS], ensure_ascii=False,
).encode()).hexdigest()[:16]
_SOURCE_CLOCK_INSTRUCTIONS = "Does answering `question` require selecting source records by their occurrence dates or recency?"
_SOURCE_CLOCK_CRITERIA = {
    "true": "The requested records must fall in a time period, or be the most recent updates: today's notes, last week's work, recent projects, or records within a stated date range.",
    "false": "The question asks about a subject, a recorded fact, or an event's date without filtering source records by when they were recorded. General past experience, a project's release date, and a historical test result do not by themselves require source-date filtering.",
}
_SOURCE_CLOCK_FLOOR = 0.8
_SOURCE_CLOCK_TIMEOUT_SECONDS = 2.0
_SOURCE_PERIOD_INSTRUCTIONS = (
    "Which exact calendar period does `question` request for source records? "
    "Select unresolved for vague recency, event dates rather than record dates, sub-day "
    "windows, comparisons of separate periods, exclusions, or a period not described by an option."
)
_SOURCE_PERIOD_CRITERIA = {
    "today": "Records from the current calendar day only.",
    "yesterday": "Records from the immediately preceding calendar day only.",
    "day_before_yesterday": "Records from the calendar day before yesterday only.",
    "last_two_days": "Records from these two calendar days, today and yesterday (这两天).",
    "last_three_days": "Records from these three calendar days, including today.",
    "last_seven_days": "Records from the last seven calendar days, including today, not the previous calendar week.",
    "last_fourteen_days": "Records from the last fourteen calendar days, including today.",
    "last_thirty_days": "Records from the last thirty calendar days, including today, not the previous calendar month.",
    "this_week": "Records from the current calendar week, Monday through today.",
    "last_week": "Records from the whole preceding calendar week, Monday through Sunday.",
    "this_month": "Records from the first day of the current month through today.",
    "last_month": "Records from the whole preceding calendar month.",
    "this_year": "Records from the first day of the current year through today.",
    "last_year": "Records from the whole preceding calendar year.",
    "explicit_dates": "Records for one literal date or one inclusive range with both full dates written in the question. No exclusions or disjoint periods.",
    "unresolved": "No exact supported source-record period: vague recently/latest, an event date, sub-day times, separate periods being compared, exclusions, or another unsupported period.",
}
_SOURCE_CLOCK_POLICY_ID = hashlib.sha256(json.dumps(
    [_SOURCE_CLOCK_INSTRUCTIONS, _SOURCE_CLOCK_CRITERIA, _SOURCE_CLOCK_FLOOR,
     _SOURCE_PERIOD_INSTRUCTIONS, _SOURCE_PERIOD_CRITERIA], sort_keys=True,
).encode()).hexdigest()[:16]


def _number(value: object, upper: float) -> float | None:
    """Invalid model output is missing evidence, never a clamped confident answer."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= upper else None


def _detail(row: dict, model: object) -> EvidenceScoreDetail:
    raw = row.get("probabilities")
    probabilities: tuple[float, ...] = ()
    if isinstance(raw, dict) and set(raw) == {str(i) for i in range(len(USEFULNESS_LEVELS))}:
        values = tuple(_number(raw[str(i)], 1) for i in range(len(USEFULNESS_LEVELS)))
        if all(v is not None for v in values) and math.isclose(sum(values), 1, abs_tol=1e-5):
            probabilities = values
    reported = model if isinstance(model, str) and re.fullmatch(r"[\w./:+-]{1,200}", model) else None
    return EvidenceScoreDetail(probabilities, _number(row.get("confidence"), 1), reported)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    seconds = _number(value, float("inf"))
    if seconds is not None:
        return seconds
    try:
        instant = parsedate_to_datetime(value)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return max(0, (instant - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


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
        # Wiring caches this adapter: concurrent recalls share the provider budget.
        self._semaphore = asyncio.Semaphore(self._concurrency)
        self._call_timeout = call_timeout
        self._retries = max(0, retries)
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._call_timeout)
        return self._client

    async def source_clock_policy(self, question: str) -> SourceClockDecision:
        """Judge source-clock intent and a supported period in one question-only request.

        Core resolves calendar boundaries and owns admission. Unavailable validation is
        distinct from a negative intent decision. The request overlaps retrieval and is
        shared by the voice lookup's early and broad phases.
        """
        async def request():
            async with self._semaphore:
                return await self._post({
                    "model": self._model, "state": {"question": question},
                    "questions": {
                        "source_clock": {"type": "noul", "instructions": _SOURCE_CLOCK_INSTRUCTIONS,
                                         "criteria": _SOURCE_CLOCK_CRITERIA},
                        "source_period": {"type": "choice", "instructions": _SOURCE_PERIOD_INSTRUCTIONS,
                                          "criteria": _SOURCE_PERIOD_CRITERIA},
                    },
                })

        try:
            payload = await asyncio.wait_for(request(), min(self._call_timeout, _SOURCE_CLOCK_TIMEOUT_SECONDS))
        except TimeoutError:
            return SourceClockDecision(policy_id=_SOURCE_CLOCK_POLICY_ID)
        if payload is None:
            return SourceClockDecision(policy_id=_SOURCE_CLOCK_POLICY_ID)
        answers = payload.get("answers")
        row = answers.get("source_clock") if isinstance(answers, dict) else None
        probability = _number(row.get("noul"), 1) if isinstance(row, dict) else None
        period_row = answers.get("source_period") if isinstance(answers, dict) else None
        period = period_row.get("choice") if isinstance(period_row, dict) else None
        period = period if isinstance(period, str) and period in _SOURCE_PERIOD_CRITERIA else None
        period_confidence = _number(period_row.get("confidence"), 1) if isinstance(period_row, dict) else None
        usage = payload.get("usage") or {}
        try:
            tokens = max(0, int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))) if isinstance(usage, dict) else 0
        except (ValueError, TypeError, OverflowError):
            tokens = 0
        return SourceClockDecision(
            probability is not None and probability >= _SOURCE_CLOCK_FLOOR, probability, tokens,
            _SOURCE_CLOCK_POLICY_ID,
            period, period_confidence,
        )

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
                "instructions": _SCORE_INSTRUCTIONS.format(candidate=f"candidates.c{index + 1}"),
                "criteria": list(USEFULNESS_LEVELS),
            }
            for index, _text in shard
        }
        return {"model": self._model, "state": state, "questions": questions}

    async def _post(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """One shard's payload, or None when it failed after its retry."""
        for attempt in range(self._retries + 1):
            retryable = False
            retry_delay = _RETRY_SLEEP_SECONDS * (2 ** attempt)
            try:
                response = await self._ensure_client().post(
                    _ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    retryable = True
                    retry_delay = max(retry_delay, _retry_after(response.headers.get("Retry-After")) or 0)
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
            # Do not retry before the provider allows it. A long cooldown is a fail-soft
            # result; the recall deadline must not become a background retry queue.
            if retry_delay >= self._call_timeout:
                return None
            await asyncio.sleep(retry_delay)
        return None

    async def score(self, question: str, candidates: Sequence[str]) -> EvidenceScores:
        texts = list(candidates)
        if not texts:
            return EvidenceScores(scores=(), input_tokens=0)
        shards = self._shards(texts)

        async def run(shard: list[tuple[int, str]]):
            async with self._semaphore:
                return shard, await self._post(self._body(question, shard))

        results = await asyncio.gather(*(run(shard) for shard in shards))

        scores: list[float | None] = [None] * len(texts)
        details: list[EvidenceScoreDetail | None] = [None] * len(texts)
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
                    input_tokens += max(0, int(raw_tokens or 0))
                except (TypeError, ValueError, OverflowError):
                    pass
            answers = payload.get("answers") or {}
            if not isinstance(answers, dict):
                continue
            for index, _text in shard:
                row = answers.get(f"c{index + 1}")
                if not isinstance(row, dict):
                    continue
                level = _number(row.get("score"), _MAX_LEVEL)
                if level is None:
                    continue
                scores[index] = level / _MAX_LEVEL
                details[index] = _detail(row, payload.get("model"))
        if shards and answered == 0:
            # Every shard failed: that is the provider being down, not a partial judgement,
            # and the caller's own fail-soft path is the honest place to land.
            raise RuntimeError("every evidence-scoring shard failed")
        return EvidenceScores(
            scores=tuple(scores), input_tokens=input_tokens, details=tuple(details),
            requested_model=self._model, rubric_id=_RUBRIC_ID,
        )

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
