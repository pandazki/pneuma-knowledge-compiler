"""Schema-evolve service flow (schema-evolve §2; Stage C).

Core owns the two pure phases (propose + reorganize) and commits nothing; this module is
the service side that drives them over the real ports, lands the reorganization on an
`evolve/<task_id>` git branch, persists the review task, and — on a human's adopt — runs a
mechanical increment-catch-up merge onto the main line.

Every write here rides the SAME per-user queue as compile (`kind="evolve"` /
`kind="evolve_adopt"`), so the git single-writer guarantee holds: an evolve branch build and
an adopt merge never race a daily compile on the same repo.

Nothing in this module calls an LLM for the adopt merge — the review-window catch-up is a
purely mechanical three-way anchor reconciliation (base branch-point ↔ evolve branch ↔
current main), so an adopt is deterministic and auditable. See `reconcile_adopt`.

Rollback (schema-evolve §2.5) has no endpoint this cut: an adopt records both `adopted_ref`
and `pre_adopt_ref` in the task's detail JSON, and the old snapshot lives in git history, so
a manual revert (reset the canonical ref to `pre_adopt_ref` + `rebuild_projection`) restores
the pre-adopt state with zero data loss.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from pneuma_knowledge_core.compile.anchor_ops import edit_claim_text, insert_block_verbatim
from pneuma_knowledge_core.compile.documents import render_document, with_derived_title
from pneuma_knowledge_core.compile.transitions import _anchor_blocks
from pneuma_knowledge_core.components import collect_evolve_evidence, component_job
from pneuma_knowledge_core.domain.archive import (
    live_documents,
    restructurable_documents,
    retired_paths,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import UserId, SourceId, extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.evolve import propose_evolution, run_evolve
from pneuma_knowledge_core.evolve.gate import (
    component_gate_checks,
    docs_from_canonical,
    docs_from_files,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import SchemaPack, compose_skill, load_skill_base
from pneuma_knowledge_core.skill.version import SkillVersion

from .groom_service import scan_oversized_documents
from .projection import rebuild_projection
from .skills import (
    MANIFEST_PATH,
    base_named_or_current,
    read_manifest,
    serialize_manifest,
    skill_for_user,
)
from .wiring import AppContext, llm_call_config

# Heading under which a window-new / revived claim is (re)inserted during adopt catch-up.
def _recovery_heading() -> str:
    """Section heading the adopt catch-up files a main-branch-only claim under."""
    return prompt("evolve.recovery_heading")


def _dropped_json(dropped) -> list[dict]:
    return [asdict(d) for d in dropped]


def _summary_line(summary: dict) -> str:
    return (
        prompt(
            "evolve.commit_message",
            moved=summary.get("moved_claims", 0),
            new_documents=summary.get("new_documents", 0),
            merged=summary.get("merged_claims", 0),
        )
    )


# --------------------------------------------------------------------- ports


def _source_bounds_port(ctx: AppContext, user: UserId):
    """`source_bounds(sid) -> block count | None`, over PG block counts (no git)."""

    async def source_bounds(source_id: str) -> int | None:
        counts = await ctx.store.block_counts(user)
        return counts.get(str(source_id))

    return source_bounds


def _fetch_source_port(ctx: AppContext, user: UserId):
    """`fetch_source(sid, start, end) -> verbatim L0 text`, over the content store."""

    async def fetch_source(source_id: str, block_start: int, block_end: int) -> str:
        try:
            return await ctx.store.fetch(
                user, SourceId(source_id), {"blocks": [block_start, block_end]}
            )
        except (KeyError, ValueError) as exc:
            return prompt("evolve.service.fetch_failed", error=exc)

    return fetch_source


def _search_knowledge_port(ctx: AppContext, user: UserId):
    """`search_knowledge(query) -> rendered L1/L2 hit list` for re-finding evidence."""
    from pneuma_knowledge_core.recall.rag import rag_recall

    async def search_knowledge(query: str) -> str:
        hits = await rag_recall(
            user,
            query,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
            embeddings=ctx.embeddings,
            limit=8,
        )
        if not hits:
            return prompt("evolve.service.search_empty", query=query)
        lines = [
            f"- [{h.source_id} ¶{h.block_start}-{h.block_end}] {h.text.strip()[:200]}"
            for h in hits
        ]
        return "\n".join(lines)

    return search_knowledge


# ----------------------------------------------------- skill composition helper


async def _compose_new_skill(
    ctx: AppContext, user: UserId, evolved_packs: list[SchemaPack]
) -> tuple[SkillVersion, str]:
    """Compose the owner's evolved skill = their base version + (their existing packs +
    the proposal's evolved packs). Returns (new_skill, manifest_content).

    Both the branch build and the adopt merge reconstruct this identically off the current
    manifest, so the manifest that lands with an adopt reloads to the same composed skill."""
    manifest = await read_manifest(ctx, user)
    if manifest is not None:
        base_version = str(
            manifest.get("base_version") or ctx.settings.user_schema_base_version
        )
        base_packs = [SchemaPack(**p) for p in manifest.get("packs", [])]
    else:
        base_version = ctx.settings.user_schema_base_version
        base_packs = []
    base_skill, _retired = base_named_or_current(ctx.settings, str(base_version))
    all_packs = base_packs + list(evolved_packs)
    new_skill = compose_skill(base_skill, all_packs)
    return new_skill, serialize_manifest(base_skill, all_packs, new_skill)


# --------------------------------------------------------------- evolve job (C3)


async def run_evolve_job(ctx: AppContext, user: UserId, job: object) -> None:
    """One `kind="evolve"` job: propose → (reorganize onto a branch) → persist a task.

    Writes NO compile_events — the user timeline gets one summary row rendered by the API
    from the task table, never mixed into the per-claim compile journal (schema-evolve §2.6)."""
    job_id = getattr(job, "job_id")
    task_id = uuid.uuid4().hex

    # Piggyback: sweep the whole repository for oversized documents before phase 1. The
    # rollover trigger only sees what a compile wrote, so a page that went quiet above the
    # threshold is never re-checked — and evolve is the lowest-frequency pass there is, which
    # makes it the cheapest place to close that gap without adding a second write-path
    # trigger. Grooming is orthogonal to schema evolution; this run's own decision is
    # unaffected either way.
    await scan_oversized_documents(ctx, user)

    current_skill = await skill_for_user(ctx, user)
    model = ctx.get_chat_model("evolve")

    # recent_events: compile events since the last evolve task (any terminal state); no prior
    # task → the full history is the increment.
    tasks = await ctx.store.list_evolve_tasks(user)  # newest first
    baseline = tasks[0]["created_at"] if tasks else None
    all_events = await ctx.store.list_compile_events(user)
    recent = [e for e in all_events if baseline is None or e["created_at"] > baseline]

    # LIVE documents only, on both halves of this job (docs/design/archive.md §2.1). The
    # proposal reasons about the shape the library has NOW, and a reorganization that could
    # see the archive could propose moving a retired page into a new family — a canonical
    # write into `archive/`, which the gate refuses anyway, computed from material the Owner
    # already said is not current. The archive is left exactly as the branch found it.
    docs = live_documents(await ctx.canonical.list(user))
    # …and one narrower set inside it. The phase-2 draft holds every live document — the
    # record among them, exactly as a daily compile's draft does, so its path and its
    # subject stay protected against a page being created over them — but the SHAPE the
    # proposal reasons about is the restructurable one. A record is not a page a
    # reorganization may re-file (every write verb refuses it, `PatchDraft`
    # `_refuse_archive_record`, and the evolve gate is the final arbiter), so counting it
    # among a family's pages would let a subject the owner retired argue for a split.
    doc_paths = [d.path for d in restructurable_documents(docs)]

    # What the enabled index components have to report about how this library is being
    # used. `None` with no component registered (or none with anything to say), and the
    # proposal's human message is then byte-identical to the one this deployment always
    # sent — the seam is invisible until something fills it.
    demand_evidence = await collect_evolve_evidence(str(user))

    proposal, reason, rationale = await propose_evolution(
        model=model,
        current_skill=current_skill,
        recent_events=recent,
        doc_paths=doc_paths,
        demand_evidence=demand_evidence,
        **llm_call_config(
            ctx, operation="evolve.propose", user_id=str(user),
            extra={"skill_version": current_skill.version},
        ),
    )

    if reason != "proposed":
        # A terminated round records WHY, not just THAT. On a no-change round the phase-1
        # rationale is the round's entire product — the verdict alone is unreadable after the
        # fact, and a schema that never moves is exactly the case where the reasoning is what
        # a reviewer needs. It lands in `detail`, which the task detail endpoint already
        # surfaces as `rationale` when no proposal exists to carry one.
        status = "no_change" if reason == "no_change" else "aborted"
        if reason == "no_change":
            detail = rationale or None
        elif rationale:
            detail = f"phase-1 {reason}: {rationale}"
        else:
            detail = f"phase-1 {reason}"
        await ctx.store.create_evolve_task(user, task_id, status=status, detail=detail)
        await ctx.store.complete(user, job_id, ok=True, detail=f"evolve: {reason}")
        return

    assert proposal is not None
    new_skill, manifest_content = await _compose_new_skill(ctx, user, proposal.packs)

    result = await run_evolve(
        user_id=user,
        model=model,
        base_docs=docs,
        new_skill=new_skill,
        proposal=proposal,
        source_bounds=_source_bounds_port(ctx, user),
        search_knowledge=_search_knowledge_port(ctx, user),
        fetch_source=_fetch_source_port(ctx, user),
        **llm_call_config(
            ctx, operation="evolve.reorganize", user_id=str(user),
            extra={"task_id": task_id, "skill_version": new_skill.version},
        ),
    )

    if result.status == "aborted":
        await ctx.store.create_evolve_task(
            user, task_id, status="aborted",
            proposal=proposal.model_dump(), summary=result.summary,
            dropped=_dropped_json(result.dropped),
            detail="evolve gate rejected: the reorganization still fails the mechanical checks.",
        )
        await ctx.store.complete(user, job_id, ok=False, detail="evolve aborted")
        return

    if result.status == "noop":
        await ctx.store.create_evolve_task(
            user, task_id, status="no_change",
            proposal=proposal.model_dump(),
            detail="the reorganization produced no change.",
        )
        await ctx.store.complete(user, job_id, ok=True, detail="evolve noop")
        return

    # completed → land the reorganization + the evolved manifest atomically on a branch.
    snaps = await ctx.canonical.snapshots(user)
    base_ref = snaps[0].ref if snaps else ""
    branch = f"evolve/{task_id}"
    files = dict(result.files)
    files[MANIFEST_PATH] = manifest_content
    await ctx.canonical.branch_commit(
        user, branch, files, f"evolve {task_id}", base=SnapshotRef(ref=base_ref)
    )
    await ctx.store.create_evolve_task(
        user, task_id, status="draft",
        base_ref=base_ref, branch=branch, proposal=proposal.model_dump(),
        summary=result.summary, dropped=_dropped_json(result.dropped),
        detail=_summary_line(result.summary),
    )
    await ctx.store.complete(user, job_id, ok=True, detail=f"evolve draft {task_id}")


# ------------------------------------------------- adopt reconciliation (C4, pure)


def _anchor_index(docs: list[CanonicalDocument]) -> dict[str, tuple[str, str]]:
    """anchor id → (path, block_text) across a document set (first-seen wins)."""
    out: dict[str, tuple[str, str]] = {}
    for d in docs:
        for anchor, text in _anchor_blocks(d.body).items():
            out.setdefault(anchor, (d.path, text))
    return out


def reconcile_adopt(
    base_docs: list[CanonicalDocument],
    branch_docs: list[CanonicalDocument],
    main_docs: list[CanonicalDocument],
) -> tuple[dict[str, str], bool, str]:
    """Mechanical increment-catch-up merge (schema-evolve §2.5): fold the review-window's
    daily-compile changes onto the evolve branch's reorganization.

    Three-way over anchors — base (branch point) ↔ branch (reorganized) ↔ main (current):

    - anchor still in branch, main changed its text in the window (`main != base`) → the
      main text wins at the branch's (new) location — nearest-wins on text, branch wins on
      layout;
    - anchor dropped by evolve (in base, not in branch): revived to its main path ONLY if the
      window changed it (`main != base`) — safety-first, never silently discard a fresh edit;
      an untouched drop stays dropped;
    - anchor new in the window (in main, not in base) → its block is (re)added to its main
      path (the whole main doc is carried over when that path never existed on the branch).

    Returns `(final_files, ok, reason)`. The terminal assertion — anchors(final) ⊇
    anchors(main) − {dropped AND window-untouched} — is mechanical: a violation means the
    merge would silently lose main content, so adopt fails (ok=False) and the task stays
    draft. `final_files` excludes the skill manifest; the caller overlays that separately.

    A document the merge leaves byte-identical to current main is serialized byte-identical;
    every other one is serialized with its DERIVED title (see the comment at the bottom)."""
    base_anchor = _anchor_index(base_docs)
    branch_anchor = _anchor_index(branch_docs)
    main_anchor = _anchor_index(main_docs)
    main_by_path = {d.path: d for d in main_docs}
    branch_by_path = {d.path: d for d in branch_docs}

    final_fm = {p: dict(d.frontmatter) for p, d in branch_by_path.items()}
    final_body = {p: d.body for p, d in branch_by_path.items()}

    # Rule A — surviving anchor whose main text moved in the window: main text wins.
    for anchor, (bpath, _btext) in branch_anchor.items():
        if anchor in base_anchor and anchor in main_anchor:
            if main_anchor[anchor][1] != base_anchor[anchor][1]:
                final_body[bpath] = edit_claim_text(
                    final_body[bpath], anchor, main_anchor[anchor][1]
                )

    # Rules B & C — window-new anchors + window-changed dropped anchors: (re)add to main path.
    to_add: list[str] = []
    for anchor, (_mpath, mtext) in main_anchor.items():
        if anchor in branch_anchor:
            continue
        if anchor not in base_anchor:
            to_add.append(anchor)  # window-new
        elif mtext != base_anchor[anchor][1]:
            to_add.append(anchor)  # dropped by evolve but changed in window → revive

    copied: set[str] = set()
    for anchor in to_add:
        mpath, mtext = main_anchor[anchor]
        # A whole-carried doc already contains EVERY one of its anchors — the copied check
        # must come first, or the 2nd+ anchor of that doc would ALSO be appended
        # individually, committing duplicate anchors that hard-fail every later compile's
        # uniqueness gate (regression case: passive trigger mid-wave → window-new topic docs).
        if mpath in copied:
            continue
        if mpath in final_body:
            final_body[mpath] = insert_block_verbatim(
                final_body[mpath], _recovery_heading(), mtext
            )
        else:
            # A path that never existed on the branch is a window-new doc (daily compile
            # cannot move a base anchor): carrying it whole covers all its window-new anchors.
            copied.add(mpath)
            final_fm[mpath] = dict(main_by_path[mpath].frontmatter)
            final_body[mpath] = main_by_path[mpath].body

    dropped_untouched = {
        anchor
        for anchor in base_anchor
        if anchor not in branch_anchor
        and anchor in main_anchor
        and main_anchor[anchor][1] == base_anchor[anchor][1]
    }
    required = set(main_anchor) - dropped_untouched
    final_anchors: set[str] = set()
    duplicated: set[str] = set()
    for body in final_body.values():
        for anchor in extract_anchors(body):
            if anchor in final_anchors:
                duplicated.add(anchor)
            final_anchors.add(anchor)
    # Uniqueness backstop: adopt commits WITHOUT a gate run, and a duplicated anchor in
    # the adopted tree hard-fails every subsequent compile touching that doc — the KB
    # would be bricked by its own uniqueness gate. Refuse the merge instead.
    if duplicated:
        return (
            {},
            False,
            f"adopt catch-up final check failed: anchors {sorted(duplicated)} are duplicated "
            "in the final tree.",
        )
    missing = required - final_anchors
    if missing:
        return (
            {},
            False,
            f"adopt catch-up final check failed: main anchors {sorted(missing)} are absent "
            "from the final tree.",
        )

    # Serialization, and the one derivation that rides it. `title` is derived from the
    # document's own `# ` heading at every write path that serializes a CHANGED document
    # (`compile/documents.with_derived_title`), and an adopt is such a write: the branch
    # rewrote bodies, the catch-up above rewrote more of them, and a stale legacy title
    # carried through unchanged would be a page whose stored name contradicts the heading a
    # reader sees. The comparison is against current MAIN, rendered UNDERIVED on both sides,
    # so the derivation is never what makes a page differ: a document this merge leaves
    # exactly as main holds it keeps its bytes, stale title included, and rides the next
    # ordinary write of the page it belongs to.
    final_files: dict[str, str] = {}
    for path in final_body:
        raw = render_document(final_fm[path], final_body[path])
        current = main_by_path.get(path)
        if current is not None and render_document(current.frontmatter, current.body) == raw:
            final_files[path] = raw
            continue
        final_files[path] = render_document(
            with_derived_title(final_fm[path], final_body[path]), final_body[path]
        )
    return final_files, True, ""


# ------------------------------------------------------------ adopt job (C4)


async def adopt_evolve_job(ctx: AppContext, user: UserId, job: object) -> None:
    """One `kind="evolve_adopt"` job: catch-up merge → commit on main → rebuild L3 → decide."""
    job_id = getattr(job, "job_id")
    payload = getattr(job, "payload", {}) or {}
    task_id = str(payload.get("task_id", ""))

    task = await ctx.store.get_evolve_task(user, task_id)
    if task is None or task["status"] != "draft":
        await ctx.store.complete(
            user, job_id, ok=False, detail="evolve adopt: the task is not an adoptable draft."
        )
        return
    branch = task["branch"]
    head = await ctx.canonical.branch_head(user, branch) if branch else None
    if head is None:
        await ctx.store.complete(
            user, job_id, ok=False, detail="evolve adopt: the branch no longer exists."
        )
        return

    base_ref = task["base_ref"]
    # The same exclusion as the branch build, on all three sides of the merge: the archive
    # is not part of the reconciliation, so no archived path enters `final_files` and the
    # adopt commit leaves every archived document byte-for-byte as it stands on main. An
    # anchor that sits in the archive is invisible on all three sides, so it is neither
    # "dropped by evolve" nor revivable — it simply is not in this conversation.
    #
    # Main is read WHOLE and filtered here rather than in the call, because the archive is
    # the one thing this merge must see without touching: the records and archived copies it
    # holds are what the two older sides are read against, below. Records stay in `main_docs`
    # — a record is a live page, and carrying it through the merge is how it comes out of the
    # adopt byte-for-byte rather than by being absent from a path-addressed commit.
    main_tree = await ctx.canonical.list(user)
    main_docs = live_documents(main_tree)
    # …and, on the two sides that PREDATE current main, one more exclusion: a path main has
    # retired. The review window is long enough for the Owner to archive a subject the
    # branch still holds as a live page, and a three-way merge that carried it would commit
    # that page back over the record standing at the same path — the retired subject
    # resurrected, by a mechanical merge, with claims nobody wrote. The record and its
    # archived copy are the two marks of that decision (`retired_paths`); main is where the
    # decision is, so main is what the other two sides are read against.
    retired = retired_paths(main_tree)
    base_docs = [
        doc
        for doc in restructurable_documents(
            await ctx.canonical.list(user, at=SnapshotRef(ref=base_ref))
        )
        if doc.path not in retired
    ]
    branch_docs = [
        doc
        for doc in restructurable_documents(
            await ctx.canonical.list(user, at=SnapshotRef(ref=branch))
        )
        if doc.path not in retired
    ]

    final_files, ok, reason = reconcile_adopt(base_docs, branch_docs, main_docs)
    if not ok:
        # adopt failed → task stays draft, detail records why (schema-evolve §2.5).
        await ctx.store.update_evolve_detail(user, task_id, reason)
        await ctx.store.complete(user, job_id, ok=False, detail=reason)
        return

    # The enabled components judge the tree this adopt would commit, against current main —
    # the second half of "a canonical field invariant belongs to canonical, not to one
    # writing channel". The branch already passed these checks when it was built, but it was
    # built against the base: the review window's daily compiles may have bound elsewhere an
    # identity the branch's new page claims, and the reconciliation above is mechanical and
    # judges nothing. This is the last moment before the merge is canonical.
    #
    # Inside the components' own window (`prepare` first), because a component's gate check
    # reads a mirror this process has not filled — an adopt job runs where no compile ran,
    # so the mirror is cold by construction and an unprepared check would fail open.
    async with component_job(str(user)):
        component_violations = component_gate_checks(
            docs_from_files(final_files), docs_from_canonical(main_docs)
        )
    if component_violations:
        reason = "adopt refused by the enabled components: " + " ".join(
            v.render() for v in component_violations
        )
        await ctx.store.update_evolve_detail(user, task_id, reason)
        await ctx.store.complete(user, job_id, ok=False, detail=reason)
        return

    # Carry the evolved skill manifest from the branch onto main so the skill flips with the
    # data — an adopt reloads to the evolved composed skill (closing the manifest-continuity
    # loop).
    manifest_content = await ctx.canonical.read_meta_at(user, MANIFEST_PATH, branch)
    if manifest_content is not None:
        final_files[MANIFEST_PATH] = manifest_content

    snaps = await ctx.canonical.snapshots(user)
    pre_adopt_ref = snaps[0].ref if snaps else ""

    adopted = await ctx.canonical.commit_patch(
        user, final_files, message=f"adopt evolve {task_id}"
    )
    await rebuild_projection(ctx, user, adopted.ref)
    await ctx.store.decide_evolve_task(
        user, task_id, "adopted",
        detail=json.dumps(
            {"adopted_ref": adopted.ref, "pre_adopt_ref": pre_adopt_ref},
            ensure_ascii=False,
        ),
    )
    await ctx.canonical.delete_branch(user, branch)
    await ctx.store.complete(user, job_id, ok=True, detail=f"evolve adopted {task_id}")


# ------------------------------------------------- drop / expiry / trigger (C4, C5)


async def drop_task(ctx: AppContext, user: UserId, task_id: str) -> bool:
    """Drop a draft evolve task: delete the branch, decide(dropped). Returns False when the
    task is not a live draft."""
    task = await ctx.store.get_evolve_task(user, task_id)
    if task is None or task["status"] != "draft":
        return False
    if task["branch"]:
        await ctx.canonical.delete_branch(user, task["branch"])
    await ctx.store.decide_evolve_task(
        user, task_id, "dropped", detail="the owner discarded this proposal."
    )
    return True


async def _maybe_expire(ctx: AppContext, user: UserId, task: dict) -> dict:
    """Lazily expire a stale draft (schema-evolve §2.5): a draft past the TTL is auto-dropped
    (conservative default), its branch deleted. Returns the (possibly updated) task."""
    if task["status"] != "draft" or task["created_at"] is None:
        return task
    age_hours = (
        datetime.now(timezone.utc) - task["created_at"]
    ).total_seconds() / 3600.0
    if age_hours <= ctx.settings.evolve_draft_ttl_hours:
        return task
    if task["branch"]:
        await ctx.canonical.delete_branch(user, task["branch"])
    await ctx.store.decide_evolve_task(
        user,
        task["task_id"],
        "expired",
        detail="the draft went undecided past the review window and expired automatically.",
    )
    refreshed = await ctx.store.get_evolve_task(user, task["task_id"])
    return refreshed if refreshed is not None else task


async def list_tasks_with_expiry(ctx: AppContext, user: UserId) -> list[dict]:
    """The user's evolve tasks, running the lazy expiry sweep first (newest first)."""
    tasks = await ctx.store.list_evolve_tasks(user)
    out = []
    for task in tasks:
        out.append(await _maybe_expire(ctx, user, task))
    return out


