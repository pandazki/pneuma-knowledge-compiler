"""TypeSafe evidence scorer: request shape, sharding, the 0–3 → 0–1 mapping, failure.

The request shape is not cosmetic here. Candidates are addressed by NAMED KEYS because
index addressing measurably costs the model accuracy. Each candidate has its own question;
this does not guarantee independence from other candidates sharing the state. Both are
asserted on the wire. The rest is the port's contract: a failed shard is unscored (not zero), a pass in
which every shard failed raises, and usage sums across shards.

Keyless: every request is served by `httpx.MockTransport`.
"""

from __future__ import annotations

import json
import asyncio

import httpx
import pytest

from pneuma_knowledge_service.adapters.typesafe_scorer import (
    USEFULNESS_LEVELS,
    TypeSafeEvidenceScorer,
)


def _scorer(handler, **kwargs) -> TypeSafeEvidenceScorer:
    scorer = TypeSafeEvidenceScorer(
        "typesafe/jev-1.13-20260917", "test-key", **kwargs
    )
    scorer._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return scorer


def _answers(body: dict, levels: dict[str, float] | None = None) -> dict:
    """Answer every question the shard asked, at `levels` or level 3."""
    return {
        "answers": {
            key: {"score": (levels or {}).get(key, 3)} for key in body["questions"]
        },
        "usage": {"input_tokens": 100},
    }


async def test_the_request_names_every_candidate_by_key_and_asks_one_score_each():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_answers(body))

    scorer = _scorer(handler)
    result = await scorer.score(
        "who renewed example.com?",
        ["[note] Mei LIN renewed it", "[note] 阿宝 booked the room"],
    )

    body = seen[0]
    assert body["model"] == "typesafe/jev-1.13-20260917"
    assert body["state"]["question"] == "who renewed example.com?"
    assert body["state"]["candidates"] == {
        "c1": {"text": "[note] Mei LIN renewed it"},
        "c2": {"text": "[note] 阿宝 booked the room"},
    }
    assert set(body["questions"]) == {"c1", "c2"}
    assert body["questions"]["c2"] == {
        "type": "score",
        "instructions": "How useful is `candidates.c2` as evidence for answering `question`?",
        "criteria": list(USEFULNESS_LEVELS),
    }
    assert result.scores == (1.0, 1.0)
    await scorer.aclose()


async def test_the_expected_level_lands_on_the_ports_zero_to_one_scale():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "c1": {"score": 0},
                    "c2": {"score": 1.5},
                    "c3": {"score": 3},
                    "c4": {"score": "not a number"},  # malformed → unscored, never a 0
                },
                "usage": {"input_tokens": 7},
            },
        )

    scorer = _scorer(handler)
    result = await scorer.score("q", ["a", "b", "c", "d"])
    assert result.scores == (0.0, 0.5, 1.0, None)
    assert result.input_tokens == 7
    await scorer.aclose()


async def test_shards_are_bounded_by_count_and_by_the_characters_they_carry():
    shards: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        shards.append(body)
        return httpx.Response(200, json=_answers(body))

    by_count = _scorer(handler, per_request=2)
    result = await by_count.score("q", [f"candidate {n}" for n in range(5)])
    assert [len(s["questions"]) for s in shards] == [2, 2, 1]
    # Every candidate came back scored, and each kept its place in the submitted list.
    assert result.scores == (1.0,) * 5
    # Keys stay GLOBAL across shards, so an answer is traceable to one candidate.
    assert sorted(k for s in shards for k in s["questions"]) == [
        "c1", "c2", "c3", "c4", "c5"
    ]
    await by_count.aclose()

    shards.clear()
    by_chars = _scorer(handler, per_request=50, max_chars=200)
    await by_chars.score("q", ["X" * 150, "Y" * 150, "Z" * 10])
    assert [len(s["questions"]) for s in shards] == [1, 2]
    await by_chars.aclose()


async def test_usage_sums_across_shards():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=_answers(body))

    scorer = _scorer(handler, per_request=1)
    result = await scorer.score("q", ["a", "b", "c"])
    assert result.input_tokens == 300
    await scorer.aclose()


