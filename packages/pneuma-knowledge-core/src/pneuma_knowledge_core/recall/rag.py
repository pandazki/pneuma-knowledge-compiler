"""rag mode: L1 lexical plus independent L2 raw/episode recall with RRF (§7).

`recall(mode=rag)` runs all three rankings and fuses them with Reciprocal Rank
Fusion. Every representation addresses the same block space (invariant I4), so a hit is
keyed by `(source_id, block_start, block_end)`; a lexical hit spans a single block
`[i, i]`. Exact spans fuse and lower-ranked overlapping spans are suppressed after retrieval, so an
episode representation can improve rank without becoming evidence or consuming a duplicate.

Like every other lane, this one reports WHERE ITS SECONDS WENT. `rag_recall` takes an
optional `StageRecorder` and measures a fixed vocabulary against it (`RAG_STAGE_ORDER`):
the query embedding, the retrieval itself with one child per face, the fusion, and the
post-fusion overlap merge. The two faces are SEQUENTIAL awaits here — no gather — so
`retrieve.lexical` and `retrieve.vector` sum to their parent rather than exceeding it, and
a diagram draws them as a chain. With no recorder passed nothing is emitted and the
function is byte-for-byte what it was before the vocabulary existed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..domain.ids import UserId, SourceId
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from .archive_filter import archive_view, index_scope, scope_windows
from .stage_timing import RETRIEVE, StageRecorder, child_name, window_entries

RRF_K = 60
POST_DEDUP_CANDIDATE_MULTIPLIER = 2

#: The rag lane's stages, in the order the code path runs them. `embed` is the query
#: embedding (skipped when a fan-out caller already holds the vector); `retrieve` is the
#: backend round trips; `fuse` is the RRF pass plus the hits it builds; `expand` is the
#: post-fusion overlap merge and the cap — the step that decides which of two overlapping
#: spans owns the citable region, which would otherwise be an unexplained gap between the
#: stages and `total`. There is no model in this lane, so there is no answer stage.
RAG_STAGE_ORDER: tuple[str, ...] = ("embed", "retrieve", "fuse", "expand", "total")

#: The two retrieval faces, in the order they are awaited. Unlike the fast lane's gather
#: these run SEQUENTIALLY, so they sum to their parent instead of exceeding it. `vector` is
#: measured once around both representation searches (raw, then episode): they are one face
#: of the same index, and a reader looking at a rag breakdown wants L1 against L2.
RAG_RETRIEVE_CHILDREN: tuple[str, ...] = ("lexical", "vector")

#: Spelled once so the measure sites and the vocabulary above cannot drift apart.
EMBED = "embed"
FUSE = "fuse"
EXPAND = "expand"
TOTAL = "total"


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
class EpisodeSummarySignal:
    """Derived episode content with the episode's own immutable L0 address."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str


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
    # Derived episode representations that contributed retrieval signal to this evidence
    # span. Fast recall may surface them as explicitly labelled, source-addressed summaries.
    episode_summaries: tuple[EpisodeSummarySignal, ...] = ()
    # Whether this hit's SOURCE is in the archive. False for every hit a default retrieval
    # produces — the archive is excluded at the index and again at assembly — and stamped
    # only on the `include_archived` path (`recall/archive_filter.py`), where it becomes a
    # marker on the rendered provenance header. Never inferred here: a hit knows its source,
    # not the archive.
    archived: bool = False


