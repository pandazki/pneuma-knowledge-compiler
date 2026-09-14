"""The review round's door: `open`, and nothing else of its own (§3.2).

A review round is an ORDINARY draft round whose material happens to be the library rather
than a source. So this module is deliberately thin: it opens the draft and renders the two
surfaces, and every other command of the round — `pkc draft read-document`, `edit-claim`,
`retitle`, `reorder-chronology`, `status`, `check`, `finish`, `abandon` — is the shared one
in `cli/draft.py`, judged by the shared gate. There is no second rulebook here, and the
Steward types the same verbs it types on any other day.

What differs from a compile open is exactly two things, and both follow from there being no
source: the task is the check's report instead of the material (`review_service.py`), and the
round's budget is sized by the FINDINGS rather than by the sources, because a finding is what
this round reads and writes about.
"""

from __future__ import annotations

from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import first_round_budget
from pneuma_knowledge_core.compile.session import DraftSession, content_sha256
from pneuma_knowledge_core.domain.archive import live_documents
from pneuma_knowledge_core.skill.contract import render_system_contract

from ..lens import read_check_over
from ..review_service import REVIEW_JOB_KIND, render_check_task
from . import draft as shared
from .draft import DraftRuntime


async def build_runtime(ctx, user_id, *, executor=None) -> DraftRuntime:
    """This tenant's runtime for a review round — the compile runtime, told which kind it is.

    The same adapters, the same skill, the same gate settings: what `kind` changes is which
    door the draft answers to (`draft_door`) and which lane's single-writer rule it takes,
    and the review round's answers to both are the compile round's.
    """
    from .runtime import build_runtime as build

    return await build(ctx, user_id, executor=executor, kind=REVIEW_JOB_KIND)


@shared.draft_command
async def open_round(
    rt: DraftRuntime, job_id: str, *, claim: bool = True
) -> tuple[int, str, str]:
    """`open`, as the two surfaces rather than as printed output: `(code, system, task)`.

    `claim=False` is the worker's unattended path: the job is ALREADY claimed by the drain
    that is about to hand it to a harness, and claiming it twice would fail on the queue's own
    single-in-flight rule.

    A resumed round re-renders nothing: the task is a reading of the library, and the round is
    editing that library, so a re-read half-way through would hand the Steward a report about
    the repairs it has already made. The surfaces are kept on the session, exactly as the
    evolve round keeps its own.
    """
    existing = await rt.drafts.get(rt.user_id, job_id)
    if existing is not None:
        await shared.require_owner(rt, job_id)
        if existing.get("kind", "compile") != REVIEW_JOB_KIND:
            print("this job has a different kind of draft", file=rt.err)
            return shared.EXIT_REFUSED, "", ""
        session = DraftSession.from_state(existing.get("session") or {})
        await rt.drafts.put(rt.user_id, job_id, existing)
        return (
            shared.EXIT_OK,
            session.context.get("system_text", ""),
            session.context.get("task_text", ""),
        )

    # One open round per LANE, and the review round is in the canonical one: it holds the
    # library's single writer for as long as it is open, exactly as a compile does.
    for other_id in await shared.open_drafts_in_lane(rt, shared.lane_of(REVIEW_JOB_KIND)):
        await shared.require_owner(rt, other_id)
        raise shared.DraftOwnershipError(
            f"draft for job {other_id} is already open; finish or abandon it first"
        )

    candidate = await rt.jobs.get_job(rt.user_id, job_id)
    if candidate is None:
        print(f"no such job for this user: {job_id}", file=rt.err)
        return shared.EXIT_NOTHING, "", ""
    if getattr(candidate, "kind", "compile") != REVIEW_JOB_KIND:
        print(f"job {job_id} is not a review job", file=rt.err)
        return shared.EXIT_REFUSED, "", ""

    outside = await shared.outside_write(rt)
    if outside:
        print(outside, file=rt.err)
        return shared.EXIT_REFUSED, "", ""

    job = (
        await rt.jobs.claim(rt.user_id, job_id, claimed_by=rt.draft_executor)
        if claim
        else candidate
    )
    if job is None or getattr(job, "status", "claimed") != "claimed":
        print(
            f"job {job_id} could not be claimed; this user may have work in flight",
            file=rt.err,
        )
        return (shared.EXIT_NOTHING if claim else shared.EXIT_REFUSED), "", ""
    if not claim and getattr(job, "claimed_by", "worker") not in ("worker", rt.draft_executor):
        raise shared.DraftOwnershipError(
            f"job {job_id} is claimed by {job.claimed_by}; cannot join its round"
        )

    # Over what the RUNTIME holds, not over an application context: a `DraftRuntime` carries
    # `canonical` and a resolved `skill`, and has no `ctx` to resolve anything out of. The
    # templates are the round's own — the same ones the draft's path ownership is judged by,
    # so the check cannot find a family the gate then refuses.
    report, documents = await read_check_over(
        rt.canonical, rt.user_id, rt.skill.path_templates
    )
    task_text = render_check_task(report, bound=int(rt.task_structure_chars))
    # The contract alone, with no owner or time context: those two carry the material's
    # situation, and this round has no material. What it needs from the system surface is the
    # write contract and the families — which is what a Steward is judged against here.
    system_text = render_system_contract(rt.skill)

    base_docs = live_documents(list(documents))
    draft = PatchDraft.from_canonical(
        base_docs,
        rt.skill.path_templates,
        overview_budget_chars=rt.overview_budget_chars,
        owner_voice_templates=rt.skill.owner_voice_templates,
        owner_authored_blocks=rt.owner_authored_blocks,
    )
    session = DraftSession(
        user_id=str(rt.user_id),
        job_id=job_id,
        kind=REVIEW_JOB_KIND,
        **shared.ownership_fields(rt),
        round="first",
        # Sized by the findings, by the same formula and the same floor a compile's sources
        # size it with: a round must be able to read every page it is about and write at
        # least twice per page, and no round is smaller than the historical floor.
        budget=first_round_budget(len(report.findings), rt.max_tool_calls),
        task_sha256=content_sha256(task_text),
        skill_id=rt.skill.skill_id,
        skill_version=rt.skill.version,
        skill_content_hash=rt.skill.content_hash,
        overview_budget_chars=rt.overview_budget_chars,
        overview_required_after_claims=rt.overview_required_after_claims,
        max_tool_calls=rt.max_tool_calls,
        commit_message="review: repair what the check found",
        context={"system_text": system_text, "task_text": task_text},
    )
    await shared._store(rt, draft, session)
    return shared.EXIT_OK, system_text, task_text


__all__ = ["build_runtime", "open_round"]
