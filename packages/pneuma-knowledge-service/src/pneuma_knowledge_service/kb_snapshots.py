"""Knowledge-base snapshots as FROZEN TENANTS — lifecycle and read routing.

THE MECHANISM
-------------
A snapshot is not a filter over a live base; it is a complete copy of that base under a tenant
id that is never written again. Every storage layer here already isolates by `user_id`, and
that isolation is the strongest versioning primitive in the system — so versioning reuses it
rather than adding a history dimension to three indexes:

  L0  PG `sources` / `blocks`          → INSERT…SELECT with the user_id rewritten
  L1  Meilisearch `blocks_<tenant>`    → re-derived from the copied L0 rows
  L2  Qdrant chunk points              → copied WITH their original vectors
  L3  PG `canonical_claims`            → INSERT…SELECT with the user_id rewritten
      Meilisearch `claims_<tenant>`    → re-derived from the copied claim rows
      Qdrant claim points              → copied WITH their original vectors
  L3  canonical (git)                  → NOT copied; the row pins `canonical_ref`

WHY canonical IS THE ONE EXCEPTION
----------------------------------
git is already a complete, byte-exact version store, and the canonical layer is the one
non-rebuildable layer (invariant I2). Copying it would create a second authority for the same
documents. So the snapshot records the commit and reads go to the OWNER's repo at that ref.

WHY VECTORS ARE COPIED AND LEXICAL FACES ARE REBUILT
----------------------------------------------------
An embedding is not reproducible: re-embedding a frozen snapshot later — after an embedding
model change or a re-chunk — would silently change what it retrieves, which is the precise
failure a snapshot exists to prevent. So vectors move as opaque numbers and are never
recomputed. A Meilisearch document, by contrast, is a pure function of the L0 rows that were
just copied, so it is re-derived through the same `index_blocks` / `index_claims` the live path
uses. One code path, no bespoke index-scroll copier to keep in sync with the document shape.

WHY THE COPY, NOT A RE-PROJECTION FROM THE REF
----------------------------------------------
The claim projection could instead be recomputed from the canonical tree at `canonical_ref`.
It is copied instead, deliberately: a snapshot promises "what this base answers right now,
forever", and the live projection — including any lag behind the newest commit — is what the
base answers right now. Re-projecting would produce a snapshot that answers DIFFERENTLY from
the base it claims to freeze, and it would also desynchronize the rebuilt lexical claim face
from the copied (never re-embedded) semantic one. The copy keeps all four claim faces the same
set by construction.

STATUS IS BINARY AT THE END
---------------------------
`creating` while the pipeline runs, then `ready` or `failed` — never a usable half-snapshot. A
`failed` row and its partial tenant are RETAINED so the remains are visible and deletable; the
read path refuses anything that is not `ready`. Every step is idempotent (unqualified
`ON CONFLICT DO NOTHING`, deterministic point ids, full index rebuilds), so re-running the
pipeline over a partial tenant completes it rather than duplicating it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.projection import ProjectedClaim

from .snapshot_tenant import (
    assert_writable,
    new_snapshot_id,
    snapshot_tenant_id,
)
from .wiring import AppContext

STATUS_CREATING = "creating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


class SnapshotNotFound(LookupError):
    """The requested snapshot does not exist for this owner (→ 404)."""


class SnapshotIncomplete(RuntimeError):
    """The copied tenant fails the completeness identity, so it may not be marked ready.

    Its own type because it is not an I/O failure: every step reported success and the
    numbers still do not add up, which is exactly the shape a half-copied tenant takes."""

    def __init__(self, points: int, chunks: int, claims: int) -> None:
        self.points, self.chunks, self.claims = points, chunks, claims
        self.claim_points = points - chunks
        super().__init__(
            f"copied tenant is incomplete: {points} vector points − {chunks} chunk points "
            f"= {self.claim_points} claim points, but {claims} claim rows were copied "
            f"(difference {self.claim_points - claims}). A snapshot whose semantic claim "
            "face and claim rows disagree answers differently from the base it froze."
        )


class SnapshotNotReady(RuntimeError):
    """The snapshot exists but is not answerable yet, or never will be (→ 409).

    Its own type so the read path cannot accidentally treat a `creating` or `failed`
    snapshot as an empty one: an empty answer over a half-copied tenant is the single most
    misleading outcome this feature could produce."""

    def __init__(self, label: str, status: str, detail: str | None = None) -> None:
        self.status = status
        message = (
            f"snapshot {label!r} is {status}, not ready to answer over"
            if status == STATUS_CREATING
            else f"snapshot {label!r} failed to build and cannot be used"
        )
        super().__init__(f"{message}{f': {detail}' if detail else ''}")


@dataclass(frozen=True)
class KbSnapshot:
    """One registry row: the identity, the routing, and the reported scale."""

    snapshot_id: str
    label: str
    tenant_id: UserId
    canonical_ref: str
    status: str
    counts: dict[str, int]
    created_at: datetime | None
    ready_at: datetime | None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == STATUS_READY

    @property
    def canonical_at(self) -> SnapshotRef | None:
        """The `at=` argument for canonical reads, or None when the owner had no canonical."""
        return SnapshotRef(ref=self.canonical_ref) if self.canonical_ref else None


def _from_row(row: dict[str, Any]) -> KbSnapshot:
    return KbSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        label=str(row["label"]),
        tenant_id=UserId(str(row["tenant_id"])),
        canonical_ref=str(row["canonical_ref"] or ""),
        status=str(row["status"]),
        counts={k: int(v) for k, v in (row.get("counts") or {}).items()},
        created_at=row.get("created_at"),
        ready_at=row.get("ready_at"),
        detail=row.get("detail"),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------ read routing


async def resolve(ctx: AppContext, owner: UserId, ref: str) -> KbSnapshot:
    """Resolve a `snapshot` request value (snapshot id or label) to a READY snapshot.

    Raises rather than degrading: silently answering over HEAD because a snapshot id was
    misspelled would present today's base as history, which is worse than an error."""
    row = await ctx.store.get_kb_snapshot(owner, ref)
    if row is None:
        raise SnapshotNotFound(f"no snapshot {ref!r} for user {str(owner)!r}")
    snapshot = _from_row(row)
    if not snapshot.ready:
        raise SnapshotNotReady(snapshot.label, snapshot.status, snapshot.detail)
    return snapshot


