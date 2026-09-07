"""The Owner's own profile: one file, one record, one write.

A library belongs to one person, and the compile contract can only file that person's own
facts differently from everyone else's if it knows which person they are. That knowledge has
exactly one home: `engine/persona/profile.yaml` in the project, mirrored into the persisted
`UserProfile` the compile round is rendered with (`render_system_contract(skill, owner=…)`).
The acceptance run showed what happens when the two are a placeholder: the Owner was compiled
into a person page like any stranger, because `display_name` still said `Someone` and nothing
in the round could tell.

So this module is the single write. `app.py init` wrote the file and upserted the record;
`pkc profile set` does the same two things through the same functions, and nothing else in
the framework writes either half. The file is edited as TEXT rather than re-serialized: it is
the commented documentation a person reads, and a YAML round trip would silently delete every
comment in it.

`is_placeholder` is the mechanical half — the scaffold's default name and no facts beside it.
It is what `pkc profile show` reports and what `pkc draft open` notices, and it is a fact
about a mapping rather than a judgement about a person.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import UserProfile

from .engine.files import engine_path, read_mapping

#: Where the owner profile lives inside a project's engine directory.
PROFILE_FILE = "persona/profile.yaml"

#: Display names that name nobody. `Someone` is the scaffold's own default (`init.py`,
#: `profile.{en,zh}.yaml`); `Owner` is what the loader falls back to when the field is blank.
#: Compared case-folded, so a hand-typed `someone` is the same placeholder.
PLACEHOLDER_NAMES = frozenset({"", "someone", "owner"})

#: What `pkc profile set` may write, spelled as the file spells it. A dotted key is a key
#: inside that block. The tuple IS the check: a field nobody listed here is refused by name,
#: rather than written into a mapping the profile model then rejects with a stack trace.
SETTABLE: tuple[str, ...] = (
    "display_name",
    "occupation",
    "bio",
    "interests",
    "industry",
    "role",
    "level",
    "locale.city",
    "locale.country",
    "locale.timezone",
    "locale.language",
    "preferences.response_language",
    "provenance.timezone",
    "provenance.language",
    "provenance.region",
)

#: Fields whose value is a list of words in the file. `--field interests=a,b` is the one
#: place a comma means something, and it means it here only.
LIST_FIELDS = frozenset({"interests"})


#: What every face says about a profile that names nobody: `pkc profile show`, `pkc profile
#: set` when what was set did not settle it, and the line `pkc draft open` prints above the
#: round. One finding, one sentence, one place.
PLACEHOLDER_NOTICE = (
    "the owner profile is the placeholder; the compile cannot tell who the owner is — "
    "`pkc profile set` first"
)


class ProfileError(ValueError):
    """The profile could not be read, addressed or built, and the message says which."""


# ───────────────────────────────────────────────────────────────────── reading the file


def profile_path(engine_dir: str | Path) -> Path:
    """The absolute path of this project's `persona/profile.yaml`."""
    return engine_path(engine_dir, PROFILE_FILE)


def read_profile_text(engine_dir: str | Path) -> str:
    """The file as text, or `""` when this deployment has no engine directory or no file.

    Text rather than a mapping, because the write path edits text: a project generated before
    this existed, or a framework checkout with no project at all, simply has nothing to edit.
    """
    if not str(engine_dir or "").strip():
        return ""
    path = profile_path(engine_dir)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def read_profile_data(engine_dir: str | Path) -> dict[str, Any]:
    """The file parsed, or `{}` when there is none. `read_mapping` is the engine's own
    loader, so a malformed profile fails the way every other engine file fails."""
    if not str(engine_dir or "").strip():
        return {}
    return dict(read_mapping(engine_dir, PROFILE_FILE))


# ─────────────────────────────────────────────────────────────── the mapping → a profile


