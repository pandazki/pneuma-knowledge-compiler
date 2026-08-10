"""A citation address resolves to original image bytes and labelled representations."""

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    BlockImage,
    DerivedMediaText,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_service.api.app import create_app


class Store:
    async def get(self, user_id: UserId, source_id: SourceId) -> NormalizedSource:
        if user_id != UserId("tenant-a") or source_id != SourceId("source-image"):
            raise KeyError("source not found")
        return NormalizedSource(
            raw=RawSource(
                source_id=source_id,
                user_id=user_id,
                kind="im",
                origin="mock",
                title="Design thread",
                mime="application/vnd.pneuma.im+json",
                checksum="checksum",
                created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ),
            blocks=[
                NormalizedBlock(
                    index=0,
                    text="Alex: latest layout",
                    images=[
                        BlockImage(
                            image_id="img-layout",
                            mime_type="image/png",
                            sha256="2c8648d103e3dd7ad87660da0f126a1443b6d21ac1bd3ec000c5e24e2373a90c",
                            size_bytes=11,
                            storage_key="tenant-a/image",
                            derived=[
                                DerivedMediaText(
                                    kind="caption",
                                    text="Three project columns.",
                                    producer="fixture-captioner",
                                )
                            ],
                        )
                    ],
                )
            ],
            structure=StructureMap(),
        )


class Media:
    async def get(self, user_id: UserId, storage_key: str) -> bytes:
        assert user_id == UserId("tenant-a")
        assert storage_key == "tenant-a/image"
        return b"image-bytes"


async def test_source_detail_and_media_endpoint_share_the_block_citation_address():
    app = create_app()
    app.state.ctx = SimpleNamespace(store=Store(), media=Media())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get("/v1/users/tenant-a/sources/source-image")
        media = await client.get(
            "/v1/users/tenant-a/sources/source-image/blocks/0/images/img-layout"
        )

    assert detail.status_code == 200
    image = detail.json()["blocks"][0]["images"][0]
    assert image["image_id"] == "img-layout"
    assert image["derived"][0]["kind"] == "caption"
    assert image["derived"][0]["producer"] == "fixture-captioner"
    assert image["url"].endswith("/blocks/0/images/img-layout")
    assert "storage_key" not in image
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.content == b"image-bytes"
