"""The install-time profile: what the machine may infer, and what the Steward must still ask.

The Owner's complaint these tests hold: a setup that leaves the profile blank and then answers
in English on a machine whose account, clock and interface all say otherwise. So the machine's
three answers are read mechanically, written as inferences that stay unsettled until confirmed,
and the rest is printed as a checklist in the Owner's own language.
"""

import json
from pathlib import Path

import pytest
from pneuma_knowledge_core.domain.user import PROFILE_FIELDS

from pkc_personal import cli, infra, library as library_module, owner_hints as hints_module
from pkc_personal import setup, skill_install
from pkc_personal.home import atomic_write, yaml_text
from pkc_personal.library import Library
from pkc_personal.owner_hints import owner_hints, read_owner_hints, system_timezone

MAC = {"USER": "pandazki", "LOGNAME": "pandazki"}


# ─────────────────────────────────────────────────────────── what the machine already says

def test_the_account_full_name_is_a_hint_and_a_bare_login_name_is_not():
    assert owner_hints(MAC, full_name="Ez Chan")["display_name"] == "Ez Chan"
    # Most Linux accounts carry the login name in gecos; that is the absence of a full name.
    assert "display_name" not in owner_hints(MAC, full_name="pandazki")
    assert "display_name" not in owner_hints(MAC, full_name="  ")
    assert "display_name" not in owner_hints(MAC, full_name=None)


def test_the_timezone_comes_from_the_link_then_tz_and_otherwise_is_not_claimed():
    assert owner_hints(MAC, timezone="Asia/Shanghai")["locale.timezone"] == "Asia/Shanghai"
    assert owner_hints({**MAC, "TZ": "Europe/Berlin"})["locale.timezone"] == "Europe/Berlin"
    # The link wins over the variable, and an offset is not a place.
    assert owner_hints({**MAC, "TZ": "Europe/Berlin"}, timezone="Asia/Shanghai")["locale.timezone"] == "Asia/Shanghai"
    assert "locale.timezone" not in owner_hints({**MAC, "TZ": "CST-8"})
    assert "locale.timezone" not in owner_hints(MAC)
    # No city and no country: a timezone is the only locality this machine actually states.
    assert set(owner_hints(MAC, timezone="Asia/Shanghai")) == {"locale.timezone"}


def test_the_system_timezone_reads_the_link_and_survives_its_absence(monkeypatch):
    monkeypatch.setattr(hints_module.os, "readlink", lambda _p: "/var/db/timezone/zoneinfo/Asia/Shanghai")
    assert system_timezone() == "Asia/Shanghai"
    monkeypatch.setattr(hints_module.os, "readlink", lambda _p: "/some/other/file")
    assert system_timezone() == ""

    def missing(_path):
        raise OSError("no such link")

    monkeypatch.setattr(hints_module.os, "readlink", missing)
    assert system_timezone() == ""


def test_a_language_is_mapped_to_the_two_this_edition_speaks_or_left_unstated():
    hints = owner_hints({**MAC, "LANG": "zh_CN.UTF-8"})
    assert hints["locale.language"] == "zh" and hints["preferences.response_language"] == "zh"
    assert owner_hints({**MAC, "LANG": "en_US.UTF-8"})["locale.language"] == "en"
    # A third language is answered in the language this edition can actually write.
    assert owner_hints({**MAC, "LANG": "ja_JP.UTF-8"})["locale.language"] == "en"
    # The interface's ordered preference is the better signal than the shell's encoding.
    assert owner_hints({**MAC, "LANG": "en_US.UTF-8"},
                       languages=["zh-Hans-US", "en-US"])["locale.language"] == "zh"
    assert "locale.language" not in owner_hints(MAC)


def test_read_owner_hints_gathers_the_three_inputs_from_this_machine(monkeypatch):
    monkeypatch.setattr(hints_module, "account_full_name", lambda: "Ez Chan")
    monkeypatch.setattr(hints_module, "system_timezone", lambda: "Asia/Shanghai")
    monkeypatch.setattr(hints_module, "interface_languages", lambda: ["en-US", "zh-Hans-US"])
    assert read_owner_hints({"USER": "pandazki", "LANG": "en_US.UTF-8"}) == {
        "display_name": "Ez Chan", "locale.timezone": "Asia/Shanghai",
        "locale.language": "en", "preferences.response_language": "en",
    }


