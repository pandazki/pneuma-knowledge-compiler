"""VectorIndex over Qdrant (architecture.md §3, §6). L2, by IntakePlan.

Single collection `pneuma_knowledge_chunks`. The tenant filter is built mechanically from
user_id inside every search (invariant I1) — the public `search` has no
parameter for "no filter", so the business layer cannot construct a cross-user
query. Chunk payloads carry user_id/source_id/block interval; point ids are
deterministic (uuid5) so re-indexing a chunk overwrites in place.

Client: `AsyncQdrantClient` (same qdrant-client package, no new dependency) — genuinely
async, so an L2 round trip never blocks the single service event loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.ports.vector_index import SemanticChunk
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from qdrant_client import AsyncQdrantClient, models

COLLECTION = "pneuma_knowledge_chunks"
_POINT_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

# One shared collection holds both layers; payload.layer distinguishes L2 raw chunks
# ("chunk") from the L3 claim projection ("claim"). Retrieval always filters by layer.
LAYER_CHUNK = "chunk"
LAYER_CLAIM = "claim"
_CLAIM_UPSERT_BATCH_SIZE = 128


@dataclass(frozen=True)
class SemanticHitRow:
    source_id: SourceId
    block_start: int
    block_end: int
    char_start: int
    char_end: int
    text: str
    score: float
    representation: Literal["raw", "episode"] = "raw"


@dataclass(frozen=True)
class ClaimHitRow:
    """L3 semantic claim hit — the ClaimHit shape core recall fuses (ports/claim_index)."""

    anchor: str
    document_path: str
    section_path: list[str]
    text: str
    citations: list[dict[str, Any]]
    score: float


def _tenant_filter(user_id: UserId) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=str(user_id)),
            )
        ]
    )


def _tenant_layer_filter(user_id: UserId, layer: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=str(user_id)),
            ),
            models.FieldCondition(
                key="layer", match=models.MatchValue(value=layer)
            ),
        ]
    )


def _claim_point_id(user_id: UserId, document_path: str, anchor: str) -> str:
    return str(
        uuid.uuid5(
            _POINT_NS,
            f"{user_id}:claim:{document_path}:{anchor}",
        )
    )


class QdrantVectorIndex:
    """Construction is inert (no I/O): the collection probe/creation that used to run in
    `__init__` is now `await ensure_collection()`, called once by `build_context` (and by
    the integration fixtures). An event loop cannot run I/O inside a constructor."""

    def __init__(self, url: str, dim: int, *, collection: str = COLLECTION) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection
        self._dim = dim

    async def ensure_collection(self) -> None:
        if await self._client.collection_exists(self._collection):
            info = await self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            if isinstance(vectors, dict):
                raise RuntimeError(
                    f"Qdrant collection {self._collection!r} uses named vectors; "
                    "Pneuma requires one unnamed vector"
                )
            actual_dim = int(vectors.size)
            if actual_dim != self._dim:
                raise RuntimeError(
                    f"Qdrant collection {self._collection!r} expected "
                    f"{self._dim} dimensions but has {actual_dim}; select a new "
                    "PNEUMA_KNOWLEDGE_QDRANT_COLLECTION or rebuild the collection"
                )
            return

        await self._client.create_collection(
            self._collection,
            vectors_config=models.VectorParams(
                size=self._dim, distance=models.Distance.COSINE
            ),
        )
        await self._client.create_payload_index(
            self._collection,
            field_name="user_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    async def upsert_chunks(
        self, user_id: UserId, chunks: list[SemanticChunk]
    ) -> None:
        if not chunks:
            return
        points = [
            models.PointStruct(
                # Point id keys on the char span, not the block interval: several
                # sub-block chunks now share one covering block, so a block-keyed id
                # would make them overwrite each other. Char span is unique per chunk.
                id=str(
                    uuid.uuid5(
                        _POINT_NS,
                        f"{user_id}:{c.source_id}:{c.char_start}:{c.char_end}"
                        + (":episode" if c.representation == "episode" else ""),
                    )
                ),
                vector=list(c.embedding),
                payload={
                    "user_id": str(user_id),
                    "source_id": str(c.source_id),
                    "block_start": c.block_start,
                    "block_end": c.block_end,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "text": c.text,
                    "layer": LAYER_CHUNK,
                    "representation": c.representation,
                },
            )
            for c in chunks
        ]
        await self._client.upsert(self._collection, points=points, wait=True)

    # --- L3 claim layer (M4) --------------------------------------------------

    async def upsert_claims(
        self,
        user_id: UserId,
        claims: list[ProjectedClaim],
        vectors: list[list[float]],
    ) -> None:
        """Upsert claim-layer points (payload.layer='claim'); deterministic point ids
        so re-projecting a claim overwrites in place."""
        if not claims:
            return
        points = [
            models.PointStruct(
                id=_claim_point_id(user_id, c.document_path, str(c.anchor)),
                vector=list(vec),
                payload={
                    "user_id": str(user_id),
                    "layer": LAYER_CLAIM,
                    "anchor": str(c.anchor),
                    "document_path": c.document_path,
                    "section_path": list(c.section_path),
                    "text": c.text,
                    "citations": [
                        {
                            "source_id": str(cit.source_id),
                            "block_start": cit.block_start,
                            "block_end": cit.block_end,
                        }
                        for cit in c.citations
                    ],
                },
            )
            for c, vec in zip(claims, vectors)
        ]
        # A full projection can contain thousands of 1536-dimension vectors. Sending
        # the whole tenant in one REST request is large enough to trip intermediary or
        # client read limits even though Qdrant finishes the write. Deterministic point
        # ids make bounded batches idempotent, so a failed rebuild can safely retry.
        for start in range(0, len(points), _CLAIM_UPSERT_BATCH_SIZE):
            await self._client.upsert(
                self._collection,
                points=points[start : start + _CLAIM_UPSERT_BATCH_SIZE],
                wait=True,
            )

    async def sync_claims(
        self,
        user_id: UserId,
        upserts: list[ProjectedClaim],
        vectors: list[list[float]],
        deleted_keys: list[tuple[str, str]],
    ) -> None:
        """Idempotently apply a claim-layer delta using deterministic point ids."""
        if deleted_keys:
            await self._client.delete(
                self._collection,
                points_selector=models.PointIdsList(
                    points=[
                        _claim_point_id(user_id, document_path, anchor)
                        for document_path, anchor in deleted_keys
                    ]
                ),
                wait=True,
            )
        if upserts:
            await self.upsert_claims(user_id, upserts, vectors)

    async def count_claims(self, user_id: UserId) -> int:
        """Exact claim-layer point count for projection consistency audits."""
        result = await self._client.count(
            self._collection,
            count_filter=_tenant_layer_filter(user_id, LAYER_CLAIM),
            exact=True,
        )
        return int(result.count)

    async def delete_claims(self, user_id: UserId) -> None:
        """Drop the user's claim-layer points (full projection rebuild, I2)."""
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=_tenant_layer_filter(user_id, LAYER_CLAIM)
            ),
            wait=True,
        )

    async def search_claims(
        self, user_id: UserId, embedding: list[float], *, limit: int = 40
    ) -> list[ClaimHitRow]:
        response = await self._client.query_points(
            self._collection,
            query=list(embedding),
            query_filter=_tenant_layer_filter(user_id, LAYER_CLAIM),  # I1 + layer
            limit=limit,
            with_payload=True,
        )
        hits: list[ClaimHitRow] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                ClaimHitRow(
                    anchor=str(payload.get("anchor", "")),
                    document_path=payload.get("document_path", ""),
                    section_path=list(payload.get("section_path") or []),
                    text=payload.get("text", ""),
                    citations=list(payload.get("citations") or []),
                    score=float(point.score),
                )
            )
        return hits

    def _chunk_layer_filter(self, user_id: UserId) -> models.Filter:
        # tenant + "not a claim": matches L2 chunk points, including legacy points that
        # predate the layer field (they are chunks). Mirrors `search`'s must_not clause.
        return models.Filter(
            must=_tenant_filter(user_id).must,
            must_not=[
                models.FieldCondition(
                    key="layer", match=models.MatchValue(value=LAYER_CLAIM)
                )
            ],
        )

    async def delete_chunks(self, user_id: UserId) -> None:
        """Drop only this user's L2 chunk points (leaving L3 claims intact) — used to
        re-index stale chunks without disturbing the claim projection."""
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=self._chunk_layer_filter(user_id)
            ),
            wait=True,
        )

    async def count_chunks(self, user_id: UserId) -> int:
        """Number of L2 chunk points a user has (re-index before/after verification)."""
        result = await self._client.count(
            self._collection,
            count_filter=self._chunk_layer_filter(user_id),
            exact=True,
        )
        return result.count

    def _copied_point_id(self, target: UserId, payload: dict[str, Any]) -> str:
        """The point id a copied point takes under `target` — re-derived, never reused.

        Both id schemes in this collection are `uuid5` over a string that STARTS with the
        tenant, so a copy cannot keep the source id (it would collide with the source point
        and the second upsert would overwrite the first). Re-deriving from the payload is
        also what makes the copy idempotent: a retried copy computes the same ids and
        overwrites its own earlier points instead of duplicating them."""
        if payload.get("layer") == LAYER_CLAIM:
            return _claim_point_id(
                target,
                str(payload.get("document_path", "")),
                str(payload.get("anchor", "")),
            )
        # Chunk ids key on the char span (see `upsert_chunks`). Legacy points predate the
        # char span; fall back to the block interval exactly as `search` does, so a legacy
        # point copies to one stable id rather than a random one.
        char_start = payload.get("char_start", payload.get("block_start"))
        char_end = payload.get("char_end", payload.get("block_end"))
        representation = str(payload.get("representation") or "raw")
        return str(
            uuid.uuid5(
                _POINT_NS,
                f"{target}:{payload.get('source_id')}:{char_start}:{char_end}"
                + (":episode" if representation == "episode" else ""),
            )
        )

    async def copy_tenant(
        self, source: UserId, target: UserId, *, batch_size: int = 256
    ) -> int:
        """Copy every point of `source` under `target`, CARRYING THE ORIGINAL VECTORS.

        This is the one copy in the snapshot pipeline that cannot be a rebuild. Re-embedding
        would defeat the entire point of a frozen snapshot: switching embedding model or
        re-chunking later would silently change what a "frozen" snapshot retrieves. So the
        vectors are moved as opaque numbers (`with_vectors=True` → the same list upserted),
        and nothing in this method knows or cares which model produced them.

        Both layers ride along in one pass — L2 chunks and the L3 claim projection are points
        in the same collection, distinguished by `payload.layer`, and a snapshot needs both.

        Returns the number of points copied. Idempotent (see `_copied_point_id`), so a failed
        pipeline can be retried without duplicating anything.
        """
        copied = 0
        offset: Any = None
        while True:
            points, offset = await self._client.scroll(
                self._collection,
                scroll_filter=_tenant_filter(source),
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if not points:
                break
            batch: list[models.PointStruct] = []
            for point in points:
                payload = dict(point.payload or {})
                vector = point.vector
                if vector is None:
                    # A point with no vector cannot participate in semantic search and would
                    # be rejected by upsert. Skipping it silently is the only wrong answer, so
                    # it fails the copy loudly instead.
                    raise RuntimeError(
                        f"point {point.id} of tenant {source!r} has no vector; "
                        "the snapshot copy would lose it"
                    )
                payload["user_id"] = str(target)
                batch.append(
                    models.PointStruct(
                        id=self._copied_point_id(target, payload),
                        vector=vector,
                        payload=payload,
                    )
                )
            await self._client.upsert(self._collection, points=batch, wait=True)
            copied += len(batch)
            if offset is None:
                break
        return copied

    async def count_points(self, user_id: UserId) -> int:
        """Every point a tenant owns, both layers (snapshot copy verification)."""
        result = await self._client.count(
            self._collection,
            count_filter=_tenant_filter(user_id),
            exact=True,
        )
        return int(result.count)

    async def delete_user(self, user_id: UserId) -> None:
        """Delete all of a user's points via the tenant filter (test-teardown
        hygiene); the single shared collection is left in place."""
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=_tenant_filter(user_id)
            ),
            wait=True,
        )

    async def search(
        self,
        user_id: UserId,
        embedding: list[float],
        *,
        limit: int = 20,
        representation: Literal["raw", "episode"] = "raw",
    ) -> list[SemanticHitRow]:
        representation_filter = models.FieldCondition(
            key="representation",
            match=models.MatchValue(value=representation),
        )
        if representation == "raw":
            # Pre-dual-vector points have no representation tag. They are the historical raw
            # channel and remain searchable until the next derived rebuild.
            representation_clause = models.Filter(
                should=[
                    representation_filter,
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="representation")),
                ],
            )
        else:
            representation_clause = models.Filter(must=[representation_filter])
        response = await self._client.query_points(
            self._collection,
            query=list(embedding),
            # I1: tenant always injected; must_not layer=claim keeps rag L2 to raw
            # chunks (legacy points with no layer still match — they are chunks).
            query_filter=models.Filter(
                must=[*_tenant_filter(user_id).must, representation_clause],
                must_not=[
                    models.FieldCondition(
                        key="layer", match=models.MatchValue(value=LAYER_CLAIM)
                    )
                ],
            ),
            limit=limit,
            with_payload=True,
        )
        hits: list[SemanticHitRow] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                SemanticHitRow(
                    source_id=SourceId(payload["source_id"]),
                    block_start=int(payload["block_start"]),
                    block_end=int(payload["block_end"]),
                    # Legacy points (pre-chonkie) have no char span; default to the block
                    # interval's edges so the field is always present and monotone.
                    char_start=int(payload.get("char_start", payload["block_start"])),
                    char_end=int(payload.get("char_end", payload["block_end"])),
                    text=payload.get("text", ""),
                    score=float(point.score),
                    representation=str(payload.get("representation") or "raw"),
                )
            )
        return hits

    async def aclose(self) -> None:
        """Close the underlying async client (lifespan/worker shutdown)."""
        await self._client.close()
