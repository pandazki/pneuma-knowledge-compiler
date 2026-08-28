"""Reading a stored briefing back: the pack itself on the wire, and only to its owner.

A briefing is the frozen text every answer in an Ask thread is grounded in, so the reader has
to be able to open it — otherwise the pack is a char count and a promise. Two properties are
worth pinning:

  * the response carries the text VERBATIM (the literal system prefix, byte for byte) plus the
    scope and snapshot it was built under, so what is displayed is what the model was handed;
  * a briefing_id is not a capability — asked for under another user_id it is simply not there
    (404, never someone else's pack). That is I1 on this route.

The store is stubbed at the port, keyed by (user_id, briefing_id): a stub that ignored the
user would make the 404 assertion vacuous.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.api.app import create_app

OWNER = "u-briefing-owner"
OTHER = "u-briefing-stranger"
BRIEFING_ID = "b0ffee"
PACK = "# Briefing\n\nc:0001 — the kayak trip moved to Sunday. [cite: s-1 ¶2-3]\n"


class _Store:
    """Only `get_briefing`, and it is user-scoped exactly as Postgres' WHERE clause is."""

    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._rows = rows
        self.asked: list[tuple[str, str]] = []

    async def get_briefing(
        self, user_id: UserId, briefing_id: str
    ) -> dict[str, Any] | None:
        self.asked.append((str(user_id), briefing_id))
        return self._rows.get((str(user_id), briefing_id))


def _store() -> _Store:
    return _Store(
        {
            (OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {
                    "query": "kayak weekend",
                    "source_ids": ["s-1"],
                    "budget_chars": 4000,
                },
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": datetime(2026, 8, 26, 10, 15, tzinfo=UTC),
            }
        }
    )


def _client(store: _Store) -> httpx.AsyncClient:
    app = create_app()
    app.state.ctx = SimpleNamespace(store=store)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_a_briefing_reads_back_with_its_text_verbatim():
    store = _store()
    async with _client(store) as client:
        response = await client.get(f"/v1/users/{OWNER}/briefings/{BRIEFING_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["briefing_id"] == BRIEFING_ID
    assert body["snapshot_ref"] == "9f1c2d"
    # Byte for byte: the panel shows the pack, not a rendering of it.
    assert body["text"] == PACK
    assert body["char_count"] == len(PACK)
    assert body["scope"] == {
        "query": "kayak weekend",
        "source_ids": ["s-1"],
        "budget_chars": 4000,
    }
    assert body["created_at"].startswith("2026-08-26T10:15")


@pytest.mark.asyncio
async def test_another_users_briefing_id_is_not_a_way_in():
    store = _store()
    async with _client(store) as client:
        response = await client.get(f"/v1/users/{OTHER}/briefings/{BRIEFING_ID}")

    assert response.status_code == 404
    assert BRIEFING_ID in response.json()["detail"]
    # The lookup was made under the asking user, not the briefing's owner.
    assert store.asked == [(OTHER, BRIEFING_ID)]


@pytest.mark.asyncio
async def test_a_briefing_that_never_existed_is_the_same_404():
    async with _client(_store()) as client:
        response = await client.get(f"/v1/users/{OWNER}/briefings/nope")
    assert response.status_code == 404
