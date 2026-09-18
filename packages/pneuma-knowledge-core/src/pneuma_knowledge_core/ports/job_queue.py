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
        order_at: datetime | None = None,
    ) -> str:
        """Queue one job for this user. None/omitted `not_before` means "now", as ever.

        `not_before` states the earliest instant the job may be CLAIMED. It exists for one
        fact the queue could not otherwise hold: an agent-path job whose harness could not
        run — the Owner's subscription is out of room until a stated hour — must come back,
        and must not come back immediately. Expressed on the row rather than as a wait inside
        a worker, so nothing sleeps, nothing holds a claim while it waits, and a restarted
        process reads the same answer the one that wrote it would have.

        `order_at` states the job's PLACE in the queue; None means the moment it was
        written. It is passed by work that queues work — an index job queueing its source's
        episode judgement, a job re-queued because its harness never ran — so the follow-up
        inherits the place of the job that caused it instead of joining the end, behind every
        compile round already waiting. It never rewrites when the row was created.
        """
        ...

    async def claim_next(
        self,
        user_id: UserId,
        *,
        exclude_kinds: Sequence[str] = (),
        tenants: Sequence[str] = (),
        lane: str | None = None,
    ) -> Job | None:
        """Claim the next per-user job (FOR UPDATE SKIP LOCKED, serial per user per lane).

        "Next" has two keys. First the kind: work that launches no harness, runs no compile
        model and never writes canonical (index, the recall projection and rebuild) is
        handed out ahead of everything else, because L1 reachability is unconditional (I3)
        and must not wait hours behind compile rounds. Then the place — `order_at`, else the
        moment the job was written — oldest first, so every other kind stays FIFO and a job
        that inherited a place keeps it. Serialization is unchanged: still one job in flight
        per user.

        An open draft also reserves the tenant even if its job was accidentally requeued.
        Finished jobs (including a row carrying a completion timestamp) are never claimed.

        `lane` names the LANE this body drains, and narrows all three of the refusals above
        to it: which rows may be taken, which claimed job counts as in flight, and which
        open draft reserves the tenant. Which kinds are in which lane is the application's
        classification, not this port's (the service's `job_lanes.py`); what the port
        promises is that serialization holds per user PER LANE, and that the lane a canonical
        writer drains in is serialized exactly as the whole queue used to be — that is the
        single writer the git canonical layer rests on. `None` means the whole tenant, as
        before lanes existed: one job in flight for that user, whatever its kind.

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
        harness_output: str | None = None,
    ) -> None:
        """Record what a FINISHED job cost and what its harness said, without touching its
        outcome.

        `complete` is the write that ends a job, and it states the outcome; this states only
        the bookkeeping columns beside it. `harness_output` is here for the same asymmetry as
        the usage: a launched round's own words exist one process out, after the round's `pkc
        draft finish` has already written the row, and they are the only account of a round
        nobody watched. It exists because of one asymmetry: under an
        agent executor the round is ended by `pkc draft finish` INSIDE the harness's session,
        which never saw the harness's own token counters — the unattended launcher did, one
        process out, after the job row was already written. Calling `complete` again to add
        them would restate (and could contradict) an outcome that is already true.

        Idempotent and outcome-preserving: a job that does not exist, or a call that supplies
        nothing, changes nothing.
        """
        ...

    async def park(
        self,
        user_id: UserId,
        job_id: str,
        *,
        payload: dict[str, Any],
        not_before: datetime | None,
        detail: str,
        paused: bool = False,
        claimed_by: str | None = None,
        harness_output: str | None = None,
    ) -> None:
        """Return a job to the queue to be retried later, on the SAME row.

        The queue's answer to every failure that is not provably hopeless (the service's
        `job_retry.py` states the rule and the one list of exceptions). It differs from
        `release` in that something DID go wrong and the row says so — `detail` carries
        `waiting: <reason>; retry at <instant> (attempt n)` and `payload.retry` carries the
        history — and from `complete(ok=False)` in that the job is not finished: it is queued
        again, behind `not_before`, at the place it already had.

        The same row on purpose. A queue that answers a failure by completing one row and
        writing another makes the Owner track a chain of ids for one piece of work, and makes
        every count of "what failed" include work that is merely waiting. Nothing about the
        row's place changes, so a job that was next is next again when its wait is over.

        `paused` is the end of the retry schedule: the row goes to the `paused` status with no
        `not_before` at all, because what it is waiting for is a PERSON rather than an
        instant. A paused job is never claimed and never requeued by a self-heal; `resume_jobs`
        is the only thing that starts it again.

        `claimed_by`, when supplied, requires that body to still hold the claim, exactly as it
        does on `complete`. A finished job is never parked.
        """
        ...

    async def resume_jobs(
        self,
        user_id: UserId,
        *,
        job_id: str | None = None,
        reason_like: str = "",
        every: bool = False,
        include_waiting: bool = False,
    ) -> int:
        """Put paused jobs back in the queue with a fresh schedule; return how many.

        `include_waiting` also releases queued jobs whose retry time is still ahead.

        The other half of the pause: a person has done the thing the row was waiting for —
        topped up the account, logged the harness in, committed what they left in the tree —
        and says so. `payload.retry.attempts` goes back to 0 so the next failure waits a
        minute rather than a day (the situation has changed, and the schedule is a guess about
        the situation), while `payload.retry.history` is KEPT: what already happened to this
        job is not undone by resuming it.

        One of three selectors, and at least one is required — `job_id` for a named row,
        `reason_like` for every row whose reason contains that text, `every` for all of them.
        Nothing else about the row moves: same id, same place, same payload of work.
        """
        ...

    async def job_summary(self, user_id: UserId) -> dict[str, Any]:
        """What this user's queue is doing right now, in one read.

        `{queued, waiting: {count, reasons: [{reason, count, next_retry_at}]}, paused:
        {count, reasons: [{reason, count, since}]}, claimed, failed, succeeded}`. `queued` is
        what a claim could take now, `waiting` is the rest of the queued rows — those whose
        `not_before` is still ahead — and `paused` is the ones that have run out of schedule
        and are waiting for a person; the counts are disjoint and a face can add them up.
        Both `reasons` lists group by the phrase the row's detail carries, because "13
        waiting" is a fact nobody can act on and "9 of them on a payment refusal" is the one
        an Owner can.
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
        harness_output: str | None = None,
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
        and a zero there would be a claim that the round was free.

        `harness_output` is what a launched harness itself printed about a round it did not
        run — bounded to its tail and scrubbed of anything credential-shaped before it gets
        here. `detail` is what the worker DECIDED; this is what the process SAID, and only
        the second one answers "why did exit 1 happen" once the worker has moved on. `None`
        states nothing, which is every job no harness refused."""
        ...
