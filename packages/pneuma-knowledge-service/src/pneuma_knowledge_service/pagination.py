"""Opaque, context-bound cursors for keyset-paginated API collections."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any


class CursorError(ValueError):
    """The cursor is malformed or belongs to another collection context."""


def encode_cursor(
    *,
    collection: str,
    user_id: str,
    filters: dict[str, str | None],
    position: dict[str, str],
) -> str:
    payload = {
        "v": 1,
        "collection": collection,
        "user_id": user_id,
        "filters": filters,
        "position": position,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(
    token: str,
    *,
    collection: str,
    user_id: str,
    filters: dict[str, str | None],
) -> dict[str, str]:
    if not token:
        raise CursorError("cursor must not be empty")
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        )
        payload: Any = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor is malformed") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise CursorError("cursor version is unsupported")
    expected = {
        "collection": collection,
        "user_id": user_id,
        "filters": filters,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise CursorError("cursor does not belong to this collection context")

    position = payload.get("position")
    if (
        not isinstance(position, dict)
        or not position
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in position.items())
    ):
        raise CursorError("cursor position is malformed")
    return position
