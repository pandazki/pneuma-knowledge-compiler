"""Applying a set of engine-file edits: validate, write, commit, report the blast radius.

Every rejection here is mechanical and happens BEFORE anything is written, which is the
only reason the console can never leave the engine directory in a state it cannot read back:

* the path must address a file inside the engine directory, spelled canonically
  (`files.assert_canonical_path`) — `validate` RETURNS that canonical set, and every later
  step consumes its return value, so "what was validated" and "what was written" are the
  same list of the same strings rather than two readings of the request;
* the content must be within the same size cap the read side enforces
  (`files.assert_within_size`) and must not be API-key-shaped (`files.assert_no_key_shape`);
* a stage file must still parse as its flat mapping, may only state keys the stage declares,
  and every stated value must match its knob's declared type and enum;
* and the resulting directory as a whole must resolve through the same `Settings`
  construction `/state` runs, so "committed, then unreadable" is not a reachable state.

The returned effects are the honesty feature: each knob whose value actually changed is
reported with its apply semantics, so the console states the blast radius of what was just
committed rather than a generic "saved".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .files import (
    EngineFileError,
    EnginePathError,
    assert_canonical_path,
    assert_no_key_shape,
    assert_within_size,
    engine_path,
    engine_root,
    overlay_catalog_keys,
    parse_mapping,
    parse_overlays,
)
from .gitops import EngineHeadMismatch, commit_paths, version
from .resolve import assert_candidate_settings
from .stage_map import Knob, Stage, stage_by_file


# Sentinel for "this file does not state the key at all", distinct from any YAML value.
_ABSENT = object()


@dataclass(frozen=True)
class Change:
    path: str  # engine-relative
    content: str


@dataclass(frozen=True)
class Effect:
    key: str  # <stage>.<key>
    apply: str


def _type_problem(knob: Knob, value: Any) -> str | None:
    """Why `value` is not an acceptable value for `knob` — or None when it is."""
    if knob.type == "bool":
        if not isinstance(value, bool):
            return "must be true or false"
        return None
    if knob.type == "int":
        # Whole numbers only, and bool is an int subclass in Python so it has to be excluded
        # by hand. The frozen knob vocabulary has no float, the console renders integer
        # steppers, and `1.5` used to pass here and then fail Settings validation on the next
        # /state — after it had already been committed.
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be a whole number"
        return None
    if knob.type in ("string", "enum"):
        if not isinstance(value, str):
            return "must be a string"
        if knob.type == "enum" and value not in knob.enum:
            return f"must be one of {', '.join(knob.enum)}"
        return None
    return None


def _assert_slots_preserved(rel: str, overlays: Mapping[str, str]) -> None:
    """An overlay must declare exactly the named placeholders its original declares.

    A placeholder is not decoration: `{cite}` is where the framework injects this mode's
    citation granularity, `{templates}` is where the skill's own path families land. An
    overlay that drops one does not "simplify the wording" — it deletes a value the
    framework computed, silently, in the one layer nobody re-reads afterwards. An overlay
    that ADDS one is worse: nothing substitutes it, so literal braces reach the model.

    Deliberately stricter than `prompts.override_prompt`, which tolerates a subset. That
    seam is a library call an author writes deliberately with the default in front of
    them; this is a console where somebody rewrites a clause from an intent and cannot see
    what the framework was going to put there. So the console refuses the save, naming
    exactly which slots went missing, instead of committing a prompt that quietly renders
    short.
    """
    from pneuma_knowledge_core.prompts import default_catalog, template_fields

    catalog = default_catalog()
    for key in sorted(overlays):
        original = template_fields(catalog[key])
        replacement = template_fields(overlays[key])
        missing = sorted(original - replacement)
        extra = sorted(replacement - original)
        if missing:
            raise EngineFileError(
                f"{rel}: the override for {key} drops the placeholder(s) "
                f"{', '.join('{' + name + '}' for name in missing)}. The framework "
                "substitutes a real value there, so an override without it renders short "
                "— keep every placeholder the original declares, spelled exactly."
            )
        if extra:
            raise EngineFileError(
                f"{rel}: the override for {key} introduces the placeholder(s) "
                f"{', '.join('{' + name + '}' for name in extra)}, which the original "
                "does not declare. Nothing substitutes them, so they would reach the "
                "model as literal braces."
            )


def _validate_stage_mapping(stage: Stage, mapping: dict[str, Any]) -> None:
    declared = {knob.key: knob for knob in stage.knobs if knob.type != "document"}
    for key, value in mapping.items():
        knob = declared.get(key)
        if knob is None:
            raise EngineFileError(
                f"{stage.file}: unknown key {key!r}. This file states only: "
                f"{', '.join(sorted(declared)) or '(nothing)'}. A key the framework does not "
                "read would sit there looking effective forever, so it is refused on write."
            )
        if knob.type == "overlay_map":
            overlays = parse_overlays(stage.file, {"overlays": value})
            # An overlay whose key is not a real catalog surface is the worst kind of
            # config: the framework wording keeps reaching the model while the deployment
            # believes it replaced it. `override_prompts` refuses it at startup; refusing it
            # at write time means the console can never save one.
            allowed = set(overlay_catalog_keys())
            unknown = sorted(set(overlays) - allowed)
            if unknown:
                raise EngineFileError(
                    f"{stage.file}: not prompt-catalog keys, so overriding them would replace "
                    f"nothing: {', '.join(unknown)}"
                )
            _assert_slots_preserved(stage.file, overlays)
            continue
        problem = _type_problem(knob, value)
        if problem is not None:
            raise EngineFileError(f"{stage.file}: {key} {problem} (got {value!r})")


def validate(
    engine_dir: str | Path,
    changes: Iterable[Change],
    environ: Mapping[str, str] | None = None,
) -> list[Change]:
    """Refuse every change the engine directory will not accept; return the canonical set.

    Writes nothing, and the returned list — canonical paths, deduplicated — is what callers
    must use from here on. Returning it rather than validating in place is the mechanism: a
    caller cannot accidentally write the request's own strings, because the only set it was
    handed back is the checked one.

    The last step is the total one: the whole candidate directory (disk plus these changes)
    must resolve through the same `Settings` construction `/state` performs. Per-knob checks
    catch the specific mistakes with specific messages; this catches everything else before it
    is committed rather than after.
    """
    canonical: list[Change] = []
    seen: set[str] = set()
    for change in changes:
        rel = assert_canonical_path(engine_dir, change.path)
        if rel in seen:
            raise EnginePathError(f"{rel} appears twice in one apply")
        seen.add(rel)
        assert_within_size(rel, change.content)
        assert_no_key_shape(rel, change.content)
        canonical.append(Change(path=rel, content=change.content))
        stage = stage_by_file(rel)
        if stage is None:
            continue  # a free file (README, notes) — no shape to enforce
        if all(knob.type == "document" for knob in stage.knobs):
            continue  # a document is prose; the framework has no shape opinion about it
        _validate_stage_mapping(stage, parse_mapping(rel, change.content))
    assert_candidate_settings(
        engine_dir,
        {change.path: change.content for change in canonical},
        os.environ if environ is None else environ,
    )
    return canonical


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _mapping_or_nothing(rel: str, text: str) -> dict[str, Any]:
    """What a file on disk currently states, or `{}` when it states nothing readable.

    Forgiving ONLY for the old side of an effect comparison. A file somebody broke by hand
    outside the console must not make the change that repairs it un-appliable: every knob in
    the new content simply counts as changed. The new side is never forgiven — `validate`
    has already refused it.
    """
    if not text.strip():
        return {}
    try:
        return parse_mapping(rel, text)
    except EngineFileError:
        return {}


def plan_effects(engine_dir: str | Path, changes: Iterable[Change]) -> list[Effect]:
    """The apply semantics of every knob whose value this change set actually alters.

    Compared against what is on disk right now, so re-applying an unchanged file reports no
    effect at all — the console's badge tells the truth about this apply, not about the file.
    Takes the canonical set `validate` returned; a raw request path would land in
    `stage_by_file` as an unrecognized file and report no effect for a real knob change.
    """
    effects: list[Effect] = []
    seen: set[str] = set()
    for change in changes:
        stage = stage_by_file(change.path)
        if stage is None:
            continue
        old_text = _read(engine_path(engine_dir, change.path))
        if all(knob.type == "document" for knob in stage.knobs):
            if old_text != change.content:
                for knob in stage.knobs:
                    key = f"{stage.id}.{knob.key}"
                    if key not in seen:
                        seen.add(key)
                        effects.append(Effect(key=key, apply=knob.apply))
            continue
        old = _mapping_or_nothing(change.path, old_text)
        new = parse_mapping(change.path, change.content)
        for knob in stage.knobs:
            if knob.type == "document":
                continue
            if old.get(knob.key, _ABSENT) == new.get(knob.key, _ABSENT):
                continue
            key = f"{stage.id}.{knob.key}"
            if key not in seen:
                seen.add(key)
                effects.append(Effect(key=key, apply=knob.apply))
    return effects


def apply_changes(
    engine_dir: str | Path,
    changes: list[Change],
    label: str,
    expected_head: str | None = None,
) -> tuple[str, list[Effect]]:
    """Validate → write → one commit of exactly those files. Returns (commit sha, effects).

    Synchronous on purpose: it is filesystem writes plus `git` subprocesses, and the whole
    sequence must stay atomic inside one thread. The route hands it to `asyncio.to_thread`
    inside the deployment's apply lock, so the check below and the commit cannot be
    interleaved by a second request.

    `expected_head` is the HEAD the change set was composed against. The console sends whole
    files, so a second editor working from an older read would roll back the first one's
    values with no sign that it happened; naming the read makes that a refusal instead. None
    means "no precondition" — the CLI and older clients keep working unchanged.
    """
    root = engine_root(engine_dir)
    if expected_head is not None:
        current = version(root).head
        if current != expected_head:
            raise EngineHeadMismatch(expected_head, current)
    changes = validate(root, changes)
    effects = plan_effects(root, changes)
    for change in changes:
        target = engine_path(root, change.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
    sha = commit_paths(root, label, [change.path for change in changes])
    return sha, effects
