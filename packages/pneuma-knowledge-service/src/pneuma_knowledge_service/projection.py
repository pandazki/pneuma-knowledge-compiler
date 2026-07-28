"""Canonical → L3 projection orchestration (architecture.md §7; milestone M4).

After a compile commits, the worker projects the new snapshot's claims onto the three
derived retrieval stores in whole (invariant I2: rebuild, never mutate incrementally):

  1. PG `canonical_claims` — one row per anchored claim + citation reverse-lookup face;
  2. Meilisearch `claims_<uid>` — the L3 lexical retrieval face;
  3. Qdrant claim layer (`payload.layer="claim"`) — the L3 semantic retrieval face.

`rebuild_projection(ctx, user)` is the standalone entry point (derived rebuild after a
strategy/skill upgrade, M5); the worker calls it with the just-committed snapshot ref.
"""

from __future__ import annotations

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.projection import (
    PROJECTION_V1,
    ProjectionStrategy,
    project_snapshot_claims,
)

from .wiring import AppContext


async def rebuild_projection(
    ctx: AppContext,
    user_id: UserId,
    snapshot_ref: str | None = None,
    *,
    strategy: ProjectionStrategy = PROJECTION_V1,
) -> int:
    """Re-project the user's claims from a snapshot (default HEAD) onto PG + Meili +
    Qdrant under `strategy`. Returns the projected claim count.

    This is the derived rebuild (invariant I2, milestone M5): a projection/rendering
    strategy upgrade re-materializes every derived row from the SAME frozen canonical —
    canonical git HEAD is read here, never written. Swap `strategy`, call this, and the
    L3 retrieval face reflects the new strategy with zero canonical churn."""
    ref = SnapshotRef(ref=snapshot_ref) if snapshot_ref else None
    docs = await ctx.canonical.list(user_id, at=ref)
    claims = project_snapshot_claims(docs, strategy)

    if snapshot_ref:
        resolved = snapshot_ref
    else:
        snaps = await ctx.canonical.snapshots(user_id)
        resolved = snaps[0].ref if snaps else ""

    # 1. PG canonical_claims (full rebuild + citation reverse-lookup face).
    await ctx.store.replace_canonical_claims(user_id, resolved, claims)

    # 2. Meili claims index (full rebuild).
    await ctx.lexical.index_claims(user_id, claims)

    # 3. Qdrant claim layer (drop then re-upsert with embeddings).
    await ctx.vectors.delete_claims(user_id)
    if claims:
        vectors = await ctx.embeddings.aembed_documents([c.text for c in claims])
        await ctx.vectors.upsert_claims(user_id, claims, vectors)

    return len(claims)
