"""The unattended round: open the draft, hand it to a harness, read it back (§9).

**The cut this module makes, stated once.** `run_compile` is not used here at all. Its
`round_runner` seam takes a message list and a tool face and returns what the round spent —
a shape that means something when the loop and the draft live in one function call, and
means nothing when the draft lives in a `DraftStore` and the calls are typed by another
process. Driving `run_compile` from here would mean building a message list nobody reads and
a tool face nobody calls, so that its `finalize_compile` could run a second finish over a
draft the harness already finished. That is a fake round, and a second code path that ends a
draft.

So the worker under an agent executor bypasses `run_compile` and this module IS the round:

    open (claim → render → persist the draft)  ← `cli/draft.open_round`, the CLI's own
    launch the harness                          ← `launcher.launch_round`
    look at the store:
        draft gone      → the harness ran `pkc draft finish` and the job is complete
        draft open      → the harness stopped without finishing; the worker runs the SAME
                          `cmd_finish`, so the gate still judges
        draft in repair → one more launch with the violations as the task, then `cmd_finish`

`cmd_finish` is the one function that ends a draft, whoever calls it — the harness through
`pkc draft finish`, or the worker through this module. There is no second finalize and no
"finish it twice" to guard against.

What the unattended posture adds to the interactive one is the one thing a launched process
can know and a terminal session cannot: what the round cost. The harness prints it, the
launcher captured it, and it lands on the job row beside `executor` — which is why step 2's
"usage is absent" rule was never about agents, only about processes that measured nothing.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from pneuma_knowledge_core.compile.gate import Violation, owed_now_lines
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import render_violations
from pneuma_knowledge_core.compile.session import DraftSession
from pneuma_knowledge_core.ports.draft_store import DraftOwnershipError
from pneuma_knowledge_core.prompts import prompt

from ..cli.draft import (
    EXIT_OK,
    DraftRuntime,
    cmd_abandon,
    cmd_finish,
    open_round,
    outside_write,
    require_owner,
    validate_brief,
)
from .backends import BackendManifest, unavailable_reason
from .install import SKILL_HASH_ENV, installed_hash
from .launcher import (
    LaunchRequest,
    LaunchResult,
    foreign_skill_copies,
    launch_round,
    resume_supported,
    scrub,
)

log = logging.getLogger(__name__)

#: What one job's harness sessions live under. Per JOB, not per launch: the repair round
#: resumes the first round's session, so the directory has to outlive the process that made
#: it — and it is deleted when the job ends, because a session is not a kept record.
CONFIG_HOME_PREFIX = "pkc-agent-home-"

#: How a finished unattended round is summarized on the job row and in the log.
Outcome = str
COMMITTED_BY_HARNESS = "finished by the harness"
FINISHED_BY_WORKER = "the harness stopped; the worker finished the round"
REPAIRED = "the harness repaired the round"
ABANDONED = "the round was abandoned"
#: The launch never became a round. The harness refused before it read anything — the
#: subscription is out of room, or the process died on its own account — so there is nothing
#: to judge and nothing to finish. It is NOT an outcome of the work, which is the whole point:
#: a draft the worker "finishes" here would commit an empty round, complete the job ok, stamp
#: its sources digested, and leave the library believing that material was compiled. That is
#: what one night against a spent quota actually did, 296 times.
HARNESS_UNAVAILABLE = "the harness did not run the round"

#: WHY it did not — the three answers, because the worker does two different things about
#: them and telling them apart is the difference between waiting for a subscription and
#: waiting for a source that will never compile.
#:
#: `rate_limited` and `unavailable` are the provider saying "not now": the Owner's
#: subscription is out of room, or the model has none. Waiting is the only thing that helps,
#: so the tenant goes on ice and the job comes back behind a `not_before`.
#:
#: `failed` is neither. The harness exited non-zero (or declared its turn failed) with no
#: marker of either kind in its output — it fell over on this job's own account, and one
#: oversized source that kills every launch would, treated as a rate limit, put the whole
#: tenant to sleep for longer on every retry. So a failure is REPORTED on the job, retried a
#: bounded number of times, and costs the rest of the queue nothing.
UNAVAILABLE_RATE_LIMITED = "rate_limited"
UNAVAILABLE_AT_CAPACITY = "unavailable"
UNAVAILABLE_FAILED = "failed"


@dataclass(frozen=True)
class AgentRoundResult:
    """What one unattended job did, as the worker needs to record it."""

    job_id: str
    outcome: Outcome
    #: The token counts the harness reported across every launch, or None when it reported
    #: none. Summed over the rounds, exactly as the langchain executor sums its two.
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    #: How many harness processes this job cost — 1 normally, 2 with a repair round.
    launches: int = 0
    timed_out: bool = False
    #: A launch refused for a reason waiting fixes: the subscription is out of room, or the
    #: model has no capacity (`launcher.LaunchResult.rate_limited`).
    rate_limited: bool = False
    #: What the last launch exited with. Carried out of the runner because a
    #: `HARNESS_UNAVAILABLE` result is reported to an operator as a fault, and "exit 1" is
    #: the whole of what the harness said about a failure it had no words for.
    exit_code: int = 0
    #: The harness's own output, for the one reader that needs its words rather than its
    #: exit code: the parser that reads WHEN the subscription's room comes back. Bounded to
    #: the tail and scrubbed of anything credential-shaped, because a job row is not a place
    #: to keep a transcript and never a place to keep a key.
    output: str = ""
    #: Which of the three `UNAVAILABLE_*` answers this was, when the outcome is
    #: `HARNESS_UNAVAILABLE`; "" for every other outcome. Decided HERE, from the manifest's
    #: own markers, so the worker branches on a classification rather than re-reading the
    #: harness's prose.
    harness_reason: str = ""


def _sum_usage(
    left: dict[str, int] | None, right: dict[str, int] | None
) -> dict[str, int] | None:
    """Two rounds' counts as one. None + None stays None; None + counts is the counts."""
    if left is None:
        return dict(right) if right is not None else None
    if right is None:
        return dict(left)
    return {key: int(left.get(key, 0)) + int(right.get(key, 0)) for key in {*left, *right}}


