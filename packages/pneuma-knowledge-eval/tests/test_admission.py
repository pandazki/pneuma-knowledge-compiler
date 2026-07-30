"""Group B: the truth-set adapter, the trajectory axis, and the mismatch refusal."""

from __future__ import annotations

import json

import pytest

from _fixtures import FROZEN_V2_TRUTH, claim, document, source, trajectory
from pneuma_knowledge_eval.errors import EvalDependencyError, EvalInputError
from pneuma_knowledge_eval.metrics.admission import (
    admission_latency,
    admission_metrics,
    noise_exclusion,
    noise_support,
    supersession_correctness,
    truth_recall_series,
)
from pneuma_knowledge_eval.metrics.common import normalize_text
from pneuma_knowledge_eval.truth import (
    BatchWindow,
    NegativeControl,
    Supersession,
    TruthEntry,
    TruthSet,
    load_84d_truth_set,
    load_content_classes,
    load_frozen_truth_manifest,
)

FACT = "The pilot is fixed-price and runs for two weeks."
LATE_FACT = "Acceptance needs twenty reviewed questions."
NOISE = "The product will be renamed next week."
OLD_DECISION = "Build a generic meeting-summary tool first."
NEW_DECISION = "Build the cited retrieval path first."


def _truth() -> TruthSet:
    from datetime import datetime, timezone

    def at(day: int) -> datetime:
        return datetime(2026, 3, day, 10, 0, tzinfo=timezone.utc)

    return TruthSet(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(
            TruthEntry("t-fact", "durable_facts", FACT, "current", at(2)),
            TruthEntry("t-late", "commitments", LATE_FACT, "current", at(2)),
            TruthEntry("t-old", "decisions", OLD_DECISION, "superseded", at(2)),
            TruthEntry("t-new", "decisions", NEW_DECISION, "current", at(9)),
        ),
        negatives=(NegativeControl("n-rename", NOISE, "chatter only"),),
        supersessions=(Supersession("sup-1", "t-old", "t-new", at(9)),),
        batches=(
            BatchWindow("B01", at(2), at(8)),
            BatchWindow("B02", at(9), at(15)),
        ),
    )


def _trajectory():
    """Round 1 admits one fact; round 2 admits the late one and the replacement decision."""
    first = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim(FACT, "aaaa0001", cite="s1 ¶0")]
        )
    }
    second = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md",
            [
                claim(FACT, "aaaa0001", cite="s1 ¶0"),
                claim(LATE_FACT, "aaaa0002", cite="s2 ¶1"),
                claim(NEW_DECISION, "aaaa0003", cite="s2 ¶2"),
            ],
        )
    }
    return trajectory([first, second])


def test_recall_is_a_series_and_names_the_round_each_fact_first_appeared():
    report = truth_recall_series(_trajectory(), _truth())
    assert [row["recall"] for row in report["series"]] == [pytest.approx(1 / 3), 1.0]
    assert report["first_match_round"]["t-fact"] == "r01"
    assert report["first_match_round"]["t-late"] == "r02"
    assert report["head_recall"] == 1.0
    assert report["degraded_from_peak"] == 0.0
    # the superseded entry is excluded from the recall denominator
    assert report["series"][0]["total"] == 3


def test_degradation_from_peak_is_visible_when_a_fact_stops_being_expressed():
    """A HEAD-only evaluation cannot see this: recall is 1.0, then the fact is rewritten past
    recognition and recall falls. The peak/head delta is the whole point of the time axis."""
    expressed = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim(FACT, "bbbb0001", cite="s1 ¶0")]
        )
    }
    buried = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim("Pilot details were discussed.", "bbbb0002", cite="s1 ¶0")]
        )
    }
    truth = TruthSet(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(TruthEntry("t-fact", "durable_facts", FACT, "current", None),),
    )
    report = truth_recall_series(trajectory([expressed, buried]), truth)
    assert report["peak_recall"] == 1.0
    assert report["head_recall"] == 0.0
    assert report["degraded_from_peak"] == 1.0


# ──────────────────────────────────────────────────────── the judge arm over recall


#: The failure the judge arm exists for, written out: the same fact as `FACT`, threaded into
#: prose. Character overlap lands below the truth threshold; the fact is stated exactly.
REWRITTEN_FACT = (
    "Scope was settled at the kickoff: the engagement runs on a single agreed price for a "
    "fourteen-day window, with no hourly billing and no option to extend the calendar."
)


