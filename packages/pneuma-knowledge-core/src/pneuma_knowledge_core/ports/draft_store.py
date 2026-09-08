"""DraftStore port — where an OPEN compile round lives between two commands.

The langchain executor needs nothing here: its round is one function call and its draft is a
local variable. A round driven from a command line has no memory between invocations, so the
draft and its session (`compile/patch.py`, `compile/session.py`) need a home for exactly as
long as the round is open (docs/design/coding-agent-mode.md ruling 3, §6).

What lives here is ephemeral by construction: it is neither an authority nor a kept record
(I2) — it is deleted when the round ends, whichever way it ends, and a round whose draft is
gone is a round that never happened. `user_id` comes first on every method (I1), and the
shipped implementation keeps it beside the job queue, so the per-user lock, the TTL and the
self-heal that govern jobs govern their drafts in the same place.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from ..domain.ids import UserId


@dataclass(frozen=True)
class DraftOwner:
    executor: str
    since: datetime
    updated_at: datetime
    worker_posture: str = ""

    @property
    def idle_seconds(self) -> int:
        return max(0, int((datetime.now(timezone.utc) - self.updated_at).total_seconds()))

    def refusal(self, door: str = "pkc draft") -> str:
        posture = f"; worker posture: {self.worker_posture}" if self.worker_posture else ""
        return (
            f"draft held by {self.executor or 'legacy:unknown'} since {self.since.isoformat()}, "
            f"idle {self.idle_seconds}s — wait for it to finish, or "
            f"`{door} abandon --take-over` when it is dead{posture}"
        )


class DraftOwnershipError(ValueError):
    """A command attempted to act on another executor's draft or a closed job."""


class DraftStore(Protocol):
    def lock(self, user_id: UserId) -> AbstractAsyncContextManager[None]:
        """Serialize a whole command, including its gate/commit, against takeover and expiry."""
        ...

    def launch(self, user_id: UserId, executor: str) -> AbstractAsyncContextManager[None]:
        """Hold a worker launch's liveness lease until its runner returns or dies."""
        ...

    async def worker_alive(self, user_id: UserId, executor: str) -> bool:
        """Whether this tenant's worker launch still holds its lease, across processes."""
        ...

    async def owner(self, user_id: UserId, job_id: str) -> DraftOwner | None:
        """The executor and store timestamps; legacy ownerless rows are never silently joined."""
        ...

    async def get(self, user_id: UserId, job_id: str) -> dict[str, Any] | None:
        """This job's open draft state, or None when no round is open on it."""
        ...

    async def put(self, user_id: UserId, job_id: str, state: dict[str, Any]) -> None:
        """Write this job's state, refusing replacement by a different session.executor.

        Owned drafts require a claimed job. A completed job can never acquire a new draft.
        """
        ...

    async def delete(self, user_id: UserId, job_id: str, *, executor: str = "") -> None:
        """Drop this job's draft. Idempotent: a draft that is already gone is not an error."""
        ...

    async def abandon(
        self, user_id: UserId, job_id: str, *, executor: str,
        take_over: bool = False, grace_seconds: int = 60,
    ) -> dict[str, Any] | None:
        """Atomically drop the draft and release its job, recording any takeover on the job.

        Another owner requires explicit takeover and either an expired grace or a dead
        worker lease. Returns the takeover audit, or None for ordinary abandonment.
        """
        ...

    async def list_open(self, user_id: UserId) -> list[str]:
        """The job ids this user currently holds a draft on.

        At most one in practice, and that is not this port's promise: the queue hands out one
        claimed job per user, so one open round per user is what the single-writer rule
        already means. It is a list because a store answers what it holds, not what the queue
        guarantees — and because it is what lets every command after `open` find the round
        without the agent having to repeat the job id it already claimed.
        """
        ...

    async def list_stale(self, older_than: datetime) -> list[tuple[str, str]]:
        """`(user_id, job_id)` for every draft not written since `older_than`.

        What the queue's self-heal asks before it decides a claimed job is orphaned: a draft
        younger than the TTL is an agent still holding its round, and an older one is a round
        nobody came back to.
        """
        ...
