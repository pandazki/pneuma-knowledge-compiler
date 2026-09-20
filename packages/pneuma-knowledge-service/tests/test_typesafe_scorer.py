"""TypeSafe evidence scorer: request shape, sharding, the 0–3 → 0–1 mapping, failure.

The request shape is not cosmetic here. Candidates are addressed by NAMED KEYS because
index addressing measurably costs the model accuracy, and one score question per candidate
is what makes the scores independent — so both are asserted on the wire, not trusted to a
comment. The rest is the port's contract: a failed shard is unscored (not zero), a pass in
which every shard failed raises, and usage sums across shards.

Keyless: every request is served by `httpx.MockTransport`.
"""

from __future__ import annotations

import json

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
