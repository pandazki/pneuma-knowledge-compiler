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
    episode_summary_text: str


class SemanticHit(Protocol):
    source_id: SourceId
    block_start: int
    block_end: int
    char_start: int
    char_end: int
    text: str
    score: float
    representation: Literal["raw", "episode"]
    episode_summary_text: str


class VectorIndex(Protocol):
    async def upsert_chunks(
        self, user_id: UserId, chunks: list[SemanticChunk], *, archived: bool = False
    ) -> None:
        """Upsert one source's chunks, carrying its archive mark.

        `archived` is the L0 mark (`RawSource.archived_at is not None`), passed in rather
        than looked up — this port knows no store. An archived source's chunks are indexed
        like any other and are reachable by an `include_archived` search, so unarchiving is a
        payload flip and never a re-embed.
        """
        ...

    async def search(
        self,
        user_id: UserId,
        embedding: list[float],
        *,
        limit: int = 20,
        representation: Literal["raw", "episode"] = "raw",
        include_archived: bool = False,
    ) -> list[SemanticHit]:
        """Semantic hits, ARCHIVE EXCLUDED unless the call states the exception.

        Excluded at the index and not after it (docs/design/archive.md §3): archived chunks
        admitted into the candidate list would spend the caps before the answer ever saw a
        live one. A point written before the flag existed reads as live.
        """
        ...
