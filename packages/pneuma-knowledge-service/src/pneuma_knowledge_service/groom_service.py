"""Rollover (`groom`) service flow: the trigger, the job, the commit, the projection.

Core owns every mechanical decision and the groom-only gate (`compile.rollover`) and commits
nothing; this module drives them over the real ports.

Three entry points:

- `heal_volume_links_for_user` — a one-shot repair for knowledge bases groomed BEFORE the
  channel compensated for a volume's extra depth. Purely mechanical (no model call at all),
  idempotent, and a no-op commit-wise on a repo that has nothing to heal.
- `maybe_trigger_rollover` — called after a compile COMMITS. It is a size check over the
  documents that compile actually wrote, nothing more: no LLM, no git read, no history sweep.
  An oversized document that this compile did not touch is left alone and rolls over the next
  time it is written, which is what keeps the trigger cheap and non-surprising.
- `scan_oversized_documents` — the same size check over the WHOLE repository, for the blind
  spot the write trigger has by construction (see its docstring).
- `run_groom_job` — one `kind="groom"` job: exactly one document, exactly one new volume.

Both ride the SAME per-user queue as compile and evolve, so the git single-writer guarantee
holds for free: a rollover never races a daily compile or an evolve build on the same repo.

A groom is all-or-nothing. The gate has no repair round and the job has no retry loop: a
violation, a failed overview call, or a document that turns out not to be rollable completes
the job with the reason recorded and leaves canonical byte-identical. The next compile that
writes that document triggers a fresh attempt.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.compile.rollover import (
    build_rollover,
    commit_message,
    heal_commit_message,
    heal_volume_links,
    is_archive_volume,
    needs_rollover,
    plan_rollover,
    write_overview,
)
from pneuma_knowledge_core.compile.runner import with_skill_trailer
from pneuma_knowledge_core.domain.ids import UserId, extract_anchors

from .projection import sync_projection
from .skills import skill_for_user
from .wiring import AppContext, llm_call_config

#: The job kind. On the shared per-user queue next to compile / index / evolve.
GROOM_JOB_KIND = "groom"


async def _enqueue_oversized(
    ctx: AppContext, user: UserId, candidates: Mapping[str, str]
) -> list[str]:
    """Enqueue one groom job per oversized document in `candidates`. Returns the job ids.

    The single place the trigger decision is made, so the write-path trigger and the
    whole-repository sweep cannot drift into two different notions of "oversized" or two
    different idempotency rules. A document already awaiting a groom is skipped — a second
    job for the same path would open a second volume for a cut that has not happened yet.
    """
    threshold = ctx.settings.rollover_threshold_chars
    if threshold <= 0:
        return []

    jobs = await ctx.store.list_jobs(user)
    pending = {
        str((job.get("payload") or {}).get("path") or "")
        for job in jobs
        if job["kind"] == GROOM_JOB_KIND and job["status"] in ("queued", "claimed")
    }

    enqueued: list[str] = []
    for path in sorted(candidates):
        content = candidates[path]
        if not needs_rollover(content, threshold) or path in pending:
            continue
        enqueued.append(await ctx.store.enqueue(user, GROOM_JOB_KIND, {"path": path}))
    return enqueued


async def maybe_trigger_rollover(
    ctx: AppContext,
    user: UserId,
    files: Mapping[str, str],
    touched_paths: Iterable[str],
) -> list[str]:
    """Enqueue a groom job per oversized document this compile wrote. Returns the job ids.

    `files` is the committed path→file-content table and `touched_paths` the paths the compile
    actually changed (derived from its events), so the check is O(changed documents) and reads
    nothing.
    """
    return await _enqueue_oversized(
        ctx,
        user,
        {path: files[path] for path in set(touched_paths) if path in files},
    )


async def scan_oversized_documents(ctx: AppContext, user: UserId) -> list[str]:
    """The write trigger's blind spot, swept: every oversized document in the repository.

    `maybe_trigger_rollover` only considers what a compile just wrote, which is what keeps it
    free. The cost of that is permanent: a page that crosses the threshold and then goes
    QUIET is never written again, so it is never re-checked, and it stays oversized forever.
    Observed in a 208-day replay — a 44 000-character page sat above a 40 000 threshold
    untouched while its two noisier neighbours were groomed.

    So the repository is swept too, just rarely: this hangs off the evolve job, the
    lowest-frequency scheduled pass the system has, rather than becoming a second trigger on
    the write path. It re-reads canonical and re-renders each document to the bytes that were
    committed, so "oversized" means the same thing here as it does after a compile. Archive
    volumes are excluded — frozen history is never rolled over again, and enqueueing jobs
    that can only report "cannot be rolled over" is noise. Idempotent through the shared
    pending-job skip.
    """
    docs = await ctx.canonical.list(user)
    return await _enqueue_oversized(
        ctx,
        user,
        {
            doc.path: render_document(doc.frontmatter, doc.body)
            for doc in docs
            if not is_archive_volume(doc)
        },
    )


async def heal_volume_links_for_user(ctx: AppContext, user: UserId) -> dict:
    """Repair the volume links an older groom left resolving one level short. No model call.

    Rides the groom channel because it writes archive volumes, which no compile may touch —
    and it is a DEFECT FIX, not a knowledge edit: every byte outside a link href is untouched
    and every rewritten link ends up at the document its text always meant. Returns a summary
    dict; commits and re-projects only when something was actually healed, so running it twice
    leaves the second run with nothing to write.
    """
    docs = await ctx.canonical.list(user)
    result = heal_volume_links(docs)
    summary: dict = {
        "status": result.status,
        "healed_links": result.healed_links,
        "documents": sorted(result.files),
        "dead_before": result.dead_before,
        "dead_after": result.dead_after,
    }
    if result.status != "ready":
        if result.violations:
            summary["violations"] = [v.render() for v in result.violations]
        return summary

    skill = await skill_for_user(ctx, user)
    snapshot = await ctx.canonical.commit_patch(
        user,
        result.files,
        message=with_skill_trailer(heal_commit_message(result.healed_links), skill),
    )
    projection = await sync_projection(ctx, user, snapshot.ref)
    summary["snapshot_ref"] = snapshot.ref
    summary["projected"] = projection.total
    return summary


async def run_groom_job(ctx: AppContext, user: UserId, job: object) -> None:
    """One `kind="groom"` job: plan the cut → write the history card → gate → commit → project.

    The only model call is the history card, and it is the only step that can fail for a
    non-mechanical reason. Every terminal state completes the job (never leaves it claimed)
    and records WHY in the job detail, because a rollover that quietly did not happen looks
    exactly like a rollover that was never triggered.
    """
    job_id = getattr(job, "job_id")
    payload = getattr(job, "payload", {}) or {}
    path = str(payload.get("path") or "")

    docs = await ctx.canonical.list(user)
    active = next((d for d in docs if d.path == path), None)
    if active is None:
        await ctx.store.complete(
            user, job_id, ok=True, detail=f"groom: {path} no longer exists"
        )
        return

    skill = await skill_for_user(ctx, user)
    plan = plan_rollover(
        active,
        docs,
        path_templates=skill.path_templates,
        keep_recent_chars=ctx.settings.rollover_keep_recent_chars,
    )
    if plan is None:
        # Not an error: a document the skill does not own has no history directory (nor does a
        # volume, so frozen history never grows a second floor), and a document whose whole body
        # already fits the retained tail has nothing to archive.
        await ctx.store.complete(
            user, job_id, ok=True, detail=f"groom: {path} cannot be rolled over"
        )
        return

    # The anchors an overview point may legitimately name: this rollover's archive plus every
    # volume already frozen for this subject. Enforced again by the gate — this only keeps the
    # model's own output from being silently wrong.
    known = set(extract_anchors(plan.archived_body))
    for volume_path, _claims, _span in plan.volumes[:-1]:
        volume = next((d for d in docs if d.path == volume_path), None)
        if volume is not None:
            known |= set(extract_anchors(volume.body))

    points, reason = await write_overview(
        model=ctx.get_chat_model("compile"),
        plan=plan,
        known_anchors=known,
        **llm_call_config(
            ctx,
            operation="compile.groom",
            user_id=str(user),
            extra={
                "job_id": str(job_id),
                "document_path": path,
                "volume_path": plan.volume_path,
                "archived_claims": plan.archived_claims,
                "skill_version": skill.version,
            },
        ),
    )
    if reason != "written":
        await ctx.store.complete(
            user, job_id, ok=False, detail=f"groom: history card {reason}"
        )
        return

    result = build_rollover(plan, points, docs, path_templates=skill.path_templates)
    if result.status == "rejected":
        await ctx.store.complete(
            user,
            job_id,
            ok=False,
            detail="; ".join(v.render() for v in result.violations),
        )
        return

    snapshot = await ctx.canonical.commit_patch(
        user, result.files, message=with_skill_trailer(commit_message(plan), skill)
    )
    # The claim projection is keyed by (document_path, anchor), so the archived claims land as
    # a delete-at-the-old-path + insert-at-the-volume-path delta through the ordinary compile
    # channel. L1/L2 are untouched by design: they index L0 blocks by source, and a document
    # path appears nowhere in their payloads.
    projection = await sync_projection(ctx, user, snapshot.ref)
    await ctx.store.complete(
        user,
        job_id,
        ok=True,
        detail="groom:"
        + json.dumps(
            {
                "path": path,
                "volume": result.volume_path,
                "archived_claims": result.archived_claims,
                "overview_points": result.overview_points,
                "projected": projection.total,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        snapshot_ref=snapshot.ref,
    )
