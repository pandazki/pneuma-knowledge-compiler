"""Profile hypotheses survive persistence, remain visible, and can be confirmed per leaf."""

import io
import json
from types import SimpleNamespace

import pytest

from pneuma_knowledge_core.domain.user import PROFILE_FIELDS, UserProfile
from pneuma_knowledge_core.persona.provenance import annotated_value, inferred_fields, profile_fields
from pneuma_knowledge_core.skill import load_skill_base, render_system_contract
from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.persona_profile import (
    is_placeholder, owner_profile, profile_notice, read_profile_data, save_owner_profile,
)

from _cli_library import USER, library
from test_profile_cli import _project, run


async def test_steward_inferences_round_trip_and_confirmation_is_per_field(tmp_path, monkeypatch):
    engine = _project(tmp_path)
    lib = library(engine_dir=str(engine))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH", "synthetic-skill-hash")
    code, text, err = await run(
        lib, "profile", "set", "--field", "display_name=Morgan Vale",
        "--field", "occupation=Cartographer", "--field", "locale.timezone=Europe/Paris", "--json",
    )
    assert code == 0, err
    profile = json.loads(text)["profile"]
    assert set(PROFILE_FIELDS) <= profile["provenance"].keys()
    assert profile["provenance"]["display_name"] == "inferred"
    assert profile["provenance"]["level"] == "placeholder"
    assert profile["provenance"]["locale.timezone"] == "inferred"
    assert profile["locale"]["timezone"] == "Europe/Paris"
    assert read_profile_data(engine)["provenance"] == profile["provenance"]
    assert (await lib.store.get_user_profile(USER))["provenance"] == profile["provenance"]
    assert await lib.store.get_user_profile("another-owner") is None

    code, text, err = await run(lib, "profile", "show")
    assert code == 0, err
    assert all(key in text for key in PROFILE_FIELDS)
    assert "Morgan Vale (inferred)" in text
    before = await lib.ctx.user_info.get_profile(USER)
    assert "Morgan Vale (inferred)" in render_system_contract(load_skill_base("v1"), before)

    code, text, err = await run(lib, "profile", "confirm", "--field", "display_name", "--json")
    assert code == 0, err
    partial = json.loads(text)["profile"]
    assert partial["provenance"]["display_name"] == "owner"
    assert partial["provenance"]["occupation"] == "inferred"
    assert partial["occupation"] == "Cartographer"
    code, text, err = await run(lib, "profile", "confirm", "--all", "--json")
    assert code == 0, err
    confirmed = await lib.ctx.user_info.get_profile(USER)
    assert not inferred_fields(confirmed)
    assert not profile_notice(confirmed)
    for key in PROFILE_FIELDS:
        assert confirmed.provenance[key] == "owner"
    assert read_profile_data(engine)["provenance"] == confirmed.provenance
    assert confirmed.display_name == before.display_name
    assert confirmed.locale == before.locale


async def test_owner_default_explicit_override_and_partial_updates_without_engine(monkeypatch):
    monkeypatch.delenv("PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH", raising=False)
    lib = library(engine_dir="")
    assert (await run(lib, "profile", "set", "--field", "display_name=Morgan Vale"))[0] == 0
    profile = await lib.ctx.user_info.get_profile(USER)
    assert profile.provenance["display_name"] == "owner"
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH", "synthetic")
    assert (await run(lib, "profile", "set", "--field", "bio=Maps estuaries", "--provenance", "owner"))[0] == 0
    assert (await run(lib, "profile", "set", "--field", "occupation=Cartographer"))[0] == 0
    profile = await lib.ctx.user_info.get_profile(USER)
    assert profile.display_name == "Morgan Vale"
    assert profile.bio == "Maps estuaries"
    assert profile.provenance["bio"] == "owner"
    assert profile.provenance["occupation"] == "inferred"


