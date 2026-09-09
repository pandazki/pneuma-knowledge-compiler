"""`pkc profile` — the Owner's own profile, and the Steward's first question.

The acceptance run filed the Owner as a person page (`memory/people/chen-wan.md`) because the
profile still said `Someone` and nothing in the round could tell. What is pinned here is the
repair: the placeholder is detectable mechanically, the Owner's own information is recorded
through ONE write (the project's `persona/profile.yaml` and the persisted profile move
together), and the round says so before it is compiled rather than after.
"""

from __future__ import annotations

import io
import json

from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.persona_profile import (
    PLACEHOLDER_NAMES,
    is_placeholder,
    owner_profile,
    read_profile_data,
    set_profile_values,
)

from _cli_library import USER, library  # noqa: E402

#: The generated file, verbatim from the scaffold's own template with the slots filled the
#: way `init.py` fills them when nobody answered the owner question.
PLACEHOLDER_FILE = '''\
# Owner profile — "registration-level" information only.

display_name: ""          # how the owner is addressed
occupation: ""            # one-line occupation
bio: ""                   # a sentence or two of background
interests: []             # long-term interest keywords

industry: ""       # tech / finance / ...
role: ""           # engineering / ...
level: ""          # entry / ... / principal

locale:
  city: ""            # home city (may stay empty)
  country: ""         # ISO country/region code
  timezone: ""        # IANA timezone
  language: ""        # BCP-47

provenance:
  timezone: unstated
  language: unstated
  region: unstated

preferences:
  response_language: ""   # empty follows locale.language
'''


def _project(tmp_path):
    """A project engine directory carrying the placeholder profile the generator writes."""
    engine = tmp_path / "engine"
    (engine / "persona").mkdir(parents=True)
    (engine / "persona" / "profile.yaml").write_text(PLACEHOLDER_FILE, encoding="utf-8")
    return engine


async def run(lib, *argv):
    args = build_parser().parse_args(["--user", str(USER), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(lib.ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# ────────────────────────────────────────────────────────────── the placeholder, as a fact


def test_the_generators_default_is_the_placeholder_and_a_name_is_not():
    assert is_placeholder({"display_name": "Someone"})
    assert is_placeholder({"display_name": "someone", "bio": "   "})
    # No profile at all answers the same question the same way: the round cannot tell.
    assert is_placeholder(None)
    assert not is_placeholder({"display_name": "Chen Wan"})
    # The default name plus facts the owner supplied is no longer the shape the generator
    # wrote, and this is where that line is drawn.
    assert not is_placeholder({"display_name": "Someone", "bio": "runs a bakery"})


def test_the_scaffolds_default_name_is_one_of_the_names_that_name_nobody():
    """The generator cannot import the framework (it runs before any environment exists), so
    it carries the same set — and this is what keeps the two from drifting apart."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "scaffold_init_for_profile", root / "scaffold" / "init.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PLACEHOLDER_NAMES == PLACEHOLDER_NAMES


def test_a_built_profile_carries_the_owners_own_information():
    profile = owner_profile(
        USER, {"display_name": "Chen Wan", "bio": "runs a bakery", "interests": ["bread"]}
    )
    assert profile.display_name == "Chen Wan"
    assert not is_placeholder(profile)
    # The file's own rule: a timezone nobody confirmed is a deployment default, not the
    # owner's setting, so it stays out of the record.
    unconfirmed = owner_profile(USER, {"locale": {"timezone": "Asia/Shanghai"}})
    assert unconfirmed.locale.timezone == ""
    confirmed = owner_profile(
        USER,
        {"locale": {"timezone": "Asia/Shanghai"}, "provenance": {"timezone": "profile"}},
    )
    assert confirmed.locale.timezone == "Asia/Shanghai"


def test_writing_the_file_keeps_every_comment_it_had():
    written = set_profile_values(
        PLACEHOLDER_FILE,
        {
            "display_name": "Chen Wan",
            "interests": ["bread", "ledgers"],
            "level": "senior",
            "locale.timezone": "Asia/Shanghai",
            "provenance.timezone": "profile",
        },
    )
    assert '# how the owner is addressed' in written
    assert '# IANA timezone' in written
    assert 'display_name: "Chen Wan"' in written
    assert 'interests: ["bread", "ledgers"]' in written
    # Existing quoting is preserved; the legacy provenance words stay bare.
    assert 'level: "senior"' in written
    assert "  timezone: profile" in written
    assert '  timezone: "Asia/Shanghai"' in written


# ──────────────────────────────────────────────────────────────────── show and set


async def test_show_says_the_profile_is_the_placeholder_when_nobody_set_one(tmp_path):
    lib = library(engine_dir=str(_project(tmp_path)))
    code, out, _err = await run(lib, "profile", "show", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["placeholder"] is True
    assert payload["profile"] is None
    assert payload["file"].endswith("persona/profile.yaml")


async def test_set_writes_the_file_and_the_record_as_one_thing(tmp_path):
    engine = _project(tmp_path)
    lib = library(engine_dir=str(engine))

    code, out, err = await run(
        lib,
        "profile",
        "set",
        "--field",
        "display_name=Chen Wan",
        "--field",
        "bio=runs a bakery in Hangzhou",
        "--field",
        "interests=bread,ledgers",
        "--json",
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["placeholder"] is False
    assert payload["profile"]["display_name"] == "Chen Wan"

    # The file: what the owner said, in the file the project versions.
    on_disk = read_profile_data(engine)
    assert on_disk["display_name"] == "Chen Wan"
    assert on_disk["interests"] == ["bread", "ledgers"]

    # The record: what a compile round is rendered with. One write, both halves.
    code, out, _err = await run(lib, "profile", "show", "--json")
    assert code == 0
    shown = json.loads(out)
    assert shown["placeholder"] is False
    assert shown["profile"]["display_name"] == "Chen Wan"
    assert shown["profile"]["bio"] == "runs a bakery in Hangzhou"


async def test_set_accepts_the_same_shape_the_file_holds(tmp_path):
    engine = _project(tmp_path)
    lib = library(engine_dir=str(engine))
    payload = json.dumps(
        {
            "display_name": "Chen Wan",
            "occupation": "baker",
            "locale": {"language": "zh-CN", "timezone": "Asia/Shanghai"},
            "provenance": {"timezone": "profile"},
            # Not a settable field: taken from the payload as silence rather than as an error,
            # so `pkc profile show --json | … | pkc profile set --file -` round trips.
            "user_id": "u-somebody-else",
        }
    )
    path = tmp_path / "owner.json"
    path.write_text(payload, encoding="utf-8")
    code, out, err = await run(lib, "profile", "set", "--file", str(path), "--json")
    assert code == 0, err
    body = json.loads(out)
    assert body["profile"]["display_name"] == "Chen Wan"
    assert body["profile"]["locale"]["timezone"] == "Asia/Shanghai"
    assert body["profile"]["user_id"] == str(USER)


async def test_a_field_the_profile_does_not_have_is_refused_by_name(tmp_path):
    lib = library(engine_dir=str(_project(tmp_path)))
    code, _out, err = await run(lib, "profile", "set", "--field", "favourite_colour=blue")
    assert code == 2
    assert "favourite_colour" in err
    assert "display_name" in err  # the refusal names what IS settable


async def test_setting_nothing_is_nothing_to_act_on(tmp_path):
    lib = library(engine_dir=str(_project(tmp_path)))
    code, _out, err = await run(lib, "profile", "set")
    assert code == 1
    assert "--field" in err
