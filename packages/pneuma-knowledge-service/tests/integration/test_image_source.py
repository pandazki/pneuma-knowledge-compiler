"""A real RustFS round trip keeps image L0 aligned with its citable message block."""

import base64
import hashlib
import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_service import kb_snapshots
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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


async def test_image_import_storage_manifest_and_private_byte_route_round_trip():
    settings = Settings()
    if not all(
        (
            _open(settings.pg_dsn, 5432),
            _open(settings.meili_url, 7700),
            _open(settings.qdrant_url, 6333),
            _open(settings.media_s3_endpoint_url, 9000),
        )
    ):
        pytest.skip("full middleware stack including RustFS unreachable")

    user = UserId(f"u-it-image-{uuid.uuid4().hex[:10]}")
    async with _client(create_app(settings)) as client:
        ctx = client.app.state.ctx
        base = f"/v1/users/{user}"
        snapshot = None
        payload = {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "image-round-trip",
            "owner_user_ids": ["owner"],
            "users": [{"user_id": "owner", "display_name": "Owner"}],
            "conversations": [
                {
                    "conversation_id": "visual-thread",
                    "conversation_type": "dm",
                    "title": "Visual thread",
                    "member_ids": ["owner"],
                    "messages": [
                        {
                            "message_id": "m1",
                            "sender_id": "owner",
                            "sent_at": "2026-08-10T10:00:00+08:00",
                            "text": "The referenced image belongs to this block.",
                            "images": [
                                {
                                    "image_id": "pixel",
                                    "mime_type": "image/png",
                                    "source": {
                                        "type": "base64",
                                        "data": base64.b64encode(PNG).decode("ascii"),
                                        "sha256": hashlib.sha256(PNG).hexdigest(),
                                    },
                                    "derived": [
                                        {
                                            "kind": "caption",
                                            "text": "A single test pixel.",
                                            "producer": "integration-fixture",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        try:
            imported = await client.post(f"{base}/sources/import", json=payload)
            assert imported.status_code == 200, imported.text
            source_id = imported.json()["sources"][0]["source_id"]

            detail = await client.get(f"{base}/sources/{source_id}")
            assert detail.status_code == 200, detail.text
            block = detail.json()["blocks"][0]
            assert block["index"] == 0
            assert block["images"][0]["derived"][0] == {
                "kind": "caption",
                "text": "A single test pixel.",
                "producer": "integration-fixture",
            }

            image = await client.get(block["images"][0]["url"])
            assert image.status_code == 200, image.text
            assert image.headers["content-type"] == "image/png"
            assert image.content == PNG

            snapshot = await kb_snapshots.create(ctx, user, "image round trip")
            ready = await kb_snapshots.run_copy(ctx, user, snapshot)
            assert ready.ready
            assert ready.counts["images"] == 1

            frozen = await ctx.store.get(ready.tenant_id, SourceId(source_id))
            assert frozen is not None
            live = await ctx.store.get(user, SourceId(source_id))
            assert live is not None
            frozen_image = frozen.blocks[0].images[0]
            live_image = live.blocks[0].images[0]
            assert frozen_image.storage_key != live_image.storage_key
            assert await ctx.media.get(
                ready.tenant_id, frozen_image.storage_key
            ) == PNG

            assert await kb_snapshots.delete(ctx, user, snapshot.snapshot_id)
            snapshot = None
            assert await ctx.media.get(user, live_image.storage_key) == PNG
        finally:
            if snapshot is not None:
                await kb_snapshots.delete(ctx, user, snapshot.snapshot_id)
            await ctx.media.delete_user(user)
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)
