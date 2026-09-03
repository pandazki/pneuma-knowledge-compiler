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
import logging
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill import (
    SchemaPack,
    compose_skill,
    load_skill_base,
    packs_for_profile,
)
from pneuma_knowledge_core.skill.version import SkillVersion

_log = logging.getLogger(__name__)

# Non-canonical meta path inside the per-user git repo (off the compile gate).
_MANIFEST_PATH = "skill/manifest.json"
MANIFEST_PATH = _MANIFEST_PATH  # public alias (evolve rides the same manifest on its branch)


def base_named_or_current(settings, named: str) -> tuple[SkillVersion, bool]:
    """The base a persisted manifest names, or the deployment's current one if it is gone.

    A manifest records the base the user's skill was composed from, and that record outlives
    the contract: an operator who advances the engine's contract (app-v2 → app-v3) registers
    ONE base, and every user manifest written before that names a version the registry no
    longer holds. Reading a library must not depend on the contract that produced it — the
    documents are already written, and a retired version is exactly what the architecture
    promises a commit may keep naming. So a name the registry cannot resolve falls back to
    the version the deployment runs today, and the caller is told (`True`) so a write path
    can re-materialize the manifest while a read path simply renders.

    A deployment with NOTHING registered still fails loudly — that is a misconfiguration,
    not a retirement, and `load_skill_base` says so with every door out.
    """
    version = (named or "").strip()
    current = str(settings.user_schema_base_version)
    if version and version != current:
        try:
            return load_skill_base(version), False
        except LookupError:
            pass
    return load_skill_base(current), bool(version) and version != current


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


async def packs_for_user(ctx, user_id: UserId) -> list[SchemaPack]:
    """The user's persisted SchemaPacks, or [] — the family blurbs the recall glance reads.

    `skill_for_user` composes packs INTO a SkillVersion, which is what compiling needs but
    loses which pack declared which family and what it said it collects. The glance needs
    exactly that pairing (`extra_path_templates` × `extra_instructions`), so it is read back
    off the same manifest rather than reconstructed from the composed skill. Never fatal: no
    manifest, packs disabled, or a malformed entry all mean "no blurbs", and the glance still
    lists what exists.
    """
    if not ctx.settings.user_schema_packs:
        return []
    manifest = await _read_manifest(ctx, user_id)
    if manifest is None:
        return []
    packs: list[SchemaPack] = []
    for entry in manifest.get("packs", []) or []:
        try:
            packs.append(SchemaPack(**entry))
        except (TypeError, ValueError):
            continue
    return packs


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


async def path_templates_for(settings, canonical, user_id: UserId) -> list[str]:
    """The path families this user's contract declares — READ-ONLY, and no ctx required.

    `skill_for_user` is the write-capable resolution: it may derive packs with a model and
    materialize a manifest. This is the same question asked by something that must not do
    either — an index component rendering a report, where inventing a user's schema as a
    side effect of grouping some paths would be absurd. So: persisted manifest if there is
    one, the deployment's base if there is not, and `[]` if the deployment registered no
    base at all (a keyless test, a fresh install). Never writes, never calls a model.

    The failures it absorbs are NAMED, and that is the difference from a bare `except
    Exception`. Three things can legitimately go wrong here — no contract base is
    registered, the manifest will not read, the manifest reads but will not compose — and
    each of them means "this user has no declared families", which a report renders as one
    unfiled group. The last two are logged with the user id, because a manifest that will
    not compose is a repair somebody has to make. Anything ELSE is a programming error, and
    swallowing it turned every path in every report unfiled with no trace of why; it now
    reaches the caller's own fail-soft boundary (the component's `_families`), which logs it
    with a traceback and renders the same ungrouped report.

    `TypeError` is named the same way, and only where it can mean the manifest: a pack
    entry that is not a mapping of `SchemaPack`'s own fields raises before pydantic ever
    validates, so it is caught AT that construction and re-raised as the malformed manifest
    it is. A `TypeError` from `compose_skill` is a bug in composition and travels on — the
    broad catch turned it into "no families" too, which is the failure this docstring is
    about, one layer down.
    """
    try:
        if not settings.user_schema_packs:
            return list(load_skill_base(settings.user_schema_base_version).path_templates)
        raw = await canonical.read_meta(user_id, _MANIFEST_PATH)
        manifest = json.loads(raw) if raw else None
        if not isinstance(manifest, dict):
            return list(load_skill_base(settings.user_schema_base_version).path_templates)
        base, _retired = base_named_or_current(
            settings, str(manifest.get("base_version") or "")
        )
        try:
            packs = [SchemaPack(**p) for p in manifest.get("packs", [])]
        except TypeError as exc:
            raise ValueError(f"malformed schema pack: {exc}") from exc
        return list(compose_skill(base, packs).path_templates)
    except LookupError:
        # No contract base is registered at all: a keyless test, a fresh install. Expected,
        # and not a failure to warn about — there is simply nothing declared to group by.
        return []
    except (OSError, ValueError) as exc:
        # The manifest could not be read (canonical unreachable), could not be parsed
        # (`json.JSONDecodeError` is a ValueError), or would not validate (`ValidationError`
        # is a ValueError; a pack of the wrong shape arrives here as the ValueError raised
        # at its construction above).
        _log.warning(
            "path templates for %s could not be resolved (%s: %s); reporting no families",
            user_id,
            type(exc).__name__,
            exc,
        )
        return []


async def skill_for_user(ctx, user_id: UserId) -> SkillVersion:
    """The SkillVersion this user compiles with (see module docstring)."""
    settings = ctx.settings
    if not settings.user_schema_packs:
        return load_skill_base(settings.user_schema_base_version)

    manifest = await _read_manifest(ctx, user_id)
    if manifest is not None:
        base, retired = base_named_or_current(
            settings, str(manifest.get("base_version") or "")
        )
        packs = [SchemaPack(**p) for p in manifest.get("packs", [])]
        composed = compose_skill(base, packs)
        if retired:
            # The contract this user was composed against is no longer registered: the
            # operator advanced the engine. A new version is meant to shape future compiles,
            # so this compile follows it and the manifest is rewritten to name it — with the
            # same packs, which are additive and independent of the base's body.
            await _write_manifest(ctx, user_id, base, packs, composed)
        return composed

    # First compile for this user: materialize the manifest now.
    base = load_skill_base(settings.user_schema_base_version)
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
