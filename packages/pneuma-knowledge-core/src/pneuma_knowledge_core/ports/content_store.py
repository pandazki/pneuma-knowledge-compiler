"""ContentStore port — L0 raw content authority (architecture.md §3, §6).

`fetch` returns verbatim text (L0): the raw bytes of the addressed block span,
never a summary. L0 reachability is unconditional (invariant I3).
"""

from __future__ import annotations

from datetime import datetime
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

    async def list_since(
        self, user_id: UserId, *, after: tuple[datetime, str] | None = None
    ) -> list[RawSource]:
        """This user's sources after a `(created_at, source_id)` watermark, oldest first.

        The incremental face of `list`, for the readers that fold every source into a mirror
        once and then only need what arrived since — a component's per-job refresh, say. The
        cursor is the pair, never the timestamp alone: sources imported in one batch share a
        wall clock, and a timestamp-only cursor drops all but one of them for good.

        `created_at` is the INGEST clock (`domain/source.py`), stamped when the source is
        written, so it only moves forward; the material's own day lives in
        `meta.occurred_on` and is not a cursor. `after=None` is the whole library — the same
        answer `list` gives, in the cursor's order.
        """
        ...

    async def fetch(
        self, user_id: UserId, source_id: SourceId, locator: Locator
    ) -> str:
        """Return verbatim L0 text for the addressed block span."""
        ...
