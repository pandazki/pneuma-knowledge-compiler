"""The `time` component's projection table against the live compose postgres.

What only a real PG can prove: the schema applies, the day range scan is inclusive at both
ends and keyed per tenant (I1), a re-derivation replaces a source's rows wholesale, and the
FK cascade takes the projection with the source it belongs to.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)


def _normalized(user, source_id: str, *, title: str = "四月记录", blocks: int = 3):
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=user,
        kind="im",
        source_class="workstream",
        title=title,
        mime="text/plain",
        checksum=f"chk-{source_id}",
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        meta={"occurred_on": "2026-04-12"},
    )
    body = [
        NormalizedBlock(index=i, text=f"第{i}段", section_path=["2026-04-12"])
        for i in range(blocks)
    ]
    return NormalizedSource(
        raw=raw,
        blocks=body,
        structure=StructureMap(
            sections=[SectionSpan(path=["2026-04-12"], start_block=0, end_block=blocks - 1)]
        ),
    )


def _rows(days: list[tuple[int, str]], *, zone: str = "Asia/Shanghai"):
    return [
        {
            "block_index": index,
            "instant_utc": datetime.fromisoformat(f"{day}T01:00:00+00:00"),
            "local_day": date.fromisoformat(day),
            "zone": zone,
            "zone_source": "profile",
            "source_zone": "Europe/Berlin",
            "kind": "im",
        }
        for index, day in days
    ]


async def test_rows_round_trip_and_the_day_range_is_inclusive_at_both_ends(pg_store, user):
    await pg_store.add(user, _normalized(user, "s-time-1"))
    written = await pg_store.put_time_blocks(
        user,
        SourceId("s-time-1"),
        _rows([(0, "2026-04-11"), (1, "2026-04-12"), (2, "2026-04-13")]),
    )
    assert written == 3

    inside = await pg_store.time_blocks_in_range(user, date(2026, 4, 11), date(2026, 4, 13))
    assert [r["block_index"] for r in inside] == [0, 1, 2]
    assert inside[0]["title"] == "四月记录" and inside[0]["kind"] == "im"
    assert inside[0]["zone"] == "Asia/Shanghai" and inside[0]["zone_source"] == "profile"
    assert inside[0]["source_zone"] == "Europe/Berlin"

    narrow = await pg_store.time_blocks_in_range(user, date(2026, 4, 12), date(2026, 4, 12))
    assert [r["block_index"] for r in narrow] == [1]

    assert await pg_store.time_blocks_in_range(user, date(2026, 5, 1), date(2026, 5, 31)) == []


async def test_a_re_derivation_replaces_the_sources_rows_wholesale(pg_store, user):
    await pg_store.add(user, _normalized(user, "s-time-2"))
    await pg_store.put_time_blocks(
        user, SourceId("s-time-2"), _rows([(0, "2026-04-11"), (1, "2026-04-12")])
    )
    # A shorter derivation must not leave the previous tail behind as a phantom day.
    await pg_store.put_time_blocks(user, SourceId("s-time-2"), _rows([(0, "2026-04-11")]))

    rows = await pg_store.time_blocks_in_range(user, date(2026, 1, 1), date(2026, 12, 31))
    assert [r["block_index"] for r in rows] == [0]

    # Idempotent: writing the same rows again changes nothing.
    await pg_store.put_time_blocks(user, SourceId("s-time-2"), _rows([(0, "2026-04-11")]))
    assert len(await pg_store.time_blocks_in_range(user, date(2026, 1, 1), date(2026, 12, 31))) == 1


async def test_the_earliest_day_lookup_answers_only_for_the_sources_asked_for(pg_store, user):
    await pg_store.add(user, _normalized(user, "s-time-3"))
    await pg_store.add(user, _normalized(user, "s-time-4"))
    await pg_store.put_time_blocks(
        user, SourceId("s-time-3"), _rows([(0, "2026-04-13"), (1, "2026-04-11")])
    )
    await pg_store.put_time_blocks(user, SourceId("s-time-4"), _rows([(0, "2026-06-01")]))

    days = await pg_store.time_days_for_sources(user, ["s-time-3", "s-time-5"])
    assert days == {"s-time-3": "2026-04-11"}
    assert await pg_store.time_days_for_sources(user, []) == {}


async def test_the_projection_is_per_tenant_and_a_rebuild_can_drop_it(pg_store, user):
    other = UserId(f"{user}-x")
    await pg_store.add(user, _normalized(user, "s-time-6"))
    await pg_store.add(other, _normalized(other, "s-time-7"))
    await pg_store.put_time_blocks(user, SourceId("s-time-6"), _rows([(0, "2026-04-11")]))
    await pg_store.put_time_blocks(other, SourceId("s-time-7"), _rows([(0, "2026-04-11")]))

    # I1: one tenant's range scan never sees another's rows.
    mine = await pg_store.time_blocks_in_range(user, date(2026, 4, 1), date(2026, 4, 30))
    assert [r["source_id"] for r in mine] == ["s-time-6"]

    assert await pg_store.delete_time_blocks(user) == 1
    assert await pg_store.time_blocks_in_range(user, date(2026, 4, 1), date(2026, 4, 30)) == []
    # …and the other tenant is untouched.
    assert len(await pg_store.time_blocks_in_range(other, date(2026, 4, 1), date(2026, 4, 30))) == 1

    await pg_store.delete_user(other)


async def test_deleting_a_user_takes_the_projection_with_it(pg_store, user):
    await pg_store.add(user, _normalized(user, "s-time-8"))
    await pg_store.put_time_blocks(user, SourceId("s-time-8"), _rows([(0, "2026-04-11")]))
    await pg_store.delete_user(user)
    assert await pg_store.time_blocks_in_range(user, date(2026, 4, 1), date(2026, 4, 30)) == []


async def test_deep_timeline_excludes_archived_source_blocks(pg_store, user):
    """A component reads L0 as L0 STANDS (docs/design/archive.md §4).

    The deep tool returns verbatim prose, so the framework's assembly filter — which works
    over claims, windows and spans — cannot take an archived source's block text back out
    of a rendered timeline. The exclusion therefore lives in the query, and the component
    never learns that the archive exists (invariant I7).
    """
    from types import SimpleNamespace

    from pneuma_knowledge_service.components.time import TimeComponent

    await pg_store.add(user, _normalized(user, "s-time-live", title="活着的四月记录"))
    await pg_store.add(user, _normalized(user, "s-time-gone", title="退役的四月记录"))
    await pg_store.put_time_blocks(user, SourceId("s-time-live"), _rows([(0, "2026-04-12")]))
    await pg_store.put_time_blocks(user, SourceId("s-time-gone"), _rows([(0, "2026-04-12")]))

    class _UserInfo:
        async def get_profile(self, user_id):
            return SimpleNamespace(
                locale=SimpleNamespace(
                    timezone="Asia/Shanghai", timezone_history=[]
                )
            )

    component = TimeComponent(
        content=pg_store,
        canonical=None,
        user_info=_UserInfo(),
        default_timezone="UTC",
    )

    both = await component.timeline(user, since="2026-04-01", until="2026-04-30")
    assert "活着的四月记录" in both and "退役的四月记录" in both

    await pg_store.set_source_archived(user, SourceId("s-time-gone"), True)

    # The projection still HOLDS the archived source's rows — it is derived from all of L0
    # and rebuilt from all of it — but the read no longer answers with them.
    after = await component.timeline(user, since="2026-04-01", until="2026-04-30")
    assert "活着的四月记录" in after
    assert "退役的四月记录" not in after
    assert [r["source_id"] for r in await pg_store.time_blocks_in_range(
        user, date(2026, 4, 1), date(2026, 4, 30)
    )] == ["s-time-live"]

    # …and unarchiving brings it back: the query is the only thing that ever hid it.
    await pg_store.set_source_archived(user, SourceId("s-time-gone"), False)
    assert "退役的四月记录" in await component.timeline(
        user, since="2026-04-01", until="2026-04-30"
    )
