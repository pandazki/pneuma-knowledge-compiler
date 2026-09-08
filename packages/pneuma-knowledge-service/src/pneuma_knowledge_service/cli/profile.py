"""`pkc profile` — who the Owner is, said by the Owner.

The library belongs to one person, and the compile contract files that person's own facts on
their profile rather than on a page about a stranger. It can only do that if the profile
names them: a round opened against `display_name: "Someone"` has no way to know, and what
comes out of it is permanent. The acceptance run produced exactly that — the Owner filed as
`memory/people/chen-wan.md`.

Values carry inferred or owner provenance; confirm changes only that provenance. `show` reads the record the round is rendered with
and says, mechanically, whether it is still the placeholder. `set` writes what the Owner
supplied — through `persona_profile.save_owner_profile`, which is the one write: the project's
`engine/persona/profile.yaml` and the persisted profile move together or not at all.

Nothing here writes canonical. A page that turns out to BE the Owner is retired the way every
other page is (`pkc archive`), after the facts worth keeping were recorded here and the Owner
said so in their own words.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import PROFILE_FIELDS
from pneuma_knowledge_core.persona.provenance import profile_fields, provenance_for

from ..persona_profile import (
    PLACEHOLDER_NOTICE,
    PROFILE_FILE,
    ProfileError,
    flatten_updates,
    is_placeholder,
    parse_fields,
    profile_path,
    save_owner_profile,
)

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2


def _dump(profile: Any) -> dict[str, Any]:
    return dict(profile.model_dump(mode="json", exclude={"level_style"}))


async def cmd_profile_show(
    ctx: Any,
    user_id: UserId,
    *,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """The profile this deployment compiles under, and whether it names anybody."""
    out = out or sys.stdout
    err = err or sys.stderr
    profile = None
    try:
        profile = await ctx.user_info.get_profile(user_id)
    except Exception:  # noqa: BLE001 — an unreadable profile IS the placeholder answer
        profile = None
    placeholder = is_placeholder(profile)
    engine_dir = str(getattr(ctx.settings, "engine_dir", "") or "").strip()
    path = str(profile_path(engine_dir)) if engine_dir else ""

    if as_json:
        print(
            json.dumps(
                {
                    "profile": _dump(profile) if profile is not None else None,
                    "placeholder": placeholder,
                    "file": path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=out,
        )
        return EXIT_OK

    if profile is None:
        print("no owner profile is recorded for this library.", file=out)
    else:
        for key, value in profile_fields(profile).items():
            rendered = ", ".join(value) if isinstance(value, list) else value
            print(f"{key:<30} {rendered or '(unset)'} ({provenance_for(profile, key)})", file=out)
    if path:
        print(f"file          {path}", file=out)
    else:
        print(f"file          (this deployment has no {PROFILE_FILE})", file=out)
    if placeholder:
        print(f"\n{PLACEHOLDER_NOTICE}", file=out)
    return EXIT_OK


async def cmd_profile_set(
    ctx: Any,
    user_id: UserId,
    *,
    payload_text: str | None = None,
    fields: list[str] | None = None,
    provenance: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Record what the Owner said about themselves — the file and the record, one write."""
    out = out or sys.stdout
    err = err or sys.stderr
    updates: dict[str, Any] = {}
    if payload_text is not None:
        import yaml  # a project dependency; JSON is a subset, so one loader reads both

        try:
            data = yaml.safe_load(payload_text)
        except Exception as exc:  # noqa: BLE001 — an unparseable payload is a refusal
            print(f"refused: the profile payload is not YAML or JSON: {exc}", file=err)
            return EXIT_REFUSED
        if not isinstance(data, dict):
            print(
                "refused: a profile payload is a mapping in the shape of "
                f"{PROFILE_FILE} (display_name, occupation, bio, interests, locale, …)",
                file=err,
            )
            return EXIT_REFUSED
        updates.update(flatten_updates(data))
    try:
        updates.update(parse_fields(fields or []))
    except ProfileError as exc:
        print(f"refused: {exc}", file=err)
        return EXIT_REFUSED
    if not updates:
        print(
            "nothing to set: give `--file <f>` (or `-` for stdin) or one or more "
            "`--field name=value`",
            file=err,
        )
        return EXIT_NOTHING

    engine_dir = str(getattr(ctx.settings, "engine_dir", "") or "").strip()
    try:
        marker = provenance or (
            "inferred" if "PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH" in os.environ else "owner"
        )
        profile, path = await save_owner_profile(
            ctx.store, user_id, engine_dir, updates, provenance=marker
        )
    except (ProfileError, ValueError) as exc:
        # A value the profile model refuses (an industry outside the enum, say) is a refusal
        # at the argument face, in the words the model used.
        print(f"refused: {exc}", file=err)
        return EXIT_REFUSED

    if as_json:
        print(
            json.dumps(
                {
                    "profile": _dump(profile),
                    "placeholder": is_placeholder(profile),
                    "file": path,
                    "set": sorted(updates),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=out,
        )
        return EXIT_OK
    print(f"profile updated: {', '.join(sorted(updates))}", file=out)
    print(f"display_name  {profile.display_name}", file=out)
    if path:
        print(f"file          {path}", file=out)
    if is_placeholder(profile):
        print(f"\n{PLACEHOLDER_NOTICE}", file=out)
    return EXIT_OK


async def cmd_profile_confirm(
    ctx: Any,
    user_id: UserId,
    *,
    fields: list[str] | None = None,
    all_fields: bool = False,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Confirm only the named leaves; values remain unchanged."""
    out = out or sys.stdout
    err = err or sys.stderr
    selected = list(PROFILE_FIELDS) if all_fields else list(dict.fromkeys(fields or []))
    if not selected or any(key not in PROFILE_FIELDS for key in selected):
        print(f"refused: confirm --field <name> or --all; fields: {', '.join(PROFILE_FIELDS)}", file=err)
        return EXIT_REFUSED
    try:
        engine_dir = str(getattr(ctx.settings, "engine_dir", "") or "").strip()
        profile, path = await save_owner_profile(
            ctx.store, user_id, engine_dir,
            {f"provenance.{key}": "owner" for key in selected},
        )
    except (ProfileError, ValueError) as exc:
        print(f"refused: {exc}", file=err)
        return EXIT_REFUSED
    if as_json:
        print(json.dumps({"profile": _dump(profile), "confirmed": selected,
                          "placeholder": is_placeholder(profile), "file": path},
                         ensure_ascii=False, indent=2), file=out)
    else:
        print(f"profile confirmed: {', '.join(selected)}", file=out)
        if is_placeholder(profile):
            print(f"\n{PLACEHOLDER_NOTICE}", file=out)
    return EXIT_OK
