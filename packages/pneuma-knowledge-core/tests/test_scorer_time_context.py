"""Computed source clocks assist a scorer without guessing event dates or query scope."""

import json
from datetime import datetime
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.evidence_context import EvidenceTime


def _facts(time, *, zone="Asia/Shanghai"):
    from pneuma_knowledge_core.recall.evidence_context import scorer_time_context

    return json.loads(scorer_time_context(
        SimpleNamespace(source_times=(time,)),
        as_of=datetime.fromisoformat("2026-09-21T01:00:00+00:00"), zone=zone,
    ))


def test_source_instants_are_compared_in_the_query_timezone():
    facts = _facts(EvidenceTime(SourceId("synthetic"), 0, 0,
                              first="2026-09-20T17:00:00+00:00",
                              last="2026-09-20T17:00:00+00:00", timed_blocks=1))
    row = facts["source_clocks"][0]
    assert row["first_day"] == "2026-09-21"
    assert row["first_relation"] == "today"
    assert row["last_relation"] == "today"
    assert row["coverage"] == "complete"
    assert facts["clock_scope"] == "source_occurrence_not_event_time"


def test_a_multiday_partial_clock_does_not_claim_full_span_coverage():
    facts = _facts(EvidenceTime(SourceId("synthetic"), 0, 4,
                              first="2026-09-19T16:00:00+00:00",
                              last="2026-09-20T16:00:00+00:00", timed_blocks=2))
    row = facts["source_clocks"][0]
    assert row["first_relation"] == "yesterday"
    assert row["last_relation"] == "today"
    assert row["coverage"] == "partial"


def test_future_and_day_only_dates_are_not_reported_as_block_instants():
    row = _facts(EvidenceTime(SourceId("synthetic"), 0, 2,
                             occurred_on="2026-09-22"))["source_clocks"][0]
    assert row["coverage"] == "source_day_only"
    assert row["source_day_relation"] == "tomorrow"
    assert "first_day" not in row


def test_missing_and_invalid_dates_stay_unknown():
    for time in (
        EvidenceTime(SourceId("synthetic"), 0, 0),
        EvidenceTime(SourceId("synthetic"), 0, 0, occurred_on="2026-02-30",
                     first="not a timestamp", last="not a timestamp", timed_blocks=1),
    ):
        row = _facts(time)["source_clocks"][0]
        assert row["coverage"] == "unknown"
        assert "source_day_relation" not in row
        assert "first_relation" not in row


def test_no_dates_or_unusable_zone_adds_no_computed_claim():
    from pneuma_knowledge_core.recall.evidence_context import scorer_time_context

    assert scorer_time_context(SimpleNamespace(), as_of=datetime(2026, 9, 21)) == ""
    assert scorer_time_context(SimpleNamespace(source_times=(
        EvidenceTime(SourceId("synthetic"), 0, 0, occurred_on="2026-09-21"),
    )), as_of=datetime(2026, 9, 21), zone="invalid-zone") == ""


def test_compact_relations_stay_beside_each_cited_clock_and_preserve_original_instants():
    from pneuma_knowledge_core.recall.evidence_context import render_scorer_context

    item = SimpleNamespace(source_times=(
        EvidenceTime(SourceId("older"), 0, 0, first="2026-09-19T17:00:00+00:00",
                     last="2026-09-19T17:00:00+00:00", timed_blocks=1),
        EvidenceTime(SourceId("newer"), 4, 6, first="2026-09-20T17:00:00+00:00",
                     last="2026-09-20T18:00:00+00:00", timed_blocks=2),
    ))
    lines = render_scorer_context(item, as_of=datetime.fromisoformat("2026-09-21T01:00:00+00:00"),
                                  zone="Asia/Shanghai").splitlines()
    assert "[cite: older ¶0-0]" in lines[0]
    assert "2026-09-19T17:00:00+00:00" in lines[0]
    assert "first_day=2026-09-20 (yesterday)" in lines[0]
    assert "coverage=complete" in lines[0]
    assert "[cite: newer ¶4-6]" in lines[1]
    assert "first_day=2026-09-21 (today)" in lines[1]
    assert "coverage=partial" in lines[1]
    assert "not event time" in lines[0]


def test_unknown_clocks_and_missing_query_clock_add_no_redundant_state():
    from pneuma_knowledge_core.recall.evidence_context import render_candidate_context, render_scorer_context

    item = SimpleNamespace(source_times=(EvidenceTime(SourceId("unknown"), 0, 0),))
    original = render_candidate_context(item)
    assert render_scorer_context(item, as_of=datetime(2026, 9, 21)) == original
    assert render_scorer_context(item) == original
    assert render_scorer_context(item, as_of=datetime(2026, 9, 21), zone="invalid-zone") == original
