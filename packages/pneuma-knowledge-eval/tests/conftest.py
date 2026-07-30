"""Session fixtures for the evaluation tests. The builders live in `_fixtures.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures import CORPUS_84D, PRESET_BUNDLE
from pneuma_knowledge_eval.artifacts import Trajectory, load_preset_trajectory


@pytest.fixture(scope="session")
def preset_bundle() -> Path:
    if not PRESET_BUNDLE.is_dir():  # pragma: no cover - the bundle ships with the repo
        pytest.skip(f"preset bundle missing: {PRESET_BUNDLE}")
    return PRESET_BUNDLE


@pytest.fixture(scope="session")
def preset_trajectory(preset_bundle: Path) -> Trajectory:
    return load_preset_trajectory(preset_bundle)


@pytest.fixture(scope="session")
def corpus_84d() -> Path:
    if not CORPUS_84D.is_dir():  # pragma: no cover - the corpus ships with the repo
        pytest.skip(f"84d corpus missing: {CORPUS_84D}")
    return CORPUS_84D