def owner_profile(user_id: UserId | str, data: Mapping[str, Any]) -> UserProfile:
    """`profile.yaml` → the `UserProfile` a compile round is rendered with.

    Moved here from the scaffold's `app.py`, which now calls it: the file and the record are
    one thing, and two mappings of the same file into the same model would be two things that
    can disagree.

    A timezone whose provenance is not `profile` is left OUT of the record (blank) so the
    framework can honestly declare it as a deployment default rather than as the Owner's own
    setting — the rule the file's own header states.
    """
    locale = dict(data.get("locale") or {})
    provenance = dict(data.get("provenance") or {})
    preferences = dict(data.get("preferences") or {})
    display_name = str(data.get("display_name") or "Owner").strip() or "Owner"
    zone = str(locale.get("timezone") or "").strip()
    if str(provenance.get("timezone") or "") != "profile":
        zone = ""
    language = str(locale.get("language") or "").strip()
    payload = {
        "user_id": str(user_id),
        "display_name": display_name,
        "avatar": {"initial": display_name[0], "color": "#6C8EBF"},
        "locale": {
            "city": str(locale.get("city") or "").strip(),
            "country": str(locale.get("country") or "").strip(),
            "timezone": zone,
            "language": language,
            "timezone_history": [],
        },
        "industry": str(data.get("industry") or "other"),
        "role": str(data.get("role") or "other"),
        "level": str(data.get("level") or "mid"),
        "occupation": str(data.get("occupation") or ""),
        "bio": str(data.get("bio") or ""),
        "interests": [str(x) for x in (data.get("interests") or [])],
        "workspace": {
            "operating_mode": "independent",
            "primary_stack": "",
            "automation_level": "assisted",
            "active_since": datetime.now(timezone.utc).date().isoformat(),
        },
        "preferences": {
            "response_language": str(preferences.get("response_language") or "").strip()
            or language
            or "zh-CN",
            "units": "metric",
            "privacy_level": "standard",
        },
        "joined_at": datetime.now(timezone.utc).date().isoformat(),
        "source": "user",
    }
    return UserProfile.model_validate(payload)


def is_placeholder(profile: Any) -> bool:
    """Does this profile name the Owner, or is it still the shape the generator wrote?

    True for a profile that does not exist at all: a round with no owner record can tell who
    the Owner is exactly as well as one that says `Someone`. Accepts either the model or the
    file's own mapping, because the two faces of one thing are asked the same question in two
    places (`pkc profile show` holds the record; the scaffold holds the file).
    """
    if profile is None:
        return True
    if isinstance(profile, Mapping):
        name = str(profile.get("display_name") or "")
        facts = (
            str(profile.get("occupation") or ""),
            str(profile.get("bio") or ""),
            "".join(str(x) for x in (profile.get("interests") or [])),
        )
    else:
        name = str(getattr(profile, "display_name", "") or "")
        facts = (
            str(getattr(profile, "occupation", "") or ""),
            str(getattr(profile, "bio", "") or ""),
            "".join(str(x) for x in (getattr(profile, "interests", None) or [])),
        )
    if name.strip().casefold() not in PLACEHOLDER_NAMES:
        return False
    return not any(fact.strip() for fact in facts)


# ──────────────────────────────────────────────────────────────── addressing the fields


def parse_field(assignment: str) -> tuple[str, Any]:
    """`display_name=Chen Wan` → `("display_name", "Chen Wan")`, refusing anything else.

    The value is taken whole after the FIRST `=`, so a bio with an equals sign in it survives.
    """
    text = str(assignment or "")
    key, sep, value = text.partition("=")
    key = key.strip()
    if not sep or not key:
        raise ProfileError(
            f"a field is written `name=value`, and {assignment!r} is not: "
            f"settable fields are {', '.join(SETTABLE)}"
        )
    if key not in SETTABLE:
        raise ProfileError(
            f"the profile has no settable field {key!r}: {', '.join(SETTABLE)}"
        )
    if key in LIST_FIELDS:
        return key, [part.strip() for part in value.split(",") if part.strip()]
    return key, value.strip()


def parse_fields(assignments: Iterable[str]) -> dict[str, Any]:
    """Every `--field name=value` of one call, in the order they were typed."""
    return dict(parse_field(item) for item in assignments)


def flatten_updates(data: Mapping[str, Any]) -> dict[str, Any]:
    """A profile-shaped mapping (a `--file` payload) → dotted keys this module writes.

    Only the settable fields are taken: a payload carrying the file's whole shape — which is
    exactly what `pkc profile show --json` and a hand-edited copy both look like — is accepted
    without the caller having to strip the parts nobody may set.
    """
    flat: dict[str, Any] = {}
    for key in SETTABLE:
        block, _, leaf = key.partition(".")
        if leaf:
            nested = data.get(block)
            if isinstance(nested, Mapping) and leaf in nested:
                flat[key] = nested[leaf]
        elif key in data:
            flat[key] = data[key]
    return flat


