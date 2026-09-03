"""The `people` component's address-term projection against the live compose postgres.

What only a real PG can prove: the schema applies, the write path ACCUMULATES (a term's
meaning is its distribution across sources, so each source adds to what is there rather than
replacing a slice) and does so at most ONCE per source — `component_people_indexed` is
claimed in the same transaction as the counts, which is what makes the archive's subtraction
of one recomputed copy exact — day bounds widen rather than move, the rows are per tenant
(I1), a rebuild reproduces the table byte-identically from an empty pair of tables, and a
long-lived compile worker's mirror follows the table across jobs rather than freezing at its
first one. `reported_since` — the day a (term → target) pair first crossed the reporting bar
— is here too: it is written once, never moved, and re-derived from L0 by the rebuild, which
is what lets the forced alias decision be asked ONCE. The component's one table is this
projection; nothing stores a decline any more, here or in canonical.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import ImSource

from pneuma_knowledge_service.components.people import (
    PeopleComponent,
    reported_terms,
    term_key,
)

FAMILY = "memory/people/{slug}.md"

USERS = [
    ("u_owner", "Lin ZHOU"),
    ("u_hw", "Hao WEN"),
    ("u_lan", "Lan LIU"),
]


def _at(hour: int, minute: int = 0, day: int = 12) -> str:
    return datetime(2026, 5, day, hour, minute, tzinfo=timezone.utc).isoformat()


def _source(user: UserId, archive: str, messages):
    payload = {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": archive,
        "owner_user_ids": ["u_owner"],
        "users": [{"user_id": uid, "display_name": name} for uid, name in USERS],
        "conversations": [
            {
                "conversation_id": f"c-{archive}",
                "conversation_type": "group_dm",
                "title": "运营群",
                "member_ids": [uid for uid, _ in USERS],
                "messages": [
                    {"message_id": f"{archive}-{i}", "sender_id": s, "sent_at": at, "text": t}
                    for i, (s, at, t) in enumerate(messages)
                ],
            }
        ],
    }
    [normalized] = normalize_source_contract(
        ImSource.model_validate(payload),
        user,
        imported_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    return normalized


async def _accumulated(pg_store, user) -> set[str]:
    """The manifest, read directly: which sources the counts already hold. No adapter method
    exposes it — nothing but `add_people_terms` has any business asking."""
    async with pg_store._pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT source_id FROM component_people_indexed WHERE user_id = %s",
            (str(user),),
        )).fetchall()
    return {r[0] for r in rows}


def _turns(day: int):
    return [
        ("u_owner", _at(9, 0, day), "@Hao WEN 阿宝，我不发通知了，你直接同步。"),
        ("u_hw", _at(9, 2, day), "好的，我这边先不动。"),
        ("u_owner", _at(9, 5, day), "阿宝，这两句文案你再顺一下。"),
        ("u_hw", _at(9, 7, day), "收到，晚点给你。"),
        ("u_owner", _at(10, 0, day), "是的，那就先这样。"),
        ("u_lan", _at(10, 1, day), "好。"),
    ]


async def test_the_projection_accumulates_and_a_rebuild_reproduces_it_byte_for_byte(
    pg_store, user
):
    component = PeopleComponent(FAMILY, content=pg_store)
    first = _source(user, "arc-p1", _turns(12))
    second = _source(user, "arc-p2", _turns(14))
    for source in (first, second):
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    rows = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    hao = rows[("阿宝", "im:u_hw")]
    # two sources' counts SUMMED, not replaced, and the day bounds widened over both
    assert (hao["answered"], hao["co_mention"], hao["sources"]) == (4, 2, 2)
    assert (hao["first_day"], hao["last_day"]) == ("2026-05-12", "2026-05-14")
    assert hao["target_name"] == "Hao WEN"
    # `是的` never reached the table at all: the grammar refuses it before any counting
    assert not [key for key in rows if key[0] == "是的"]
    assert reported_terms(
        [r for r in await component.library_terms(user)]
    ).keys() == {"阿宝"}

    # a restricted read answers the preamble's question without loading the library
    assert [r["term"] for r in await pg_store.people_terms(user, terms=["阿宝"])] == ["阿宝"]
    assert await pg_store.people_terms(user, terms=[]) == []

    # both sources are claimed in the manifest, and a repeat of one adds NOTHING: the
    # accumulation is idempotent per source, so an at-least-once queue cannot double it
    assert await _accumulated(pg_store, user) == {
        str(first.raw.source_id), str(second.raw.source_id)
    }
    await component.on_source_indexed(str(user), first)
    assert await pg_store.people_terms(user) == list(rows.values())
    # … and the rebuild re-derives the same table from L0, both tables starting from nothing
    await component.rebuild(str(user))
    assert await pg_store.people_terms(user) == list(rows.values())
    assert await _accumulated(pg_store, user) == {
        str(first.raw.source_id), str(second.raw.source_id)
    }


async def test_reported_since_is_written_once_and_a_rebuild_re_derives_it(pg_store, user):
    """The additive column the one-time ask runs on, against the real schema and the real
    `… WHERE reported_since IS NULL` update. A pair needs two sources, so it crosses the bar
    on the SECOND day; nothing after that moves the date, and a rebuild replaying L0 in
    `(occurred_on, source_id)` order arrives at the same day from an empty table."""
    component = PeopleComponent(FAMILY, content=pg_store)
    sources = [_source(user, f"arc-s{n}", _turns(day)) for n, day in enumerate((12, 14, 16))]
    for source in sources:
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    rows = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    hao = rows[("阿宝", "im:u_hw")]
    assert hao["sources"] == 3
    # one conversation is an anecdote, so the day the library STARTED asking is the second
    assert hao["reported_since"] == "2026-05-14"

    # a fourth source adds support and the stamp stands: written once, never moved
    fourth = _source(user, "arc-s9", _turns(20))
    await pg_store.add(user, fourth)
    await component.on_source_indexed(str(user), fourth)
    after = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    assert after[("阿宝", "im:u_hw")]["reported_since"] == "2026-05-14"
    assert after[("阿宝", "im:u_hw")]["sources"] == 4

    # …and a rebuild re-derives the whole table, dates included, byte for byte
    await component.rebuild(str(user))
    assert await pg_store.people_terms(user) == list(after.values())


async def test_a_rebuild_re_dates_a_projection_the_index_jobs_stamped_out_of_order(
    pg_store, user
):
    """The date is a fact about the MATERIAL, so it may not depend on the order the queue
    drained. Indexed newest-first, the incremental path stamps the pair with the second
    source it happened to see; the rebuild replays L0 in the material's own order and
    produces the day the library actually started asking."""
    component = PeopleComponent(FAMILY, content=pg_store)
    sources = [_source(user, f"arc-o{n}", _turns(day)) for n, day in enumerate((12, 14, 16))]
    for source in sources:
        await pg_store.add(user, source)
    for source in reversed(sources):
        await component.on_source_indexed(str(user), source)

    arrival = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    assert arrival[("阿宝", "im:u_hw")]["reported_since"] == "2026-05-14"  # 16 then 14

    await component.rebuild(str(user))
    rebuilt = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    assert rebuilt[("阿宝", "im:u_hw")]["reported_since"] == "2026-05-14"
    # …and a second rebuild reproduces the first, byte for byte
    await component.rebuild(str(user))
    assert await pg_store.people_terms(user) == list(rebuilt.values())


#: A synthetic API vendor the turns talk ABOUT — the shape of term that concentrates on
#: whoever habitually answers and is nobody's name.
VENDOR = "Zetlin"


def _mixed_turns(day: int):
    """The same conversation with one impostor added: a word that opens two messages Hao
    answers and turns up three more times inside sentences."""
    return [
        *_turns(day),
        ("u_owner", _at(11, 0, day), f"{VENDOR}，这个接口你跟一下。"),
        ("u_hw", _at(11, 1, day), "我来跟。"),
        ("u_owner", _at(11, 30, day), f"{VENDOR}，限流口径也确认下。"),
        ("u_hw", _at(11, 31, day), "在确认了。"),
        ("u_owner", _at(12, 0, day), f"我们把 {VENDOR} 的返回值记一下，{VENDOR} 那边没说清楚。"),
        ("u_hw", _at(12, 1, day), "记下了。"),
        ("u_owner", _at(12, 30, day), f"我看 {VENDOR} 的文档也没写。"),
        ("u_hw", _at(12, 31, day), "我再翻翻。"),
    ]


async def test_the_mid_sentence_count_round_trips_through_the_real_column(pg_store, user):
    """The column the vocative share is read from: it is written, accumulated and re-derived
    by the same paths as every other count, and the schema this repo boots with carries it —
    a table created before the column exists is altered into shape rather than dropped."""
    component = PeopleComponent(FAMILY, content=pg_store)
    for archive, day in (("arc-v1", 12), ("arc-v2", 14)):
        source = _source(user, archive, _mixed_turns(day))
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    rows = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    vendor = rows[(term_key(VENDOR), "im:u_hw")]
    # summed across the two sources like every other column: 2 vocatives and 3 mid-sentence
    # occurrences per conversation
    assert (vendor["answered"], vendor["non_vocative"]) == (4, 6)
    # the nickname is at the vocative position and nowhere else
    assert rows[("阿宝", "im:u_hw")]["non_vocative"] == 0

    # …so the library reports one of them and not the other, read back out of real rows
    library = await component.library_terms(user)
    assert reported_terms(library).keys() == {"阿宝"}

    # a re-index leaves the new column where it stands, like every other count — the
    # source id is content-addressed, so a freshly built copy of the same material is the
    # same source and the manifest already holds it
    await component.on_source_indexed(str(user), _source(user, "arc-v1", _mixed_turns(12)))
    assert await pg_store.people_terms(user) == list(rows.values())
    await component.rebuild(str(user))
    assert await pg_store.people_terms(user) == list(rows.values())


async def test_the_projection_is_per_tenant_and_a_deleted_user_takes_it_with_them(
    pg_store, user
):
    other_user = UserId(f"{user}-x")
    mine = PeopleComponent(FAMILY, content=pg_store)
    theirs = PeopleComponent(FAMILY, content=pg_store)
    for owner, component, archive in (
        (user, mine, "arc-mine"),
        (other_user, theirs, "arc-theirs"),
    ):
        source = _source(owner, archive, _turns(12))
        await pg_store.add(owner, source)
        await component.on_source_indexed(str(owner), source)

    assert len(await pg_store.people_terms(user)) == len(await pg_store.people_terms(other_user))
    assert await pg_store.delete_people_terms(user) > 0
    assert await pg_store.people_terms(user) == []
    # the neighbour's rows are untouched: no cross-user read or write path exists (I1)
    assert await pg_store.people_terms(other_user) != []

    # …and dropping a user takes their projection with them (no source FK to cascade from)
    await pg_store.delete_user(other_user)
    assert await pg_store.people_terms(other_user) == []


async def test_a_long_lived_worker_sees_the_terms_a_later_index_job_wrote(pg_store, user):
    """`prepare` is per JOB, and so is the read behind it. The counts are the half of this
    component's mirror that changes: an index job in another process adds to the table while
    a compile worker is alive, and a mirror read once per process would state that worker's
    first job's library for the rest of its life."""
    worker = PeopleComponent(FAMILY, content=pg_store)
    indexer = PeopleComponent(FAMILY, content=pg_store)
    first = _source(user, "arc-w1", _turns(12))
    await pg_store.add(user, first)
    await indexer.on_source_indexed(str(user), first)

    await worker.prepare(str(user))
    before = {(r.term, r.target) for r in worker._mirrored_terms(str(user))}
    assert ("阿宝", "im:u_hw") in before

    # the index process folds a second source in — a term this worker has never seen
    second = _source(user, "arc-w2", [
        ("u_owner", _at(9, 0, 15), "@Lan LIU 小兰，物料清单你来跟。"),
        ("u_lan", _at(9, 2, 15), "好，今天给你。"),
        ("u_owner", _at(9, 5, 15), "小兰，纸张也一起问了。"),
        ("u_lan", _at(9, 7, 15), "收到。"),
    ])
    await pg_store.add(user, second)
    await indexer.on_source_indexed(str(user), second)

    # …and the worker's NEXT job sees it, without a restart
    await worker.prepare(str(user))
    after = {(r.term, r.target) for r in worker._mirrored_terms(str(user))}
    assert ("小兰", "im:u_lan") in after and before < after


