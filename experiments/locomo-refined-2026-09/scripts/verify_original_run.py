#!/usr/bin/env python3
"""Fail closed if any protected artifact from the original run has changed."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_HASHES = {
    "RUN-REPORT.md": "6c9598fb597417dda3e6e02a588e7233e8765842482f6b4104001651bd5fcef4",
    "results/score-summary.json": "693b4944ea60583a839caff68ceffa9359b2b94211b47074b6919af5a05a7a86",
    "results/official-summary.json": "0074f150ab3073e5e4974c0f29b1b3bd279d87c3586b7d0b1e9cb0a763ad1d82",
    "results/predictions.jsonl": "c1134ae29ba81a0f22af92ecb83e4cd319079e26a06e1ced62e1b34d57737140",
    "results/predictions-scored-sanitized.jsonl": "2c299829ba2c9934a28f97b5556c90a7e8feb84fbd84b58c1c9acaa6654259f3",
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path, expected: dict[str, str] = BASELINE_HASHES) -> int:
    for relative, wanted in expected.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"protected artifact is missing: {relative}")
        actual = sha256_path(path)
        if actual != wanted:
            raise ValueError(f"protected artifact changed: {relative}")
    return len(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        count = verify(args.root)
        print(f"ORIGINAL RUN VERIFIED: {count} artifacts")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
