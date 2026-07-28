"""Canonical → L3 projection orchestration (architecture.md §7; milestone M4).

After a compile commits, the worker projects the new snapshot's claims onto the three
derived retrieval stores (invariant I2: fully reconstructable from canonical):

  1. PG `canonical_claims` — one row per anchored claim + citation reverse-lookup face;
  2. Meilisearch `claims_<uid>` — the L3 lexical retrieval face;
  3. Qdrant claim layer (`payload.layer="claim"`) — the L3 semantic retrieval face.

`rebuild_projection(ctx, user)` is the standalone repair/strategy-upgrade entry point.
The normal worker path uses `sync_projection`: it compares the complete projected
snapshot with PostgreSQL's last successful manifest and synchronizes only the content
delta, so unchanged claims are not repeatedly embedded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.projection import (
    PROJECTION_V1,
    ProjectedClaim,
    ProjectionStrategy,
    project_snapshot_claims,
)

from .wiring import AppContext

ClaimKey = tuple[str, str]


@dataclass(frozen=True)
class ProjectionSyncResult:
    total: int
    upserted: int
    deleted: int
    unchanged: int


def _claim_key(claim: ProjectedClaim) -> ClaimKey:
    return claim.document_path, str(claim.anchor)


def _claim_signature(claim: ProjectedClaim) -> tuple[Any, ...]:
    return (
        tuple(claim.section_path),
        claim.text,
        tuple(
            (str(c.source_id), c.block_start, c.block_end) for c in claim.citations
        ),
    )


def _row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(row.get("section_path") or []),
        str(row.get("text") or ""),
        tuple(
            (
                str(citation.get("source_id") or ""),
                int(citation.get("block_start") or 0),
                int(citation.get("block_end") or 0),
            )
            for citation in (row.get("citations") or [])
        ),
    )


def _projection_delta(
    claims: list[ProjectedClaim],
    previous: list[dict[str, Any]],
) -> tuple[list[ProjectedClaim], list[ClaimKey], int]:
    previous_by_key = {
        (str(row["document_path"]), str(row["anchor"])): row for row in previous
    }
    current_keys: set[ClaimKey] = set()
    upserts: list[ProjectedClaim] = []
    unchanged = 0
    for claim in claims:
        key = _claim_key(claim)
        current_keys.add(key)
        old = previous_by_key.get(key)
        if old is not None and _row_signature(old) == _claim_signature(claim):
            unchanged += 1
        else:
            upserts.append(claim)
    deleted = sorted(set(previous_by_key) - current_keys)
    return upserts, deleted, unchanged


async def sync_projection(
    ctx: AppContext,
    user_id: UserId,
    snapshot_ref: str,
    *,
    strategy: ProjectionStrategy = PROJECTION_V1,
) -> ProjectionSyncResult:
    """Synchronize one committed snapshot without re-embedding unchanged claims.

    PostgreSQL is the last-successful projection manifest and therefore lands last.
    Remote operations use deterministic ids, so a failure before the manifest advance
    can be retried with the same delta safely.
    """
    docs = await ctx.canonical.list(user_id, at=SnapshotRef(ref=snapshot_ref))
    claims = project_snapshot_claims(docs, strategy)
    previous = await ctx.store.list_canonical_claims(user_id)
    upserts, deleted, unchanged = _projection_delta(claims, previous)

    if upserts:
        vectors = await ctx.embeddings.aembed_documents([claim.text for claim in upserts])
    else:
        vectors = []

    if upserts or deleted:
        await asyncio.gather(
            ctx.lexical.sync_claims(user_id, upserts, deleted),
            ctx.vectors.sync_claims(user_id, upserts, vectors, deleted),
        )

    await ctx.store.sync_canonical_claims(
        user_id, snapshot_ref, upserts, deleted
    )
    return ProjectionSyncResult(
        total=len(claims),
        upserted=len(upserts),
        deleted=len(deleted),
        unchanged=unchanged,
    )


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
