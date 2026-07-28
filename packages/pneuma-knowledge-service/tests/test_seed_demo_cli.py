"""Public CLI contract for the synthetic demo seeder."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_seed_demo_help_exposes_fail_closed_real_provider_mode() -> None:
    result = subprocess.run(
        [sys.executable, "examples/seed_demo.py", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--real" in result.stdout
    assert "scripted" in result.stdout
    assert "fake" in result.stdout


def test_seed_demo_real_mode_refuses_mock_providers_before_resetting_data() -> None:
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
        [sys.executable, "examples/seed_demo.py", "--real", "--keep"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "refuses scripted" in result.stderr
    assert "refuses fake" in result.stderr


def test_seed_demo_treats_completed_failed_jobs_as_pipeline_failure(
    monkeypatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "examples"))
    seed_demo = importlib.import_module("seed_demo")
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

    assert seed_demo._failed_job_details(jobs) == [
        "compile bad: vector dimension mismatch"
    ]
