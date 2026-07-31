"""Public CLI contract for the small four-source seeder."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from examples.opc import seed


ROOT = Path(__file__).resolve().parents[3]


def test_seed_help_exposes_real_provider_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "examples.opc", "seed", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--real" in result.stdout
    assert "scripted" in result.stdout
    assert "fake" in result.stdout


def test_real_mode_refuses_local_providers_before_data_access() -> None:
    env = os.environ.copy()
    env.update(
        {
            "OPENROUTER_API_KEY": "",
            "PNEUMA_KNOWLEDGE_LLM_MODEL": "scripted:do-not-run.json",
            "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE": "scripted:do-not-run.json",
            "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL": "scripted:do-not-run.json",
            "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL": "fake:64",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "examples.opc", "seed", "--real", "--keep"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "still uses scripted" in result.stderr
    assert "embedding still uses fake" in result.stderr


def test_failed_or_unfinished_jobs_fail_the_demo() -> None:
    jobs = [
        {"job_id": "ok", "kind": "index", "status": "done", "ok": True},
        {
            "job_id": "bad",
            "kind": "compile",
            "status": "done",
            "ok": False,
            "detail": "vector dimension mismatch",
        },
    ]

    assert seed._failed_job_details(jobs) == [
        "compile bad: vector dimension mismatch"
    ]
