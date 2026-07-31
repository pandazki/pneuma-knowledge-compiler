"""Session fixtures for evaluation tests.

The preset bundle is built from two tiny generic commits at test time. No compiled
business demo or stale vector dump is shipped merely to test a file-format loader.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from _fixtures import claim, document
from pneuma_knowledge_eval.artifacts import Trajectory, load_preset_trajectory


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "eval fixture",
            "GIT_AUTHOR_EMAIL": "eval@example.test",
            "GIT_COMMITTER_NAME": "eval fixture",
            "GIT_COMMITTER_EMAIL": "eval@example.test",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


def _commit(repo: Path, path: str, body: str, job_id: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-m",
        f"compile {job_id}\n\nSkill-Version: v1\n",
    )


def _write_gzip(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(json.dumps(rows, ensure_ascii=False).encode("utf-8"))


@pytest.fixture(scope="session")
def preset_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("generic-eval-preset")
    repo = root / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")

    source_ids = ("src-generic-01", "src-generic-02")
    jobs = ("1" * 32, "2" * 32)
    _commit(
        repo,
        "memory/profile.md",
        document(
            "memory/profile.md",
            [claim("The workspace owner prefers traceable decisions.", "aaaa1111", cite=f"{source_ids[0]} ¶0")],
            type_="profile",
        ),
        jobs[0],
    )
    _commit(
        repo,
        "memory/topics/release-checklist.md",
        document(
            "memory/topics/release-checklist.md",
            [claim("Release checks include tests and a clean build.", "bbbb2222", cite=f"{source_ids[1]} ¶0")],
        ),
        jobs[1],
    )

    bundle = root / "bundle"
    bundle.mkdir()
    with tarfile.open(bundle / "canonical.tar.gz", "w:gz") as archive:
        for child in repo.iterdir():
            archive.add(child, arcname=child.name)

    now = "2026-01-02T03:04:05+00:00"
    _write_gzip(
        bundle / "pg" / "sources.json.gz",
        [
            {
                "source_id": source_ids[0],
                "kind": "document",
                "title": "Owner preferences",
                "created_at": now,
            },
            {
                "source_id": source_ids[1],
                "kind": "document",
                "title": "Release checklist",
                "created_at": now,
            },
        ],
    )
    _write_gzip(
        bundle / "pg" / "blocks.json.gz",
        [
            {
                "source_id": source_ids[0],
                "block_index": 0,
                "text": "The workspace owner prefers traceable decisions.",
            },
            {
                "source_id": source_ids[1],
                "block_index": 0,
                "text": "Release checks include tests and a clean build.",
            },
        ],
    )
    _write_gzip(
        bundle / "pg" / "compile_jobs.json.gz",
        [
            {
                "id": jobs[index],
                "kind": "compile",
                "payload": {"source_ids": [source_id]},
            }
            for index, source_id in enumerate(source_ids)
        ],
    )
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "friendly_id": "generic-eval-fixture",
                "source_user_id": "u-generic-eval",
                "counts": {
                    "canonical_commits": 2,
                    "pg": {
                        "sources": 2,
                        "blocks": 2,
                        "canonical_claims": 2,
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle


@pytest.fixture(scope="session")
def preset_trajectory(preset_bundle: Path) -> Trajectory:
    return load_preset_trajectory(preset_bundle)


def _truth_manifest() -> dict:
    return {
        "experiment_id": "generic-longitudinal-fixture",
        "truth": {
            "durable_facts": [
                {
                    "truth_id": "fact-traceable",
                    "value": "The workspace owner prefers traceable decisions.",
                    "status": "current",
                    "effective_at": "2026-03-02T09:00:00+00:00",
                }
            ],
            "decisions": [
                {
                    "truth_id": "decision-manual",
                    "value": "Release checks use a manual checklist.",
                    "status": "superseded",
                    "effective_at": "2026-03-09T09:00:00+00:00",
                },
                {
                    "truth_id": "decision-automated",
                    "value": "Release checks include tests and a clean build.",
                    "status": "current",
                    "effective_at": "2026-03-16T09:00:00+00:00",
                },
            ],
            "commitments": [
                {
                    "truth_id": "commit-review",
                    "value": "The release checklist will be reviewed before publishing.",
                    "status": "current",
                }
            ],
            "constraints": [
                {
                    "truth_id": "constraint-clean",
                    "value": "A release cannot proceed without a clean build.",
                    "status": "current",
                    "effective_at": "2026-03-23T09:00:00+00:00",
                }
            ],
            "negative_controls": [
                {
                    "truth_id": "noise-theme",
                    "value": "The interface theme changes every Friday.",
                    "reason": "unconfirmed chatter",
                }
            ],
            "supersessions": [
                {
                    "supersession_id": "sup-release-checks",
                    "before_truth_id": "decision-manual",
                    "after_truth_id": "decision-automated",
                    "effective_at": "2026-03-16T09:00:00+00:00",
                }
            ],
            "retrieval_cases": [
                {
                    "case_id": "q-release",
                    "question": "What checks are required before a release?",
                    "expected_truth_ids": [
                        "decision-automated",
                        "constraint-clean",
                    ],
                    "as_of": "2026-03-30T09:00:00+00:00",
                }
            ],
        },
    }


@pytest.fixture(scope="session")
def labelled_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A generic 12-window corpus used to exercise the directory adapter."""
    root = tmp_path_factory.mktemp("generic-labelled-corpus")
    (root / "manifest.json").write_text(
        json.dumps(_truth_manifest(), indent=2) + "\n",
        encoding="utf-8",
    )
    windows = []
    for index in range(12):
        start = datetime(2026, 3, 2, tzinfo=UTC)
        started_at = start + timedelta(days=index * 7)
        ended_at = started_at + timedelta(days=6, hours=23)
        windows.append(
            {
                "batch_id": f"B{index + 1:02d}",
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            }
        )
    (root / "index.json").write_text(
        json.dumps(windows, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="session")
def frozen_truth_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The same generic labels in the single-file frozen-manifest shape."""
    root = tmp_path_factory.mktemp("generic-frozen-truth")
    payload = _truth_manifest()
    payload["truth"]["commitments"][0]["effective_at"] = "2026-03-30T09:00:00+00:00"
    path = root / "truth.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
