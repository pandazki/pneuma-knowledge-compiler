#!/usr/bin/env python
"""Rebuild ALL derived indexes (L1 + L2 + L3) for one or more users from the authorities.

The canonical L0 (PG sources/blocks) and L3 canonical git repos are the only authorities
(invariant I2). Everything else — L1 Meili lexical, L2 Qdrant vectors, and the L3
projection (PG canonical_claims + Meili claims + Qdrant claim layer) — is derived and
rebuildable. Use this after a Qdrant/Meili wipe, a container/version switch, an embedding
model change (dimension change), or a chunk-strategy change, when a single layer is not
enough and you want the whole retrieval surface reconciled to the current config.

What it does per user, reporting before/after so you can eyeball the reconciliation:
  L1  re-index every source's stored blocks into Meili (drops the user's stale index first);
  L2  re-chunk + re-embed every source via the configured strategy (semantic replays its
      chunk manifest for a byte-deterministic rebuild — see docs/getting-started.md);
  L3  re-project canonical HEAD onto PG claims + Meili claims + Qdrant claim layer;
  C   re-derive the framework's access statistics AND every enabled index component's own
      projection (e.g. the `time` component's per-block calendar rows, re-normalized under
      the CURRENT timezone) — enqueued as one `recall_rebuild` job and drained here, so it
      cannot interleave with that user's in-flight `recall_projection` jobs.

Usage:
    uv run python scripts/ops/rebuild_derived.py <user-id>
    uv run python scripts/ops/rebuild_derived.py --all

Run against the compose stack (docker compose -f infra/docker-compose.yml up -d --wait).
Semantic chunking + embeddings need a real OPENROUTER_API_KEY in .env; the L2 step is the
only one that calls a provider (L1 and L3-lexical are mechanical; L3 vectors re-embed).
"""

from __future__ import annotations

import asyncio
import sys

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _env  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.access_stats import (
    RECALL_PROJECTION_JOB_KIND,
    RECALL_REBUILD_JOB_KIND,
    run_recall_projection_job,
    run_recall_rebuild_job,
)
from pneuma_knowledge_service.projection import rebuild_projection
from pneuma_knowledge_service.settings import Settings, get_settings
from pneuma_knowledge_service.wiring import build_context, embed_l2_chunks

from reindex_l2 import _chunks_for


async def all_users(ctx) -> list[UserId]:
    """Every tenant with something derived to rebuild, from ALL authoritative substrates.

    L0 sources are no longer the only one. A component projection may be derived from the
    use-side records (`consultations`), and a tenant can ask business questions — and
    accumulate misses — before it has imported anything at all. Enumerating from `sources`
    alone made that tenant's projection unrepairable by the very script I7 names as what
    makes it derived.
    """
    users = set(await ctx.store.list_users())
    lister = getattr(ctx.store, "list_consultation_users", None)
    if lister is not None:
        users |= set(await lister())
    return [UserId(u) for u in sorted(users)]


async def rebuild_user(ctx, user_id: UserId) -> None:
    sources = await ctx.store.list(user_id)
    l2_before = await ctx.vectors.count_chunks(user_id)
    print(
        f"\n== {user_id}: {len(sources)} source(s) | "
        f"L2 chunks before = {l2_before} =="
    )
    if not sources:
        # L1/L2/L3 are all functions of the sources, so there is nothing there to redo — but
        # a component projection may be derived from the use-side records instead, and that
        # tenant is exactly the one that needs repairing. The component pass runs below.
        print("  (no L0 sources — L1/L2/L3 have nothing to rebuild)")
        await rebuild_component_projections(ctx, user_id)
        return

    # L1 — drop the user's lexical indexes, then re-index every source's stored blocks.
    await ctx.lexical.delete_user(user_id)
    l1_sources = 0
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        await ctx.lexical.index_blocks(user_id, raw.source_id, normalized.blocks)
        l1_sources += 1
    print(f"  L1  re-indexed {l1_sources} source(s) into Meili")

    # L2 — drop stale chunk points once, then re-chunk + re-embed every source.
    await ctx.vectors.delete_chunks(user_id)
    l2_chunks = 0
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        chunks = await _chunks_for(ctx, raw.source_id, normalized, user_id)
        if not chunks:
            continue
        embedded = await embed_l2_chunks(ctx, chunks, normalized)
        await ctx.vectors.upsert_chunks(user_id, embedded)
        l2_chunks += len(chunks)
    l2_after = await ctx.vectors.count_chunks(user_id)
    print(f"  L2  {l2_after} chunk(s) (was {l2_before})")

    # L3 — re-project canonical HEAD onto PG + Meili claims + Qdrant claim layer.
    claim_count = await rebuild_projection(ctx, user_id)
    print(f"  L3  projected {claim_count} claim(s) from canonical HEAD")

    await rebuild_component_projections(ctx, user_id)


