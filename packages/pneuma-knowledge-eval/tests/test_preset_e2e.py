"""End-to-end mechanical evaluation of a runtime-built preset bundle.

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
    assert scorecard["bundle"]["id"] == "generic-eval-fixture"
    assert scorecard["mode"] == "mechanical"
    assert (tmp_path / "out" / "report.md").is_file()
    assert "OK: scorecard" in capsys.readouterr().out


def test_cli_runs_group_f_against_a_live_answer_url(
    tmp_path, preset_bundle, labelled_corpus, capsys, monkeypatch
):
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

    def fake_truth_judge(statement: str, claim: str) -> tuple[bool, str]:
        return False, "NO\nthe claim does not carry the fact"

    monkeypatch.setattr(cli, "build_http_answerer", fake_answerer)
    monkeypatch.setattr(cli, "build_llm_judge", lambda **_: fake_judge)
    monkeypatch.setattr(cli, "build_truth_judge", lambda **_: fake_truth_judge)
    # full mode's embedding arm is a network call; group F does not use it.
    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)

    exit_code = cli.main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(labelled_corpus),
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
    assert {user for user, _ in asked} == {"generic-eval-fixture"}
    assert '"qa_accuracy": 0.0' in capsys.readouterr().out


def test_cli_full_mode_still_refuses_when_no_answerer_is_configured(
    tmp_path, preset_bundle, labelled_corpus, capsys, monkeypatch
):
    """Adding a way to supply the arm must not add a way to skip it silently.

    The embedding arm and group B's judge arm are stubbed out so the ONE missing arm under test
    is the answerer; otherwise this passes on another arm's missing key and never reaches
    group F.
    """
    from pneuma_knowledge_eval import cli

    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)
    monkeypatch.setattr(
        cli, "build_truth_judge", lambda **_: (lambda statement, claim: (False, "NO"))
    )
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(labelled_corpus),
            "--mode",
            "full",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "no answerer" in capsys.readouterr().err


def test_cli_full_mode_gives_group_b_a_judge_arm_and_reports_both_recalls(
    tmp_path, preset_bundle, labelled_corpus, capsys, monkeypatch
):
    """Full mode must reach group B's judge arm through the same wiring group F uses, and the
    scorecard must carry BOTH recall numbers — the similarity arm keeps its historical meaning,
    the judged arm is a second number beside it, never a replacement for it."""
    from pneuma_knowledge_eval import cli

    seen: list[tuple[str, str]] = []

    def fake_truth_judge(statement: str, claim: str) -> tuple[bool, str]:
        seen.append((statement, claim))
        return True, "YES\nthe claim carries the fact"

    async def fake_answer(question: str, as_of: str | None) -> str:
        return "no idea"

    async def fake_judge(question: str, expected: str, answer: str) -> tuple[bool, str]:
        return False, "NO"

    monkeypatch.setattr(cli, "build_http_answerer", lambda *a, **k: fake_answer)
    monkeypatch.setattr(cli, "build_llm_judge", lambda **_: fake_judge)
    monkeypatch.setattr(cli, "build_truth_judge", lambda **_: fake_truth_judge)
    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)

    exit_code = cli.main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(labelled_corpus),
            "--mode",
            "full",
            "--answer-url",
            "http://127.0.0.1:9",
            "--out",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    recall = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))["groups"][
        "B_admission"
    ]["recall"]
    assert recall["arms"] == ["similarity", "judge"]
    assert recall["recall_similarity"]["status"] == "ok"
    assert recall["recall_judged"]["status"] == "ok"
    # this judge approves everything, so the judged arm is total and the similarity arm is not:
    # the gap between the two IS the reading the arm exists to produce
    assert recall["recall_judged"]["head"] == 1.0
    assert recall["recall_similarity"]["head"] < 1.0
    # one model call per distinct (fact, claim) pair; repeated pairs are cacheable.
    assert recall["recall_judged"]["judge_calls"] == len(seen) == len(set(seen))
    assert recall["recall_judged"]["judge_decisions"] >= len(seen)
    out = capsys.readouterr().out
    assert '"recall_judged": 1.0' in out


def test_cli_no_judge_opts_both_arms_out_without_pretending_either_ran(
    tmp_path, preset_bundle, labelled_corpus, monkeypatch
):
    """`--no-judge` is an explicit opt-out, so it must read as one: group B reports
    `recall_judged` unavailable with its reason rather than echoing the similarity number."""
    from pneuma_knowledge_eval import cli

    async def fake_answer(question: str, as_of: str | None) -> str:
        return "no idea"

    monkeypatch.setattr(cli, "build_http_answerer", lambda *a, **k: fake_answer)
    monkeypatch.setattr(cli, "_build_matcher", lambda mode, trajectory, truth: char_similarity)

    exit_code = cli.main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(labelled_corpus),
            "--mode",
            "full",
            "--answer-url",
            "http://127.0.0.1:9",
            "--no-judge",
            "--out",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    scorecard = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))
    recall = scorecard["groups"]["B_admission"]["recall"]
    assert recall["arms"] == ["similarity"]
    assert recall["recall_judged"]["status"] == "unavailable"
    assert "--no-judge" in recall["recall_judged"]["reason"]
    assert scorecard["groups"]["F_usability_qa"]["judge_used"] is False
    assert "B_admission.recall.recall_judged" in {
        row["metric"] for row in scorecard["unavailable"]
    }


# ─────────────────────────────────────────── --git-repo, with and without its L0 half


def _unpacked_repo(bundle, into):
    import tarfile

    repo = into / "canonical"
    repo.mkdir(parents=True)
    with tarfile.open(bundle / "canonical.tar.gz", "r:gz") as tar:
        tar.extractall(repo, filter="data")
    return repo


def test_cli_git_repo_without_l0_names_every_metric_that_did_not_run(tmp_path, preset_bundle, capsys):
    """The regression this closes: `--git-repo` published a scorecard that looked complete while
    five metrics had silently not run. They are now in the scorecard's `unavailable` list AND in
    the command's own closing words on stderr, with the flag that supplies them."""
    repo = _unpacked_repo(preset_bundle, tmp_path / "bare")

    exit_code = main(["evaluate", "--git-repo", str(repo), "--out", str(tmp_path / "out")])

    assert exit_code == 0
    scorecard = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))
    l0_absent = {row["metric"] for row in scorecard["unavailable"] if row["cause"] == "l0_absent"}
    assert l0_absent == {
        "A_grounded.citations.locator_replay",
        "C_layering.compression",
        "C_layering.verbatim_reproduction",
        "D_navigability.growth",
    }  # B's L0 metric needs a truth set to be reached at all
    captured = capsys.readouterr()
    assert '"l0_sources": 0' in captured.out
    assert "no L0 sources" in captured.err
    for metric in l0_absent:
        assert metric in captured.err
    assert "--pg-dumps" in captured.err


