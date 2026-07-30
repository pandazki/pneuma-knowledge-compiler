"""End-to-end mechanical evaluation of the shipped preset bundle.

These assertions are deliberately about EXISTENCE, DENOMINATORS and INVARIANTS rather than
exact values. A golden number would break the moment the preset is regenerated with a better
compiler — which is the outcome the whole package exists to encourage — so what is locked here
is that every rate has a non-zero denominator, every series spans the whole trajectory, and
the invariants the mechanism actually promises hold.

The one place a concrete number appears is `manifest.json`'s own counts, which the loader
already reconciles against: those are the bundle's self-declared identity, not a quality
expectation.
"""

from __future__ import annotations

import json

from pneuma_knowledge_eval.cli import main
from pneuma_knowledge_eval.metrics.common import char_similarity
from pneuma_knowledge_eval.scorecard import build_scorecard, render_report


def test_mechanical_evaluation_of_the_preset_is_complete_and_grounded(preset_trajectory):
    scorecard = build_scorecard(preset_trajectory, mode="mechanical")
    rounds = len(preset_trajectory.checkpoints)
    groups = scorecard["groups"]

    # every series covers the whole trajectory (or the transitions between rounds)
    assert len(groups["A_grounded"]["citations"]["series"]) == rounds
    assert len(groups["A_grounded"]["anchors"]["series"]) == rounds - 1
    assert len(groups["C_layering"]["compression"]["series"]) == rounds
    assert len(groups["D_navigability"]["reachability"]["series"]) == rounds
    assert len(groups["E_evolution"]["response"]["pressure"]["series"]) == rounds

    citations = groups["A_grounded"]["citations"]
    head = citations["head"]
    assert citations["l0_available"] is True
    assert head["claims_total"] > 0
    assert head["citations_total"] > 0  # the resolvability denominator is real
    assert head["citations_resolvable"] == head["citations_total"]
    assert head["unparsable_marker_residue"] == 0
    assert 0.0 < head["claim_coverage"] <= 1.0

    anchors = groups["A_grounded"]["anchors"]
    assert anchors["invariants"]["no_repo_wide_anchor_loss"] is True
    assert anchors["invariants"]["anchor_floor_is_monotone"] is True
    assert anchors["invariants"]["no_document_dropped"] is True

    links = groups["A_grounded"]["links"]
    assert links["head"]["dead"] == 0 and links["head"]["self"] == 0


def test_preset_layering_and_navigability_report_real_denominators(preset_trajectory):
    groups = build_scorecard(preset_trajectory, mode="mechanical")["groups"]

    compression = groups["C_layering"]["compression"]
    assert compression["status"] == "ok"
    for row in compression["series"]:
        assert row["l0_chars"] > 0
        assert row["prose_chars"] > 0
        assert row["compression_ratio"] > 0

    verbatim = groups["C_layering"]["verbatim_reproduction"]
    assert verbatim["head"]["claims_judged"] > 0  # the transcription-rate denominator

    reach = groups["D_navigability"]["reachability"]
    assert reach["head"]["documents"] > 1
    assert reach["basis"] == "retrieval_hit_seeded"
    # Every seed reaches at least itself, so the rate has a real, non-degenerate denominator
    # whether or not this bundle happens to link well.
    assert 0.0 < reach["head"]["mean_reach_rate"] <= 1.0
    assert reach["head"]["dead_end_documents"] <= reach["head"]["documents"]
    assert 0.0 <= reach["head"]["orphan_claim_rate"] <= 1.0

    glance = groups["D_navigability"]["glance"]
    assert glance["status"] == "ok"
    assert glance["documents_at_head"] == len(preset_trajectory.head.files)
    assert glance["families_declared"] == len(preset_trajectory.path_templates)
    assert glance["within_budget"] is True

    structure = groups["D_navigability"]["structure"]
    assert structure["families_available"] == len(preset_trajectory.path_templates)
    assert structure["claims_in_unowned_paths"] == 0  # path ownership held at every round
    assert sum(structure["family_claim_counts"].values()) == len(preset_trajectory.head.claims)


