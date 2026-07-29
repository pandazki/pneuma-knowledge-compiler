"""TimeContext: the knowledge subject's timezone, as a compile INPUT.

WHY THIS EXISTS
---------------
Everything is stored in UTC — instants are compared in UTC and nothing here changes that.
But a knowledge base is one person's, and the units that person's knowledge is filed and
recalled by are *calendar days in their own life*: "what happened on the 18th", "last
Monday's decision". A UTC calendar day is not that day. For a subject at +08:00 every
message sent between 00:00 and 08:00 local time carries the PREVIOUS UTC date, so a
conversation the owner remembers as one evening lands in two different sections, and a
claim compiled from it is dated a day early. The error is not cosmetic: the date is one of
the slots the compiler is least allowed to get wrong.

So the timezone is a compile INPUT, resolved once per job and threaded to the two
boundaries where an instant becomes a calendar day:

  · ingest sectioning — which local day a turn belongs to (`ingest/adapters.py`),
  · the compile time frame — what "today" is, and what period the material covers.

Anything that merely COMPARES instants (recency, ordering, `as_of`) keeps using UTC and
does not touch this module.

RESOLUTION (three links, first hit wins)
----------------------------------------
  1. a registered `TimeZoneProvider` — the business seam, shaped like
     `ingest.source_types.register_source_type`. A provider may read the RawSource, so a
     deployment whose capture carries its own `timezone` field can answer per source.
  2. `UserProfile.locale.timezone` (an IANA name) — the framework's own answer.
  3. UTC.

An unusable IANA name is a warning and a fall-through, never a crash: a bad profile field
must not be able to fail a compile job.

FORWARD-ONLY HISTORY
--------------------
A subject who moves changes their timezone, and every date already written into canonical
was normalized under the OLD one. Rewriting them is out of the question (canonical is the
non-rebuildable layer, and I2 forbids retro-editing settled knowledge), so the change is
carried as data instead: `UserProfile.locale.timezone_history` records each transition and
the compile time frame states it, so the model reads older dates under the zone they were
actually normalized in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from .ids import UserId

if TYPE_CHECKING:  # RawSource would be a cycle at runtime; providers only READ it.
    from .source import RawSource

_log = logging.getLogger(__name__)

__all__ = [
    "UTC",
    "TimeContext",
    "TimeZoneProvider",
    "TimezoneChange",
    "load_zone",
    "register_timezone_provider",
    "registered_timezone_providers",
    "reset_timezone_providers",
    "resolve_zone",
    "time_context_for",
]

UTC = ZoneInfo("UTC")


class TimezoneChange(BaseModel):
    """One recorded transition of the subject's timezone. `changed_at` is UTC.

    Forward-only: appended when the profile's timezone actually changes, and never used to
    rewrite dates already compiled — only to TELL the compiler which zone earlier dates
    were normalized under.
    """

    changed_at: datetime
    from_zone: str
    to_zone: str


def load_zone(name: object) -> ZoneInfo | None:
    """An IANA name → ZoneInfo, or None (with a warning) when it is unusable.

    Deliberately not an exception: the name comes from a profile field a human typed, and a
    typo there must degrade to UTC rather than fail the job that reads it.
    """
    text = str(name or "").strip()
    if not text:
        return None
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        _log.warning("unusable IANA timezone %r; falling back to UTC", text)
        return None


@dataclass(frozen=True)
class TimeContext:
    """The subject's clock for one job: an instant, their zone, and its recorded changes.

    Frozen and explicit — `now_utc` is passed in rather than read from the clock, so every
    render that depends on "today" stays deterministic and testable.
    """

    now_utc: datetime
    zone: ZoneInfo = UTC
    # Ascending by `changed_at`. Empty for a subject who never moved (the common case),
    # and an empty history renders nothing at all.
    history: tuple[TimezoneChange, ...] = ()

    def resolve(self, dt: datetime) -> datetime:
        """An instant → the same instant expressed in the subject's zone.

        A NAIVE datetime is interpreted as UTC, because UTC is what every storage boundary
        in this system writes; a stored timestamp that lost its tzinfo on the way through a
        driver is still a UTC instant, and guessing local time for it would silently shift
        it by the offset.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.zone)

    def local_date(self, dt: datetime) -> date:
        """The subject's calendar day containing this instant — the sectioning unit."""
        return self.resolve(dt).date()

    @property
    def today(self) -> date:
        """The subject's current calendar day (not the UTC one)."""
        return self.local_date(self.now_utc)

    @property
    def zone_name(self) -> str:
        """The IANA name, for prose that has to say which zone a date is in."""
        return self.zone.key


