"""Qdrant L2 against live compose — I1 tenant isolation is the hard acceptance.

Both users store an IDENTICAL chunk text, so their vectors are identical: any
cross-user hit would then be pure filter failure, not vector dissimilarity. The
mechanically-injected tenant filter must still return zero cross-user results.
"""

from __future__ import annotations

import os
import uuid

import pytest
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
from pneuma_knowledge_service.adapters.qdrant import QdrantVectorIndex
from qdrant_client import AsyncQdrantClient


def _chunk(source_id: str, text: str, embedding: list[float]) -> EmbeddedChunk:
    return EmbeddedChunk(
        source_id=SourceId(source_id),
        block_start=0,
        block_end=0,
        char_start=0,
        char_end=len(text),
        text=text,
        embedding=embedding,
    )


async def test_two_users_cannot_read_each_others_vectors(qdrant, embeddings):
    user_a = UserId(f"u-a-{uuid.uuid4().hex[:10]}")
    user_b = UserId(f"u-b-{uuid.uuid4().hex[:10]}")
    shared_text = "季度目标是提升客户留存率并降低获客成本"
    vec = await embeddings.aembed_query(shared_text)

    await qdrant.upsert_chunks(user_a, [_chunk("src-a", shared_text, vec)])
    await qdrant.upsert_chunks(user_b, [_chunk("src-b", shared_text, vec)])

    hits_a = await qdrant.search(user_a, vec, limit=10)
    hits_b = await qdrant.search(user_b, vec, limit=10)

    assert hits_a, "user A must retrieve its own chunk"
    assert hits_b, "user B must retrieve its own chunk"
    # I1: zero cross-user leakage despite identical vectors.
    assert {h.source_id for h in hits_a} == {SourceId("src-a")}
    assert {h.source_id for h in hits_b} == {SourceId("src-b")}


async def test_search_returns_span_text_and_score(qdrant, embeddings):
    user = UserId(f"u-q-{uuid.uuid4().hex[:10]}")
    text = "供应商交期从两周缩短到五天"
    vec = await embeddings.aembed_query(text)
    await qdrant.upsert_chunks(user, [_chunk("src-x", text, vec)])

    (hit,) = await qdrant.search(user, vec, limit=5)
    assert hit.source_id == SourceId("src-x")
    assert (hit.block_start, hit.block_end) == (0, 0)
    assert hit.text == text
    assert hit.score > 0


async def test_existing_collection_with_wrong_dimension_fails_at_startup():
    qdrant_url = os.environ.get(
        "PNEUMA_KNOWLEDGE_QDRANT_URL", "http://localhost:16333"
    )
    collection = f"pneuma_dimension_guard_{uuid.uuid4().hex}"
    first = QdrantVectorIndex(qdrant_url, 3, collection=collection)
    mismatch = QdrantVectorIndex(qdrant_url, 4, collection=collection)
    cleanup = AsyncQdrantClient(url=qdrant_url)
    try:
        await first.ensure_collection()
        with pytest.raises(RuntimeError, match=r"expected 4.*has 3"):
            await mismatch.ensure_collection()
    finally:
        await first.aclose()
        await mismatch.aclose()
        await cleanup.delete_collection(collection)
        await cleanup.close()
