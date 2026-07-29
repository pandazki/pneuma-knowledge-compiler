"""Per-user skill: resolve → persist → load (schema-evolve M1, §1.3).

`skill_for_user` is the service-side entry the compile worker calls per job to get the
skill a given owner compiles with:

  1. `user_schema_packs` off → the bare base version (no packs, no manifest).
  2. A persisted `skill/manifest.json` in the user's canonical repo → recompose from its
     recorded base_version + packs (no re-derive; the LLM inference ran once, at first
     compile).
  3. No manifest → resolve packs from the owner's picture (matrix + optional LLM derive),
     compose, and **materialize** the manifest into the canonical repo (registration timing
     is not the service's to observe, so the first compile is where a per-user skill is
     physically written).

The manifest lives in the same per-user git repo as the data it governs, but off the
compile gate: it is written via the git adapter's narrow read_meta/write_meta pair, not
commit_patch (skill/ is not a compile product — no path ownership, no compile_events).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill import (
    SchemaPack,
    compose_skill,
    load_builtin_skill,
    packs_for_profile,
)
from pneuma_knowledge_core.skill.version import SkillVersion

# Non-canonical meta path inside the per-user git repo (off the compile gate).
_MANIFEST_PATH = "skill/manifest.json"
MANIFEST_PATH = _MANIFEST_PATH  # public alias (evolve rides the same manifest on its branch)


def serialize_manifest(
    base: SkillVersion, packs: list[SchemaPack], composed: SkillVersion
) -> str:
    """The byte-shape of skill/manifest.json — base_version + the full pack list + the
    composed content hash. Shared by first-compile materialization (here) and the evolve
    flow (which appends evolved packs onto the same manifest so an adopt reloads correctly)."""
    manifest = {
        "base_version": base.version,
        "packs": [p.model_dump() for p in packs],
        "content_hash": composed.content_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


async def read_manifest(ctx, user_id: UserId) -> dict | None:
    """The persisted skill manifest at HEAD (base_version + packs), or None."""
    return await _read_manifest(ctx, user_id)


async def _read_manifest(ctx, user_id: UserId) -> dict | None:
    raw = await ctx.canonical.read_meta(user_id, _MANIFEST_PATH)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _write_manifest(
    ctx,
    user_id: UserId,
    base: SkillVersion,
    packs: list[SchemaPack],
    composed: SkillVersion,
) -> None:
    content = serialize_manifest(base, packs, composed)
    await ctx.canonical.write_meta(
        user_id,
        _MANIFEST_PATH,
        content,
        message="skill: materialize per-user schema manifest",
    )


async def skill_for_user(ctx, user_id: UserId) -> SkillVersion:
    """The SkillVersion this user compiles with (see module docstring)."""
    settings = ctx.settings
    if not settings.user_schema_packs:
        return load_builtin_skill(settings.user_schema_base_version)

    manifest = await _read_manifest(ctx, user_id)
    if manifest is not None:
        base = load_builtin_skill(
            str(manifest.get("base_version") or settings.user_schema_base_version)
        )
        packs = [SchemaPack(**p) for p in manifest.get("packs", [])]
        return compose_skill(base, packs)

    # First compile for this user: materialize the manifest now.
    base = load_builtin_skill(settings.user_schema_base_version)
    profile = await ctx.user_info.get_profile(user_id)
    # derive needs an LLM; a build/route failure degrades to matrix-only packs.
    try:
        model = ctx.get_chat_model("compile")
    except Exception:  # noqa: BLE001
        model = None
    packs = await packs_for_profile(
        profile, model=model, matrix_path=settings.user_schema_matrix_path
    )
    composed = compose_skill(base, packs)
    await _write_manifest(ctx, user_id, base, packs, composed)
    return composed
