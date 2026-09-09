"""RecallHandoffStore port — a question handed over without an answer, waiting for one.

`pkc recall --evidence` gives the Steward the fast lane's assembled context and makes no
answering call (docs/design/coding-agent-mode.md §5.1). A consultation cannot be written at
that moment: `ConsultationRecord` is frozen and `is_miss` reads `answer_kind`, so a record
written before the answer exists would either be rewritten later — which a kept record is
never — or would state a miss the lane never observed.

So the hand-over is kept HERE instead, and it is not a consultation: it is the material one
would be built from — the question, the instant, the library ref sampled as the lane samples
it, the lane's own evidence manifest and its query-local handle map, and the visitor class the
caller asked for. `pkc consult answer <handoff_id>` reads it back, builds the record through
the fast lane's own builder and emits it down the path `/recall` uses; the row is deleted at
that point. A question the Steward never answered therefore leaves NO consultation at all —
which is the honest outcome, and is stated in the design rather than hidden behind a
fabricated miss.

The CLI also retains the rendered reader text, header, page size and original JSON payload
in this state. `pkc recall --evidence --handoff <id> --page N` serves that result without
retrieval or another handoff. Silent calls retain pages on the same terms; retention is
independent of consultation recording and ends with the handoff's deletion or expiry.

Ephemeral like a draft and for the same reason (I2): neither an authority nor a kept record.
A row nobody came back to expires under `PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL`, swept by the
same startup self-heal that sweeps abandoned drafts. `user_id` comes first on every method
(I1); the shipped implementation keeps it in Postgres beside the consultations it may become.
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