async def test_the_source_cursor_returns_only_what_arrived_after_the_watermark(pg_store, user):
    """The incremental boundary read against real SQL. Two sources imported in one batch
    share a `created_at` — which is why the cursor is the PAIR: a `> created_at` predicate
    would drop all but the last of them for good, and the component would judge later rounds
    against a library missing a source it can never fetch again."""
    batch = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)
    first = _source(user, "arc-c1", _turns(12))
    second = _source(user, "arc-c2", _turns(13))
    later = _source(user, "arc-c3", _turns(14))
    for source, stamp in ((first, batch), (second, batch), (later, batch.replace(hour=10))):
        source.raw.created_at = stamp
        await pg_store.add(user, source)

    everything = await pg_store.list_since(user)
    ids = [str(r.source_id) for r in everything]
    # oldest first, and inside the shared wall clock the source_id breaks the tie
    assert ids == sorted(ids[:2]) + [str(later.raw.source_id)]

    # …resuming from the FIRST of the two that share a wall clock returns the second
    after = (batch, min(ids[0], ids[1]))
    assert [str(r.source_id) for r in await pg_store.list_since(user, after=after)] == [
        max(ids[0], ids[1]),
        ids[2],
    ]
    # …and from the end of the batch, only the source imported after it
    assert [
        str(r.source_id)
        for r in await pg_store.list_since(user, after=(batch, max(ids[0], ids[1])))
    ] == [ids[2]]
    # …and from the very end, nothing
    assert await pg_store.list_since(user, after=(batch.replace(hour=10), ids[2])) == []


