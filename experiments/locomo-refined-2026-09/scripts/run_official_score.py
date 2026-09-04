#!/usr/bin/env python3
"""Run the unmodified official scorer with credentials passed only in its environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from merge_env import read_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = read_env(ROOT / "app-01" / ".env")
        api_key = values.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError("OpenRouter credential is missing")
        provider = values.get("PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER", "")
        if provider != "openai":
            raise ValueError("OpenRouter provider order is not pinned to openai")
        python_bin = ROOT / ".runtime" / "evaluator-venv" / "bin" / "python"
        if not python_bin.is_file():
            raise ValueError("framework Python environment is missing")
        environment = os.environ.copy()
        environment.update(
            {
                "EVALUATOR_API_KEY": api_key,
                "EVALUATOR_MODEL": "qwen/qwen3-14b",
                "EVALUATOR_API_BASE": "https://openrouter.ai/api/v1",
                "LOCOMO_PYTHON_BIN": str(python_bin),
                "LOCOMO_PREDICTIONS_PATH": str(args.predictions.resolve()),
            }
        )
        process = subprocess.run(
            [
                "./scripts/run_eval.sh",
                "--metrics",
                "llm",
                "f1",
                "bleu",
                "--llm-judge",
                "refined",
                "--concurrency",
                "64",
            ],
            cwd=ROOT / "data",
            env=environment,
            check=False,
        )
        return process.returncode
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: official score launch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
