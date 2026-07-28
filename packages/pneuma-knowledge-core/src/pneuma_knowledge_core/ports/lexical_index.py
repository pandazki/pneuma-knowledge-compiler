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
    ) -> None: ...

    async def search(
        self, user_id: UserId, query: str, *, limit: int = 20
    ) -> list[LexicalHit]: ...
