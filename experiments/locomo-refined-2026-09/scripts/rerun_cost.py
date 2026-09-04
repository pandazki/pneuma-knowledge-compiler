#!/usr/bin/env python3
"""Aggregate answer-side usage from atomic follow-up records."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


INPUT_USD_PER_M = 0.20
OUTPUT_USD_PER_M = 1.20
SOFT_CEILING_USD = 50.0


def summarize(answers_root: Path, *, expected: int) -> dict[str, object]:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    qa_ids: set[str] = set()
    for path in sorted((answers_root / "records").glob("app-*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        qa_id = str(record.get("qa_id") or "")
        if not qa_id or qa_id in qa_ids:
            raise ValueError(f"missing or duplicate qa_id in {path}")
        qa_ids.add(qa_id)
        token_usage = record.get("token_usage")
        if not isinstance(token_usage, dict):
            raise ValueError(f"missing token usage in {path}")
        for key in usage:
            value = token_usage.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid {key} in {path}")
            usage[key] += value
    completed = len(qa_ids)
    if completed > expected:
        raise ValueError(f"answer count {completed} exceeds expected {expected}")
    observed = (
        usage["input_tokens"] / 1_000_000 * INPUT_USD_PER_M
        + usage["output_tokens"] / 1_000_000 * OUTPUT_USD_PER_M
    )
    projected = observed * expected / completed if completed else 0.0
    return {
        "pricing_basis": {
            "input_usd_per_m": INPUT_USD_PER_M,
            "output_usd_per_m": OUTPUT_USD_PER_M,
            "cache_assumption": "all input charged at full price",
        },
        "answer_usage": usage,
        "completed_answers": completed,
        "expected_answers": expected,
        "observed_usd": round(observed, 6),
        "projected_usd": round(projected, 6),
        "soft_ceiling_usd": SOFT_CEILING_USD,
        "soft_ceiling_observed": observed >= SOFT_CEILING_USD,
        "soft_ceiling_projected": projected >= SOFT_CEILING_USD,
    }


def write_atomic(payload: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers-root", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=1382)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        payload = summarize(args.answers_root, expected=args.expected)
        if args.out:
            write_atomic(payload, args.out)
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: rerun cost aggregation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