async def test_a_second_prepare_reads_only_the_source_imported_since_the_first(pg_store, user):
    """The component's own use of it: a long-lived worker's later jobs transfer what arrived,
    not the library. What it holds afterwards is the same mirror either way."""
    component = PeopleComponent(FAMILY, content=pg_store)
    first = _source(user, "arc-i1", _turns(12))
    await pg_store.add(user, first)
    await component.prepare(str(user))
    assert component._mirrored[str(user)] == {str(first.raw.source_id)}
    watermark = component._watermark[str(user)]

    second = _source(user, "arc-i2", _turns(14))
    await pg_store.add(user, second)
    # exactly one row crosses the boundary for the next job…
    assert [str(r.source_id) for r in await pg_store.list_since(user, after=watermark)] == [
        str(second.raw.source_id)
    ]
    await component.prepare(str(user))
    # …and the mirror holds both sources, with the cursor moved on
    assert component._mirrored[str(user)] == {
        str(first.raw.source_id),
        str(second.raw.source_id),
    }
    assert component._watermark[str(user)] > watermark


async def test_enumerate_identities_excludes_archived_sources(pg_store, user):
    """`enumerate_identities` is a CLOSED-WORLD enumeration over L0 — "who is in the
    library" — so it answers over LIVE sources (docs/design/archive.md §4).

    The component is given no `include_archived` and learns nothing about the archive
    (invariant I7); it simply reads L0 as L0 stands. It has to be the reader that filters,
    because `ContentStore.list` is the authority's own enumeration and hides nothing (I3),
    and because a deep tool hands the model prose the assembly filter cannot redact.
    """
    from pneuma_knowledge_core.domain.ids import SourceId

    component = PeopleComponent(FAMILY, content=pg_store)
    live = _source(user, "arc-live", _turns(12))
    retired = _source(user, "arc-gone", _turns(14))
    for source in (live, retired):
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    both = await component.enumerate(user, since="2026-05-01", until="2026-05-31")
    assert "2 source(s)" in both  # Hao WEN was seen in both conversations

    await pg_store.set_source_archived(user, retired.raw.source_id, True)

    after = await component.enumerate(user, since="2026-05-01", until="2026-05-31")
    assert "2 source(s)" not in after
    assert "1 source(s)" in after
    # …and the archived source is still IN L0 and still addressable by id.
    assert (await pg_store.get(user, SourceId(str(retired.raw.source_id)))) is not None
    assert str(retired.raw.source_id) in {
        str(sid) for sid in await pg_store.archived_source_ids(user)
    }

    # Unarchiving restores the closed world it was computed over.
    await pg_store.set_source_archived(user, retired.raw.source_id, False)
    assert "2 source(s)" in await component.enumerate(
        user, since="2026-05-01", until="2026-05-31"
    )


