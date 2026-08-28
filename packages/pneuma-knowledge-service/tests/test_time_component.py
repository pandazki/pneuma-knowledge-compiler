"""The `time` component: the owner's calendar as an index.

Keyless and store-free — an in-memory stand-in plays the PG projection with the same
semantics (wholesale per-source replacement, an inclusive day-range scan, a
source→earliest-day lookup), so what is under test is the component's derivation and
rendering rather than psycopg.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.components import register_component, reset_components
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.domain.time_context import time_context_for
from pneuma_knowledge_core.recall.paths import route_paths

from pneuma_knowledge_service.components.time import TimeComponent, group_spans, time_rows
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import register_components

USER = UserId("u-time")
NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    reset_components()
    yield
    reset_components()


# ------------------------------------------------------------------ in-memory stand-ins


class _Store:
    """The PG projection's semantics, in a dict. Mirrors `PostgresStore`'s contract:
    user_id first, per-source wholesale replacement, an inclusive local-day range scan."""

    def __init__(self) -> None:
        self.sources: dict[tuple[str, str], NormalizedSource] = {}
        self.rows: dict[tuple[str, str], list[dict]] = {}
        self.writes = 0

    async def add(self, user_id, normalized: NormalizedSource) -> SourceId:
        self.sources[(str(user_id), str(normalized.raw.source_id))] = normalized
        return normalized.raw.source_id

    async def list(self, user_id) -> list[RawSource]:
        return [
            ns.raw
            for (uid, _), ns in sorted(self.sources.items())
            if uid == str(user_id)
        ]

    async def get(self, user_id, source_id) -> NormalizedSource:
        return self.sources[(str(user_id), str(source_id))]

    async def put_time_blocks(self, user_id, source_id, rows) -> int:
        self.writes += 1
        self.rows[(str(user_id), str(source_id))] = [dict(r) for r in rows]
        return len(rows)

    async def delete_time_blocks(self, user_id) -> int:
        keys = [k for k in self.rows if k[0] == str(user_id)]
        for key in keys:
            del self.rows[key]
        return len(keys)

    async def time_blocks_in_range(self, user_id, since, until, *, limit=5000):
        out = []
        for (uid, sid), rows in self.rows.items():
            if uid != str(user_id):
                continue
            raw = self.sources[(uid, sid)].raw
            for row in rows:
                if since <= row["local_day"] <= until:
                    out.append({**row, "source_id": sid, "title": raw.title})
        out.sort(
            key=lambda r: (
                r["local_day"],
                r["instant_utc"] or datetime.min.replace(tzinfo=timezone.utc),
                r["source_id"],
                r["block_index"],
            )
        )
        return out[:limit]

    async def time_days_for_sources(self, user_id, source_ids) -> dict[str, str]:
        out: dict[str, str] = {}
        for sid in source_ids:
            rows = self.rows.get((str(user_id), str(sid)))
            if rows:
                out[str(sid)] = min(r["local_day"] for r in rows).isoformat()
        return out


class _UserInfo:
    def __init__(self, timezone_name: str = "Asia/Shanghai", history=()) -> None:
        self.profile = SimpleNamespace(
            locale=SimpleNamespace(timezone=timezone_name, timezone_history=list(history))
        )

    async def get_profile(self, user_id):
        return self.profile


def _component(store: _Store, *, zone: str = "Asia/Shanghai", canonical=None) -> TimeComponent:
    return TimeComponent(
        content=store,
        canonical=canonical,
        user_info=_UserInfo(zone),
        default_timezone="UTC",
    )


# ------------------------------------------------------------------ fixtures: L0 material


def _im(messages: list[tuple[str, str]], *, archive: str = "a1", conversation: str = "c1"):
    """One IM conversation from the official contract — real meta, real block alignment."""
    payload = {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": archive,
        "owner_user_ids": ["u1"],
        "users": [
            {"user_id": "u1", "display_name": "主人"},
            {"user_id": "u2", "display_name": "贾宁"},
        ],
        "conversations": [
            {
                "conversation_id": conversation,
                "conversation_type": "dm",
                "title": "排期",
                "member_ids": ["u1", "u2"],
                "messages": [
                    {
                        "message_id": f"m{i}",
                        "sender_id": "u2",
                        "sent_at": sent_at,
                        "text": text,
                    }
                    for i, (sent_at, text) in enumerate(messages)
                ],
            }
        ],
    }
    time = time_context_for(USER, _UserInfo().profile, now_utc=NOW)
    return normalize_source_contract(
        parse_source_contract(payload), USER, imported_at=NOW, time=time
    )[0]


def _meeting():
    """A meeting captured in Berlin, for an owner in Shanghai."""
    payload = {
        "schema": "pneuma.source.meeting/v1",
        "provider": "mock",
        "meeting_id": "m-berlin",
        "title": "供应商评审",
        "started_at": "2026-04-12T14:15:00+02:00",
        "timezone": "Europe/Berlin",
        "owner_participant_ids": ["p1"],
        "participants": [
            {"participant_id": "p1", "display_name": "主人"},
            {"participant_id": "p2", "display_name": "Anke"},
        ],
        "segments": [
            {
                "segment_id": "s1",
                "speaker_id": "p2",
                "started_at": "2026-04-12T14:15:00+02:00",
                "text": "Wir liefern im Mai.",
            },
            {
                "segment_id": "s2",
                "speaker_id": "p1",
                "started_at": "2026-04-12T15:03:00+02:00",
                "text": "了解。",
            },
        ],
    }
    time = time_context_for(USER, _UserInfo().profile, now_utc=NOW)
    return normalize_source_contract(
        parse_source_contract(payload), USER, imported_at=NOW, time=time
    )[0]


def _plain(source_id: str, occurred_on: str, blocks: int = 2) -> NormalizedSource:
    """A source with no per-block instants: it has a day, it has no clock."""
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=USER,
        kind="conversation",
        source_class="workstream",
        title="旧笔记",
        mime="text/plain",
        checksum=source_id,
        created_at=NOW,
        meta={"occurred_on": occurred_on},
    )
    body = [
        NormalizedBlock(index=i, text=f"第{i}段", section_path=["笔记"]) for i in range(blocks)
    ]
    return NormalizedSource(
        raw=raw,
        blocks=body,
        structure=StructureMap(
            sections=[SectionSpan(path=["笔记"], start_block=0, end_block=blocks - 1)]
        ),
    )


# ------------------------------------------------------------------ D1: the index key


async def test_the_index_key_is_the_owners_day_even_when_the_utc_date_disagrees():
    """The +08:00 midnight case, end to end. Two messages 23:30 and 00:30 the owner's time
    are two of his days — and the SAME UTC date. Keyed by UTC the second one would be filed
    on the 12th and never found by "what happened on the 13th"."""
    store = _Store()
    source = _im(
        [("2026-04-12T23:30:00+08:00", "今晚定了"), ("2026-04-13T00:30:00+08:00", "补一句")]
    )
    await store.add(USER, source)
    component = _component(store)

    await component.on_source_indexed(str(USER), source)
    rows = store.rows[(str(USER), str(source.raw.source_id))]

    assert [r["local_day"] for r in rows] == [date(2026, 4, 12), date(2026, 4, 13)]
    # …while both instants fall on the same UTC calendar date.
    assert {r["instant_utc"].astimezone(timezone.utc).date() for r in rows} == {date(2026, 4, 12)}
    assert [r["block_index"] for r in rows] == [0, 1]


async def test_every_row_records_the_zone_it_was_normalized_under_and_where_it_came_from():
    """D2. A row that did not say which zone produced it could not be told apart from one
    produced under another, and a later change would silently mix two calendars."""
    store = _Store()
    source = _im([("2026-04-12T23:30:00+08:00", "x")])
    await store.add(USER, source)
    await _component(store).on_source_indexed(str(USER), source)

    [row] = store.rows[(str(USER), str(source.raw.source_id))]
    assert row["zone"] == "Asia/Shanghai" and row["zone_source"] == "profile"

    # No profile at all → the deployment's own assumption, and it says so.
    bare = TimeComponent(content=_Store(), default_timezone="UTC")
    await bare.on_source_indexed(str(USER), source)
    [row] = bare._content.rows[(str(USER), str(source.raw.source_id))]
    assert row["zone"] == "UTC" and row["zone_source"] == "deployment_default"


async def test_a_meeting_in_another_zone_is_keyed_by_the_owners_day_not_the_sources():
    """D1's second half: the source's own zone is METADATA. The Berlin meeting at 14:15 CEST
    is the owner's 20:15 on the same day here — and the row is keyed by his day."""
    store = _Store()
    source = _meeting()
    await store.add(USER, source)
    component = _component(store)
    await component.on_source_indexed(str(USER), source)

    rows = store.rows[(str(USER), str(source.raw.source_id))]
    assert [r["local_day"] for r in rows] == [date(2026, 4, 12), date(2026, 4, 12)]
    assert {r["source_zone"] for r in rows} == {"Europe/Berlin"}
    assert {r["zone"] for r in rows} == {"Asia/Shanghai"}


