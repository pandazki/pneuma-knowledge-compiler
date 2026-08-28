"""Subject-local calendar time: the pure rules the `time` index component runs on.

WHY A MODULE OF ITS OWN
-----------------------
`domain/time_context.py` answers "which zone is the subject's, and where did that answer
come from". This module answers the two questions that follow, and it answers them without
touching a store, a model or a clock:

  · a range of the subject's CALENDAR DAYS → the UTC interval that holds them, converted
    with the zone that was in effect for each end of the range (D3), so a subject who moved
    does not silently get one zone applied to their whole history;
  · one instant or one day → the MECHANICAL LABELS a rendered time line carries (D5): the
    absolute subject-local day with its weekday, the offset from `as_of` in words, and the
    source's own local clock beside the subject's whenever the two zones differ.

Both are derivations, never parsing: nothing here reads natural language. "上季度" and
"last Monday" are the routing model's to resolve into ISO days before an argument ever
reaches this module (D4) — an index that guessed at colloquial time would be inventing the
one slot the compiler is least allowed to get wrong.

STORAGE STAYS UTC (D1)
----------------------
Instants are UTC everywhere. What is keyed by calendar semantics is the SUBJECT's local
day — the same day `ingest` already wrote into `section_path[0]` / `occurred_on`. A
source's own zone (a meeting's `timezone`) is metadata: it is rendered beside the subject's
day, never used as the index key.

Everything here is sync, pure and deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..domain.time_context import UTC, TimezoneChange, load_zone

__all__ = [
    "ISO_DAY_RE",
    "WEEKDAY_NAMES",
    "clock",
    "day_label",
    "day_range_to_utc",
    "dual_clock",
    "local_day",
    "parse_iso_day",
    "relative_label",
    "span_label",
    "weekday",
    "zone_at",
    "zone_for_day",
]

#: The ONE accepted input spelling for a day (D4). `2025/06/02` is not a near miss to be
#: repaired — it is rejected, and the rejection is what the audit trail records.
ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_iso_day(value: object) -> date:
    """`"2025-06-02"` → a date. Anything else raises `ValueError`.

    Strict on purpose: a pydantic args schema calls this, so a malformed argument from the
    routing model becomes an `invalid_args` audit row rather than a silently shifted range.
    """
    text = str(value or "").strip()
    if not ISO_DAY_RE.match(text):
        raise ValueError(f"expected an ISO day YYYY-MM-DD, got {text!r}")
    return date.fromisoformat(text)


def local_day(instant: datetime, zone: ZoneInfo) -> date:
    """The calendar day an instant falls on in `zone`. Naive input is read as UTC — every
    storage boundary here writes UTC, so a timestamp that lost its tzinfo in a driver is
    still a UTC instant and guessing local time for it would shift it by the offset."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(zone).date()


# ------------------------------------------------------------------ zone over time (D3)


def zone_at(
    instant: datetime,
    *,
    zone: ZoneInfo,
    history: Sequence[TimezoneChange] = (),
) -> ZoneInfo:
    """The subject's zone AT a UTC instant, walking the forward-only `timezone_history`.

    `zone` is the CURRENT zone (the profile's). History records transitions, so:
      · after the last recorded change → the current zone;
      · between two changes → that change's `to_zone`;
      · before the first change → its `from_zone` (the zone the subject left).
    An unusable IANA name in a history row degrades to the current zone rather than raising:
    a typo in a profile field must not be able to fail a query.
    """
    changes = sorted(history, key=lambda c: c.changed_at)
    if not changes:
        return zone
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    chosen: str | None = None
    for change in changes:
        changed_at = change.changed_at
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        if changed_at <= instant:
            chosen = change.to_zone
        else:
            if chosen is None:
                chosen = change.from_zone
            break
    if chosen is None:  # every change is at or before the instant → the latest to_zone
        chosen = changes[-1].to_zone
    return load_zone(chosen) or zone


def zone_for_day(
    day: date,
    *,
    zone: ZoneInfo,
    history: Sequence[TimezoneChange] = (),
) -> ZoneInfo:
    """The zone a subject-local DAY was normalized under.

    Chicken-and-egg: which zone applies depends on the instant, and which instant a local
    day starts at depends on the zone. The rule is fixed and stated rather than clever —
    probe at **12:00 UTC of that day**. Midday is the probe with the smallest possible
    error (every IANA offset is inside ±14h, and a transition is only ever misattributed
    for a day immediately adjacent to it), and being a fixed rule it is deterministic:
    the same day always resolves to the same zone, so a rebuild reproduces a range exactly.
    """
    probe = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    return zone_at(probe, zone=zone, history=history)