def apply_updates(data: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    """The file's mapping with these dotted keys replaced — for building the record."""
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in data.items()}
    for key, value in updates.items():
        block, _, leaf = key.partition(".")
        if leaf:
            nested = merged.get(block)
            merged[block] = {**(nested if isinstance(nested, dict) else {}), leaf: value}
        else:
            merged[key] = value
    return merged


# ───────────────────────────────────────────────────────────────────── writing the file

_TOP = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$")
_NESTED = re.compile(r"^(\s+)([A-Za-z_][A-Za-z0-9_]*):(.*)$")
#: A value line's value and its trailing comment. Quoted strings and `[…]` lists are taken
#: whole, so a `#` inside either is part of the value rather than the start of a comment.
_VALUE = re.compile(r'^\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\]|[^#\n]*?)\s*(#.*)?$')


def _split_value(rest: str) -> tuple[str, str]:
    match = _VALUE.match(rest)
    if not match:
        return rest.strip(), ""
    return match.group(1) or "", match.group(2) or ""


def _render_value(value: Any, *, quoted: bool) -> str:
    """The new value, in the spelling the line already used.

    Preserving the file's own quoting is what keeps a rewritten line looking like the line it
    replaced: the enums and the provenance words are bare in the template, the prose fields
    are quoted, and neither should change shape because a value did.
    """
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(f'"{str(item)}"' for item in value) + "]"
    text = str(value)
    if not quoted:
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_profile_values(text: str, updates: Mapping[str, Any]) -> str:
    """`profile.yaml` text with these dotted keys rewritten, every comment intact.

    Line-by-line replacement rather than a YAML rewrite, for the reason the scaffold already
    replaces lines this way: the file is documentation a person reads, and the comments are
    most of it. A key the file does not carry is appended at the end, so a profile written by
    an older generator still accepts a field this one knows.
    """
    remaining = dict(updates)
    lines = text.splitlines()
    block: str | None = None
    for i, line in enumerate(lines):
        top = _TOP.match(line)
        if top:
            key, rest = top.group(1), top.group(2)
            value, comment = _split_value(rest)
            if not value.strip():
                # `locale:` and the other block headers: the key opens a block, it has no
                # value of its own, and the entries below it belong to that block.
                block = key
                continue
            block = None
            if key in remaining:
                new = _render_value(remaining.pop(key), quoted=value.startswith('"'))
                spacer = " " if comment else ""
                lines[i] = f"{key}: {new}{spacer}{comment}"
            continue
        nested = _NESTED.match(line)
        if not nested or block is None:
            continue
        indent, key, rest = nested.group(1), nested.group(2), nested.group(3)
        dotted = f"{block}.{key}"
        if dotted not in remaining:
            continue
        value, comment = _split_value(rest)
        new = _render_value(remaining.pop(dotted), quoted=value.startswith('"'))
        spacer = " " if comment else ""
        lines[i] = f"{indent}{key}: {new}{spacer}{comment}"

    if remaining:
        appended = apply_updates({}, remaining)
        for key in sorted(appended):
            value = appended[key]
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for leaf in sorted(value):
                    lines.append(f"  {leaf}: {_render_value(value[leaf], quoted=True)}")
            else:
                lines.append(f"{key}: {_render_value(value, quoted=True)}")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────── the one write


async def upsert_owner_profile(store: Any, user_id: UserId, data: Mapping[str, Any]) -> UserProfile:
    """The record half: the file's mapping, validated, persisted under this tenant (I1)."""
    profile = owner_profile(user_id, data)
    # mode="json": the profile holds datetimes (locale.timezone_history) and `level_style` is
    # a computed field the model derives rather than stores.
    await store.upsert_user_profile(
        user_id, profile.model_dump(mode="json", exclude={"level_style"})
    )
    return profile


async def save_owner_profile(
    store: Any,
    user_id: UserId,
    engine_dir: str | Path,
    updates: Mapping[str, Any],
) -> tuple[UserProfile, str]:
    """Write the Owner's own information: the file, then the record. One call, both halves.

    Returns `(profile, path)` — the path is `""` when this deployment has no profile file to
    edit, which is the honest report for a framework checkout or a project generated before
    the file existed: the record is still written, and the round still knows who the Owner is.
    """
    text = read_profile_text(engine_dir)
    data = apply_updates(read_profile_data(engine_dir), updates)
    profile = await upsert_owner_profile(store, user_id, data)
    if not text:
        return profile, ""
    path = profile_path(engine_dir)
    path.write_text(set_profile_values(text, updates), encoding="utf-8")
    return profile, str(path)
