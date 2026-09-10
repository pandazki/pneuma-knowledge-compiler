"""JobQueue port — compile task queue (ADR-001, §5, §6).

Backed by PG `FOR UPDATE SKIP LOCKED`, serialized per user_id (I1). This
per-user serialization is what guarantees single-writer semantics on the git
canonical layer while service/worker processes stay stateless.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
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
        *,
        not_before: datetime | None = None,
    ) -> str:
        """Queue one job for this user. None/omitted `not_before` means "now", as ever.

        `not_before` states the earliest instant the job may be CLAIMED. It exists for one
        fact the queue could not otherwise hold: an agent-path job whose harness could not
        run — the Owner's subscription is out of room until a stated hour — must come back,
        and must not come back immediately. Expressed on the row rather than as a wait inside
        a worker, so nothing sleeps, nothing holds a claim while it waits, and a restarted
        process reads the same answer the one that wrote it would have.
        """
        ...

    async def claim_next(
        self,
        user_id: UserId,
        *,
        exclude_kinds: Sequence[str] = (),
        tenants: Sequence[str] = (),
    ) -> Job | None:
        """Claim the next per-user job (FOR UPDATE SKIP LOCKED, serial per user).

        An open draft also reserves the tenant even if its job was accidentally requeued.
        Finished jobs (including a row carrying a completion timestamp) are never claimed.

        A job whose `not_before` is still in the future is not claimed either, by the same
        means and for the same reason — it is skipped in the query rather than handed out
        and given back.

        `exclude_kinds` skips over kinds this body will not run and claims the oldest job
        that is left. The worker under an agent executor is the caller: a compile job is
        then the Steward's to open (`pkc draft open`), so the worker must reach that user's
        later index and projection jobs without claiming the compile one — and a
        kind-agnostic claim would hand it exactly that job and hold the user's single
        in-flight slot with it. The lock, the ordering and the per-user serialization are
        unchanged; only the row this claim is willing to take is narrower.

        `tenants` narrows WHOSE row it will take, for the same reason and by the same means:
        a body that serves only some of the tenants on one store — one engine process per
        library, several libraries on one Postgres — states them here and the claim query
        refuses everything else. Empty means every tenant, which is what a single worker over
        a single store has always done. Stated at the claim rather than enforced by claiming
        and releasing: a job put back has still spent that tenant's single in-flight slot.
        """
        ...

    async def claim(
        self, user_id: UserId, job_id: str, *, claimed_by: str = "worker"
    ) -> Job | None:
        """Claim ONE named job, under the same lock and the same per-user serialization.

        `claim_next` serves a body that takes whatever is next; this serves one that was told
        which job to work on — `pkc draft open <job-id>`, an agent claiming the round it is
        about to drive by hand (docs/design/coding-agent-mode.md §6). The guarantee is
        identical and deliberately so: whoever holds a user's claimed job is that user's
        single writer, and the canonical layer never learns which body it was. `claimed_by`
        records that anyway, because a job held by an open draft should be legible in the
        queue rather than merely missing from it.

        None when the job is not this user's, not queued, or when that user already has a job
        in flight.
        """
        ...

    async def attach_executor(self, user_id: UserId, job_id: str, executor: str) -> bool:
        """Bind an unstarted worker claim to one launch, refusing a draft or terminal job.

        This is a compare-and-set from claimed_by='worker', never a new queue claim.
        """
        ...

    async def record_job_usage(
        self,
        user_id: UserId,
        job_id: str,
        *,
        token_usage: dict[str, int] | None = None,
        executor: str | None = None,
    ) -> None:
        """Record what a FINISHED job cost, without touching its outcome.

        `complete` is the write that ends a job, and it states the outcome; this states only
        the two bookkeeping columns beside it. It exists because of one asymmetry: under an
        agent executor the round is ended by `pkc draft finish` INSIDE the harness's session,
        which never saw the harness's own token counters — the unattended launcher did, one
        process out, after the job row was already written. Calling `complete` again to add
        them would restate (and could contradict) an outcome that is already true.

        Idempotent and outcome-preserving: a job that does not exist, or a call that supplies
        nothing, changes nothing.
        """
        ...

    async def release(self, user_id: UserId, job_id: str) -> None:
        """Return a claimed job to the queue, undecided (`pkc draft abandon`).

        Not `complete(ok=False)`: nothing was judged about the work, so the row goes back to
        'queued' exactly as it stood and the next body picks it up. Canonical is untouched
        either way."""
        ...

    async def complete(
        self,
        user_id: UserId,
        job_id: str,
        *,
        ok: bool = True,
        detail: str | None = None,
        snapshot_ref: str | None = None,
        token_usage: dict[str, int] | None = None,
        executor: str | None = None,
        claimed_by: str | None = None,
    ) -> None:
        """Mark a job finished once. A late completion never replaces a terminal outcome.

        `claimed_by`, when supplied, requires that same executor to still own the claim.
        The worker's error tail uses it so an old launch cannot fail a replacement's round.

        `ok=False` records an aborted compile with its
        gate-violation `detail`; `snapshot_ref` is the resulting commit on success.

        `token_usage` is what the job's model calls actually spent, recorded on the same
        write that ends the job rather than through a second one: a job row that says it is
        done and cannot say what it cost is the one place a knowledge base spends most of
        its money invisibly. `None` states nothing, which is not the same as zero.

        `executor` names WHO ran the round — `langchain:<model spec>` for the worker's own
        loop, `agent:<backend>` for a coding agent that typed the calls through `pkc draft`
        (docs/design/coding-agent-mode.md ruling 1). It is recorded beside the usage because
        the two answer one question together: an agent-executed job carries an executor and
        NO usage, since the harness's counters are the subscription's and not the library's,
        and a zero there would be a claim that the round was free."""
        ...
