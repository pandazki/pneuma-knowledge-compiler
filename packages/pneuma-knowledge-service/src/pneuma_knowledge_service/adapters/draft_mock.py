"""In-memory `DraftStore` and job queue — the keyless stand-ins the draft tests run on.

The shipped implementations are Postgres (`adapters/postgres.py`), and the rules they enforce
— one row per job, per-user single-in-flight, a claim that names who holds it — are rules the
`pkc draft` lifecycle depends on rather than incidental storage behaviour. So they are
implemented once more here, in memory, with the SAME semantics, and the default (keyless)
suite exercises the lifecycle against these; the Postgres tier re-checks the same claims
against real SQL when middleware is reachable.

Nothing here is a production path: no persistence, no locking beyond a dict, and no attempt
to be fast.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class InMemoryDraftStore:
    """`DraftStore` (core `ports/draft_store.py`) over a dict, keyed `(user_id, job_id)`."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._stamps: dict[tuple[str, str], datetime] = {}

    async def get(self, user_id, job_id: str) -> dict[str, Any] | None:  # noqa: ANN001
        row = self._rows.get((str(user_id), job_id))
        return dict(row) if row is not None else None

    async def put(self, user_id, job_id: str, state: dict[str, Any]) -> None:  # noqa: ANN001
        key = (str(user_id), job_id)
        self._rows[key] = dict(state)
        self._stamps[key] = datetime.now(timezone.utc)

    async def delete(self, user_id, job_id: str) -> None:  # noqa: ANN001
        key = (str(user_id), job_id)
        self._rows.pop(key, None)
        self._stamps.pop(key, None)

    async def list_open(self, user_id) -> list[str]:  # noqa: ANN001
        return [
            job_id
            for (uid, job_id), _ in sorted(self._stamps.items(), key=lambda kv: -kv[1].timestamp())
            if uid == str(user_id)
        ]

    async def list_stale(self, older_than: datetime) -> list[tuple[str, str]]:
        return [key for key, at in sorted(self._stamps.items()) if at < older_than]


class _Job:
    """The `Job` protocol as an attribute bag (`ports/job_queue.py`)."""

    def __init__(self, job_id: str, user_id, kind: str, payload: dict) -> None:  # noqa: ANN001
        self.job_id = job_id
        self.user_id = user_id
        self.kind = kind
        self.payload = payload
        self.status = "queued"


