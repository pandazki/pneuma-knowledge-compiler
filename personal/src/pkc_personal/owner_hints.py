"""What this machine already says about its Owner, before anybody has been asked.

The personal edition runs on the Owner's own computer, and that computer already holds three
facts about them: the name on the account, the timezone the clock keeps, and the language the
interface speaks. A setup that leaves the profile blank throws those away and then answers the
Owner in English on a machine whose every other application knows better.

So they are read mechanically and written as inferences — `--provenance inferred`, which
`status.profile_settled` refuses to call settled until the Owner has confirmed each one. That
is the whole discipline: the product may guess out loud, and the guess stays a guess in the
record until its subject says otherwise.

Nothing is derived beyond what the inputs literally state. A UI language region (`zh-Hans-US`)
is a keyboard, not a residence, so no city and no country are inferred from it; the timezone is
the one honest locality signal this machine has. A language nobody stated is not inferred at
all — an absent hint is a question for the Steward to ask, and that is cheaper than a wrong
answer nobody thought to check.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

#: The hints this module can produce, in the order every face reports them.
HINT_FIELDS: tuple[str, ...] = (
    "display_name", "locale.timezone", "locale.language", "preferences.response_language",
)

#: The two languages this edition speaks. Anything else is answered in English, because a
#: library whose skill text exists in en and zh cannot honestly promise a third.
_LANGUAGE_TAG = re.compile(r"[A-Za-z]+")
_QUOTED = re.compile(r'"([^"]*)"')


def _language_of(tag: str) -> str:
    """`zh_CN.UTF-8`, `zh-Hans-US` → `zh`; anything else that names a language → `en`."""
    match = _LANGUAGE_TAG.match(tag.strip())
    if not match:
        return ""
    return "zh" if match.group(0).lower().startswith("zh") else "en"


def _display_name(environ: dict[str, str], full_name: str | None) -> str:
    """The account's real name, or nothing when the account only carries its login name."""
    name = (full_name or "").strip()
    if not name:
        return ""
    logins = {environ.get("USER", "").strip().casefold(), environ.get("LOGNAME", "").strip().casefold()}
    return "" if name.casefold() in logins else name


def owner_hints(
    environ: dict[str, str], *, full_name: str | None = None, timezone: str | None = None,
    languages: list[str] | None = None,
) -> dict[str, str]:
    """The machine's inputs → profile fields, as a pure function of what it was given.

    Every key is a `PROFILE_FIELDS` name, so the result goes straight into `pkc profile set`.
    A field the inputs do not state is absent rather than empty: writing an empty value would
    be a claim that the machine looked and found nothing there.
    """
    hints: dict[str, str] = {}
    name = _display_name(environ, full_name)
    if name:
        hints["display_name"] = name
    # `TZ` is the fallback and only when it names a zone: `TZ=CST-8` is an offset, and an
    # offset is not a place — the profile's timezone field is an IANA zone.
    zone = (timezone or "").strip() or environ.get("TZ", "").strip()
    if "/" in zone:
        hints["locale.timezone"] = zone
    # The interface's own ordered preference first (the Owner set it in the system's face),
    # then the shell's locale, which is often just the terminal's encoding.
    candidates = [*(languages or []), environ.get("LC_ALL", ""), environ.get("LANG", "")]
    language = next((found for tag in candidates if (found := _language_of(tag))), "")
    if language:
        hints["locale.language"] = language
        hints["preferences.response_language"] = language
    return hints


def account_full_name() -> str:
    """The first gecos field of this account — `Ez Chan` on a Mac, empty on most Linux boxes."""
    try:
        import pwd

        entry = pwd.getpwuid(os.getuid())
    except (ImportError, KeyError, OSError):
        return ""
    return (entry.pw_gecos or "").split(",")[0].strip()


def system_timezone() -> str:
    """The IANA zone `/etc/localtime` points at, or nothing when the link says nothing."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return ""
    _, separator, name = target.partition("zoneinfo/")
    return name.strip("/") if separator else ""


def interface_languages() -> list[str]:
    """macOS's ordered UI language list; empty on every other platform and on any failure."""
    if sys.platform != "darwin":
        return []
    try:
        result = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                                capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    if result.returncode != 0:
        return []
    return [tag for tag in _QUOTED.findall(result.stdout) if tag.strip()]


def read_owner_hints(environ: dict[str, str] | None = None) -> dict[str, str]:
    """`owner_hints` with the machine's own three answers gathered for it."""
    return owner_hints(dict(os.environ if environ is None else environ),
                       full_name=account_full_name(), timezone=system_timezone(),
                       languages=interface_languages())
