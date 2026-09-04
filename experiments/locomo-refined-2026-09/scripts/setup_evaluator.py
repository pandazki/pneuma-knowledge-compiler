#!/usr/bin/env python3
"""Create the ignored, pinned Python environment used only by the official scorer."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".runtime" / "evaluator-venv"
PYTHON = ENVIRONMENT / "bin" / "python"
PINS = {"openai": "1.109.1", "tenacity": "9.1.4"}


def installed_versions() -> dict[str, str]:
    if not PYTHON.is_file():
        return {}
    script = (
        "import importlib.metadata,json; "
        "print(json.dumps({n:importlib.metadata.version(n) for n in ('openai','tenacity')}))"
    )
    process = subprocess.run(
        [str(PYTHON), "-c", script], capture_output=True, text=True, check=False
    )
    if process.returncode != 0:
        return {}
    import json

    payload = json.loads(process.stdout)
    return {str(key): str(value) for key, value in payload.items()}


def main() -> int:
    try:
        if not PYTHON.is_file():
            ENVIRONMENT.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["uv", "venv", str(ENVIRONMENT), "--python", "3.12"], check=True
            )
        if installed_versions() != PINS:
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(PYTHON),
                    *[f"{name}=={version}" for name, version in PINS.items()],
                ],
                check=True,
            )
        if installed_versions() != PINS:
            raise ValueError("evaluator dependency versions do not match pins")
        print("evaluator_environment=ready dependencies=2")
        return 0
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: evaluator environment setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
