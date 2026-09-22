"""The evaluator keeps labels out of inputs and keeps missing scores out of negatives."""

import pytest
from datetime import datetime

from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScores, SourceClockDecision
from pneuma_knowledge_eval.evidence_scoring import compare, evaluate_source_clock_policy, evaluate_source_time_scope


async def test_comparison_passes_only_question_and_candidates_and_alternates_order():
    calls = []

    class Scorer:
        async def score(self, question, candidates):
            calls.append((question, candidates))
            return EvidenceScores((0.9, None), 10)

    case = {"id": "synthetic", "question": "q", "expected": [True, False],
            "modes": {"before": ["a", "b"], "after": ["a + clock", "b + clock"]}}
    rows = await compare(Scorer(), [case], repeats=2)
    assert [r["mode"] for r in rows] == ["before", "after", "after", "before"]
    assert calls == [("q", case["modes"][r["mode"]]) for r in rows]
    assert all(r["tp"] == 1 and r["unscored"] == 1 and r["tn"] == 0 for r in rows)


async def test_misaligned_fixture_fails_before_any_call():
    with pytest.raises(ValueError, match="index-aligned"):
        await compare(object(), [{"id": "bad", "question": "q", "expected": [],
                                  "modes": {"before": ["a"], "after": []}}])


async def test_policy_evaluation_never_sends_labels_and_does_not_count_unknown_as_correct():
    class Policy:
        async def source_clock_policy(self, question):
            assert question == "What is Project Heron?"
            return SourceClockDecision()

    rows = await evaluate_source_clock_policy(Policy(), [
        {"id": "synthetic", "question": "What is Project Heron?", "expected": False},
    ])
    assert rows[0]["matches"] is None
    assert rows[0]["use_source_clocks"] is False


async def test_scope_evaluation_keeps_expected_dates_out_of_model_inputs():
    class Policy:
        async def source_clock_policy(self, question):
            assert question == "昨天记录了什么？"
            return SourceClockDecision(True, 0.95, 12, "synthetic", "yesterday", 0.9)

    case = {"id": "synthetic", "question": "昨天记录了什么？", "status": "resolved",
            "start": "2026-09-20", "end": "2026-09-20"}
    rows = await evaluate_source_time_scope(Policy(), [case],
        as_of=datetime.fromisoformat("2026-09-21T01:00:00+00:00"), zone="Asia/Shanghai")
    assert rows[0]["matches"] is True
    assert rows[0]["decision"]["input_tokens"] == 12


async def test_scope_evaluation_does_not_count_policy_outage_as_correct_abstention():
    class Policy:
        async def source_clock_policy(self, question):
            raise TimeoutError("synthetic")

    rows = await evaluate_source_time_scope(Policy(), [
        {"id": "synthetic", "question": "recently?", "status": "unresolved"},
    ], as_of=datetime(2026, 9, 21))
    assert rows[0]["matches"] is None and rows[0]["actual"]["status"] == "unavailable"