async def test_stdin_payload_and_all_editable_leaves_have_provenance(tmp_path, monkeypatch):
    lib = library(engine_dir=str(_project(tmp_path)))
    payload = {
        "display_name": "Morgan Vale", "occupation": "Cartographer", "bio": "Makes maps",
        "interests": ["rivers", "canals"], "industry": "creative", "role": "design", "level": "senior",
        "locale": {"city": "Paris", "country": "FR", "timezone": "Europe/Paris", "language": "fr-FR"},
        "preferences": {"response_language": "fr-FR"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    args = build_parser().parse_args(["profile", "set", "-", "--provenance", "inferred", "--json"])
    out, err = io.StringIO(), io.StringIO()
    assert await dispatch(lib.ctx, args, out=out, err=err) == 0, err.getvalue()
    profile = json.loads(out.getvalue())["profile"]
    provenance = profile["provenance"]
    assert all(provenance[key] == "inferred" for key in PROFILE_FIELDS)
    assert profile_fields(profile) == profile_fields(payload)


def test_owner_rendering_preserves_historical_bytes_and_inferred_rendering_is_stable():
    profile = owner_profile(USER, {
        "display_name": "Morgan Vale", "occupation": "Cartographer", "bio": "Maps estuaries",
        "interests": ["rivers"], "level": "mid",
        "locale": {"city": "Paris", "country": "FR", "timezone": "Europe/Paris", "language": "fr-FR"},
        "provenance": {key: "owner" for key in PROFILE_FIELDS},
    })
    # The old renderer's input shape has identical values and no provenance field.
    old = SimpleNamespace(**{key: getattr(profile, key) for key in type(profile).model_fields if key != "provenance"})
    skill = load_skill_base("v1")
    assert render_system_contract(skill, profile) == render_system_contract(skill, old)
    inferred = profile.model_copy(deep=True)
    inferred.provenance = {key: "inferred" for key in PROFILE_FIELDS}
    rendered = render_system_contract(skill, inferred)
    assert rendered == render_system_contract(skill, inferred)
    for value in ["Morgan Vale", "Cartographer", "Maps estuaries", "rivers", "Paris", "FR", "Europe/Paris", "fr-FR"]:
        assert f"{value} (inferred)" in rendered
    assert "level: mid (inferred)" in rendered


async def test_file_comments_nested_fields_and_escaped_values_survive_repeated_writes(tmp_path):
    engine = _project(tmp_path)
    lib = library(engine_dir=str(engine))
    for key, value in [
        ("display_name", 'Morgan "Vale"'), ("locale.city", "Paris"),
        ("interests", ['river "Delta"', "canals\\locks"]), ("bio", "Maps: water # terrain\nSecond line"),
    ]:
        profile, _ = await save_owner_profile(lib.store, USER, engine, {key: value}, provenance="inferred")
        data = read_profile_data(engine)
        assert data["provenance"] == profile.provenance
    text = (engine / "persona/profile.yaml").read_text()
    assert text.count("\nprovenance:") == 1
    assert text.count("\nlocale:") == 1
    assert "# how the owner is addressed" in text
    assert data["locale"]["city"] == "Paris"
    assert data["bio"] == "Maps: water # terrain\nSecond line"
    assert data["interests"] == ['river "Delta"', "canals\\locks"]


async def test_failed_store_write_restores_profile_file(tmp_path, monkeypatch):
    engine = _project(tmp_path)
    path = engine / "persona/profile.yaml"
    before = path.read_bytes()
    lib = library(engine_dir=str(engine))
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic store failure")
    monkeypatch.setattr(lib.store, "upsert_user_profile", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        await save_owner_profile(lib.store, USER, engine, {"bio": "Maps"}, provenance="inferred")
    assert path.read_bytes() == before


@pytest.mark.parametrize("language", ["no", "NO", "on", "off", "true", "false", "null"])
async def test_unquoted_language_field_keeps_yaml_reserved_words_as_text(tmp_path, language):
    engine = _project(tmp_path)
    path = engine / "persona/profile.yaml"
    path.write_text(path.read_text().replace('response_language: ""', "response_language: en"))
    lib = library(engine_dir=str(engine))
    profile, _ = await save_owner_profile(
        lib.store, USER, engine, {"preferences.response_language": language},
        provenance="inferred",
    )
    assert read_profile_data(engine)["preferences"]["response_language"] == language
    assert profile.preferences.response_language == language
    assert (await lib.store.get_user_profile(USER))["preferences"]["response_language"] == language


async def test_profile_api_edit_confirms_only_edited_fields_and_updates_the_engine(tmp_path):
    from pneuma_knowledge_service.api.routes.v1 import ProfileUpdateIn, put_profile

    engine = _project(tmp_path)
    lib = library(engine_dir=str(engine))
    await save_owner_profile(lib.store, USER, engine,
                             {"display_name": "Morgan Vale", "occupation": "Cartographer"},
                             provenance="inferred")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=lib.ctx)))
    profile = await put_profile(str(USER), ProfileUpdateIn(occupation="Surveyor"), request)
    assert profile.provenance["occupation"] == "owner"
    assert profile.provenance["display_name"] == "inferred"
    assert read_profile_data(engine)["occupation"] == "Surveyor"
    assert read_profile_data(engine)["provenance"] == profile.provenance


