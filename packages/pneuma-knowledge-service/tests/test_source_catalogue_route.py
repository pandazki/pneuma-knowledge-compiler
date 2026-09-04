"""The source catalogue page: corpus time on the wire, and a crawlable page ceiling.

Two properties the reading UI depends on and nothing else guarded:

  * `occurred_on` — the day the MATERIAL happened, carried through from `meta`. Without it
    the only date a catalogue row has is the ingest wall clock, and a backfill of half a
    year of capture reads as "everything happened the afternoon we imported it". A source
    that never got one comes back null: the reader says "ingest time" rather than pretending.
  * the `limit` ceiling — a reader that filters its whole inventory client-side pulls the
    catalogue in a handful of round trips. 500 must be accepted and 501 refused, so the
    budget stays a stated number instead of drifting.

The store is stubbed at the port: this is about what the route puts on the wire, and a real
Postgres would only slow the assertion down.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import RawSource
from pneuma_knowledge_service.api.app import create_app

USER = "u-catalogue"


def _raw(source_id: str, *, meta: dict[str, Any]) -> RawSource:
    return RawSource(
        source_id=SourceId(source_id),
        user_id=UserId(USER),
        kind="conversation",
        source_class="workstream",
        origin="context_stream",
        title=f"title {source_id}",
        mime="text/plain",
        checksum=f"sum-{source_id}",
        created_at=datetime(2026, 7, 30, 16, 5, tzinfo=UTC),
        meta=meta,
    )


class _Store:
    """Just the three port methods the catalogue route calls."""

    def __init__(self, raws: list[RawSource]) -> None:
        self._raws = raws
        self.limits: list[int] = []

    async def list_sources_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        before: tuple[datetime, str] | None = None,
        query: str | None = None,
        kind: str | None = None,
        include_archived: bool = False,
    ) -> tuple[list[RawSource], int, bool]:
        self.limits.append(limit)
        return list(self._raws), len(self._raws), False

    async def block_counts(self, user_id: UserId, source_ids: list[str]) -> dict[str, int]:
        return {sid: 3 for sid in source_ids}

    async def digested_map(
        self, user_id: UserId, source_ids: list[str]
    ) -> dict[str, str | None]:
        return {sid: None for sid in source_ids}


def _client(store: _Store) -> httpx.AsyncClient:
    app = create_app()
    app.state.ctx = SimpleNamespace(store=store)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_corpus_time_reaches_the_catalogue_row_and_absence_stays_visible():
    store = _Store(
        [
            _raw("s-dated", meta={"occurred_on": "2026-01-09"}),
            _raw("s-blank", meta={"occurred_on": "   "}),
            _raw("s-none", meta={}),
        ]
    )
    async with _client(store) as client:
        response = await client.get(f"/v1/users/{USER}/sources")

    assert response.status_code == 200
    rows = {row["source_id"]: row for row in response.json()["items"]}
    assert rows["s-dated"]["occurred_on"] == "2026-01-09"
    # A whitespace-only stamp is no stamp: it must not become a date the reader trusts.
    assert rows["s-blank"]["occurred_on"] is None
    assert rows["s-none"]["occurred_on"] is None
    # The ingest wall clock is still reported, and is still a different thing.
    assert rows["s-dated"]["created_at"].startswith("2026-07-30")


@pytest.mark.asyncio
async def test_the_page_ceiling_is_a_stated_crawl_budget():
    store = _Store([_raw("s-1", meta={})])
    async with _client(store) as client:
        assert (await client.get(f"/v1/users/{USER}/sources?limit=500")).status_code == 200
        assert (await client.get(f"/v1/users/{USER}/sources?limit=501")).status_code == 422
    assert store.limits == [500]