def test_preset_evolution_reports_absence_without_crashing_or_imputing(preset_trajectory):
    """The shipped bundle contains no evolve event. That must read as a stated absence with the
    pressure series intact, not as an empty section and not as a zero score."""
    groups = build_scorecard(preset_trajectory, mode="mechanical")["groups"]
    response = groups["E_evolution"]["response"]

    assert response["status"] == "no_evolution_events"
    assert response["verdict"] in {"aligned_restraint", "missed_pressure"}
    assert response["pressure"]["series"]
    assert all("catchall_share" in row for row in response["pressure"]["series"])
    assert groups["E_evolution"]["move_fidelity"]["status"] == "no_moves_observed"
    assert groups["E_evolution"]["schema_stability"]["invariants"] == {
        "family_floor_is_monotone": True,
        "anchor_floor_is_monotone": True,
    }


def test_preset_admission_and_qa_are_unavailable_not_zero(preset_trajectory):
    """No truth set is bound to this corpus, and mechanical mode asks no questions. Both must
    say so: a zero here would read as a catastrophic quality finding."""
    scorecard = build_scorecard(preset_trajectory, mode="mechanical")
    assert scorecard["groups"]["B_admission"]["status"] == "unavailable"
    assert scorecard["groups"]["F_usability_qa"]["status"] == "skipped"
    unavailable = {row["metric"] for row in scorecard["unavailable"]}
    assert {"B_admission", "F_usability_qa"} <= unavailable


def test_preset_report_renders(preset_trajectory):
    report = render_report(build_scorecard(preset_trajectory, mode="mechanical"))
    assert preset_trajectory.bundle_id in report
    assert report.count("| r") >= len(preset_trajectory.checkpoints)


def test_cli_writes_both_artifacts_for_the_shipped_preset(tmp_path, preset_bundle, capsys):
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--mode",
            "mechanical",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 0
    scorecard = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))
    assert scorecard["bundle"]["id"] == "u-opc-lin"
    assert scorecard["mode"] == "mechanical"
    assert (tmp_path / "out" / "report.md").is_file()
    assert "OK: scorecard" in capsys.readouterr().out


def test_cli_runs_group_f_against_a_live_answer_url(tmp_path, preset_bundle, corpus_84d, capsys, monkeypatch):
    """The regression this guards: `--mode full --truth ...` had no way to supply an answerer,
    so the six-group mode raised on group F and could never complete. The arms are faked here
    (the point is the wiring, not the network), but everything else is the real path."""
    from pneuma_knowledge_eval import cli

    asked: list[tuple[str, str | None]] = []

    def fake_answerer(base_url, user_id, *, mode="fast", timeout=120.0):
        assert base_url == "http://127.0.0.1:9" and mode == "fast"

        async def answer(question: str, as_of: str | None) -> str:
            asked.append((user_id, as_of))
            return "no idea"

        return answer

    async def fake_judge(question: str, expected: str, answer: str) -> tuple[bool, str]:
        return False, "NO\nthe answer carries nothing"

    monkeypatch.setattr(cli, "build_http_answerer", fake_answerer)
    monkeypatch.setattr(cli, "build_llm_judge", lambda **_: fake_judge)
    # full mode's embedding arm is a network call; group F does not use it.
    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)

    exit_code = cli.main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(corpus_84d),
            "--mode",
            "full",
            "--answer-url",
            "http://127.0.0.1:9",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 0
    scorecard = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))
    qa = scorecard["groups"]["F_usability_qa"]
    assert qa["status"] == "ok"
    assert qa["cases_total"] == len(asked) > 0
    assert qa["accuracy"] == 0.0  # every answer was "no idea"; nothing is imputed
    assert qa["judge_used"] is True and qa["judge_decided_checks"] > 0
    # the tenant defaults to the evaluated bundle, and the corpus's own as_of labels survive
    assert {user for user, _ in asked} == {"u-opc-lin"}
    assert '"qa_accuracy": 0.0' in capsys.readouterr().out


def test_cli_full_mode_still_refuses_when_no_answerer_is_configured(tmp_path, preset_bundle, corpus_84d, capsys, monkeypatch):
    """Adding a way to supply the arm must not add a way to skip it silently.

    The embedding arm is stubbed out so the ONE missing arm under test is the answerer;
    otherwise this passes on the embedding key's absence and never reaches group F.
    """
    from pneuma_knowledge_eval import cli

    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(corpus_84d),
            "--mode",
            "full",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "no answerer" in capsys.readouterr().err


def test_cli_refuses_a_truth_set_from_another_corpus(tmp_path, preset_bundle, corpus_84d, capsys):
    """Binding one corpus's labels to another corpus's canonical would score near zero and read
    as a quality finding. The guard makes the mismatch a loud input error instead."""
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(corpus_84d),
            "--require-corpus",
            "some-other-corpus",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "not the requested" in capsys.readouterr().err
