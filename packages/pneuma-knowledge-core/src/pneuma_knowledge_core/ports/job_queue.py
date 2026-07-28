"""JobQueue port — compile task queue (ADR-001, §5, §6).

Backed by PG `FOR UPDATE SKIP LOCKED`, serialized per user_id (I1). This
per-user serialization is what guarantees single-writer semantics on the git
canonical layer while service/worker processes stay stateless.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.ids import UserId


class Job(Protocol):
    job_id: str
    user_id: UserId
    kind: str
    payload: dict[str, Any]


class JobQueue(Protocol):
    async def enqueue(
        self,
        user_id: UserId,
        kind: str,
        payload: dict[str, Any],
    ) -> str: ...

    async def claim_next(self, user_id: UserId) -> Job | None:
        """Claim the next per-user job (FOR UPDATE SKIP LOCKED, serial per user)."""
        ...

    async def complete(
        self,
        user_id: UserId,
        job_id: str,
        *,
        ok: bool = True,
        detail: str | None = None,
        snapshot_ref: str | None = None,
    ) -> None:
        """Mark a claimed job finished. `ok=False` records an aborted compile with its
        gate-violation `detail`; `snapshot_ref` is the resulting commit on success."""
        ...
