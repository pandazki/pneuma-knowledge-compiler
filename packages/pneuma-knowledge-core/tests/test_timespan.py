"""Subject-local calendar time: the day a range means, the zone it was normalized under,
and the labels a rendered time line carries. Pure, keyless, no store."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from pneuma_knowledge_core.domain.time_context import TimezoneChange
from pneuma_knowledge_core.recall.timespan import (
    day_label,
    day_range_to_utc,
    dual_clock,
    local_day,
    parse_iso_day,
    relative_label,
    span_label,
    weekday,
    zone_at,
    zone_for_day,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")


# ------------------------------------------------------------------ D1: the index key


def test_the_index_key_is_the_subjects_day_not_the_utc_one():
    """The whole reason this exists. A subject at +08:00 sends a message at 23:30 local on
    the 12th (15:30 UTC, still the 12th) and another at 00:30 local on the 13th — which is
    16:30 UTC on the *12th*. Keyed by UTC the second one lands on the wrong day."""
    late = datetime(2026, 4, 12, 15, 30, tzinfo=timezone.utc)
    past_midnight = datetime(2026, 4, 12, 16, 30, tzinfo=timezone.utc)

    assert local_day(late, SHANGHAI) == date(2026, 4, 12)
    assert local_day(past_midnight, SHANGHAI) == date(2026, 4, 13)
    # …and the UTC calendar would have put both on the 12th.
    assert local_day(late, UTC) == local_day(past_midnight, UTC) == date(2026, 4, 12)


def test_a_naive_instant_is_read_as_utc_not_as_local_time():
    naive = datetime(2026, 4, 12, 16, 30)
    assert local_day(naive, SHANGHAI) == date(2026, 4, 13)


# ------------------------------------------------ D3: the zone in effect for that period


def _moved() -> list[TimezoneChange]:
    return [
        TimezoneChange(
            changed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            from_zone="Europe/Berlin",
            to_zone="Asia/Shanghai",
        )
    ]


def test_zone_at_walks_the_forward_only_history():
    history = _moved()
    before = datetime(2026, 2, 1, tzinfo=timezone.utc)
    after = datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert zone_at(before, zone=SHANGHAI, history=history).key == "Europe/Berlin"
    assert zone_at(after, zone=SHANGHAI, history=history).key == "Asia/Shanghai"
    # No history at all → the current zone, always.
    assert zone_at(before, zone=SHANGHAI, history=()).key == "Asia/Shanghai"


def test_zone_for_day_is_a_fixed_deterministic_probe():
    history = _moved()
    assert zone_for_day(date(2026, 2, 15), zone=SHANGHAI, history=history).key == "Europe/Berlin"
    assert zone_for_day(date(2026, 3, 15), zone=SHANGHAI, history=history).key == "Asia/Shanghai"
    # The same day always resolves to the same zone — a rebuild reproduces a range exactly.
    repeated = {
        zone_for_day(date(2026, 2, 15), zone=SHANGHAI, history=history).key
        for _ in range(5)
    }
    assert repeated == {"Europe/Berlin"}


def test_a_range_spanning_a_move_converts_each_end_with_its_own_zone():
    history = _moved()
    start, end = day_range_to_utc(
        date(2026, 2, 20), date(2026, 3, 20), zone=SHANGHAI, history=history
    )
    # 2026-02-20 00:00 in Berlin (+01:00) → 2026-02-19 23:00Z
    assert start == datetime(2026, 2, 19, 23, 0, tzinfo=timezone.utc)
    # end is exclusive: 2026-03-21 00:00 in Shanghai (+08:00) → 2026-03-20 16:00Z
    assert end == datetime(2026, 3, 20, 16, 0, tzinfo=timezone.utc)
    # …and the same range under one zone would have been an hour and nine hours off.
    flat_start, flat_end = day_range_to_utc(
        date(2026, 2, 20), date(2026, 3, 20), zone=SHANGHAI, history=()
    )
    assert flat_start != start and flat_end == end


def test_an_inclusive_range_ends_at_midnight_of_the_following_day():
    start, end = day_range_to_utc(date(2026, 6, 1), date(2026, 6, 1), zone=SHANGHAI)
    assert start == datetime(2026, 5, 31, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 1, 16, tzinfo=timezone.utc)


def test_a_reversed_range_is_normalized_rather_than_returning_nothing():
    forward = day_range_to_utc(date(2026, 6, 1), date(2026, 6, 3), zone=UTC)
    assert day_range_to_utc(date(2026, 6, 3), date(2026, 6, 1), zone=UTC) == forward


def test_an_unusable_zone_name_in_history_degrades_to_the_current_zone():
    history = [
        TimezoneChange(
            changed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            from_zone="Mars/Olympus",
            to_zone="Asia/Shanghai",
        )
    ]
    assert zone_at(
        datetime(2026, 1, 1, tzinfo=timezone.utc), zone=SHANGHAI, history=history
    ).key == "Asia/Shanghai"


# ------------------------------------------------------------ D4: ISO on input, only ISO


@pytest.mark.parametrize("bad", ["2025/06/02", "last Monday", "上季度", "2025-6-2", "", None])
def test_only_iso_days_are_accepted_on_input(bad):
    with pytest.raises(ValueError):
        parse_iso_day(bad)


def test_an_iso_day_parses():
    assert parse_iso_day(" 2025-06-02 ") == date(2025, 6, 2)


# --------------------------------------------------- D5: several representations on output


def test_weekday_and_relative_labels_are_derived_not_parsed():
    assert weekday(date(2025, 6, 2)) == "Mon"
    as_of = date(2025, 8, 25)
    assert relative_label(as_of, as_of) == "today"
    assert relative_label(date(2025, 8, 24), as_of) == "yesterday"
    assert relative_label(date(2025, 8, 26), as_of) == "tomorrow"
    assert relative_label(date(2025, 8, 21), as_of) == "4 days before as_of"
    assert relative_label(date(2025, 8, 10), as_of) == "2 weeks before as_of"
    assert relative_label(date(2025, 6, 2), as_of) == "2 months before as_of"
    assert relative_label(date(2023, 6, 2), as_of) == "2 years before as_of"
    assert relative_label(date(2025, 12, 25), as_of) == "4 months after as_of"


def test_the_absolute_day_always_leads_the_relative_one():
    label = day_label(date(2025, 6, 2), as_of_day=date(2025, 8, 25))
    assert label == "2025-06-02 (Mon, 2 months before as_of)"
    assert day_label(date(2025, 6, 2)) == "2025-06-02 (Mon)"


def test_the_sources_own_clock_is_shown_beside_the_subjects_only_when_it_differs():
    start = datetime(2026, 4, 12, 12, 15, tzinfo=timezone.utc)
    end = datetime(2026, 4, 12, 13, 3, tzinfo=timezone.utc)
    both = dual_clock(start, end, subject_zone=SHANGHAI, source_zone=BERLIN)
    assert both == "20:15–21:03 Asia/Shanghai · source zone Europe/Berlin 14:15–15:03"
    same = dual_clock(start, end, subject_zone=SHANGHAI, source_zone=SHANGHAI)
    assert same == "20:15–21:03 Asia/Shanghai"
    assert dual_clock(start, None, subject_zone=SHANGHAI) == "20:15 Asia/Shanghai"


def test_one_rendered_time_line_carries_every_representation():
    line = span_label(
        date(2026, 4, 12),
        first=datetime(2026, 4, 12, 12, 15, tzinfo=timezone.utc),
        last=datetime(2026, 4, 12, 13, 3, tzinfo=timezone.utc),
        subject_zone=SHANGHAI,
        source_zone=BERLIN,
        as_of_day=date(2026, 4, 13),
    )
    assert line == (
        "2026-04-12 (Sun, yesterday) 20:15–21:03 Asia/Shanghai "
        "· source zone Europe/Berlin 14:15–15:03"
    )
    # A source with no clock still has a day.
    assert span_label(date(2026, 4, 12)) == "2026-04-12 (Sun)"
