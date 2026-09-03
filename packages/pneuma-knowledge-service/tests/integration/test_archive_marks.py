"""The archive's two marks and the three derived filters, against live middleware.

docs/design/archive.md. The mark on L0 is a column (`sources.archived_at`); the mark in
canonical is a path prefix. Everything below is what the derived layers do with them, and
the property under test is always the same one: the DEFAULT excludes the archive, the
exception is stated, and a row or point written before the field existed still reads as LIVE.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    ConversationTurn,
    NormalizedBlock,
    RawSource,
)
from pneuma_knowledge_core.ingest.adapters import (
    PlainConversationAdapter,
    PlainConversationInput,
)
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from pneuma_knowledge_service.adapters.meilisearch import _index_uid


def _normalized(user, source_id: str, checksum: str, *, title: str = "t"):
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=user,
        kind="conversation",
        source_class="workstream",
        title=title,
        mime="text/plain",
        checksum=checksum,
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        intake_plan={"canonical_treatment": "full", "semantic_indexing": "full"},
    )
    turns = [
        ConversationTurn(speaker="A", text="Aurora 的交付节奏"),
        ConversationTurn(speaker="B", text="Aurora 的付款条款"),
    ]
    return PlainConversationAdapter().normalize(
        PlainConversationInput(raw=raw, turns=turns)
    )


# ============================================================== L0: sources.archived_at


async def test_the_l0_mark_round_trips_and_leaves_reachability_alone(pg_store, user):
    await pg_store.add(user, _normalized(user, "sid-live", "chk-live"))
    await pg_store.add(user, _normalized(user, "sid-old", "chk-old"))

    assert await pg_store.archived_source_ids(user) == frozenset()
    assert all(raw.archived_at is None for raw in await pg_store.list(user))

    stamped = await pg_store.set_source_archived(user, SourceId("sid-old"), True)
    assert stamped is not None

    assert await pg_store.archived_source_ids(user) == frozenset(
        {SourceId("sid-old")}
    )
    by_id = {raw.source_id: raw for raw in await pg_store.list(user)}
    # I3: the authority's own enumeration hides nothing, and the value round-trips.
    assert set(by_id) == {SourceId("sid-live"), SourceId("sid-old")}
    assert by_id[SourceId("sid-old")].archived_at == stamped
    assert by_id[SourceId("sid-live")].archived_at is None

    # …and so does fetch by address: an archived source still answers verbatim.
    fetched = await pg_store.get(user, SourceId("sid-old"))
    assert fetched.raw.archived_at == stamped
    assert await pg_store.fetch(user, SourceId("sid-old"), {"blocks": [0, 0]})

    cleared = await pg_store.set_source_archived(user, SourceId("sid-old"), False)
    assert cleared is None
    assert await pg_store.archived_source_ids(user) == frozenset()


async def test_the_listing_excludes_the_archive_unless_the_call_says_otherwise(
    pg_store, user
):
    await pg_store.add(user, _normalized(user, "sid-1", "chk-1", title="live"))
    await pg_store.add(user, _normalized(user, "sid-2", "chk-2", title="retired"))
    await pg_store.set_source_archived(user, SourceId("sid-2"), True)

    rows, total, _ = await pg_store.list_sources_page(user, limit=10)
    assert [r.source_id for r in rows] == [SourceId("sid-1")]
    assert total == 1  # the count applies the same predicate as the page

    rows, total, _ = await pg_store.list_sources_page(
        user, limit=10, include_archived=True
    )
    assert {r.source_id for r in rows} == {SourceId("sid-1"), SourceId("sid-2")}
    assert total == 2
    # Every row carries the mark either way, so a caller can label what it shows.
    assert {r.source_id: r.archived_at is not None for r in rows} == {
        SourceId("sid-1"): False,
        SourceId("sid-2"): True,
    }


async def test_an_archived_source_is_not_offered_to_compile_again(pg_store, user):
    await pg_store.add(user, _normalized(user, "sid-a", "chk-a"))
    await pg_store.add(user, _normalized(user, "sid-b", "chk-b"))
    assert set(await pg_store.undigested_source_ids(user)) == {"sid-a", "sid-b"}

    await pg_store.set_source_archived(user, SourceId("sid-b"), True)
    assert await pg_store.undigested_source_ids(user) == ["sid-a"]


# =========================================================== the kept proposal record


async def test_archive_proposals_are_kept_and_advance_without_losing_earlier_stages(
    pg_store, user
):
    pid = f"ap-{uuid.uuid4().hex[:8]}"
    await pg_store.create_archive_proposal(
        user,
        pid,
        action="archive",
        seeds={"documents": ["work/products/aurora.md"], "sources": []},
        items=[
            {
                "kind": "document",
                "ref": "work/products/aurora.md",
                "role": "seed",
                "selected": True,
                "reason": {},
            }
        ],
        library_ref="sha-head",
        note="Aurora shipped in June.",
        statement_ref="src-owner-1",
    )

    row = await pg_store.get_archive_proposal(user, pid)
    assert row["action"] == "archive"
    assert row["status"] == "proposed"
    assert row["library_ref"] == "sha-head"
    assert row["note"] == "Aurora shipped in June."
    assert row["statement_ref"] == "src-owner-1"
    assert row["seeds"]["documents"] == ["work/products/aurora.md"]
    assert [i["ref"] for i in row["items"]] == ["work/products/aurora.md"]
    assert row["confirmed_at"] is None and row["executed_at"] is None

    confirmed_at = datetime.now(timezone.utc)
    await pg_store.update_archive_proposal(
        user,
        pid,
        status="confirmed",
        items=[
            {
                "kind": "document",
                "ref": "work/products/aurora.md",
                "role": "seed",
                "selected": False,  # the Owner narrowed the set
                "reason": {},
            }
        ],
        confirmed_at=confirmed_at,
        job_id="job-1",
    )
    await pg_store.update_archive_proposal(
        user, pid, status="executed", executed_at=datetime.now(timezone.utc)
    )

    row = await pg_store.get_archive_proposal(user, pid)
    assert row["status"] == "executed"
    # The later stage did not blank what the earlier one recorded.
    assert row["confirmed_at"] is not None
    assert row["job_id"] == "job-1"
    assert row["items"][0]["selected"] is False
    assert row["seeds"]["documents"] == ["work/products/aurora.md"]

    assert [r["proposal_id"] for r in await pg_store.list_archive_proposals(user)] == [
        pid
    ]
    assert await pg_store.get_archive_proposal(user, "no-such-proposal") is None


async def test_the_lifecycle_predicate_lets_exactly_one_writer_win(pg_store, user):
    """`expected_status` is evaluated by the row lock, which is the whole point.

    Two confirms, or a confirm racing a drop, both READ `proposed` — the read cannot decide
    between them. Appended to the WHERE clause, the predicate lets exactly one UPDATE match:
    the loser writes nothing and is told so by `rowcount`, so only one archive job is ever
    queued for one move and a drop never closes a proposal that now has one.
    """
    pid = f"ap-{uuid.uuid4().hex[:8]}"
    await pg_store.create_archive_proposal(
        user,
        pid,
        action="archive",
        seeds={"documents": [], "sources": []},
        items=[],
        library_ref="sha-head",
        note=None,
        statement_ref=None,
    )

    won = await pg_store.update_archive_proposal(
        user,
        pid,
        status="confirmed",
        confirmed_at=datetime.now(timezone.utc),
        expected_status="proposed",
    )
    assert won is True

    # The racing confirm and the racing drop both lose, and neither touches the row.
    assert (
        await pg_store.update_archive_proposal(
            user, pid, status="confirmed", job_id="job-2", expected_status="proposed"
        )
        is False
    )
    assert (
        await pg_store.update_archive_proposal(
            user, pid, status="dropped", expected_status="proposed"
        )
        is False
    )
    row = await pg_store.get_archive_proposal(user, pid)
    assert row["status"] == "confirmed"
    assert row["job_id"] is None  # the loser's write landed nowhere

    # Without the predicate the statement is unconditional — the caller that is not racing
    # anyone can still ask for it. (The job's terminal writes do NOT: they pass
    # `expected_status='confirmed'`, so a finished job never overwrites a row that moved
    # under it.)
    assert (
        await pg_store.update_archive_proposal(
            user, pid, status="executed", executed_at=datetime.now(timezone.utc)
        )
        is True
    )
    assert (await pg_store.get_archive_proposal(user, pid))["status"] == "executed"

    # A predicate that matches no row at all (wrong proposal) is a loss, not an error.
    assert (
        await pg_store.update_archive_proposal(
            user, "ap-nonexistent", status="dropped", expected_status="proposed"
        )
        is False
    )


async def test_the_confirm_writes_the_decision_and_its_job_in_one_transaction(
    pg_store, user
):
    """The row and the job commit together, or neither does.

    Two statements would have to be ordered and both orders leave a state nothing can
    reconcile: a `confirmed` proposal with no job is a decision nothing executes and nothing
    reports, and a job with no confirmed proposal is a mover for a decision nobody made. So
    the flip and the INSERT are one transaction, and the id is minted once for both — which
    is asserted here against the real `compile_jobs` row, not a fake queue.
    """
    pid = f"ap-{uuid.uuid4().hex[:8]}"
    await pg_store.create_archive_proposal(
        user,
        pid,
        action="archive",
        seeds={"documents": ["work/products/aurora.md"], "sources": []},
        items=[{"kind": "document", "ref": "work/products/aurora.md", "selected": True}],
        library_ref="sha-head",
        note="the plan's note",
        statement_ref=None,
    )

    job_id = await pg_store.confirm_archive_proposal(
        user,
        pid,
        items=[
            {"kind": "document", "ref": "work/products/aurora.md", "selected": False}
        ],
        job_kind="archive",
        payload={"proposal_id": pid},
        note="Aurora shipped.",
    )
    assert job_id is not None

    row = await pg_store.get_archive_proposal(user, pid)
    assert row["status"] == "confirmed"
    assert row["job_id"] == job_id  # one id, in both rows
    assert row["confirmed_at"] is not None
    assert row["items"][0]["selected"] is False  # the Owner's narrowing was kept
    assert row["note"] == "Aurora shipped."  # …and their reason, typed at the decision
    assert row["library_ref"] == "sha-head"  # untouched: it identifies the plan's state

    # The job is really on the queue the worker drains, under the id the row records.
    claimed = await pg_store.claim_next(user)
    assert claimed is not None
    assert (claimed.job_id, claimed.kind, claimed.payload) == (
        job_id,
        "archive",
        {"proposal_id": pid},
    )
    await pg_store.complete(user, job_id, ok=True, detail="done")


async def test_a_confirm_stores_a_cleared_note_as_cleared(pg_store, user):
    """`COALESCE` cannot spell an erasure, so the store is told which one it is.

    Silence and "the Owner deleted what they typed" both arrive as a NULL parameter. Read as
    silence, the second left the plan's old note standing while the confirm's own preview had
    already been computed without it — and the record then quoted the note the console had
    replaced. `note_given` is the flag that lets NULL be written on purpose.
    """
    ids = [f"ap-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    for pid in ids:
        await pg_store.create_archive_proposal(
            user,
            pid,
            action="archive",
            seeds={"documents": [], "sources": []},
            items=[],
            library_ref="sha-head",
            note="the plan's note",
        )

    # 1. cleared: the Owner emptied the box, and the row says so.
    assert await pg_store.confirm_archive_proposal(
        user, ids[0], items=[], job_kind="archive", payload={"proposal_id": ids[0]},
        note=None, note_given=True,
    )
    assert (await pg_store.get_archive_proposal(user, ids[0]))["note"] is None

    # 2. silent: nothing was said about the note, so the plan's stands.
    assert await pg_store.confirm_archive_proposal(
        user, ids[1], items=[], job_kind="archive", payload={"proposal_id": ids[1]},
    )
    assert (await pg_store.get_archive_proposal(user, ids[1]))["note"] == "the plan's note"

    # 3. replaced.
    assert await pg_store.confirm_archive_proposal(
        user, ids[2], items=[], job_kind="archive", payload={"proposal_id": ids[2]},
        note="Aurora shipped.", note_given=True,
    )
    assert (await pg_store.get_archive_proposal(user, ids[2]))["note"] == "Aurora shipped."

    # And the same three states on the lifecycle statement beside it.
    assert await pg_store.update_archive_proposal(
        user, ids[2], status="confirmed", note=None, note_given=True
    )
    assert (await pg_store.get_archive_proposal(user, ids[2]))["note"] is None
    assert await pg_store.update_archive_proposal(user, ids[1], status="confirmed")
    assert (await pg_store.get_archive_proposal(user, ids[1]))["note"] == "the plan's note"


async def test_a_confirm_that_loses_the_predicate_queues_nothing_at_all(pg_store, user):
    """The losing half of "one decision, one job", against the real table.

    Two confirms in flight both READ `proposed`; only the WHERE clause can decide between
    them. The loser must not merely fail to move the row — it must leave no job behind
    either, or one move would be executed twice.
    """
    pid = f"ap-{uuid.uuid4().hex[:8]}"
    await pg_store.create_archive_proposal(
        user,
        pid,
        action="archive",
        seeds={"documents": [], "sources": []},
        items=[],
        library_ref="sha-head",
    )
    first = await pg_store.confirm_archive_proposal(
        user, pid, items=[], job_kind="archive", payload={"proposal_id": pid}
    )
    assert first is not None

    second = await pg_store.confirm_archive_proposal(
        user, pid, items=[], job_kind="archive", payload={"proposal_id": pid}
    )
    assert second is None
    # The row still names the winner's job, and the queue holds exactly one archive job.
    row = await pg_store.get_archive_proposal(user, pid)
    assert row["job_id"] == first
    jobs = [
        job
        for job in await pg_store.list_jobs(user)
        if job["kind"] == "archive" and (job["payload"] or {}).get("proposal_id") == pid
    ]
    assert [job["job_id"] for job in jobs] == [first]

    # A drop that got there first is the same shape from the other side: nothing queued.
    other = f"ap-{uuid.uuid4().hex[:8]}"
    await pg_store.create_archive_proposal(
        user,
        other,
        action="archive",
        seeds={"documents": [], "sources": []},
        items=[],
        library_ref="sha-head",
    )
    await pg_store.update_archive_proposal(
        user, other, status="dropped", expected_status="proposed"
    )
    assert (
        await pg_store.confirm_archive_proposal(
            user, other, items=[], job_kind="archive", payload={"proposal_id": other}
        )
        is None
    )
    assert not [
        job
        for job in await pg_store.list_jobs(user)
        if (job["payload"] or {}).get("proposal_id") == other
    ]


async def test_the_confirm_is_scoped_to_one_user(pg_store):
    """I1, at the statement that mints a job: another tenant's proposal is simply not
    there, so the confirm writes nothing and queues nothing."""
    mine = UserId(f"u-confirm-mine-{uuid.uuid4().hex[:6]}")
    theirs = UserId(f"u-confirm-theirs-{uuid.uuid4().hex[:6]}")
    try:
        pid = f"ap-{uuid.uuid4().hex[:8]}"
        await pg_store.create_archive_proposal(
            theirs,
            pid,
            action="archive",
            seeds={"documents": [], "sources": []},
            items=[],
            library_ref="sha-head",
        )
        assert (
            await pg_store.confirm_archive_proposal(
                mine, pid, items=[], job_kind="archive", payload={"proposal_id": pid}
            )
            is None
        )
        assert (await pg_store.get_archive_proposal(theirs, pid))["status"] == "proposed"
        assert await pg_store.list_jobs(mine) == []
    finally:
        await pg_store.delete_user(mine)
        await pg_store.delete_user(theirs)


async def test_deleting_a_user_takes_their_archive_proposals_with_it(pg_store):
    victim = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    await pg_store.create_archive_proposal(
        victim,
        "ap-doomed",
        action="unarchive",
        seeds={},
        items=[],
        library_ref="sha",
        note=None,
        statement_ref=None,
    )
    await pg_store.delete_user(victim)
    assert await pg_store.list_archive_proposals(victim) == []


# ================================================================= L1: Meilisearch


async def test_meili_default_search_keeps_legacy_documents_and_drops_the_archive(meili):
    """The empirical fact the whole L1 filter rests on.

    Three block documents: one with NO `archived` attribute (what every document written
    before this field existed looks like), one `archived=True`, one `archived=False`. The
    default search must return the first and the third — a legacy document reads as LIVE.
    """
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    # Written straight through the client with NO `archived` key — exactly the document a
    # build before the archive existed produced. `add_documents` replaces wholesale, so the
    # key is genuinely absent rather than merged away.
    raw_index = await meili._ensure_index(_index_uid(user))
    task = await raw_index.add_documents(
        [
            {
                "id": "sid-legacy_0",
                "source_id": "sid-legacy",
                "block_index": 0,
                "text": "Aurora 交付节奏 legacy",
            }
        ],
        primary_key="id",
    )
    await meili._client.wait_for_task(task.task_uid)

    await meili.index_blocks(
        user,
        SourceId("sid-archived"),
        [NormalizedBlock(index=0, text="Aurora 交付节奏 archived")],
        archived=True,
    )
    await meili.index_blocks(
        user,
        SourceId("sid-live"),
        [NormalizedBlock(index=0, text="Aurora 交付节奏 live")],
        archived=False,
    )

    default = await meili.search(user, "Aurora 交付节奏", limit=10)
    assert {h.source_id for h in default} == {
        SourceId("sid-legacy"),
        SourceId("sid-live"),
    }

    everything = await meili.search(
        user, "Aurora 交付节奏", limit=10, include_archived=True
    )
    assert {h.source_id for h in everything} == {
        SourceId("sid-legacy"),
        SourceId("sid-archived"),
        SourceId("sid-live"),
    }

    await meili.delete_user(user)


async def test_meili_flips_one_source_without_touching_its_text(meili):
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    blocks = [
        NormalizedBlock(index=0, text="Aurora 的交付节奏"),
        NormalizedBlock(index=1, text="Aurora 的付款条款"),
    ]
    await meili.index_blocks(user, SourceId("sid-x"), blocks)
    await meili.index_blocks(
        user, SourceId("sid-y"), [NormalizedBlock(index=0, text="Aurora 的运维排班")]
    )

    await meili.set_source_archived(user, SourceId("sid-x"), len(blocks), True)

    default = await meili.search(user, "Aurora", limit=10)
    assert {h.source_id for h in default} == {SourceId("sid-y")}
    everything = await meili.search(user, "Aurora", limit=10, include_archived=True)
    # The verbatim text is untouched by the flip — a partial update, not a re-index.
    assert {h.text for h in everything if h.source_id == SourceId("sid-x")} == {
        "Aurora 的交付节奏",
        "Aurora 的付款条款",
    }

    await meili.set_source_archived(user, SourceId("sid-x"), len(blocks), False)
    back = await meili.search(user, "Aurora", limit=10)
    assert {h.source_id for h in back} == {SourceId("sid-x"), SourceId("sid-y")}

    await meili.delete_user(user)


def _claim(path: str, anchor: str, text: str, *, archived: bool) -> ProjectedClaim:
    return ProjectedClaim(
        anchor=AnchorId(anchor),
        document_path=path,
        section_path=("Facts",),
        text=text,
        citations=(),
        archived=archived,
    )


async def test_meili_claims_exclude_the_archive_by_default(meili):
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    await meili.index_claims(
        user,
        [
            _claim("work/products/aurora.md", "aa11", "Aurora 已交付", archived=False),
            _claim(
                "archive/work/products/borealis.md",
                "bb22",
                "Borealis 已交付",
                archived=True,
            ),
        ],
    )

    default = await meili.search_claims(user, "已交付", limit=10)
    assert [h.anchor for h in default] == ["aa11"]

    everything = await meili.search_claims(
        user, "已交付", limit=10, include_archived=True
    )
    assert {h.anchor for h in everything} == {"aa11", "bb22"}

    # A sync that only flips the flag still reaches the index.
    await meili.sync_claims(
        user,
        [_claim("work/products/aurora.md", "aa11", "Aurora 已交付", archived=True)],
        [],
    )
    assert await meili.search_claims(user, "已交付", limit=10) == []

    await meili.delete_user(user)


# ==================================================================== L2: Qdrant


def _chunk(source_id: str, text: str, embedding: list[float]) -> EmbeddedChunk:
    return EmbeddedChunk(
        source_id=SourceId(source_id),
        block_start=0,
        block_end=0,
        char_start=0,
        char_end=len(text),
        text=text,
        embedding=embedding,
        representation="raw",
    )


async def test_qdrant_archives_one_source_of_a_tenant_and_brings_it_back(
    qdrant, embeddings
):
    """Identical vectors for two sources of ONE user, so anything the default search drops
    it dropped by the archive filter and not by vector distance."""
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    shared_text = "Aurora 的交付节奏与付款条款"
    vec = await embeddings.aembed_query(shared_text)

    await qdrant.upsert_chunks(user, [_chunk("src-live", shared_text, vec)])
    await qdrant.upsert_chunks(user, [_chunk("src-old", shared_text, vec)])

    assert {h.source_id for h in await qdrant.search(user, vec, limit=10)} == {
        SourceId("src-live"),
        SourceId("src-old"),
    }

    await qdrant.set_source_archived(user, SourceId("src-old"), True)

    assert {h.source_id for h in await qdrant.search(user, vec, limit=10)} == {
        SourceId("src-live")
    }
    assert {
        h.source_id
        for h in await qdrant.search(user, vec, limit=10, include_archived=True)
    } == {SourceId("src-live"), SourceId("src-old")}
    # The flip re-embedded nothing: the point still carries its verbatim text.
    everything = await qdrant.search(user, vec, limit=10, include_archived=True)
    assert {h.text for h in everything} == {shared_text}

    await qdrant.set_source_archived(user, SourceId("src-old"), False)
    assert {h.source_id for h in await qdrant.search(user, vec, limit=10)} == {
        SourceId("src-live"),
        SourceId("src-old"),
    }

    await qdrant.delete_user(user)


async def test_qdrant_points_written_before_the_flag_existed_read_as_live(
    qdrant, embeddings
):
    """`must_not archived = true` and not `must archived = false`: a legacy point has no
    `archived` key, does not match the condition, and stays searchable."""
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    text = "Aurora 的历史点位"
    vec = await embeddings.aembed_query(text)
    await qdrant.upsert_chunks(user, [_chunk("src-legacy", text, vec)])
    # Strip the key, reproducing exactly what a pre-archive build wrote.
    await qdrant._client.delete_payload(
        qdrant._collection,
        keys=["archived"],
        points=qdrant._chunk_layer_filter(user),
        wait=True,
    )

    assert {h.source_id for h in await qdrant.search(user, vec, limit=10)} == {
        SourceId("src-legacy")
    }

    await qdrant.delete_user(user)


async def test_qdrant_claim_layer_excludes_the_archive_by_default(qdrant, embeddings):
    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    live = _claim("work/products/aurora.md", "aa11", "Aurora 已交付", archived=False)
    archived = _claim(
        "archive/work/products/borealis.md", "bb22", "Borealis 已交付", archived=True
    )
    vec = await embeddings.aembed_query("已交付")
    await qdrant.upsert_claims(user, [live, archived], [vec, vec])

    assert [h.anchor for h in await qdrant.search_claims(user, vec, limit=10)] == [
        "aa11"
    ]
    assert {
        h.anchor
        for h in await qdrant.search_claims(user, vec, limit=10, include_archived=True)
    } == {"aa11", "bb22"}

    # A source-addressed flip must never reach the claim layer: a claim's archive state is
    # a property of its DOCUMENT's path.
    await qdrant.set_source_archived(user, SourceId("src-anything"), True)
    assert [h.anchor for h in await qdrant.search_claims(user, vec, limit=10)] == [
        "aa11"
    ]

    await qdrant.delete_user(user)


async def test_ensure_collection_declares_payload_indexes_on_an_existing_collection(
    qdrant, settings, embeddings
):
    """The early return this replaced is why a deployment that already had a collection
    would never have gained the archive index — the one that most needs it."""
    from qdrant_client import AsyncQdrantClient, models
    from pneuma_knowledge_service.adapters.qdrant import QdrantVectorIndex

    collection = f"pneuma_archive_index_{uuid.uuid4().hex}"
    bare = AsyncQdrantClient(url=settings.qdrant_url)
    store = QdrantVectorIndex(settings.qdrant_url, 3, collection=collection)
    try:
        # A collection created WITHOUT any of the payload indexes — the legacy shape.
        await bare.create_collection(
            collection,
            vectors_config=models.VectorParams(
                size=3, distance=models.Distance.COSINE
            ),
        )
        assert not (await bare.get_collection(collection)).payload_schema

        await store.ensure_collection()

        schema = (await bare.get_collection(collection)).payload_schema
        assert {"user_id", "source_id", "archived", "layer"} <= set(schema)

        # Idempotent: a second boot re-declares them without failing.
        await store.ensure_collection()
    finally:
        await store.aclose()
        await bare.delete_collection(collection)
        await bare.close()


async def test_a_search_only_process_configures_an_index_an_older_build_created(
    settings, meili
):
    """The failure this guards: Meilisearch REFUSES a filter on an unconfigured attribute,
    and `search` turns that refusal into an empty result — the whole L1 lane going quiet
    with nothing to read about it. The API process may never index anything, so it cannot
    rely on the write path having declared the settings."""
    from meilisearch_python_sdk.models.settings import MeilisearchSettings
    from pneuma_knowledge_service.adapters.meilisearch import MeiliLexicalIndex

    user = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
    writer = MeiliLexicalIndex(settings.meili_url, settings.meili_key)
    reader = MeiliLexicalIndex(settings.meili_url, settings.meili_key)
    try:
        # An index carrying the settings a build BEFORE the archive declared.
        uid = _index_uid(user)
        task = await writer._client.index(uid).update_settings(
            MeilisearchSettings(
                searchable_attributes=["text"],
                displayed_attributes=["source_id", "block_index", "text"],
            )
        )
        await writer._client.wait_for_task(task.task_uid)
        writer._configured.add(uid)  # …and a process that believes it is configured
        await writer.index_blocks(
            user,
            SourceId("sid-1"),
            [NormalizedBlock(index=0, text="Aurora 的交付节奏")],
        )

        # A separate process, fresh memo, that only ever searches.
        hits = await reader.search(user, "Aurora", limit=10)
        assert [h.source_id for h in hits] == [SourceId("sid-1")]

        # And a user with no index at all answers empty without CREATING one.
        stranger = UserId(f"u-it-{uuid.uuid4().hex[:12]}")
        assert await reader.search(stranger, "Aurora", limit=10) == []
        assert await reader.search_claims(stranger, "Aurora", limit=10) == []
        indexes = {i.uid for i in await reader._client.get_indexes() or []}
        assert _index_uid(stranger) not in indexes
    finally:
        await writer.delete_user(user)
        await writer.aclose()
        await reader.aclose()