def _one_fact_truth() -> TruthSet:
    return TruthSet(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(TruthEntry("t-fact", "durable_facts", FACT, "current", None),),
    )


def _rewritten_trajectory():
    """One round, one claim: the fact, restated well enough that characters miss it."""
    return trajectory(
        [
            {
                "memory/topics/pilot.md": document(
                    "memory/topics/pilot.md", [claim(REWRITTEN_FACT, "eeee0001", cite="s1 ¶0")]
                )
            }
        ]
    )


def test_the_similarity_arm_alone_misses_a_correctly_rewritten_fact():
    """The premise of the whole arm, asserted rather than assumed: this is what 0/N looked
    like on a base that states the fact perfectly."""
    report = truth_recall_series(_rewritten_trajectory(), _one_fact_truth())
    assert report["head_recall"] == 0.0
    assert report["arms"] == ["similarity"]
    # and it says the second arm did not run, rather than letting one number stand for both
    assert report["recall_judged"]["status"] == "unavailable"
    assert report["recall_judged"]["cause"] == "no_judge_arm"
    assert report["recall_similarity"]["head"] == 0.0


def test_a_fact_below_the_threshold_that_the_judge_accepts_counts_in_recall_judged():
    consulted: list[tuple[str, str]] = []

    def judge(statement: str, claim: str) -> tuple[bool, str]:
        consulted.append((statement, claim))
        return True, "YES\nthe claim states the price basis and the two-week window"

    report = truth_recall_series(_rewritten_trajectory(), _one_fact_truth(), judge=judge)

    # the judge saw the labelled fact and the best-matching claim, and nothing else
    assert consulted == [(FACT, REWRITTEN_FACT)]
    assert report["arms"] == ["similarity", "judge"]
    # both numbers are reported, and they disagree — which is the finding
    assert report["recall_similarity"]["head"] == 0.0
    assert report["head_recall"] == 0.0  # the historical spelling keeps its historical meaning
    assert report["recall_judged"]["head"] == 1.0
    assert report["recall_judged"]["matched_at_head"] == 1
    assert report["recall_judged"]["judge_decisions"] == 1
    assert report["recall_judged"]["judge_calls"] == 1
    assert report["series"][-1]["matched"] == 0
    assert report["series"][-1]["matched_judged"] == 1
    assert report["series"][-1]["by_category_judged"]["durable_facts"]["recall"] == 1.0


def test_a_fact_the_judge_also_rejects_stays_a_miss():
    def judge(statement: str, claim: str) -> tuple[bool, str]:
        return False, "NO\nthe claim names the topic without stating the fact"

    report = truth_recall_series(_rewritten_trajectory(), _one_fact_truth(), judge=judge)

    assert report["recall_judged"]["status"] == "ok"
    assert report["recall_judged"]["head"] == 0.0
    assert report["recall_judged"]["judge_decisions"] == 1
    miss = report["misses_at_head"][0]
    assert miss["judge_pass"] is False
    assert miss["matched_judged"] is False
    assert "NO" in miss["judge_rationale"]  # the verdict is auditable, not just counted


def test_the_judge_is_never_asked_about_a_fact_the_threshold_already_accepted():
    """The arm can only ADD recognized facts. Letting it review passes would let a judge
    remove a fact the corpus and the characters both agree is there."""
    consulted: list[str] = []

    def judge(statement: str, claim: str) -> tuple[bool, str]:  # pragma: no cover - must not run
        consulted.append(statement)
        return False, "NO"

    verbatim = trajectory(
        [{"memory/topics/p.md": document("memory/topics/p.md", [claim(FACT, "eeee0002")])}]
    )
    report = truth_recall_series(verbatim, _one_fact_truth(), judge=judge)

    assert consulted == []
    assert report["recall_similarity"]["head"] == report["recall_judged"]["head"] == 1.0
    assert report["recall_judged"]["judge_decisions"] == 0


def test_a_judge_failure_raises_instead_of_degrading_to_the_similarity_arm():
    def judge(statement: str, claim: str) -> tuple[bool, str]:
        raise RuntimeError("connection reset")

    with pytest.raises(EvalDependencyError, match="judge arm failed"):
        truth_recall_series(_rewritten_trajectory(), _one_fact_truth(), judge=judge)