@dataclass
class AgentRoundRunner:
    """One compile job, run unattended through a coding agent.

    Everything a launch needs that is not the job itself is a field, and the launcher is one
    of them: the keyless tests substitute a double and exercise the whole decision tree —
    finished, stopped, repaired, aborted — without a harness on `PATH`.
    """

    manifest: BackendManifest
    project_dir: str
    timeout_s: float
    model: str = ""
    #: How hard the harness is told to think, when its manifest states a flag for it.
    reasoning_effort: str = ""
    retries: int = 3
    keep_workdir: bool = False
    #: Injected so the tests can drive every branch with no subprocess at all.
    launcher: Callable[[LaunchRequest], Awaitable[LaunchResult]] = launch_round
    #: Whether this installation can continue a session, asked once by running it.
    can_resume: Callable[[BackendManifest], Awaitable[bool]] = resume_supported
    env: dict[str, str] = field(default_factory=dict)
    #: The worker's own resolved settings, handed to the launcher so the harness's `pkc`
    #: stands in the same library this worker does (`launcher.CONNECTION_SETTINGS`).
    settings: object | None = None
    #: The queue's failure tail uses this identity to avoid ending a replacement round.
    executor: str = field(default="", init=False)

    # ── the round ────────────────────────────────────────────────────────────────────────

    async def run_job(self, rt: DraftRuntime, job_id: str) -> AgentRoundResult:
        executor = f"worker:{self.manifest.name}:{uuid.uuid4().hex}"
        self.executor = executor
        previous = rt.draft_executor, rt.expected_job_id, rt.worker_posture
        rt.draft_executor, rt.expected_job_id, rt.worker_posture = executor, job_id, "unattended"
        try:
            async with rt.drafts.launch(rt.user_id, executor):
                async with rt.drafts.lock(rt.user_id):
                    if not await rt.jobs.attach_executor(rt.user_id, job_id, executor):
                        owner = await rt.drafts.owner(rt.user_id, job_id)
                        detail = owner.refusal() if owner else "job is not an unstarted worker claim"
                        raise AgentRoundOpenRefused(job_id, 2, detail)
                return await self._run_owned_job(rt, job_id)
        finally:
            rt.draft_executor, rt.expected_job_id, rt.worker_posture = previous

    async def _run_owned_job(self, rt: DraftRuntime, job_id: str) -> AgentRoundResult:
        """Open the job's draft, hand it to the harness, and make sure the round ends.

        The job is ALREADY claimed by the drain that called this, so `open_round` is asked
        not to claim it again (the queue's single-in-flight rule would refuse).
        """
        if rt.kind == "evolve":
            from ..cli.evolve import open_round as open_draft, cmd_finish as finish
        elif rt.kind == "episodes":
            from ..cli.episodes import open_round as open_draft, cmd_finish as finish
            rt.executor_skill = rt.executor_skill or self._env().get(SKILL_HASH_ENV, "")
        else:
            open_draft, finish = open_round, cmd_finish
        code, system_text, task_text = await open_draft(rt, job_id, claim=False)
        if code != EXIT_OK:
            # `open` refused — an un-attributable HEAD, or a job that is not there. The
            # reason travels ON the exception rather than only on stderr, because the drain's
            # error path writes it onto the job row and that row is where an operator looks.
            owner = await rt.drafts.owner(rt.user_id, job_id)
            detail = owner.refusal() if owner and owner.executor != rt.draft_executor else await outside_write(rt)
            raise AgentRoundOpenRefused(job_id, code, detail)

        home = Path(tempfile.mkdtemp(prefix=CONFIG_HOME_PREFIX))
        usage: dict[str, int] | None = None
        cost: float | None = None
        launches = 0
        timed_out = False
        rate_limited = False
        last_message = ""
        try:
            first = await self._launch(
                system_text=system_text,
                task_text=self._task(job_id, task_text, kind=rt.kind),
                home=home,
                executor=rt.draft_executor,
            )
            last_message = first.last_message
            launches += 1
            usage, cost = _sum_usage(usage, first.usage), _add(cost, first.cost_usd)
            timed_out = timed_out or first.timed_out
            rate_limited = rate_limited or first.rate_limited

            state = await self._open_state(rt, job_id)
            if state is not None and _never_ran(first, state[1]):
                # A launch that refused and typed NOTHING. There is no round here to judge,
                # so nothing is finished and nothing is abandoned: the worker completes the
                # job as a fault and queues the same work for later.
                #
                # Both halves are load-bearing. A refusal alone is not it — a harness that
                # wrote three claims and then hit the limit left real work, and the gate
                # judges that exactly as it judges any round its process walked out of. And
                # an untouched draft alone is not it either — a harness that read the
                # material and decided there was nothing to record is a legitimate empty
                # round, which is why `first.rate_limited or exit != 0` has to be true too.
                # Together they are the one shape that cannot be work: the harness was told
                # no before it read anything.
                last_message = ""  # the harness wrote no brief; it wrote a refusal
                return self._result(
                    job_id, HARNESS_UNAVAILABLE, usage, cost, launches, timed_out,
                    rate_limited, exit_code=first.exit_code,
                    output=_tail(first.stderr, first.stdout),
                    harness_reason=classify_refusal(self.manifest, first),
                )
            if state is None:
                return self._result(
                    job_id, COMMITTED_BY_HARNESS, usage, cost, launches, timed_out, rate_limited
                )

            outcome = FINISHED_BY_WORKER
            if state[1].round == "first":
                # Either the harness stopped mid-round, or its own `pkc draft finish` was
                # refused and it did not try again. The worker finishes what is there through
                # the same function `pkc draft finish` is, so the gate judges what was
                # written rather than the worker deciding anything.
                await finish(rt)
                state = await self._open_state(rt, job_id)
                if state is None:
                    return self._result(
                        job_id, outcome, usage, cost, launches, timed_out, rate_limited
                    )

            # A draft still open here is a draft the gate refused: one repair round, with what
            # the gate said as its task and the first round's session resumed where the
            # harness supports it.
            repair = await self._launch(
                system_text=system_text,
                task_text=self._repair_task(job_id, *state),
                home=home,
                executor=rt.draft_executor,
                resume_session=first.session_id if await self.can_resume(self.manifest) else "",
            )
            last_message = repair.last_message or last_message
            launches += 1
            usage, cost = _sum_usage(usage, repair.usage), _add(cost, repair.cost_usd)
            timed_out = timed_out or repair.timed_out
            rate_limited = rate_limited or repair.rate_limited
            outcome = REPAIRED

            if await self._open_state(rt, job_id) is None:
                return self._result(
                    job_id, outcome, usage, cost, launches, timed_out, rate_limited
                )
            # The repair round did not finish either. The worker finishes it: on a repair
            # round `cmd_finish` either commits or aborts, so this ends the draft whatever
            # the gate says.
            await finish(rt)
            if await self._open_state(rt, job_id) is not None:
                # Nothing left to try. Release the job rather than hold it claimed forever.
                await cmd_abandon(rt)
                outcome = ABANDONED
            return self._result(
                job_id, outcome, usage, cost, launches, timed_out, rate_limited
            )
        except DraftOwnershipError:
            # An explicit takeover/TTL recovery ended this launch's authority. Its late
            # return must neither finish nor abandon the replacement executor's work.
            last_message = ""  # A replacement's version must not inherit this launch's brief.
            return self._result(
                job_id, "draft ownership lost", usage, cost, launches, timed_out, rate_limited
            )
        finally:
            shutil.rmtree(home, ignore_errors=True)
            if rt.kind == "compile" and last_message and rt.record_brief is not None:
                try:
                    job = await rt.jobs.get_job(rt.user_id, job_id)
                    if job is not None and job.status == "done" and job.claimed_by == rt.draft_executor:
                        text = validate_brief(last_message)
                        # The store only fills a missing brief on this launch's version.
                        # An explicit --brief wins; a replacement's narration stays its own.
                        await rt.record_brief(job_id, text)
                except Exception:
                    log.warning("could not record the Steward brief for %s", job_id, exc_info=True)

    # ── the pieces ───────────────────────────────────────────────────────────────────────

    async def _launch(
        self, *, system_text: str, task_text: str, home: Path, executor: str,
        resume_session: str = ""
    ) -> LaunchResult:
        request = LaunchRequest(
            manifest=self.manifest,
            system_text=system_text,
            task_text=task_text,
            project_dir=self.project_dir,
            config_home=str(home),
            timeout_s=self.timeout_s,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            resume_session=resume_session,
            # The round sees one `pkc-steward` — this library's — and no global copy beside it.
            hidden_skills=foreign_skill_copies(self.manifest, self.project_dir),
            env={**self._env(), "PKC_DRAFT_EXECUTOR": executor},
            settings=self.settings,
            retries=self.retries,
            keep_workdir=self.keep_workdir,
        )
        result = await self.launcher(request)
        log.info(
            "%s round finished: exit %s%s%s in %d attempt(s)",
            self.manifest.display_label,
            result.exit_code,
            ", timed out" if result.timed_out else "",
            ", rate limited" if result.rate_limited else "",
            result.attempts,
        )
        return result

    def _env(self) -> dict[str, str]:
        """What the launched session is told beyond the manifest's own variables.

        The installed skill's hash, when the project has one: the shim reads it from disk and
        exports it, and stating it here means a harness that bypassed the shim still stamps
        `Executor-Skill:` on the commit — the identity of the words the executor was taught
        travels with the commit, or it does not travel at all.
        """
        env = dict(self.env)
        digest = installed_hash(self.project_dir, self.manifest)
        if digest:
            env.setdefault(SKILL_HASH_ENV, digest)
        return env

    def _shim(self) -> str:
        return str(Path(self.project_dir).expanduser().resolve() / self.manifest.skill_dir / "scripts" / "pkc")

    def _task(self, job_id: str, task_text: str, *, kind: str = "compile") -> str:
        """The round's task, headed by the one thing an unattended agent has to be told.

        Every other sentence it reads comes from the catalog through the skill; so does this
        one (ruling 4). What it says is the whole of what differs: the draft is already open,
        so start at step 3 — and the shim's path, because the working directory is empty and
        that path is the only hand it has.
        """
        key = {
            "evolve": "steward.unattended.evolve_task",
            "episodes": "steward.unattended.episodes_task",
        }.get(kind, "steward.unattended.task")
        preamble = prompt(key, job=job_id, pkc=self._shim()).strip("\n")
        return f"{preamble}\n\n{task_text}"

    def _repair_task(self, job_id: str, draft: PatchDraft, session: DraftSession) -> str:
        """The repair round's task: what the gate said, in the gate's own words.

        Two shapes, because a `finish` can be refused two ways. When the gate REJECTED the
        draft the session carries its findings, and `render_violations` — the same function
        the langchain repair round is fed and the same one `pkc draft finish` prints — renders
        them, so the two executors' repair rounds read the same words about the same findings.
        When it was refused by the overview floor instead, the session carries no findings and
        the round is still its first: what is owed is then asked of the draft directly, with
        `owed_now_lines` — the same lines `pkc draft status` prints.
        """
        if session.violations:
            body = render_violations(
                [Violation(*triple) for triple in session.violations],
                cut_off_at=session.spent if session.cut_off else None,
                next_budget=session.budget,
            )
        else:
            owed = owed_now_lines(
                draft, threshold=session.overview_required_after_claims
            )
            body = "\n".join(
                ["`pkc draft finish` did not accept this round. What it still owes:", *owed]
            )
        return self._task(job_id, body, kind=session.kind)

    @staticmethod
    async def _open_state(
        rt: DraftRuntime, job_id: str
    ) -> tuple[PatchDraft, DraftSession] | None:
        """This job's open round, or None when the draft is gone — i.e. the round ended."""
        async with rt.drafts.lock(rt.user_id):
            state = await rt.drafts.get(rt.user_id, job_id)
            job = await rt.jobs.get_job(rt.user_id, job_id)
            if job is not None and getattr(job, "status", "") == "done":
                if getattr(job, "claimed_by", None) != rt.draft_executor:
                    raise DraftOwnershipError(f"job {job_id} was finished by a replacement executor")
                # Finish can have completed its job before a failure in its final cleanup.
                # The persisted outcome wins; only this launch's leftover draft is removed.
                if state:
                    await rt.drafts.delete(rt.user_id, job_id, executor=rt.draft_executor)
                return None
            if not state:
                raise DraftOwnershipError(f"job {job_id} no longer belongs to this launch")
            await require_owner(rt, job_id)
            return (
                PatchDraft.from_state(state.get("draft") or {}),
                DraftSession.from_state(state.get("session") or {}),
            )

    @staticmethod
    def _result(
        job_id: str,
        outcome: Outcome,
        usage: dict[str, int] | None,
        cost: float | None,
        launches: int,
        timed_out: bool,
        rate_limited: bool,
        *,
        exit_code: int = 0,
        output: str = "",
        harness_reason: str = "",
    ) -> AgentRoundResult:
        return AgentRoundResult(
            job_id=job_id,
            outcome=outcome,
            usage=usage,
            cost_usd=cost,
            launches=launches,
            timed_out=timed_out,
            rate_limited=rate_limited,
            exit_code=exit_code,
            output=output,
            harness_reason=harness_reason,
        )


