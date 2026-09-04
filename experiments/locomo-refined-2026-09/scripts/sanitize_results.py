#!/usr/bin/env python3
"""Whitelist safe scorer fields and compute official and burned-excluded scores."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = frozenset(
    {"question", "answer", "evidence", "evidence_messages", "matched_answer"}
)
SAFE_FIELDS = (
    "qa_id",
    "conversation_idx",
    "qa_index",
    "category",
    "is_multi_modality",
    "predicted_answer",
    "response",
    "ori_response",
    "prediction_found",
    "llm_judge",
    "success",
    "errors",
    "llm_score",
    "llm_reason",
    "f1_score",
    "bleu_score",
)


def _assert_no_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        collision = FORBIDDEN_KEYS.intersection(value)
        if collision:
            raise ValueError(f"forbidden scorer fields survived: {sorted(collision)}")
        for nested in value.values():
            _assert_no_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_forbidden(nested)


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
    if len(values) != len(rows):
        raise ValueError(f"metric {field} is missing from {len(rows) - len(values)} records")
    return sum(values) / len(values) if values else 0.0


def sanitize(
    raw_rows: list[dict[str, Any]], burned_ids: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    safe_rows = [
        {field: row[field] for field in SAFE_FIELDS if field in row}
        for row in raw_rows
    ]
    _assert_no_forbidden(safe_rows)
    ids = [str(row.get("qa_id") or "") for row in safe_rows]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("sanitized rows have missing or duplicate qa_id")
    unburned = [row for row in safe_rows if str(row["qa_id"]) not in burned_ids]
    burned_present = sorted(set(ids).intersection(burned_ids))
    summary = {
        "record_count": len(safe_rows),
        "burned_qa_ids": burned_present,
        "burned_count": len(burned_present),
        "unburned_record_count": len(unburned),
        "official_llm_score_pct": round(_mean(safe_rows, "llm_score") * 100, 6),
        "unburned_llm_score_pct": round(_mean(unburned, "llm_score") * 100, 6),
        "official_f1_pct": round(_mean(safe_rows, "f1_score") * 100, 6),
        "official_bleu_pct": round(_mean(safe_rows, "bleu_score") * 100, 6),
    }
    return safe_rows, summary


def _write_jsonl_atomic(rows: list[dict[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", type=Path, required=True)
    parser.add_argument("--official-summary", type=Path, required=True)
    parser.add_argument("--burned", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=1382)
    args = parser.parse_args()
    try:
        raw_rows = [
            json.loads(line)
            for line in args.scored.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(raw_rows) != args.expected:
            raise ValueError(f"scored record count is {len(raw_rows)}, expected {args.expected}")
        burned_records = json.loads(args.burned.read_text(encoding="utf-8"))
        burned_ids = {str(record["qa_id"]) for record in burned_records}
        safe_rows, summary = sanitize(raw_rows, burned_ids)
        official_summary = json.loads(args.official_summary.read_text(encoding="utf-8"))
        _assert_no_forbidden(official_summary)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl_atomic(safe_rows, args.output_dir / "predictions-scored-sanitized.jsonl")
        (args.output_dir / "score-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "official-summary.json").write_text(
            json.dumps(official_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"sanitized_records={len(safe_rows)} official_llm_score_pct="
            f"{summary['official_llm_score_pct']:.6f} unburned_llm_score_pct="
            f"{summary['unburned_llm_score_pct']:.6f}"
        )
        return 0
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: result sanitization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