def day_range_to_utc(
    since: date,
    until: date,
    *,
    zone: ZoneInfo,
    history: Sequence[TimezoneChange] = (),
) -> tuple[datetime, datetime]:
    """An inclusive range of subject-local days → the half-open UTC interval `[start, end)`.

    Each END of the range is converted with the zone in effect FOR ITS OWN period (D3), so
    a range that spans a move is not squashed into one offset. `until` is inclusive, so the
    interval ends at midnight of the day AFTER it.
    """
    if until < since:
        since, until = until, since
    start_zone = zone_for_day(since, zone=zone, history=history)
    end_zone = zone_for_day(until, zone=zone, history=history)
    start_local = datetime(since.year, since.month, since.day, tzinfo=start_zone)
    end_day = until + timedelta(days=1)
    end_local = datetime(end_day.year, end_day.month, end_day.day, tzinfo=end_zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


# --------------------------------------------------------------- derived labels (D5)


def weekday(day: date) -> str:
    """`Mon`…`Sun` — the label a person actually recalls a day by."""
    return WEEKDAY_NAMES[day.weekday()]


def relative_label(day: date, as_of_day: date) -> str:
    """A day's distance from `as_of`, in the words a question would use.

    Derived mechanically so the answering model can match a colloquial phrasing in the
    question ("上个月", "last week") against evidence without the index ever having parsed
    one. Coarse on purpose: past a month the unit is months, past a year it is years —
    a "137 days before" label is precise and unusable.
    """
    delta = (as_of_day - day).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta == -1:
        return "tomorrow"
    ahead = delta < 0
    n = abs(delta)
    if n < 7:
        unit = f"{n} days"
    elif n < 28:
        weeks = n // 7
        unit = f"{weeks} week{'s' if weeks > 1 else ''}"
    else:
        months = (as_of_day.year - day.year) * 12 + (as_of_day.month - day.month)
        if ahead:
            months = -months
            if day.day < as_of_day.day:
                months -= 1
        elif as_of_day.day < day.day:
            months -= 1
        months = max(months, 1)
        if months < 12:
            unit = f"{months} month{'s' if months > 1 else ''}"
        else:
            years = months // 12
            unit = f"{years} year{'s' if years > 1 else ''}"
    return f"{unit} {'after' if ahead else 'before'} as_of"


def day_label(day: date, *, as_of_day: date | None = None) -> str:
    """`2025-06-02 (Mon)` — plus the offset from as_of when one is known.

    The absolute day always leads: the relative part is an aid to matching the question's
    words, never the address of the evidence.
    """
    tail = weekday(day)
    if as_of_day is not None:
        tail += ", " + relative_label(day, as_of_day)
    return f"{day.isoformat()} ({tail})"


def clock(instant: datetime, zone: ZoneInfo) -> str:
    """`14:15` — an instant's wall clock in one zone."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(zone).strftime("%H:%M")


def dual_clock(
    first: datetime,
    last: datetime | None = None,
    *,
    subject_zone: ZoneInfo,
    source_zone: ZoneInfo | None = None,
) -> str:
    """The subject's local clock, and the source's own beside it when the zones differ.

    One representation on input, several on output (D5): a meeting captured in Berlin and
    recalled by an owner in Shanghai is one instant with two true wall clocks, and showing
    only one of them makes half the material unmatchable to the question that asks for it.
    """
    def span(zone: ZoneInfo) -> str:
        start = clock(first, zone)
        if last is None or clock(last, zone) == start:
            return start
        return f"{start}–{clock(last, zone)}"

    local = f"{span(subject_zone)} {subject_zone.key}"
    if source_zone is None or source_zone.key == subject_zone.key:
        return local
    return f"{local} · source zone {source_zone.key} {span(source_zone)}"


def span_label(
    day: date,
    *,
    first: datetime | None = None,
    last: datetime | None = None,
    subject_zone: ZoneInfo = UTC,
    source_zone: ZoneInfo | None = None,
    as_of_day: date | None = None,
) -> str:
    """One rendered time line: absolute subject-local day + weekday + offset from as_of,
    and the clock span in the subject's zone (plus the source's own when it differs).

    e.g. `2025-06-02 (Mon, 2 months before as_of) 21:00–21:40 Asia/Shanghai ·
    source zone Europe/Berlin 15:00–15:40`
    """
    head = day_label(day, as_of_day=as_of_day)
    if first is None:
        return head
    return f"{head} {dual_clock(first, last, subject_zone=subject_zone, source_zone=source_zone)}"