async def test_draft_open_prints_one_inference_notice_without_refusing():
    from test_draft_cli import harness, source
    from pneuma_knowledge_service.cli.draft import cmd_open

    profile = owner_profile(USER, {"display_name": "Morgan Vale", "provenance": {"display_name": "inferred"}})
    h = await harness([source()])
    h.rt.owner_profile_notice = profile_notice(profile)
    assert await cmd_open(h.rt, h.job_id) == 0
    assert h.out().count("note: ") == 1
    assert "unconfirmed inferences: display_name" in h.out()


def test_unstated_and_legacy_declared_records_complete_provenance_per_field():
    unstated = UserProfile.unstated(USER)
    assert set(unstated.provenance) == set(PROFILE_FIELDS)
    assert set(unstated.provenance.values()) == {"placeholder"}
    assert not any(profile_fields(unstated).values())
    old = unstated.model_dump(exclude={"provenance", "level_style"})
    old.update(source="user", industry="tech")
    declared = UserProfile.model_validate(old)
    assert declared.provenance["industry"] == "owner"
    assert declared.provenance["display_name"] == "placeholder"
    assert not is_placeholder(declared)
    assert not declared.joined_at and not declared.workspace.active_since


@pytest.mark.parametrize("marker,expected", [
    ("profile", "owner"), ("owner", "owner"), ("inferred", "inferred"),
    ("deployment_default", "placeholder"), ("unstated", "placeholder"),
])
def test_legacy_locale_markers_map_to_field_provenance(marker, expected):
    profile = owner_profile(USER, {
        "locale": {"city": "Paris", "country": "FR", "timezone": "Europe/Paris", "language": "fr-FR"},
        "provenance": dict.fromkeys(("region", "timezone", "language"), marker),
    })
    for key in ("locale.city", "locale.country", "locale.timezone", "locale.language"):
        assert profile.provenance[key] == expected
        assert bool(profile_fields(profile)[key]) is (expected != "placeholder")
    assert profile.provenance["preferences.response_language"] == "placeholder"


@pytest.mark.parametrize("marker", ["placeholder", "deployment_default", "unstated", "owner", "profile"])
def test_only_inferred_values_receive_a_rendered_marker(marker):
    assert annotated_value({"provenance": {"bio": marker}}, "bio", "Maps rivers") == "Maps rivers"


async def test_clearing_a_name_and_confirming_blank_fields_keeps_dates_unstated(tmp_path):
    lib = library(engine_dir=str(_project(tmp_path)))
    assert (await run(lib, "profile", "set", "--field", "display_name=Morgan Vale"))[0] == 0
    code, text, err = await run(lib, "profile", "set", "--field", "display_name=", "--json")
    assert code == 0, err
    profile = json.loads(text)["profile"]
    assert profile["source"] == "user"
    assert profile["avatar"]["initial"] == "?"
    assert profile["provenance"]["display_name"] == "owner"
    assert is_placeholder(profile)
    assert not profile["joined_at"] and not profile["workspace"]["active_since"]
    code, text, err = await run(lib, "profile", "confirm", "--all", "--json")
    assert code == 0, err
    confirmed = json.loads(text)["profile"]
    assert set(confirmed["provenance"][key] for key in PROFILE_FIELDS) == {"owner"}
    assert profile_fields(confirmed) == profile_fields(profile)


async def test_profile_edits_preserve_application_declared_dates():
    lib = library(engine_dir="")
    stored = UserProfile.unstated(USER).model_dump(exclude={"level_style"})
    stored["joined_at"] = "2025-02-03"
    stored["workspace"]["active_since"] = "2025-03-04"
    await lib.store.upsert_user_profile(USER, stored)
    profile, _ = await save_owner_profile(lib.store, USER, "", {"industry": "tech"}, provenance="owner")
    assert profile.joined_at == stored["joined_at"]
    assert profile.workspace.active_since == stored["workspace"]["active_since"]
    assert profile.provenance["industry"] == "owner"
    assert profile.provenance["display_name"] == "placeholder"


@pytest.mark.parametrize("language", ["en", "zh"])
def test_shipped_profile_template_with_blank_slots_is_unstated(language):
    from pneuma_knowledge_service.engine.files import parse_mapping
    from pneuma_knowledge_service.engine.template_files import template_text

    text = template_text("profile", language)
    for slot in ("DISPLAY_NAME", "OCCUPATION", "BIO", "INDUSTRY", "ROLE", "LEVEL"):
        text = text.replace("{{" + slot + "}}", "")
    text = text.replace("{{INTERESTS}}", "[]")
    profile = owner_profile(USER, parse_mapping("persona/profile.yaml", text))
    assert profile.source == "unstated"
    assert not any(profile_fields(profile).values())
    assert all(profile.provenance[key] == "placeholder" for key in PROFILE_FIELDS)
