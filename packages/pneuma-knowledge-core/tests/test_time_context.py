"""Timezone as a compile input: TimeContext, the provider chain, and the two boundaries.

Storage stays UTC. What these cover is the two places an instant becomes a CALENDAR DAY —
ingest sectioning and the compile time frame — because that is where a UTC day and the
subject's day disagree, and where the disagreement turns into a wrongly dated claim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from pneuma_knowledge_core.compile.runner import _render_time_anchor
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    ConversationTurn,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.domain.time_context import (
    UTC,
    TimeContext,
    TimezoneChange,
    load_zone,
    register_timezone_provider,
    reset_timezone_providers,
    resolve_zone,
    resolve_zone_with_source,
    time_context_for,
)
from pneuma_knowledge_core.domain.user import Locale
from pneuma_knowledge_core.ingest.adapters import (
    ContextStreamAdapter,
    PlainConversationAdapter,
    PlainConversationInput,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
LISBON = ZoneInfo("Europe/Lisbon")
USER = UserId("u1")


@pytest.fixture(autouse=True)
def _clean_providers():
    reset_timezone_providers()
    yield
    reset_timezone_providers()


def _raw(**meta) -> RawSource:
    return RawSource(
        source_id=SourceId("s1"),
        user_id=USER,
        kind="conversation",
        origin="context_stream",
        title="evening thread",
        mime="application/vnd.pneuma.context-stream+json",
        checksum="c",
        created_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        meta=dict(meta),
    )


class _FixedProvider:
    """A business TimeZoneProvider: answers from the source's own capture metadata."""

    def __init__(self, zone: ZoneInfo | None, *, only_with_raw: bool = False) -> None:
        self._zone = zone
        self._only_with_raw = only_with_raw

    def zone_for(self, user_id, raw):
        if self._only_with_raw and raw is None:
            return None  # defer to the next link
        return self._zone


# ───────────────────────────────────────────────────────── TimeContext arithmetic


def test_late_utc_evening_is_the_next_local_day_at_plus_eight():
    """22:30 UTC is already 06:30 the NEXT morning in Shanghai. Filing that turn under the
    UTC date puts it in the day before the one the subject lived it in."""
    time = TimeContext(now_utc=datetime(2026, 7, 30, 22, 30, tzinfo=timezone.utc), zone=SHANGHAI)
    at = datetime(2026, 7, 30, 22, 30, tzinfo=timezone.utc)
    assert at.date().isoformat() == "2026-07-30"  # the UTC day
    assert time.local_date(at).isoformat() == "2026-07-31"  # the subject's day
    assert time.today.isoformat() == "2026-07-31"
    assert time.zone_name == "Asia/Shanghai"


def test_naive_datetime_is_interpreted_as_utc_not_as_local_time():
    """Every storage boundary here writes UTC, so a timestamp that lost its tzinfo on the
    way through a driver is still a UTC instant — guessing local would shift it silently."""
    time = TimeContext(now_utc=datetime(2026, 7, 30, tzinfo=timezone.utc), zone=SHANGHAI)
    naive = datetime(2026, 7, 30, 20, 0)  # no tzinfo
    assert time.resolve(naive) == datetime(2026, 7, 31, 4, 0, tzinfo=SHANGHAI)
    assert time.local_date(naive).isoformat() == "2026-07-31"


def test_an_offset_carrying_instant_is_honoured_as_the_instant_it_denotes():
    time = TimeContext(now_utc=datetime(2026, 7, 30, tzinfo=timezone.utc), zone=LISBON)
    at = datetime(2026, 7, 31, 2, 0, tzinfo=SHANGHAI)  # = 2026-07-30 18:00 UTC
    assert time.local_date(at).isoformat() == "2026-07-30"


# ───────────────────────────────────────────────────────── the resolution chain


def test_registered_provider_outranks_the_profile_locale():
    register_timezone_provider(_FixedProvider(SHANGHAI))
    locale = Locale(city="Lisbon", country="Portugal", timezone="Europe/Lisbon", language="pt-PT")
    assert resolve_zone(USER, _Profile(locale)) == SHANGHAI


