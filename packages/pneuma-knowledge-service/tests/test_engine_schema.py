"""The schema↔Settings sync pin (engine design, Ruling 3: the map is derived, never drawn).

Two failures matter here and both are deliberate tripwires:

* a strategy knob added to `Settings` that no stage covers and nothing classified as
  non-engine — the console (and the docs it feeds) would silently not know about it;
* a committed `engine-schema.json` that no longer matches what the code derives — a default
  changed, a stage retitled, a knob added, without regenerating the asset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pneuma_knowledge_service.engine.schema import (
    SCHEMA_PATH,
    SCHEMA_VERSION,
    build_schema,
    load_schema,
    serialize_schema,
)
from pneuma_knowledge_service.engine.stage_map import (
    ACCESS_ROUTES,
    APPLY_SEMANTICS,
    EDGES,
    KNOB_TYPES,
    NON_ENGINE_SETTINGS,
    STAGES,
    iter_knobs,
    knob_settings,
)
from pneuma_knowledge_service.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
REGENERATE = "uv run python scripts/generate_engine_schema.py"


def test_every_setting_is_either_an_engine_knob_or_classified_non_engine():
    covered = set(knob_settings())
    fields = set(Settings.model_fields)
    unclassified = fields - covered - NON_ENGINE_SETTINGS
    assert not unclassified, (
        "these Settings fields are neither engine knobs nor listed in NON_ENGINE_SETTINGS: "
        f"{sorted(unclassified)}. Decide: is it strategy a person edits (give it a knob in "
        "engine/stage_map.py and regenerate the schema) or deployment wiring (list it in "
        "NON_ENGINE_SETTINGS with the reason)?"
    )
    stale = NON_ENGINE_SETTINGS - fields
    assert not stale, f"NON_ENGINE_SETTINGS names settings that no longer exist: {sorted(stale)}"
    overlap = covered & NON_ENGINE_SETTINGS
    assert not overlap, f"a setting cannot be both a knob and non-engine: {sorted(overlap)}"


def test_committed_schema_is_exactly_what_the_code_derives():
    fresh = serialize_schema(build_schema())
    committed = SCHEMA_PATH.read_text(encoding="utf-8")
    assert fresh == committed, f"engine-schema.json is stale — regenerate: {REGENERATE}"


def test_loaded_schema_round_trips_as_json():
    schema = load_schema()
    assert schema["schema_version"] == SCHEMA_VERSION
    assert json.dumps(schema)  # serializable as an API response
    assert [s["id"] for s in schema["stages"]] == [s.id for s in STAGES]


def test_knob_declarations_stay_inside_the_frozen_vocabularies():
    for stage, knob in iter_knobs():
        where = f"{stage.id}.{knob.key}"
        assert knob.type in KNOB_TYPES, f"{where}: unknown type {knob.type!r}"
        assert knob.apply in APPLY_SEMANTICS, f"{where}: unknown apply {knob.apply!r}"
        if knob.type == "enum":
            assert knob.enum, f"{where}: an enum knob must list its values"
        else:
            assert not knob.enum, f"{where}: only enum knobs carry a literal enum"
        if knob.enum_source:
            assert knob.enum_source == "prompt_catalog", f"{where}: unknown enum source"
            assert knob.type == "overlay_map", f"{where}: only the overlay map is key-sourced"
        if knob.type in ("document", "overlay_map"):
            assert not knob.setting, f"{where}: {knob.type} knobs are not Settings fields"
            assert not knob.env, f"{where}: {knob.type} knobs have no env var"
        else:
            assert knob.setting, f"{where}: needs the Settings field it resolves into"
            assert knob.env.startswith("PNEUMA_KNOWLEDGE_"), f"{where}: env prefix"


def test_env_names_match_the_settings_prefix_convention():
    for _stage, knob in iter_knobs():
        if not knob.setting:
            continue
        assert knob.env == f"PNEUMA_KNOWLEDGE_{knob.setting.upper()}", (
            f"{knob.key}: the env var must be the prefixed setting name, or the precedence "
            "check would look at the wrong variable"
        )


def test_enum_defaults_are_inside_their_enum():
    schema = load_schema()
    for stage in schema["stages"]:
        for knob in stage["knobs"]:
            if knob["type"] == "enum":
                assert knob["default"] in knob["enum"], f"{stage['id']}.{knob['key']}"


def test_the_overlay_knob_carries_the_real_prompt_catalog_keys():
    """The console's overlay picker is fed by the catalog, not by a hand-kept copy of it."""
    from pneuma_knowledge_core.prompts import default_catalog

    schema = load_schema()
    prompts = next(s for s in schema["stages"] if s["id"] == "prompts")
    # by type, not by position: the stage also carries the language knob, and an index would
    # make this test pass or fail on the order the knobs happen to be declared in.
    overlay = next(k for k in prompts["knobs"] if k["type"] == "overlay_map")
    keys = overlay["enum"]
    assert keys == sorted(default_catalog())
    assert "compile.challenge.questions_system" in keys


def test_the_prompt_language_knob_offers_the_language_packs_core_actually_ships():
    """`en` is the catalog itself and needs no pack; every other value must resolve to a
    non-empty, total pack — an enum member with nothing behind it would silently do nothing."""
    from pneuma_knowledge_core.prompts import default_catalog

    from pneuma_knowledge_service.engine.prompts import language_pack

    schema = load_schema()
    prompts = next(s for s in schema["stages"] if s["id"] == "prompts")
    language = next(k for k in prompts["knobs"] if k["key"] == "language")
    assert language["default"] == "en"
    assert language_pack("en") == {}
    for value in language["enum"]:
        if value == "en":
            continue
        assert set(language_pack(value)) == set(default_catalog()), value


