"""The engine directory's three-level precedence, proved level by level.

process env > engine file > framework default. Each level gets its own test, plus the one
that matters most for everything else in this repository: with no engine directory
configured, settings assembly is byte-for-byte what it was before the concept existed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pneuma_knowledge_service.engine.files import EngineFileError
from pneuma_knowledge_service.engine.resolve import engine_overrides, resolve_engine
from pneuma_knowledge_service.settings import Settings, get_settings


def _engine(root: Path, files: dict[str, str]) -> Path:
    """An engine directory holding exactly the given files (dedented for readability)."""
    engine = root / "engine"
    for rel, text in files.items():
        path = engine / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    engine.mkdir(parents=True, exist_ok=True)
    return engine


@pytest.fixture(autouse=True)
def _clean_strategy_env(monkeypatch):
    """Start every test from "the environment states nothing about strategy".

    The service conftest pins several PNEUMA_KNOWLEDGE_* routing vars to "" for the whole
    session, and an entry present-but-empty is a legitimate env-level statement — so a
    precedence test must clear them or it would be measuring the conftest.
    """
    for name in (
        "PNEUMA_KNOWLEDGE_ENGINE_DIR",
        "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE",
        "PNEUMA_KNOWLEDGE_RECALL_CLAIM_CANDIDATE_CAP",
        "PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP",
        "PNEUMA_KNOWLEDGE_RECALL_WINDOW_CANDIDATE_CAP",
        "PNEUMA_KNOWLEDGE_RECALL_EPISODE_SUMMARY_CAP",
        "PNEUMA_KNOWLEDGE_RECALL_WINDOW_CAP",
        "PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED",
        "PNEUMA_KNOWLEDGE_EVOLVE_AUTO_TRIGGER",
        "PNEUMA_KNOWLEDGE_EVOLVE_DRAFT_TTL_HOURS",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_ANSWER",
        "PNEUMA_KNOWLEDGE_ANSWER_REASONING_EFFORT",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
    ):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ level 3: the default


def test_no_engine_dir_is_the_pre_engine_behavior(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # away from any .env in the repository
    settings = get_settings()
    assert settings.engine_dir == ""
    assert settings.chunk_strategy == Settings.model_fields["chunk_strategy"].default
    assert settings.challenge_enabled is Settings.model_fields["challenge_enabled"].default
    assert settings.recall_claim_cap == Settings.model_fields["recall_claim_cap"].default
    assert settings.recall_claim_candidate_cap == 80
    assert settings.recall_claim_cap == 40
    assert settings.recall_window_candidate_cap == 60
    assert settings.recall_episode_summary_cap == 24
    assert settings.recall_window_cap == 6


def test_an_empty_engine_dir_states_nothing_and_changes_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = _engine(tmp_path, {})
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))
    settings = get_settings()
    assert settings.engine_dir == str(engine)
    assert settings.chunk_strategy == Settings.model_fields["chunk_strategy"].default
    overrides, resolution = engine_overrides(engine, {})
    assert overrides == {}
    assert set(resolution.values()) == {"default"}


# ------------------------------------------------------------------ level 2: the engine file


def test_engine_files_beat_the_framework_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = _engine(
        tmp_path,
        {
            "intake/intake.yaml": "chunk_strategy: sentence\n",
            "compile/challenge.yaml": "enabled: true\nmax_rounds: 4\n",
            "evolve/evolve.yaml": "auto_trigger: false\ndraft_ttl_hours: 6\n",
            "recall/recall.yaml": (
                "answer_style: concise\nclaim_candidate_cap: 100\nclaim_cap: 50\n"
                "window_candidate_cap: 70\nepisode_summary_cap: 30\nwindow_cap: 7\n"
            ),
            "engine.yaml": "compile: openrouter:x/compile\nrecall: openrouter:x/recall\n",
        },
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))
    settings = get_settings()
    assert settings.chunk_strategy == "sentence"
    assert settings.challenge_enabled is True
    assert settings.challenge_max_rounds == 4
    assert settings.challenge_max_questions == 6  # unstated → still the default
    assert settings.evolve_auto_trigger is False
    assert settings.evolve_draft_ttl_hours == 6.0
    assert settings.recall_answer_style == "concise"
    assert settings.recall_claim_candidate_cap == 100
    assert settings.recall_claim_cap == 50
    assert settings.recall_window_candidate_cap == 70
    assert settings.recall_episode_summary_cap == 30
    assert settings.recall_window_cap == 7
    assert settings.llm_model_compile == "openrouter:x/compile"

    resolved = resolve_engine(engine, {})
    assert resolved.resolution["intake.chunk_strategy"] == "engine"
    assert resolved.resolution["challenge.max_questions"] == "default"
    assert resolved.values["challenge.max_rounds"] == 4
    # An int knob over a float setting reports whole hours, not 6.0.
    assert resolved.values["evolve.draft_ttl_hours"] == 6
    assert isinstance(resolved.values["evolve.draft_ttl_hours"], int)


def test_answer_model_and_effort_resolve_from_the_engine(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = _engine(
        tmp_path,
        {
            "engine.yaml": """\
                recall: openrouter:openai/gpt-5.6-luna
                answer: openrouter:openai/gpt-5.6-luna-pro
                answer_reasoning_effort: high
            """,
        },
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))

    settings = get_settings()

    assert settings.llm_model_answer == "openrouter:openai/gpt-5.6-luna-pro"
    assert settings.answer_reasoning_effort == "high"


# ------------------------------------------------------------------ level 1: process env


def test_process_env_beats_the_engine_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = _engine(
        tmp_path,
        {
            "intake/intake.yaml": "chunk_strategy: sentence\n",
            "recall/recall.yaml": "answer_style: concise\nclaim_cap: 80\n",
        },
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CHUNK_STRATEGY", "semantic")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP", "128")
    settings = get_settings()
    assert settings.chunk_strategy == "semantic"
    assert settings.recall_claim_cap == 128
    assert settings.recall_answer_style == "concise"  # env silent here → engine still wins

    import os

    resolved = resolve_engine(engine, dict(os.environ))
    assert resolved.resolution["intake.chunk_strategy"] == "env"
    assert resolved.resolution["recall.claim_cap"] == "env"
    assert resolved.resolution["recall.answer_style"] == "engine"
    assert resolved.values["recall.claim_cap"] == 128


def test_an_empty_env_var_is_still_an_env_level_statement(tmp_path):
    """A benchmark harness that exports MODEL="" is saying "no model for this run"."""
    engine = _engine(tmp_path, {"engine.yaml": "deep: openrouter:x/deep\n"})
    overrides, resolution = engine_overrides(
        engine, {"PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP": ""}
    )
    assert resolution["models.deep"] == "env"
    assert "llm_model_deep" not in overrides


# ------------------------------------------------------------------ documents and overlays


def test_documents_are_files_not_values(tmp_path):
    engine = _engine(
        tmp_path,
        {
            "compile/contract.md": "---\nskill_id: x\n---\n\nbody\n",
            "persona/profile.yaml": "display_name: Someone\n",
        },
    )
    resolved = resolve_engine(engine, {})
    assert "compile.contract" not in resolved.values
    assert "compile.contract" not in resolved.resolution
    assert "persona.profile" not in resolved.values


def test_overlays_resolve_as_a_mapping(tmp_path):
    engine = _engine(
        tmp_path,
        {
            "prompts/overlays.yaml": """\
                overlays:
                  gate.anchor_continuity: "an anchor never moves"
                """,
        },
    )
    resolved = resolve_engine(engine, {})
    assert resolved.resolution["prompts.overlays"] == "engine"
    assert resolved.values["prompts.overlays"] == {
        "gate.anchor_continuity": "an anchor never moves"
    }


def test_absent_overlay_file_resolves_to_the_empty_default(tmp_path):
    engine = _engine(tmp_path, {})
    resolved = resolve_engine(engine, {})
    assert resolved.resolution["prompts.overlays"] == "default"
    assert resolved.values["prompts.overlays"] == {}


# ------------------------------------------------------------------ loud failures


def test_malformed_engine_yaml_fails_loudly_rather_than_falling_back(tmp_path):
    engine = _engine(tmp_path, {"recall/recall.yaml": "answer_style: [unclosed\n"})
    with pytest.raises(EngineFileError) as exc:
        engine_overrides(engine, {})
    assert "recall/recall.yaml" in str(exc.value)


def test_a_stage_file_that_is_not_a_mapping_fails_loudly(tmp_path):
    engine = _engine(tmp_path, {"intake/intake.yaml": "- semantic\n"})
    with pytest.raises(EngineFileError):
        engine_overrides(engine, {})


def test_an_engine_value_that_settings_rejects_fails_loudly(tmp_path):
    engine = _engine(tmp_path, {"recall/recall.yaml": "answer_style: shouty\n"})
    with pytest.raises(EngineFileError) as exc:
        resolve_engine(engine, {})
    assert "do not validate" in str(exc.value)


def test_a_missing_engine_dir_resolves_to_defaults_without_raising(tmp_path):
    resolved = resolve_engine(tmp_path / "nope", {})
    assert set(resolved.resolution.values()) == {"default"}