def test_last_registered_provider_wins_and_none_defers_to_the_next_link():
    register_timezone_provider(_FixedProvider(LISBON))
    register_timezone_provider(_FixedProvider(SHANGHAI))
    assert resolve_zone(USER, None) == SHANGHAI
    # a provider that only answers for a specific source defers when asked in general
    reset_timezone_providers()
    register_timezone_provider(_FixedProvider(SHANGHAI, only_with_raw=True))
    locale = Locale(city="Lisbon", country="Portugal", timezone="Europe/Lisbon", language="pt-PT")
    assert resolve_zone(USER, _Profile(locale), raw=None) == LISBON
    assert resolve_zone(USER, _Profile(locale), raw=_raw()) == SHANGHAI


def test_profile_locale_timezone_is_used_when_no_provider_is_registered():
    locale = Locale(city="Shanghai", country="China", timezone="Asia/Shanghai", language="zh-CN")
    assert resolve_zone(USER, _Profile(locale)) == SHANGHAI


def test_no_profile_and_no_provider_falls_back_to_utc():
    assert resolve_zone(USER, None) == UTC


# ────────────────────────────────── the chain reports WHICH link answered, and the default


def test_each_link_of_the_chain_labels_its_own_answer():
    """The compile contract declares where the subject's zone came from, so the resolution has to
    say. Without the label a deployment default is indistinguishable from the subject's own
    setting, and the prompt would be asserting something nobody knows."""
    locale = Locale(city="Lisbon", country="Portugal", timezone="Europe/Lisbon", language="pt-PT")

    from_profile = resolve_zone_with_source(USER, _Profile(locale))
    assert (from_profile.zone, from_profile.source) == (LISBON, "profile")

    register_timezone_provider(_FixedProvider(SHANGHAI))
    from_provider = resolve_zone_with_source(USER, _Profile(locale))
    assert (from_provider.zone, from_provider.source) == (SHANGHAI, "provider")

    reset_timezone_providers()
    from_default = resolve_zone_with_source(USER, None, default_timezone="Asia/Shanghai")
    assert (from_default.zone, from_default.source) == (SHANGHAI, "deployment_default")


def test_the_last_link_is_the_deployment_default_not_a_hardcoded_utc():
    """`Settings.default_timezone` reaches here from the caller: what an installation assumes
    about a subject it knows nothing about is a deployment fact, and UTC for a subject living at
    +08:00 files a third of their evenings on the previous day."""
    assert resolve_zone(USER, None, default_timezone="Asia/Shanghai") == SHANGHAI
    assert resolve_zone(USER, None, default_timezone=SHANGHAI) == SHANGHAI
    # An unusable default is still not a crash — UTC is the floor a library can defend.
    assert resolve_zone(USER, None, default_timezone="Mars/Olympus") == UTC
    assert resolve_zone(USER, None, default_timezone="") == UTC


def test_a_profile_zone_outranks_the_deployment_default():
    locale = Locale(city="Lisbon", country="Portugal", timezone="Europe/Lisbon", language="pt-PT")
    resolution = resolve_zone_with_source(
        USER, _Profile(locale), default_timezone="Asia/Shanghai"
    )
    assert (resolution.zone, resolution.source) == (LISBON, "profile")


def test_time_context_for_carries_the_provenance_of_the_zone_it_resolved():
    locale = Locale(city="Lisbon", country="Portugal", timezone="Europe/Lisbon", language="pt-PT")
    assert time_context_for(USER, _Profile(locale)).zone_source == "profile"
    assert (
        time_context_for(USER, None, default_timezone="Asia/Shanghai").zone_source
        == "deployment_default"
    )
    # A hand-built context claims no provenance rather than borrowing one.
    assert TimeContext(now_utc=datetime(2026, 7, 30, tzinfo=timezone.utc)).zone_source == "unstated"


