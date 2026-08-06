#!/usr/bin/env python
"""Regenerate the committed engine schema asset.

    uv run python scripts/generate_engine_schema.py           # write
    uv run python scripts/generate_engine_schema.py --check    # exit 1 if stale

The schema is derived from `Settings` field metadata plus the hand-authored stage map
(`engine/stage_map.py`) and committed as
`packages/pneuma-knowledge-service/src/pneuma_knowledge_service/engine/assets/engine-schema.json`
so the API can serve one artifact that a reader can also just open. Run this after touching
either source; `--check` is the same comparison `tests/test_engine_schema.py` makes, kept
here so the fix is one command away from the failure.
"""

from __future__ import annotations

import argparse
import sys

from pneuma_knowledge_service.engine.schema import SCHEMA_PATH, build_schema, serialize_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero when the committed asset is stale",
    )
    args = parser.parse_args()

    fresh = serialize_schema(build_schema())
    current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.is_file() else ""
    if fresh == current:
        print(f"engine schema up to date: {SCHEMA_PATH}")
        return 0
    if args.check:
        print(
            f"engine schema is stale: {SCHEMA_PATH}\n"
            "  regenerate with: uv run python scripts/generate_engine_schema.py",
            file=sys.stderr,
        )
        return 1
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(fresh, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