def test_the_compile_preamble_renders_both_clocks_when_the_zones_differ():
    """D5 at the compile seam: one instant, two true wall clocks; showing one hides the
    other from every question phrased in it."""
    store = _Store()
    component = _component(store)
    component._zones[str(USER)] = time_context_for(
        USER, _UserInfo().profile, now_utc=NOW
    )

    line = component.source_preamble(_meeting())
    assert line == (
        "Time of this source (the owner's calendar): 2026-04-12 (Sun) "
        "20:15–21:03 Asia/Shanghai · source zone Europe/Berlin 14:15–15:03"
    )
    # A source with no per-block instants adds nothing — compile already states occurred_on.
    assert component.source_preamble(_plain("s-plain", "2026-04-01")) is None


def test_the_preambles_day_matches_the_blocks_own_sections_even_on_a_cold_cache():
    """Index and compile are separate jobs, so a restart between them leaves this SYNC seam
    with no resolved zone. The day must still be the one the blocks are sectioned under —
    stating one day above blocks filed under another is the exact contradiction this
    component exists to prevent."""
    late = _im([("2026-04-13T00:30:00+08:00", "补一句")])
    assert late.blocks[0].section_path == ["2026-04-13"]

    cold = TimeComponent(content=_Store(), default_timezone="UTC")  # nothing cached
    line = cold.source_preamble(late)

    assert line.startswith("Time of this source (the owner's calendar): 2026-04-13 (Mon)")
    # …and it names the zone the clock was rendered under, so nothing is presented as the
    # owner's own when it is only the deployment's assumption.
    assert "16:30 UTC" in line


