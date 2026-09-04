#!/usr/bin/env python3
"""Assemble complete, ordered, field-minimal official predictions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def _write_atomic(rows: list[dict[str, str]], destination: Path) -> None:
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


def assemble(
    projection_path: Path,
    answers_dir: Path,
    output_path: Path,
    *,
    expected: int,
) -> dict[str, int]:
    official_order: list[str] = []
    seen_projected: set[str] = set()
    for line in projection_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if set(record) != {"qa_id", "conversation_idx", "question"}:
            raise ValueError("projection contains unexpected fields")
        qa_id = str(record["qa_id"])
        if qa_id in seen_projected:
            raise ValueError(f"duplicate projected qa_id: {qa_id}")
        seen_projected.add(qa_id)
        official_order.append(qa_id)
    if len(official_order) != expected:
        raise ValueError(f"projection count {len(official_order)} does not equal {expected}")

    answers: dict[str, str] = {}
    for path in sorted(answers_dir.glob("app-*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            qa_id = str(record.get("qa_id") or "")
            if qa_id not in seen_projected:
                raise ValueError(f"unknown answer qa_id in {path.name}:{line_number}")
            if qa_id in answers:
                raise ValueError(f"duplicate answer qa_id: {qa_id}")
            answer = str(record.get("predicted_answer") or "").strip()
            if not answer:
                raise ValueError(f"empty answer for qa_id: {qa_id}")
            answers[qa_id] = answer
    missing = [qa_id for qa_id in official_order if qa_id not in answers]
    if missing or len(answers) != expected:
        raise ValueError(
            f"answer set incomplete: answers={len(answers)} missing={len(missing)} expected={expected}"
        )
    rows = [
        {"qa_id": qa_id, "predicted_answer": answers[qa_id]}
        for qa_id in official_order
    ]
    _write_atomic(rows, output_path)
    return {"records": len(rows), "missing": 0, "extra": 0, "empty": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--answers-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-copy", type=Path)
    parser.add_argument("--expected", type=int, default=1382)
    args = parser.parse_args()
    try:
        summary = assemble(
            args.projection, args.answers_dir, args.output, expected=args.expected
        )
        if args.evidence_copy:
            rows = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines()]
            _write_atomic(rows, args.evidence_copy)
        print(
            f"predictions={summary['records']} missing={summary['missing']} "
            f"extra={summary['extra']} empty={summary['empty']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: prediction assembly failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
