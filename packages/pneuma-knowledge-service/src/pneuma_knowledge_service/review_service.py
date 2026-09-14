"""The review round: the check reaching the Steward as a round of its own (§3.2).

The check (`lens.py`) lists what an insider standing at the page can see against the
contract — a page that names another subject and never links it, a title that collides with a
sibling, a chronology whose dated sections arrive in ingest order. Reading it changes
nothing. What acts on it is THIS: a `review` job on the canonical lane, whose round opens a
draft over the whole library with no source, whose task is that report, and whose instruction
is to repair what a round can repair through the ordinary draft verbs under the ordinary
gate — and to say in the brief what it left and why.

Three properties are the whole design, and each is mechanical rather than asked for:

- **its own round.** The report reaches no other job's task. A compile is about its source;
  putting the library's shape into it would make every compile answer for the whole library
  and would put a finding's account into a place the gate never judged it.
- **the ordinary verbs, the ordinary gate.** Nothing here is a write path. The round holds a
  draft like any other, every write is post-checked like any other, and `pkc draft finish`
  judges it with the same predicates. A repair that cannot pass the gate does not land.
- **the Owner asks for it.** `pkc jobs enqueue review` and `POST /v1/users/{uid}/jobs/review`,
  and nothing else in this version. Scheduling it is a later decision (§8), and a round that
  scheduled itself before anyone had watched its unattended behaviour would be exactly the
  thing the design defers.
"""

from __future__ import annotations

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.prompts import prompt


#: The job kind. `job_lanes.py` classifies it into the canonical lane by this spelling, and
#: `tests/test_job_lanes.py` pins the two against each other.
REVIEW_JOB_KIND = "review"

#: The catalog key carrying the round's one instruction. ONE sentence-set from the catalog,
#: not a briefing composed here: what the Steward is asked to do is prose a deployment may
#: reword through the overlay seam, like every other sentence a round reads.
REVIEW_TASK_KEY = "steward.review.task"

#: And the key carrying the other thing this round can be asked, which is nothing. A library
#: the check reads clean must be told so in words rather than handed "repair what a round can
#: repair" over an empty list: the instruction alone, under a report with no findings in it,
#: is an invitation to find something — and the one write this round must never make is a
#: claim nobody asked for.
REVIEW_CLEAN_KEY = "steward.review.clean"


def render_check_task(report, *, bound: int = 0) -> str:
    """The check's report as the round's task text, bounded, with the instruction under it.

    Called when the round OPENS and never at enqueue: a review job may sit in the queue
    behind a compile that repairs half of what the check found, and a task frozen at enqueue
    would send the round after findings that no longer exist. That is also why the queued row
    carries no payload — there is nothing about the library for it to hold.

    The report first and the instruction after it, because the instruction is written about
    the report ("repair what a round can repair") and a reader meets the subject before the
    thing said about it.

    `bound` is `agent_task_structure_chars` — the same bound a compile task's source material
    stops at. A library with three hundred findings must not hand a harness a task the size of
    its own library, and what is cut is STATED in findings rather than in characters: the
    round is told how many it did not see, and `pkc library review --page N` is where the rest
    is. Cutting silently would tell the round the library was cleaner than it is, which is the
    one thing a reading of the library's shape must never do.
    """
    from .cli.lens import check_head, finding_blocks

    findings = list(report.findings)
    head = check_head(report)
    if not findings:
        # The empty case, stated. The head already says `0 finding(s)`; what it does not say
        # is what to do about it, and the round's ordinary instruction — repair what a round
        # can repair — says the opposite of the truth over an empty list.
        return "\n".join(head).strip("\n") + "\n\n" + prompt(REVIEW_CLEAN_KEY).strip("\n")
    blocks = finding_blocks(findings)
    kept: list[list[str]] = []
    spent = len("\n".join(head))
    for block in blocks:
        text = "\n".join(block)
        if bound > 0 and kept and spent + len(text) + 1 > bound:
            break
        kept.append(block)
        spent += len(text) + 1
    lines = [*head, *(line for block in kept for line in block)]
    if len(kept) < len(blocks):
        lines.append(
            f"\n…and {len(blocks) - len(kept)} more finding(s) not shown here — "
            "`pkc library review --page 2` for the next page."
        )
    return "\n".join(lines).strip("\n") + "\n\n" + prompt(REVIEW_TASK_KEY).strip("\n")


async def enqueue_review(ctx, user_id: UserId) -> str:
    """Queue one review round for this library. Returns the job id.

    No payload: the round is about the library at the moment it opens, and a payload naming a
    ref would freeze a reading the round then works against instead of the library it holds.
    """
    return await ctx.store.enqueue(user_id, REVIEW_JOB_KIND, {})


__all__ = [
    "REVIEW_CLEAN_KEY",
    "REVIEW_JOB_KIND",
    "REVIEW_TASK_KEY",
    "enqueue_review",
    "render_check_task",
]
