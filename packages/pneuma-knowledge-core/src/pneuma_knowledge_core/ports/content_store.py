"""ContentStore port — L0 raw content authority (architecture.md §3, §6).

`fetch` returns verbatim text (L0): the raw bytes of the addressed block span,
never a summary. L0 reachability is unconditional (invariant I3).
"""

from __future__ import annotations

from typing import Protocol

from ..domain.ids import UserId, SourceId
from ..domain.source import Locator, NormalizedSource, RawSource


class ContentStore(Protocol):
    async def add(
        self, user_id: UserId, source: NormalizedSource
    ) -> SourceId: ...

    async def get(
        self, user_id: UserId, source_id: SourceId
    ) -> NormalizedSource: ...

    async def list(self, user_id: UserId) -> list[RawSource]: ...

    async def fetch(
        self, user_id: UserId, source_id: SourceId, locator: Locator
    ) -> str:
        """Return verbatim L0 text for the addressed block span."""
        ...
