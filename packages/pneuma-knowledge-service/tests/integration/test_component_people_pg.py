"""The `people` component's address-term projection against the live compose postgres.

What only a real PG can prove: the schema applies, the write path ACCUMULATES (a term's
meaning is its distribution across sources, so each source adds to what is there rather than
replacing a slice), day bounds widen rather than move, the rows are per tenant (I1), a
rebuild reproduces the table byte-identically after any amount of double counting, and a
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

    # re-indexing the same source double counts (the write path adds) …
    await component.on_source_indexed(str(user), first)
    doubled = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    assert doubled[("阿宝", "im:u_hw")]["sources"] == 3
    # … and the rebuild is what makes that safe: it starts from nothing and re-derives L0
    await component.rebuild(str(user))
    assert await pg_store.people_terms(user) == list(rows.values())


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

    # a re-index doubles the new column with the rest, and the rebuild re-derives all of it
    await component.on_source_indexed(str(user), _source(user, "arc-v1", _mixed_turns(12)))
    doubled = {(r["term"], r["target_identity"]): r for r in await pg_store.people_terms(user)}
    assert doubled[(term_key(VENDOR), "im:u_hw")]["non_vocative"] == 9
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
