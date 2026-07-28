"""ProjectionStore port — derived projections/annotations (architecture.md §5, §6).

Everything here is derived (invariant I2): fully rebuildable from canonical +
raw content. Keyed by user_id (I1).
"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.ids import DocumentId, UserId


class ProjectionStore(Protocol):
    async def read(
        self, user_id: UserId, document_id: DocumentId
    ) -> dict[str, Any] | None: ...

    async def write(
        self,
        user_id: UserId,
        document_id: DocumentId,
        projection: dict[str, Any],
    ) -> None: ...
