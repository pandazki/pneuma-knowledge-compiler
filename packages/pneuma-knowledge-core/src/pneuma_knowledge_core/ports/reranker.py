"""Reranker port: score candidate texts against one query.

A dedicated cross-encoder reranker (Cohere rerank, bge-reranker, …) reads the query and
each candidate text together and returns a real relevance score per candidate — exactly
the judgement rank fusion (RRF) cannot make, because RRF counts list positions and never
sees magnitudes. The fast lane keeps RRF as its cheap candidate generator and hands the
pooled candidates to this port to decide which ones actually matter.

Unlike the storage ports this one carries no ``user_id``: a reranker holds no state and
reads nothing — it is pure computation over the texts the caller already retrieved under
its own tenant, the same tenant-free shape as ``Embeddings`` and ``BaseChatModel`` (I1
guards read paths into stored state; there is none here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class RerankResult:
    """One scored candidate: the index into the submitted document list, and the
    reranker's relevance score (higher = more relevant; scale is model-specific, but
    ordering and relative gaps are meaningful within one call)."""

    index: int
    score: float


class Reranker(Protocol):
    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]:
        """Score `documents` against `query`; return up to `top_n` results, best first.

        Implementations raise on transport/provider failure — the caller decides what
        degradation means (the fast lane falls back to its fused order)."""
        ...