def test_a_fact_with_no_candidate_claim_at_all_is_not_handed_to_the_judge():
    """A best match of zero means the base offered nothing for this fact. Showing the judge an
    arbitrary claim would be inventing the candidate the metric is supposed to find."""
    consulted: list[str] = []

    def judge(statement: str, claim: str) -> tuple[bool, str]:
        consulted.append(claim)
        return True, "YES"

    unrelated = trajectory(
        [
            {
                "memory/topics/q.md": document(
                    "memory/topics/q.md", [claim("氣候很好。", "eeee0003")]
                )
            }
        ]
    )
    report = truth_recall_series(unrelated, _one_fact_truth(), judge=judge)

    assert consulted == []
    assert report["recall_judged"]["head"] == 0.0
    assert report["recall_judged"]["judge_no_candidate"] == 1


def test_the_judge_is_asked_once_per_distinct_pair_across_a_long_trajectory():
    """Canonical is forward-only, so the same (fact, best claim) pair recurs every round. One
    verdict, one model call — otherwise a 170-round trajectory pays 170 times for one answer."""
    calls: list[str] = []

    def judge(statement: str, claim: str) -> tuple[bool, str]:
        calls.append(claim)
        return True, "YES"

    files = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim(REWRITTEN_FACT, "eeee0004", cite="s1 ¶0")]
        )
    }
    report = truth_recall_series(trajectory([files] * 6), _one_fact_truth(), judge=judge)

    assert len(calls) == 1
    assert report["recall_judged"]["judge_calls"] == 1
    assert report["recall_judged"]["judge_decisions"] == 6
    assert [row["recall_judged"] for row in report["series"]] == [1.0] * 6


def test_the_judge_reaches_recall_only_and_group_b_reports_both_numbers():
    def judge(statement: str, claim: str) -> tuple[bool, str]:
        return True, "YES"

    report = admission_metrics(_rewritten_trajectory(), _one_fact_truth(), judge=judge)

    assert report["recall"]["recall_similarity"]["head"] == 0.0
    assert report["recall"]["recall_judged"]["head"] == 1.0
    # noise exclusion turns on a labelled statement being FOUND, where a false positive costs
    # more than a false negative: it keeps the character threshold alone
    assert report["noise_exclusion"]["status"] == "ok"
    assert "judge" not in json.dumps(report["noise_exclusion"])


def test_a_guarded_mention_of_exhaust_is_not_a_leak():
    leaked = {
        "memory/topics/x.md": document("memory/topics/x.md", [claim(NOISE, "cccc0001")])
    }
    guarded = {
        "memory/topics/x.md": document(
            "memory/topics/x.md",
            [claim(f"旧设想（已废弃）：{NOISE}", "cccc0002")],
        )
    }
    report = noise_exclusion(trajectory([leaked, guarded]), _truth())
    assert report["series"][0]["unguarded_leaks"] == 1
    assert report["series"][1]["unguarded_leaks"] == 0
    assert report["series"][1]["guarded_mentions"] == 1
    assert report["invariants"]["no_unguarded_leak_at_head"] is True
    assert report["invariants"]["no_unguarded_leak_ever"] is False


def test_latency_is_measured_in_rounds_against_the_intake_batch():
    report = admission_latency(_trajectory(), _truth())
    assert report["round_axis_aligned"] is True
    by_id = {row["truth_id"]: row for row in report["details"]}
    assert by_id["t-fact"]["lag_rounds"] == 0
    assert by_id["t-late"]["lag_rounds"] == 1
    assert by_id["t-new"]["effective_batch"] == "B02"
    assert by_id["t-new"]["lag_rounds"] == 0
    assert report["same_round_admissions"] == 2


def test_latency_is_unavailable_without_intake_windows():
    truth = TruthSet(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(TruthEntry("t-fact", "durable_facts", FACT, "current", None),),
    )
    report = admission_latency(_trajectory(), truth)
    assert report["status"] == "unavailable"
    assert "no intake batch windows" in report["reason"]


def test_supersession_requires_the_replacement_and_the_retirement():
    report = supersession_correctness(_trajectory(), _truth())
    assert report["series"][0]["correct"] == 0  # replacement not yet present
    assert report["series"][1]["correct"] == 1
    assert report["head"]["accuracy"] == 1.0


