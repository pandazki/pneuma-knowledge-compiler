"""MediaStore port — immutable binary L0 authority for block-aligned media."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ..domain.ids import UserId


class MediaStore(Protocol):
    async def put(
        self,
        user_id: UserId,
        data: bytes,
        *,
        sha256: str,
        mime_type: str,
    ) -> str:
        """Store verified bytes and return an opaque tenant-scoped object key."""
        ...

    async def get(self, user_id: UserId, storage_key: str) -> bytes:
        """Return immutable bytes after mechanically checking tenant ownership."""
        ...

    async def delete_user(self, user_id: UserId) -> None:
        """Delete every media object owned by one tenant."""
        ...

    async def copy_user(
        self,
        user_id: UserId,
        target_user_id: UserId,
        objects: Mapping[str, str],
    ) -> dict[str, str]:
        """Copy source keys to another tenant and return old-key to new-key mappings."""
        ...

    async def aclose(self) -> None:
        """Release adapter resources."""
        ...