#: The job kinds this script is willing to run itself. Both are keyless and modelless — no
#: chat model, no skill manifest, no canonical write — which is precisely why an ops script
#: may drain them and may not drain a compile.
_DRAINABLE = (RECALL_REBUILD_JOB_KIND, RECALL_PROJECTION_JOB_KIND)


async def rebuild_component_projections(ctx, user_id: UserId) -> None:
    """The use-side derived layer — the framework's access statistics and every enabled
    component's own projection — rebuilt THROUGH THE QUEUE.

    Through the queue, and not called directly, because a rebuild that replayed
    `consultations` while the worker was applying a `recall_projection` for the same user
    would swap the replay over an increment nobody had replayed. The queue already answers
    that: `claim_next` refuses to hand out a second job for a user with one in flight, so
    while this job is claimed no projection for that user can be, and vice versa. That is
    the smallest sound shape available — the alternative was a per-user lock in the database
    plus a second connection pool to hold it on, which this delivery model deleted.

    The job is drained HERE rather than left for the worker, so an operator who runs this
    against a stack with no worker up still gets a rebuild, and so the script can report
    what happened. It claims only its own kinds: a compile job at the head of this user's
    queue is reported and left alone (this script has no model and no skill), and the worker
    will pick the rebuild up behind it.

    It is also the ONLY place a timezone change is allowed to re-normalize already-written
    rows: explicit, operator-run, and reported.
    """
    await ctx.store.enqueue(user_id, RECALL_REBUILD_JOB_KIND, {})
    while True:
        jobs = await ctx.store.list_jobs(user_id)  # newest first
        queued = [j for j in reversed(jobs) if j["status"] == "queued"]  # oldest first
        if not queued:
            return
        if queued[0]["kind"] not in _DRAINABLE:
            print(
                f"  C   a {queued[0]['kind']} job is ahead in the queue; the rebuild is "
                "enqueued and the worker will run it"
            )
            return
        job = await ctx.store.claim_next(user_id)
        if job is None:
            print("  C   another worker holds this user's queue; the rebuild is enqueued")
            return
        kind = getattr(job, "kind", "")
        if kind not in _DRAINABLE:
            # Only reachable if a live worker enqueued for this user between the peek and
            # the claim — which this script's contract already forbids (see
            # `requeue_orphaned_jobs`). Released rather than returned, because a job left
            # 'claimed' blocks that user's whole queue forever and nothing would say why.
            await ctx.store.complete(
                user_id,
                job.job_id,
                ok=False,
                detail=f"released by rebuild_derived: no model to run a {kind} job",
            )
            print(
                f"  C   claimed an unexpected {kind} job and released it — do not run this "
                "script alongside a live compile worker"
            )
            return
        try:
            if kind == RECALL_REBUILD_JOB_KIND:
                await run_recall_rebuild_job(ctx, user_id, job)
            else:
                await run_recall_projection_job(ctx, user_id, job)
        except Exception as exc:  # noqa: BLE001 — never leave a job stuck 'claimed'
            await ctx.store.complete(
                user_id, job.job_id, ok=False, detail=f"rebuild script error: {exc}"
            )
            print(f"  C   {kind} job failed: {exc}")
            return
        if kind == RECALL_REBUILD_JOB_KIND:
            detail = next(
                (
                    j["detail"]
                    for j in await ctx.store.list_jobs(user_id)
                    if j["job_id"] == job.job_id
                ),
                "",
            )
            print(f"  C   rebuilt the use-side projections: {detail}")
            return


async def main() -> int:
    args = sys.argv[1:]
    settings = get_settings()
    ctx = await build_context(settings)
    print(
        f"chunk_strategy={settings.chunk_strategy}  "
        f"embedding={settings.embedding_model}  qdrant={settings.qdrant_collection}"
    )
    try:
        if args == ["--all"]:
            users = await all_users(ctx)
            print(f"rebuilding ALL {len(users)} user(s)")
        elif args and not args[0].startswith("--"):
            users = [UserId(u) for u in args]
        else:
            print(__doc__)
            return 2
        for user in users:
            await rebuild_user(ctx, user)
    finally:
        await ctx.aclose()
    print("\nOK: derived rebuild complete (L1 + L2 + L3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
