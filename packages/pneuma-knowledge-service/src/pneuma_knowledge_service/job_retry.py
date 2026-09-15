"""One treatment for every job that did not finish: wait, and say why.

A knowledge base is fed by a harness, a provider, an embedding API, a vector store and a git
repository, and every one of them can be out of room, out of money, out of patience or simply
away for two minutes. Classifying those failures one by one was a losing game: each new
sentence a provider prints needed a branch, and a sentence nobody had a branch for struck the
job out — a library that stopped compiling because a card expired, with 300 rows saying
`worker error: …` and nothing saying what to do about it.

So there is one rule and one exception to it.

**The rule.** A job that did not finish goes back to `queued` on its own row, with
`not_before` set by `RETRY_BACKOFF_S`, its `detail` reading `waiting: <reason>; retry at
<instant> (attempt n)`, and the failure appended to `payload.retry.history`. Nothing is
struck out, nothing is duplicated, and the id the Owner is tracking stays the id it was. That
is `park`.

**The end of the schedule is a pause, not a verdict.** Once the last step has been tried the
job stops asking and waits for a PERSON: the row goes to `paused`, saying what it waited for,
how many attempts it made and over what span, and how to start it again. Retrying a seventh
time changes nothing that six attempts over thirty hours did not already change — what has to
happen is that somebody tops up the account, logs the harness in, commits the tree — and a job
that goes on asking for ever teaches the Owner to ignore the queue. `pkc jobs resume` (and
`POST /jobs/resume`) puts paused rows back with a FRESH schedule, because a person who resumes
has changed something and the next minute is the right first wait.

**The exception.** A failure that provably cannot succeed on a retry — the input has to
change first — is terminal, and there is one enumerated list of those (`TERMINAL_FAILURES`).
Anything not in the list parks. The list is short on purpose: the burden is on the failure to
prove it is hopeless, never on the queue to prove it is not.

The wait is a column and not a sleeping worker, for the reason `JobQueue.enqueue` already
states: a row that says when it may be claimed is read the same way by every body, holds no
claim while it waits, and survives a restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Iterable
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId

#: How long a job waits before its nth attempt. The last value stands for every attempt after
#: it, so a failure nobody fixes settles into one retry a day rather than stopping: a minute
#: for the blip, five and fifteen for the outage somebody is already fixing, an hour and four
#: for the provider that is down for the afternoon, a day for the card that expired. There is
#: no ceiling knob because the last element IS the ceiling, and two places to state one
#: number is one place too many.
RETRY_BACKOFF_S: tuple[int, ...] = (60, 300, 900, 3600, 4 * 3600, 24 * 3600)

#: How many past failures one job's payload keeps. Enough to read a pattern off a row — the
#: same provider sentence six times is a different fact from six different ones — and bounded
#: so a job that waits for a week does not grow a log in its payload.
RETRY_HISTORY = 10

#: How much of one failure's own words ride the row. Generous rather than tidy: the reason is
#: the diagnosis — a gate's violations, a provider's sentence — and a row that cannot say what
#: refused it is the row this whole treatment exists to stop writing. It is bounded because it
#: is one line in a job listing and not a stack trace; the faces that print it in a summary
#: line cut it again to their own width (`REASON_LINE_CHARS`).
WAITING_REASON_CHARS = 500

#: How much of a reason one summary line shows. A `Waiting:` line names up to five reasons
#: side by side, and a line that carries five 500-character diagnoses is a line nobody reads.
REASON_LINE_CHARS = 80


def reason_line(reason: str) -> str:
    """One reason as a summary line shows it — cut to `REASON_LINE_CHARS`."""
    text = str(reason or "")
    return text if len(text) <= REASON_LINE_CHARS else text[: REASON_LINE_CHARS - 1] + "…"

#: What a parked row's `detail` starts with. One token, so every face that has to tell a job
#: that is waiting from a job that failed greps for one string.
WAITING_PREFIX = "waiting: "
_RETRY_AT = "; retry at "

#: And what a paused row's starts with — the same discipline, a different word, because the
#: two are different questions to a person: one is "it will come back", the other is "it is
#: waiting for you".
PAUSED_PREFIX = "paused: "
_ATTEMPTS = "; "

#: The one command that starts a paused job again, written on the row itself. A row that
#: says a person has to act and does not say what to type is half a message.
RESUME_HINT = "resume with pkc jobs resume"

#: The status a job out of schedule carries. One spelling, imported by the adapters, because
#: a status value spelled twice is a status value that will be spelled differently once.
PAUSED_STATUS = "paused"


#: Every failure that a retry cannot fix, and why each one cannot be fixed by waiting. A
#: failure in this list is completed `ok=False` and never comes back; everything else parks.
#: The list is the whole enumeration — there is no "and anything that looks like it".
TERMINAL_FAILURES: dict[str, str] = {
    # The dispatch has no body for this kind, so a retry hands it to the same nothing.
    "unknown_kind": "no body in this build runs a job of that kind",
    # The row's payload is not the shape its kind requires, and a retry reads the same bytes.
    "payload_invalid": "the payload is not the shape this kind of job requires",
    # The material this job names is gone from L0; nothing a retry does brings it back.
    "source_gone": "the source this job names no longer exists",
    # Longer than one round can take, AFTER the windowing and task bounds the framework
    # already applies — the same material is the same length on every later attempt.
    "input_too_large": "the material is longer than one round can take, after the splitting "
                       "the framework already does",
    # The archive proposal was confirmed against a canonical HEAD that has since moved; the
    # decision has to be made again against the tree that exists.
    "proposal_stale": "the archive proposal's canonical HEAD has moved; it must be re-planned",
}


class TerminalJobFailure(Exception):
    """A failure whose code is in `TERMINAL_FAILURES`: the input must change first.

    Raised where the fact is known — the dispatch that has no body for a kind, the loader
    that found no source — so the drain's failure tail never has to guess from an exception
    class whether waiting could help.
    """

    def __init__(self, code: str, message: str = "") -> None:
        if code not in TERMINAL_FAILURES:
            raise ValueError(f"{code!r} is not an enumerated terminal failure")
        self.code = code
        self.message = message or TERMINAL_FAILURES[code]
        super().__init__(f"{code}: {self.message}")

    @property
    def detail(self) -> str:
        """The sentence the job row carries. `<code>: <what happened>`, so an operator greps
        for the code and reads the rest."""
        return f"{self.code}: {self.message}"


def retry_backoff(attempts: int) -> int:
    """Seconds to wait before attempt `attempts` (1-based); the last step, forever after."""
    index = max(1, int(attempts)) - 1
    return RETRY_BACKOFF_S[min(index, len(RETRY_BACKOFF_S) - 1)]


def bounded_reason(reason: str) -> str:
    """One line, bounded — what a parked row says it is waiting for."""
    text = " ".join(str(reason or "").split()).strip() or "the job did not finish"
    return text if len(text) <= WAITING_REASON_CHARS else text[: WAITING_REASON_CHARS - 1] + "…"


def waiting_detail(reason: str, not_before: datetime, attempts: int) -> str:
    """The sentence a parked row carries, and the one `waiting_reason` reads back."""
    return f"{WAITING_PREFIX}{reason}{_RETRY_AT}{not_before.isoformat()} (attempt {attempts})"


def humanize_span(seconds: float) -> str:
    """How long the attempts went on, as a person says it: `31h`, `2d 6h`, `45m`, `<1m`.

    Coarse on purpose — the number that matters is the order of magnitude, and a row reading
    `6 attempts over 1d 6h` says "this has been failing since yesterday" at a glance, which
    is what decides whether the Owner goes looking."""
    total = int(max(0.0, float(seconds)))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m" if minutes else "<1m"


def paused_detail(reason: str, attempts: int, span_seconds: float) -> str:
    """The sentence a paused row carries: what it waited for, how hard it tried, what to type."""
    tried = f"{attempts} attempt{'s' if attempts != 1 else ''} over {humanize_span(span_seconds)}"
    return f"{PAUSED_PREFIX}{reason}{_ATTEMPTS}{tried}; {RESUME_HINT}"


def paused_reason(detail: str | None) -> str:
    """The reason phrase out of a paused row's `detail`, or "" when it is not a paused row.

    The inverse of `paused_detail`, and the summary's grouping key. Cut at the LAST `"; "`
    pair this format writes, so a reason carrying its own semicolons survives — the two
    trailing clauses are written here and never contain one.
    """
    text = str(detail or "")
    if not text.startswith(PAUSED_PREFIX):
        return ""
    body = text[len(PAUSED_PREFIX):]
    if body.endswith(RESUME_HINT):
        body = body[: -len(RESUME_HINT)].rstrip()
        body = body[:-1] if body.endswith(";") else body
    reason, sep, _tried = body.rpartition(_ATTEMPTS)
    return (reason if sep else body).strip()


def waiting_reason(detail: str | None) -> str:
    """The reason phrase out of a parked row's `detail`, or "" when it is not a parked row.

    The inverse of `waiting_detail`, and the summary's grouping key. Split from the RIGHT:
    a reason may carry its own semicolons (`round_incomplete: timed out; nothing was
    committed`), and the instant this cuts at cannot.
    """
    text = str(detail or "")
    if not text.startswith(WAITING_PREFIX):
        return ""
    reason, sep, _ = text[len(WAITING_PREFIX):].rpartition(_RETRY_AT)
    return (reason if sep else text[len(WAITING_PREFIX):]).strip()


@dataclass(frozen=True)
class Parked:
    """What one `park` decided, for the caller's own log line.

    `paused` is the end of the schedule: the row is not coming back on its own and
    `not_before` is None, because what it is waiting for is a person."""

    attempts: int
    not_before: datetime | None
    detail: str
    reason: str
    paused: bool = False


def _grouped(
    rows: Iterable[tuple[str | None, datetime | None]],
    *,
    read: "Callable[[str | None], str]",
    stamp: str,
) -> list[dict[str, Any]]:
    """Group `(detail, instant)` by the reason the detail carries, biggest group first.

    One shape for both halves of the summary, and the same instant in both: the EARLIEST of
    the group. For `waiting` that is when this starts moving again; for `paused`, how long it
    has been sitting. A row whose detail this reader does not recognise is counted under one
    honest name rather than dropped, because the summary's counts have to add up to what the
    queue holds.
    """
    groups: dict[str, dict[str, Any]] = {}
    for detail, instant in rows:
        reason = read(detail) or "held back"
        entry = groups.setdefault(reason, {"reason": reason, "count": 0, stamp: None})
        entry["count"] += 1
        held = entry[stamp]
        if instant is not None and (held is None or instant < held):
            entry[stamp] = instant
    return sorted(groups.values(), key=lambda e: (-e["count"], e["reason"]))


def waiting_reasons(
    rows: Iterable[tuple[str | None, datetime | None]],
) -> list[dict[str, Any]]:
    """Group `(detail, not_before)` of the waiting rows into the summary's `reasons`.

    One entry per reason phrase, biggest group first, each carrying the soonest retry in it —
    the shape `GET /jobs/summary` publishes and `pkchome status` prints.
    """
    return _grouped(rows, read=waiting_reason, stamp="next_retry_at")


def paused_reasons(
    rows: Iterable[tuple[str | None, datetime | None]],
) -> list[dict[str, Any]]:
    """The same grouping for the paused rows, carrying `since` — the OLDEST pause in each
    group, because the question a paused line answers is how long this has been sitting."""
    return _grouped(rows, read=paused_reason, stamp="since")


def retry_payload(
    payload: dict[str, Any], reason: str, *, at: datetime
) -> tuple[dict[str, Any], int]:
    """The job payload a park writes, and the attempt number it is now on. Pure.

    The history is the point: a row that has waited six times for the same provider sentence
    and a row that has met six different failures are different situations, and `attempts`
    alone cannot tell them apart.
    """
    body = dict(payload or {})
    previous = body.get("retry")
    previous = previous if isinstance(previous, dict) else {}
    attempts = int(previous.get("attempts", 0) or 0) + 1
    failure = {"at": at.isoformat(), "detail": reason}
    history = [*(previous.get("history") or []), failure][-RETRY_HISTORY:]
    body["retry"] = {"attempts": attempts, "last_failure": failure, "history": history}
    # The pre-park counter this replaces. Left behind on a payload written by an older build,
    # it would be read by nothing and would still be the first thing a person saw.
    body.pop("harness_failures", None)
    return body, attempts


def attempt_span(payload: dict[str, Any]) -> float:
    """Seconds from the first failure this payload remembers to the last. 0 when it cannot
    say — a payload written before the history existed, or one failure only."""
    history = ((payload or {}).get("retry") or {}).get("history") or []
    stamps: list[datetime] = []
    for entry in history:
        try:
            stamps.append(datetime.fromisoformat(str((entry or {}).get("at") or "")))
        except ValueError:
            continue
    return (max(stamps) - min(stamps)).total_seconds() if len(stamps) > 1 else 0.0


def resumed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload a resume writes: the schedule restarted, the history kept.

    `attempts` back to 0 because a person who resumes has CHANGED something, and the next
    failure should wait a minute rather than the day the exhausted schedule ended on. The
    history stays because what already happened to this job is not undone by resuming it —
    and a job that pauses twice in a week is a different fact from one that pauses once.
    """
    body = dict(payload or {})
    previous = body.get("retry")
    if isinstance(previous, dict):
        body["retry"] = {**previous, "attempts": 0}
    return body