async def list_snapshots(ctx: AppContext, owner: UserId) -> list[KbSnapshot]:
    """This owner's snapshots, newest first, in every status (the picker shows progress)."""
    return [_from_row(row) for row in await ctx.store.list_kb_snapshots(owner)]


# --------------------------------------------------------------------------- lifecycle


async def create(ctx: AppContext, owner: UserId, label: str) -> KbSnapshot:
    """Register a snapshot of the owner's CURRENT state and return it in status 'creating'.

    Only "now" can be snapshotted, never an arbitrary past ref: the L0/L1/L2 layers hold one
    live state each, so a past commit's raw content and vectors are simply not recoverable
    from them. Pretending otherwise is the half-measure this design replaced.

    The `canonical_ref` recorded here is PROVISIONAL — today's HEAD, so a pipeline that dies
    still leaves a meaningful row. `run_copy` settles the final ref once the claim rows are
    copied; see the ordering argument there.
    """
    assert_writable(owner)  # a snapshot of a snapshot would be a write to a frozen tenant
    snapshot_id = new_snapshot_id()
    tenant = snapshot_tenant_id(snapshot_id)
    head = await ctx.canonical.snapshots(owner)
    created_at = _now()
    await ctx.store.create_kb_snapshot(
        owner,
        snapshot_id,
        label=label,
        tenant_id=str(tenant),
        canonical_ref=head[0].ref if head else "",
        created_at=created_at,
    )
    row = await ctx.store.get_kb_snapshot(owner, snapshot_id)
    assert row is not None  # just inserted, in the same pool
    return _from_row(row)


def _projected(row: dict[str, Any]) -> ProjectedClaim:
    """A copied `canonical_claims` row back into the shape the index adapters take."""
    return ProjectedClaim(
        anchor=AnchorId(str(row["anchor"])),
        document_path=str(row["document_path"]),
        section_path=tuple(row.get("section_path") or ()),
        text=str(row.get("text") or ""),
        citations=tuple(
            Citation(
                source_id=SourceId(str(c["source_id"])),
                block_start=int(c["block_start"]),
                block_end=int(c["block_end"]),
            )
            for c in (row.get("citations") or [])
        ),
    )


