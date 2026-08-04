"""skill_for_user: per-user resolve → materialize → reload (schema-evolve M1, §1.3).

Git-only (no docker): a real GitCanonicalStore over tmp_path backs the manifest; the rest
of the context is a light fake. Covers the master switch, manifest materialization on first
compile, no re-derive on reload (count assertion), and per-user differentiation with a
byte-stable per-user contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pneuma_knowledge_service.skills as skills_mod
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import Avatar, Locale, Preferences, UserProfile, WorkspaceProfile
from pneuma_knowledge_core.skill import SchemaPack, load_skill_base, render_system_contract
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.skills import skill_for_user


def _profile(uid: str, *, source="user", role="engineering", occupation="后端工程师") -> UserProfile:
    return UserProfile(
        user_id=UserId(uid),
        display_name="U",
        avatar=Avatar(initial="U", color="#6C8EBF"),
        locale=Locale(city="上海", country="中国", timezone="Asia/Shanghai", language="zh-CN"),
        industry="tech",
        role=role,
        level="senior",
        occupation=occupation,
        bio="bio",
        interests=["x"],
        workspace=WorkspaceProfile(
            operating_mode="independent",
            primary_stack="Python + TypeScript",
            automation_level="agentic",
            active_since="2024-05-01",
        ),
        preferences=Preferences(response_language="zh-CN", units="metric", privacy_level="standard"),
        joined_at="2024-05-01",
        source=source,
    )


class _CountingDerive:
    """A model whose with_structured_output(...).ainvoke returns an empty derive (→ None)
    and counts how many times it was invoked."""

    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
        return self

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        from pneuma_knowledge_core.skill.pack import _DerivedPack

        return {"parsed": _DerivedPack(instructions="", templates=[]), "raw": None}


def _ctx(tmp_path, *, profiles, model, **settings_over):
    settings = Settings(canonical_root=str(tmp_path / "canonical"), **settings_over)
    canonical = GitCanonicalStore(settings.canonical_root)

    async def get_profile(uid):
        return profiles[str(uid)]

    return SimpleNamespace(
        settings=settings,
        canonical=canonical,
        user_info=SimpleNamespace(get_profile=get_profile),
        get_chat_model=lambda role="default": model,
    )


async def test_switch_off_returns_bare_base(tmp_path):
    uid = "u-off"
    ctx = _ctx(tmp_path, profiles={uid: _profile(uid)}, model=_CountingDerive(),
               user_schema_packs=False, user_schema_base_version="v1")
    skill = await skill_for_user(ctx, UserId(uid))
    assert skill.content_hash == load_skill_base("v1").content_hash
    # No manifest written when the switch is off.
    assert await ctx.canonical.read_meta(UserId(uid), "skill/manifest.json") is None


async def test_materializes_manifest_and_no_rederive_on_reload(tmp_path):
    uid = "u-mat"
    model = _CountingDerive()
    ctx = _ctx(tmp_path, profiles={uid: _profile(uid)}, model=model, user_schema_base_version="v1")

    first = await skill_for_user(ctx, UserId(uid))
    assert model.calls == 1  # derive ran once at first compile
    manifest = await ctx.canonical.read_meta(UserId(uid), "skill/manifest.json")
    assert manifest is not None and '"base_version": "v1"' in manifest

    second = await skill_for_user(ctx, UserId(uid))
    assert model.calls == 1  # reload composes from manifest — derive NOT re-run
    assert second.content_hash == first.content_hash
    assert render_system_contract(second) == render_system_contract(first)


async def test_deployment_matrix_path_reaches_auto_resolution(tmp_path):
    # Branch 3 (no manifest, first compile) must honor a deployment-supplied matrix: this
    # is the prose seam for pack wording. Without the plumb, replacing the built-in matrix
    # text required pre-writing a full manifest, which REPLACES auto-resolution.
    import json

    matrix = tmp_path / "deploy_matrix.json"
    matrix.write_text(json.dumps({"packs": [{
        "pack_id": "deploy-eng",
        "match": {"roles": ["engineering"], "industries": ["tech"]},
        "extra_instructions": "DEPLOYMENT-SUPPLIED PACK WORDING",
        "extra_path_templates": ["memory/deploy-projects/{slug}.md"],
    }]}), encoding="utf-8")

    uid = "u-matrix"
    ctx = _ctx(tmp_path, profiles={uid: _profile(uid)}, model=_CountingDerive(),
               user_schema_base_version="v1", user_schema_matrix_path=str(matrix))
    skill = await skill_for_user(ctx, UserId(uid))

    contract = render_system_contract(skill)
    assert "DEPLOYMENT-SUPPLIED PACK WORDING" in contract
    assert "memory/deploy-projects/{slug}.md" in skill.path_templates
    # The manifest records the resolved packs, so reloads never depend on the file again.
    manifest = await ctx.canonical.read_meta(UserId(uid), "skill/manifest.json")
    assert manifest is not None and "deploy-eng" in manifest


async def test_per_user_contracts_differ_and_are_stable(tmp_path, monkeypatch):
    # Differentiate packs by role, independent of the shipped matrix asset.
    async def fake_packs(profile, *, model=None, matrix_path=None, callbacks=None, trace_metadata=None):
        if profile.role == "engineering":
            return [SchemaPack(pack_id="role-eng", origin="matrix", extra_instructions="ENG",
                               extra_path_templates=["memory/projects/{slug}.md"])]
        return [SchemaPack(pack_id="role-sales", origin="matrix", extra_instructions="SALES",
                           extra_path_templates=["memory/deals/{slug}.md"])]

    monkeypatch.setattr(skills_mod, "packs_for_profile", fake_packs)

    profiles = {
        "u-eng": _profile("u-eng", role="engineering"),
        "u-sales": _profile("u-sales", role="sales"),
    }
    ctx = _ctx(tmp_path, profiles=profiles, model=_CountingDerive(), user_schema_base_version="v1")

    eng = await skill_for_user(ctx, UserId("u-eng"))
    sales = await skill_for_user(ctx, UserId("u-sales"))

    c_eng = render_system_contract(eng)
    c_sales = render_system_contract(sales)
    assert c_eng != c_sales
    assert "memory/projects/{slug}.md" in c_eng and "memory/deals/{slug}.md" in c_sales
    # Each user's contract is byte-stable across reloads (reads back from its manifest).
    assert render_system_contract(await skill_for_user(ctx, UserId("u-eng"))) == c_eng
    assert render_system_contract(await skill_for_user(ctx, UserId("u-sales"))) == c_sales


# --- the deployment must choose a contract ------------------------------------------


async def test_unset_base_version_fails_loud_instead_of_picking_a_contract(tmp_path):
    """`user_schema_base_version` has no default, and the miss must be self-explaining.

    It used to default to "v3", so a deployment that never chose one still compiled every
    user against this project's own personal-knowledge contract — and the manifest it then
    materialized recorded that choice as if it had been made. Failing here costs one
    startup; the old behaviour cost a knowledge base modelled for somebody else.
    """
    uid = "u-unset"
    ctx = _ctx(tmp_path, profiles={uid: _profile(uid)}, model=_CountingDerive(),
               user_schema_base_version="")
    with pytest.raises(LookupError) as excinfo:
        await skill_for_user(ctx, UserId(uid))
    message = str(excinfo.value)
    assert "register_skill_base" in message
    assert "packages/pneuma-knowledge-strategies/" in message
    # and it failed before writing anything into the user's repo
    assert await ctx.canonical.read_meta(UserId(uid), "skill/manifest.json") is None


async def test_unregistered_base_version_fails_loud_too(tmp_path):
    """A version string nobody registered is the same mistake, one step later."""
    uid = "u-unregistered"
    ctx = _ctx(tmp_path, profiles={uid: _profile(uid)}, model=_CountingDerive(),
               user_schema_base_version="v-nope")
    with pytest.raises(LookupError) as excinfo:
        await skill_for_user(ctx, UserId(uid))
    assert "v-nope" in str(excinfo.value)
