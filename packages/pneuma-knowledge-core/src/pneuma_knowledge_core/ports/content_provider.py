"""ContentProvider port — read-only abstraction over a future external content
microservice (architecture.md §6). Fetch by ref; no write path.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.ids import UserId


class ContentProvider(Protocol):
    async def fetch(self, user_id: UserId, ref: str) -> bytes: ...
