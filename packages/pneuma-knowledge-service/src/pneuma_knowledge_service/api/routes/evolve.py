"""Schema-evolve API surface (schema-evolve §2.5): trigger, review, adopt, drop + the
current effective skill (the "tailored for you" panel).

Every write (manual trigger, adopt) is ENQUEUED onto the same per-user queue the compiler
drains — the API only accepts and reports queue state, never touches git inline — so the
single-writer guarantee holds. Reads run the lazy draft-expiry sweep first (no background
timer): a stale draft is auto-dropped the next time the list/detail is asked for.
"""

from __future__ import annotations

from typing import Any

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.skill import claim_labels_for
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...evolve_service import (
    drop_task,
    get_task_with_expiry,
    has_pending_evolve,
    list_tasks_with_expiry,
)
from ...skills import read_manifest, skill_for_user
from ...wiring import AppContext

router = APIRouter(prefix="/v1/users/{user_id}")


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


class EvolveTaskSummaryOut(BaseModel):
    task_id: str
    status: str
    detail: str | None
    summary: dict[str, Any] | None
    created_at: str | None
    decided_at: str | None


class ChangedFileOut(BaseModel):
    path: str
    old_body: str
    new_body: str


class EvolveTaskDetailOut(BaseModel):
    task_id: str
    status: str
    detail: str | None
    summary: dict[str, Any] | None
    dropped: list[dict[str, Any]]
    proposal: dict[str, Any] | None
    rationale: str | None
    base_ref: str | None
    branch: str | None
    created_at: str | None
    decided_at: str | None
    # Review payload: per-file old (base_ref) vs new (branch) body. Empty once adopted/dropped
    # (the branch is gone) — the detail degrades to summary-only.
    changed_files: list[ChangedFileOut]


class EnqueuedOut(BaseModel):
    job_id: str
    status: str = "queued"


class DroppedOut(BaseModel):
    dropped: bool


class ClaimLabelOut(BaseModel):
    label: str
    name: str
    description: str
    tier: str


class SkillOut(BaseModel):
    version: str
    content_hash: str
    base_version: str
    path_templates: list[str]
    # Compact pack summary (id/origin/templates) — the UI's "tailored for you" panel.
    packs: list[dict[str, Any]]
    # Claim-prefix vocabulary this skill declares (§5 strength tiers) — the UI renders it as a
    # generic badge mechanism instead of hardcoding any specific word.
    claim_labels: list[ClaimLabelOut]


def _summary_out(t: dict) -> EvolveTaskSummaryOut:
    return EvolveTaskSummaryOut(
        task_id=t["task_id"],
        status=t["status"],
        detail=t["detail"],
        summary=t["summary"],
        created_at=_iso(t["created_at"]),
        decided_at=_iso(t["decided_at"]),
    )


@router.post("/evolve", response_model=EnqueuedOut)
async def trigger_evolve(user_id: str, request: Request) -> EnqueuedOut:
    """Manually fire a schema-evolve run. 409 when a draft is already awaiting review or an
    evolve job is already queued/in-flight (single-flight per user)."""
    ctx = _ctx(request)
    user = UserId(user_id)
    if await has_pending_evolve(ctx, user):
        raise HTTPException(
            status_code=409,
            detail="an evolve draft is already awaiting review, or an evolve job is queued.",
        )
    job_id = await ctx.store.enqueue(user, "evolve", {})
    return EnqueuedOut(job_id=job_id)


@router.get("/evolve", response_model=list[EvolveTaskSummaryOut])
async def list_evolve(user_id: str, request: Request) -> list[EvolveTaskSummaryOut]:
    """All evolve tasks (newest first); runs the lazy stale-draft expiry sweep first."""
    tasks = await list_tasks_with_expiry(_ctx(request), UserId(user_id))
    return [_summary_out(t) for t in tasks]