class AgentRoundOpenRefused(RuntimeError):
    """`pkc draft open` refused this job, and why."""

    def __init__(self, job_id: str, code: int, reason: str = "") -> None:
        super().__init__(
            f"the draft for job {job_id} could not be opened (exit {code})"
            + (f": {reason}" if reason else "")
        )
        self.job_id = job_id
        self.code = code
        self.reason = reason


#: How much of a refusing harness's output travels out of the round. Enough to hold the
#: sentence that names the deadline, and nowhere near enough to be a transcript.
OUTPUT_TAIL_CHARS = 4000


def _never_ran(launch: LaunchResult, session: DraftSession) -> bool:
    """Did this launch refuse before it became a round at all?

    Two mechanical facts, both required: the launch could not run (a transient refusal the
    launcher already waited out, or a non-zero exit), and the draft it was handed still has
    every one of its calls unspent — the harness typed nothing. The second is what keeps a
    partially-written round out of this branch, and the first is what keeps a deliberate
    empty round out of it.
    """
    return (launch.rate_limited or launch.exit_code != 0) and session.spent == 0


def _tail(*parts: str) -> str:
    """The tail of what the harness said, joined and scrubbed — its own words, no keys.

    Scrubbed HERE and not at the reader, because this string is the one that travels: onto
    the job row, through the jobs API, into a `pkc jobs --json` an Owner pastes somewhere.
    """
    text = "\n".join(part for part in parts if part)
    return scrub(text[-OUTPUT_TAIL_CHARS:])


