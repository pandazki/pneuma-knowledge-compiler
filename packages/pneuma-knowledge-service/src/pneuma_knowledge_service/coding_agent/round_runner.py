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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from pneuma_knowledge_core.compile.gate import Violation, owed_now_lines
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import render_violations
from pneuma_knowledge_core.compile.session import DraftSession
from pneuma_knowledge_core.prompts import prompt

from ..cli.draft import (
    EXIT_OK,
    DraftRuntime,
    cmd_abandon,
    cmd_finish,
    open_round,
    outside_write,
)
from .backends import BackendManifest
from .install import SKILL_HASH_ENV, installed_hash
from .launcher import LaunchRequest, LaunchResult, launch_round, resume_supported

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
    rate_limited: bool = False


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

    # ── the round ────────────────────────────────────────────────────────────────────────

    async def run_job(self, rt: DraftRuntime, job_id: str) -> AgentRoundResult:
        """Open the job's draft, hand it to the harness, and make sure the round ends.

        The job is ALREADY claimed by the drain that called this, so `open_round` is asked
        not to claim it again (the queue's single-in-flight rule would refuse).
        """
        code, system_text, task_text = await open_round(rt, job_id, claim=False)
        if code != EXIT_OK:
            # `open` refused — an un-attributable HEAD, or a job that is not there. The
            # reason travels ON the exception rather than only on stderr, because the drain's
            # error path writes it onto the job row and that row is where an operator looks.
            raise AgentRoundOpenRefused(job_id, code, await outside_write(rt))

        home = Path(tempfile.mkdtemp(prefix=CONFIG_HOME_PREFIX))
        usage: dict[str, int] | None = None
        cost: float | None = None
        launches = 0
        timed_out = False
        rate_limited = False
        try:
            first = await self._launch(
                system_text=system_text,
                task_text=self._task(job_id, task_text),
                home=home,
            )
            launches += 1
            usage, cost = _sum_usage(usage, first.usage), _add(cost, first.cost_usd)
            timed_out = timed_out or first.timed_out
            rate_limited = rate_limited or first.rate_limited

            state = await self._open_state(rt, job_id)
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
                await cmd_finish(rt)
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
                resume_session=first.session_id if await self.can_resume(self.manifest) else "",
            )
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
            await cmd_finish(rt)
            if await self._open_state(rt, job_id) is not None:
                # Nothing left to try. Release the job rather than hold it claimed forever.
                await cmd_abandon(rt)
                outcome = ABANDONED
            return self._result(
                job_id, outcome, usage, cost, launches, timed_out, rate_limited
            )
        finally:
            shutil.rmtree(home, ignore_errors=True)

    # ── the pieces ───────────────────────────────────────────────────────────────────────

    async def _launch(
        self, *, system_text: str, task_text: str, home: Path, resume_session: str = ""
    ) -> LaunchResult:
        request = LaunchRequest(
            manifest=self.manifest,
            system_text=system_text,
            task_text=task_text,
            project_dir=self.project_dir,
            config_home=str(home),
            timeout_s=self.timeout_s,
            model=self.model,
            resume_session=resume_session,
            env=self._env(),
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

    def _task(self, job_id: str, task_text: str) -> str:
        """The round's task, headed by the one thing an unattended agent has to be told.

        Every other sentence it reads comes from the catalog through the skill; so does this
        one (ruling 4). What it says is the whole of what differs: the draft is already open,
        so start at step 3 — and the shim's path, because the working directory is empty and
        that path is the only hand it has.
        """
        preamble = prompt("steward.unattended.task", job=job_id, pkc=self._shim()).strip("\n")
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
        preamble = prompt("steward.unattended.task", job=job_id, pkc=self._shim()).strip("\n")
        return f"{preamble}\n\n{body}"

    @staticmethod
    async def _open_state(
        rt: DraftRuntime, job_id: str
    ) -> tuple[PatchDraft, DraftSession] | None:
        """This job's open round, or None when the draft is gone — i.e. the round ended."""
        state = await rt.drafts.get(rt.user_id, job_id)
        if not state:
            return None
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
    ) -> AgentRoundResult:
        return AgentRoundResult(
            job_id=job_id,
            outcome=outcome,
            usage=usage,
            cost_usd=cost,
            launches=launches,
            timed_out=timed_out,
            rate_limited=rate_limited,
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


def _add(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    return left + (right or 0.0)


__all__ = [
    "ABANDONED",
    "COMMITTED_BY_HARNESS",
    "FINISHED_BY_WORKER",
    "REPAIRED",
    "AgentRoundOpenRefused",
    "AgentRoundResult",
    "AgentRoundRunner",
]