def test_group_is_unavailable_rather_than_zero_without_a_truth_set():
    report = admission_metrics(_trajectory(), None)
    assert report["status"] == "unavailable"
    assert "labelled" in report["reason"]
    assert "recall" not in report


def test_group_entry_point_reports_the_bound_truth_set():
    report = admission_metrics(_trajectory(), _truth())
    assert report["truth_set"]["current_entries"] == 3
    assert report["recall"]["head_recall"] == 1.0
    assert report["latency"]["status"] == "ok"


# ─────────────────────────────────────────────────────── the shipped labelled corpora


def test_the_84d_corpus_loads_with_its_intake_windows(corpus_84d):
    truth = load_84d_truth_set(corpus_84d)
    assert truth.corpus_key
    assert len(truth.batches) == 12
    assert len(truth.entries) > 0
    assert len(truth.current_entries()) < len(truth.entries)  # some are superseded
    assert truth.negatives and truth.supersessions and truth.retrieval_cases
    # Facts, decisions and constraints carry the effective timestamp latency needs, and each
    # lands inside an intake window. Commitments record a DUE date rather than an
    # admissibility date, so they stay undated instead of being dated by proxy.
    datable = [
        entry for entry in truth.entries if entry.category != "commitments"
    ]
    assert datable
    assert all(truth.batch_index_for(entry.effective_at) is not None for entry in datable)
    assert all(
        entry.effective_at is None
        for entry in truth.entries
        if entry.category == "commitments"
    )


def test_the_frozen_v2_manifest_loads_through_the_same_shape():
    if not FROZEN_V2_TRUTH.is_file():  # pragma: no cover - ships with the repo
        pytest.skip("frozen v2 truth asset missing")
    truth = load_frozen_truth_manifest(FROZEN_V2_TRUTH)
    assert truth.experiment_id == "opc-84d-v2"
    assert truth.batches == ()  # the frozen asset declares no intake index
    assert all(entry.effective_at is not None for entry in truth.entries)


def test_a_truth_set_with_dangling_references_is_rejected():
    with pytest.raises(EvalInputError, match="unknown truth"):
        TruthSet(
            experiment_id="broken",
            corpus_key="broken",
            entries=(TruthEntry("t-a", "decisions", "A", "current", None),),
            supersessions=(Supersession("sup-x", "t-a", "t-missing", None),),
        )


def test_corpus_mismatch_is_the_callers_guard_not_a_silent_zero(corpus_84d):
    """The 84d labels against another corpus's canonical would score ~0 and read as a
    catastrophic finding. Group B computes it, but the corpus key is what makes the
    mismatch detectable — see the CLI's --require-corpus."""
    truth = load_84d_truth_set(corpus_84d)
    report = truth_recall_series(_trajectory(), truth)
    assert report["head_recall"] == 0.0
    assert truth.corpus_key != "fixture"


# ───────────────────────────────────────────── over-inclusion against corpus content classes

SIGNAL_BLOCK = "The pilot is fixed-price and runs for two weeks, agreed by both sides."
NOISE_BLOCK = "The rice delivery can be paused until Wednesday noon."
AMBIGUOUS_BLOCK = "Someone asked about the invoice again this morning."


def _classified_truth(**overrides) -> TruthSet:
    base = dict(
        experiment_id="fixture",
        corpus_key="fixture",
        entries=(TruthEntry("t-fact", "durable_facts", FACT, "current", None),),
        content_classes={
            normalize_text(SIGNAL_BLOCK): "signal",
            normalize_text(NOISE_BLOCK): "noise",
            normalize_text(AMBIGUOUS_BLOCK): "ambiguous",
        },
    )
    base.update(overrides)
    return TruthSet(**base)


def _classified_trajectory():
    """One claim per evidence class, plus one that threads noise together with signal."""
    files = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md",
            [
                claim("The pilot is fixed price.", "aaaa0001", cite="s1 ¶0"),
                claim("The rice delivery is paused.", "aaaa0002", cite="s1 ¶1"),
                claim("An invoice question is open.", "aaaa0003", cite="s1 ¶2"),
                claim("Pilot terms, with a delivery note.", "aaaa0004", cite="s1 ¶0-¶1"),
                claim("Unsupported by any citation.", "aaaa0005"),
            ],
        )
    }
    sources = {"s1": source("s1", [SIGNAL_BLOCK, NOISE_BLOCK, AMBIGUOUS_BLOCK])}
    return trajectory([files], sources=sources, consumed=[["s1"]])


