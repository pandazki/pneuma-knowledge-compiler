from __future__ import annotations

import asyncio
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "run_opc_84d_experiment.py"
EVALUATE_SCRIPT = ROOT / "examples" / "evaluate_opc_84d_experiment.py"


def _load_script():
    sys.path.insert(0, str(ROOT / "examples"))
    spec = importlib.util.spec_from_file_location("run_opc_84d_experiment", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_experiment_user_is_fresh_and_url_safe() -> None:
    module = _load_script()

    first = str(module._new_user_id())
    second = str(module._new_user_id())

    assert first != second
    assert first.startswith("u-opc-seamlog-v2-")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_explicit_experiment_user_is_preserved_and_validated() -> None:
    module = _load_script()

    assert str(module._user_id("u-opc-seamlog-v2-review_1")) == (
        "u-opc-seamlog-v2-review_1"
    )
    for invalid in (
        "../shared-tenant",
        "shared.tenant",
        "shared:tenant",
        "u-existing-customer",
    ):
        with pytest.raises(ValueError, match="user_id"):
            module._user_id(invalid)


def test_default_report_paths_are_unique_and_user_scoped() -> None:
    module = _load_script()
    user_id = module._user_id("u-opc-seamlog-v2-review_1")

    first = module._new_report_path(user_id, kind="run")
    second = module._new_report_path(user_id, kind="run")

    assert first != second
    assert first.parent == module.DEFAULT_REPORT_DIR
    assert str(user_id) in first.name


def test_public_run_report_redacts_openrouter_model_routing() -> None:
    module = _load_script()

    assert (
        module._public_model_label("openrouter:vendor/private-model")
        == "openrouter:configured"
    )
    assert module._public_model_label("scripted:opc-84d") == "scripted:opc-84d"


def test_resuming_requires_an_explicit_user() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--from-batch", "2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--from-batch > 1 requires --user" in result.stderr


def test_evaluation_requires_the_exact_experiment_user() -> None:
    result = subprocess.run(
        [sys.executable, str(EVALUATE_SCRIPT), "--mode", "scripted"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--user USER" in result.stderr


def test_reset_cannot_skip_the_required_prior_batches() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--user",
            "u-opc-seamlog-v2-resume-test",
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


def test_run_function_also_rejects_reset_from_a_later_batch(tmp_path: Path) -> None:
    module = _load_script()

    with pytest.raises(ValueError, match="reset cannot be combined"):
        asyncio.run(
            module.run(
                user_id=module._user_id("u-opc-seamlog-v2-resume-test"),
                mode="scripted",
                reset=True,
                from_batch=2,
                until_batch=2,
                report_path=tmp_path / "never-written.json",
            )
        )


def test_programmatic_run_rejects_a_non_experiment_tenant_before_reset(
    tmp_path: Path,
) -> None:
    module = _load_script()

    with pytest.raises(ValueError, match="reserved experiment prefix"):
        asyncio.run(
            module.run(
                user_id=module.UserId("u-existing-customer"),
                mode="scripted",
                reset=True,
                from_batch=1,
                until_batch=1,
                report_path=tmp_path / "never-written.json",
            )
        )


def test_run_closes_context_when_compile_provider_initialization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()

    class Context:
        closed = False

        def get_chat_model(self, role):
            assert role == "compile"
            raise RuntimeError("provider unavailable")

        async def aclose(self):
            self.closed = True

    context = Context()

    async def build_context(settings):
        return context

    monkeypatch.setattr(module, "_build_dataset", lambda: SimpleNamespace(batches=[]))
    monkeypatch.setattr(module, "_settings", lambda mode: object())
    monkeypatch.setattr(module, "build_context", build_context)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(
            module.run(
                user_id=module._user_id("u-opc-seamlog-v2-provider-failure"),
                mode="real",
                reset=False,
                from_batch=1,
                until_batch=1,
                report_path=tmp_path / "never-written.json",
            )
        )

    assert context.closed


def test_resume_preflight_requires_every_source_from_all_prior_batches() -> None:
    module = _load_script()
    dataset = module._build_dataset()

    first_batch = module._required_source_ids(dataset, before_batch=2)
    first_two_batches = module._required_source_ids(dataset, before_batch=3)

    assert first_batch
    assert first_batch < first_two_batches


def test_runner_defaults_to_the_28_accepted_v2_batches() -> None:
    module = _load_script()

    dataset = module._build_dataset()

    assert len(dataset.batches) == 28
    assert [batch.batch_id for batch in dataset.batches] == [
        f"G{number:02d}" for number in range(1, 29)
    ]
    assert sum(len(batch.contracts) for batch in dataset.batches) == 104


def test_batch_one_refuses_a_tenant_with_only_an_existing_profile() -> None:
    module = _load_script()

    class Store:
        async def list(self, user_id):
            return []

        async def list_jobs(self, user_id):
            return []

        async def get_user_profile(self, user_id):
            return {"display_name": "existing user"}

        async def list_canonical_claims(self, user_id):
            return []

    class Canonical:
        async def list(self, user_id):
            return []

        async def snapshots(self, user_id):
            return []

    ctx = SimpleNamespace(store=Store(), canonical=Canonical())
    with pytest.raises(RuntimeError, match="non-empty tenant"):
        asyncio.run(
            module._require_empty_tenant(
                ctx,
                module._user_id("u-opc-seamlog-v2-existing-profile"),
            )
        )


def test_resume_refuses_a_tenant_without_experiment_ownership() -> None:
    module = _load_script()

    class Store:
        async def get_user_profile(self, user_id):
            return {"experiment_id": "another-experiment"}

    ctx = SimpleNamespace(store=Store())
    with pytest.raises(RuntimeError, match="not owned"):
        asyncio.run(
            module._require_resume_tenant(
                ctx,
                module._user_id("u-opc-seamlog-v2-foreign"),
                module._build_dataset(),
                from_batch=2,
            )
        )


def test_resume_allows_current_partial_sources_but_rejects_future_sources() -> None:
    module = _load_script()
    dataset = module._build_dataset()
    prior = module._required_source_ids(dataset, before_batch=2)
    through_current = module._required_source_ids(dataset, before_batch=3)
    current = through_current - prior
    future = (
        module._required_source_ids(
            dataset, before_batch=len(dataset.batches) + 1
        )
        - through_current
    )
    assert prior and current and future

    class Store:
        def __init__(self, source_ids):
            self.source_ids = source_ids

        async def get_user_profile(self, user_id):
            return {"experiment_id": module.EXPERIMENT_ID}

        async def list(self, user_id):
            return [
                SimpleNamespace(source_id=source_id)
                for source_id in self.source_ids
            ]

    user_id = module._user_id("u-opc-seamlog-v2-resume-partial")
    asyncio.run(
        module._require_resume_tenant(
            SimpleNamespace(
                store=Store(prior | {next(iter(current))})
            ),
            user_id,
            dataset,
            from_batch=2,
        )
    )

    with pytest.raises(RuntimeError, match="foreign source"):
        asyncio.run(
            module._require_resume_tenant(
                SimpleNamespace(
                    store=Store(
                        prior
                        | {next(iter(current))}
                        | {next(iter(future))}
                    )
                ),
                user_id,
                dataset,
                from_batch=2,
            )
        )


def test_evaluation_rejects_a_user_id_that_can_escape_report_directory() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(EVALUATE_SCRIPT),
            "--mode",
            "scripted",
            "--user",
            "../outside",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "user_id must start" in result.stderr
