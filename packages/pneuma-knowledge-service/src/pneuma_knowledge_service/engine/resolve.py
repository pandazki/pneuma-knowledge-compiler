"""The three-level precedence chain: process env > engine file > framework default.

Explicit process environment wins so a benchmark harness can override any knob per run
without touching (or dirtying) the versioned engine directory. The engine file is the
durable truth a person edits. Unset everywhere falls through to the `Settings` default,
which is why an empty or absent engine directory is byte-for-byte the pre-engine behavior.

"Process env" means `os.environ` — an entry there outranks the engine file even when its
value is the empty string, because setting a variable to nothing is still a statement about
that variable. A value supplied by a `.env` FILE is not process env and ranks BELOW the
engine file: dotenv is where a deployment keeps its secrets and infrastructure, and a
strategy key that drifted into it must not silently outrank the versioned unit.

Nothing here awaits anything, so nothing here is a coroutine: it is file reads and dict
work, called once at settings assembly and once per state request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .files import EngineFileError, parse_mapping, parse_overlays, read_mapping
from .stage_map import STAGES, coerce_value, iter_knobs

_MISSING = object()


@dataclass(frozen=True)
class ResolvedEngine:
    """Everything one read of the engine directory yields.

    `overrides` are `Settings` init kwargs (only the keys the engine file states and the
    environment does not); `values` and `resolution` are the console's `<stage>.<key>` maps.
    """

    overrides: dict[str, Any]
    values: dict[str, Any]
    resolution: dict[str, str]


def _stage_mappings(
    engine_dir: str | Path,
    texts: Mapping[str, str] | None = None,
    *,
    lenient: bool = False,
) -> dict[str, dict[str, Any]]:
    """stage id → the flat mapping its file states. Document-only stages are skipped.

    `texts` substitutes a stage file's content for what is on disk — that is how a candidate
    state (disk + the changes an apply is about to write) is resolved through exactly this
    code path instead of a second interpretation of it. `lenient` forgives an unreadable file
    that the caller is NOT replacing: a file somebody broke by hand must not make an unrelated
    apply impossible, which is the same forgiveness the effect comparison already grants.
    """
    out: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        if all(knob.type == "document" for knob in stage.knobs):
            continue
        if texts is not None and stage.file in texts:
            out[stage.id] = parse_mapping(stage.file, texts[stage.file])
            continue
        try:
            out[stage.id] = read_mapping(engine_dir, stage.file)
        except EngineFileError:
            if not lenient:
                raise
            out[stage.id] = {}
    return out


def engine_overrides(
    engine_dir: str | Path,
    environ: Mapping[str, str],
    texts: Mapping[str, str] | None = None,
    *,
    lenient: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """(Settings init kwargs, `<stage>.<key>` → "env" | "engine" | "default").

    `document` knobs are absent from the resolution map by design: a document has no
    resolved scalar, it IS a file, and the console reads it out of the state's `files`.
    """
    mappings = _stage_mappings(engine_dir, texts, lenient=lenient)
    overrides: dict[str, Any] = {}
    resolution: dict[str, str] = {}
    for stage, knob in iter_knobs():
        if knob.type == "document":
            continue
        dotted = f"{stage.id}.{knob.key}"
        if knob.env and knob.env in environ:
            resolution[dotted] = "env"
            continue
        mapping = mappings.get(stage.id, {})
        if knob.type == "overlay_map":
            stated = parse_overlays(stage.file, mapping) if "overlays" in mapping else _MISSING
        else:
            stated = mapping.get(knob.key, _MISSING)
        if stated is _MISSING:
            resolution[dotted] = "default"
            continue
        resolution[dotted] = "engine"
        if knob.setting:
            overrides[knob.setting] = stated
    return overrides, resolution


def _settings_from(overrides: dict[str, Any]):
    """`Settings(**overrides)` with the one error message both callers should give."""
    from ..settings import Settings  # local: settings.py calls back into this module

    try:
        return Settings(**overrides)
    except Exception as exc:  # pydantic ValidationError and friends
        raise EngineFileError(f"the engine files do not validate as settings: {exc}") from exc


def assert_candidate_settings(
    engine_dir: str | Path, texts: Mapping[str, str], environ: Mapping[str, str]
) -> None:
    """Refuse a change set whose resulting engine directory `/state` could not read back.

    The per-knob type and enum checks in `apply` are the console's fast, specific rejections;
    this is the total one, and it is the SAME resolution `/state` runs — so "apply succeeded
    and then /state was 400" stops being a reachable state rather than a bug to remember.
    Files the change set does not touch are read leniently: one broken by hand must not block
    the apply that repairs a different one.
    """
    overrides, _ = engine_overrides(engine_dir, environ, texts, lenient=True)
    _settings_from(overrides)


def resolve_engine(engine_dir: str | Path, environ: Mapping[str, str]) -> ResolvedEngine:
    """The engine directory's current truth, coerced through `Settings` validation.

    Values are read back off a `Settings` built with the resolved overrides rather than off
    the raw YAML: that way what the console displays is exactly what the framework would
    use, including the environment's contribution and every type coercion, instead of a
    second interpretation of the same files.
    """
    overrides, resolution = engine_overrides(engine_dir, environ)
    settings = _settings_from(overrides)
    mappings = _stage_mappings(engine_dir)
    values: dict[str, Any] = {}
    for stage, knob in iter_knobs():
        if knob.type == "document":
            continue
        dotted = f"{stage.id}.{knob.key}"
        if knob.setting:
            values[dotted] = coerce_value(knob, getattr(settings, knob.setting))
        elif knob.type == "overlay_map":
            values[dotted] = parse_overlays(stage.file, mappings.get(stage.id, {}))
    return ResolvedEngine(overrides=overrides, values=values, resolution=resolution)