def test_an_unusable_iana_name_degrades_to_utc_instead_of_crashing():
    """The name comes from a field a human typed; a typo must not be able to fail a job."""
    assert load_zone("Mars/Olympus") is None
    locale = Locale(city="?", country="?", timezone="Not/AZone", language="en-US")
    assert resolve_zone(USER, _Profile(locale)) == UTC


def test_a_raising_provider_defers_rather_than_failing_the_job():
    class _Broken:
        def zone_for(self, user_id, raw):
            raise RuntimeError("provider is down")

    register_timezone_provider(_Broken())
    locale = Locale(city="Shanghai", country="China", timezone="Asia/Shanghai", language="zh-CN")
    assert resolve_zone(USER, _Profile(locale)) == SHANGHAI


def test_time_context_for_carries_the_profiles_timezone_history_ascending():
    locale = Locale(
        city="Shanghai",
        country="China",
        timezone="Asia/Shanghai",
        language="zh-CN",
        timezone_history=[
            TimezoneChange(
                changed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                from_zone="Europe/Lisbon",
                to_zone="Asia/Shanghai",
            ),
            TimezoneChange(
                changed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                from_zone="America/New_York",
                to_zone="Europe/Lisbon",
            ),
        ],
    )
    time = time_context_for(USER, _Profile(locale))
    assert time.zone == SHANGHAI
    assert [c.to_zone for c in time.history] == ["Europe/Lisbon", "Asia/Shanghai"]


# ────────────────────────────────────────────── boundary 1: ingest sectioning


def _turns() -> list[ConversationTurn]:
    # One Shanghai evening: 21:00 and 23:00 local on the 30th, then 00:30 local on the 31st.
    return [
        ConversationTurn(speaker="self/1", text="a", role="owner", at=datetime(2026, 7, 30, 13, 0, tzinfo=timezone.utc)),
        ConversationTurn(speaker="self/1", text="b", role="owner", at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)),
        ConversationTurn(speaker="self/1", text="c", role="owner", at=datetime(2026, 7, 30, 16, 30, tzinfo=timezone.utc)),
    ]


@pytest.mark.parametrize("adapter", [PlainConversationAdapter(), ContextStreamAdapter()])
def test_sections_are_cut_by_the_subjects_local_day(adapter):
    time = TimeContext(now_utc=datetime(2026, 7, 31, tzinfo=timezone.utc), zone=SHANGHAI)
    normalized = adapter.normalize(
        PlainConversationInput(raw=_raw(), turns=_turns()), time=time
    )
    assert [b.section_path for b in normalized.blocks] == [
        ["2026-07-30"],
        ["2026-07-30"],
        ["2026-07-31"],
    ]
    assert [(s.path, s.start_block, s.end_block) for s in normalized.structure.sections] == [
        (["2026-07-30"], 0, 1),
        (["2026-07-31"], 2, 2),
    ]


def test_without_a_time_context_the_same_turns_all_land_on_the_utc_day():
    """The regression this task fixes: every one of those turns is the 30th in UTC, so the
    subject's late-evening turn is filed a day early."""
    normalized = PlainConversationAdapter().normalize(
        PlainConversationInput(raw=_raw(), turns=_turns())
    )
    assert {tuple(b.section_path) for b in normalized.blocks} == {("2026-07-30",)}


def test_undated_turns_stay_in_their_own_section():
    time = TimeContext(now_utc=datetime(2026, 7, 31, tzinfo=timezone.utc), zone=SHANGHAI)
    turns = [
        ConversationTurn(speaker="x", text="a"),
        ConversationTurn(speaker="x", text="b", at=datetime(2026, 7, 30, 16, 30, tzinfo=timezone.utc)),
    ]
    normalized = PlainConversationAdapter().normalize(
        PlainConversationInput(raw=_raw(), turns=turns), time=time
    )
    assert [b.section_path for b in normalized.blocks] == [["undated"], ["2026-07-31"]]


# ────────────────────────────────────────────── occurred_on: framework-computed


