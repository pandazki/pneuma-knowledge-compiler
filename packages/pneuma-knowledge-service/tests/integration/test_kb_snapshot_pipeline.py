"""Freezing a knowledge base across the real three stores, and cleaning it up again.

The unit tests prove the pipeline's shape against stand-ins. What only the real stores can
prove is that a copy is actually READABLE afterwards through the ordinary retrieval face —
that the Meilisearch index the snapshot rebuilt answers a search under the frozen tenant, and
that the Qdrant points arrived with vectors intact rather than as payload-only husks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from pneuma_knowledge_service import kb_snapshots


def _source(user: UserId, title: str, texts: list[str]) -> NormalizedSource:
    sid = SourceId(uuid.uuid4().hex)
    return NormalizedSource(
        raw=RawSource(
            source_id=sid,
            user_id=user,
            kind="document",
            source_class="workstream",
            title=title,
            mime="text/markdown",
            checksum=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc),
        ),
        blocks=[
            NormalizedBlock(index=i, text=text, section_path=["Notes"])
            for i, text in enumerate(texts)
        ],
        structure=StructureMap(sections=[]),
    )


def _claim(anchor: str, path: str, text: str, source_id: str) -> ProjectedClaim:
    return ProjectedClaim(
        anchor=AnchorId(anchor),
        document_path=path,
        section_path=("Notes",),
        text=text,
        citations=(
            Citation(source_id=SourceId(source_id), block_start=0, block_end=0),
        ),
    )


class _Canonical:
    """The canonical face `create` needs: HEAD's sha. No git repo required — a snapshot never
    copies canonical, it only records which commit it pinned."""

    def __init__(self, head: str) -> None:
        self._head = head

    async def snapshots(self, user_id):  # noqa: ANN001
        return [SnapshotRef(ref=self._head, label="latest")]


@pytest.fixture
async def frozen_ctx(pg_store, meili, qdrant, embeddings, user):
    """An owner with two indexed sources and one projected claim, ready to be frozen."""
    ctx = SimpleNamespace(
        store=pg_store,
        lexical=meili,
        vectors=qdrant,
        canonical=_Canonical("sha-head-int"),
    )
    first = _source(user, "pilot notes", ["the pilot shipped in March", "owner acked"])
    second = _source(user, "budget notes", ["the budget was approved"])
    for normalized in (first, second):
        await pg_store.add(user, normalized)
        await meili.index_blocks(user, normalized.raw.source_id, normalized.blocks)

    claim = _claim(
        "aa11", "memory/pilot.md", "the pilot shipped in March",
        str(first.raw.source_id),
    )
    await pg_store.replace_canonical_claims(user, "sha-head-int", [claim])
    await meili.index_claims(user, [claim])
    vector = await embeddings.aembed_query(claim.text)
    await qdrant.upsert_claims(user, [claim], [vector])

    snapshots: list[str] = []
    try:
        yield ctx, user, first, snapshots
    finally:
        for snapshot_id in snapshots:
            await kb_snapshots.delete(ctx, user, snapshot_id)


async def test_freeze_then_read_then_delete(frozen_ctx, embeddings):
    ctx, owner, first, created = frozen_ctx

    snapshot = await kb_snapshots.create(ctx, owner, "before the reorg")
    created.append(snapshot.snapshot_id)
    assert snapshot.status == kb_snapshots.STATUS_CREATING

    ready = await kb_snapshots.run_copy(ctx, owner, snapshot)
    assert ready.status == kb_snapshots.STATUS_READY
    assert ready.canonical_ref == "sha-head-int"
    assert ready.counts["sources"] == 2
    assert ready.counts["blocks"] == 3
    assert ready.counts["claims"] == 1
    assert ready.counts["points"] == 1

    tenant = ready.tenant_id

    # L0 is readable verbatim under the frozen tenant — the unconditional-reachability
    # invariant holds for a snapshot too, or a citation in a snapshot answer is undrillable.
    text = await ctx.store.fetch(
        tenant, first.raw.source_id, {"blocks": [0, 0]}
    )
    assert "pilot shipped" in text

    # L1: the rebuilt lexical index actually answers under the frozen tenant.
    hits = await ctx.lexical.search(tenant, "budget", limit=5)
    assert hits, "the snapshot's lexical index returned nothing"

    # L3 lexical + semantic: the claim face survived, and the semantic side kept its ORIGINAL
    # vector (a payload-only copy would return no hit for the claim's own text).
    claim_hits = await ctx.lexical.search_claims(tenant, "pilot", limit=5)
    assert [h.document_path for h in claim_hits] == ["memory/pilot.md"]
    semantic = await ctx.vectors.search_claims(
        tenant, await embeddings.aembed_query("the pilot shipped in March"), limit=5
    )
    assert [h.anchor for h in semantic] == ["aa11"]

    # The owner keeps moving; the frozen tenant does not.
    later = _source(owner, "reorg notes", ["the reorg happened in July"])
    await ctx.store.add(owner, later)
    await ctx.lexical.index_blocks(owner, later.raw.source_id, later.blocks)

    assert await ctx.lexical.search(owner, "reorg", limit=5)
    assert not await ctx.lexical.search(tenant, "reorg", limit=5)
    tenant_sources = {str(r.source_id) for r in await ctx.store.list(tenant)}
    assert str(later.raw.source_id) not in tenant_sources

    # A frozen tenant never shows up as a user.
    assert str(tenant) not in await ctx.store.list_users()

    # Delete leaves all three stores clean and the owner untouched.
    assert await kb_snapshots.delete(ctx, owner, ready.snapshot_id)
    created.remove(ready.snapshot_id)
    assert await ctx.store.list(tenant) == []
    assert await ctx.store.list_canonical_claims(tenant) == []
    assert await ctx.lexical.search(tenant, "budget", limit=5) == []
    assert await ctx.vectors.count_points(tenant) == 0
    assert await kb_snapshots.list_snapshots(ctx, owner) == []
    assert len(await ctx.store.list(owner)) == 3


async def test_rerunning_the_copy_is_idempotent(frozen_ctx):
    ctx, owner, _first, created = frozen_ctx
    snapshot = await kb_snapshots.create(ctx, owner, "retry me")
    created.append(snapshot.snapshot_id)

    first_run = await kb_snapshots.run_copy(ctx, owner, snapshot)
    second_run = await kb_snapshots.run_copy(ctx, owner, snapshot)
    # Same counts, not doubled: every step keys on a deterministic identity.
    assert second_run.counts == first_run.counts
    assert await ctx.vectors.count_points(snapshot.tenant_id) == 1
