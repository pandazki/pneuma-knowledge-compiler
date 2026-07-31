from __future__ import annotations

import json
from pathlib import Path

import pytest

from pneuma_knowledge_core.domain.user import UserProfile
from pneuma_knowledge_core.prompts import (
    prompt,
    prompt_overlay_hash,
    reset_prompt_overrides,
)
from pneuma_knowledge_core.skill import (
    load_builtin_skill,
    reset_skill_bases,
)

from examples.opc.environment import (
    BASE_VERSION,
    EXAMPLE_ROOT,
    EXAMPLE_USER_ID,
    KEYLESS_QDRANT_COLLECTION,
    REAL_QDRANT_COLLECTION,
    configure_example,
    example_settings,
    load_example_profile,
    require_real_providers,
)


def _set_real_provider_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    for role in (
        "COMPILE",
        "RECALL",
        "DEEP",
        "LIVE_CONTEXT",
        "EVOLVE",
        "SKILL",
    ):
        monkeypatch.setenv(
            f"PNEUMA_KNOWLEDGE_LLM_MODEL_{role}",
            "openrouter:openai/gpt-4o-mini",
        )
    monkeypatch.setenv(
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "openrouter:google/gemini-embedding-2",
    )


def test_example_configuration_owns_profile_skill_prompts_and_schema() -> None:
    reset_prompt_overrides()
    reset_skill_bases()

    identity = configure_example()
    profile = load_example_profile()
    skill = load_builtin_skill(BASE_VERSION)

    assert identity.user_id == EXAMPLE_USER_ID
    assert isinstance(profile, UserProfile)
    assert profile.user_id == EXAMPLE_USER_ID
    assert profile.source == "example"
    assert profile.locale.timezone == "Asia/Shanghai"
    assert profile.preferences.response_language == "zh-CN"

    assert skill.skill_id == "opc-example"
    assert skill.version == BASE_VERSION
    assert "work/products/{slug}.md" in skill.path_templates
    assert "work/experiments/{slug}.md" in skill.path_templates

    assert prompt_overlay_hash() == identity.prompt_overlay_hash
    assert identity.skill_content_hash == skill.content_hash
    assert "知识库主体" in prompt("compile.owner_env.write_language")

    matrix = json.loads(identity.schema_matrix_path.read_text(encoding="utf-8"))
    assert matrix["packs"]
    assert identity.schema_matrix_path.is_relative_to(EXAMPLE_ROOT)


def test_keyless_and_real_modes_share_business_contract_but_not_providers(
    monkeypatch,
) -> None:
    _set_real_provider_env(monkeypatch)

    keyless = example_settings("keyless")
    real = example_settings("real")

    for settings in (keyless, real):
        assert settings.user_schema_base_version == BASE_VERSION
        assert Path(settings.user_schema_matrix_path) == (
            EXAMPLE_ROOT / "assets" / "schema-matrix.json"
        )
        assert settings.default_timezone == "Asia/Shanghai"

    assert keyless.qdrant_collection == KEYLESS_QDRANT_COLLECTION
    assert real.qdrant_collection == REAL_QDRANT_COLLECTION
    assert keyless.qdrant_collection != real.qdrant_collection
    assert keyless.llm_model.startswith("scripted:")
    assert keyless.embedding_model == "fake:64"
    assert real.llm_model_compile.startswith("openrouter:")
    assert real.embedding_model.startswith("openrouter:")


def test_real_mode_rejects_a_scripted_skill_route(monkeypatch) -> None:
    _set_real_provider_env(monkeypatch)
    settings = example_settings("real").model_copy(
        update={"llm_model_skill": "scripted:skill.json"}
    )

    with pytest.raises(RuntimeError, match="skill still uses scripted"):
        require_real_providers(settings)


def test_real_mode_requires_the_openrouter_key(monkeypatch) -> None:
    _set_real_provider_env(monkeypatch)
    settings = example_settings("real").model_copy(update={"openrouter_api_key": ""})

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is missing"):
        require_real_providers(settings)


def test_example_tree_contains_only_current_runtime_data() -> None:
    assert (EXAMPLE_ROOT / "compose.yaml").is_file()
    assert (EXAMPLE_ROOT / "data" / "demo" / "sources" / "meeting.json").is_file()
    assert (EXAMPLE_ROOT / "data" / "84-day" / "manifest.json").is_file()

    assert not (EXAMPLE_ROOT.parent / "data" / "opc-84d").exists()
    assert not (EXAMPLE_ROOT.parent / "data" / "preset").exists()
    assert not (
        EXAMPLE_ROOT.parents[1]
        / "packages"
        / "pneuma-knowledge-service"
        / "src"
        / "pneuma_knowledge_service"
        / "experiments"
    ).exists()
