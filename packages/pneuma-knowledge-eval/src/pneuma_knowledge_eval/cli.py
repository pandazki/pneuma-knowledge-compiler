"""`python -m pneuma_knowledge_eval.cli` — the evaluation entry point.

    uv run python -m pneuma_knowledge_eval.cli evaluate \
        --preset examples/data/preset/u-opc-lin --mode mechanical --out var/eval

Mechanical mode is offline and deterministic: same bundle in, same `scorecard.json` out
(modulo the generation timestamp). Full mode adds the embedding matcher and the judge arm and
REFUSES to run when their credentials are absent, rather than reporting mechanical numbers
under the `full` label.

Group F needs one thing the other five groups do not: something to ask. Point `--answer-url`
at a running service for the tenant that owns these artifacts and the labelled questions are
asked over its live recall path:

    uv run python -m pneuma_knowledge_eval.cli evaluate \
        --git-repo data/canonical/<user> --truth <corpus-or-manifest> --mode full \
        --answer-url http://127.0.0.1:8000 --out var/eval

Without `--answer-url`, `--mode full` with a truth set fails loudly instead of publishing a
five-group scorecard under the six-group label.

L0 AND `--git-repo`
-------------------
A canonical repo is the compiled layer only. Five metrics need the raw sources it does not
carry — citation replay, compression, verbatim reproduction, growth, admission
over-inclusion — so `--git-repo` alone leaves them uncomputed. Two things follow, and both are
implemented here rather than left to the reader:

  * they are named. Every one lands in the scorecard's `unavailable` list with cause
    `l0_absent`, and this command's last words on stderr are the list of what a missing L0
    cost. A scorecard quietly missing five metrics looks exactly like one that has them.
  * they are supplyable. `--pg-dumps <dir>` takes the same `pg/*.json.gz` table dumps a preset
    bundle ships, so a live canonical repo plus a dumps directory is a complete trajectory:

        uv run python -m pneuma_knowledge_eval.cli evaluate \
            --git-repo data/canonical/<user> --pg-dumps <bundle>/pg --out var/eval

There is deliberately no live-Postgres flag. Exporting a bundle from a live stack is an
existing path, and a read-only evaluator that opens its own database connection is a second
way for the same numbers to be produced.

One thing about the evaluated subject cannot be read off their artifacts: the language their
knowledge base is supposed to be written in. It is a setting in their profile, so it is passed
in — `--declared-language zh-CN` — and group C holds every claim to it. Omitted, English, which
is the same default the compile contract states to the model for a subject who declared none.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .artifacts import load_preset_trajectory, load_repo_trajectory
from .errors import EvalDependencyError, EvalInputError
from .metrics.common import L0_ABSENT, char_similarity
from .qa import (
    TruthJudge,
    build_http_answerer,
    build_llm_judge,
    build_truth_judge,
    qa_metrics_async,
)
from .scorecard import build_scorecard, unavailable_because, write_outputs
from .truth import load_truth_set


def _build_matcher(mode: str, trajectory, truth):
    """The mechanical matcher, or the embedding-augmented one when `full` is requested.

    Mirrors the existing evaluator's rule: the score is `max(char, embedding)`, so adding the
    embedding arm can only recognize MORE true matches, never fewer.
    """
    if mode == "mechanical":
        return char_similarity
    from .embedding import build_embedding_matcher, collect_texts

    return build_embedding_matcher(collect_texts(trajectory, truth))


def _build_qa(args: argparse.Namespace, trajectory, truth) -> dict | None:
    """Group F, run against a live recall path — or left to the synchronous shell.

    The answer arm is scored on character containment plus the judge, NOT on the embedding
    matcher: group B's matcher is built over claim and truth texts, and an answer's prose was
    never embedded, so handing it over would silently score every answer on characters while
    labelling it semantic.
    """
    if args.mode != "full" or not args.answer_url:
        return None
    answerer = build_http_answerer(
        args.answer_url,
        args.answer_user or trajectory.bundle_id,
        mode=args.answer_mode,
    )
    judge = None if args.no_judge else build_llm_judge(model=args.judge_model)
    return asyncio.run(
        qa_metrics_async(truth, mode=args.mode, answerer=answerer, judge=judge)
    )


def _build_truth_judge(args: argparse.Namespace, truth) -> TruthJudge | None:
    """Group B's entailment arm — full mode, truth set bound, judge not opted out of.

    Raises through `build_truth_judge` when credentials are absent. That is the point: a full
    run that cannot reach the judge must not publish the similarity arm's recall as if the
    stronger arm had agreed with it.
    """
    if args.mode != "full" or truth is None or args.no_judge:
        return None
    return build_truth_judge(model=args.judge_model)


def _report_l0_gap(scorecard: dict) -> None:
    """Name, on stderr, every metric a missing L0 half cost — and how to supply it.

    The scorecard already carries this (each metric's own `unavailable` entry), but a caller
    reads the summary and the exit code. An evaluation that silently returned five fewer
    metrics than it looks like it returned is the failure mode this whole package is against.
    """
    missing = unavailable_because(scorecard, L0_ABSENT)
    if not missing:
        return
    print(
        f"WARNING: this trajectory carries no L0 sources, so {len(missing)} metric(s) were "
        "NOT computed:",
        file=sys.stderr,
    )
    for row in missing:
        print(f"  - {row['metric']}: {row['reason']}", file=sys.stderr)
    print(
        "  supply the raw sources with --pg-dumps <dir> (the pg/*.json.gz dumps a preset "
        "bundle ships) to compute them.",
        file=sys.stderr,
    )


def evaluate(args: argparse.Namespace) -> int:
    if args.preset:
        if args.pg_dumps:
            raise EvalInputError(
                "--pg-dumps applies to --git-repo: a preset bundle already carries its own pg/ "
                "dumps, and taking a second set would evaluate one user's canonical against "
                "another's L0"
            )
        trajectory = load_preset_trajectory(args.preset)
    else:
        trajectory = load_repo_trajectory(args.git_repo, pg_dumps=args.pg_dumps)
    truth = (
        load_truth_set(args.truth, content_classes=args.content_classes)
        if args.truth
        else None
    )
    if truth is not None and args.require_corpus and truth.corpus_key != args.require_corpus:
        raise EvalInputError(
            f"truth set corpus {truth.corpus_key!r} is not the requested "
            f"{args.require_corpus!r}: a truth set from another corpus scores near zero and "
            "reads as a quality finding"
        )
    scorecard = build_scorecard(
        trajectory,
        mode=args.mode,
        truth=truth,
        matcher=_build_matcher(args.mode, trajectory, truth),
        qa=_build_qa(args, trajectory, truth),
        declared_language=args.declared_language,
        truth_judge=_build_truth_judge(args, truth),
    )
    json_path, report_path = write_outputs(scorecard, args.out)
    qa = scorecard["groups"]["F_usability_qa"]
    recall = (scorecard["groups"]["B_admission"].get("recall") or {}) if truth else {}
    judged = recall.get("recall_judged") or {}
    summary = {
        "bundle": scorecard["bundle"]["id"],
        "mode": scorecard["mode"],
        "checkpoints": scorecard["bundle"]["checkpoints"],
        "claims_at_head": scorecard["bundle"]["claims_at_head"],
        "l0_sources": scorecard["bundle"]["sources"],
        "findings": len(scorecard["findings"]),
        "unavailable": len(scorecard["unavailable"]),
        "l0_absent_metrics": [row["metric"] for row in unavailable_because(scorecard, L0_ABSENT)],
        "recall_similarity": recall.get("head_recall"),
        "recall_judged": judged.get("head") if judged.get("status") == "ok" else None,
        "qa_status": qa.get("status"),
        "qa_accuracy": qa.get("accuracy"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OK: scorecard → {json_path}")
    print(f"OK: report    → {report_path}")
    _report_l0_gap(scorecard)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pneuma_knowledge_eval.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("evaluate", help="evaluate a compiled knowledge trajectory")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--preset", type=Path, help="a shipped preset bundle directory")
    source.add_argument("--git-repo", type=Path, help="a canonical git repository directory")
    run.add_argument(
        "--pg-dumps",
        type=Path,
        help="directory of pg/*.json.gz table dumps (same format a preset bundle ships) "
        "supplying the L0 half --git-repo cannot carry: sources, blocks, per-round consumption, "
        "compile events, evolve tasks. Without it, five metrics report unavailable by name",
    )
    run.add_argument("--mode", choices=("mechanical", "full"), default="mechanical")
    run.add_argument(
        "--truth",
        type=Path,
        help="labelled corpus directory or frozen truth manifest (enables group B)",
    )
    run.add_argument(
        "--require-corpus",
        help="fail unless the truth set declares this corpus key (mismatch guard)",
    )
    run.add_argument(
        "--content-classes",
        type=Path,
        help="directory of authored corpus JSON carrying authorship.content_class labels; "
        "enables the admission over-inclusion metric (B.noise_support)",
    )
    run.add_argument(
        "--declared-language",
        help="the evaluated subject's own language setting (their profile's locale.language, "
        "e.g. zh-CN); group C holds every claim to it. Default: en, which is the framework's "
        "default for a subject who declared none",
    )
    run.add_argument(
        "--answer-url",
        help="base url of a running service; enables group F over its live recall path",
    )
    run.add_argument(
        "--answer-user",
        help="tenant to ask; defaults to the evaluated bundle id",
    )
    run.add_argument(
        "--answer-mode",
        choices=("fast", "deep"),
        default="fast",
        help="recall mode the questions are asked in (the rag-only ablation is a hit list, "
        "not an answer, so it is not offered here)",
    )
    run.add_argument(
        "--judge-model",
        help="judge model for both judge arms — group F's answers and group B's claims — that "
        "the character matcher rejected (default: EVAL_JUDGE_MODEL)",
    )
    run.add_argument(
        "--no-judge",
        action="store_true",
        help="run both judged arms on character matching alone: group F records "
        "judge_used=false and group B reports recall_judged as unavailable with its reason",
    )
    run.add_argument("--out", type=Path, required=True, help="output directory")
    run.set_defaults(handler=evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (EvalInputError, EvalDependencyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