# ───────────────────────────────────────────────────────────────── setup writes the hints

@pytest.fixture
def cold_start(monkeypatch):
    """A setup whose every machine-touching step is stubbed except the profile write."""
    monkeypatch.setattr(library_module, "render_library", lambda *_: None)
    monkeypatch.setattr(library_module, "persist_owner_profile", lambda *_, **__: False)
    monkeypatch.setattr(setup, "persist_owner_profile", lambda *_, **__: False)
    monkeypatch.setattr(setup, "render_library", lambda *_: None)
    monkeypatch.setattr(setup, "console_dist", lambda _home: Path("/console/dist"))
    monkeypatch.setattr(infra, "up", lambda *_: None)
    monkeypatch.setattr(skill_install, "install", lambda *_, **__: None)
    monkeypatch.setattr(setup.engine, "start", lambda *_: None)
    machine = {"display_name": "Ez Chan", "locale.timezone": "Asia/Shanghai",
               "locale.language": "en", "preferences.response_language": "en"}
    monkeypatch.setattr(setup, "read_owner_hints", lambda: dict(machine))


def _answers(tmp_path, **fields) -> Path:
    path = tmp_path / "answers.yaml"
    atomic_write(path, yaml_text({"library": "notes", **fields}))
    return path


def test_setup_writes_the_machine_hints_as_inferences_and_reports_them(
    home, tmp_path, capsys, cold_start, pkc
):
    setup.setup(home, _answers(tmp_path))
    assert pkc.fields("inferred") == [
        "display_name=Ez Chan", "locale.timezone=Asia/Shanghai",
        "locale.language=en", "preferences.response_language=en",
    ]
    line = capsys.readouterr().out.splitlines()[0]
    assert ("profile (inferred: display_name, locale.timezone, locale.language, "
            "preferences.response_language)") in line


def test_the_owners_own_language_answer_wins_over_the_interface_language(
    home, tmp_path, capsys, cold_start, pkc
):
    """The machine says en; the Owner asked for zh in the answers file. The Owner chose."""
    setup.setup(home, _answers(tmp_path, language="zh"))
    assert pkc.fields("inferred") == [
        "display_name=Ez Chan", "locale.timezone=Asia/Shanghai",
        "locale.language=zh", "preferences.response_language=zh",
    ]


def test_answers_may_state_owner_facts_and_they_are_written_as_the_owners_own(
    home, tmp_path, capsys, cold_start, pkc
):
    setup.setup(home, _answers(tmp_path, owner={
        "display_name": "Chen Wan", "occupation": "translator", "role": "design",
        "interests": ["typography", "poetry"],
    }))
    assert pkc.fields("owner") == [
        "display_name=Chen Wan", "interests=typography,poetry", "occupation=translator",
        "role=design",
    ]
    # The machine's guess is still written, and then overwritten by the Owner's own words.
    assert [command[1:3] for command in pkc.calls if command[1] == "profile"][:2] == [
        ["profile", "set"], ["profile", "set"]]
    assert pkc.calls[0][-1] == "inferred" and pkc.calls[1][-1] == "owner"
    assert "owner: display_name, interests, occupation, role" in capsys.readouterr().out


def test_an_unknown_owner_field_is_refused_by_name_with_the_field_list(home, tmp_path, cold_start, pkc):
    answers = _answers(tmp_path, owner={"favourite_colour": "green"})
    with pytest.raises(ValueError, match="favourite_colour"):
        setup.setup(home, answers)
    with pytest.raises(ValueError, match="preferences.response_language"):
        setup.setup(home, answers)
    assert pkc.calls == []