async def run_copy(ctx: AppContext, owner: UserId, snapshot: KbSnapshot) -> KbSnapshot:
    """The copy pipeline: vector points → PG rows → pinned ref → lexical faces → status.

    THE ORDER IS THE CORRECTNESS ARGUMENT, not a convenience. A live base keeps ingesting and
    compiling while the copy runs — there is no transaction spanning three stores — so the
    snapshot is taken over a WINDOW, and different layers can land at slightly different
    moments. What must never happen is a DANGLING REFERENCE: a piece of evidence in the
    snapshot pointing at something the snapshot does not contain. The order makes each layer a
    subset of the layer that can address it:

    1. **Qdrant first.** A chunk/claim point names a `source_id`, so the point set must not
       outrun the source rows. Copied first, it can only be a subset of step 2.
    2. **PG next**, in one transaction: sources + blocks + the claim projection together. So
       every point's source row is present, and every copied claim's cited sources are too.
    3. **The pinned canonical ref is read HERE**, after the claim rows. A claim names its
       `document_path`, and `read_document` resolves that path in the tree at this ref — so
       the tree must be no OLDER than the claim rows, or a snapshot answer could cite a
       document its own tools cannot open. The ref recorded at creation is only provisional
       for exactly this reason; on a live base it can be minutes stale by now.
    4. **Meilisearch last**, re-derived from the rows copied in step 2, so both lexical faces
       are consistent with the frozen L0 by construction rather than by timing.

    5. **The completeness identity is asserted LAST**, after every layer has landed and
       before the row is marked ready: `points − chunks == claims`. See the step itself.

    The residual skew is benign and one-directional: a source or claim copied in step 2 may
    have no vector yet (its point arrived after step 1), which reads exactly like the ordinary
    indexing lag a live base already has, and costs at most one retrieval path for that item.

    Any exception marks the snapshot `failed` with the reason and re-raises for the caller's
    log — it never leaves the row in `creating`, because a row stuck in `creating` is
    indistinguishable from a pipeline still running.
    """
    tenant = snapshot.tenant_id
    try:
        # 1. L2 + L3 semantic, with the original vectors — never re-embedded.
        points = await ctx.vectors.copy_tenant(owner, tenant)

        # 2. L0 + the claim projection, one transaction.
        counts = await ctx.store.copy_tenant_rows(owner, tenant)
        counts["points"] = points

        # 3. Pin the tree that can resolve the claim rows just copied.
        head = await ctx.canonical.snapshots(owner)
        canonical_ref = head[0].ref if head else snapshot.canonical_ref

        # 4. L1 + L3 lexical, re-derived from the copied rows. Per source, because that is the
        # granularity `index_blocks` takes and it keeps each request's payload bounded.
        for raw in await ctx.store.list(tenant):
            normalized = await ctx.store.get(tenant, raw.source_id)
            await ctx.lexical.index_blocks(tenant, raw.source_id, normalized.blocks)
        claims = [
            _projected(row) for row in await ctx.store.list_canonical_claims(tenant)
        ]
        await ctx.lexical.index_claims(tenant, claims)

        # 5. COMPLETENESS, before `ready` and never after. The collection holds both layers
        # under one tenant, so the copy's own numbers state an identity: every point is
        # either an L2 chunk or an L3 claim, and the claim points must be exactly the claim
        # rows copied in step 2. `points − chunks == claims` is that identity, and it is
        # cheap, total, and computed from counts the pipeline already has. A tenant that
        # fails it is a snapshot that would answer with a different claim set depending on
        # which face a query happens to hit — the one outcome `ready` must never cover.
        chunks = await ctx.vectors.count_chunks(tenant)
        counts["chunks"] = chunks
        if points - chunks != int(counts.get("claims", 0)):
            raise SnapshotIncomplete(points, chunks, int(counts.get("claims", 0)))

        await ctx.store.finish_kb_snapshot(
            owner,
            snapshot.snapshot_id,
            status=STATUS_READY,
            counts=counts,
            ready_at=_now(),
            canonical_ref=canonical_ref,
        )
    except Exception as exc:  # noqa: BLE001 — every failure mode ends as an honest 'failed'
        await ctx.store.finish_kb_snapshot(
            owner,
            snapshot.snapshot_id,
            status=STATUS_FAILED,
            detail=f"{type(exc).__name__}: {exc}",
        )
        raise
    row = await ctx.store.get_kb_snapshot(owner, snapshot.snapshot_id)
    return _from_row(row) if row else snapshot


async def delete(ctx: AppContext, owner: UserId, snapshot_id: str) -> bool:
    """Delete a snapshot: purge its tenant from all three stores, then drop the registry row.

    Stores first, row last. If a store purge fails the row survives, so the snapshot is still
    listed and still deletable — the alternative (row first) would strand tenant data that
    nothing in the system any longer names. canonical is untouched: `canonical_ref` points into
    the owner's git history, and deleting a snapshot must not rewrite history.
    """
    row = await ctx.store.get_kb_snapshot(owner, snapshot_id)
    if row is None:
        return False
    snapshot = _from_row(row)
    tenant = snapshot.tenant_id
    await ctx.vectors.delete_user(tenant)
    await ctx.lexical.delete_user(tenant)
    await ctx.store.delete_tenant_rows(tenant)
    await ctx.store.delete_kb_snapshot(owner, snapshot.snapshot_id)
    return True


def spawn_copy(ctx: AppContext, owner: UserId, snapshot: KbSnapshot) -> asyncio.Task:
    """Run `run_copy` as a background task on the current loop (the 202 path).

    Not routed through the compile JobQueue on purpose: that queue serializes per user and is
    consumed by the compile worker, so a snapshot copy would queue behind compiles and block
    them in turn — while being pure store-to-store I/O that needs no compile machinery, no
    model and no canonical write lock. The cost of this choice is stated rather than hidden: if
    the API process dies mid-copy the row stays `creating` until someone deletes it, and the
    read path refuses it in the meantime.
    """
    task = asyncio.create_task(run_copy(ctx, owner, snapshot))
    # Retain a reference so the task is not garbage-collected mid-flight, and swallow the
    # re-raise here (the failure is already recorded on the row by `run_copy`).
    _IN_FLIGHT.add(task)
    task.add_done_callback(_IN_FLIGHT.discard)
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return task


#: Strong references to in-flight copy tasks — asyncio only holds weak ones.
_IN_FLIGHT: set[asyncio.Task] = set()


__all__ = [
    "KbSnapshot",
    "STATUS_CREATING",
    "STATUS_FAILED",
    "STATUS_READY",
    "SnapshotIncomplete",
    "SnapshotNotFound",
    "SnapshotNotReady",
    "create",
    "delete",
    "list_snapshots",
    "resolve",
    "run_copy",
    "spawn_copy",
]
