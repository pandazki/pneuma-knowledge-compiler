"""OpenRouter embeddings retry budget: patient across a blip, loud once it is spent.

The old budget (3 tries, 0.5s + 1.0s of backoff) was shorter than one ordinary network
hiccup, so a transient failure that a minute of patience would have absorbed failed a
whole ingest instead. These tests pin three parts of one contract: the budget is
minutes-scale, exhausting it still raises rather than returning a degraded vector, and the
budget is never spent on an answer the provider has already given — a wrong key produced
"failed after 6 tries" a minute after the first 401, with the engine dead the whole time.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from pneuma_knowledge_service.adapters import openrouter_embeddings as mod
from pneuma_knowledge_service.adapters.openrouter_embeddings import OpenRouterEmbeddings

VECTOR = [0.5, 0.25, 0.125]
_REAL_BACKOFF = mod._backoff


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [{"index": 0, "embedding": VECTOR}]}


class _FlakyClient:
    """Fails `failures` times with a transient error, then returns a real payload."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def post(self, url, json):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("connection reset by peer")
        return _Response()

    async def apost(self, url, json):
        return self.post(url, json)


class _Waits(list):
    """The backoff attempts taken, priced with the REAL schedule (no test sleeps)."""

    @property
    def seconds(self) -> float:
        return sum(_REAL_BACKOFF(attempt) for attempt in self)


def _adapter(monkeypatch, *, failures: int):
    """An adapter with a flaky fake transport and instant (but recorded) backoff."""
    emb = OpenRouterEmbeddings("vendor/embed", "sk-test-not-a-real-key")
    client = _FlakyClient(failures)
    emb._aclient = SimpleNamespace(post=client.apost)
    monkeypatch.setattr(emb, "_sync_client", lambda: client)

    waits = _Waits()

    def _instant(attempt: int) -> float:
        waits.append(attempt)
        return 0.0

    monkeypatch.setattr(mod, "_backoff", _instant)
    return emb, client, waits


def test_retry_budget_spends_about_a_minute_before_giving_up() -> None:
    """Total patience across the whole retry chain, in seconds."""
    budget = sum(_REAL_BACKOFF(attempt) for attempt in range(mod._RETRIES - 1))

    assert mod._RETRIES >= 6
    assert 55.0 <= budget <= 120.0
    # Exponential with a per-sleep cap: an early blip is retried fast, a long outage is
    # not hammered.
    assert _REAL_BACKOFF(0) < _REAL_BACKOFF(1)
    assert _REAL_BACKOFF(99) == mod._BACKOFF_CAP


def test_async_embed_survives_five_consecutive_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emb, client, waits = _adapter(monkeypatch, failures=mod._RETRIES - 1)

    assert asyncio.run(emb.aembed_query("hello")) == VECTOR
    assert client.calls == mod._RETRIES
    assert waits.seconds >= 55.0


def test_async_embed_fails_loud_once_the_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emb, client, _ = _adapter(monkeypatch, failures=mod._RETRIES)

    with pytest.raises(RuntimeError, match="OpenRouter embeddings failed after"):
        asyncio.run(emb.aembed_query("hello"))
    assert client.calls == mod._RETRIES


def test_sync_face_shares_the_same_budget_and_fail_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emb, client, waits = _adapter(monkeypatch, failures=mod._RETRIES - 1)
    assert emb.embed_query("hello") == VECTOR
    assert client.calls == mod._RETRIES
    assert waits.seconds >= 55.0

    exhausted, client, _ = _adapter(monkeypatch, failures=mod._RETRIES)
    with pytest.raises(RuntimeError, match="OpenRouter embeddings failed after"):
        exhausted.embed_query("hello")
    assert client.calls == mod._RETRIES


class _StatusClient:
    """Answers every request with the same real HTTP response."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.calls = 0

    def post(self, url, json):
        self.calls += 1
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings")
        return httpx.Response(self.status, request=request, json={"error": "synthetic"})

    async def apost(self, url, json):
        return self.post(url, json)


def _status_adapter(monkeypatch, status: int):
    emb = OpenRouterEmbeddings("vendor/embed", "sk-test-not-a-real-key")
    client = _StatusClient(status)
    emb._aclient = SimpleNamespace(post=client.apost)
    monkeypatch.setattr(emb, "_sync_client", lambda: client)
    monkeypatch.setattr(mod, "_backoff", lambda attempt: 0.0)
    return emb, client


def test_a_rejected_key_fails_on_the_first_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 is the provider's decision, not a blip: asking again gets the same answer."""
    emb, client = _status_adapter(monkeypatch, 401)

    with pytest.raises(RuntimeError, match="failed after 1 try:") as refusal:
        asyncio.run(emb.aembed_query("hello"))
    assert client.calls == 1
    # Chained, so a caller can read the status off the cause instead of the sentence.
    assert refusal.value.__cause__.response.status_code == 401


@pytest.mark.parametrize("status", [400, 403, 404])
def test_other_decided_client_errors_are_final_too(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    emb, client = _status_adapter(monkeypatch, status)
    with pytest.raises(RuntimeError, match="failed after 1 try:"):
        asyncio.run(emb.aembed_query("hello"))
    assert client.calls == 1

    exhausted, client = _status_adapter(monkeypatch, status)
    with pytest.raises(RuntimeError, match="failed after 1 try:"):
        exhausted.embed_query("hello")
    assert client.calls == 1


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_later_and_server_side_statuses_still_spend_the_budget(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """429 and 408 mean "later", 5xx means "not me, not now" — all three are worth waiting on."""
    emb, client = _status_adapter(monkeypatch, status)
    with pytest.raises(RuntimeError, match="failed after 6 tries:"):
        asyncio.run(emb.aembed_query("hello"))
    assert client.calls == mod._RETRIES
