"""engine-schema.json: derived from `Settings` metadata + the hand-authored stage map.

Ruling 3 of the engine design: the map is derived, never drawn. A hand-maintained diagram
of "what this engine does" rots the first time a default changes; this module builds the
whole picture from two sources that cannot silently disagree with the code —
`stage_map.STAGES` / `EDGES` / `ACCESS_ROUTES` for structure, and `Settings` field defaults
for values.

The built product is committed as `assets/engine-schema.json` so the API can serve it (and
a reader can read it) without importing anything, and `scripts/generate_engine_schema.py`
regenerates it. `tests/test_engine_schema.py` pins the two together: a default changed in
`Settings`, a knob added, or a stage retitled without regenerating fails the suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..settings import Settings
from .files import overlay_catalog_keys
from .stage_map import ACCESS_ROUTES, EDGES, STAGES, Knob, coerce_value

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).resolve().parent / "assets" / "engine-schema.json"


def _settings_default(field_name: str) -> Any:
    field = Settings.model_fields[field_name]
    return field.default


def knob_default(knob: Knob) -> Any:
    """The framework default this knob falls back to when neither env nor engine states it.

    Read from `Settings` for knobs backed by a setting, so the schema cannot drift from the
    code. `int`-typed knobs are normalized to `int` because the console has integer
    steppers only — `evolve_draft_ttl_hours` is a float setting whose default is a whole
    number of hours, and reporting `24.0` as an integer knob's default would just be noise.
    """
    if not knob.setting:
        return knob.literal_default
    return coerce_value(knob, _settings_default(knob.setting))


def knob_enum(knob: Knob) -> tuple[str, ...]:
    """The values (or, for the overlay map, the KEYS) this knob accepts.

    A literal list for an ordinary enum; for the prompt overlay knob, the framework's own
    catalog keys, so the console's overlay picker is fed by the code rather than by a
    hand-kept copy of it.
    """
    if knob.enum_source == "prompt_catalog":
        return overlay_catalog_keys()
    return knob.enum


def _knob_json(knob: Knob) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": knob.key,
        "env": knob.env,
        "type": knob.type,
    }
    allowed = knob_enum(knob)
    if allowed:
        out["enum"] = list(allowed)
    out["default"] = knob_default(knob)
    out["apply"] = knob.apply
    out["label"] = {"en": knob.label_en, "zh": knob.label_zh}
    out["description"] = {"en": knob.description_en, "zh": knob.description_zh}
    return out


def build_schema() -> dict[str, Any]:
    """The engine schema, freshly derived. The committed asset is this, serialized."""
    return {
        "schema_version": SCHEMA_VERSION,
        "stages": [
            {
                "id": stage.id,
                "title": {"en": stage.title_en, "zh": stage.title_zh},
                "summary": {"en": stage.summary_en, "zh": stage.summary_zh},
                "doc": stage.doc,
                "file": stage.file,
                "knobs": [_knob_json(knob) for knob in stage.knobs],
            }
            for stage in STAGES
        ],
        "edges": [
            {
                "from": edge.source,
                "to": edge.target,
                **({"condition": edge.condition} if edge.condition else {}),
                "label": {"en": edge.label_en, "zh": edge.label_zh},
            }
            for edge in EDGES
        ],
        # The other half of the picture: `edges` is what the pipeline DOES to material,
        # `access_routes` is how the same material stays reachable afterwards. A map with only
        # the first reads as "everything is answered out of the compile step", which is the
        # architecture's central claim inverted.
        "access_routes": [
            {
                "id": route.id,
                "from": route.source,
                "to": route.target,
                **({"condition": route.condition} if route.condition else {}),
                "title": {"en": route.title_en, "zh": route.title_zh},
                "summary": {"en": route.summary_en, "zh": route.summary_zh},
            }
            for route in ACCESS_ROUTES
        ],
    }


def serialize_schema(schema: dict[str, Any]) -> str:
    """The exact bytes of the committed asset (so the pin test compares text, not dicts)."""
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def load_schema() -> dict[str, Any]:
    """The COMMITTED schema — what `GET /v1/engine/schema` serves.

    Deliberately the asset rather than `build_schema()`: the file is the artifact the
    console, the docs and any external reader share, and serving the asset means the API
    can never quietly disagree with what is in the repository. The pin test is what keeps
    the asset honest.
    """
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
