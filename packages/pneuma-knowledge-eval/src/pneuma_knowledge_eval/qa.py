"""Group F — usability: can the compiled structure answer the question without the raw text?

This is the outcome measurement, and it is deliberately the LAST group rather than the first.
Groups A-E measure properties of the artifact; F measures whether those properties buy
anything — accuracy by category over questions whose correct answers were labelled before
compilation. A structure that scores well on A-E and badly here is a well-formed structure
that does not work.

TWO ARMS, ONE SCORING RULE
--------------------------
An answer counts as correct when it carries the expected statement. The mechanical check is
normalized character containment (the same matcher group B uses); only when that fails is the
optional LLM judge consulted, because a judge that is asked first will happily approve an
answer the corpus never supported. Both arms are recorded per case, so a reader can see which
verdicts depended on the judge.

FAIL LOUD, NEVER DEGRADE
------------------------
This module never invents an arm it does not have. `mechanical` mode reports F as skipped:
answering requires a live recall path, and pretending otherwise would put a number under a
label it did not earn. `full` mode without an answerer or without judge credentials raises
`EvalDependencyError` instead of quietly falling back to string matching alone.

The ablation the design keeps in reserve (rag-only vs fused recall) drops straight into this
shape: run the suite twice with two answerers and diff the accuracy — the difference IS
canonical's marginal contribution to follow-the-thread.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pneuma_knowledge_core.prompts import prompt

from .errors import EvalDependencyError
from .metrics.common import Matcher, char_similarity, rate
from .truth import TRUTH_CATEGORIES, TruthSet

#: `(question, as_of) -> answer text`. A live service, a replayed transcript, or a fake.
Answerer = Callable[[str, str | None], Awaitable[str]]

#: `(question, expected, answer) -> (correct, rationale)`. Consulted only after the
#: mechanical check has already failed.
Judge = Callable[[str, str, str], Awaitable[tuple[bool, str]]]

#: Containment threshold for the mechanical arm. Lower than the truth-admission threshold on
#: purpose: an answer legitimately wraps the fact in prose, so the fact only has to be
#: recoverable from the answer, not to dominate it.
ANSWER_THRESHOLD = 0.62


@dataclass(frozen=True)
class QaCase:
    """One outcome question with the statements a correct answer must carry."""

    case_id: str
    question: str
    expected: tuple[str, ...]
    categories: tuple[str, ...]
    as_of: str | None = None

    @property
    def category(self) -> str:
        """The single category this case is reported under (`mixed` when it spans several)."""
        unique = sorted(set(self.categories))
        if len(unique) == 1:
            return unique[0]
        return "mixed"


def cases_from_truth(truth: TruthSet) -> tuple[QaCase, ...]:
    """Build the question suite from the corpus's own frozen retrieval cases.

    The questions are NOT model-generated: the corpus already ships human-reviewed questions
    with their expected truth ids, and generating new ones would put an unreviewed question
    set between the artifact and the score.
    """
    by_id = truth.by_id()
    cases: list[QaCase] = []
    for case in truth.retrieval_cases:
        entries = [by_id[tid] for tid in case.expected_truth_ids if tid in by_id]
        if not entries:
            continue
        cases.append(
            QaCase(
                case_id=case.case_id,
                question=case.question,
                expected=tuple(entry.value for entry in entries),
                categories=tuple(entry.category for entry in entries),
                as_of=case.as_of.isoformat() if case.as_of else None,
            )
        )
    return tuple(cases)


async def run_qa_suite(
    cases: Sequence[QaCase],
    *,
    answerer: Answerer,
    judge: Judge | None = None,
    matcher: Matcher = char_similarity,
    threshold: float = ANSWER_THRESHOLD,
) -> dict[str, Any]:
    """Ask every question, score every expected statement, report accuracy by category."""
    if not cases:
        return {"status": "unavailable", "reason": "the truth set ships no retrieval cases"}
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        answer = await answerer(case.question, case.as_of)
        checks: list[dict[str, Any]] = []
        for expected in case.expected:
            score = round(matcher(expected, answer), 6)
            mechanical = score >= threshold
            judged: bool | None = None
            rationale = ""
            if not mechanical and judge is not None:
                judged, rationale = await judge(case.question, expected, answer)
            checks.append(
                {
                    "expected": expected,
                    "score": score,
                    "mechanical_pass": mechanical,
                    "judge_pass": judged,
                    "judge_rationale": rationale,
                    "correct": bool(mechanical or judged),
                }
            )
        outcomes.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
                "answer": answer,
                "checks": checks,
                "correct": all(check["correct"] for check in checks),
            }
        )
    by_category: dict[str, Any] = {}
    for category in (*TRUTH_CATEGORIES, "mixed"):
        subset = [row for row in outcomes if row["category"] == category]
        if not subset:
            continue
        passed = sum(row["correct"] for row in subset)
        by_category[category] = {
            "correct": passed,
            "total": len(subset),
            "accuracy": rate(passed, len(subset)),
        }
    correct = sum(row["correct"] for row in outcomes)
    judged_checks = [
        check for row in outcomes for check in row["checks"] if check["judge_pass"] is not None
    ]
    return {
        "status": "ok",
        "threshold": threshold,
        "judge_used": judge is not None,
        "cases_correct": correct,
        "cases_total": len(outcomes),
        "accuracy": rate(correct, len(outcomes)),
        "by_category": by_category,
        "judge_decided_checks": len(judged_checks),
        "cases": outcomes,
    }


def qa_metrics(
    truth: TruthSet | None,
    *,
    mode: str,
    answerer: Answerer | None = None,
    judge: Judge | None = None,
) -> dict[str, Any]:
    """Group F entry point (synchronous shell).

    Returns a `skipped`/`unavailable` record for every configuration that cannot honestly
    produce a number, and raises for a `full` run that was asked for without its arm — the
    caller has to know it did not get what it requested.
    """
    if mode == "mechanical":
        return {
            "group": "F_usability_qa",
            "status": "skipped",
            "reason": (
                "outcome question answering needs a live recall path (and, for the judge arm, a "
                "model); mechanical mode is defined as zero-LLM and zero-network"
            ),
        }
    if truth is None:
        return {
            "group": "F_usability_qa",
            "status": "unavailable",
            "reason": "no truth set is bound: there are no labelled questions to ask",
        }
    if answerer is None:
        raise EvalDependencyError(
            "full mode requested group F but no answerer was supplied; pass a live recall "
            "endpoint (see build_http_answerer) or run --mode mechanical"
        )
    return {
        "group": "F_usability_qa",
        "status": "pending",
        "reason": "run_qa_suite is async; await qa_metrics_async to actually ask the questions",
        "cases": len(cases_from_truth(truth)),
        "judge_available": judge is not None,
    }


async def qa_metrics_async(
    truth: TruthSet | None,
    *,
    mode: str,
    answerer: Answerer | None = None,
    judge: Judge | None = None,
    matcher: Matcher = char_similarity,
    threshold: float = ANSWER_THRESHOLD,
) -> dict[str, Any]:
    """Group F, actually run — the async face `qa_metrics` can only promise.

    `qa_metrics` is a synchronous shell, so the one configuration that CAN produce a number
    (full mode, truth set bound, answerer supplied) could only ever come back as `pending`.
    That left the group unreachable from any synchronous caller, the CLI included. This
    entry point applies the identical refusals — same statuses, same reasons, same raise for
    a `full` run missing its arm — and then asks the questions.
    """
    gate = qa_metrics(truth, mode=mode, answerer=answerer, judge=judge)
    if gate.get("status") != "pending":
        return gate
    assert truth is not None and answerer is not None  # guaranteed by the gate above
    report = await run_qa_suite(
        cases_from_truth(truth),
        answerer=answerer,
        judge=judge,
        matcher=matcher,
        threshold=threshold,
    )
    return {"group": "F_usability_qa", **report}


# ───────────────────────────────────────────────────────────────────── the live arms


def build_http_answerer(
    base_url: str, user_id: str, *, mode: str = "fast", timeout: float = 120.0
) -> Answerer:
    """Answer through a running service's recall endpoint. Full mode only.

    Raises rather than degrading: no base url and no `httpx` are both hard failures, because
    the alternative is a suite that silently scores an empty answer for every question.
    """
    if not base_url:
        raise EvalDependencyError("build_http_answerer needs a service base url")
    try:
        import httpx
    except ModuleNotFoundError as exc:  # pragma: no cover - dev dependency present in CI
        raise EvalDependencyError(
            "the live QA arm needs httpx (install the eval package's dev extra)"
        ) from exc

    endpoint = f"{base_url.rstrip('/')}/v1/users/{user_id}/recall"

    async def answer(question: str, as_of: str | None) -> str:
        payload: dict[str, Any] = {"query": question, "mode": mode}
        if as_of:
            payload["as_of"] = as_of
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
        if isinstance(body, dict):
            return str(body.get("answer") or "")
        raise EvalDependencyError(
            f"recall endpoint returned a hit list, not an answer: mode={mode!r} is wrong for QA"
        )

    return answer


def build_llm_judge(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Judge:
    """An LLM judge for answers the mechanical arm rejected. Full mode only.

    The judge's prose lives in the prompt catalog under `eval.qa.*`, like every other
    model-visible surface in this framework, so a deployment can replace the judging language
    without forking the evaluator. Missing credentials raise: a judge that cannot be reached
    must not be reported as a judge that approved nothing.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EvalDependencyError(
            "the LLM judge arm needs OPENROUTER_API_KEY or OPENAI_API_KEY; mechanical mode "
            "requires neither"
        )
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:  # pragma: no cover - service dependency
        raise EvalDependencyError("the LLM judge arm needs langchain-openai") from exc

    chat = ChatOpenAI(
        model=model or os.environ.get("EVAL_JUDGE_MODEL") or "openai/gpt-4o-mini",
        api_key=key,
        base_url=base_url or os.environ.get("OPENROUTER_BASE_URL") or None,
        temperature=0,
    )
    verdict_yes = prompt("eval.qa.judge_verdict_yes").strip().lower()

    async def judge(question: str, expected: str, answer: str) -> tuple[bool, str]:
        response = await chat.ainvoke(
            [
                ("system", prompt("eval.qa.judge_system")),
                (
                    "human",
                    prompt(
                        "eval.qa.judge_user",
                        question=question,
                        expected=expected,
                        answer=answer,
                    ),
                ),
            ]
        )
        text = str(response.content).strip()
        first = text.splitlines()[0].strip().lower() if text else ""
        return first.startswith(verdict_yes), text

    return judge


__all__ = [
    "ANSWER_THRESHOLD",
    "Answerer",
    "Judge",
    "QaCase",
    "build_http_answerer",
    "build_llm_judge",
    "cases_from_truth",
    "qa_metrics",
    "qa_metrics_async",
    "run_qa_suite",
]