def resumed_detail(payload: dict[str, Any]) -> str:
    """What a resumed row says while it waits its turn.

    Read off the payload BEFORE `resumed_payload` resets it, so the line names the attempts
    this row actually made: nothing has happened to it since, and how much it had already
    tried is the context for whatever happens next."""
    previous = (payload or {}).get("retry")
    attempts = int((previous or {}).get("attempts", 0) or 0) if isinstance(previous, dict) else 0
    return f"resumed after {attempts} attempt{'s' if attempts != 1 else ''}"


async def park(
    store,  # noqa: ANN001 — the JobQueue port; typed there
    user_id: UserId,
    job_id: str,
    *,
    payload: dict[str, Any],
    reason: str,
    not_before: datetime | None = None,
    now: datetime | None = None,
    claimed_by: str | None = None,
    harness_output: str | None = None,
) -> Parked:
    """Put this job back in its own place, waiting, and say on the row what it waits for.

    Same row and same job id: the Owner is tracking one id, and a queue that answers a failure
    by writing a second row makes them track a chain. `not_before` is the provider's own
    deadline when one was named and it is still ahead of us — a stated hour beats a schedule —
    and otherwise the schedule's next step.

    **Past the last step it PAUSES** (`RETRY_BACKOFF_S` exhausted). The row goes to `paused`
    with no `not_before` at all: `claim_next` will not take it and the self-heal will not
    requeue it, so it sits until a person runs `pkc jobs resume`. That is the honest reading
    of six attempts spread over a day and a half — whatever this is waiting for is not going
    to change by itself, and a job that goes on asking for ever is a job the Owner learns to
    scroll past. The provider's own stated deadline does not override it either: an hour named
    by a provider we have already failed against six times is not new information.

    `claimed_by`, when given, is a predicate: only the body that still holds the claim may
    park it, so a launch that was replaced cannot put back a round somebody else is running.
    """
    at = now or datetime.now(timezone.utc)
    said = bounded_reason(reason)
    body, attempts = retry_payload(payload, said, at=at)
    if attempts > len(RETRY_BACKOFF_S):
        detail = paused_detail(said, attempts, attempt_span(body))
        await store.park(
            user_id,
            job_id,
            payload=body,
            not_before=None,
            detail=detail,
            paused=True,
            claimed_by=claimed_by,
            harness_output=harness_output,
        )
        return Parked(
            attempts=attempts, not_before=None, detail=detail, reason=said, paused=True
        )
    when = not_before if (not_before is not None and not_before > at) else (
        at + timedelta(seconds=retry_backoff(attempts))
    )
    detail = waiting_detail(said, when, attempts)
    await store.park(
        user_id,
        job_id,
        payload=body,
        not_before=when,
        detail=detail,
        claimed_by=claimed_by,
        harness_output=harness_output,
    )
    return Parked(attempts=attempts, not_before=when, detail=detail, reason=said)


__all__ = [
    "PAUSED_PREFIX",
    "PAUSED_STATUS",
    "Parked",
    "RETRY_BACKOFF_S",
    "RETRY_HISTORY",
    "TERMINAL_FAILURES",
    "TerminalJobFailure",
    "WAITING_PREFIX",
    "WAITING_REASON_CHARS",
    "REASON_LINE_CHARS",
    "attempt_span",
    "bounded_reason",
    "humanize_span",
    "reason_line",
    "park",
    "retry_backoff",
    "retry_payload",
    "waiting_detail",
    "waiting_reason",
    "waiting_reasons",
    "paused_detail",
    "paused_reason",
    "paused_reasons",
    "RESUME_HINT",
    "resumed_detail",
    "resumed_payload",
]