async def test_a_transient_failure_is_retried_once_and_then_succeeds():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json=_answers(body))

    scorer = _scorer(handler)
    result = await scorer.score("q", ["a"])
    assert len(attempts) == 2
    assert result.scores == (1.0,)
    await scorer.aclose()


async def test_a_shard_that_fails_twice_leaves_exactly_its_own_candidates_unscored():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "c2" in body["questions"]:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(200, json=_answers(body))

    scorer = _scorer(handler, per_request=1)
    result = await scorer.score("q", ["a", "b", "c"])
    # None for the failed shard only: unscored is neither kept nor dropped, and the two
    # shards that answered are not thrown away with it.
    assert result.scores == (1.0, None, 1.0)
    await scorer.aclose()


async def test_a_pass_in_which_every_shard_failed_raises_for_the_caller_to_degrade():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    scorer = _scorer(handler, per_request=1)
    with pytest.raises(RuntimeError):
        await scorer.score("q", ["a", "b"])
    await scorer.aclose()


async def test_a_client_error_is_final_and_not_retried():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400, json={"error": "bad request"})

    scorer = _scorer(handler)
    with pytest.raises(RuntimeError):
        await scorer.score("q", ["a"])
    assert len(attempts) == 1
    await scorer.aclose()


async def test_no_candidates_means_no_request_at_all():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    scorer = _scorer(handler)
    result = await scorer.score("q", [])
    assert result.scores == () and result.input_tokens == 0
    await scorer.aclose()


async def test_the_adapter_never_logs_candidate_text(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=_answers(body))

    secret = "Mei LIN's unlisted address at example.com"
    scorer = _scorer(handler)
    with caplog.at_level("DEBUG"):
        await scorer.score("where does she live?", [secret])
    assert secret not in caplog.text
    await scorer.aclose()


def test_the_adapter_refuses_to_exist_without_a_key_or_a_model():
    with pytest.raises(ValueError):
        TypeSafeEvidenceScorer("typesafe/jev-1.13-20260917", "")
    with pytest.raises(ValueError):
        TypeSafeEvidenceScorer("", "test-key")


async def test_invalid_numeric_answers_are_unscored_instead_of_confident_evidence():
    values = ["NaN", "Infinity", "-Infinity", -1, 4, True, 1.5]

    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=_answers(body, dict(zip(body["questions"], values))))

    scorer = _scorer(handler)
    try:
        result = await scorer.score("q", [f"synthetic {i}" for i in range(len(values))])
        assert result.scores == (None, None, None, None, None, None, 0.5)
    finally:
        await scorer.aclose()


async def test_equal_means_retain_different_uncertainty_without_changing_scores():
    def handler(request):
        return httpx.Response(200, json={
            "model": "typesafe/jev-1.13-20260917",
            "answers": {
                "c1": {"score": 1, "confidence": 1,
                       "probabilities": {"0": 0, "1": 1, "2": 0, "3": 0}},
                "c2": {"score": 1, "confidence": 0.1,
                       "probabilities": {"0": 0.5, "1": 0, "2": 0.5, "3": 0}},
            },
        })

    scorer = _scorer(handler)
    try:
        result = await scorer.score("q", ["synthetic A", "synthetic B"])
        assert result.scores == (1 / 3, 1 / 3)
        assert result.details[0].confidence == 1
        assert result.details[1].confidence == 0.1
        assert result.details[0].probabilities == (0, 1, 0, 0)
        assert result.details[1].probabilities == (0.5, 0, 0.5, 0)
        assert result.details[0].model == "typesafe/jev-1.13-20260917"
        assert result.rubric_id
    finally:
        await scorer.aclose()


async def test_concurrent_questions_share_one_adapter_concurrency_budget():
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return httpx.Response(200, json=_answers(json.loads(request.content)))
        finally:
            active -= 1

    scorer = _scorer(handler, concurrency=2, per_request=1)
    try:
        results = await asyncio.gather(*(scorer.score("q", ["a", "b"]) for _ in range(3)))
        assert all(r.scores == (1.0, 1.0) for r in results)
        assert peak <= 2
    finally:
        await scorer.aclose()


async def test_long_retry_after_does_not_trigger_an_early_retry():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "busy"})

    scorer = _scorer(handler, call_timeout=1)
    try:
        with pytest.raises(RuntimeError):
            await scorer.score("q", ["synthetic"])
        assert attempts == 1
    finally:
        await scorer.aclose()