async def get_task_with_expiry(
    ctx: AppContext, user: UserId, task_id: str
) -> dict | None:
    task = await ctx.store.get_evolve_task(user, task_id)
    if task is None:
        return None
    return await _maybe_expire(ctx, user, task)


async def has_pending_evolve(ctx: AppContext, user: UserId) -> bool:
    """True when a draft is awaiting review OR an evolve/adopt job is queued/claimed — the
    single-flight guard for both the manual trigger (409) and the passive trigger."""
    tasks = await ctx.store.list_evolve_tasks(user)
    if any(t["status"] == "draft" for t in tasks):
        return True
    jobs = await ctx.store.list_jobs(user)
    return any(
        j["kind"] in ("evolve", "evolve_adopt") and j["status"] in ("queued", "claimed")
        for j in jobs
    )


async def maybe_trigger_evolve(ctx: AppContext, user: UserId) -> str | None:
    """Passive trigger (schema-evolve §2.1): after a committed compile, fire an evolve job
    when — since the last evolve task — enough NEW documents AND new anchors accrued, and no
    evolve is already in flight. New documents are counted across ALL families (any path a
    compile has written), not just memory/topics/: evolve reorganizes the whole KB, so the
    growth that warrants it is whole-KB growth — a corpus whose contract files everything
    under e.g. work/products/ or memory/people/ deserves structural re-examination exactly
    as much as a topics-heavy one, and counting only one family left such corpora unable to
    ever trigger. All statistics come from compile_events (no git read). Returns the
    enqueued job id, or None."""
    settings = ctx.settings
    if not settings.evolve_auto_trigger:
        return None
    if await has_pending_evolve(ctx, user):
        return None

    tasks = await ctx.store.list_evolve_tasks(user)
    baseline = tasks[0]["created_at"] if tasks else None
    events = await ctx.store.list_compile_events(user)

    def after(e) -> bool:
        return baseline is None or e["created_at"] > baseline

    window = [e for e in events if after(e)]
    new_claims = sum(1 for e in window if e["type"] == "claim_added")
    # New documents (any family): paths first seen strictly in the window (no event
    # at/before the baseline).
    docs_before = {e["path"] for e in events if not after(e)}
    docs_after = {
        e["path"] for e in window if e["type"] == "claim_added"
    }
    new_docs = docs_after - docs_before

    if (
        len(new_docs) >= settings.evolve_trigger_topic_docs
        and new_claims >= settings.evolve_trigger_new_claims
    ):
        return await ctx.store.enqueue(user, "evolve", {})
    return None