def test_a_profile_write_that_fails_is_reported_and_never_fails_the_setup(
    home, tmp_path, capsys, cold_start, pkc
):
    pkc.answer("profile set", returncode=1, stderr="refused: the store is unreachable\n")
    library = setup.setup(home, _answers(tmp_path))
    assert library.state.name == "notes"
    assert "profile skipped: refused: the store is unreachable" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────────── the Steward's list

def _profile(language: str, **fields) -> str:
    profile = {
        "display_name": "Ez Chan", "occupation": "", "bio": "", "interests": [],
        "industry": "", "role": "", "level": "",
        "locale": {"city": "", "country": "", "timezone": "Asia/Shanghai", "language": language},
        "preferences": {"response_language": language},
        "provenance": {"display_name": "inferred", "locale.timezone": "inferred",
                       "locale.language": "inferred", "preferences.response_language": "inferred"},
        **fields,
    }
    return json.dumps({"profile": profile, "placeholder": False, "file": "profile.yaml"})


def test_onboarding_asks_the_missing_questions_in_the_owners_language(home, make_library, pkc):
    library = make_library()
    pkc.answer("profile show", stdout=_profile("zh"))
    text = setup.onboarding(home, library)
    assert "Speak to the Owner in zh." in text
    # The inferred fields, with their values, and the two commands that settle one.
    assert f"  {'display_name':<30}Ez Chan" in text
    assert f"  {'locale.timezone':<30}Asia/Shanghai" in text
    assert "pkc profile confirm --field <name>" in text
    assert "--provenance owner" in text
    for question in ("你现在做的是什么工作？", "用一句话说：你在做什么，这座知识库要装下什么。"):
        assert question in text
    assert "What do you do?" not in text
    # The order the questions are asked in.
    assert [line.split()[0] for line in text.splitlines() if line.startswith("  occupation")
            or line.startswith("  role") or line.startswith("  bio")
            or line.startswith("  interests")] == ["occupation", "role", "bio", "interests"]

    pkc.answer("profile show", stdout=_profile("en"))
    english = setup.onboarding(home, library)
    assert "Speak to the Owner in en." in english
    assert "What do you do? The work itself, in your own words." in english
    assert "你现在做的是什么工作？" not in english


def test_onboarding_drops_what_is_already_settled(home, make_library, pkc):
    library = make_library()
    pkc.answer("profile show", stdout=_profile(
        "en", occupation="translator", bio="Turns books over.", interests=["poetry"],
        role="design",
        provenance={key: "owner" for key in ("display_name", "locale.timezone",
                                             "locale.language", "preferences.response_language")}))
    text = setup.onboarding(home, library)
    assert "Inferred from this machine" not in text
    assert "What do you do?" not in text
    # Retrieval is the one question left on a keyless machine.
    assert "Retrieval is still undecided" in text
    assert "OPENROUTER_API_KEY" in text
    home.set_credential("OPENROUTER_API_KEY", "synthetic")
    assert "Nothing is waiting" in setup.onboarding(home, library)


def test_pkchome_onboarding_prints_the_same_block(home, make_library, pkc, capsys):
    library = make_library()
    pkc.answer("profile show", stdout=_profile("zh"))
    assert cli.main(["onboarding", "--library", library.state.name]) == 0
    assert capsys.readouterr().out.strip() == setup.onboarding(home, library).strip()


def test_onboarding_still_asks_when_the_library_cannot_be_reached(home, make_library, pkc):
    library = make_library()
    pkc.answer("profile show", returncode=1, stderr="connection refused\n")
    text = setup.onboarding(home, library)
    assert "could not be asked" in text
    # The library's own recorded language decides how to ask, since no profile states one.
    assert "What do you do?" in text
    assert Library.load(home, "notes").state.choices.language == "en"


# ──────────────────────────────────────────── onboarding seeds what the setup could not

#: The machine, as these tests let it speak.
MACHINE = {"display_name": "Ez Chan", "locale.timezone": "Asia/Shanghai",
           "locale.language": "en", "preferences.response_language": "en"}