async def test_prepare_warms_the_zone_so_a_compile_renders_the_owners_clock():
    """`prepare` is the ASYNC face of the sync seam, and the reason it exists.

    A compile process's zone cache is cold by construction — the index job that filled it
    ran elsewhere — so without this hook the preamble falls through to the DEPLOYMENT
    default and renders a subject at +08:00 under UTC. Honest (the line names UTC), and
    still the wrong clock: it is the same instant told on a stranger's watch.
    """
    late = _im([("2026-04-13T00:30:00+08:00", "补一句")])

    cold = TimeComponent(content=_Store(), user_info=_UserInfo("Asia/Shanghai"),
                         default_timezone="UTC")
    assert "16:30 UTC" in cold.source_preamble(late)

    await cold.prepare(str(USER))
    warmed = cold.source_preamble(late)
    assert "00:30 Asia/Shanghai" in warmed
    assert warmed.startswith("Time of this source (the owner's calendar): 2026-04-13 (Mon)")


async def test_a_source_without_a_clock_still_gets_a_day_and_one_without_a_day_gets_no_row():
    store = _Store()
    dated = _plain("s-dated", "2026-04-01")
    undated = _plain("s-undated", "")
    await store.add(USER, dated)
    await store.add(USER, undated)
    component = _component(store)

    await component.on_source_indexed(str(USER), dated)
    await component.on_source_indexed(str(USER), undated)

    rows = store.rows[(str(USER), "s-dated")]
    assert [r["local_day"] for r in rows] == [date(2026, 4, 1), date(2026, 4, 1)]
    assert all(r["instant_utc"] is None for r in rows)
    # A block with no knowable day gets no row at all: a NULL day would answer every range
    # query wrongly rather than not at all.
    assert store.rows[(str(USER), "s-undated")] == []


