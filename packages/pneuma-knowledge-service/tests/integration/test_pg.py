"""PG ContentStore + JobQueue against the live compose postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn, RawSource
from pneuma_knowledge_core.ingest.adapters import PlainConversationAdapter, PlainConversationInput
from pneuma_knowledge_core.recall.projection import ProjectedClaim


def _normalized(
    user,
    source_id: str,
    checksum: str,
    *,
    title: str = "t",
    kind: str = "conversation",
    created_at: datetime | None = None,
):
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=user,
        kind=kind,
        source_class="workstream",
        title=title,
        mime="text/plain",
        checksum=checksum,
        created_at=created_at or datetime(2026, 7, 20, tzinfo=timezone.utc),
        intake_plan={"canonical_treatment": "full", "semantic_indexing": "full"},
    )
    turns = [
        ConversationTurn(speaker="A", text="第一段 合同 内容", at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)),
        ConversationTurn(speaker="B", text="第二段 付款 条款", at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)),
        ConversationTurn(speaker="A", text="次の日の話", at=datetime(2026, 7, 21, 9, tzinfo=timezone.utc)),
    ]
    return PlainConversationAdapter().normalize(PlainConversationInput(raw=raw, turns=turns))


async def test_roundtrip_and_intake_plan_persists(pg_store, user):
    src = _normalized(user, "sid-a", "chk-a")
    sid = await pg_store.add(user, src)
    assert sid == SourceId("sid-a")

    got = await pg_store.get(user, sid)
    assert [b.text for b in got.blocks] == [b.text for b in src.blocks]
    assert got.raw.intake_plan == {"canonical_treatment": "full", "semantic_indexing": "full"}

    listed = await pg_store.list(user)
    assert [r.source_id for r in listed] == [SourceId("sid-a")]
    assert listed[0].intake_plan["semantic_indexing"] == "full"


async def test_dedup_same_checksum_returns_existing_source(pg_store, user):
    first = await pg_store.add(user, _normalized(user, "sid-1", "same-chk"))
    second = await pg_store.add(user, _normalized(user, "sid-2", "same-chk"))
    assert first == SourceId("sid-1")
    assert second == SourceId("sid-1")  # append-only: second is deduped to the first
    assert len(await pg_store.list(user)) == 1


async def test_fetch_l0_by_section_and_block_locator(pg_store, user):
    await pg_store.add(user, _normalized(user, "sid-f", "chk-f"))
    # Section = one calendar date; 2026-07-20 covers blocks 0..1.
    by_section = await pg_store.fetch(user, SourceId("sid-f"), {"section": ["2026-07-20"]})
    assert by_section == "A: 第一段 合同 内容\nB: 第二段 付款 条款"
    # Explicit block interval.
    by_blocks = await pg_store.fetch(user, SourceId("sid-f"), {"blocks": [2, 2]})
    assert by_blocks == "A: 次の日の話"


async def test_job_queue_enqueue_claim_complete_serial_per_user(pg_store, user):
    j1 = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-1"]})
    await pg_store.enqueue(user, "compile", {"source_ids": ["sid-2"]})

    claimed = await pg_store.claim_next(user)
    assert claimed is not None and claimed.job_id == j1
    assert claimed.payload == {"source_ids": ["sid-1"]}

    # Serial per user: a second claim is blocked while one is in flight.
    assert await pg_store.claim_next(user) is None

    await pg_store.complete(user, j1)
    second = await pg_store.claim_next(user)
    assert second is not None and second.kind == "compile"


async def test_source_pages_are_bounded_stable_filtered_and_user_scoped(pg_store, user):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    for index, title in enumerate(
        ["Alpha brief", "Beta notes", "Alpha decision", "Gamma log", "Alpha mail"]
    ):
        await pg_store.add(
            user,
            _normalized(
                user,
                f"sid-page-{index}",
                f"chk-page-{index}",
                title=title,
                kind="email" if index == 4 else "document",
                created_at=base + timedelta(days=index),
            ),
        )

    page1, total, has_more = await pg_store.list_sources_page(user, limit=2)
    assert total == 5
    assert has_more is True
    assert [str(row.source_id) for row in page1] == ["sid-page-4", "sid-page-3"]

    last = page1[-1]
    page2, total2, has_more2 = await pg_store.list_sources_page(
        user,
        limit=2,
        before=(last.created_at, str(last.source_id)),
    )
    assert total2 == 5
    assert has_more2 is True
    assert [str(row.source_id) for row in page2] == ["sid-page-2", "sid-page-1"]
    assert {row.source_id for row in page1}.isdisjoint(row.source_id for row in page2)

    filtered, filtered_total, filtered_more = await pg_store.list_sources_page(
        user,
        limit=10,
        query="alpha",
        kind="document",
    )
    assert filtered_total == 2
    assert filtered_more is False
    assert [row.title for row in filtered] == ["Alpha decision", "Alpha brief"]

    other = type(user)(f"{user}-other")
    await pg_store.add(
        other,
        _normalized(
            other,
            "sid-page-other",
            "chk-page-other",
            title="Alpha private",
            kind="document",
            created_at=base + timedelta(days=20),
        ),
    )
    isolated, isolated_total, _ = await pg_store.list_sources_page(user, limit=10)
    assert isolated_total == 5
    assert all(row.user_id == user for row in isolated)


async def test_job_pages_are_bounded_filtered_and_do_not_repeat(pg_store, user):
    job_ids = [
        await pg_store.enqueue(
            user,
            "index" if index % 2 == 0 else "compile",
            {"source_ids": [f"sid-{index}"]},
        )
        for index in range(7)
    ]
    await pg_store.complete(user, job_ids[0], ok=True)
    await pg_store.complete(user, job_ids[1], ok=False, detail="expected test failure")

    page1, total, has_more = await pg_store.list_jobs_page(user, limit=3)
    assert total == 7
    assert has_more is True
    assert len(page1) == 3

    last = page1[-1]
    page2, total2, has_more2 = await pg_store.list_jobs_page(
        user,
        limit=3,
        before=(last["created_at"], last["job_id"]),
    )
    assert total2 == 7
    assert has_more2 is True
    assert {row["job_id"] for row in page1}.isdisjoint(
        row["job_id"] for row in page2
    )

    queued, queued_total, queued_more = await pg_store.list_jobs_page(
        user,
        limit=10,
        status="queued",
        kind="index",
    )
    assert queued_total == 3
    assert queued_more is False
    assert all(row["status"] == "queued" and row["kind"] == "index" for row in queued)


async def test_workspace_counts_are_derived_in_one_user_scope(pg_store, user):
    await pg_store.add(user, _normalized(user, "sid-count", "chk-count"))
    await pg_store.enqueue(user, "index", {"source_ids": ["sid-count"]})
    await pg_store.replace_canonical_claims(
        user,
        "snapshot-count",
        [
            ProjectedClaim(
                anchor=AnchorId("a001"),
                document_path="work/products/a.md",
                section_path=("范围",),
                text="事实 A",
            ),
            ProjectedClaim(
                anchor=AnchorId("a002"),
                document_path="work/products/a.md",
                section_path=("范围",),
                text="事实 B",
            ),
            ProjectedClaim(
                anchor=AnchorId("b001"),
                document_path="work/products/b.md",
                section_path=("决定",),
                text="事实 C",
            ),
        ],
    )

    assert await pg_store.workspace_counts(user) == {
        "sources": 1,
        "jobs": 1,
        "documents": 2,
        "claims": 3,
    }

    other = type(user)(f"{user}-counts-other")
    await pg_store.add(other, _normalized(other, "sid-other-count", "chk-other-count"))
    assert await pg_store.workspace_counts(user) == {
        "sources": 1,
        "jobs": 1,
        "documents": 2,
        "claims": 3,
    }


async def test_history_pages_merge_sources_jobs_and_patches_without_repeats(
    pg_store, user
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    for index in range(2):
        await pg_store.add(
            user,
            _normalized(
                user,
                f"sid-history-{index}",
                f"chk-history-{index}",
                created_at=base + timedelta(days=index),
            ),
        )

    first_job = await pg_store.enqueue(
        user, "compile", {"source_ids": ["sid-history-0"]}
    )
    await pg_store.complete(user, first_job, snapshot_ref="ref-history-1")
    await pg_store.record_compile_events(
        user,
        first_job,
        "ref-history-1",
        [
            {
                "type": "claim_added",
                "path": "work/products/a.md",
                "anchor": "a001",
                "after": "事实 A",
            }
        ],
    )
    await pg_store.enqueue(user, "index", {"source_ids": ["sid-history-1"]})
    await pg_store.enqueue(user, "compile", {"source_ids": ["sid-history-1"]})

    page1, counts, has_more = await pg_store.list_history_page(user, limit=3)
    assert counts == {"patches": 1, "jobs": 3, "snapshots": 2, "total": 6}
    assert len(page1) == 3
    assert has_more is True
    assert {row["kind"] for row in page1} <= {"patch", "job", "snapshot"}

    last = page1[-1]
    page2, counts2, has_more2 = await pg_store.list_history_page(
        user,
        limit=3,
        before=(last["ts"], last["kind"], last["ref"]),
    )
    assert counts2 == counts
    assert len(page2) == 3
    assert has_more2 is False
    assert {(row["kind"], row["ref"]) for row in page1}.isdisjoint(
        (row["kind"], row["ref"]) for row in page2
    )


async def test_user_profile_upsert_get_roundtrip(pg_store, user):
    # Never-set user: get returns None (mock fallback happens one layer up).
    assert await pg_store.get_user_profile(user) is None

    await pg_store.upsert_user_profile(user, {"display_name": "First", "industry": "tech"})
    assert await pg_store.get_user_profile(user) == {"display_name": "First", "industry": "tech"}

    # Upsert replaces the stored JSON.
    await pg_store.upsert_user_profile(user, {"display_name": "Second", "industry": "finance"})
    got = await pg_store.get_user_profile(user)
    assert got["display_name"] == "Second" and got["industry"] == "finance"

    # delete_user reaps the profile row too (test hygiene).
    await pg_store.delete_user(user)
    assert await pg_store.get_user_profile(user) is None
