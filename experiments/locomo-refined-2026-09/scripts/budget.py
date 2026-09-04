#!/usr/bin/env python3
"""Conservatively aggregate compile/answer token logs and enforce the run budget."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


COMPILE_RE = re.compile(
    r"Compile-model tokens: input=(\d+) output=(\d+) total=(\d+)"
)
INPUT_USD_PER_M = 0.20
OUTPUT_USD_PER_M = 1.20
SOFT_USD = 50.0
HARD_USD = 60.0


def empty_usage() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def add_usage(total: dict[str, int], usage: dict[str, object]) -> None:
    total["input_tokens"] += int(usage.get("input_tokens") or 0)
    total["output_tokens"] += int(usage.get("output_tokens") or 0)
    reported_total = int(usage.get("total_tokens") or 0)
    total["total_tokens"] += reported_total or (
        int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    )


def collect_compile_usage(root: Path) -> dict[str, int]:
    usage = empty_usage()
    if not root.exists():
        return usage
    for path in sorted(root.rglob("*.log")):
        for match in COMPILE_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
            usage["input_tokens"] += int(match.group(1))
            usage["output_tokens"] += int(match.group(2))
            usage["total_tokens"] += int(match.group(3))
    return usage


def collect_answer_usage(root: Path) -> dict[str, int]:
    usage = empty_usage()
    if not root.exists():
        return usage
    for path in sorted(root.glob("app-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            token_usage = record.get("token_usage") or {}
            if not isinstance(token_usage, dict):
                raise ValueError(f"token_usage is not an object in {path}")
            add_usage(usage, token_usage)
    return usage


def summarize(
    compile_usage: dict[str, int],
    answered_usage: dict[str, int],
    *,
    completed: int,
    total: int,
) -> dict[str, object]:
    if completed < 0 or total <= 0 or completed > total:
        raise ValueError("completed/total unit counts are invalid")
    combined = empty_usage()
    add_usage(combined, compile_usage)
    add_usage(combined, answered_usage)
    observed = (
        combined["input_tokens"] / 1_000_000 * INPUT_USD_PER_M
        + combined["output_tokens"] / 1_000_000 * OUTPUT_USD_PER_M
    )
    projected = observed if completed == 0 else observed * total / completed
    return {
        "pricing_basis": {
            "input_usd_per_m": INPUT_USD_PER_M,
            "output_usd_per_m": OUTPUT_USD_PER_M,
            "cache_assumption": "all input charged at full price; embeddings not present in CLI logs",
        },
        "compile_usage": compile_usage,
        "answer_usage": answered_usage,
        "combined_usage": combined,
        "completed_units": completed,
        "total_units": total,
        "observed_usd": round(observed, 6),
        "projected_usd": round(projected, 6),
        "soft_ceiling_usd": SOFT_USD,
        "hard_ceiling_usd": HARD_USD,
        "soft_ceiling_projected": projected > SOFT_USD,
        "hard_ceiling_reached": observed >= HARD_USD,
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--compile-root", type=Path, required=True)
    cli.add_argument("--answers-root", type=Path)
    cli.add_argument("--completed", type=int, required=True)
    cli.add_argument("--total", type=int, required=True)
    cli.add_argument("--out", type=Path)
    cli.add_argument("--enforce-hard", action="store_true")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        compile_usage = collect_compile_usage(args.compile_root)
        answer_usage = collect_answer_usage(args.answers_root) if args.answers_root else empty_usage()
        summary = summarize(
            compile_usage, answer_usage, completed=args.completed, total=args.total
        )
        payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        if args.enforce_hard and bool(summary["hard_ceiling_reached"]):
            return 60
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