def _lan_turns(day: int):
    """A second nickname, carried by its own conversations, so it can be retired alone."""
    return [
        ("u_owner", _at(9, 0, day), "@Lan LIU 小兰，物料清单你来跟。"),
        ("u_lan", _at(9, 2, day), "好，今天给你。"),
        ("u_owner", _at(9, 5, day), "小兰，纸张也一起问了。"),
        ("u_lan", _at(9, 7, day), "收到。"),
    ]


async def test_a_term_only_archived_sources_support_is_no_longer_reported(pg_store, user):
    """The address terms hold to the same rule `enumerate_identities` does, and this is the
    one face where it costs arithmetic.

    `component_people_terms` is an ACCUMULATION — one row per (term → target) pair for the
    whole library — so there is no source column to join `sources.archived_at IS NULL`
    against the way `time_blocks_in_range` does, and the primary key IS the pair, so there
    cannot be one. What built the row is addition, so the archived sources' own contribution
    is recomputed from L0 and subtracted at the READ (`subtract_term_rows`). A nickname the
    archive accounted for entirely disappears rather than reporting a smaller count: it is
    not a weak candidate, it is a name the library has stopped saying.

    The table itself is untouched — it keeps every source and still rebuilds from all of L0
    (I2) — and unarchiving brings the term back with nothing re-indexed.
    """
    component = PeopleComponent(FAMILY, content=pg_store)
    hao = [_source(user, "arc-h1", _turns(12)), _source(user, "arc-h2", _turns(14))]
    lan = [_source(user, "arc-l1", _lan_turns(16)), _source(user, "arc-l2", _lan_turns(18))]
    for source in (*hao, *lan):
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    assert reported_terms(await component.library_terms(user)).keys() == {"阿宝", "小兰"}

    for source in lan:
        await pg_store.set_source_archived(user, source.raw.source_id, True)

    # the ASYNC face — `find_person`'s lookup tier, the deep tools, the fast `person` path
    live = await component.library_terms(user)
    assert reported_terms(live).keys() == {"阿宝"}
    assert term_key("小兰") not in {row.term for row in live}

    # the SYNC seams — the compile-face term report and the gate checks — read the mirror
    # `prepare` fills, and it is net of the archive too.
    await component.prepare(str(user))
    assert reported_terms(component._mirrored_terms(str(user))).keys() == {"阿宝"}

    # …and the deep tool's prose, which the framework's assembly filter cannot redact.
    listing = await component.enumerate(user, since="2026-05-01", until="2026-05-31")
    assert "阿宝" in listing and "小兰" not in listing

    # The TABLE still holds every source: the archive is a property of the read (I2).
    assert term_key("小兰") in {r["term"] for r in await pg_store.people_terms(user)}

    # Unarchiving brings the term back, with nothing re-indexed.
    for source in lan:
        await pg_store.set_source_archived(user, source.raw.source_id, False)
    await component.prepare(str(user))
    assert reported_terms(await component.library_terms(user)).keys() == {"阿宝", "小兰"}
    assert reported_terms(component._mirrored_terms(str(user))).keys() == {"阿宝", "小兰"}