def test_stage_files_and_ids_are_unique_and_engine_relative():
    ids = [stage.id for stage in STAGES]
    files = [stage.file for stage in STAGES]
    assert len(set(ids)) == len(ids)
    assert len(set(files)) == len(files), "one file per stage: the apply path maps back by file"
    for stage in STAGES:
        assert not stage.file.startswith("/") and ".." not in stage.file


def test_edges_reference_real_stages_and_real_bool_conditions():
    ids = {stage.id for stage in STAGES}
    conditions = {
        f"{stage.id}.{knob.key}"
        for stage, knob in iter_knobs()
        if knob.type == "bool"
    }
    for edge in EDGES:
        assert edge.source in ids and edge.target in ids, edge
        if edge.condition:
            assert edge.condition in conditions, (
                f"edge condition {edge.condition!r} is not a bool knob — an arrow the console "
                "cannot evaluate would render as permanently off"
            )


# ------------------------------------------------------------------- the four access routes


def test_the_four_levels_are_all_declared_and_all_land_on_recall():
    """VERIFY #2: the canvas drew `intake → compile → recall` and nothing else, so a newcomer
    read the system as "material → LLM compile → answer". The four levels are PARALLEL views
    fused per question (architecture.md §3), and the fusion is exactly the fact that every one
    of them is answered in the recall stage — asserted, not narrated."""
    assert [route.id for route in ACCESS_ROUTES] == ["l0", "l1", "l2", "l3"]
    stage_ids = {stage.id for stage in STAGES}
    for route in ACCESS_ROUTES:
        assert route.source in stage_ids and route.target in stage_ids, route.id
        assert route.target == "recall", (
            f"{route.id} does not converge on recall — the four levels being fused at answer "
            "time is what makes them parallel views instead of a fallback chain"
        )
    # L0/L1 come off intake, L3 off compile: the compile route is a route, not the only one.
    assert {r.id for r in ACCESS_ROUTES if r.source == "intake"} == {"l0", "l1", "l2"}
    assert [r.id for r in ACCESS_ROUTES if r.source == "compile"] == ["l3"]


def test_l0_and_l1_are_declared_unconditional_and_l2_l3_per_source():
    """Invariant I3 in the picture: L0 and L1 reachability does not depend on anything, so a
    console must not draw them as gated. L2/L3 are gated by the intake plan — per source, and
    not by any engine setting, which is why the condition is not a knob reference."""
    gates = {route.id: route.condition for route in ACCESS_ROUTES}
    assert gates["l0"] == "" and gates["l1"] == ""
    assert gates["l2"] == "intake_plan.semantic_indexing"
    assert gates["l3"] == "intake_plan.canonical_treatment"


def test_an_access_route_condition_names_something_that_really_gates_it():
    """The drift pin. A knob condition must be a bool knob (as for edges); an `intake_plan.`
    condition must be a real field of core's IntakePlan, so renaming that field fails here
    instead of leaving the canvas explaining a gate that no longer exists."""
    from pneuma_knowledge_core.domain.intake import IntakePlan

    bool_knobs = {
        f"{stage.id}.{knob.key}" for stage, knob in iter_knobs() if knob.type == "bool"
    }
    plan_fields = set(IntakePlan.model_fields)
    for route in ACCESS_ROUTES:
        if not route.condition:
            continue
        scope, _, field = route.condition.partition(".")
        if scope == "intake_plan":
            assert field in plan_fields, (
                f"{route.id}: IntakePlan has no field {field!r} — the condition names a gate "
                "that does not exist"
            )
        else:
            assert route.condition in bool_knobs, route.id


def test_every_access_route_is_bilingual_and_says_more_than_its_title():
    for route in ACCESS_ROUTES:
        for value in (route.title_en, route.title_zh, route.summary_en, route.summary_zh):
            assert value.strip(), route.id
        assert route.summary_en != route.title_en and route.summary_zh != route.title_zh


def test_the_served_schema_carries_the_access_routes_in_the_frozen_shape():
    schema = load_schema()
    routes = schema["access_routes"]
    assert [r["id"] for r in routes] == [r.id for r in ACCESS_ROUTES]
    for served, route in zip(routes, ACCESS_ROUTES):
        assert set(served) == {"id", "from", "to", "title", "summary"} | (
            {"condition"} if route.condition else set()
        )
        assert served["from"] == route.source and served["to"] == route.target
        assert set(served["title"]) == {"en", "zh"}
        assert set(served["summary"]) == {"en", "zh"}


def _anchor(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug).strip("-")


@pytest.mark.parametrize("stage", STAGES, ids=[s.id for s in STAGES])
def test_stage_doc_links_resolve_in_this_repository(stage):
    """A dead deep link is exactly the rot Ruling 3 exists to prevent."""
    path, _, anchor = stage.doc.partition("#")
    target = REPO_ROOT / path
    assert target.is_file(), f"{stage.id}: doc link points at a missing file: {path}"
    if not anchor:
        return
    anchors = {
        _anchor(line.lstrip("#").strip())
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }
    assert anchor in anchors, f"{stage.id}: no heading in {path} anchors at #{anchor}"
