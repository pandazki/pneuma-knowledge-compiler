"""rag mode: dual-path (L2 semantic + L1 lexical) recall with RRF fusion (§7).

`recall(mode=rag)` runs both retrieval paths and fuses them with Reciprocal Rank
Fusion. Both paths address into the same block space (invariant I4), so a hit is
keyed by `(source_id, block_start, block_end)`; a lexical hit spans a single block
`[i, i]`. When both paths surface the exact same span it fuses into one hit carrying
both source markers; otherwise the union is returned in fused order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.ids import UserId, SourceId
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex

RRF_K = 60


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion of several ranked id lists.

    Standard RRF: each list contributes 1/(k + rank) per id (rank 0-based here),
    scores summed across lists. Returns ids sorted by fused score descending;
    ties broken by first-appearance order for determinism.
    """
    scores = _rrf_scores(rankings, k)
    first_seen: dict[str, int] = {}
    order = 0
    for ranking in rankings:
        for doc_id in ranking:
            if doc_id not in first_seen:
                first_seen[doc_id] = order
                order += 1
    return sorted(scores, key=lambda d: (-scores[d], first_seen[d]))


def _rrf_scores(rankings: Sequence[Sequence[str]], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass(frozen=True)
class RecallHit:
    """One fused recall result, addressed by an inclusive block interval (I4).

    The block interval is the fusion key (a lexical block hit and a semantic chunk fuse
    when they cover the same span) and the UI drill-down key. ``char_start`` / ``char_end``
    carry the semantic chunk's exact char span for precise provenance when present; they
    are ``None`` for a lexical-only hit (a block has no sub-block char identity)."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    paths: tuple[str, ...]  # subset of ("lexical", "vector"), in path order
    score: float  # fused RRF score
    char_start: int | None = None
    char_end: int | None = None


async def rag_recall(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex,
    vectors: VectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = 10,
    query_embedding: list[float] | None = None,
) -> list[RecallHit]:
    """L1 + L2 dual-path recall fused by RRF (§7). No source with L1 coverage is
    ever invisible: the lexical path covers the retrieval surface even when a
    source has no L2 chunks.

    `query_embedding` lets a caller that already holds the vector supply it instead of
    paying another round trip. It defaults to None = embed here, so every existing caller
    is behaviorally untouched. The lever exists for fan-out callers (suggestion evaluates N
    transcript turns per round and batches all N through one `aembed_documents`).

    Snapshot-scoped recall needs nothing here: a snapshot is a frozen TENANT (see
    service/kb_snapshots.py), so answering over one is this same function called with that
    tenant's `user_id` — the per-user isolation both indexes already enforce is the
    versioning mechanism."""
    lexical_hits = await lexical.search(user_id, query, limit=limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    semantic_hits = await vectors.search(user_id, query_embedding, limit=limit)

    # key = (source_id, block_start, block_end); lexical block -> [i, i].
    info: dict[tuple, dict] = {}
    lexical_ranking: list[str] = []
    for hit in lexical_hits:
        key = (str(hit.source_id), hit.block_index, hit.block_index)
        lexical_ranking.append(repr(key))
        entry = info.setdefault(key, {"text": hit.text, "paths": []})
        if "lexical" not in entry["paths"]:
            entry["paths"].append("lexical")

    semantic_ranking: list[str] = []
    for hit in semantic_hits:
        key = (str(hit.source_id), hit.block_start, hit.block_end)
        semantic_ranking.append(repr(key))
        entry = info.setdefault(key, {"text": hit.text, "paths": []})
        # Carry the exact char span for provenance; the first semantic hit on a block
        # interval wins the span (same rule as its text).
        entry.setdefault("char_start", getattr(hit, "char_start", None))
        entry.setdefault("char_end", getattr(hit, "char_end", None))
        if "vector" not in entry["paths"]:
            entry["paths"].append("vector")

    fused_keys = rrf_fuse([lexical_ranking, semantic_ranking])
    scores = _rrf_scores([lexical_ranking, semantic_ranking], RRF_K)

    by_repr = {repr(k): k for k in info}
    raw: list[RecallHit] = []
    for key_repr in fused_keys:
        key = by_repr[key_repr]
        entry = info[key]
        source_id, block_start, block_end = key
        raw.append(
            RecallHit(
                source_id=SourceId(source_id),
                block_start=block_start,
                block_end=block_end,
                text=entry["text"],
                paths=tuple(entry["paths"]),
                score=scores[key_repr],
                char_start=entry.get("char_start"),
                char_end=entry.get("char_end"),
            )
        )
    # Dedup the two faces of the same region: a lexical [6,6] and the vector chunk [6,7]
    # that contains it are one candidate, not two hits. Coalesce block-overlapping hits
    # within a source, then take the strongest `limit`.
    merged = _coalesce_overlapping(raw)
    merged.sort(key=lambda h: (-h.score, str(h.source_id), h.block_start))
    return merged[:limit]


def _coalesce_overlapping(hits: list[RecallHit]) -> list[RecallHit]:
    """Merge hits whose block spans OVERLAP within a source into one hit.

    Dedups the lexical vs vector faces of the same region. Overlap is strict (shared
    blocks), never mere adjacency, so two distinct back-to-back candidates stay separate.
    The widest member keeps its text/char-span (it contains the narrower); `paths` union;
    scores SUM so a region surfaced by both paths outranks a single-path hit (and reads as
    a stronger match than the RRF-rank cap of one list)."""
    by_source: dict[str, list[RecallHit]] = {}
    for h in hits:
        by_source.setdefault(str(h.source_id), []).append(h)

    out: list[RecallHit] = []
    for sid, group in by_source.items():
        group.sort(key=lambda h: (h.block_start, h.block_end))
        cur: dict | None = None
        for h in group:
            if cur is not None and h.block_start <= cur["end"]:  # strict overlap (shared block)
                cur["end"] = max(cur["end"], h.block_end)
                cur["score"] += h.score
                for p in h.paths:
                    if p not in cur["paths"]:
                        cur["paths"].append(p)
                if (h.block_end - h.block_start) > cur["width"]:
                    cur.update(
                        text=h.text, char_start=h.char_start,
                        char_end=h.char_end, width=h.block_end - h.block_start,
                    )
                continue
            if cur is not None:
                out.append(_hit_from(sid, cur))
            cur = {
                "start": h.block_start, "end": h.block_end, "text": h.text,
                "paths": list(h.paths), "score": h.score,
                "char_start": h.char_start, "char_end": h.char_end,
                "width": h.block_end - h.block_start,
            }
        if cur is not None:
            out.append(_hit_from(sid, cur))
    return out


def _hit_from(source_id: str, c: dict) -> RecallHit:
    return RecallHit(
        source_id=SourceId(source_id),
        block_start=c["start"],
        block_end=c["end"],
        text=c["text"],
        paths=tuple(c["paths"]),
        score=c["score"],
        char_start=c["char_start"],
        char_end=c["char_end"],
    )