@runtime_checkable
class TimeZoneProvider(Protocol):
    """The business seam for "which timezone is this subject's material in".

    Shaped like `FirstPartySourceType`: a deployment registers one at startup and the
    framework asks it first. `raw` is supplied when the question is being asked about a
    specific source (ingest), and None when it is about the subject in general (compile),
    so a provider that keys on per-source capture metadata must tolerate None.

    Return None to defer to the next link in the chain — that is how a provider that only
    knows about SOME sources stays composable instead of having to invent an answer.
    """

    def zone_for(
        self, user_id: UserId, raw: "RawSource | None"
    ) -> ZoneInfo | None: ...


# Registered providers, consulted in REVERSE registration order so a later registration
# takes precedence — the same "registering wins" semantics as register_source_type.
_PROVIDERS: list[TimeZoneProvider] = []


def register_timezone_provider(provider: TimeZoneProvider) -> None:
    """Register a resolver for the subject's timezone. Call at startup (wiring)."""
    _PROVIDERS.append(provider)


def registered_timezone_providers() -> tuple[TimeZoneProvider, ...]:
    """The registered providers, in consultation order (last registered first)."""
    return tuple(reversed(_PROVIDERS))


def reset_timezone_providers() -> None:
    """Drop every registered provider. Tests only — registration is a startup contract."""
    _PROVIDERS.clear()


def _profile_zone_name(profile: object | None) -> str | None:
    """`profile.locale.timezone`, duck-typed so core never imports the profile model."""
    locale = getattr(profile, "locale", None)
    if locale is None and isinstance(profile, dict):
        locale = profile.get("locale")
    if isinstance(locale, dict):
        return locale.get("timezone")
    name = getattr(locale, "timezone", None)
    return str(name) if name else None


def _profile_history(profile: object | None) -> tuple[TimezoneChange, ...]:
    """`profile.locale.timezone_history`, ascending. Malformed entries are dropped, not
    raised: history is context for a prompt line, never a hard dependency."""
    locale = getattr(profile, "locale", None)
    if locale is None and isinstance(profile, dict):
        locale = profile.get("locale")
    raw_items = (
        locale.get("timezone_history")
        if isinstance(locale, dict)
        else getattr(locale, "timezone_history", None)
    )
    changes: list[TimezoneChange] = []
    for item in raw_items or []:
        if isinstance(item, TimezoneChange):
            changes.append(item)
            continue
        try:
            changes.append(TimezoneChange.model_validate(item))
        except Exception:  # noqa: BLE001 — a bad row is dropped, never fatal
            _log.warning("unusable timezone_history entry %r; ignored", item)
    changes.sort(key=lambda c: c.changed_at)
    return tuple(changes)


def resolve_zone(
    user_id: UserId,
    profile: object | None = None,
    raw: "RawSource | None" = None,
) -> ZoneInfo:
    """The subject's timezone: registered provider → profile locale → UTC.

    `profile` is duck-typed (anything exposing `.locale.timezone`, or the equivalent dict)
    so this stays in the domain layer without importing the profile model.
    """
    for provider in registered_timezone_providers():
        try:
            zone = provider.zone_for(user_id, raw)
        except Exception:  # noqa: BLE001 — a broken provider defers, never fails a job
            _log.warning("timezone provider %r raised; deferring", provider, exc_info=True)
            continue
        if zone is not None:
            return zone
    return load_zone(_profile_zone_name(profile)) or UTC


def time_context_for(
    user_id: UserId,
    profile: object | None = None,
    *,
    now_utc: datetime | None = None,
    raw: "RawSource | None" = None,
) -> TimeContext:
    """Build the job's TimeContext — the single place a caller needs to touch.

    `now_utc` defaults to the wall clock because a job's "now" genuinely is now; every
    render downstream takes the resulting TimeContext, so the clock is read once, here.
    """
    return TimeContext(
        now_utc=now_utc or datetime.now(timezone.utc),
        zone=resolve_zone(user_id, profile, raw),
        history=_profile_history(profile),
    )
