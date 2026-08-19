"""Official image declarations become immutable, tenant-scoped L0 objects."""

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_service.media_ingest import materialize_contract_images


class RecordingMediaStore:
    def __init__(self) -> None:
        self.puts: list[tuple[UserId, bytes, str, str]] = []

    async def put(
        self,
        user_id: UserId,
        data: bytes,
        *,
        sha256: str,
        mime_type: str,
    ) -> str:
        self.puts.append((user_id, data, sha256, mime_type))
        return f"tenants/opaque/images/{sha256}"


async def test_inline_image_is_verified_stored_and_keeps_derived_text():
    contract = parse_source_contract(
        {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "a-images",
            "owner_user_ids": ["U1"],
            "users": [{"user_id": "U1", "display_name": "Test User"}],
            "conversations": [
                {
                    "conversation_id": "C1",
                    "conversation_type": "dm",
                    "title": "Notes",
                    "member_ids": ["U1"],
                    "messages": [
                        {
                            "message_id": "1.1",
                            "sender_id": "U1",
                            "sent_at": "2026-07-28T11:00:00+08:00",
                            "text": "Latest layout",
                            "images": [
                                {
                                    "image_id": "img-layout",
                                    "mime_type": "image/png",
                                    "source": {
                                        "type": "base64",
                                        "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                                        "sha256": "431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460",
                                    },
                                    "derived": [
                                        {
                                            "kind": "caption",
                                            "text": "Three project columns.",
                                            "producer": "fixture-captioner",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    store = RecordingMediaStore()

    result = await materialize_contract_images(
        store, UserId("tenant-a"), contract, max_bytes=1024
    )

    assert store.puts == [
        (
            UserId("tenant-a"),
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
            ),
            "431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460",
            "image/png",
        )
    ]
    assert result["img-layout"].storage_key.startswith("tenants/opaque/images/")
    assert result["img-layout"].size_bytes == 68
    assert result["img-layout"].derived[0].text == "Three project columns."


async def test_inline_image_rejects_bytes_that_do_not_match_declared_mime():
    contract = parse_source_contract(
        {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "a-images",
            "owner_user_ids": ["U1"],
            "users": [{"user_id": "U1", "display_name": "Test User"}],
            "conversations": [
                {
                    "conversation_id": "C1",
                    "conversation_type": "dm",
                    "title": "Notes",
                    "member_ids": ["U1"],
                    "messages": [
                        {
                            "message_id": "1.1",
                            "sender_id": "U1",
                            "sent_at": "2026-07-28T11:00:00+08:00",
                            "text": "Not really an image",
                            "images": [
                                {
                                    "image_id": "img-fake",
                                    "mime_type": "image/png",
                                    "source": {
                                        "type": "base64",
                                        "data": "aW1hZ2UtYnl0ZXM=",
                                        "sha256": "2c8648d103e3dd7ad87660da0f126a1443b6d21ac1bd3ec000c5e24e2373a90c",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    try:
        await materialize_contract_images(
            RecordingMediaStore(), UserId("tenant-a"), contract, max_bytes=1024
        )
    except ValueError as exc:
        assert "does not match declared MIME type" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("invalid image bytes must be rejected")
