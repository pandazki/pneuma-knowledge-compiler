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

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from pneuma_knowledge_core.ports.draft_store import DraftOwner, DraftOwnershipError

from .postgres import CLAIM_FIRST_KINDS


class InMemoryDraftStore:
    """`DraftStore` (core `ports/draft_store.py`) over a dict, keyed `(user_id, job_id)`."""

    def __init__(self, jobs=None) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._stamps: dict[tuple[str, str], datetime] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._held = ContextVar("memory_draft_locks", default=())
        self._launches: set[tuple[str, str]] = set()
        self.jobs = jobs or InMemoryJobQueue()
        self.jobs.drafts = self

    @asynccontextmanager
    async def lock(self, user_id):
        key = (str(user_id), asyncio.current_task())
        if key in self._held.get():
            yield
            return
        async with self._locks.setdefault(str(user_id), asyncio.Lock()):
            token = self._held.set((*self._held.get(), key))
            try:
                yield
            finally:
                self._held.reset(token)

    @asynccontextmanager
    async def launch(self, user_id, executor):
        key = (str(user_id), executor)
        self._launches.add(key)
        try:
            yield
        finally:
            self._launches.discard(key)

    async def worker_alive(self, user_id, executor):
        return (str(user_id), executor) in self._launches

    async def owner(self, user_id, job_id):
        key = (str(user_id), job_id)
        if key not in self._rows:
            return None
        session = self._rows[key].get("session") or {}
        return DraftOwner(
            executor=session.get("executor", ""),
            since=datetime.fromisoformat(session["opened_at"]) if session.get("opened_at") else self._stamps[key],
            updated_at=self._stamps[key], worker_posture=session.get("worker_posture", ""),
        )

    async def get(self, user_id, job_id: str) -> dict[str, Any] | None:
        row = self._rows.get((str(user_id), job_id))
        return dict(row) if row is not None else None

    async def put(self, user_id, job_id: str, state: dict[str, Any]) -> None:
        async with self.lock(user_id):
            key = (str(user_id), job_id)
            executor = (state.get("session") or {}).get("executor", "")
            owner = await self.owner(user_id, job_id)
            if owner and owner.executor != executor:
                raise DraftOwnershipError(owner.refusal())
            if executor:
                job = await self.jobs.get_job(user_id, job_id)
                if job is None or job.status != "claimed" or job.claimed_by != executor:
                    raise DraftOwnershipError(f"job {job_id} is not claimed by {executor}; cannot reopen it")
                job.claimed_by = executor
            self._rows[key] = dict(state)
            self._stamps[key] = datetime.now(timezone.utc)

    async def delete(self, user_id, job_id: str, *, executor: str = "") -> None:
        async with self.lock(user_id):
            key = (str(user_id), job_id)
            owner = await self.owner(user_id, job_id)
            if owner and executor and owner.executor != executor:
                raise DraftOwnershipError(owner.refusal())
            self._rows.pop(key, None)
            self._stamps.pop(key, None)

    async def abandon(self, user_id, job_id, *, executor, take_over=False, grace_seconds=60):
        async with self.lock(user_id):
            owner = await self.owner(user_id, job_id)
            if owner is None:
                return None
            audit = None
            if owner.executor != executor:
                if not take_over:
                    raise DraftOwnershipError(owner.refusal())
                dead = owner.executor.startswith("worker:") and not await self.worker_alive(user_id, owner.executor)
                grace = max(60, grace_seconds)
                if owner.idle_seconds < grace and not dead:
                    raise DraftOwnershipError(f"{owner.refusal()}; takeover refused within {grace}s grace")
                audit = {
                    "previous_executor": owner.executor or "legacy:unknown", "executor": executor,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "reason": "owning worker launch is gone" if dead else f"draft idle for {owner.idle_seconds}s (grace {grace}s)",
                }
                job = await self.jobs.get_job(user_id, job_id)
                if job and job.status == "claimed":
                    job.payload.setdefault("draft_takeovers", []).append(audit)
            await self.delete(user_id, job_id)
            await self.jobs.release(user_id, job_id)
            return audit

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

    def __init__(  # noqa: ANN001
        self, job_id: str, user_id, kind: str, payload: dict,
        not_before: datetime | None = None,
        order_at: datetime | None = None,
        seq: int = 0,
        created_at: datetime | None = None,
    ) -> None:
        self.job_id = job_id
        self.user_id = user_id
        self.kind = kind
        self.payload = payload
        self.status = "queued"
        #: The earliest instant a claim may take it; None = now, as a queue has always meant.
        self.not_before = not_before
        self.created_at = created_at or datetime.now(timezone.utc)
        #: Its place in the queue — `COALESCE(order_at, created_at)`, as the SQL computes it —
        #: and whether that place was inherited, which wins a tie exactly as in the SQL.
        self.order_at = order_at or self.created_at
        self.inherited = order_at is not None
        self.seq = seq

    def claim_key(self) -> tuple:
        """The claim query's ORDER BY, in Python (adapters/postgres.py `claim_next`). The
        write sequence stands in for the ties a real clock would not produce."""
        rank = 0 if self.kind in CLAIM_FIRST_KINDS else 1
        return (rank, self.order_at, not self.inherited, self.seq)