async def test_archiving_one_of_a_terms_sources_leaves_the_rest_of_its_support(
    pg_store, user
):
    """Subtraction, not deletion. A pair the archive only PARTLY accounts for keeps what its
    live sources still show — the counts come down by exactly one source's contribution —
    and the reporting rule then decides on the arithmetic that is left. Here it falls under
    `REPORT_MIN_SOURCES`, which is the honest outcome: one conversation is not a library-wide
    distribution."""
    component = PeopleComponent(FAMILY, content=pg_store)
    first = _source(user, "arc-s1", _turns(12))
    second = _source(user, "arc-s2", _turns(14))
    for source in (first, second):
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)

    stored = {(r.term, r.target): r for r in await component.library_terms(user)}
    assert stored[("阿宝", "im:u_hw")].sources == 2

    await pg_store.set_source_archived(user, second.raw.source_id, True)

    rows = {(r.term, r.target): r for r in await component.library_terms(user)}
    kept = rows[("阿宝", "im:u_hw")]
    assert kept.sources == 1, "one source's contribution came out, the other stayed"
    assert kept.answered == stored[("阿宝", "im:u_hw")].answered // 2
    assert reported_terms(rows.values()) == {}, "and one source is not a distribution"


async def test_a_retried_index_job_in_a_fresh_worker_adds_the_source_only_once(
    pg_store, user
):
    """The shape the finding actually has. An index job is at-least-once — a worker killed
    mid-job, a job the queue self-heals on restart — and the retry usually runs in a NEW
    process, where nothing in memory remembers the first attempt. The guard therefore has to
    live in the database, not in the component: the manifest row is claimed in the same
    transaction as the counts, so the second attempt claims nothing and adds nothing.
    """
    source = _source(user, "arc-r1", _turns(12))
    await pg_store.add(user, source)

    first_worker = PeopleComponent(FAMILY, content=pg_store)
    await first_worker.on_source_indexed(str(user), source)
    once = await pg_store.people_terms(user)
    assert once, "the first attempt is the one that writes"

    # the job is re-delivered to a process that shares nothing with the first
    second_worker = PeopleComponent(FAMILY, content=pg_store)
    await second_worker.on_source_indexed(str(user), source)
    assert await pg_store.people_terms(user) == once
    assert await _accumulated(pg_store, user) == {str(source.raw.source_id)}

    # …and the second worker's own mirror says the same thing as the table it skipped
    assert {(r.term, r.target) for r in await second_worker.library_terms(user)} == {
        (r["term"], r["target_identity"]) for r in once
    }


