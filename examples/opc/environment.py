"""Deployment-owned configuration for the fictional OPC example.

This module is deliberately outside both framework packages. Import it from every
example entrypoint before loading a skill or rendering model-visible prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import UserProfile
from pneuma_knowledge_core.prompts import override_prompts, prompt_overlay_hash
from pneuma_knowledge_core.skill import (
    SchemaPack,
    SkillVersion,
    compose_skill,
    load_builtin_skill,
    matrix_packs,
    register_skill_base,
)
from pneuma_knowledge_service.skills import MANIFEST_PATH, serialize_manifest
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import resolve_model_name


EXAMPLE_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = EXAMPLE_ROOT / "assets"
DATA_ROOT = EXAMPLE_ROOT / "data"
BASE_VERSION = "opc-example-v1"
EXAMPLE_USER_ID = UserId("u-opc-lin")
EXPERIMENT_USER_PREFIX = "u-opc-seamlog-v2"
KEYLESS_QDRANT_COLLECTION = "opc_example_chunks"
REAL_QDRANT_COLLECTION = "opc_example_chunks_real"
_PROFILE_PATH = ASSET_ROOT / "profile.json"
_STRATEGY_PATH = ASSET_ROOT / "strategy.md"
_OVERLAY_PATH = ASSET_ROOT / "prompt-overlay.json"
_MATRIX_PATH = ASSET_ROOT / "schema-matrix.json"
_ENV_PATH = EXAMPLE_ROOT / ".env"
_ENV_EXAMPLE_PATH = EXAMPLE_ROOT / ".env.example"
_KEYLESS_REPLAY = DATA_ROOT / "demo" / "replay" / "recall.json"

_PATH_TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "work/products/{slug}.md",
    "work/experiments/{slug}.md",
    "work/operations/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]
_CONTRACT_RULES = (
    "contract.rule.citation_granularity",
    "contract.rule.citation_shape",
    "contract.rule.strength_labels",
)


@dataclass(frozen=True)
class ExampleIdentity:
    user_id: UserId
    base_version: str
    skill_content_hash: str
    prompt_overlay_hash: str
    schema_matrix_path: Path


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"example asset must contain one JSON object: {path}")
    return value


def load_example_profile() -> UserProfile:
    """Return the checked-in fictional owner profile."""
    return UserProfile.model_validate(_load_json(_PROFILE_PATH))


def _matrix_packs_for(profile: UserProfile) -> list[SchemaPack]:
    """Resolve only the example-owned deterministic matrix packs.

    Profile-derived LLM packs are a separate feature under test. The checked-in
    example baseline pins its schema so keyless and real runs differ only by provider.
    """
    return matrix_packs(
        profile.industry,
        profile.role,
        matrix_path=_MATRIX_PATH,
    )


def _load_skill() -> SkillVersion:
    instructions = _STRATEGY_PATH.read_text(encoding="utf-8")
    return SkillVersion(
        skill_id="opc-example",
        version=BASE_VERSION,
        instructions=instructions,
        path_templates=list(_PATH_TEMPLATES),
        contract_rules=_CONTRACT_RULES,
        content_hash=SkillVersion.compute_hash(
            "opc-example",
            BASE_VERSION,
            instructions,
            _PATH_TEMPLATES,
            _CONTRACT_RULES,
        ),
    )


def configure_example() -> ExampleIdentity:
    """Register the example's prompt and skill assets in the current process."""
    overlay = _load_json(_OVERLAY_PATH)
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in overlay.items()):
        raise ValueError("prompt-overlay.json must map string keys to string templates")
    override_prompts(overlay)
    skill = _load_skill()
    register_skill_base(BASE_VERSION, skill)
    overlay_hash = prompt_overlay_hash()
    if overlay_hash is None:  # the checked-in overlay is intentionally non-empty
        raise RuntimeError("OPC example prompt overlay was not registered")
    return ExampleIdentity(
        user_id=EXAMPLE_USER_ID,
        base_version=BASE_VERSION,
        skill_content_hash=skill.content_hash,
        prompt_overlay_hash=overlay_hash,
        schema_matrix_path=_MATRIX_PATH,
    )


def _settings_source() -> Path:
    return _ENV_PATH if _ENV_PATH.is_file() else _ENV_EXAMPLE_PATH