class InMemoryJobQueue:
    """A `JobQueue` with the two rules the canonical layer's single writer rests on:
    per-user serialization (nothing is handed out while that user has a job in flight) and a
    claim that records WHICH body holds it."""

    def __init__(self) -> None:
        self.jobs: list[_Job] = []
        self.completed: list[dict[str, Any]] = []
        self._seq = 0
        #: The last creation instant handed out. Separate transactions never share a
        #: Postgres timestamp in practice, but two writes here can land in one microsecond;
        #: an inherited place (`order_at` = another job's `created_at`) would then tie with a
        #: job written after that other one and win the tie. A strictly increasing clock
        #: keeps the in-memory order the order the SQL sees.
        self._last_created: datetime | None = None
        self.drafts = None

    async def enqueue(  # noqa: ANN001
        self, user_id, kind: str, payload: dict, *, not_before: datetime | None = None,
        order_at: datetime | None = None,
    ) -> str:
        self._seq += 1
        now = datetime.now(timezone.utc)
        if self._last_created is not None and now <= self._last_created:
            now = self._last_created + timedelta(microseconds=1)
        self._last_created = now
        job = _Job(
            f"job-{self._seq:02d}", user_id, kind, dict(payload), not_before, order_at,
            seq=self._seq, created_at=now,
        )
        self.jobs.append(job)
        return job.job_id

    def _in_flight(self, user_id) -> bool:  # noqa: ANN001
        return any(
            j.status == "claimed" and str(j.user_id) == str(user_id) for j in self.jobs
        )

    async def claim_next(  # noqa: ANN001
        self, user_id, *, claimed_by: str = "worker", exclude_kinds=(), tenants=()
    ):
        if self._in_flight(user_id) or (self.drafts and await self.drafts.list_open(user_id)):
            return None
        skip = {k for k in exclude_kinds if k}
        allowed = {t for t in tenants if t}
        now = datetime.now(timezone.utc)
        for job in sorted(self.jobs, key=_Job.claim_key):
            if (
                job.status == "queued"
                and str(job.user_id) == str(user_id)
                and (not allowed or str(job.user_id) in allowed)
                and job.kind not in skip
                and (job.not_before is None or job.not_before <= now)
            ):
                job.status = "claimed"
                job.claimed_by = claimed_by
                return job
        return None

    async def claim(self, user_id, job_id: str, *, claimed_by: str = "worker"):  # noqa: ANN001
        if self._in_flight(user_id) or (self.drafts and await self.drafts.list_open(user_id)):
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

    async def held_draft(self, user_id):
        if self.drafts:
            for job_id in await self.drafts.list_open(user_id):
                owner = await self.drafts.owner(user_id, job_id)
                if owner:
                    return job_id, owner
        return None

    async def requeue_claimed_jobs(self, *, draft_ttl=0, tenants=()):
        reclaimed = 0
        for job in self.jobs:
            if tenants and str(job.user_id) not in tenants:
                continue
            owner = await self.drafts.owner(job.user_id, job.job_id) if self.drafts else None
            if job.status == "done":
                if owner:
                    await self.drafts.delete(job.user_id, job.job_id)
                continue
            if job.status != "claimed" and owner is None:
                continue
            executor = owner.executor if owner else (getattr(job, "claimed_by", "") or "")
            expired = bool(owner and draft_ttl > 0 and owner.idle_seconds >= draft_ttl)
            if executor.startswith("worker:"):
                if not expired and self.drafts and await self.drafts.worker_alive(job.user_id, executor):
                    continue
            elif owner and not expired and draft_ttl > 0:
                continue
            if owner:
                await self.drafts.delete(job.user_id, job.job_id)
            was_claimed = job.status == "claimed"
            await self.release(job.user_id, job.job_id)
            reclaimed += int(was_claimed)
        return reclaimed

    async def list_jobs(self, user_id) -> list[dict[str, Any]]:  # noqa: ANN001
        """This user's jobs, newest first — the shape `PostgresStore.list_jobs` returns, and
        the peek a drain uses to see what it is leaving behind."""
        return [
            {
                "job_id": job.job_id,
                "kind": job.kind,
                "payload": dict(job.payload),
                "status": job.status,
                "not_before": job.not_before,
                "created_at": job.created_at,
                # The OUTCOME as this queue recorded it, so a reader that selects on what a
                # job DID — `pkc jobs requeue --empty-rounds` — is testable keyless.
                **self._outcome_of(user_id, job.job_id),
            }
            for job in reversed(self.jobs)
            if str(job.user_id) == str(user_id)
        ]

    def _outcome_of(self, user_id, job_id: str) -> dict[str, Any]:  # noqa: ANN001
        for record in reversed(self.completed):
            if record["job_id"] == job_id and record["user_id"] == str(user_id):
                return {
                    "ok": record.get("ok"),
                    "detail": record.get("detail"),
                    "snapshot_ref": record.get("snapshot_ref"),
                    "executor": record.get("executor"),
                    "token_usage": dict(record.get("token_usage") or {}),
                    "harness_output": record.get("harness_output"),
                }
        return {"ok": None, "detail": None, "snapshot_ref": None, "executor": None,
                "token_usage": {}, "harness_output": None}

    async def queue_cooling(self, user_id):  # noqa: ANN001
        """The earliest future `not_before` among this user's queued jobs, and its reason."""
        now = datetime.now(timezone.utc)
        waiting = [
            job for job in self.jobs
            if str(job.user_id) == str(user_id) and job.status == "queued"
            and job.not_before is not None and job.not_before > now
        ]
        if not waiting:
            return None
        first = min(waiting, key=lambda job: job.not_before)
        return first.not_before, str(first.payload.get("cooling_reason") or "")

    async def get_job(self, user_id, job_id: str):  # noqa: ANN001
        for job in self.jobs:
            if job.job_id == job_id and str(job.user_id) == str(user_id):
                return job
        return None

    async def attach_executor(self, user_id, job_id, executor):
        job = await self.get_job(user_id, job_id)
        if (job is None or job.status != "claimed" or job.claimed_by != "worker"
                or (self.drafts and await self.drafts.list_open(user_id))):
            return False
        job.claimed_by = executor
        return True

    async def release(self, user_id, job_id: str) -> None:  # noqa: ANN001
        for job in self.jobs:
            if (
                job.job_id == job_id
                and str(job.user_id) == str(user_id)
                and job.status == "claimed"
            ):
                job.status = "queued"
                job.claimed_by = None

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
        claimed_by: str | None = None,
        harness_output: str | None = None,
    ) -> None:
        for job in self.jobs:
            if job.job_id == job_id and str(job.user_id) == str(user_id):
                if claimed_by is not None and getattr(job, "claimed_by", None) != claimed_by:
                    return
                if job.status == "done":
                    return
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
                "harness_output": harness_output,
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