async def test_a_term_only_an_archived_source_supports_vanishes_after_a_repeated_index(
    pg_store, user
):
    """The finding itself: why the accumulation has to be idempotent, and not merely tidy.

    The archive is subtracted at the READ — one copy of the archived sources' contribution,
    recomputed from L0 (`subtract_term_rows`). That arithmetic is exact only if the table
    holds one copy too. With the counts doubled by a redelivered index job, subtracting one
    copy left the other behind, and a nickname whose only conversations the Owner retired
    stayed on offer in `find_person`, in the compile-face term report and in the deep tools.
    """
    lan = [_source(user, f"arc-la{n}", _lan_turns(day)) for n, day in enumerate((16, 18, 20))]
    hao = [_source(user, "arc-ha1", _turns(12)), _source(user, "arc-ha2", _turns(14))]
    component = PeopleComponent(FAMILY, content=pg_store)
    for source in (*lan, *hao):
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)
    # a worker dies mid-drain and the batch of 小兰's index jobs is delivered again — the
    # amount of double counting that survives a subtraction, rather than a single stray one
    for source in lan:
        await component.on_source_indexed(str(user), source)
    assert reported_terms(await component.library_terms(user)).keys() == {"阿宝", "小兰"}
    lan_row = {(r.term, r.target): r for r in await component.library_terms(user)}[
        (term_key("小兰"), "im:u_lan")
    ]
    assert lan_row.sources == len(lan), "each conversation counted once, redelivery or not"

    for source in lan:
        await pg_store.set_source_archived(user, source.raw.source_id, True)

    # the async faces …
    assert reported_terms(await component.library_terms(user)).keys() == {"阿宝"}
    # … and the sync seams, which read the cache `prepare` fills
    await component.prepare(str(user))
    assert reported_terms(component._mirrored_terms(str(user))).keys() == {"阿宝"}
    listing = await component.enumerate(user, since="2026-05-01", until="2026-05-31")
    assert "小兰" not in listing


async def test_a_rebuild_after_a_repeated_index_re_derives_the_once_added_rows(
    pg_store, user
):
    """A rebuild has to empty BOTH tables. Clearing the counts alone would leave every source
    claimed in the manifest, so the replay would add nothing and the library would come back
    projected as empty — the failure a rebuild exists to be the answer to."""
    sources = [_source(user, f"arc-b{n}", _turns(day)) for n, day in enumerate((12, 14))]
    component = PeopleComponent(FAMILY, content=pg_store)
    for source in sources:
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)
    once = await pg_store.people_terms(user)
    for source in sources:
        await component.on_source_indexed(str(user), source)

    await component.rebuild(str(user))
    rebuilt = await pg_store.people_terms(user)
    assert rebuilt, "the replay re-derived the library rather than skipping it"
    assert rebuilt == once
    assert await _accumulated(pg_store, user) == {str(s.raw.source_id) for s in sources}

    # the first half of a rebuild, on its own: both tables go, or neither
    assert await pg_store.delete_people_terms(user) > 0
    assert await pg_store.people_terms(user) == []
    assert await _accumulated(pg_store, user) == set()