async def rag_recall(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex,
    vectors: VectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = 10,
    query_embedding: list[float] | None = None,
    stages: StageRecorder | None = None,
    include_archived: bool = False,
    content: Any | None = None,
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
    versioning mechanism.

    `stages` is a `StageRecorder` over `RAG_STAGE_ORDER` for a caller that wants the
    breakdown (and, with an `on_event` sink, the stages as they happen). None = one is made
    here and never read, so nothing is emitted and nothing changes.

    `include_archived` is off by default and rides straight through to both indexes, which is
    where the exclusion has to happen FIRST: archived blocks and chunks admitted into the
    candidate list would spend the caps before the answer ever saw a live one (archive.md
    §3). The keyword is passed only when it is on, because off IS the port's own default — so
    a call that does not ask for the archive is byte-for-byte the call this lane always made.

    `content` is the L0 store, and it is what gives this lane the SECOND half every other
    lane has: the assembly-time filter (`recall/archive_filter.py`). Trusting the two index
    filters alone made the property rest on a flag flip in two backends — a `set_payload`
    that failed, an index built before the field existed, a fake that accepts the keyword and
    ignores it — and any of those leaks the archive into a default answer. With `content`
    passed, an archived hit is dropped after fusion when the archive was not asked for, and
    LABELLED (`RecallHit.archived`) when it was; without it the lane is exactly what it was,
    so no existing caller changes. What the drop cost is reported on the `expand` stage as
    `archive_hidden`, the same key every other lane states this omission under."""
    timer = stages if stages is not None else StageRecorder(
        RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN
    )
    with timer.measure(TOTAL):
        return await _rag_recall(
            user_id,
            query,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            limit=limit,
            query_embedding=query_embedding,
            timer=timer,
            include_archived=include_archived,
            content=content,
        )


async def _rag_recall(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex,
    vectors: VectorIndex,
    embeddings,
    limit: int,
    query_embedding: list[float] | None,
    timer: StageRecorder,
    include_archived: bool = False,
    content: Any | None = None,
) -> list[RecallHit]:
    """`rag_recall`'s body, with `total` already wrapping it. Split only so the wrapper is
    one statement: an early return inside the outer `measure` would otherwise be a place
    where the total could stop being the total."""
    # Over-fetch each path before post-retrieval suppression. Semantic overlaps and the
    # independent raw/episode representations can legitimately surface the same region;
    # asking each backend for only the final cap would let duplicates shrink recall rather
    # than backfill from the tail (Nemori's hybrid path uses the same 2× candidate shape).
    candidate_limit = limit * POST_DEDUP_CANDIDATE_MULTIPLIER
    scope = index_scope(include_archived)
    # The archive, read once for this call — before the round trips, so the filter below is a
    # set membership test and not a second await inside the assembly step. With no `content`
    # the view is empty and every hit stands, which is what every pre-archive caller gets.
    # NO `documents_archived` HERE, and none is missing: that flag exists to switch the
    # document pin on (`archive_filter._pin`), and this lane holds no document set to pin to
    # — it returns hits, not an answer over pages. The view's only use here is the
    # archived-source drop, which is already a no-op when no source is archived.
    view = await archive_view(user_id, content)
    # The embedding is taken FIRST — before the lexical round trip it used to sit behind —
    # so the order the stages are measured in is the order the vocabulary emits them in.
    # The two are independent, so what comes back is unchanged either way; what changes is
    # that a reader watching the lane live and a reader reading the finished breakdown see
    # the same sequence.
    if query_embedding is None:
        with timer.measure(EMBED):
            query_embedding = await embeddings.aembed_query(query)
            timer.preview(EMBED, {"dimensions": len(query_embedding)})
    with timer.measure(RETRIEVE):
        # SEQUENTIAL, not a gather: one face after the other, so the children sum to the
        # parent. Left alone deliberately — measuring a lane must not reshape it.
        with timer.measure(child_name("lexical")):
            lexical_hits = await lexical.search(
                user_id, query, limit=candidate_limit, **scope
            )
            timer.preview(
                child_name("lexical"),
                {"candidates": candidate_limit, **_hit_preview(lexical_hits)},
            )
        with timer.measure(child_name("vector")):
            raw_hits = await vectors.search(
                user_id,
                query_embedding,
                limit=candidate_limit,
                representation="raw",
                **scope,
            )
            episode_hits = await vectors.search(
                user_id,
                query_embedding,
                limit=candidate_limit,
                representation="episode",
                **scope,
            )
            timer.preview(
                child_name("vector"),
                {
                    "raw": len(raw_hits),
                    "episode": len(episode_hits),
                    **_hit_preview([*raw_hits, *episode_hits]),
                },
            )

    with timer.measure(FUSE):
        raw = _fuse(lexical_hits, raw_hits, episode_hits)
        timer.preview(
            FUSE,
            {
                "rankings": len(lexical_hits) + len(raw_hits) + len(episode_hits),
                **_hit_preview(raw),
            },
        )
    with timer.measure(EXPAND):
        merged = _suppress_overlapping(raw)
        # THE ASSEMBLY-TIME HALF, before the cap rather than after it: a dropped archived hit
        # backfills from the tail instead of leaving the caller short of `limit`. Off drops
        # and counts; on stamps `RecallHit.archived`, which is how a hit the caller asked for
        # reaches the wire saying what it is.
        merged, hidden = scope_windows(
            merged, view, include_archived=include_archived
        )
        kept = merged[:limit]
        timer.preview(
            EXPAND,
            {
                "fused": len(raw),
                **({"archive_hidden": hidden} if hidden else {}),
                **_hit_preview(kept),
            },
        )
        return kept


def _hit_preview(hits) -> dict:
    """`hits` plus the first few of them: what each one SAYS, then its source and block span.

    The address is the one addressing scheme (I4) and it stays — a hit is a source and a span,
    which is what a citation would carry — but it is no longer the whole entry. A list of
    spans names what came back and describes none of it; the head of the passage does both.
    Bounded by `bound_preview` like every other preview.
    """
    return {"hits": len(hits), "top": window_entries(hits)}


def _fuse(lexical_hits, raw_hits, episode_hits) -> list[RecallHit]:
    """RRF over the three rankings, and the hits it produces, in fused order."""
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
            episode_summary_text = str(
                getattr(hit, "episode_summary_text", "") or ""
            ).strip()
            if representation == "episode" and episode_summary_text:
                signal = EpisodeSummarySignal(
                    source_id=SourceId(str(hit.source_id)),
                    block_start=int(hit.block_start),
                    block_end=int(hit.block_end),
                    text=episode_summary_text,
                )
                episode_summaries = entry.setdefault("episode_summaries", [])
                if signal not in episode_summaries:
                    episode_summaries.append(signal)
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
                episode_summaries=tuple(entry.get("episode_summaries", ())),
            )
        )
    # Dedup the two faces of the same region AFTER fusion. Rank-order suppression is
    # intentionally not an interval union: smart-overlap episodes can form A↔B↔C chains,
    # and unioning the chain would turn several distinct memories into one giant passage.
    raw.sort(key=lambda h: (-h.score, str(h.source_id), h.block_start))
    return raw


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
        episode_summaries = tuple(
            dict.fromkeys((*prior.episode_summaries, *candidate.episode_summaries))
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
            episode_summaries=episode_summaries,
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
