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

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import (
    LOCALE_PROVENANCE_ALIASES,
    PLACEHOLDER_NAMES,
    PROFILE_FIELDS,
    UserProfile,
)
from pneuma_knowledge_core.persona.provenance import inferred_fields, profile_fields, provenance_for

from .engine.files import engine_path, parse_mapping, read_mapping

#: Where the owner profile lives inside a project's engine directory.
PROFILE_FILE = "persona/profile.yaml"

#: What `pkc profile set` may write, spelled as the file spells it. A dotted key is a key
#: inside that block. The tuple IS the check: a field nobody listed here is refused by name,
#: rather than written into a mapping the profile model then rejects with a stack trace.
SETTABLE: tuple[str, ...] = (
    *PROFILE_FIELDS,
    *(f"provenance.{key}" for key in PROFILE_FIELDS),
    "provenance.timezone", "provenance.language", "provenance.region",
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

    Legacy detected/unstated timezones stay out of the record so they retain their
    deployment-default meaning. An owner-confirmed or explicitly inferred timezone is
    retained with its marker; the contract renders an inference as a hypothesis.
    """
    locale = dict(data.get("locale") or {})
    provenance = dict(data.get("provenance") or {})
    display_name = str(data.get("display_name") or "").strip()
    if display_name.casefold() in PLACEHOLDER_NAMES:
        display_name = ""
    payload = UserProfile.unstated(UserId(str(user_id))).model_dump(exclude={"level_style"})
    updates = flatten_updates(data)
    # An unquoted empty YAML slot parses as None. It still means unstated, not an
    # invalid enum or a request for a generated default.
    for key in PROFILE_FIELDS:
        if key in updates:
            value = updates[key]
            updates[key] = [str(x) for x in (value or [])] if key in LIST_FIELDS else str(value or "")
    payload = apply_updates(payload, updates)
    payload["display_name"] = display_name
    payload["avatar"]["initial"] = display_name[:1] or "?"
    payload["provenance"] = provenance
    # Legacy locale detection is a deployment default, never a personal declaration.
    # Explicit leaf markers take precedence over the old shared locale markers.
    for key, alias in LOCALE_PROVENANCE_ALIASES.items():
        leaf = key.split(".")[1]
        marker = provenance.get(key, provenance.get(alias))
        declared = marker in {"profile", "owner", "inferred"}
        if leaf == "city" and marker is None:
            declared = True
        payload["locale"][leaf] = str(locale.get(leaf) or "").strip() if declared else ""
    # A placeholder value is template scaffolding, not an Owner fact. In particular,
    # neither a locale default nor a response-language fallback becomes a declaration.
    for key, value in profile_fields(payload).items():
        if provenance.get(key) in {"placeholder", "unstated", "deployment_default"}:
            payload = apply_updates(payload, {key: [] if isinstance(value, list) else ""})
    # These dates and operating facts are application/Owner declarations, never today's date.
    for key in ("joined_at", "workspace"):
        if key in data:
            value = data[key]
            payload[key] = {**payload[key], **value} if isinstance(value, Mapping) else value
    payload["source"] = "user"
    if (
        data.get("source") != "user" and is_placeholder(payload)
        and not any(provenance.get(key) in {"owner", "inferred"} for key in PROFILE_FIELDS)
    ):
        payload["source"] = "unstated"
    return UserProfile.model_validate(payload)


def is_placeholder(profile: Any) -> bool:
    """An absent profile or one with no stated fields, even when the name is blank."""
    if profile is None:
        return True
    source = profile.get("source") if isinstance(profile, Mapping) else getattr(profile, "source", None)
    if source == "unstated":
        return True
    for key, value in profile_fields(profile).items():
        if key == "display_name" and str(value or "").strip().casefold() in PLACEHOLDER_NAMES:
            continue
        if provenance_for(profile, key) in {"placeholder", "unstated", "deployment_default"}:
            continue
        stated = any(str(x).strip() for x in value) if isinstance(value, list) else bool(str(value or "").strip())
        if stated:
            return False
    return True


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
_NESTED = re.compile(r"^(\s+)([A-Za-z_][A-Za-z0-9_.]*):(.*)$")
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
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    if (
        not quoted
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_/-]*", text)
        and text.casefold() not in {"null", "true", "false", "yes", "no", "on", "off"}
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


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
                additions = [
                    f"  {leaf}: {_render_value(value[leaf], quoted=True)}"
                    for leaf in sorted(value)
                ]
                # Extend the existing block, never append a duplicate YAML key that would
                # hide all of its earlier leaves on the next read.
                header = next(
                    (i for i, line in enumerate(lines) if (m := _TOP.match(line)) and m[1] == key),
                    None,
                )
                if header is None:
                    lines.extend([f"{key}:", *additions])
                else:
                    end = next(
                        (i for i in range(header + 1, len(lines)) if _TOP.match(lines[i])),
                        len(lines),
                    )
                    lines[end:end] = additions
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
    *,
    provenance: str | None = None,
    current: UserProfile | None = None,
) -> tuple[UserProfile, str]:
    """Persist values and their provenance through the same file/record write.

    Partial updates use the persisted record when there is no engine file. A failed store
    write restores the file, and a failed file write never changes the record.
    """
    unknown = set(updates) - set(SETTABLE)
    if unknown:
        raise ProfileError(f"the profile has no settable field {sorted(unknown)[0]!r}")
    if provenance is not None and provenance not in {"inferred", "owner"}:
        raise ProfileError("provenance must be inferred or owner")
    text = read_profile_text(engine_dir)
    lookup = getattr(store, "get_user_profile", None)
    stored = current if current is not None else (await lookup(user_id) if lookup is not None else None)
    stored = stored.model_dump(mode="json") if isinstance(stored, UserProfile) else stored
    data = read_profile_data(engine_dir) if text and current is None else (stored or {})
    # Establish the old fields' markers before editing any values: giving the placeholder
    # a name must not silently confirm its untouched defaults (industry, role, level).
    data = {**data, "provenance": owner_profile(user_id, data).provenance}
    changes = dict(updates)
    for key, alias in LOCALE_PROVENANCE_ALIASES.items():
        alias_key = f"provenance.{alias}"
        field_key = f"provenance.{key}"
        if alias_key in updates and field_key not in updates:
            changes[field_key] = updates[alias_key]
    if provenance is not None:
        for key in PROFILE_FIELDS:
            if key in updates:
                changes[f"provenance.{key}"] = provenance
    data = apply_updates(data, changes)
    profile = owner_profile(user_id, data)
    if stored:
        # Registration updates never reset the user's presentation or timezone history.
        payload = apply_updates(stored, flatten_updates(profile.model_dump(mode="json")))
        payload.update({
            "user_id": str(user_id), "source": "user", "provenance": profile.provenance,
        })
        payload["avatar"] = {**payload["avatar"], "initial": profile.display_name[:1] or "?"}
        profile = UserProfile.model_validate(payload)
    # Persist the complete map in both representations, including defaults for old files.
    if not text or current is not None:
        changes.update(flatten_updates(profile.model_dump(mode="json")))
    changes.update({f"provenance.{key}": value for key, value in profile.provenance.items()})
    path = profile_path(engine_dir) if str(engine_dir or "").strip() else None
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        written = set_profile_values(text, changes)
        file_data = parse_mapping(PROFILE_FILE, written)
        # Verify the text edit before either representation is changed. In particular a
        # duplicate or malformed nested block must never persist a different provenance.
        file_profile = owner_profile(user_id, file_data)
        if (
            file_profile.provenance != profile.provenance
            or profile_fields(file_profile) != profile_fields(profile)
        ):
            raise ProfileError("the profile file edit did not preserve its values and provenance")
        path.write_text(written, encoding="utf-8")
    try:
        await store.upsert_user_profile(
            user_id, profile.model_dump(mode="json", exclude={"level_style"})
        )
    except BaseException:
        if path is not None:
            if text:
                path.write_text(text, encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        raise
    return profile, str(path) if path is not None else ""


def profile_notice(profile: object | None) -> str:
    """One notice per round, with the placeholder taking precedence over hypotheses."""
    if is_placeholder(profile):
        return PLACEHOLDER_NOTICE
    fields = inferred_fields(profile)
    if fields:
        return (
            f"the owner profile holds unconfirmed inferences: {', '.join(fields)}; "
            "review with `pkc profile show`, then `pkc profile confirm --field <name>`"
        )
    return ""