async def test_a_meta_list_that_does_not_align_with_the_blocks_drops_the_clock_not_guesses():
    """The one failure that must never be silent: attaching entry i's timestamp to a block
    it does not belong to."""
    store = _Store()
    source = _im([("2026-04-12T09:00:00+08:00", "a"), ("2026-04-12T10:00:00+08:00", "b")])
    source.raw.meta = {**source.raw.meta, "messages": source.raw.meta["messages"][:1]}
    await store.add(USER, source)
    await _component(store).on_source_indexed(str(USER), source)

    rows = store.rows[(str(USER), str(source.raw.source_id))]
    assert all(r["instant_utc"] is None for r in rows)
    assert [r["local_day"] for r in rows] == [date(2026, 4, 12), date(2026, 4, 12)]


# ------------------------------------------------------- D2: rebuild is the only rewrite


async def test_a_zone_change_rewrites_nothing_until_an_explicit_rebuild():
    store = _Store()
    source = _im([("2026-04-13T00:30:00+08:00", "补一句")])
    await store.add(USER, source)
    component = _component(store)
    await component.on_source_indexed(str(USER), source)
    assert store.rows[(str(USER), str(source.raw.source_id))][0]["local_day"] == date(2026, 4, 13)

    # The owner moves. Nothing re-runs on its own; the existing row keeps saying what it was
    # built from.
    component._user_info = _UserInfo("Europe/Berlin")
    assert store.rows[(str(USER), str(source.raw.source_id))][0]["zone"] == "Asia/Shanghai"

    await component.rebuild(str(USER))
    row = store.rows[(str(USER), str(source.raw.source_id))][0]
    assert row["zone"] == "Europe/Berlin"
    # 2026-04-12T16:30Z is still the 12th in Berlin (+02:00) — the same instant, another day.
    assert row["local_day"] == date(2026, 4, 12)


async def test_a_rebuild_cannot_leave_a_previous_derivations_tail_behind():
    store = _Store()
    long_source = _im(
        [("2026-04-12T09:00:00+08:00", "a"), ("2026-04-12T10:00:00+08:00", "b")]
    )
    await store.add(USER, long_source)
    component = _component(store)
    await component.on_source_indexed(str(USER), long_source)
    assert len(store.rows[(str(USER), str(long_source.raw.source_id))]) == 2

    short = _im([("2026-04-12T09:00:00+08:00", "a")])
    short.raw.source_id = long_source.raw.source_id
    await store.add(USER, short)
    await component.rebuild(str(USER))
    assert len(store.rows[(str(USER), str(long_source.raw.source_id))]) == 1


# ------------------------------------------------------------------ the fast path


def _page(slug: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/people/{slug}.md",
        frontmatter={"doc_id": f"d-{slug}", "type": "person", "slug": slug},
        body=body,
    )


async def _seeded() -> tuple[_Store, TimeComponent, NormalizedSource, NormalizedSource]:
    store = _Store()
    june = _im(
        [
            ("2026-06-02T09:00:00+08:00", "先给排期"),
            ("2026-06-02T09:05:00+08:00", "再谈价"),
            ("2026-06-03T20:00:00+08:00", "隔天补充"),
        ],
        archive="june",
    )
    august = _im([("2026-08-01T09:00:00+08:00", "八月的事")], archive="august")
    await store.add(USER, june)
    await store.add(USER, august)
    component = _component(store)
    await component.on_source_indexed(str(USER), june)
    await component.on_source_indexed(str(USER), august)
    return store, component, june, august


