#!/usr/bin/env python3
"""Build reproducible Phase-C aggregates from gold-free, sanitized results only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = {
    "question",
    "answer",
    "evidence",
    "evidence_messages",
    "matched_answer",
}
HEDGE_RE = re.compile(
    r"\b(record|records|context|conversation|source|information)\b.{0,40}"
    r"\b(do(?:es)? not|doesn.t|don.t|not|isn.t|aren.t|cannot|can.t|unclear|specif|establish|confirm)\b",
    re.IGNORECASE | re.DOTALL,
)
SAMPLE_SALT = "phase-c-sample-v1:"


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scored", type=Path, required=True)
    cli.add_argument("--official-summary", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    return cli


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


def length_stats(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    lengths = [len(str(row["predicted_answer"])) for row in rows]
    ordered = sorted(lengths)
    p90_index = int(0.9 * (len(ordered) - 1))
    return {
        "count": len(rows),
        "mean_chars": round(statistics.mean(lengths), 6),
        "median_chars": statistics.median(lengths),
        "p90_chars": ordered[p90_index],
        "hedged_surface_count": sum(
            bool(HEDGE_RE.search(str(row["predicted_answer"]))) for row in rows
        ),
        "multiline_count": sum("\n" in str(row["predicted_answer"]) for row in rows),
    }


def main() -> int:
    args = parser().parse_args()
    rows = [
        json.loads(line)
        for line in args.scored.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    official = json.loads(args.official_summary.read_text(encoding="utf-8"))
    forbidden = find_forbidden(rows)
    if forbidden:
        raise SystemExit(f"forbidden keys in sanitized input: {sorted(forbidden)}")
    if len(rows) != 1382 or len({row["qa_id"] for row in rows}) != 1382:
        raise SystemExit("sanitized input must contain 1,382 unique qa_ids")

    wrong = [row for row in rows if float(row["llm_score"]) == 0.0]
    right = [row for row in rows if float(row["llm_score"]) == 1.0]
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in wrong:
        modality = "multimodal_available" if row["is_multi_modality"] else "text_only"
        strata[(str(row["category"]), modality)].append(row)

    sampled: list[dict[str, Any]] = []
    by_stratum: dict[str, dict[str, int | float]] = {}
    for (category, modality), members in sorted(strata.items()):
        key = f"category_{category}__{modality}"
        ordered = sorted(
            members,
            key=lambda row: hashlib.sha256(
                (SAMPLE_SALT + str(row["qa_id"])).encode("utf-8")
            ).hexdigest(),
        )
        population = sum(
            1
            for row in rows
            if str(row["category"]) == category
            and ("multimodal_available" if row["is_multi_modality"] else "text_only")
            == modality
        )
        by_stratum[key] = {
            "incorrect": len(members),
            "population": population,
            "incorrect_pct": round(100 * len(members) / population, 6),
        }
        for row in ordered[:2]:
            answer = str(row["predicted_answer"])
            sampled.append(
                {
                    "qa_id": row["qa_id"],
                    "category": category,
                    "modality": modality,
                    "prediction_chars": len(answer),
                    "hedged_surface": bool(HEDGE_RE.search(answer)),
                    "multiline": "\n" in answer,
                }
            )

    payload = {
        "schema_version": 1,
        "inputs": {
            "sanitized_scored_sha256": hashlib.sha256(args.scored.read_bytes()).hexdigest(),
            "official_summary_sha256": hashlib.sha256(
                args.official_summary.read_bytes()
            ).hexdigest(),
        },
        "score_counts": {"correct": len(right), "incorrect": len(wrong)},
        "answer_surface": {
            "correct": length_stats(right),
            "incorrect": length_stats(wrong),
            "hedged_surface_definition": HEDGE_RE.pattern,
        },
        "incorrect_by_category_and_modality": by_stratum,
        "wrong_sample": {
            "method": "two incorrect qa_ids per category x modality stratum, ordered by sha256 of fixed salt plus qa_id",
            "salt": SAMPLE_SALT,
            "count": len(sampled),
            "records": sampled,
        },
        "official_overall": official["overall"],
    }
    if find_forbidden(payload):
        raise SystemExit("forbidden keys in Phase-C output")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"PHASE C ANALYSIS COMPLETE records={len(rows)} wrong={len(wrong)} "
        f"sample={len(sampled)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
