from __future__ import annotations

import pytest
from pneuma_knowledge_service.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_roundtrip_binds_collection_user_and_filters():
    filters = {"query": "alpha", "kind": "document"}
    token = encode_cursor(
        collection="sources",
        user_id="u-a",
        filters=filters,
        position={"created_at": "2026-07-20T10:00:00+00:00", "id": "sid-2"},
    )

    assert decode_cursor(
        token,
        collection="sources",
        user_id="u-a",
        filters=filters,
    ) == {"created_at": "2026-07-20T10:00:00+00:00", "id": "sid-2"}


@pytest.mark.parametrize(
    ("token", "collection", "user_id", "filters"),
    [
        ("not-base64", "sources", "u-a", {}),
        ("", "sources", "u-a", {}),
    ],
)
def test_malformed_cursor_fails_closed(token, collection, user_id, filters):
    with pytest.raises(CursorError):
        decode_cursor(
            token,
            collection=collection,
            user_id=user_id,
            filters=filters,
        )


@pytest.mark.parametrize(
    ("collection", "user_id", "filters"),
    [
        ("jobs", "u-a", {"query": "alpha"}),
        ("sources", "u-b", {"query": "alpha"}),
        ("sources", "u-a", {"query": "beta"}),
    ],
)
def test_cursor_cannot_be_reused_in_another_context(collection, user_id, filters):
    token = encode_cursor(
        collection="sources",
        user_id="u-a",
        filters={"query": "alpha"},
        position={"created_at": "2026-07-20T10:00:00+00:00", "id": "sid-2"},
    )

    with pytest.raises(CursorError):
        decode_cursor(
            token,
            collection=collection,
            user_id=user_id,
            filters=filters,
        )