def test_over_inclusion_counts_only_claims_whose_whole_basis_is_exhaust():
    """A claim that threads a noise block together with real evidence is doing its job; a claim
    whose entire basis is exhaust is the admission error."""
    report = noise_support(_classified_trajectory(), _classified_truth())
    head = report["head"]
    assert report["status"] == "ok"
    # 4 of the 5 claims have a resolvable citation; the uncited one is not judged.
    assert head["claims_judged"] == 4
    assert head["claims_total"] == 5
    assert head["claims_noise_only"] == 1  # only the rice-delivery claim
    assert head["claims_citing_any_noise"] == 2  # plus the one that also cites signal
    assert head["noise_only_rate"] == 0.25
    assert head["cited_block_classes"] == {"signal": 2, "noise": 2, "ambiguous": 1}
    assert head["claims_with_unknown_support"] == 0
    assert [row["anchor"] for row in report["noise_only_claims_at_head"]] == ["aaaa0002"]
    assert report["documents_at_head"] == {"memory/topics/pilot.md": 1}
    assert report["invariants"]["no_noise_only_claim_at_head"] is False


def test_over_inclusion_is_unavailable_without_labels_rather_than_reporting_zero():
    """No labels must not read as "no over-inclusion" — the two are opposite conclusions."""
    unlabelled = _classified_truth(content_classes={})
    report = noise_support(_classified_trajectory(), unlabelled)
    assert report["status"] == "unavailable"
    assert "content_class" in report["reason"]
    assert noise_support(_classified_trajectory(), None)["status"] == "unavailable"


def test_over_inclusion_never_assumes_an_unmatched_block_is_signal():
    """A ¶ block whose text matches no authored label is reported as unmatched, so the
    authoring-to-ingest reformatting gap is visible instead of resolved in the compiler's
    favour."""
    truth = _classified_truth(
        content_classes={normalize_text(NOISE_BLOCK): "noise"}
    )
    report = noise_support(_classified_trajectory(), truth)
    head = report["head"]
    assert head["cited_block_classes"]["unmatched"] == 3
    # Only the claim citing the noise block ALONE qualifies. The claim citing noise together
    # with an unmatched block is excluded: an unlabelled block could be signal, and letting it
    # stand in for one would inflate the very number this metric exists to report.
    assert head["claims_noise_only"] == 1
    assert [row["anchor"] for row in report["noise_only_claims_at_head"]] == ["aaaa0002"]
    assert head["claims_with_unknown_support"] == 3


def test_over_inclusion_is_unavailable_without_l0():
    report = noise_support(
        trajectory([{"memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("X.", "aaaa0001")])}]),
        _classified_truth(),
    )
    assert report["status"] == "unavailable"
    assert "L0" in report["reason"]


def test_content_class_labels_load_structurally_from_authored_json(tmp_path):
    """Matched by shape (authorship.content_class + a text key), not by source family, so a new
    family needs no loader change."""
    (tmp_path / "G01.json").write_text(
        json.dumps(
            {
                "sources": {
                    "meetings": [
                        {
                            "utterances": [
                                {
                                    "text": SIGNAL_BLOCK,
                                    "authorship": {"content_class": "signal"},
                                }
                            ]
                        }
                    ],
                    "brand_new_family": [
                        {
                            "items": [
                                {
                                    "full_text": NOISE_BLOCK,
                                    "authorship": {"content_class": "noise"},
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    labels = load_content_classes(tmp_path)
    assert labels[normalize_text(SIGNAL_BLOCK)] == "signal"
    assert labels[normalize_text(NOISE_BLOCK)] == "noise"


def test_content_class_loader_refuses_an_unlabelled_corpus(tmp_path):
    (tmp_path / "G01.json").write_text(json.dumps({"sources": {}}), encoding="utf-8")
    with pytest.raises(EvalInputError, match="content_class"):
        load_content_classes(tmp_path)
    with pytest.raises(EvalInputError, match="no content-class corpus"):
        load_content_classes(tmp_path / "missing")


def test_over_inclusion_reaches_the_group_b_entry_point():
    groups = admission_metrics(_classified_trajectory(), _classified_truth())
    assert groups["noise_support"]["head"]["claims_noise_only"] == 1