async def test_a_snapshot_copy_carries_neither_the_counts_nor_the_manifest(pg_store, user):
    """The two tables travel together — here by both staying put.

    `copy_tenant_rows` copies L0 and the claim projection and no component projection: a
    frozen tenant refuses every write, is never indexed and is never rebuilt, so it has no
    use for a term count. The manifest is keyed exactly like the counts it guards and moves
    with them, which here means it does not move: a manifest copied without its counts would
    tell the target tenant that sources contributing nothing had already been accumulated.
    """
    source = _source(user, "arc-c1", _turns(12))
    await pg_store.add(user, source)
    component = PeopleComponent(FAMILY, content=pg_store)
    await component.on_source_indexed(str(user), source)

    target = UserId(f"{user}-snap")
    counts = await pg_store.copy_tenant_rows(user, target)
    assert counts["sources"] == 1  # L0 travelled …

    assert await pg_store.people_terms(target) == []  # … the projection did not …
    assert await _accumulated(pg_store, target) == set()  # … nor the manifest
    # and the live tenant is untouched by the copy (I1)
    assert await pg_store.people_terms(user) != []
    assert await _accumulated(pg_store, user) == {str(source.raw.source_id)}

    await pg_store.delete_user(target)


async def test_the_schema_backfills_a_manifest_for_counts_that_predate_it(pg_store, user):
    """The upgrade path, against the real bootstrap: a library that accumulated before the
    manifest table existed.

    Its counts are held by a manifest that says nothing was ever accumulated, so the next
    redelivered index job would claim a free row and add its source a second time — exactly
    the doubling the manifest was added to close, arriving on the installations that have the
    most to lose. `apply_schema` runs on every process start, and the backfill it carries
    records every source a counted user owns as already accumulated, once. A user whose
    manifest has already begun is not a user this is about, and is left alone.
    """
    component = PeopleComponent(FAMILY, content=pg_store)
    sources = [_source(user, f"arc-m{n}", _turns(day)) for n, day in enumerate((12, 14))]
    for source in sources:
        await pg_store.add(user, source)
        await component.on_source_indexed(str(user), source)
    before = await pg_store.people_terms(user)
    assert before

    # …and back to the state the upgrade finds: the counts stand, the manifest does not.
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "DELETE FROM component_people_indexed WHERE user_id = %s", (str(user),)
        )
    assert await _accumulated(pg_store, user) == set()

    # A second library that already upgraded: counts AND a manifest — one that deliberately
    # does not name every source it owns, which is the ordinary state of a library whose
    # newest source has not been indexed yet.
    other = UserId(f"{user}-kept")
    accumulated = _source(other, "arc-m9", _turns(12))
    await pg_store.add(other, accumulated)
    await component.on_source_indexed(str(other), accumulated)
    pending = _source(other, "arc-m8", _turns(16))
    await pg_store.add(other, pending)
    assert await _accumulated(pg_store, other) == {str(accumulated.raw.source_id)}

    await pg_store.apply_schema()

    # Every source the counted library owns now reads as accumulated …
    assert await _accumulated(pg_store, user) == {str(s.raw.source_id) for s in sources}
    # … so a redelivered index job for one of them claims nothing and adds nothing.
    assert (
        await pg_store.add_people_terms(
            user,
            str(sources[0].raw.source_id),
            [{"term": "阿宝", "target_identity": "im:u_hw", "answered": 99}],
        )
        is False
    )
    assert await pg_store.people_terms(user) == before

    # …and the library whose manifest had already begun is byte-for-byte where it was: the
    # source it has not indexed yet stays unclaimed, so its counts still have somewhere to go.
    assert await _accumulated(pg_store, other) == {str(accumulated.raw.source_id)}

    # Applied again on the next boot, the backfill writes nothing more: the rows it wrote are
    # the manifest that now stops it.
    await pg_store.apply_schema()
    assert await _accumulated(pg_store, user) == {str(s.raw.source_id) for s in sources}
    assert await _accumulated(pg_store, other) == {str(accumulated.raw.source_id)}

    await pg_store.delete_user(other)