def test_cli_git_repo_with_pg_dumps_computes_them_and_stays_quiet(tmp_path, preset_bundle, capsys):
    """The other half: the same repo, the same command, plus the dumps directory — every L0
    metric computes and there is nothing left to warn about."""
    repo = _unpacked_repo(preset_bundle, tmp_path / "whole")

    exit_code = main(
        [
            "evaluate",
            "--git-repo",
            str(repo),
            "--pg-dumps",
            str(preset_bundle / "pg"),
            "--out",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    scorecard = json.loads((tmp_path / "out" / "scorecard.json").read_text("utf-8"))
    assert [row for row in scorecard["unavailable"] if row["cause"] == "l0_absent"] == []
    assert scorecard["bundle"]["sources"] > 0 and scorecard["bundle"]["l0_blocks"] > 0
    groups = scorecard["groups"]
    assert groups["A_grounded"]["citations"]["locator_replay"]["status"] == "ok"
    assert groups["C_layering"]["compression"]["status"] == "ok"
    assert groups["D_navigability"]["growth"]["status"] == "ok"
    captured = capsys.readouterr()
    assert "no L0 sources" not in captured.err


def test_cli_git_repo_with_pg_dumps_matches_the_preset_scorecard(tmp_path, preset_bundle, preset_trajectory):
    """Two loaders, one trajectory: the numbers must not depend on which door they came in
    through. Only the bundle id and the loading provenance differ."""
    from pneuma_knowledge_eval.scorecard import build_scorecard
    from pneuma_knowledge_eval.artifacts import load_repo_trajectory

    repo = _unpacked_repo(preset_bundle, tmp_path / "same")
    loaded = load_repo_trajectory(
        repo, pg_dumps=preset_bundle / "pg", bundle_id=preset_trajectory.bundle_id
    )

    mine = build_scorecard(loaded, mode="mechanical")
    theirs = build_scorecard(preset_trajectory, mode="mechanical")
    for card in (mine, theirs):
        card.pop("generated_at")
        card["bundle"].pop("origin")
    assert json.dumps(mine, sort_keys=True) == json.dumps(theirs, sort_keys=True)


def test_cli_refuses_pg_dumps_alongside_a_preset(tmp_path, preset_bundle, capsys):
    """A preset already carries its own pg/. Accepting a second set would pair one user's
    canonical with another user's L0 and report the resulting nonsense as compression."""
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--pg-dumps",
            str(preset_bundle / "pg"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "--pg-dumps applies to --git-repo" in capsys.readouterr().err


def test_cli_refuses_a_truth_set_from_another_corpus(
    tmp_path, preset_bundle, labelled_corpus, capsys
):
    """Binding one corpus's labels to another corpus's canonical would score near zero and read
    as a quality finding. The guard makes the mismatch a loud input error instead."""
    exit_code = main(
        [
            "evaluate",
            "--preset",
            str(preset_bundle),
            "--truth",
            str(labelled_corpus),
            "--require-corpus",
            "some-other-corpus",
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "not the requested" in capsys.readouterr().err
