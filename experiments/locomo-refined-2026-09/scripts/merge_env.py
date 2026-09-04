#!/usr/bin/env python3
"""Merge generated settings and operator secrets without exposing values."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path


KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROVIDER_KEY = "PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER"


def read_env(path: Path) -> OrderedDict[str, str]:
    if not path.is_file():
        raise ValueError(f"environment source does not exist: {path}")
    values: OrderedDict[str, str] = OrderedDict()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"malformed environment assignment at {path}:{number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"invalid environment key at {path}:{number}")
        values[key] = value.strip()
    return values


def merge_env(generated: Path, secret: Path, destination: Path) -> str:
    values = read_env(generated)
    secret_values = read_env(secret)
    values.update(secret_values)
    values[PROVIDER_KEY] = "openai"
    if not values.get("OPENROUTER_API_KEY", "").strip():
        raise ValueError("OPENROUTER_API_KEY is absent or empty")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return f"merged_keys={len(values)} secret_keys={len(secret_values)}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: merge_env.py GENERATED SECRET DESTINATION", file=sys.stderr)
        return 2
    try:
        summary = merge_env(*(Path(value) for value in args))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

