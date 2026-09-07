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

from datetime import datetime
from typing import Any, Protocol

from ..domain.ids import UserId


class DraftStore(Protocol):
    async def get(self, user_id: UserId, job_id: str) -> dict[str, Any] | None:
        """This job's open draft state, or None when no round is open on it."""
        ...

    async def put(self, user_id: UserId, job_id: str, state: dict[str, Any]) -> None:
        """Write (or replace) this job's draft state. One row per job."""
        ...

    async def delete(self, user_id: UserId, job_id: str) -> None:
        """Drop this job's draft. Idempotent: a draft that is already gone is not an error."""
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
