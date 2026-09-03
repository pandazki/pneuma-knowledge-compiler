"""Knowledge-base snapshots as frozen tenants: lifecycle, write protection, read routing.

These tests drive the pipeline over in-memory stand-ins for the four stores, so they assert
the MECHANISM (what is copied, under which tenant, in which order, what happens on failure)
without needing PG/Meili/Qdrant. The real three-store round trip is
`integration/test_kb_snapshot_pipeline.py`.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_service import kb_snapshots
from pneuma_knowledge_service.snapshot_tenant import (
    RESERVED_PREFIX,
    SnapshotTenantWriteError,
    assert_writable,
    is_snapshot_tenant,
    snapshot_tenant_id,
)

OWNER = UserId("u-kbsnap-owner")


# --------------------------------------------------------------------------- stand-ins


@dataclass
class _Block:
    index: int
    text: str
    section_path: list[str] = field(default_factory=list)
    images: list[_Image] = field(default_factory=list)


@dataclass
class _Image:
    storage_key: str
    sha256: str


@dataclass
class _Raw:
    source_id: SourceId
    # The archive mark rides the copy: a snapshot's L1 excludes exactly what the base did.
    archived_at: object = None


@dataclass
class _Normalized:
    blocks: list[_Block]


class FakeStore:
    """The PG face the snapshot pipeline uses, tenant-keyed exactly like the real one."""

    def __init__(self) -> None:
        # tenant -> {source_id: [blocks]}
        self.sources: dict[str, dict[str, list[_Block]]] = {}
        self.claims: dict[str, list[dict[str, Any]]] = {}
        self.registry: dict[tuple[str, str], dict[str, Any]] = {}
        self.copy_calls = 0
        self.fail_copy: Exception | None = None
        #: Shared step log — the pipeline's ORDER is a correctness property, so it is observed.
        self.order: list[str] = []

    # -- registry ---------------------------------------------------------------
    async def create_kb_snapshot(
        self, user_id, snapshot_id, *, label, tenant_id, canonical_ref, created_at
    ):  # noqa: ANN001
        self.registry[(str(user_id), snapshot_id)] = {
            "snapshot_id": snapshot_id,
            "label": label,
            "tenant_id": tenant_id,
            "canonical_ref": canonical_ref,
            "status": kb_snapshots.STATUS_CREATING,
            "counts": {},
            "detail": None,
            "created_at": created_at,
            "ready_at": None,
        }

    async def finish_kb_snapshot(
        self,
        user_id,  # noqa: ANN001
        snapshot_id,  # noqa: ANN001
        *,
        status,  # noqa: ANN001
        counts=None,  # noqa: ANN001
        detail=None,  # noqa: ANN001
        ready_at=None,  # noqa: ANN001
        canonical_ref=None,  # noqa: ANN001
    ):
        row = self.registry[(str(user_id), snapshot_id)]
        row.update(
            status=status, counts=counts or {}, detail=detail, ready_at=ready_at
        )
        # Mirrors the real COALESCE: None keeps the provisional ref from creation.
        if canonical_ref is not None:
            row["canonical_ref"] = canonical_ref

    async def list_kb_snapshots(self, user_id):  # noqa: ANN001
        return [
            dict(row)
            for (uid, _), row in self.registry.items()
            if uid == str(user_id)
        ]

    async def get_kb_snapshot(self, user_id, ref):  # noqa: ANN001
        for (uid, sid), row in self.registry.items():
            if uid == str(user_id) and ref in (sid, row["label"]):
                return dict(row)
        return None

    async def delete_kb_snapshot(self, user_id, snapshot_id):  # noqa: ANN001
        self.registry.pop((str(user_id), snapshot_id), None)

    # -- tenant copy ------------------------------------------------------------
    async def copy_tenant_rows(self, source, target):  # noqa: ANN001
        self.copy_calls += 1
        self.order.append("pg")
        if self.fail_copy is not None:
            raise self.fail_copy
        src, dst = str(source), str(target)
        # Mirrors the real INSERT…SELECT … ON CONFLICT DO NOTHING: existing keys survive.
        into = self.sources.setdefault(dst, {})
        for sid, blocks in self.sources.get(src, {}).items():
            into.setdefault(sid, deepcopy(blocks))
        claims = self.claims.setdefault(dst, [])
        seen = {(c["document_path"], c["anchor"]) for c in claims}
        for claim in self.claims.get(src, []):
            key = (claim["document_path"], claim["anchor"])
            if key not in seen:
                claims.append(dict(claim))
                seen.add(key)
        return {
            "sources": len(into),
            "blocks": sum(len(b) for b in into.values()),
            "claims": len(claims),
        }

    async def delete_tenant_rows(self, user_id):  # noqa: ANN001
        self.sources.pop(str(user_id), None)
        self.claims.pop(str(user_id), None)

    # -- ContentStore face the rebuild reads ------------------------------------
    async def list(self, user_id):  # noqa: ANN001
        return [_Raw(SourceId(sid)) for sid in sorted(self.sources.get(str(user_id), {}))]

    async def get(self, user_id, source_id):  # noqa: ANN001
        return _Normalized(self.sources[str(user_id)][str(source_id)])

    async def list_canonical_claims(self, user_id):  # noqa: ANN001
        return [dict(c) for c in self.claims.get(str(user_id), [])]

    async def list_media_objects(self, user_id):  # noqa: ANN001
        objects: dict[str, str] = {}
        for blocks in self.sources.get(str(user_id), {}).values():
            for block in blocks:
                for image in block.images:
                    previous = objects.setdefault(image.storage_key, image.sha256)
                    if previous != image.sha256:
                        raise RuntimeError("media key has conflicting digests")
        return objects

    async def rewrite_media_keys(self, user_id, replacements):  # noqa: ANN001
        changed = 0
        for blocks in self.sources.get(str(user_id), {}).values():
            for block in blocks:
                for image in block.images:
                    if image.storage_key in replacements:
                        image.storage_key = replacements[image.storage_key]
                        changed += 1
        return changed


class FakeLexical:
    def __init__(self) -> None:
        self.blocks: dict[str, dict[str, list[_Block]]] = {}
        self.claims: dict[str, list] = {}
        self.deleted: list[str] = []

    async def index_blocks(self, user_id, source_id, blocks, *, archived=False):  # noqa: ANN001
        self.blocks.setdefault(str(user_id), {})[str(source_id)] = list(blocks)

    async def index_claims(self, user_id, claims):  # noqa: ANN001
        self.claims[str(user_id)] = list(claims)  # full rebuild, like the real adapter

    async def delete_user(self, user_id):  # noqa: ANN001
        self.deleted.append(str(user_id))
        self.blocks.pop(str(user_id), None)
        self.claims.pop(str(user_id), None)


class FakeVectors:
    """Both layers live in one collection, so the fake carries each point's layer too — the
    completeness identity the pipeline asserts (`points − chunks == claims`) is only
    meaningful over a store that can tell an L2 chunk point from an L3 claim point."""

    def __init__(self, order: list[str] | None = None) -> None:
        # tenant -> {point_id: vector} and tenant -> {point_id: layer}
        self.points: dict[str, dict[str, list[float]]] = {}
        self.layers: dict[str, dict[str, str]] = {}
        self.deleted: list[str] = []
        self.order = order if order is not None else []

    def add(self, tenant: str, point_id: str, vector: list[float], layer: str) -> None:
        self.points.setdefault(tenant, {})[point_id] = list(vector)
        self.layers.setdefault(tenant, {})[point_id] = layer

    async def copy_tenant(self, source, target, *, batch_size=256):  # noqa: ANN001, ARG002
        self.order.append("qdrant")
        # Deterministic ids under the target, so a retry overwrites instead of duplicating.
        into = self.points.setdefault(str(target), {})
        into_layers = self.layers.setdefault(str(target), {})
        for pid, vector in self.points.get(str(source), {}).items():
            into[f"{target}:{pid}"] = list(vector)
            into_layers[f"{target}:{pid}"] = self.layers.get(str(source), {}).get(
                pid, "chunk"
            )
        return len(into)

    async def count_chunks(self, user_id):  # noqa: ANN001
        return sum(
            1
            for layer in self.layers.get(str(user_id), {}).values()
            if layer != "claim"
        )

    async def delete_user(self, user_id):  # noqa: ANN001
        self.deleted.append(str(user_id))
        self.points.pop(str(user_id), None)
        self.layers.pop(str(user_id), None)


class FakeCanonical:
    """HEAD that can MOVE mid-pipeline, the way a live base's does.

    `advance_on_read` reproduces the real hazard: the replay commits between the request and
    the copy, so a ref pinned too early names a tree older than the claim rows copied after
    it — and a claim would then cite a document `read_document` cannot open."""

    def __init__(self, head: str = "sha-head", advance_on_read: str | None = None) -> None:
        self.head = head
        self._advance_on_read = advance_on_read
        self.reads = 0

    async def snapshots(self, user_id):  # noqa: ANN001
        self.reads += 1
        if self._advance_on_read and self.reads > 1:
            self.head = self._advance_on_read
        return [SnapshotRef(ref=self.head, label="latest")] if self.head else []


class FakeMedia:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.deleted: list[str] = []
        self.copies: list[tuple[str, str, dict[str, str]]] = []

    async def copy_user(self, source, target, objects):  # noqa: ANN001
        self.order.append("media")
        self.copies.append((str(source), str(target), dict(objects)))
        target_prefix = f"media/{target}"
        return {
            key: f"{target_prefix}/{digest}"
            for key, digest in objects.items()
        }

    async def delete_user(self, user_id):  # noqa: ANN001
        self.deleted.append(str(user_id))


@dataclass
class FakeCtx:
    store: FakeStore
    lexical: FakeLexical
    vectors: FakeVectors
    canonical: FakeCanonical
    media: FakeMedia


def _ctx(head: str = "sha-head") -> FakeCtx:
    store = FakeStore()
    store.sources[str(OWNER)] = {
        "src-a": [_Block(0, "the pilot shipped"), _Block(1, "owner is on it")],
        "src-b": [_Block(0, "budget approved")],
    }
    store.claims[str(OWNER)] = [
        {
            "document_path": "memory/a.md",
            "anchor": "aa11",
            "section_path": ["Facts"],
            "text": "the pilot shipped",
            "citations": [{"source_id": "src-a", "block_start": 0, "block_end": 0}],
            "snapshot_ref": head,
        }
    ]
    vectors = FakeVectors(store.order)
    # One chunk point + one claim point, matching the one claim row above: the owner satisfies
    # the completeness identity, so the copy of it does too.
    vectors.add(str(OWNER), "p1", [0.1, 0.2], "chunk")
    vectors.add(str(OWNER), "p2", [0.3, 0.4], "claim")
    return FakeCtx(store, FakeLexical(), vectors, FakeCanonical(head), FakeMedia(store.order))


# ------------------------------------------------------------------ tenant identity


def test_tenant_id_is_derived_from_the_snapshot_id_alone():
    tenant = snapshot_tenant_id("deadbeef")
    assert str(tenant) == f"{RESERVED_PREFIX}deadbeef"
    # No owner text leaks in — the id must be safe in every physical namespace (a Meili index
    # uid, a directory name), which owner ids containing '.' or ':' are not.
    assert set(str(tenant)) <= set("abcdefghijklmnopqrstuvwxyz0123456789-")


def test_write_protection_is_a_total_function_on_the_id():
    assert is_snapshot_tenant(snapshot_tenant_id("abc"))
    assert not is_snapshot_tenant(OWNER)
    assert_writable(OWNER)  # no raise
    with pytest.raises(SnapshotTenantWriteError) as excinfo:
        assert_writable(snapshot_tenant_id("abc"))
    assert excinfo.value.tenant_id == f"{RESERVED_PREFIX}abc"
    # Loud: the message names the tenant and the alternative, never a bare "forbidden".
    assert "read-only" in str(excinfo.value)


async def test_ingest_refuses_a_snapshot_tenant():
    from pneuma_knowledge_service.ingest import ingest_conversation

    with pytest.raises(SnapshotTenantWriteError):
        await ingest_conversation(
            None,  # never reached — the guard is the first statement
            snapshot_tenant_id("abc"),
            [],
            title="nope",
        )


# ----------------------------------------------------------------------- lifecycle


async def test_create_registers_creating_then_run_copy_makes_it_ready():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "before the reorg")
    assert snapshot.status == kb_snapshots.STATUS_CREATING
    assert snapshot.canonical_ref == "sha-head"
    assert not snapshot.ready  # a 'creating' snapshot is never answerable

    ready = await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    assert ready.status == kb_snapshots.STATUS_READY
    assert ready.ready
    assert ready.counts == {
        "sources": 2,
        "blocks": 3,
        "claims": 1,
        "points": 2,
        "chunks": 1,
    }
    assert ready.ready_at is not None


async def test_the_copy_lands_under_the_tenant_and_leaves_the_owner_untouched():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    tenant = str(snapshot.tenant_id)

    assert set(ctx.store.sources[tenant]) == {"src-a", "src-b"}
    assert len(ctx.store.claims[tenant]) == 1
    # L1 + L3 lexical are re-derived from the COPIED rows, per source, under the tenant.
    assert set(ctx.store.sources[tenant]) == set(ctx.lexical.blocks[tenant])
    assert [c.document_path for c in ctx.lexical.claims[tenant]] == ["memory/a.md"]
    # L2 + L3 vectors are copied, never re-embedded: the same numbers arrive.
    assert sorted(ctx.vectors.points[tenant].values()) == sorted(
        ctx.vectors.points[str(OWNER)].values()
    )
    # And the owner's own tenant is exactly as it was.
    assert set(ctx.store.sources[str(OWNER)]) == {"src-a", "src-b"}
    assert str(OWNER) not in ctx.lexical.blocks


async def test_image_objects_and_manifests_move_into_the_frozen_tenant():
    ctx = _ctx()
    digest = "a" * 64
    owner_key = f"media/{OWNER}/{digest}"
    ctx.store.sources[str(OWNER)]["src-a"][0].images.append(
        _Image(storage_key=owner_key, sha256=digest)
    )

    snapshot = await kb_snapshots.create(ctx, OWNER, "visual")
    ready = await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    tenant = str(snapshot.tenant_id)
    frozen_image = ctx.store.sources[tenant]["src-a"][0].images[0]

    assert ready.counts["images"] == 1
    assert frozen_image.storage_key == f"media/{tenant}/{digest}"
    assert ctx.store.sources[str(OWNER)]["src-a"][0].images[0].storage_key == owner_key
    assert ctx.media.copies == [(str(OWNER), tenant, {owner_key: digest})]
    assert ctx.store.order == ["qdrant", "pg", "media"]

    await kb_snapshots.delete(ctx, OWNER, snapshot.snapshot_id)
    assert ctx.media.deleted == [tenant]


async def test_the_projected_claim_keeps_its_anchor_path_and_citations():
    # The lexical claim face is rebuilt from rows, so the round trip through
    # dict -> ProjectedClaim must not drop provenance (invariant I4).
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    claim = ctx.lexical.claims[str(snapshot.tenant_id)][0]
    assert str(claim.anchor) == "aa11"
    assert claim.section_path == ("Facts",)
    assert claim.text == "the pilot shipped"
    assert [str(c.source_id) for c in claim.citations] == ["src-a"]
    assert (claim.citations[0].block_start, claim.citations[0].block_end) == (0, 0)


async def test_rerunning_the_copy_completes_rather_than_duplicates():
    # Idempotence is what makes a retry after a failed pipeline safe.
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    first = await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    second = await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    assert second.counts == first.counts
    tenant = str(snapshot.tenant_id)
    assert len(ctx.store.claims[tenant]) == 1
    assert len(ctx.vectors.points[tenant]) == 2


async def test_a_failed_step_marks_failed_with_the_reason_and_never_ready():
    ctx = _ctx()
    ctx.store.fail_copy = RuntimeError("pg went away")
    snapshot = await kb_snapshots.create(ctx, OWNER, "doomed")
    with pytest.raises(RuntimeError):
        await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    rows = await kb_snapshots.list_snapshots(ctx, OWNER)
    assert [r.status for r in rows] == [kb_snapshots.STATUS_FAILED]
    assert "pg went away" in rows[0].detail
    # Retained, not deleted: the remains have to be visible to be cleanable.
    assert rows[0].snapshot_id == snapshot.snapshot_id


async def test_a_tenant_that_fails_the_completeness_identity_is_failed_not_ready():
    """`points − chunks == claims` is the copy's own arithmetic, and it is checked before the
    row is marked ready. Every step here reports success — the numbers are what disagree, and
    that is exactly the shape a half-copied tenant takes. The polluted state this was written
    for reported 183 claim rows against 3072 claim points."""
    ctx = _ctx()
    # A claim point with no claim row behind it: the semantic face would answer with a claim
    # the row face does not have.
    ctx.vectors.add(str(OWNER), "p3", [0.5, 0.6], "claim")
    snapshot = await kb_snapshots.create(ctx, OWNER, "half copied")

    with pytest.raises(kb_snapshots.SnapshotIncomplete) as excinfo:
        await kb_snapshots.run_copy(ctx, OWNER, snapshot)

    assert (excinfo.value.points, excinfo.value.chunks, excinfo.value.claims) == (3, 1, 1)
    rows = await kb_snapshots.list_snapshots(ctx, OWNER)
    assert [r.status for r in rows] == [kb_snapshots.STATUS_FAILED]
    assert not rows[0].ready
    # The detail carries the arithmetic, not just a verdict.
    assert "2 claim points, but 1 claim rows" in rows[0].detail


async def test_a_snapshot_of_a_snapshot_is_refused():
    ctx = _ctx()
    with pytest.raises(SnapshotTenantWriteError):
        await kb_snapshots.create(ctx, snapshot_tenant_id("abc"), "nested")


async def test_delete_purges_all_four_stores_then_the_registry_row():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    tenant = str(snapshot.tenant_id)

    assert await kb_snapshots.delete(ctx, OWNER, snapshot.snapshot_id)
    assert tenant not in ctx.store.sources
    assert tenant not in ctx.store.claims
    assert ctx.lexical.deleted == [tenant]
    assert ctx.vectors.deleted == [tenant]
    assert ctx.media.deleted == [tenant]
    assert await kb_snapshots.list_snapshots(ctx, OWNER) == []
    # Idempotent: deleting again reports "nothing to delete" rather than erroring.
    assert not await kb_snapshots.delete(ctx, OWNER, snapshot.snapshot_id)


async def test_delete_never_touches_the_owner_or_the_pinned_commit():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    await kb_snapshots.delete(ctx, OWNER, snapshot.snapshot_id)
    assert set(ctx.store.sources[str(OWNER)]) == {"src-a", "src-b"}
    assert ctx.canonical.head == "sha-head"  # git history is not rewritten


# ------------------------------------------------------------------- read routing


async def test_resolve_accepts_the_id_or_the_label():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "before the reorg")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    by_id = await kb_snapshots.resolve(ctx, OWNER, snapshot.snapshot_id)
    by_label = await kb_snapshots.resolve(ctx, OWNER, "before the reorg")
    assert by_id.snapshot_id == by_label.snapshot_id == snapshot.snapshot_id
    assert by_id.tenant_id == snapshot.tenant_id


async def test_resolve_refuses_an_unknown_or_unready_snapshot():
    ctx = _ctx()
    with pytest.raises(kb_snapshots.SnapshotNotFound):
        await kb_snapshots.resolve(ctx, OWNER, "no-such-snapshot")

    creating = await kb_snapshots.create(ctx, OWNER, "still copying")
    with pytest.raises(kb_snapshots.SnapshotNotReady):
        await kb_snapshots.resolve(ctx, OWNER, creating.snapshot_id)

    ctx.store.fail_copy = RuntimeError("boom")
    broken = await kb_snapshots.create(ctx, OWNER, "broken")
    with pytest.raises(RuntimeError):
        await kb_snapshots.run_copy(ctx, OWNER, broken)
    with pytest.raises(kb_snapshots.SnapshotNotReady):
        await kb_snapshots.resolve(ctx, OWNER, broken.snapshot_id)


async def test_later_data_is_invisible_to_a_snapshot_taken_before_it():
    # The whole promise, at the storage level: the owner keeps growing, the frozen tenant does
    # not — and it does not because nothing writes to it, not because a filter hides anything.
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "before src-c")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    tenant = str(snapshot.tenant_id)

    ctx.store.sources[str(OWNER)]["src-c"] = [_Block(0, "the reorg happened")]
    ctx.store.claims[str(OWNER)].append(
        {
            "document_path": "memory/reorg.md",
            "anchor": "cc33",
            "section_path": [],
            "text": "the reorg happened",
            "citations": [],
            "snapshot_ref": "sha-later",
        }
    )

    assert "src-c" not in ctx.store.sources[tenant]
    assert [c["document_path"] for c in ctx.store.claims[tenant]] == ["memory/a.md"]
    assert "src-c" not in ctx.lexical.blocks[tenant]


async def test_canonical_at_pins_the_commit_and_is_none_without_canonical():
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "frozen")
    assert snapshot.canonical_at == SnapshotRef(ref="sha-head")

    empty = _ctx(head="")
    bare = await kb_snapshots.create(empty, OWNER, "no canonical yet")
    assert bare.canonical_ref == ""
    assert bare.canonical_at is None  # → canonical reads fall back to HEAD (i.e. nothing)


def test_created_at_is_utc():
    # The freeze moment is stated to the model, so it must not be a naive local timestamp.
    assert kb_snapshots._now().tzinfo is timezone.utc
    assert kb_snapshots._now() <= datetime.now(timezone.utc)


async def test_vectors_are_copied_before_the_source_rows():
    # Ordering is the correctness argument (see `run_copy`): a point names a source_id, so the
    # point set must not outrun the source rows, or the snapshot holds a dangling reference.
    ctx = _ctx()
    snapshot = await kb_snapshots.create(ctx, OWNER, "ordered")
    await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    assert ctx.store.order == ["qdrant", "pg"]


async def test_the_pinned_ref_is_settled_after_the_claim_rows_not_at_request_time():
    # A live base moves while the copy runs. The tree must be no older than the copied claim
    # rows, so the ref recorded at creation is provisional and re-read afterwards.
    ctx = _ctx()
    ctx.canonical = FakeCanonical("sha-at-request", advance_on_read="sha-after-copy")
    provisional = await kb_snapshots.create(ctx, OWNER, "moving base")
    assert provisional.canonical_ref == "sha-at-request"

    ready = await kb_snapshots.run_copy(ctx, OWNER, provisional)
    assert ready.canonical_ref == "sha-after-copy"


async def test_a_failed_copy_keeps_the_provisional_ref():
    # The failure path must not blank the ref: a 'failed' row still has to say what it was
    # trying to freeze, or the remains cannot be reasoned about.
    ctx = _ctx()
    ctx.store.fail_copy = RuntimeError("pg went away")
    snapshot = await kb_snapshots.create(ctx, OWNER, "doomed")
    with pytest.raises(RuntimeError):
        await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    rows = await kb_snapshots.list_snapshots(ctx, OWNER)
    assert rows[0].canonical_ref == "sha-head"