class InMemoryJobQueue:
    """A `JobQueue` with the two rules the canonical layer's single writer rests on:
    per-user serialization (nothing is handed out while that user has a job in flight) and a
    claim that records WHICH body holds it."""

    def __init__(self) -> None:
        self.jobs: list[_Job] = []
        self.completed: list[dict[str, Any]] = []
        self._seq = 0

    async def enqueue(self, user_id, kind: str, payload: dict) -> str:  # noqa: ANN001
        self._seq += 1
        job = _Job(f"job-{self._seq:02d}", user_id, kind, dict(payload))
        self.jobs.append(job)
        return job.job_id

    def _in_flight(self, user_id) -> bool:  # noqa: ANN001
        return any(
            j.status == "claimed" and str(j.user_id) == str(user_id) for j in self.jobs
        )

    async def claim_next(  # noqa: ANN001
        self, user_id, *, claimed_by: str = "worker", exclude_kinds=()
    ):
        if self._in_flight(user_id):
            return None
        skip = {k for k in exclude_kinds if k}
        for job in self.jobs:
            if (
                job.status == "queued"
                and str(job.user_id) == str(user_id)
                and job.kind not in skip
            ):
                job.status = "claimed"
                job.claimed_by = claimed_by
                return job
        return None

    async def claim(self, user_id, job_id: str, *, claimed_by: str = "worker"):  # noqa: ANN001
        if self._in_flight(user_id):
            return None
        for job in self.jobs:
            if (
                job.job_id == job_id
                and job.status == "queued"
                and str(job.user_id) == str(user_id)
            ):
                job.status = "claimed"
                job.claimed_by = claimed_by
                return job
        return None

    async def list_jobs(self, user_id) -> list[dict[str, Any]]:  # noqa: ANN001
        """This user's jobs, newest first — the shape `PostgresStore.list_jobs` returns, and
        the peek a drain uses to see what it is leaving behind."""
        return [
            {
                "job_id": job.job_id,
                "kind": job.kind,
                "payload": dict(job.payload),
                "status": job.status,
            }
            for job in reversed(self.jobs)
            if str(job.user_id) == str(user_id)
        ]

    async def get_job(self, user_id, job_id: str):  # noqa: ANN001
        for job in self.jobs:
            if job.job_id == job_id and str(job.user_id) == str(user_id):
                return job
        return None

    async def release(self, user_id, job_id: str) -> None:  # noqa: ANN001
        for job in self.jobs:
            if (
                job.job_id == job_id
                and str(job.user_id) == str(user_id)
                and job.status == "claimed"
            ):
                job.status = "queued"

    async def complete(  # noqa: ANN001
        self,
        user_id,
        job_id: str,
        *,
        ok: bool = True,
        detail: str | None = None,
        snapshot_ref: str | None = None,
        token_usage: dict[str, int] | None = None,
        executor: str | None = None,
    ) -> None:
        for job in self.jobs:
            if job.job_id == job_id and str(job.user_id) == str(user_id):
                job.status = "done"
        self.completed.append(
            {
                "user_id": str(user_id),
                "job_id": job_id,
                "ok": ok,
                "detail": detail,
                "snapshot_ref": snapshot_ref,
                "token_usage": token_usage,
                "executor": executor,
            }
        )


    async def record_job_usage(  # noqa: ANN001
        self,
        user_id,
        job_id: str,
        *,
        token_usage: dict[str, int] | None = None,
        executor: str | None = None,
    ) -> None:
        """What the unattended launcher measured, added to an already-finished job row."""
        for record in self.completed:
            if record["job_id"] == job_id and record["user_id"] == str(user_id):
                if token_usage is not None:
                    record["token_usage"] = dict(token_usage)
                if executor is not None:
                    record["executor"] = executor


class InMemoryRecallHandoffStore:
    """`RecallHandoffStore` (core `ports/recall_handoff_store.py`) over a dict.

    Same shape as the draft store above and for the same reason: what the hand-over rules
    are — one row per id, deleted on answer, swept by age — is behaviour `pkc consult answer`
    depends on rather than incidental storage, so the keyless suite exercises it here and the
    Postgres tier re-checks the same claims against real SQL.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._stamps: dict[tuple[str, str], datetime] = {}

    async def create(self, user_id, handoff_id: str, state: dict[str, Any]) -> None:  # noqa: ANN001
        key = (str(user_id), handoff_id)
        self._rows[key] = dict(state)
        self._stamps.setdefault(key, datetime.now(timezone.utc))

    async def get(self, user_id, handoff_id: str) -> dict[str, Any] | None:  # noqa: ANN001
        row = self._rows.get((str(user_id), handoff_id))
        return dict(row) if row is not None else None

    async def delete(self, user_id, handoff_id: str) -> None:  # noqa: ANN001
        key = (str(user_id), handoff_id)
        self._rows.pop(key, None)
        self._stamps.pop(key, None)

    async def list_pending(self, user_id) -> list[tuple[str, dict[str, Any]]]:  # noqa: ANN001
        return [
            (handoff_id, dict(self._rows[(uid, handoff_id)]))
            for (uid, handoff_id), _ in sorted(
                self._stamps.items(), key=lambda kv: -kv[1].timestamp()
            )
            if uid == str(user_id)
        ]

    async def sweep(self, older_than: datetime) -> int:
        stale = [key for key, at in self._stamps.items() if at < older_than]
        for key in stale:
            self._rows.pop(key, None)
            self._stamps.pop(key, None)
        return len(stale)


__all__ = [
    "InMemoryDraftStore",
    "InMemoryJobQueue",
    "InMemoryRecallHandoffStore",
]
