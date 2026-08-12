"""rag mode: L1 lexical plus independent L2 raw/episode recall with RRF (§7).

`recall(mode=rag)` runs all three rankings and fuses them with Reciprocal Rank
Fusion. Every representation addresses the same block space (invariant I4), so a hit is
keyed by `(source_id, block_start, block_end)`; a lexical hit spans a single block
`[i, i]`. Exact spans fuse and lower-ranked overlapping spans are suppressed after retrieval, so an
episode representation can improve rank without becoming evidence or consuming a duplicate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.ids import UserId, SourceId
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex

RRF_K = 60
POST_DEDUP_CANDIDATE_MULTIPLIER = 2


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
    # Internal provenance of the ranking signal. Public APIs keep the stable coarse
    # `paths` vocabulary (lexical/vector), while post-retrieval suppression needs to know
    # that an episode-only hit is derived routing text and must not displace an overlapping
    # raw/caption or lexical evidence span.
    representations: tuple[str, ...] = ()  # subset of ("lexical", "raw", "episode")


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
    """L1 + two L2 representations fused by ordinary RRF (§7). No source with L1 coverage is
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
    # Over-fetch each path before post-retrieval suppression. Semantic overlaps and the
    # independent raw/episode representations can legitimately surface the same region;
    # asking each backend for only the final cap would let duplicates shrink recall rather
    # than backfill from the tail (Nemori's hybrid path uses the same 2× candidate shape).
    candidate_limit = limit * POST_DEDUP_CANDIDATE_MULTIPLIER
    lexical_hits = await lexical.search(user_id, query, limit=candidate_limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    raw_hits = await vectors.search(
        user_id, query_embedding, limit=candidate_limit, representation="raw"
    )
    episode_hits = await vectors.search(
        user_id, query_embedding, limit=candidate_limit, representation="episode"
    )

    # key = (source_id, block_start, block_end); lexical block -> [i, i].
    info: dict[tuple, dict] = {}
    lexical_ranking: list[str] = []
    for hit in lexical_hits:
        key = (str(hit.source_id), hit.block_index, hit.block_index)
        lexical_ranking.append(repr(key))
        entry = info.setdefault(key, {"text": hit.text, "paths": []})
        if "lexical" not in entry["paths"]:
            entry["paths"].append("lexical")
        entry.setdefault("representations", []).append("lexical")

    vector_rankings: list[list[str]] = []
    for representation, vector_hits in (("raw", raw_hits), ("episode", episode_hits)):
        ranking: list[str] = []
        for hit in vector_hits:
            key = (str(hit.source_id), hit.block_start, hit.block_end)
            key_repr = repr(key)
            # One representation can never contribute twice to the same source span. This
            # is the post-retrieval dedup boundary: raw and episode rank independently, but
            # repeated/sub-chunked points cannot consume several fused candidates.
            if key_repr in ranking:
                continue
            ranking.append(key_repr)
            entry = info.setdefault(key, {"text": hit.text, "paths": []})
            entry.setdefault("char_start", getattr(hit, "char_start", None))
            entry.setdefault("char_end", getattr(hit, "char_end", None))
            if "vector" not in entry["paths"]:
                entry["paths"].append("vector")
            representations = entry.setdefault("representations", [])
            if representation not in representations:
                representations.append(representation)
        vector_rankings.append(ranking)

    rankings = [lexical_ranking, *vector_rankings]
    fused_keys = rrf_fuse(rankings)
    scores = _rrf_scores(rankings, RRF_K)

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
                representations=tuple(entry.get("representations", ())),
            )
        )
    # Dedup the two faces of the same region AFTER fusion. Rank-order suppression is
    # intentionally not an interval union: smart-overlap episodes can form A↔B↔C chains,
    # and unioning the chain would turn several distinct memories into one giant passage.
    raw.sort(key=lambda h: (-h.score, str(h.source_id), h.block_start))
    return _suppress_overlapping(raw)[:limit]


def _suppress_overlapping(hits: list[RecallHit]) -> list[RecallHit]:
    """Greedy rank-order overlap suppression without score or interval inflation.

    Exact spans have already fused through their common RRF key. For merely overlapping
    spans, keep the stronger candidate's source text/span/score, copy only the path markers
    from suppressed duplicates, and continue. One exception is structural rather than
    score-based: episode-only hits are derived routing text, so an overlapping raw/caption
    or lexical span always owns the citable result. Between two direct representations, a
    raw semantic chunk owns an overlapping lexical-only block: both are verbatim, but the
    raw span is the natural unit selected at ingest. The episode can raise the winning
    result's score but cannot replace its exact evidence. Two disjoint candidates survive even
    when a broad episode overlaps both, so overlap cannot create a transitive mega-window.
    """

    kept: list[RecallHit] = []
    for candidate in hits:
        duplicate_index = next(
            (
                index
                for index, prior in enumerate(kept)
                if prior.source_id == candidate.source_id
                and prior.block_start <= candidate.block_end
                and candidate.block_start <= prior.block_end
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(candidate)
            continue
        prior = kept[duplicate_index]
        prior_priority = _evidence_priority(prior)
        candidate_priority = _evidence_priority(candidate)
        winner = candidate if candidate_priority > prior_priority else prior
        paths = tuple(dict.fromkeys((*prior.paths, *candidate.paths)))
        representations = tuple(
            dict.fromkeys((*prior.representations, *candidate.representations))
        )
        kept[duplicate_index] = RecallHit(
            source_id=winner.source_id,
            block_start=winner.block_start,
            block_end=winner.block_end,
            text=winner.text,
            paths=paths,
            score=max(prior.score, candidate.score),
            char_start=winner.char_start,
            char_end=winner.char_end,
            representations=representations,
        )
    return kept


def _evidence_priority(hit: RecallHit) -> int:
    """Structural ownership of an overlapping citable span.

    Raw semantic chunks and lexical hits are both verbatim evidence. Raw wins between them
    because it already carries the source's ingest-time natural-unit boundary; lexical wins
    over episode-only routing prose. Empty legacy metadata remains direct lexical-shaped
    evidence for compatibility.
    """

    if "raw" in hit.representations:
        return 2
    if not hit.representations or "lexical" in hit.representations:
        return 1
    return 0