def example_settings(mode: Literal["keyless", "real"] = "keyless") -> Settings:
    """Build settings for the example while keeping provider mode explicit."""
    configure_example()
    settings = Settings(_env_file=_settings_source())  # type: ignore[call-arg]
    shared = {
        "default_timezone": "Asia/Shanghai",
        "user_schema_packs": True,
        "user_schema_base_version": BASE_VERSION,
        "user_schema_matrix_path": str(_MATRIX_PATH),
    }
    if mode == "keyless":
        return settings.model_copy(
            update={
                **shared,
                "qdrant_collection": KEYLESS_QDRANT_COLLECTION,
                "llm_model": f"scripted:{_KEYLESS_REPLAY.as_posix()}",
                "llm_model_compile": "",
                "llm_model_recall": "",
                "llm_model_deep": "",
                "llm_model_skill": "",
                "llm_model_evolve": "",
                "llm_model_live_context": "",
                "embedding_model": "fake:64",
                "chunk_strategy": "sentence",
                "evolve_auto_trigger": False,
            }
        )
    if mode != "real":
        raise ValueError(f"unknown OPC example mode: {mode!r}")
    # A scripted *base* intentionally overrides every role in framework routing.
    # Real mode therefore promotes the explicitly configured compile route to the
    # base before validating all roles; otherwise a keyless .env default would mask
    # perfectly valid per-operation real routes.
    real = settings.model_copy(
        update={
            **shared,
            "qdrant_collection": REAL_QDRANT_COLLECTION,
            "llm_model": settings.llm_model_compile or settings.llm_model,
        }
    )
    require_real_providers(real)
    return real


def require_real_providers(settings: Settings) -> None:
    """Fail before tenant mutation when real mode still points at local doubles."""
    issues: list[str] = []
    models = {
        role: resolve_model_name(settings, role)
        for role in ("compile", "recall", "deep", "skill", "live_context", "evolve")
    }
    for role, model in models.items():
        if model.startswith("scripted:"):
            issues.append(f"{role} still uses scripted model {model}")
    if settings.embedding_model.startswith("fake:"):
        issues.append(f"embedding still uses {settings.embedding_model}")
    uses_openrouter = any(
        model.startswith("openrouter:") for model in models.values()
    ) or settings.embedding_model.startswith("openrouter:")
    if uses_openrouter and not settings.openrouter_api_key.strip():
        issues.append("OPENROUTER_API_KEY is missing")
    if issues:
        raise RuntimeError("real OPC example refuses local providers: " + "; ".join(issues))


async def install_example_subject(
    ctx,
    user_id: UserId = EXAMPLE_USER_ID,
    *,
    experiment_id: str | None = None,
    profile_updates: dict | None = None,
) -> tuple[UserProfile, SkillVersion]:
    """Persist the fictional subject and its deterministic schema contract.

    The service's fallback profile is intentionally generic. Example entrypoints call
    this function before ingestion so the business profile and schema never leak into
    framework adapters. A matching manifest is left untouched on resume/``--keep``.
    """
    configure_example()
    profile_payload = load_example_profile().model_dump(
        mode="json",
        exclude={"level_style"},
    )
    profile_payload["user_id"] = str(user_id)
    if profile_updates:
        profile_payload.update(profile_updates)
    profile = UserProfile.model_validate(profile_payload)
    stored_payload = profile.model_dump(mode="json", exclude={"level_style"})
    if experiment_id is not None:
        stored_payload["experiment_id"] = experiment_id
    await ctx.store.upsert_user_profile(user_id, stored_payload)

    base = load_builtin_skill(BASE_VERSION)
    packs = _matrix_packs_for(profile)
    composed = compose_skill(base, packs)
    current = await ctx.canonical.read_meta(user_id, MANIFEST_PATH)
    current_identity: tuple[str | None, str | None] = (None, None)
    if current:
        try:
            parsed = json.loads(current)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            current_identity = (
                parsed.get("base_version"),
                parsed.get("content_hash"),
            )
    if current_identity != (base.version, composed.content_hash):
        await ctx.canonical.write_meta(
            user_id,
            MANIFEST_PATH,
            serialize_manifest(base, packs, composed),
            message="skill: install OPC example schema",
        )
    return profile, composed
