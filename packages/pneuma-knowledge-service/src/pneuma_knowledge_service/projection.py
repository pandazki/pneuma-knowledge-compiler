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

THE GUARDRAILS BELOW EXIST BECAUSE THIS MODULE ONCE WIPED A LIVE PROJECTION
--------------------------------------------------------------------------
A repair script was pointed at the wrong canonical root. The store it read was an EMPTY
repository, so `project_snapshot_claims` produced nothing, so the projection sync computed
"every claim you have is gone" and executed it: 3072 claims deleted, then 183 rebuilt from
the wrong repository's freshly-bootstrapped tree. Nothing in this module objected, because
each individual step did exactly what it was told.

The lesson is not "be careful with roots" — it is that a derived layer must refuse to
destroy itself on the say-so of an authority it cannot corroborate. Three refusals follow
from that, and each one names the moment the incident passed through unchallenged:

  1. an empty canonical tree may not replace a non-empty projection (`rebuild_projection`,
     the whole-table `replace_canonical_claims` path);
  2. a snapshot ref that the CURRENT store's canonical repository cannot read is not a
     snapshot, it is evidence of a misconfiguration — the first place the wrong root became
     observable;
  3. a sync that would lose more than `MAX_PROJECTION_LOSS_SHARE` of the projected claims is
     a wipe wearing a delta's clothes.

Every refusal has the same escape hatch, `allow_wipe=True`, because deleting a projection on
purpose is a legitimate operation — it just may not happen by accident.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pneuma_knowledge_core.compile.documents import OVERVIEW_LABEL
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

#: How much of a tenant's projected knowledge one sync may LOSE before it is refused.
#:
#: WHY A SHARE, AND WHY A HALF. An ordinary delta is a compile's worth of claims — single or
#: double digits against a base of hundreds to thousands — and the compile gate has no
#: deletion channel at all, so the honest expected loss on the normal path is exactly zero.
#: Half is therefore orders of magnitude above anything real traffic produces and far below
#: the failure it names (the incident above lost 100%). A share rather than an absolute count
#: because the number that matters is "how much of this knowledge base", which is meaningless
#: without the base.
#:
#: WHY LOSS IS COUNTED IN ANCHORS, NOT IN DELETED KEYS. The projection is keyed by
#: (document_path, anchor), so a rollover — which MOVES claims from a page into its archive
#: volume — legitimately deletes every key it moves and re-inserts it under the volume's path.
#: Counting deleted keys would refuse a groom of a small knowledge base as if it were a wipe.
#: An anchor is repo-unique and survives the move, so "anchors that were projected and are
#: projected no longer" is precisely the claims the knowledge base actually lost.
#:
#: WHY OVERVIEW ANCHORS ARE NOT PART OF THAT COUNT. A document's overview region is a
#: rewritable head, not knowledge: `rewrite_overview` replaces every block wholesale and the
#: anchors of the blocks it replaced are RETIRED by design, which is what makes wholesale
#: rewrite safe. Their claims project under the section path `("overview", <slot>)`, so they
#: are mechanically distinguishable from ledger claims — and they must be, because a small
#: library whose pages are mostly head (8 overview claims against 6 ledger claims is an
#: ordinary young tenant) would otherwise trip this guardrail on its first honest rewrite.
#: Loss is therefore measured over LEDGER anchors on both sides of the ratio: overview churn
#: neither counts as loss nor inflates the base, while a real ledger wipe still refuses at the
#: same half.
MAX_PROJECTION_LOSS_SHARE = 0.5


class ProjectionRefused(RuntimeError):
    """A projection write was refused because it would destroy projected claims.

    Structured rather than a bare message: whatever reports this — a job detail, an API error
    body, an operator's terminal — has to state WHAT was refused and by how much, and a
    string that must be re-parsed to recover those numbers is not a report. `reason` is the
    stable machine face; `facts` carries the counts the message renders.
    """

    def __init__(self, reason: str, message: str, **facts: Any) -> None:
        self.reason = reason
        self.facts = facts
        super().__init__(message)


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


def _lost_anchors(
    claims: list[ProjectedClaim], previous: list[dict[str, Any]]
) -> set[str]:
    """Anchors that were projected and would be projected no longer — the real loss.

    A rollover re-keys a claim (page → archive volume) without losing it, so this set is
    empty for a groom and total for a wipe. See MAX_PROJECTION_LOSS_SHARE.

    Every CURRENT anchor is subtracted, overview included: an anchor that is still projected
    anywhere has not been lost, wherever it now sits.
    """
    return {str(row["anchor"]) for row in previous} - {
        str(claim.anchor) for claim in claims
    }


def _is_overview_row(row: dict[str, Any]) -> bool:
    """Whether a projected row belongs to a document's overview region rather than its ledger.

    Read off the same section-path prefix `ProjectedClaim.labels` reads, so the guard and the
    projection agree on what "overview" means by construction — not by two copies of a rule.
    """
    section_path = row.get("section_path") or []
    return bool(section_path) and str(section_path[0]) == OVERVIEW_LABEL