async def test_timespan_groups_consecutive_blocks_of_one_source_per_day_and_orders_by_time():
    store, component, june, _ = await _seeded()

    result = await component.timespan(
        USER, since="2026-06-01", until="2026-06-30", documents=[], as_of=NOW
    )

    spans = [(str(w.source_id), w.block_start, w.block_end) for w in result.windows]
    # Two blocks on the 2nd are one span; the 3rd is its own, because the DAY is the unit.
    assert spans == [(str(june.raw.source_id), 0, 1), (str(june.raw.source_id), 2, 2)]
    assert result.windows[0].text.startswith(
        "2026-06-02 (Tue, 2 months before as_of) 09:00–09:05 Asia/Shanghai"
    )
    assert "先给排期" in result.windows[0].text and "再谈价" in result.windows[0].text
    assert result.windows[1].text.startswith("2026-06-03 (Wed, 2 months before as_of) 20:00")
    # August is outside the range.
    assert all("八月" not in w.text for w in result.windows)


async def test_timespan_returns_the_ranges_claims_current_first_and_labels_the_superseded():
    store, component, june, august = await _seeded()
    page = _page(
        "jia-ning",
        f"- 贾宁是恒印对接人。[cite: {june.raw.source_id} ¶0-1] <!-- c:a1f3 -->\n"
        f"- 贾宁任采购总监。[cite: {august.raw.source_id} ¶0-0] <!-- c:c07e --> "
        f"<!-- supersedes: c:a1f3 -->",
    )

    june_result = await component.timespan(
        USER, since="2026-06-01", until="2026-06-30", documents=[page], as_of=NOW
    )
    assert [(str(c.anchor), c.labels) for c in june_result.claims] == [
        ("a1f3", ("superseded",))
    ]

    both = await component.timespan(
        USER, since="2026-06-01", until="2026-08-31", documents=[page], as_of=NOW
    )
    assert [(str(c.anchor), c.labels) for c in both.claims] == [
        ("c07e", ("current",)),
        ("a1f3", ("superseded",)),
    ]


async def test_the_path_returns_the_whole_range_and_the_framework_caps_it():
    """The path enumerates; the cap belongs to the framework, applied AFTER ordering — and
    what it did not show is described per day, not quietly cut."""
    from pneuma_knowledge_core.recall.paths import merge_component_evidence, run_paths

    store = _Store()
    # 20 separate days in one month — comfortably past the path's cap of 12.
    wide = _im(
        [(f"2026-06-{day:02d}T09:00:00+08:00", f"第 {day} 天") for day in range(1, 21)],
        archive="wide",
    )
    await store.add(USER, wide)
    component = _component(store)
    await component.on_source_indexed(str(USER), wide)

    [path] = component.fast_paths(str(USER))
    args = path.args_schema(since="2026-06-01", until="2026-06-30")
    [evidence] = await run_paths(
        str(USER), [(path, args)], question="六月 12 号发生了什么", documents=[], as_of=NOW
    )

    assert evidence.degraded is None
    # the lookup returns the WHOLE range: 20 days, nothing cut at the source
    assert len(evidence.windows) == 20 and evidence.dropped == 0
    # the day the question names ranks first, before any cap is spent
    assert evidence.windows[0].text.startswith("2026-06-12")

    [merged], _ = merge_component_evidence([evidence], claims=[], windows=[])
    assert len(merged.windows) == path.cap
    assert merged.dropped == 20 - path.cap  # counted, not quietly cut
    # and DESCRIBED: one entry per omitted day
    assert len(merged.dropped_summary) == 20 - path.cap
    assert all(count == 1 for _, count in merged.dropped_summary)
    assert sum(count for _, count in merged.dropped_summary) == merged.dropped


async def test_a_colloquial_or_non_iso_day_never_reaches_the_index():
    """D4. The index parses no natural-language time, so a bad argument is an audit row —
    not a range quietly interpreted as something else."""
    store, component, *_ = await _seeded()
    paths = component.fast_paths(str(USER))

    class _Router:
        async def ainvoke(self, messages, config=None):
            from langchain_core.messages import AIMessage

            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "timespan",
                        "args": {"since": "2025/06/02", "until": "上季度"},
                        "id": "t1",
                        "type": "tool_call",
                    }
                ],
            )

    class _Model:
        def bind_tools(self, tools, **kw):
            return _Router()

    chosen, _usage, degraded, rejected = await route_paths(
        _Model(), "上季度都发生了什么", paths, as_of=NOW, zone="Asia/Shanghai"
    )
    assert chosen == [] and degraded is None
    assert [(r.path, r.degraded) for r in rejected] == [("timespan", "invalid_args")]


