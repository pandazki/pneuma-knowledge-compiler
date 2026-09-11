"""VectorIndex over Qdrant (architecture.md §3, §6). L2, by IntakePlan.

Single collection `pneuma_knowledge_chunks`. The tenant filter is built mechanically from
user_id inside every search (invariant I1) — the public `search` has no
parameter for "no filter", so the business layer cannot construct a cross-user
query. Chunk payloads carry user_id/source_id/block interval; point ids are
deterministic (uuid5) so re-indexing a chunk overwrites in place.

Client: `AsyncQdrantClient` (same qdrant-client package, no new dependency) — genuinely
async, so an L2 round trip never blocks the single service event loop.

THE ARCHIVE FILTER (docs/design/archive.md §3). Both layers carry a boolean payload field
`archived`, and both default searches exclude it with `must_not archived = true` — the same
shape as the existing `must_not layer = claim` clause, and for the same reason: a point
written before the field existed carries no `archived` key, does not match the condition,
and therefore stays LIVE. Excluding an equivalent `must archived = false` is deliberate; it
would silently drop every legacy point until a full derived rebuild.
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

#: How many points one write request carries. Every write in this adapter goes out in
#: batches of at most this many, because a request's size is the one thing the writer
#: controls and the read that waits for its response is what breaks first: a source's whole
#: L2 — a long window's points, each with a full vector — went out as ONE `upsert(wait=True)`
#: and the read died mid-response (`httpx.ReadError`, live, three times in a row, until the
#: job was failed for it).
#:
#: Partial progress is SAFE here, and not by luck: every point id in this collection is a
#: uuid5 over the tenant and the thing it indexes (`upsert_chunks`, `_claim_point_id`), so a
#: batch that landed and is sent again overwrites itself, and a batch that never landed is
#: written by the retry. A write interrupted halfway leaves the collection with a prefix of
#: its points and no duplicates — which is exactly what the retried job then completes.
UPSERT_BATCH = 256

#: How long a request to Qdrant may take before the client gives up. The library's own
#: default is 5 seconds, which is a read timeout on a search and an ambush on a write of a
#: few hundred vectors; batching bounds the size and this bounds the wait.
CLIENT_TIMEOUT_S = 60.0


def _batched(points: list[Any], size: int) -> list[list[Any]]:
    """`points` in chunks of at most `size` (a non-positive size means one request)."""
    if size <= 0 or len(points) <= size:
        return [points]
    return [points[start : start + size] for start in range(0, len(points), size)]


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
    episode_summary_text: str = ""


@dataclass(frozen=True)
class ClaimHitRow:
    """L3 semantic claim hit — the ClaimHit shape core recall fuses (ports/claim_index)."""

    anchor: str
    document_path: str
    section_path: list[str]
    text: str
    citations: list[dict[str, Any]]
    score: float


#: The one excluding clause, stated once (see the module docstring). `must_not` and not a
#: positive match, so a point with no `archived` key reads as live.
def _not_archived() -> list[models.Condition]:
    return [
        models.FieldCondition(key="archived", match=models.MatchValue(value=True))
    ]


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


async def existing_dimension(
    url: str, collection: str, *, timeout: float = CLIENT_TIMEOUT_S
) -> int | None:
    """The vector size of an existing collection, or None when there is none yet. A process
    that only reads adopts the dimension the collection already has instead of spending a
    model call to learn it; the engine, which may have to CREATE the collection, still probes."""
    client = AsyncQdrantClient(url=url, timeout=max(1, int(timeout)))
    try:
        if not await client.collection_exists(collection):
            return None
        vectors = (await client.get_collection(collection)).config.params.vectors
        return None if isinstance(vectors, dict) else int(vectors.size)
    finally:
        await client.close()


class QdrantVectorIndex:
    """Construction is inert (no I/O): the collection probe/creation that used to run in
    `__init__` is now `await ensure_collection()`, called once by `build_context` (and by
    the integration fixtures). An event loop cannot run I/O inside a constructor."""

    #: The write bound as a CLASS default, so it is the deployment's default for any instance
    #: — including the ones tests build around an in-memory client without going through
    #: `__init__`. A deployment states its own per instance below.
    _upsert_batch: int = UPSERT_BATCH

    def __init__(
        self,
        url: str,
        dim: int,
        *,
        collection: str = COLLECTION,
        timeout: float = CLIENT_TIMEOUT_S,
        upsert_batch: int = UPSERT_BATCH,
    ) -> None:
        # The client's own default is 5 seconds (`CLIENT_TIMEOUT_S` says why that is not a
        # timeout this deployment can live with). Stated as a whole number of seconds
        # because that is what the client takes.
        self._client = AsyncQdrantClient(url=url, timeout=max(1, int(timeout)))
        self._collection = collection
        self._dim = dim
        self._upsert_batch = int(upsert_batch)

    #: The payload fields every filter in this adapter names, and therefore the indexes the
    #: collection must carry: the tenant clause (I1), the source a flip is addressed by, the
    #: archive mark, and the layer that separates L2 chunks from the L3 claim projection.
    _PAYLOAD_INDEXES: tuple[tuple[str, models.PayloadSchemaType], ...] = (
        ("user_id", models.PayloadSchemaType.KEYWORD),
        ("source_id", models.PayloadSchemaType.KEYWORD),
        ("archived", models.PayloadSchemaType.BOOL),
        ("layer", models.PayloadSchemaType.KEYWORD),
    )

    async def ensure_collection(self) -> None:
        """Create the collection if absent, and declare the payload indexes EITHER WAY.

        The index declaration deliberately runs on an existing collection too. A deployment
        that already holds one predates every index added since it was created, and an
        early return would mean the collection that most needs the new index is the one that
        never gets it — a filter would then fall back to a full scan, or, for a field the
        server refuses to filter unindexed, fail. `create_payload_index` is idempotent, so
        re-declaring what is already there costs one no-op call per boot.
        """
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
            await self._ensure_payload_indexes()
            return

        await self._client.create_collection(
            self._collection,
            vectors_config=models.VectorParams(
                size=self._dim, distance=models.Distance.COSINE
            ),
        )
        await self._ensure_payload_indexes()

    async def _ensure_payload_indexes(self) -> None:
        for field_name, schema in self._PAYLOAD_INDEXES:
            await self._client.create_payload_index(
                self._collection,
                field_name=field_name,
                field_schema=schema,
            )

    async def upsert_chunks(
        self, user_id: UserId, chunks: list[SemanticChunk], *, archived: bool = False
    ) -> None:
        """Upsert one source's L2 points, carrying its archive mark.

        `archived` is the L0 mark (`RawSource.archived_at is not None`), passed by the
        caller: L2 coverage follows the IntakePlan, but whether the material is archived is
        a fact about the source, not about the chunker."""
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
                    "archived": archived,
                    "representation": c.representation,
                    "episode_summary_text": c.episode_summary_text,
                },
            )
            for c in chunks
        ]
        await self._upsert_points(points)

    async def _upsert_points(self, points: list[models.PointStruct]) -> None:
        """Write `points` in bounded batches (`UPSERT_BATCH`), never as one request.

        The one place every write in this adapter goes through, so no caller has to remember
        the bound and none of them can send a whole layer in a single request again."""
        for batch in _batched(points, self._upsert_batch):
            if batch:
                await self._client.upsert(self._collection, points=batch, wait=True)

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
                    # Derived from the claim's document path by the projection, never
                    # decided here (docs/design/archive.md §2.1).
                    "archived": c.archived,
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
        # ids make bounded batches idempotent, so a failed rebuild can safely retry — the
        # same reasoning `UPSERT_BATCH` now states once for every write here, which is why
        # this path no longer carries a bound of its own.
        await self._upsert_points(points)

    async def sync_claims(
        self,
        user_id: UserId,
        upserts: list[ProjectedClaim],
        vectors: list[list[float]],
        deleted_keys: list[tuple[str, str]],
    ) -> None:
        """Idempotently apply a claim-layer delta using deterministic point ids."""
        if deleted_keys:
            # Batched for the same reason the upserts are: a rebuild's delta can name
            # thousands of ids, and one request carrying all of them is one read that can
            # die on the way back. A delete of an id that is already gone is a no-op, so a
            # retried batch costs nothing.
            ids = [
                _claim_point_id(user_id, document_path, anchor)
                for document_path, anchor in deleted_keys
            ]
            for batch in _batched(ids, self._upsert_batch):
                await self._client.delete(
                    self._collection,
                    points_selector=models.PointIdsList(points=batch),
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
        self,
        user_id: UserId,
        embedding: list[float],
        *,
        limit: int = 40,
        include_archived: bool = False,
    ) -> list[ClaimHitRow]:
        """L3 semantic claim search; the archive is excluded unless the call says otherwise."""
        base = _tenant_layer_filter(user_id, LAYER_CLAIM)  # I1 + layer
        query_filter = (
            base
            if include_archived
            else models.Filter(must=base.must, must_not=_not_archived())
        )
        response = await self._client.query_points(
            self._collection,
            query=list(embedding),
            query_filter=query_filter,
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

    async def set_source_archived(
        self, user_id: UserId, source_id: SourceId, archived: bool
    ) -> None:
        """Flip one source's L2 chunk points to `archived`, without re-embedding them.

        `set_payload` merges the one key into the points the selector matches, so the
        vectors, the verbatim text and the char spans are untouched — an archive is a change
        of attention, not of content, and re-embedding a library to express it would be both
        expensive and a lie about what changed.

        The selector is the tenant clause (I1) plus the source, minus the claim layer: a
        claim's archive state is a property of its DOCUMENT's path and is written by the
        projection, so a source-addressed flip must not reach it even when a claim in the
        same tenant cites that source.
        """
        await self._client.set_payload(
            self._collection,
            payload={"archived": archived},
            points=models.Filter(
                must=[
                    *_tenant_filter(user_id).must,
                    models.FieldCondition(
                        key="source_id", match=models.MatchValue(value=str(source_id))
                    ),
                ],
                must_not=[
                    models.FieldCondition(
                        key="layer", match=models.MatchValue(value=LAYER_CLAIM)
                    )
                ],
            ),
            wait=True,
        )

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

    async def delete_source_chunks(self, user_id: UserId, source_id: SourceId) -> None:
        """Replace an episode selection without retaining vectors for omitted blocks."""
        selector = self._chunk_layer_filter(user_id)
        selector.must = [
            *(selector.must or []),
            models.FieldCondition(key="source_id", match=models.MatchValue(value=str(source_id))),
        ]
        await self._client.delete(
            self._collection, points_selector=models.FilterSelector(filter=selector), wait=True,
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
        self, source: UserId, target: UserId, *, batch_size: int | None = None
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

        `batch_size` is how many points one round trip reads AND writes; it follows the
        adapter's configured write bound unless a caller states its own.
        """
        limit = int(batch_size or self._upsert_batch)
        copied = 0
        offset: Any = None
        while True:
            points, offset = await self._client.scroll(
                self._collection,
                scroll_filter=_tenant_filter(source),
                limit=limit,
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
            await self._upsert_points(batch)
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
        include_archived: bool = False,
    ) -> list[SemanticHitRow]:
        """L2 semantic search; the archive is excluded unless the call says otherwise."""
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
                    ),
                    *([] if include_archived else _not_archived()),
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
                    episode_summary_text=str(payload.get("episode_summary_text") or ""),
                )
            )
        return hits

    async def ping(self) -> None:
        """One request to the server; raises the client's transport error while it is away."""
        await self._client.collection_exists(self._collection)

    async def aclose(self) -> None:
        """Close the underlying async client (lifespan/worker shutdown)."""
        await self._client.close()
