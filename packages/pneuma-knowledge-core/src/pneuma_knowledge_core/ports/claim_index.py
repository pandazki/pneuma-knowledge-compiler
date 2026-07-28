"""Claim-retrieval ports — the L3 retrieval face (architecture.md §3, §7; M4).

The canonical claim projection (recall/projection.py) is indexed into two derived
retrieval faces: a lexical face (Meilisearch, a per-user `claims_<uid>` index) and a
semantic face (Qdrant, the shared chunk collection with `payload.layer="claim"`). Both
are keyed by user_id first (invariant I1) and return the same ClaimHit shape so
fast/deep recall can fuse them with RRF. A ClaimHit carries the claim's anchor + path +
its citations, so provenance (I4) survives the round trip through the index.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.ids import UserId


class ClaimHit(Protocol):
    anchor: str
    document_path: str
    section_path: list[str]
    text: str
    citations: list[dict[str, Any]]  # [{"source_id","block_start","block_end"}, ...]
    score: float


class ClaimLexicalIndex(Protocol):
    async def search_claims(
        self, user_id: UserId, query: str, *, limit: int = 40
    ) -> list[ClaimHit]: ...


class ClaimVectorIndex(Protocol):
    async def search_claims(
        self, user_id: UserId, embedding: list[float], *, limit: int = 40
    ) -> list[ClaimHit]: ...