@router.get("/evolve/{task_id}", response_model=EvolveTaskDetailOut)
async def get_evolve(
    user_id: str, task_id: str, request: Request
) -> EvolveTaskDetailOut:
    ctx = _ctx(request)
    user = UserId(user_id)
    task = await get_task_with_expiry(ctx, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"evolve task not found: {task_id}")

    proposal = task["proposal"] or None
    rationale = proposal.get("rationale") if isinstance(proposal, dict) else None

    changed: list[ChangedFileOut] = []
    branch = task["branch"]
    if task["status"] == "draft" and branch:
        head = await ctx.canonical.branch_head(user, branch)
        if head is not None:
            base_docs = await ctx.canonical.list(
                user, at=SnapshotRef(ref=task["base_ref"])
            )
            branch_docs = await ctx.canonical.list(user, at=SnapshotRef(ref=branch))
            base_by = {d.path: d.body for d in base_docs}
            branch_by = {d.path: d.body for d in branch_docs}
            for path in sorted(set(base_by) | set(branch_by)):
                old = base_by.get(path, "")
                new = branch_by.get(path, "")
                if old != new:
                    changed.append(
                        ChangedFileOut(path=path, old_body=old, new_body=new)
                    )

    return EvolveTaskDetailOut(
        task_id=task["task_id"],
        status=task["status"],
        detail=task["detail"],
        summary=task["summary"],
        dropped=task["dropped"] or [],
        proposal=proposal,
        rationale=rationale,
        base_ref=task["base_ref"],
        branch=branch,
        created_at=_iso(task["created_at"]),
        decided_at=_iso(task["decided_at"]),
        changed_files=changed,
    )


@router.post("/evolve/{task_id}/adopt", response_model=EnqueuedOut, status_code=202)
async def adopt_evolve(
    user_id: str, task_id: str, request: Request
) -> EnqueuedOut:
    """Accept a draft: enqueue the adopt job (mechanical catch-up merge → commit on main →
    rebuild L3). 404 for an unknown task, 409 when it is not a live draft."""
    ctx = _ctx(request)
    user = UserId(user_id)
    task = await get_task_with_expiry(ctx, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"evolve task not found: {task_id}")
    if task["status"] != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"task status is {task['status']}, so it cannot be adopted.",
        )
    job_id = await ctx.store.enqueue(user, "evolve_adopt", {"task_id": task_id})
    return EnqueuedOut(job_id=job_id)


@router.post("/evolve/{task_id}/drop", response_model=DroppedOut)
async def drop_evolve(
    user_id: str, task_id: str, request: Request
) -> DroppedOut:
    """Discard a draft: delete its branch, record it dropped (immediate, not queued)."""
    ctx = _ctx(request)
    user = UserId(user_id)
    task = await get_task_with_expiry(ctx, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"evolve task not found: {task_id}")
    ok = await drop_task(ctx, user, task_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"task status is {task['status']}, so it cannot be discarded.",
        )
    return DroppedOut(dropped=True)


@router.get("/skill", response_model=SkillOut)
async def get_skill(user_id: str, request: Request) -> SkillOut:
    """The owner's CURRENT effective composed skill — the "tailored for you" panel. Version +
    content hash + base version + the pack list it composes + the path-ownership templates."""
    ctx = _ctx(request)
    user = UserId(user_id)
    skill = await skill_for_user(ctx, user)
    manifest = await read_manifest(ctx, user)
    if manifest is not None:
        base_version = str(
            manifest.get("base_version") or ctx.settings.user_schema_base_version
        )
        packs = [
            {
                "pack_id": p.get("pack_id"),
                "origin": p.get("origin"),
                "extra_path_templates": p.get("extra_path_templates", []),
            }
            for p in manifest.get("packs", [])
        ]
    else:
        base_version = ctx.settings.user_schema_base_version
        packs = []
    return SkillOut(
        version=skill.version,
        content_hash=skill.content_hash,
        base_version=base_version,
        path_templates=list(skill.path_templates),
        packs=packs,
        claim_labels=[ClaimLabelOut(**label.model_dump()) for label in claim_labels_for(skill)],
    )