async def sync_projection(
    ctx: AppContext,
    user_id: UserId,
    snapshot_ref: str,
    *,
    strategy: ProjectionStrategy = PROJECTION_V1,
    allow_wipe: bool = False,
) -> ProjectionSyncResult:
    """Synchronize one committed snapshot without re-embedding unchanged claims.

    PostgreSQL is the last-successful projection manifest and therefore lands last.
    Remote operations use deterministic ids, so a failure before the manifest advance
    can be retried with the same delta safely.

    Refuses (`ProjectionRefused`) when the ref does not resolve in this store's canonical
    repository, or when the delta would lose more than `MAX_PROJECTION_LOSS_SHARE` of the
    tenant's projected LEDGER claims (an overview region is a rewritable head — its anchors
    are retired on purpose). `allow_wipe=True` is the deliberate-destruction escape hatch;
    the ref check has none, because an unreadable ref is never intentional.
    """
    # The ref must resolve HERE — in the canonical repository this context is wired to. A
    # compile that committed into a different repository produces a ref that is perfectly
    # valid somewhere else, and reading it here is the first moment that mismatch is
    # observable. Failing loud at that moment is the difference between one broken job and a
    # silently re-projected knowledge base.
    try:
        docs = await ctx.canonical.list(user_id, at=SnapshotRef(ref=snapshot_ref))
    except Exception as exc:  # noqa: BLE001 — every read failure means "cannot corroborate"
        raise ProjectionRefused(
            "unresolvable_snapshot_ref",
            f"snapshot ref {snapshot_ref!r} could not be read from the canonical "
            f"repository this store is wired to ({type(exc).__name__}: {exc}); the commit "
            "may live in a different repository, and projecting from an unverified tree "
            "would rewrite the derived layer from the wrong authority",
            snapshot_ref=snapshot_ref,
            error=f"{type(exc).__name__}: {exc}",
        ) from exc

    claims = project_snapshot_claims(docs, strategy)
    previous = await ctx.store.list_canonical_claims(user_id)
    upserts, deleted, unchanged = _projection_delta(claims, previous)

    # Overview claims are excluded from BOTH sides of the ratio: their anchors are retired by
    # every rewrite of a rewritable head, so counting them would make an honest rewrite of a
    # small library read as a wipe. See MAX_PROJECTION_LOSS_SHARE.
    previous_ledger = [row for row in previous if not _is_overview_row(row)]
    if previous_ledger and not allow_wipe:
        lost = _lost_anchors(claims, previous_ledger)
        limit = MAX_PROJECTION_LOSS_SHARE * len(previous_ledger)
        if len(lost) > limit:
            raise ProjectionRefused(
                "excessive_claim_loss",
                f"projecting snapshot {snapshot_ref!r} would drop {len(lost)} of "
                f"{len(previous_ledger)} projected ledger claims "
                f"({len(lost) / len(previous_ledger):.1%}, over the "
                f"{MAX_PROJECTION_LOSS_SHARE:.0%} guardrail); pass allow_wipe=True if the "
                "loss is intended",
                snapshot_ref=snapshot_ref,
                lost=len(lost),
                projected=len(previous_ledger),
                overview_excluded=len(previous) - len(previous_ledger),
                limit=MAX_PROJECTION_LOSS_SHARE,
            )

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
    allow_wipe: bool = False,
) -> int:
    """Re-project the user's claims from a snapshot (default HEAD) onto PG + Meili +
    Qdrant under `strategy`. Returns the projected claim count.

    This is the derived rebuild (invariant I2, milestone M5): a projection/rendering
    strategy upgrade re-materializes every derived row from the SAME frozen canonical —
    canonical git HEAD is read here, never written. Swap `strategy`, call this, and the
    L3 retrieval face reflects the new strategy with zero canonical churn.

    Refuses (`ProjectionRefused`) when the canonical tree is EMPTY while the tenant still
    has claims projected: an empty tree is what a wrong / uninitialized canonical root looks
    like, and the whole-table replace below would carry out its instruction — delete
    everything — without a second reader. `allow_wipe=True` when the emptiness is real."""
    ref = SnapshotRef(ref=snapshot_ref) if snapshot_ref else None
    docs = await ctx.canonical.list(user_id, at=ref)
    claims = project_snapshot_claims(docs, strategy)

    if not docs and not allow_wipe:
        projected = await ctx.store.list_canonical_claims(user_id)
        if projected:
            raise ProjectionRefused(
                "empty_canonical",
                f"canonical holds no documents at "
                f"{snapshot_ref or 'HEAD'!r} while the tenant has {len(projected)} "
                "projected claims; rebuilding from an empty repo would wipe all of them "
                "(a missing or misconfigured canonical root reads exactly like this). Pass "
                "allow_wipe=True if the repository really is empty on purpose",
                snapshot_ref=snapshot_ref or "HEAD",
                projected=len(projected),
            )

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
