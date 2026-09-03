"""An owner dialogue takes the ordinary road: import → index → L0 verbatim + L1 hit.

The ruling is only worth anything if the statement is a source like the others, so this
test asserts exactly what an `im/v1` import asserts and nothing more: the bundle expands,
L0 comes back verbatim by section, L1 finds the owner's words, and no other tenant can see
either (I1). If any of that needed a special case, the contract would be a write path in
disguise.
"""

import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs


def _open(url: str, default: int) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or default), timeout=1.5
        ):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            client.app = app
            yield client


@pytest.fixture
async def client():
    settings = Settings()
    if not (
        _open(settings.pg_dsn, 5432)
        and _open(settings.meili_url, 7700)
        and _open(settings.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(settings)) as value:
        yield value


DIALOGUE = {
    "schema": "pneuma.source.owner-dialogue/v1",
    "provider": "console",
    "dialogue_id": "dlg-it-1",
    "owner_id": "app-owner-mei",
    "steward_id": "app-steward-1",
    "turns": [
        {
            "turn_id": "t1",
            "role": "owner",
            "said_at": "2026-08-31T09:00:00+08:00",
            "text": "Aurora 的交付日期改到 2026-09-30 了。",
        },
        {
            "turn_id": "t2",
            "role": "steward",
            "said_at": "2026-08-31T09:00:20+08:00",
            "text": "收到，库里现在记的是 2026-09-15。",
        },
        {
            "turn_id": "t3",
            "role": "owner",
            "said_at": "2026-08-31T09:00:40+08:00",
            "text": "对，评审那天定的日子已经不作数。",
        },
    ],
}


async def test_an_owner_dialogue_round_trips_like_any_other_source(client):
    uid = f"u-it-owner-dlg-{uuid.uuid4().hex[:10]}"
    other = f"u-it-owner-dlg-{uuid.uuid4().hex[:10]}"
    user, stranger = UserId(uid), UserId(other)
    base = f"/v1/users/{uid}"
    ctx = client.app.state.ctx
    try:
        response = await client.post(f"{base}/sources/import", json=DIALOGUE)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["contract_schema"] == "pneuma.source.owner-dialogue/v1"
        # One statement is one source: there is no expansion boundary inside a dialogue.
        assert len(body["sources"]) == 1
        source_id = body["sources"][0]["source_id"]
        assert body["sources"][0]["deduplicated"] is False
        # Full canonical treatment, so a compile job is queued beside the index job.
        assert body["sources"][0]["intake_plan"]["canonical_treatment"] == "full"

        listed = (await client.get(f"{base}/sources")).json()["items"]
        assert [(item["kind"], item["origin"]) for item in listed] == [
            ("owner_dialogue", "console")
        ]

        assert await drain_index_jobs(ctx, user) == 1

        # L0 — verbatim, by the section the statement's own day cut (I3).
        fetched = await client.post(
            f"{base}/sources/{source_id}/fetch",
            json={"locator": {"section": ["2026-08-31"]}},
        )
        assert fetched.status_code == 200, fetched.text
        text = fetched.json()["text"]
        assert "Aurora 的交付日期改到 2026-09-30 了。" in text
        # The role is the label; the application's ids never entered the text.
        assert "app-owner-mei" not in text and "app-steward-1" not in text

        # L1 — the owner's words are findable without a compile having run (I3).
        hits = await ctx.lexical.search(user, "交付日期", limit=10)
        assert any(str(hit.source_id) == source_id for hit in hits)

        # I1 — the statement belongs to one tenant and to no other.
        assert not await ctx.lexical.search(stranger, "交付日期", limit=10)
        with pytest.raises(KeyError):
            await ctx.store.get(stranger, SourceId(source_id))
        assert (await client.get(f"/v1/users/{other}/sources")).json()["items"] == []

        # Content-addressed like every other contract: a replay deduplicates.
        again = await client.post(f"{base}/sources/import", json=DIALOGUE)
        assert again.status_code == 200, again.text
        assert again.json()["sources"][0]["deduplicated"] is True
        assert again.json()["sources"][0]["source_id"] == source_id
    finally:
        for tenant in (user, stranger):
            await ctx.store.delete_user(tenant)
            await ctx.lexical.delete_user(tenant)
            await ctx.vectors.delete_user(tenant)
