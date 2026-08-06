#!/usr/bin/env python3
"""Merge credentials from the host credential file into a generated project's .env.

Values are never printed, never echoed, never returned. Only key names and a
non-empty boolean are reported.

    python3 apply_env.py app-01
"""
from __future__ import annotations

import sys
from pathlib import Path

CRED_SOURCE = Path("/data/qiwei/repos/pneuma-knowledge-compiler/.env")
KEYS = (
    "OPENROUTER_API_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_BASE_URL",
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_env.py <project-dir>", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    if not target.is_absolute():
        target = Path(__file__).resolve().parent / target
    env_path = target / ".env"
    if not env_path.exists():
        print(f"error: {env_path} not found", file=sys.stderr)
        return 1

    creds = read_env(CRED_SOURCE)
    missing = [k for k in KEYS if not creds.get(k)]
    if missing:
        print(f"error: credential source lacks {missing}", file=sys.stderr)
        return 1

    lines = env_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    written: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.partition("=")[0].strip() if "=" in stripped else ""
        if key in KEYS:
            out.append(f"{key}={creds[key]}")
            written.add(key)
        else:
            out.append(line)
    remaining = [k for k in KEYS if k not in written]
    if remaining:
        out.append("")
        out.append("# credentials merged by apply_env.py")
        out.extend(f"{k}={creds[k]}" for k in remaining)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"merged into {env_path}:")
    for k in KEYS:
        print(f"  {k}  non-empty={bool(creds[k])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