def test_occurred_on_is_computed_by_the_framework_in_the_subjects_zone():
    time = TimeContext(now_utc=datetime(2026, 7, 31, tzinfo=timezone.utc), zone=SHANGHAI)
    raw = _raw()
    ContextStreamAdapter().normalize(
        PlainConversationInput(raw=raw, turns=_turns()), time=time
    )
    # earliest local day the material covers — not the UTC one, not raw.created_at
    assert raw.meta["occurred_on"] == "2026-07-30"


def test_an_explicitly_supplied_occurred_on_is_never_overwritten():
    """A business that knows the true occurrence day (a backfill, an authoritative capture
    field) outranks a day derived from turn timestamps."""
    time = TimeContext(now_utc=datetime(2026, 7, 31, tzinfo=timezone.utc), zone=SHANGHAI)
    raw = _raw(occurred_on="2026-01-09")
    ContextStreamAdapter().normalize(
        PlainConversationInput(raw=raw, turns=_turns()), time=time
    )
    assert raw.meta["occurred_on"] == "2026-01-09"


def test_a_source_with_no_timestamps_gets_no_occurred_on():
    time = TimeContext(now_utc=datetime(2026, 7, 31, tzinfo=timezone.utc), zone=SHANGHAI)
    raw = _raw()
    PlainConversationAdapter().normalize(
        PlainConversationInput(raw=raw, turns=[ConversationTurn(speaker="x", text="a")]),
        time=time,
    )
    assert "occurred_on" not in raw.meta


# ─────────────────────────────────────── boundary 2: the compile time frame


def _source(occurred_on: str) -> NormalizedSource:
    return NormalizedSource(
        raw=_raw(occurred_on=occurred_on), blocks=[], structure=StructureMap(sections=[])
    )


def test_the_time_frame_states_todays_local_date_and_the_zone():
    time = TimeContext(now_utc=datetime(2026, 7, 30, 22, 30, tzinfo=timezone.utc), zone=SHANGHAI)
    lines = _render_time_anchor([_source("2026-07-30")], time)
    assert "2026-07-31" in lines[0]  # the subject's day, not the UTC 30th
    assert "Asia/Shanghai" in lines[0]


def test_no_time_context_renders_no_now_line_at_all():
    lines = _render_time_anchor([_source("2026-07-30")], None)
    assert not any("runs on" in line for line in lines)


def test_a_recorded_timezone_change_is_stated_in_the_time_frame():
    time = TimeContext(
        now_utc=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        zone=SHANGHAI,
        history=(
            TimezoneChange(
                changed_at=datetime(2026, 3, 1, 2, 0, tzinfo=timezone.utc),
                from_zone="Europe/Lisbon",
                to_zone="Asia/Shanghai",
            ),
        ),
    )
    rendered = "\n".join(_render_time_anchor([_source("2026-07-30")], time))
    assert "Europe/Lisbon" in rendered and "Asia/Shanghai" in rendered
    assert "2026-03-01" in rendered


def test_an_empty_history_renders_no_change_line():
    time = TimeContext(now_utc=datetime(2026, 7, 30, tzinfo=timezone.utc), zone=SHANGHAI)
    rendered = "\n".join(_render_time_anchor([_source("2026-07-30")], time))
    assert "timezone changed" not in rendered


def test_the_write_contract_states_the_local_calendar_day_convention():
    """The time frame names the zone per round; the CONTRACT is where the rule that a
    canonical date means a day in that zone lives, so it is stated once and byte-stably."""
    from pneuma_knowledge_core.prompts import prompt
    from pneuma_knowledge_core.skill import load_builtin_skill, render_system_contract

    clause = "a date in canonical is a calendar day in the\nknowledge subject's own timezone"
    assert clause in prompt("compile.write_contract")
    assert clause in render_system_contract(load_builtin_skill("v3"))


class _Profile:
    """Minimal stand-in for UserProfile: resolution is duck-typed on `.locale`."""

    def __init__(self, locale: Locale) -> None:
        self.locale = locale
