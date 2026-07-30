"""Group F: the suite over injected arms, and the refusals that keep `full` honest."""

from __future__ import annotations

import pytest

from pneuma_knowledge_eval.errors import EvalDependencyError
from pneuma_knowledge_eval.qa import (
    QaCase,
    build_http_answerer,
    build_llm_judge,
    cases_from_truth,
    qa_metrics,
    qa_metrics_async,
    run_qa_suite,
)
from pneuma_knowledge_eval.truth import RetrievalCase, TruthEntry, TruthSet

FACT = "The pilot is fixed-price and runs for two weeks."
DECISION = "Build the cited retrieval path first."


def _truth() -> TruthSet:
    return TruthSet(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(
            TruthEntry("t-fact", "durable_facts", FACT, "current", None),
            TruthEntry("t-decision", "decisions", DECISION, "current", None),
        ),
        retrieval_cases=(
            RetrievalCase("q-fact", "What shape is the pilot?", ("t-fact",), None),
            RetrievalCase("q-both", "What was decided about the pilot?", ("t-fact", "t-decision"), None),
        ),
    )


def test_cases_come_from_the_corpus_not_from_a_model():
    cases = cases_from_truth(_truth())
    assert [case.case_id for case in cases] == ["q-fact", "q-both"]
    assert cases[0].category == "durable_facts"
    assert cases[1].category == "mixed"  # spans two labelled categories


async def test_mechanical_containment_alone_can_pass_a_case():
    async def answerer(question: str, as_of: str | None) -> str:
        return f"Short answer: {FACT}"

    report = await run_qa_suite(
        [QaCase("q-fact", "What shape is the pilot?", (FACT,), ("durable_facts",))],
        answerer=answerer,
    )
    assert report["accuracy"] == 1.0
    assert report["judge_used"] is False
    assert report["cases"][0]["checks"][0]["mechanical_pass"] is True


async def test_the_judge_is_only_consulted_after_the_mechanical_check_fails():
    consulted: list[str] = []

    async def answerer(question: str, as_of: str | None) -> str:
        return "It is a two-week engagement billed at a flat rate."

    async def judge(question: str, expected: str, answer: str) -> tuple[bool, str]:
        consulted.append(expected)
        return True, "YES\nthe answer states the duration and the flat rate"

    report = await run_qa_suite(
        [QaCase("q-fact", "What shape is the pilot?", (FACT,), ("durable_facts",))],
        answerer=answerer,
        judge=judge,
    )
    assert consulted == [FACT]
    assert report["accuracy"] == 1.0
    assert report["judge_decided_checks"] == 1
    assert report["cases"][0]["checks"][0]["mechanical_pass"] is False


async def test_a_missing_expected_statement_fails_the_whole_case():
    async def answerer(question: str, as_of: str | None) -> str:
        return FACT  # says nothing about the decision

    report = await run_qa_suite(
        [QaCase("q-both", "What was decided?", (FACT, DECISION), ("durable_facts", "decisions"))],
        answerer=answerer,
    )
    assert report["accuracy"] == 0.0
    assert report["by_category"]["mixed"]["total"] == 1


async def test_an_empty_suite_is_unavailable_rather_than_a_perfect_score():
    async def answerer(question: str, as_of: str | None) -> str:  # pragma: no cover
        return ""

    report = await run_qa_suite([], answerer=answerer)
    assert report["status"] == "unavailable"


def test_mechanical_mode_skips_the_group_and_says_why():
    report = qa_metrics(_truth(), mode="mechanical")
    assert report["status"] == "skipped"
    assert "zero-LLM" in report["reason"]


def test_full_mode_without_an_answerer_refuses_instead_of_degrading():
    with pytest.raises(EvalDependencyError, match="no answerer"):
        qa_metrics(_truth(), mode="full")


def test_full_mode_without_a_truth_set_is_unavailable():
    report = qa_metrics(None, mode="full")
    assert report["status"] == "unavailable"


async def test_the_async_face_actually_asks_the_questions():
    """`qa_metrics` can only ever answer `pending` for the one configuration that CAN produce
    a number, which left group F unreachable from every synchronous caller — the CLI
    included. `qa_metrics_async` is the face that runs it."""

    async def answerer(question: str, as_of: str | None) -> str:
        return f"Both: {FACT} And: {DECISION}"

    pending = qa_metrics(_truth(), mode="full", answerer=answerer)
    assert pending["status"] == "pending"

    report = await qa_metrics_async(_truth(), mode="full", answerer=answerer)
    assert report["group"] == "F_usability_qa"
    assert report["status"] == "ok"
    assert report["accuracy"] == 1.0
    assert report["cases_total"] == 2


async def test_the_async_face_keeps_every_refusal_of_the_sync_shell():
    async def answerer(question: str, as_of: str | None) -> str:  # pragma: no cover
        return ""

    assert (await qa_metrics_async(_truth(), mode="mechanical"))["status"] == "skipped"
    assert (await qa_metrics_async(None, mode="full", answerer=answerer))["status"] == "unavailable"
    with pytest.raises(EvalDependencyError, match="no answerer"):
        await qa_metrics_async(_truth(), mode="full")


async def test_the_as_of_label_reaches_the_answerer_verbatim():
    """A question labelled `as_of` is a question about a moment; dropping it would score the
    answer against today's canonical instead of the one the label names."""
    seen: list[str | None] = []

    async def answerer(question: str, as_of: str | None) -> str:
        seen.append(as_of)
        return FACT

    await run_qa_suite(
        [QaCase("q", "When?", (FACT,), ("durable_facts",), as_of="2026-03-30T00:00:00")],
        answerer=answerer,
    )
    assert seen == ["2026-03-30T00:00:00"]


def test_live_arms_refuse_without_their_dependencies(monkeypatch):
    with pytest.raises(EvalDependencyError, match="base url"):
        build_http_answerer("", "u-x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EvalDependencyError, match="OPENROUTER_API_KEY"):
        build_llm_judge()


def test_judge_prose_lives_in_the_prompt_catalog():
    """Every model-visible sentence in this framework is addressable by catalog key, including
    the evaluator's own — otherwise a deployment cannot audit or replace it."""
    from pneuma_knowledge_core.prompts import catalog, prompt

    keys = set(catalog())
    assert {"eval.qa.judge_system", "eval.qa.judge_user", "eval.qa.judge_verdict_yes"} <= keys
    rendered = prompt("eval.qa.judge_user", question="Q?", expected="E", answer="A")
    assert "Q?" in rendered and "E" in rendered and "A" in rendered
