"""Ephemeral recall handoffs: retained evidence prose and query-local handles.

`pkc recall --evidence` records an immutable consultation opening immediately for business
and audit visitors. This store separately retains the state needed to page the evidence and
resolve an answer's handles. `pkc consult answer` appends the answer event once under the
handoff id, then deletes the handoff. It never rewrites the kept opening.

An unanswered handoff expires under `PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL`; expiry removes
only this ephemeral state, never the consultation, which remains explicitly unanswered.
Silent calls retain evidence on the same terms but record neither consultation event.
Every read is tenant-scoped (I1). Retained paging performs no new retrieval or recording.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from ..domain.ids import UserId


class RecallHandoffStore(Protocol):
    async def create(
        self, user_id: UserId, handoff_id: str, state: dict[str, Any]
    ) -> None:
        """Record one hand-over. `handoff_id` is system-assigned by the caller."""
        ...

    async def get(self, user_id: UserId, handoff_id: str) -> dict[str, Any] | None:
        """The pending hand-over, or None when it never existed or has been answered."""
        ...

    async def delete(self, user_id: UserId, handoff_id: str) -> None:
        """Drop it. Idempotent: a hand-over already answered is not an error."""
        ...

    async def list_pending(self, user_id: UserId) -> list[tuple[str, dict[str, Any]]]:
        """`(handoff_id, state)` for every hand-over this user has not answered, newest
        first — what `pkc consult pending` shows and what a Steward resuming a session
        needs to find the question it walked away from."""
        ...

    async def sweep(self, older_than: datetime) -> int:
        """Delete every hand-over created before `older_than`; return how many. Global
        rather than per-user for the same reason the queue's self-heal is: it runs at
        startup, when nothing is legitimately in flight."""
        ...
