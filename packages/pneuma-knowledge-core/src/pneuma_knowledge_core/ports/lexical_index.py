"""LexicalIndex port — L1 lexical full-text search (architecture.md §3, §6).

Index-per-user (invariant I1). L1 coverage is unconditional (I3): every source is
indexed on intake regardless of IntakePlan. CJK tokenization quality is an M1
acceptance item (ADR-002).
"""

from __future__ import annotations

from typing import Protocol

from ..domain.ids import UserId, SourceId
from ..domain.source import NormalizedBlock


class LexicalHit(Protocol):
    source_id: SourceId
    block_index: int
    text: str
    score: float


class LexicalIndex(Protocol):
    async def index_blocks(
        self,
        user_id: UserId,
        source_id: SourceId,
        blocks: list[NormalizedBlock],
        *,
        archived: bool = False,
    ) -> None:
        """Index one source's blocks, carrying its archive mark.

        Indexing itself stays unconditional (I3): an archived source is indexed exactly like
        a live one and simply carries the flag, so it is reachable by an `include_archived`
        search and needs no re-index to come back. `archived` is the L0 mark
        (`RawSource.archived_at is not None`), passed in rather than looked up — this port
        knows no store.
        """
        ...

    async def search(
        self,
        user_id: UserId,
        query: str,
        *,
        limit: int = 20,
        include_archived: bool = False,
    ) -> list[LexicalHit]:
        """Lexical hits, ARCHIVE EXCLUDED unless the call states the exception.

        Excluded at the index and not after it (docs/design/archive.md §3): archived blocks
        admitted into the candidate list would spend the caps before the answer ever saw a
        live one. A block indexed before the flag existed reads as live.
        """
        ...