# ------------------------------------------------------------------ deep-recall tools


async def test_timeline_is_a_deterministic_digest_that_states_what_it_holds():
    store, component, june, august = await _seeded()
    page = _page("jia-ning", f"- 定了排期。[cite: {june.raw.source_id} ¶0-1] <!-- c:a1f3 -->")

    text = await component.timeline(
        USER, since="2026-06-01", until="2026-08-31", documents=[page]
    )

    assert text == await component.timeline(
        USER, since="2026-06-01", until="2026-08-31", documents=[page]
    )
    lines = text.splitlines()
    assert lines[0] == (
        "3 source span(s) across 3 day(s) in 2026-06-01..2026-08-31 "
        "(the owner's calendar, Asia/Shanghai; zone from profile)"
    )
    assert "## 2026-06-02 (Tue)" in lines
    assert any(f"[cite: {june.raw.source_id} ¶0-1]" in line for line in lines)
    assert any("· [c:a1f3 · memory/people/jia-ning.md · current] 定了排期。" in line for line in lines)

    weekly = await component.timeline(
        USER, since="2026-06-01", until="2026-08-31", granularity="week", documents=[page]
    )
    assert "## 2026-06-01..2026-06-07 (week)" in weekly.splitlines()


async def test_timeline_says_so_when_a_window_holds_nothing():
    _store, component, *_ = await _seeded()
    text = await component.timeline(USER, since="2026-01-01", until="2026-01-31", documents=[])
    assert text.splitlines()[-1] == "(no material in this window)"


async def test_timeline_pages_its_buckets_and_says_how_to_read_the_rest():
    """Deep: completeness over caps. A digest that simply stopped at bucket N would read as
    \"that was the whole window\"."""
    _store, component, *_ = await _seeded()

    first = await component.timeline(
        USER, since="2026-06-01", until="2026-08-31", documents=[], limit=2
    )
    assert first.count("\n## ") == 2
    assert "2 of 3 day(s) shown (positions 1-2)" in first
    assert (
        'the rest: timeline(since="2026-06-01", until="2026-08-31", granularity="day", '
        "offset=2, limit=2)" in first
    )
    # the way DOWN is spelled out too, not left for the model to invent
    assert 'one section: timeline(since="2026-06-02", until="2026-06-02", granularity="verbatim")' in first

    rest = await component.timeline(
        USER, since="2026-06-01", until="2026-08-31", documents=[], offset=2, limit=2
    )
    assert rest.count("\n## ") == 1 and "the rest:" not in rest


async def test_verbatim_reads_one_whole_day_block_by_block_and_refuses_a_range():
    _store, component, june, _ = await _seeded()

    text = await component.timeline(
        USER, since="2026-06-02", until="2026-06-02", granularity="verbatim", documents=[]
    )
    lines = text.splitlines()
    assert lines[0].startswith("# 2026-06-02 (Tue) — 2 block(s) across 1 source span(s)")
    assert f"[cite: {june.raw.source_id} ¶0-0] " in text and "先给排期" in text
    assert f"[cite: {june.raw.source_id} ¶1-1] " in text and "再谈价" in text
    assert "2 of 2 blocks shown" in text

    paged = await component.timeline(
        USER, since="2026-06-02", until="2026-06-02", granularity="verbatim", documents=[], limit=1
    )
    assert "1 of 2 blocks shown (positions 1-1)" in paged
    assert "offset=1, limit=1" in paged

    ranged = await component.timeline(
        USER, since="2026-06-01", until="2026-06-30", granularity="verbatim", documents=[]
    )
    assert ranged.startswith("verbatim reads ONE day at a time")
    assert 'timeline(since="2026-06-01", until="2026-06-01", granularity="verbatim")' in ranged