async def test_retry_after_seconds_is_respected_without_sleeping_in_the_test(monkeypatch):
    attempts = 0
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=_answers(json.loads(request.content)))

    monkeypatch.setattr(asyncio, "sleep", sleep)
    scorer = _scorer(handler)
    try:
        assert (await scorer.score("q", ["synthetic"])).scores == (1.0,)
        assert sleeps == [2]
    finally:
        await scorer.aclose()


async def test_missing_or_invalid_optional_diagnostics_do_not_discard_valid_scores():
    def handler(request):
        return httpx.Response(200, json={"answers": {
            "c1": {"score": 2},
            "c2": {"score": 2, "confidence": "NaN",
                   "probabilities": {"0": 0.1, "1": 0.1, "2": 0.1, "3": 0.1}},
        }})

    scorer = _scorer(handler)
    try:
        result = await scorer.score("q", ["a", "b"])
        assert result.scores == (2 / 3, 2 / 3)
        assert all(d.confidence is None and d.probabilities == () for d in result.details)
        assert all(d.model is None for d in result.details)
        assert result.requested_model == "typesafe/jev-1.13-20260917"
    finally:
        await scorer.aclose()


async def test_shard_diagnostics_stay_aligned_across_failure_and_provider_versions():
    def handler(request):
        body = json.loads(request.content)
        if "c2" in body["questions"]:
            return httpx.Response(503)
        payload = _answers(body)
        payload["model"] = "synthetic/version-a" if "c1" in body["questions"] else "synthetic/version-b"
        return httpx.Response(200, json=payload)

    scorer = _scorer(handler, per_request=1, retries=0)
    try:
        result = await scorer.score("q", ["a", "b", "c"])
        assert result.details[0].model == "synthetic/version-a"
        assert result.details[1] is None
        assert result.details[2].model == "synthetic/version-b"
    finally:
        await scorer.aclose()


async def test_cancellation_releases_the_shared_concurrency_slot():
    entered = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json=_answers(json.loads(request.content)))

    scorer = _scorer(handler, concurrency=1)
    try:
        task = asyncio.create_task(scorer.score("q", ["a"]))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await asyncio.wait_for(scorer.score("q", ["b"]), 1)
        assert result.scores == (1.0,)
    finally:
        await scorer.aclose()


@pytest.mark.parametrize("value,enabled", [(0.97, True), (0.6, False), (0.1, False), ("NaN", False)])
async def test_source_clock_policy_uses_only_the_question_and_parses_intent_with_period(value, enabled):
    def handler(request):
        body = json.loads(request.content)
        assert body["state"] == {"question": "What changed in yesterday's notes?"}
        assert body["questions"]["source_clock"]["type"] == "noul"
        assert body["questions"]["source_period"]["type"] == "choice"
        return httpx.Response(200, json={"answers": {"source_clock": {"noul": value},
            "source_period": {"choice": "yesterday", "confidence": 0.94}},
                                        "usage": {"input_tokens": 31}})

    scorer = _scorer(handler)
    try:
        decision = await scorer.source_clock_policy("What changed in yesterday's notes?")
        assert decision.use_source_clocks is enabled
        assert decision.input_tokens == 31
        assert decision.period == "yesterday" and decision.period_confidence == 0.94
    finally:
        await scorer.aclose()


async def test_policy_outage_reports_unavailable_instead_of_a_negative_intent():
    scorer = _scorer(lambda request: httpx.Response(503), retries=0)
    try:
        decision = await scorer.source_clock_policy("What happened today?")
        assert decision.use_source_clocks is False and decision.probability is None
        assert decision.policy_id
    finally:
        await scorer.aclose()


async def test_policy_timeout_releases_budget_and_reports_unavailable():
    async def handler(request):
        await asyncio.sleep(1)
        raise AssertionError("the policy should have been cancelled")

    scorer = _scorer(handler, call_timeout=0.01, concurrency=1)
    try:
        decision = await asyncio.wait_for(scorer.source_clock_policy("today's notes?"), 0.2)
        assert decision.probability is None
        assert not scorer._semaphore.locked()
    finally:
        await scorer.aclose()