def classify_refusal(manifest: BackendManifest, launch: LaunchResult) -> str:
    """Which of the three `UNAVAILABLE_*` answers this launch was.

    Mechanical, off the manifest's own marker lists — the same words `launcher._is_rate_limited`
    matched to decide there was anything transient here at all. The launcher answers "is
    waiting worth it"; this answers "waiting for WHAT", which is the question the worker has
    to act on: a spent subscription and a busy model are a tenant-wide wait, and a harness
    that fell over is one job's fault.
    """
    if not launch.rate_limited:
        return UNAVAILABLE_FAILED
    said = unavailable_reason(f"{launch.stderr}\n{launch.stdout}", manifest)
    if said in ("at capacity", "unavailable"):
        return UNAVAILABLE_AT_CAPACITY
    # A rate-limit EXIT CODE names no words at all; the launcher already read it as a limit,
    # and a limit is what it stays.
    return UNAVAILABLE_RATE_LIMITED


#: How much of a failure's own sentence reaches the job's detail. A detail is read in a list
#: — a paragraph there would push every other row off the screen — and the whole tail is on
#: the row beside it for anyone who wants the rest.
FAILURE_LINE_CHARS = 200


def failure_line(text: str) -> str:
    """The one line from a harness's output that names what went wrong, or "".

    The FIRST meaningful line of the tail, because the tail is built stderr-first and a
    harness states its fault before it states its stack. Blank lines and pure punctuation
    are skipped; nothing is interpreted, so what a person reads on the job row is the
    harness's own sentence rather than this framework's guess about it.
    """
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line or not any(character.isalnum() for character in line):
            continue
        return line[:FAILURE_LINE_CHARS]
    return ""


def _add(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    return left + (right or 0.0)


__all__ = [
    "ABANDONED",
    "COMMITTED_BY_HARNESS",
    "FINISHED_BY_WORKER",
    "HARNESS_UNAVAILABLE",
    "REPAIRED",
    "UNAVAILABLE_AT_CAPACITY",
    "UNAVAILABLE_FAILED",
    "UNAVAILABLE_RATE_LIMITED",
    "AgentRoundOpenRefused",
    "AgentRoundResult",
    "AgentRoundRunner",
    "classify_refusal",
    "failure_line",
]
