"""PG ContentStore + JobQueue against the live compose postgres."""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn, RawSource
from pneuma_knowledge_core.ingest.adapters import PlainConversationAdapter, PlainConversationInput


def _normalized(user, source_id: str, checksum: str):
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=user,
        kind="conversation",
        source_class="workstream",
        title="t",
        mime="text/plain",
        checksum=checksum,
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
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