def _blank() -> str:
    """The profile a cold start leaves when its seeding step did not happen."""
    profile = {
        "display_name": "", "occupation": "", "bio": "", "interests": [],
        "industry": "", "role": "", "level": "",
        "locale": {"city": "", "country": "", "timezone": "", "language": ""},
        "preferences": {"response_language": ""},
        "provenance": {key: "placeholder" for key in PROFILE_FIELDS},
    }
    return json.dumps({"profile": profile, "placeholder": True, "file": "profile.yaml"})


@pytest.fixture
def machine(monkeypatch):
    monkeypatch.setattr(setup, "read_owner_hints", lambda: dict(MACHINE))


def test_onboarding_seeds_the_hints_a_skipped_setup_never_wrote(home, make_library, pkc, machine):
    """The observed cold start: `setup` reported `profile skipped:` and the checklist that
    followed had no confirmation step in it, because there was nothing to confirm."""
    library = make_library()
    pkc.answer("profile show", stdout=_blank())
    pkc.then("profile show", stdout=_profile("en"))
    text = setup.onboarding(home, library)

    assert text.splitlines()[0] == (
        "seeded: display_name, locale.timezone, locale.language, preferences.response_language")
    assert pkc.fields("inferred") == [
        "display_name=Ez Chan", "locale.timezone=Asia/Shanghai",
        "locale.language=en", "preferences.response_language=en",
    ]
    # And the list is the record as it now stands, not as it stood a moment ago.
    assert "Inferred from this machine" in text
    assert f"  {'display_name':<30}Ez Chan" in text
    assert "Owner onboarding — notes. Speak to the Owner in en." in text


def test_the_librarys_own_language_is_what_the_seeding_writes(home, make_library, pkc, machine):
    """The machine's interface says en; this library was created zh. The library's choice
    is the Owner's, so it wins — and stays `inferred` until they say so themselves."""
    library = make_library(language="zh")
    pkc.answer("profile show", stdout=_blank())
    pkc.then("profile show", stdout=_profile("zh"))
    setup.onboarding(home, library)
    assert pkc.fields("inferred") == [
        "display_name=Ez Chan", "locale.timezone=Asia/Shanghai",
        "locale.language=zh", "preferences.response_language=zh",
    ]


def test_a_second_onboarding_seeds_nothing(home, make_library, pkc, machine):
    library = make_library()
    pkc.answer("profile show", stdout=_profile("en"))
    text = setup.onboarding(home, library)
    assert not text.startswith("seeded:")
    assert [command for command in pkc.calls if command[1:3] == ["profile", "set"]] == []


def test_seeding_never_overwrites_what_the_owner_said_about_themselves(
    home, make_library, pkc, machine
):
    """A display_name the Owner stated is theirs. The machine's guess about it is not
    written, and the fields nobody has stated still are."""
    library = make_library()
    owned = json.loads(_blank())
    owned["profile"]["display_name"] = "Chen Wan"
    owned["profile"]["provenance"]["display_name"] = "owner"
    owned["placeholder"] = False
    pkc.answer("profile show", stdout=json.dumps(owned))
    pkc.then("profile show", stdout=json.dumps(owned))
    text = setup.onboarding(home, library)

    assert text.splitlines()[0] == (
        "seeded: locale.timezone, locale.language, preferences.response_language")
    assert pkc.fields("inferred") == [
        "locale.timezone=Asia/Shanghai", "locale.language=en",
        "preferences.response_language=en",
    ]


def test_a_library_that_cannot_be_asked_is_not_written_to(home, make_library, pkc, machine):
    library = make_library()
    pkc.answer("profile show", returncode=1, stderr="connection refused\n")
    text = setup.onboarding(home, library)
    assert "could not be asked" in text
    assert [command for command in pkc.calls if command[1:3] == ["profile", "set"]] == []


def test_a_seeding_write_that_fails_names_the_reason_and_still_asks(home, make_library, pkc, machine):
    library = make_library()
    pkc.answer("profile show", stdout=_blank())
    pkc.answer("profile set", returncode=1, stderr="refused: the store is unreachable\n")
    text = setup.onboarding(home, library)
    assert text.splitlines()[0] == "profile skipped: refused: the store is unreachable"
    assert "What do you do?" in text