async def test_as_of_reports_the_chain_link_that_was_in_force_on_that_day():
    store, component, june, august = await _seeded()
    page = _page(
        "jia-ning",
        f"- 贾宁是恒印对接人。[cite: {june.raw.source_id} ¶0-1] <!-- c:a1f3 -->\n"
        f"- 贾宁任采购总监。[cite: {august.raw.source_id} ¶0-0] <!-- c:c07e --> "
        f"<!-- supersedes: c:a1f3 -->",
    )

    early = await component.as_of(USER, day="2026-07-01", alias="jia-ning", documents=[page])
    assert "[c:a1f3 · evidence 2026-06-02] 贾宁是恒印对接人。" in early
    assert "(superseded after this date by c:c07e)" in early

    late = await component.as_of(USER, day="2026-08-20", alias="jia-ning", documents=[page])
    assert "[c:c07e · evidence 2026-08-01] 贾宁任采购总监。" in late
    assert "superseded after this date" not in late

    assert "no page matches 老王" in await component.as_of(
        USER, day="2026-08-20", alias="老王", documents=[page]
    )


async def test_as_of_says_plainly_when_nothing_about_the_subject_has_changed():
    store, component, june, _ = await _seeded()
    page = _page("jia-ning", f"- 一条事实。[cite: {june.raw.source_id} ¶0-1] <!-- c:a1f3 -->")
    text = await component.as_of(USER, day="2026-07-01", alias="jia-ning", documents=[page])
    assert "no superseded chain on this page" in text


async def test_as_of_delegates_identity_resolution_to_the_people_component_when_enabled():
    from pneuma_knowledge_service.components.people import PeopleComponent

    store, component, june, _ = await _seeded()
    page = CanonicalDocument(
        doc_id=DocumentId("d-jn"),
        path="memory/people/jn.md",
        frontmatter={"doc_id": "d-jn", "type": "person", "slug": "jn", "aliases": "贾宁"},
        body=f"- 一条事实。[cite: {june.raw.source_id} ¶0-1] <!-- c:a1f3 -->",
    )
    # Without `people`, the alias 贾宁 is not the slug and nothing matches.
    assert "no page matches 贾宁" in await component.as_of(
        USER, day="2026-07-01", alias="贾宁", documents=[page]
    )

    register_component(PeopleComponent("memory/people/{slug}.md"))
    text = await component.as_of(USER, day="2026-07-01", alias="贾宁", documents=[page])
    assert "`memory/people/jn.md`" in text


# ------------------------------------------------------------------ pure helpers, wiring


def test_group_spans_cuts_at_a_day_boundary_and_at_a_block_gap():
    rows = [
        {"source_id": "s1", "block_index": 0, "local_day": date(2026, 6, 2), "instant_utc": None},
        {"source_id": "s1", "block_index": 1, "local_day": date(2026, 6, 2), "instant_utc": None},
        {"source_id": "s1", "block_index": 3, "local_day": date(2026, 6, 2), "instant_utc": None},
        {"source_id": "s1", "block_index": 4, "local_day": date(2026, 6, 3), "instant_utc": None},
    ]
    assert [(s.start, s.end, s.day) for s in group_spans(rows)] == [
        (0, 1, date(2026, 6, 2)),
        (3, 3, date(2026, 6, 2)),
        (4, 4, date(2026, 6, 3)),
    ]


def test_time_rows_is_pure_and_needs_no_store():
    source = _im([("2026-04-12T23:30:00+08:00", "x")])
    ctx = time_context_for(USER, _UserInfo().profile, now_utc=NOW)
    [row] = time_rows(source.raw, source.blocks, ctx)
    assert row["local_day"] == date(2026, 4, 12) and row["kind"] == "im"


def test_time_is_registrable_by_name_and_an_unknown_name_still_fails_loudly():
    from pneuma_knowledge_core.components import registered_components

    settings = Settings(components="people,time")
    assert register_components(settings, store=_Store(), canonical=None) == ["people", "time"]
    assert [c.name for c in registered_components()] == ["people", "time"]

    reset_components()
    with pytest.raises(ValueError, match="unknown index component"):
        register_components(Settings(components="places"), store=_Store(), canonical=None)


def test_the_time_component_offers_its_path_and_its_two_deep_tools():
    component = _component(_Store())
    [path] = component.fast_paths(str(USER))
    assert path.name == "timespan" and path.cap == 12
    assert "YYYY-MM-DD" in path.description
    assert {t.name for t in component.recall_tools(str(USER))} == {"timeline", "as_of"}
