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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .artifacts import load_git_trajectory, load_preset_trajectory
from .errors import EvalDependencyError, EvalInputError
from .metrics.common import char_similarity
from .qa import build_http_answerer, build_llm_judge, qa_metrics_async
from .scorecard import build_scorecard, write_outputs
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


def evaluate(args: argparse.Namespace) -> int:
    if args.preset:
        trajectory = load_preset_trajectory(args.preset)
    else:
        trajectory = load_git_trajectory(args.git_repo)
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
    )
    json_path, report_path = write_outputs(scorecard, args.out)
    qa = scorecard["groups"]["F_usability_qa"]
    summary = {
        "bundle": scorecard["bundle"]["id"],
        "mode": scorecard["mode"],
        "checkpoints": scorecard["bundle"]["checkpoints"],
        "claims_at_head": scorecard["bundle"]["claims_at_head"],
        "findings": len(scorecard["findings"]),
        "unavailable": len(scorecard["unavailable"]),
        "qa_status": qa.get("status"),
        "qa_accuracy": qa.get("accuracy"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OK: scorecard → {json_path}")
    print(f"OK: report    → {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pneuma_knowledge_eval.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("evaluate", help="evaluate a compiled knowledge trajectory")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--preset", type=Path, help="a shipped preset bundle directory")
    source.add_argument("--git-repo", type=Path, help="a canonical git repository directory")
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
        help="judge model for answers the mechanical arm rejected (default: EVAL_JUDGE_MODEL)",
    )
    run.add_argument(
        "--no-judge",
        action="store_true",
        help="run group F on character containment alone and record judge_used=false",
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
