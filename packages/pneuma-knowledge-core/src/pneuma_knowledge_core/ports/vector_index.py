"""VectorIndex port — L2 semantic search (architecture.md §3, §6).

Single Qdrant collection with a mandatory tenant filter. The tenant filter is
injected mechanically by the adapter from user_id (invariant I1); the
business layer cannot bypass it and never constructs the filter itself. L2
coverage follows IntakePlan (semantic_indexing knob), unlike L0/L1.
"""

from __future__ import annotations

from typing import Literal, Protocol

from ..domain.ids import UserId, SourceId


class SemanticChunk(Protocol):
    source_id: SourceId
    block_start: int
    block_end: int
    # Half-open offsets into the source-global block-joined string (ingest/chunking.py):
    # the chunk's unique identity, distinguishing several sub-block chunks of one block.
    char_start: int
    char_end: int
    text: str
    embedding: list[float]
    representation: Literal["raw", "episode"]


class SemanticHit(Protocol):
    source_id: SourceId
    block_start: int
    block_end: int
    char_start: int
    char_end: int
    text: str
    score: float
    representation: Literal["raw", "episode"]


class VectorIndex(Protocol):
    async def upsert_chunks(
        self, user_id: UserId, chunks: list[SemanticChunk]
    ) -> None: ...

    async def search(
        self,
        user_id: UserId,
        embedding: list[float],
        *,
        limit: int = 20,
        representation: Literal["raw", "episode"] = "raw",
    ) -> list[SemanticHit]: ...
