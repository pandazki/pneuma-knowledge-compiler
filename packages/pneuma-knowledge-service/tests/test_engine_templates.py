"""The engine's starting texts ship with the library, and the scaffold reads them from there.

Two editions start an engine directory — the scaffold's generated project and the personal
edition — and they must start it from the same contract skeleton, the same owner-profile
skeleton and the same orientation README. Keeping the files inside the service package is
what makes that a fact rather than an agreement; these tests pin the package data, the
lookup vocabulary, and that the scaffold has no copy of its own.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest

from pneuma_knowledge_service.engine import template_files

ROOT = Path(__file__).resolve().parents[3]


def test_every_template_ships_as_package_data_readable_through_importlib_resources():
    # importlib.resources, not a path walk: this is the reading that still works from an
    # installed wheel, which is how the personal edition will get at these files.
    root = importlib.resources.files("pneuma_knowledge_service.engine") / "templates"
    for name, suffix in template_files.TEMPLATE_SUFFIXES.items():
        for language in template_files.TEMPLATE_LANGUAGES:
            resource = root / f"{name}.{language}.{suffix}"
            assert resource.is_file(), f"missing package data: {resource}"
            assert resource.read_text(encoding="utf-8").strip()


def test_template_text_matches_the_file_template_path_names():
    for name in template_files.template_names():
        for language in template_files.TEMPLATE_LANGUAGES:
            path = template_files.template_path(name, language)
            assert path.name.startswith(f"{name}.{language}.")
            assert template_files.template_text(name, language) == path.read_text(encoding="utf-8")


def test_the_default_language_is_english():
    assert template_files.template_text("contract") == template_files.template_text("contract", "en")


def test_an_unknown_name_or_language_names_what_does_exist():
    with pytest.raises(template_files.UnknownTemplate) as unknown_name:
        template_files.template_path("intake")
    assert "contract" in str(unknown_name.value)
    assert "engine-README" in str(unknown_name.value)

    with pytest.raises(template_files.UnknownTemplate) as unknown_language:
        template_files.template_path("contract", "fr")
    assert "en" in str(unknown_language.value)
    assert "zh" in str(unknown_language.value)


def test_the_contract_skeleton_is_what_the_scaffold_writes_into_a_generated_engine():
    # The scaffold no longer owns a copy: its generator fills `{{SKILL_ID}}` in exactly this
    # text. A second copy under scaffold/templates/ would be the drift this move removes.
    text = template_files.template_text("contract", "en")
    assert "{{SKILL_ID}}" in text
    # The starter is executable as written (no TODO slots to fill before a first build):
    # it declares at least one path template and carries the contract's own guidance.
    assert "path_templates:" in text and "TODO" not in text
    scaffold_templates = ROOT / "scaffold" / "templates"
    if scaffold_templates.is_dir():
        strays = sorted(
            path.name
            for path in scaffold_templates.iterdir()
            if path.is_file()
            and path.name.split(".")[0] in template_files.TEMPLATE_SUFFIXES
        )
        assert not strays, f"engine templates left behind in the scaffold: {strays}"
