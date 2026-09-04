#!/usr/bin/env python3
"""Compare two gold-free sanitized runs without emitting row-level content."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_RECORDS = 1382
FORBIDDEN_KEYS = {
    "question",
    "answer",
    "evidence",
    "evidence_messages",
    "matched_answer",
}
METRICS = ("llm_score", "f1_score", "bleu_score")
TRANSITIONS = ("0_to_0", "0_to_1", "1_to_0", "1_to_1")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline-scored", type=Path, required=True)
    cli.add_argument("--rerun-scored", type=Path, required=True)
    cli.add_argument("--baseline-official", type=Path, required=True)
    cli.add_argument("--rerun-official", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    return cli


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_forbidden(value: Any, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                found.add(key)
            find_forbidden(child, found)
    elif isinstance(value, list):
        for child in value:
            find_forbidden(child, found)
    return found


def load_rows(path: Path, expected: int = EXPECTED_RECORDS) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if find_forbidden(rows):
        raise ValueError(f"forbidden keys in sanitized input: {sorted(find_forbidden(rows))}")
    if len(rows) != expected or len({str(row["qa_id"]) for row in rows}) != expected:
        raise ValueError(f"expected {expected} unique sanitized rows")
    return rows


def empty_transitions() -> dict[str, int]:
    return {key: 0 for key in TRANSITIONS}


def build_comparison(
    baseline_rows: list[dict[str, Any]], rerun_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline = {str(row["qa_id"]): row for row in baseline_rows}
    rerun = {str(row["qa_id"]): row for row in rerun_rows}
    if len(baseline) != len(baseline_rows) or len(rerun) != len(rerun_rows):
        raise ValueError("duplicate qa_id")
    if set(baseline) != set(rerun):
        raise ValueError("baseline and rerun qa_id sets differ")

    transitions = empty_transitions()
    identical_prediction_transitions = empty_transitions()
    by_category: dict[str, dict[str, int]] = defaultdict(empty_transitions)
    by_modality: dict[str, dict[str, int]] = defaultdict(empty_transitions)
    changed = 0
    baseline_lengths: list[int] = []
    rerun_lengths: list[int] = []

    for qa_id in sorted(baseline):
        old = baseline[qa_id]
        new = rerun[qa_id]
        if str(old["category"]) != str(new["category"]):
            raise ValueError(f"category changed for {qa_id}")
        if bool(old["is_multi_modality"]) != bool(new["is_multi_modality"]):
            raise ValueError(f"modality changed for {qa_id}")
        old_score = int(float(old["llm_score"]))
        new_score = int(float(new["llm_score"]))
        if old_score not in (0, 1) or new_score not in (0, 1):
            raise ValueError(f"non-binary llm score for {qa_id}")
        transition = f"{old_score}_to_{new_score}"
        category = str(old["category"])
        modality = (
            "multimodal_available" if old["is_multi_modality"] else "text_only"
        )
        transitions[transition] += 1
        by_category[category][transition] += 1
        by_modality[modality][transition] += 1

        old_text = str(old["predicted_answer"])
        new_text = str(new["predicted_answer"])
        texts_differ = old_text != new_text
        changed += texts_differ
        if not texts_differ:
            identical_prediction_transitions[transition] += 1
        baseline_lengths.append(len(old_text))
        rerun_lengths.append(len(new_text))

    count = len(baseline)
    return {
        "record_count": count,
        "llm_score_transitions": transitions,
        "identical_prediction_llm_score_transitions": identical_prediction_transitions,
        "by_category": dict(sorted(by_category.items())),
        "by_modality": dict(sorted(by_modality.items())),
        "prediction_text": {
            "changed_count": changed,
            "identical_count": count - changed,
            "baseline_mean_chars": round(statistics.mean(baseline_lengths), 6),
            "rerun_mean_chars": round(statistics.mean(rerun_lengths), 6),
            "mean_chars_delta": round(
                statistics.mean(rerun_lengths) - statistics.mean(baseline_lengths), 6
            ),
            "baseline_median_chars": statistics.median(baseline_lengths),
            "rerun_median_chars": statistics.median(rerun_lengths),
        },
    }


def score_slice(bucket: dict[str, Any]) -> dict[str, float | int]:
    return {
        "count": int(bucket["count"]),
        **{f"{metric}_pct": round(100 * float(bucket[metric]), 6) for metric in METRICS},
    }


def compare_score_slice(
    baseline: dict[str, Any], rerun: dict[str, Any]
) -> dict[str, Any]:
    old = score_slice(baseline)
    new = score_slice(rerun)
    if old["count"] != new["count"]:
        raise ValueError("score slice counts differ")
    return {
        "count": old["count"],
        "baseline_pct": {metric: old[f"{metric}_pct"] for metric in METRICS},
        "rerun_pct": {metric: new[f"{metric}_pct"] for metric in METRICS},
        "delta_pp": {
            metric: round(new[f"{metric}_pct"] - old[f"{metric}_pct"], 6)
            for metric in METRICS
        },
    }


def score_comparison(
    baseline: dict[str, Any], rerun: dict[str, Any]
) -> dict[str, Any]:
    if set(baseline["by_category"]) != set(rerun["by_category"]):
        raise ValueError("official category sets differ")
    if set(baseline["by_is_multi_modality"]) != set(
        rerun["by_is_multi_modality"]
    ):
        raise ValueError("official modality sets differ")
    return {
        "overall": compare_score_slice(baseline["overall"], rerun["overall"]),
        "by_category": {
            key: compare_score_slice(
                baseline["by_category"][key], rerun["by_category"][key]
            )
            for key in sorted(baseline["by_category"])
        },
        "by_modality": {
            key: compare_score_slice(
                baseline["by_is_multi_modality"][key],
                rerun["by_is_multi_modality"][key],
            )
            for key in sorted(baseline["by_is_multi_modality"])
        },
    }


def main() -> int:
    args = parser().parse_args()
    baseline_rows = load_rows(args.baseline_scored)
    rerun_rows = load_rows(args.rerun_scored)
    baseline_official = json.loads(args.baseline_official.read_text(encoding="utf-8"))
    rerun_official = json.loads(args.rerun_official.read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "inputs": {
            "baseline_scored_sha256": sha256_path(args.baseline_scored),
            "rerun_scored_sha256": sha256_path(args.rerun_scored),
            "baseline_official_sha256": sha256_path(args.baseline_official),
            "rerun_official_sha256": sha256_path(args.rerun_official),
        },
        "scores": score_comparison(baseline_official, rerun_official),
        **build_comparison(baseline_rows, rerun_rows),
    }
    if find_forbidden(payload):
        raise ValueError("forbidden keys in comparison output")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "RERUN COMPARISON COMPLETE "
        f"records={payload['record_count']} "
        f"changed={payload['prediction_text']['changed_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
