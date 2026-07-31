from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from examples.opc import run


ROOT = Path(__file__).resolve().parents[3]


def test_default_experiment_user_is_fresh_and_url_safe() -> None:
    first = str(run._new_user_id())
    second = str(run._new_user_id())

    assert first != second
    assert first.startswith(f"{run.DEFAULT_USER_PREFIX}-")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_explicit_user_is_scoped_to_the_experiment() -> None:
    valid = f"{run.DEFAULT_USER_PREFIX}-review_1"
    assert str(run._user_id(valid)) == valid
    for invalid in ("../shared", "shared.tenant", "u-existing-customer"):
        with pytest.raises(ValueError, match="user_id"):
            run._user_id(invalid)


def test_cli_requires_explicit_user_for_resume() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "examples.opc", "run", "--from-batch", "2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--from-batch > 1 requires --user" in result.stderr


def test_cli_rejects_reset_that_skips_prior_batches() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.opc",
            "run",
            "--user",
            f"{run.DEFAULT_USER_PREFIX}-resume-test",
            "--reset-user",
            "--from-batch",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--reset-user cannot be combined with --from-batch > 1" in result.stderr


def test_runner_uses_only_the_frozen_28_group_corpus() -> None:
    assembled = run._build_dataset()

    assert len(assembled.batches) == 28
    assert sum(len(batch.contracts) for batch in assembled.batches) == 104


def test_keyless_control_compiles_reviewed_evidence_not_truth_paraphrases() -> None:
    manifest = {
        "truth": {
            "durable_facts": [
                {
                    "value": "a deliberately different summary",
                    "status": "current",
                    "evidence": [{"quote": "the reviewed source wording"}],
                },
                {
                    "value": "old state",
                    "status": "superseded",
                    "evidence": [{"quote": "must not enter the current baseline"}],
                },
            ],
            "decisions": [],
            "commitments": [],
            "constraints": [],
        }
    }

    class Store:
        async def get(self, user_id, source_id):
            return SimpleNamespace(
                raw=SimpleNamespace(kind="im", title="Review thread"),
                blocks=[
                    SimpleNamespace(index=0, text="irrelevant chatter"),
                    SimpleNamespace(
                        index=1,
                        text="Owner: the reviewed\nsource wording, with context.",
                    ),
                ],
            )

    quotes = run._current_truth_evidence(manifest)
    turns = asyncio.run(
        run._scripted_turns(
            SimpleNamespace(store=Store()),
            run._user_id(f"{run.DEFAULT_USER_PREFIX}-evidence-control"),
            ["source-1"],
            quotes,
        )
    )

    assert quotes == ("the reviewed source wording",)
    create = turns[0][0]
    assert create["name"] == "create_document"
    assert "irrelevant chatter" not in create["args"]["body"]
    assert "the reviewed source wording" in create["args"]["body"]
    assert "[cite: s01 ¶1]" in create["args"]["body"]


def test_resume_requires_prior_sources_and_example_ownership() -> None:
    assembled = run._build_dataset()
    prior = run._required_source_ids(assembled, before_batch=2)

    class Store:
        def __init__(self, profile, source_ids):
            self.profile = profile
            self.source_ids = source_ids

        async def get_user_profile(self, user_id):
            return self.profile

        async def list(self, user_id):
            return [
                SimpleNamespace(source_id=source_id)
                for source_id in self.source_ids
            ]

    user_id = run._user_id(f"{run.DEFAULT_USER_PREFIX}-resume")
    asyncio.run(
        run._require_resume_tenant(
            SimpleNamespace(
                store=Store({"experiment_id": run.EXPERIMENT_ID}, prior)
            ),
            user_id,
            assembled,
            from_batch=2,
        )
    )
    with pytest.raises(RuntimeError, match="not owned"):
        asyncio.run(
            run._require_resume_tenant(
                SimpleNamespace(store=Store({"experiment_id": "other"}, prior)),
                user_id,
                assembled,
                from_batch=2,
            )
        )


def test_real_provider_initialization_failure_still_closes_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        closed = False

        def get_chat_model(self, role):
            raise RuntimeError("provider unavailable")

        async def aclose(self):
            self.closed = True

    context = Context()

    async def build_context(settings):
        return context

    monkeypatch.setattr(
        run,
        "_build_dataset",
        lambda: SimpleNamespace(batches=[]),
    )
    monkeypatch.setattr(run, "_settings", lambda mode: object())
    monkeypatch.setattr(run, "build_context", build_context)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(
            run.run(
                user_id=run._user_id(f"{run.DEFAULT_USER_PREFIX}-provider-failure"),
                mode="real",
                reset=False,
                from_batch=1,
                until_batch=1,
                report_path=tmp_path / "never.json",
            )
        )
    assert context.closed


def test_public_report_redacts_openrouter_routes() -> None:
    assert run._public_model_label("openrouter:vendor/private") == (
        "openrouter:configured"
    )
    assert run._public_model_label("scripted:fixture") == "scripted:fixture"


def test_report_json_converts_numeric_library_scalars() -> None:
    class Scalar:
        def item(self):
            return 7

    assert run._json_text({"count": Scalar()}) == '{\n  "count": 7\n}\n'
