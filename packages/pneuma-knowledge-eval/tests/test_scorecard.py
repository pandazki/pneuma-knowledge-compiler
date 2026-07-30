"""Scorecard assembly: no overall score, explicit unavailability, findings with evidence."""

from __future__ import annotations

import json

import pytest

from _fixtures import claim, document, source, trajectory
from pneuma_knowledge_eval.scorecard import (
    SCORECARD_SCHEMA,
    build_scorecard,
    render_report,
    write_outputs,
)

SOURCES = {"s1": source("s1", ["block zero", "block one"])}


def _trajectory():
    first = {
        "memory/profile.md": document(
            "memory/profile.md", [claim("Owner works alone.", "aaaa0001", cite="s1 ¶0")]
        )
    }
    second = {
        "memory/profile.md": document(
            "memory/profile.md",
            [claim("Owner works alone.", "aaaa0001", cite="s1 ¶0")],
            links=["topics/pilot.md"],
        ),
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim("The pilot is fixed price.", "aaaa0002", cite="s1 ¶1")]
        ),
    }
    return trajectory([first, second], sources=SOURCES, consumed=[["s1"], ["s1"]])


def test_scorecard_holds_six_groups_and_no_overall_score():
    """A weighted total would invent a trade-off nobody decided and hide the pattern this
    package exists to expose: impeccably grounded, completely unnavigable."""
    scorecard = build_scorecard(_trajectory())
    assert scorecard["schema"] == SCORECARD_SCHEMA
    assert set(scorecard["groups"]) == {
        "A_grounded",
        "B_admission",
        "C_layering",
        "D_navigability",
        "E_evolution",
        "F_usability_qa",
    }
    assert "score" not in scorecard
    assert "overall" not in scorecard
    assert json.loads(json.dumps(scorecard, ensure_ascii=False))  # JSON-serializable


def test_every_uncomputable_metric_is_listed_with_a_reason():
    scorecard = build_scorecard(_trajectory())
    metrics = {row["metric"]: row for row in scorecard["unavailable"]}
    assert "B_admission" in metrics  # no truth set bound
    assert "F_usability_qa" in metrics  # mechanical mode
    assert all(row["reason"] or row["status"] for row in scorecard["unavailable"])


def test_findings_name_the_metric_the_value_and_why_it_matters():
    scorecard = build_scorecard(_trajectory())
    assert scorecard["findings"]
    for finding in scorecard["findings"]:
        assert set(finding) == {"metric", "severity", "observed", "why"}
        assert finding["why"]


def test_the_declared_language_reaches_group_c_and_defaults_to_english():
    """Group C holds the claims to the language the base is DECLARED to be in — the subject's own
    setting, which only the entry point knows. Unstated, English: the same default the compile
    contract states to the model, so the evaluation and the compile agree on the target."""
    default = build_scorecard(_trajectory())["groups"]["C_layering"]["language_consistency"]
    assert (default["declared_language"], default["declared_language_source"]) == (
        "en",
        "default",
    )
    assert default["head"]["diverged_from_declared"] == 0  # the fixture claims are English

    declared = build_scorecard(_trajectory(), declared_language="zh-CN")["groups"][
        "C_layering"
    ]["language_consistency"]
    assert declared["declared_script"] == "cjk"
    # every English claim in the fixture now counts against a Chinese-reading subject
    assert (
        declared["head"]["diverged_from_declared"] == declared["head"]["claims_total"] > 0
    )
    assert declared["head"]["declared_language_rate"] == 0.0
    findings = {row["metric"] for row in build_scorecard(_trajectory(), declared_language="zh-CN")["findings"]}
    assert "C.language_consistency.diverged_from_declared" in findings


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown evaluation mode"):
        build_scorecard(_trajectory(), mode="approximate")


def test_report_renders_the_series_tables_and_the_findings():
    scorecard = build_scorecard(_trajectory())
    report = render_report(scorecard)
    assert "## A · grounded" in report
    assert "## C · layering" in report
    assert "## D · navigability" in report
    assert "## E · evolution" in report
    assert "## Findings" in report
    assert "| r01 |" in report and "| r02 |" in report


def test_write_outputs_emits_both_artifacts(tmp_path):
    scorecard = build_scorecard(_trajectory())
    json_path, report_path = write_outputs(scorecard, tmp_path / "out")
    assert json.loads(json_path.read_text("utf-8"))["bundle"]["checkpoints"] == 2
    assert report_path.read_text("utf-8").startswith("# Evaluation scorecard")


def test_a_precomputed_group_f_lands_in_the_scorecard_and_clears_the_coverage_finding():
    """Asking a live recall path a question cannot happen inside a pure sync function, so an
    async caller hands the finished group in. It must be reported as group F, not appended
    next to it, and must stop being listed as missing coverage."""
    qa = {
        "group": "F_usability_qa",
        "status": "ok",
        "threshold": 0.62,
        "judge_used": True,
        "cases_correct": 1,
        "cases_total": 2,
        "accuracy": 0.5,
        "by_category": {"durable_facts": {"correct": 1, "total": 2, "accuracy": 0.5}},
        "judge_decided_checks": 1,
        "cases": [
            {
                "case_id": "q-one",
                "category": "durable_facts",
                "question": "Q?",
                "answer": "A",
                "checks": [{"correct": True}],
                "correct": True,
            },
            {
                "case_id": "q-two",
                "category": "durable_facts",
                "question": "Q?",
                "answer": "A",
                "checks": [{"correct": False}],
                "correct": False,
            },
        ],
    }
    scorecard = build_scorecard(_trajectory(), mode="full", qa=qa)
    assert scorecard["groups"]["F_usability_qa"]["accuracy"] == 0.5
    assert "F_usability_qa" not in {row["metric"] for row in scorecard["unavailable"]}
    assert "F.usability_qa" not in {row["metric"] for row in scorecard["findings"]}
    report = render_report(scorecard)
    assert "## F · usability QA" in report
    assert "| q-one | durable_facts | yes | 1/1 |" in report


def test_a_bound_truth_set_renders_its_admission_series(corpus_84d):
    """Group B was readable only by opening scorecard.json; a bound truth set is exactly the
    input the report exists to show."""
    from pneuma_knowledge_eval.truth import load_truth_set

    scorecard = build_scorecard(_trajectory(), truth=load_truth_set(corpus_84d))
    report = render_report(scorecard)
    assert "## B · admission" in report
    assert "truth set: `opc-84d-relayforge`" in report
    assert "head recall:" in report


def test_mechanical_mode_is_deterministic():
    """Same bundle in, same numbers out — the property that makes the mode CI-runnable."""
    first = build_scorecard(_trajectory())
    second = build_scorecard(_trajectory())
    first.pop("generated_at")
    second.pop("generated_at")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
