"""fast mode — canonical-annotation-dense recall (architecture.md §7; milestone M4).

Three seals, all mechanical (§0 discipline 1), not prose pleas:

1. **Fixed answer contract.** The SystemMessage is `selector_contract()` verbatim — a
   byte-stable string (I5). It is a top-down account (identity → the three evidence forms
   → world-facts about the evidence → answer shape), not a rule list; it never carries
   a timestamp, the question, or claim content, so the provider cache is earned by
   assembly order.
2. **Annotation cap + dedup.** Claims come from a dual-path retrieval (Meili claims +
   Qdrant claim layer) fused by RRF, deduped by (document_path, anchor), then capped to
   `cap` (default 40) before rendering.
3. **Everything volatile in the Human turn, question LAST.** Evidence sections render
   first (glance → claim notes → derived episode summaries → raw excerpts → any fully-read
   documents), then as_of +
   question close the message — the live ask sits in the attention-hot tail instead of
   drowning above a 40-claim wall.

On top of retrieval the lane carries the knowledge base GLANCE (canonical_glance.py) — the
library's layout, present for every question — plus one concurrent selection pass that may
ask for a handful of documents to be read in full. Both are additive: with no canonical
documents supplied the lane is byte-for-byte the retrieval-only one it has always been, and
a failed selection pass degrades to exactly that. See `fast_recall`.

`token_usage` passes through the provider's cache_read / cache_creation fields
(defaulting to 0 when absent — scripted/keyless models report 0).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.content import create_image_block
from pydantic import BaseModel, Field

from ..canonical_glance import render_canonical_glance
from ..compile.documents import render_document
from ..domain.canonical import CanonicalDocument, Citation
from ..domain.ids import AnchorId, UserId, SourceId
from ..domain.source import BlockImage
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.media_store import MediaStore
from ..ports.reranker import Reranker
from ..ports.vector_index import VectorIndex
from ..prompts import prompt
from .citation_alias import SessionAliaser, alias_sources
from .scope import SnapshotScope, scope_declaration
from .spine import (
    CITE_SOURCE_LEVEL,
    CLOSE_ANSWER_HONESTLY,
    DEFAULT_ANSWER_STYLE,
    spine,
    style_clause,
)
from .assembly import (
    Passage,
    expand_and_merge,
    order_lost_in_middle,
    render_passages,
)
from .projection import PROJECTION_V1, ProjectedClaim, project_document_claims
from .rag import EpisodeSummarySignal, RecallHit, _rrf_scores, rag_recall, rrf_fuse

# Product defaults separate cheap retrieval breadth from expensive answer evidence. The
# values are intentionally corpus-agnostic: retrieve enough tail for lexical/semantic
# disagreement and post-dedup backfill, then keep the final wall small enough for an
# interactive personal or team knowledge base. A deployment may tune each boundary without
# changing the mechanism.
DEFAULT_CLAIM_CANDIDATE_CAP = 80
DEFAULT_CLAIM_CAP = 40
DEFAULT_WINDOW_CANDIDATE_CAP = 60
DEFAULT_EPISODE_SUMMARY_CAP = 24
DEFAULT_WINDOW_CAP = 6
DEFAULT_IMAGE_CAP = 8

#: How many hit documents `timeline_expand` may expand into sibling timelines. Together with
#: the per-document sibling cap this bounds the section's total size mechanically:
#: ≤ timeline_expand × DEFAULT_TIMELINE_DOC_CAP claims (~55 tokens each), never "whatever the
#: retrieval happened to touch".
DEFAULT_TIMELINE_DOC_CAP = 4

#: How many claim notes may hang under ONE window when `annotate_windows` is on. Small on
#: purpose: a footnote stack taller than the excerpt it annotates stops reading as a footnote
#: and becomes a second claim section wearing an indent.
DEFAULT_WINDOW_NOTE_CAP = 3

#: How many documents the glance pass may ask to be read in full. Small on purpose: the pass
#: exists for the question whose answer IS one document, not as a second retrieval channel.
DEFAULT_GLANCE_PICK_CAP = 3

#: Wall-clock ceiling on the glance pass. It runs concurrently with retrieval, so the whole
#: lane costs max(retrieval, this) — but a hung provider must not hold the answer hostage, and
#: the answer is well-formed without the pass (that is the whole point of it being additive).
DEFAULT_GLANCE_TIMEOUT_SECONDS = 8.0


def invoke_config(
    run_name: str,
    callbacks: list | None,
    trace_metadata: dict | None,
) -> dict:
    """Assemble the langchain `config` passed to every `model.ainvoke` in core.

    core stays middleware-free (architecture.md §2): it depends only on langchain's
    callback abstraction. A langfuse handler (or any BaseCallbackHandler) is injected by
    the service via `callbacks`; `trace_metadata` rides `config["metadata"]` so a trace
    can be filtered by operation / user_id / snapshot. Both default to no-ops, so
    the keyless path (callbacks=None) is byte-for-byte the pre-tracing behavior.
    """
    return {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": run_name,
    }


def selector_contract(answer_style: str = DEFAULT_ANSWER_STYLE) -> str:
    """The fast lane's System contract: head + shared spine + answer-style clause.

    I5: byte-stable per prompt overlay and per `answer_style` — a deployment picks one
    style and every ask shares those bytes. No timestamp, no question, no claim/window
    content — posture only. Assembled per call rather than at import so a
    startup-registered overlay reaches it."""
    return (
        prompt("recall.fast.contract_head")
        + spine(CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY)
        + style_clause(answer_style)
    )


@dataclass(frozen=True)
class RetrievedClaim:
    """A claim surfaced by the L3 retrieval face, carrying provenance (I4)."""

    anchor: AnchorId
    document_path: str
    section_path: tuple[str, ...]
    text: str
    citations: tuple[Citation, ...]
    paths: tuple[str, ...] = field(default_factory=tuple)  # ("lexical","vector") subset
    score: float = 0.0


@dataclass(frozen=True)
class FastAnswer:
    answer: str
    used_claims: tuple[RetrievedClaim, ...]
    token_usage: dict[str, int]
    # {handle: real_source_id} for the query-local `sNN` citation handles the answer uses —
    # the business/UI side reverse-binds each `[cite: sNN]` to its real source.
    citation_handles: dict[str, str] = field(default_factory=dict)
    # L1/L2 body windows fused into the answer alongside claims (uncompiled content).
    # Merged Passages when a ContentStore is wired (expand→merge assembly); raw RecallHits
    # in the langchain-only fallback. Both expose source_id/block_start/block_end/text.
    used_windows: tuple[RecallHit | Passage, ...] = field(default_factory=tuple)
    # The glance's size in the prompt, 0 when no canonical documents were supplied — the
    # in-presence signal a caller (or the evaluation) checks without re-rendering.
    glance_chars: int = 0
    # Paths the glance pass asked to be read in full and that were actually expanded.
    expanded_documents: tuple[str, ...] = field(default_factory=tuple)
    # Why the glance pass contributed nothing, when it failed rather than simply selecting
    # nothing: "timeout", "error", or None. Telemetry, never an error surfaced to the owner.
    glance_degraded: str | None = None
    # The annotation join's yield, both 0 whenever `annotate_windows` is off: how many claims
    # were MOVED under a window (so `used_claims` is short by exactly this many), and how many
    # windows ended up carrying at least one note. The measurable of the experiment.
    annotated_claims: int = 0
    annotated_windows: int = 0
    # The timeline expansion's yield, both empty/0 whenever `timeline_expand` is off: which
    # hit documents were expanded into sibling timelines, and how many sibling claims the
    # timeline section carries in total. The measurable of that experiment.
    timeline_documents: tuple[str, ...] = field(default_factory=tuple)
    timeline_claims: int = 0
    # The planning pass's yield, empty whenever `plan_queries_cap` is 0: the extra retrieval
    # queries the model derived (the question itself is always searched and never listed).
    planned_queries: tuple[str, ...] = field(default_factory=tuple)
    # Why the planning / rerank passes contributed nothing, when they failed rather than
    # simply choosing nothing: "timeout", "error", or None. Telemetry, like glance_degraded.
    plan_degraded: str | None = None
    rerank_degraded: str | None = None
    # Images aligned to the selected raw windows and actually supplied to the answer call.
    # Bytes never leave the model boundary; this count is safe response/trace telemetry.
    image_count: int = 0
    image_mode: str = "caption"
    # Candidate-vs-evidence telemetry makes the two budgets observable without exposing any
    # generated navigation text or source content.
    claim_candidates: int = 0
    window_candidates: int = 0
    used_episode_summaries: tuple["EpisodeSummary", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EpisodeSummary:
    """One explicitly derived, source-addressed episode description shown to the answer.

    `text` is model-generated compression, never verbatim source. The remaining fields are
    mechanical metadata from L0 plus the exact span that the episode representation indexes.
    """

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    score: float
    source_title: str = ""
    source_occurred_on: str = ""
    section_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecallImage:
    """One immutable image aligned to a recalled source block."""

    source_id: SourceId
    block_index: int
    image: BlockImage
    data: bytes | None = None


def zero_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
    }


def extract_usage(response: BaseMessage) -> dict[str, int]:
    """Pull usage + provider cache fields off a chat response (cache defaults 0)."""
    meta: Mapping = getattr(response, "usage_metadata", None) or {}
    details: Mapping = meta.get("input_token_details") or {}
    return {
        "input_tokens": int(meta.get("input_tokens", 0) or 0),
        "output_tokens": int(meta.get("output_tokens", 0) or 0),
        "total_tokens": int(meta.get("total_tokens", 0) or 0),
        "cache_read": int(details.get("cache_read", 0) or 0),
        "cache_creation": int(details.get("cache_creation", 0) or 0),
    }


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in zero_usage()}


def _claim_from_hit(hit, paths: list[str], score: float) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=AnchorId(hit.anchor),
        document_path=hit.document_path,
        section_path=tuple(hit.section_path or ()),
        text=hit.text,
        citations=tuple(
            Citation(
                source_id=SourceId(str(c["source_id"])),
                block_start=int(c["block_start"]),
                block_end=int(c["block_end"]),
            )
            for c in (hit.citations or [])
        ),
        paths=tuple(paths),
        score=score,
    )


def _dedup_by_containment(claims: list[RetrievedClaim]) -> list[RetrievedClaim]:
    """Drop claims whose text is equal to, or contained in, another claim's text —
    keeping the more complete one at the better (earlier) rank of the pair.

    Anchor-level dedup cannot see these: the same fact re-filed by a later compile (a
    compensation round, a second document) carries a different anchor but adds nothing
    the longer statement doesn't already say, and every duplicate burns one slot of the
    claim budget. Containment is judged on stripped text; the kept claim keeps its own
    provenance (equal texts state the same fact, and the surviving statement's citation
    is a valid trail for it)."""
    kept: list[RetrievedClaim] = []
    kept_texts: list[str] = []
    for claim in claims:
        text = claim.text.strip()
        replaced = False
        for position, existing in enumerate(kept_texts):
            if text == existing or text in existing:
                replaced = True  # an equal or more complete statement is already ranked
                break
            if existing in text:
                kept[position] = claim  # more complete version takes the better rank
                kept_texts[position] = text
                replaced = True
                break
        if not replaced:
            kept.append(claim)
            kept_texts.append(text)
    return kept


def _fuse_claim_hits(
    labeled_hits: Sequence[tuple[str, Sequence]], limit: int
) -> list[RetrievedClaim]:
    """RRF-fuse any number of labeled hit lists into one claim ranking, deduped by
    (document_path, anchor) and then by text containment (`_dedup_by_containment`) before
    the cap — a slot freed by a duplicate refills from the fused tail. A claim keyed the
    same in several lists fuses into one hit carrying every path marker it appeared under.
    Shared by the single-query pair (lexical, vector) and the multi-query pool — one
    fusion, however many rankings."""
    info: dict[tuple, dict] = {}
    rankings: list[list[str]] = []
    for label, hits in labeled_hits:
        ranking: list[str] = []
        for hit in hits:
            key = (hit.document_path, hit.anchor)
            ranking.append(repr(key))
            entry = info.setdefault(key, {"hit": hit, "paths": []})
            if label not in entry["paths"]:
                entry["paths"].append(label)
        rankings.append(ranking)

    fused = rrf_fuse(rankings)
    scores = _rrf_scores(rankings, 60)
    by_repr = {repr(k): k for k in info}

    claims: list[RetrievedClaim] = []
    for key_repr in fused:
        entry = info[by_repr[key_repr]]
        claims.append(
            _claim_from_hit(entry["hit"], entry["paths"], scores[key_repr])
        )
    # Containment dedup runs over the FULL fused ranking before the cap, so a slot freed
    # by a duplicate refills from the tail instead of shrinking the budget.
    return _dedup_by_containment(claims)[:limit]


async def retrieve_claims(
    user_id: UserId,
    query: str,
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_CLAIM_CAP,
    query_embedding: list[float] | None = None,
) -> list[RetrievedClaim]:
    """Dual-path claim retrieval fused by RRF, deduped by (document_path, anchor).

    Mirrors rag_recall's fusion but over the claim face; a claim keyed the same in both
    paths fuses into one hit carrying both path markers.

    `query_embedding` (default None = embed here, i.e. today's behavior verbatim) lets a
    caller that already holds the vector skip the round trip — see `rag_recall`.

    Snapshot-scoped recall needs nothing here either (see `rag_recall`): the claim faces are
    per-tenant, so a frozen snapshot tenant carries its own frozen claim projection."""
    if limit <= 0:
        return []
    lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    vector_hits = await claim_vectors.search_claims(
        user_id, query_embedding, limit=limit
    )
    return _fuse_claim_hits(
        [("lexical", lexical_hits), ("vector", vector_hits)], limit
    )


async def retrieve_claims_multi(
    user_id: UserId,
    queries: Sequence[str],
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_CLAIM_CAP,
    pool_cap: int | None = None,
) -> list[RetrievedClaim]:
    """Pooled multi-query claim retrieval: every query contributes its own lexical and
    vector rankings, and ONE RRF fusion ranks the union.

    This is the retrieval half of the planned fan-out (`plan_retrieval_queries`): a
    multi-aspect question retrieves each aspect at full strength instead of blending them
    into one query. With a single query this is byte-for-byte `retrieve_claims`. Queries
    run concurrently; per-query rank order is preserved into the fusion in query order,
    so the result is deterministic for a given hit set.

    `limit` is the per-query, per-face retrieval depth; the fused result is truncated to
    `pool_cap` (default None = `limit`, today's behavior). A reranking caller passes a
    LARGER pool_cap so RRF — which is score-blind — never discards a candidate the
    reranker was going to judge: fusion order then only decides dedup, the failure
    fallback, and which tail falls off the hard cap."""

    if limit <= 0 or (pool_cap is not None and pool_cap <= 0):
        return []

    async def one(query: str) -> tuple[Sequence, Sequence]:
        lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
        vector = await embeddings.aembed_query(query)
        vector_hits = await claim_vectors.search_claims(user_id, vector, limit=limit)
        return lexical_hits, vector_hits

    per_query = await asyncio.gather(*(one(q) for q in queries))
    labeled: list[tuple[str, Sequence]] = []
    for lexical_hits, vector_hits in per_query:
        labeled.append(("lexical", lexical_hits))
        labeled.append(("vector", vector_hits))
    return _fuse_claim_hits(labeled, pool_cap if pool_cap is not None else limit)


def render_claims(claims: list[RetrievedClaim]) -> str:
    """Compact deterministic claim payload for the Human turn (input order preserved)."""
    lines: list[str] = []
    for c in claims:
        section = " › ".join(c.section_path) if c.section_path else ""
        head = f"[c:{c.anchor} · {c.document_path}"
        head += f" · {section}]" if section else "]"
        # Provenance as the fixed English `[cite: …]` marker (full source_id) — the model
        # cites by copying it; the app extracts it into a component, so it is never
        # translated to the answer's language.
        cites = " ".join(
            f"[cite: {cit.source_id} ¶{cit.block_start}-{cit.block_end}]"
            for cit in c.citations
        )
        line = f"{head} {c.text}"
        if cites:
            line += f"  {cites}"
        lines.append(line)
    return "\n".join(lines)


def render_windows(windows: list[RecallHit]) -> str:
    """Compact deterministic body-window payload for the Human turn (full block text).

    Windows are the recall lever over uncompiled content, so each line carries the FULL
    block text (capped by count upstream, never truncated). The provenance label uses the
    same `[cite: …]` grammar as render_passages (I4: one addressing vocabulary everywhere)."""
    lines: list[str] = []
    for w in windows:
        # Same fixed English `[cite: …]` marker with the FULL source_id (never truncated),
        # so a window-sourced citation resolves like a claim's.
        lines.append(f"[cite: {w.source_id} ¶{w.block_start}-{w.block_end}] {w.text}")
    return "\n".join(lines)


async def build_episode_summaries(
    hits: Sequence[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
    cap: int = DEFAULT_EPISODE_SUMMARY_CAP,
) -> list[EpisodeSummary]:
    """Lift dense derived episode text from a wide window pool and add mechanical L0 metadata.

    Rank and cap follow the fused source-hit order. Exact `(source, span, text)` duplicates are
    removed. L0 metadata is best-effort (the core-only path may have no ContentStore), but the
    source id and block span are always present because they are the vector point's address.
    """

    if cap <= 0:
        return []
    selected: list[tuple[RecallHit, EpisodeSummarySignal, str]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for hit in hits:
        for signal in hit.episode_summaries:
            text = signal.text.strip()
            key = (
                str(signal.source_id),
                signal.block_start,
                signal.block_end,
                text,
            )
            if not text or key in seen:
                continue
            seen.add(key)
            selected.append((hit, signal, text))
            if len(selected) >= cap:
                break
        if len(selected) >= cap:
            break

    source_ids = tuple(
        dict.fromkeys(str(signal.source_id) for _, signal, _ in selected)
    )

    async def load_source(source_id: str):
        if content is None:
            return None
        try:
            return await content.get(user_id, SourceId(source_id))
        except KeyError:
            return None

    loaded = await asyncio.gather(*(load_source(source_id) for source_id in source_ids))
    cache = dict(zip(source_ids, loaded))

    summaries: list[EpisodeSummary] = []
    for hit, signal, text in selected:
        source = cache[str(signal.source_id)]
        source_title = ""
        source_occurred_on = ""
        section_path: tuple[str, ...] = ()
        if source is not None:
            source_title = getattr(source.raw, "title", "") or ""
            source_occurred_on = source.raw.occurred_on()
            section_path = next(
                (
                    tuple(block.section_path)
                    for block in source.blocks
                    if block.index == signal.block_start
                ),
                (),
            )
        summaries.append(
            EpisodeSummary(
                source_id=signal.source_id,
                block_start=signal.block_start,
                block_end=signal.block_end,
                text=text,
                score=hit.score,
                source_title=source_title,
                source_occurred_on=source_occurred_on,
                section_path=section_path,
            )
        )
    return summaries


def render_episode_summaries(summaries: Sequence[EpisodeSummary]) -> str:
    """Render derived compression with an explicit identity and enough source metadata."""

    return "\n\n".join(
        prompt(
            "recall.fast.episode_summary.item",
            source_id=summary.source_id,
            start=summary.block_start,
            end=summary.block_end,
            source_title=summary.source_title,
            occurred_on=summary.source_occurred_on,
            section=" › ".join(summary.section_path),
            text=summary.text,
        )
        for summary in summaries
    )


def _render_window_section(windows: list) -> str:
    """Render the window payload: assembled Passages (labeled, context-expanded) when the
    hits carry a section_path, else the flat RecallHit rendering (langchain-only fallback)."""
    if windows and hasattr(windows[0], "section_path"):
        return render_passages(windows, header="")
    return render_windows(windows)


def _render_recall_image(image: RecallImage) -> str:
    """Textual locator and derived representations that travel with one image."""

    lines = [
        prompt(
            "recall.fast.image_locator",
            source_id=image.source_id,
            index=image.block_index,
            image_id=image.image.image_id,
        )
    ]
    if image.image.derived:
        lines.extend(
            prompt(
                "compile.task.image_derived",
                image_id=image.image.image_id,
                kind=derived.kind,
                producer=derived.producer,
                text=derived.text,
            )
            for derived in image.image.derived
        )
    else:
        lines.append(
            prompt(
                "compile.task.image_without_derived",
                image_id=image.image.image_id,
            )
        )
    return "\n".join(lines)


async def collect_window_images(
    user_id: UserId,
    windows: Sequence,
    *,
    content: ContentStore | None,
    media: MediaStore | None,
    image_mode: Literal["caption", "native"],
    cap: int = DEFAULT_IMAGE_CAP,
) -> list[RecallImage]:
    """Load images whose blocks overlap selected windows, deduped by immutable digest.

    Caption mode reads only the L0 image manifests and their labelled derived text. Native
    mode additionally retrieves and verifies the original bytes before they can reach the
    model. The selected windows are the mechanical relevance gate: an unrelated image in the
    same source is never attached merely because that source had one hit elsewhere.
    """
    if content is None or not windows or cap <= 0:
        return []
    if image_mode == "native" and media is None:
        raise RuntimeError("native image recall requires a media store")

    spans: dict[SourceId, list[tuple[int, int]]] = {}
    source_order: list[SourceId] = []
    for window in windows:
        source_id = SourceId(str(window.source_id))
        if source_id not in spans:
            spans[source_id] = []
            source_order.append(source_id)
        spans[source_id].append((int(window.block_start), int(window.block_end)))

    result: list[RecallImage] = []
    seen_digests: set[str] = set()
    for source_id in source_order:
        source = await content.get(user_id, source_id)
        for block in source.blocks:
            if not any(start <= block.index <= end for start, end in spans[source_id]):
                continue
            for image in block.images:
                if image.sha256 in seen_digests:
                    continue
                data: bytes | None = None
                if image_mode == "native":
                    assert media is not None
                    data = await media.get(user_id, image.storage_key)
                    if len(data) != image.size_bytes:
                        raise ValueError(
                            f"stored image {image.image_id!r} size no longer matches L0 manifest"
                        )
                    if hashlib.sha256(data).hexdigest() != image.sha256:
                        raise ValueError(
                            f"stored image {image.image_id!r} digest no longer matches L0 manifest"
                        )
                result.append(
                    RecallImage(
                        source_id=source_id,
                        block_index=block.index,
                        image=image,
                        data=data,
                    )
                )
                seen_digests.add(image.sha256)
                if len(result) >= cap:
                    return result
    return result


# ------------------------------------------------- annotation join (opt-in, default off)
#
# The two evidence faces are addressed in disjoint id spaces (claim anchor vs block span),
# which is why they render as two sections — but they are NOT disjoint in the underlying
# text: a claim carries `[cite: <source_id> ¶a-b]`, and a window IS a `[cite: <source_id>
# ¶a-b]`. When those spans overlap, the claim is the compiled reading OF the lines in that
# window, and the model is being asked to discover that by attending across the whole
# evidence wall. The join below does it mechanically instead, and MOVES the claim under its
# window — a move, not a copy, so the claim is stated exactly once and the model is never
# invited to treat the note and the notes-section entry as two pieces of evidence.

#: The skill's controlled strength prefix (`contract.rule.strength_labels`), which the
#: compiler writes at the head of a commitment/relationship claim in every locale: the
#: 【…】 brackets are the fixed shape, the label inside them is the overlay's word.
_STRENGTH_PREFIX_RE = re.compile(r"^【([^】\n]{1,12})】\s*")


def split_strength_label(text: str) -> tuple[str | None, str]:
    """`("firm", "the rest")` for a labeled claim, `(None, text)` for an unlabeled one.

    Lifted out of the text rather than re-derived: the projection layer already tiers on
    this prefix, so a footnote that keeps it in its own slot presents the same tiering the
    rest of the system does, instead of leaving a bracket floating in prose."""
    match = _STRENGTH_PREFIX_RE.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end() :]


def _overlaps(claim: RetrievedClaim, window) -> bool:
    """True when any of the claim's cited spans intersects the window's block interval."""
    return any(
        str(cit.source_id) == str(window.source_id)
        and cit.block_start <= window.block_end
        and window.block_start <= cit.block_end
        for cit in claim.citations
    )


def join_claims_to_windows(
    claims: Sequence[RetrievedClaim],
    windows: Sequence,
    *,
    cap: int = DEFAULT_WINDOW_NOTE_CAP,
) -> tuple[list[RetrievedClaim], list[tuple[object, tuple[RetrievedClaim, ...]]]]:
    """Move each claim under the FIRST window its citation overlaps; cap `cap` per window.

    Returns `(claims that stayed in the notes section, [(window, its notes)] in window
    order)`. A claim lands under at most one window even when it overlaps several — it is
    one statement, and repeating it under each window would re-introduce exactly the
    duplication this join exists to remove. Deterministic: windows in their given order,
    claims in retrieval (RRF) order within each window."""
    taken: set[int] = set()
    paired: list[tuple[object, tuple[RetrievedClaim, ...]]] = []
    for window in windows:
        notes: list[RetrievedClaim] = []
        for index, claim in enumerate(claims):
            if len(notes) >= cap:
                break
            if index in taken or not _overlaps(claim, window):
                continue
            notes.append(claim)
            taken.add(index)
        paired.append((window, tuple(notes)))
    remaining = [c for i, c in enumerate(claims) if i not in taken]
    return remaining, paired


def render_window_notes(notes: Sequence[RetrievedClaim]) -> str:
    """The footnote block under one window: a count line, then one indented line per claim.

    No `[cite: …]` marker on a note line — the window's own provenance header, three lines
    above, IS that citation, and a second copy of the same span would only give the model a
    second thing to transcribe. What the note adds is what the window cannot show: the
    strength the compiler assigned, the claim's anchor, and the document it was filed into."""
    lines = [prompt("recall.fast.window_note.header", count=len(notes))]
    for claim in notes:
        label, text = split_strength_label(claim.text)
        key = "recall.fast.window_note.line_labeled" if label else "recall.fast.window_note.line"
        fields = {
            "text": text,
            "anchor": f"c:{claim.anchor}",
            "document": claim.document_path,
        }
        if label:
            fields["label"] = label
        lines.append(prompt(key, **fields))
    return "\n".join(lines)


def render_annotated_windows(
    paired: Sequence[tuple[object, tuple[RetrievedClaim, ...]]]
) -> str:
    """The window section with each window's claim notes hung directly beneath it."""
    parts: list[str] = []
    for window, notes in paired:
        parts.append(_render_window_section([window]))
        if notes:
            parts.append(render_window_notes(notes))
    return "\n".join(parts)


# --------------------------------------------- subject-timeline expansion (opt-in, default off)
#
# Retrieval surfaces a subject's dated facts one at a time — whichever claims happened to
# match the question's wording — while an interval/ordering question ("when did X first…",
# "what changed between…") is answered by the subject's dated facts arriving TOGETHER, in
# order. Claims are compiled into per-subject documents whose body order approximates
# chronology (the compiler appends as the record grows), and every claim carries its dates in
# its own text. So when a retrieved claim proves a document relevant, the expansion below
# re-projects that document's sibling claims (recall/projection.py — the same parse the L3
# index was built from) and renders them as one compact timeline block per document. The
# expansion is VOLUME-AWARE: a rolled-over subject is one file plus a same-name directory of
# frozen `aNN.md` volumes (compile/rollover.py), and a hit on ANY of those shards expands the
# subject's whole timeline — volumes oldest-first, then the active page — as one block.
# Additive: the claim-notes section is untouched, and `timeline_expand=0` is byte-for-byte
# the lane without this section.


@dataclass(frozen=True)
class TimelineBlock:
    """One hit subject's sibling claims, in document (projection) order.

    `document_path` is the subject's ACTIVE page. For a rolled-over subject the claims span
    its frozen history volumes (oldest first) plus the active page — one subject, one block."""

    document_path: str
    claims: tuple[ProjectedClaim, ...]
    total_claims: int  # the subject's full claim count (all pages), before the per-subject cap


#: A rollover volume's filename inside a subject's history directory (`<page>/aNN.md`).
#: Mirrors `compile.patch._VOLUME_FILE_RE` mechanically: recall reads the layout the groom
#: channel produces without importing the write channel.
_TIMELINE_VOLUME_FILE_RE = re.compile(r"^a\d{2,}\.md$")


def timeline_subject(path: str, documents_by_path: Mapping[str, CanonicalDocument]) -> str:
    """The active page whose timeline `path` belongs to.

    A rollover volume (`work/products/x/a01.md`) belongs to its active page
    (`work/products/x.md`) when that page is in the supplied canonical set; every other path
    — including a volume whose active page is absent — is its own subject. Mechanical, like
    `compile.patch.history_volume_owner`, but keyed off the supplied documents rather than
    the write templates: the canonical set is this lane's authority (never the hit's path)."""
    directory, _, filename = path.rpartition("/")
    if directory and _TIMELINE_VOLUME_FILE_RE.match(filename):
        owner = f"{directory}.md"
        if owner in documents_by_path:
            return owner
    return path


def subject_timeline_paths(
    subject: str, documents_by_path: Mapping[str, CanonicalDocument]
) -> list[str]:
    """The subject's pages oldest-first: frozen volumes in volume order, then the active page.

    Rollover archives the OLDEST claim blocks (`compile.rollover`), so reading a01, a02, …,
    then the active page keeps the concatenated projection in approximate chronological
    order — exactly the order the timeline section renders."""
    prefix = subject.removesuffix(".md") + "/"
    volumes = sorted(
        p
        for p in documents_by_path
        if p.startswith(prefix) and _TIMELINE_VOLUME_FILE_RE.match(p[len(prefix) :])
    )
    return [*volumes, subject]


def select_timeline_claims(
    doc_claims: Sequence[ProjectedClaim],
    hit_anchors: set[str],
    cap: int,
) -> list[ProjectedClaim]:
    """The ≤`cap` sibling claims kept for one document, in document order.

    A document at or under the cap is kept whole — the timeline IS the point. Over the cap,
    the kept set is the claims nearest (by document-order distance) to a retrieved hit: the
    hits anchor which stretch of the subject's history the question touched, and the window
    around them is that stretch's before/after context. Deterministic ties: the earlier claim
    wins. The result is re-sorted into document order, so the rendered block always reads
    oldest → newest regardless of which claims were kept."""
    if cap <= 0 or not doc_claims:
        return []
    if len(doc_claims) <= cap:
        return list(doc_claims)
    hit_positions = [
        i for i, claim in enumerate(doc_claims) if str(claim.anchor) in hit_anchors
    ] or [0]
    ranked = sorted(
        range(len(doc_claims)),
        key=lambda i: (min(abs(i - h) for h in hit_positions), i),
    )
    kept = sorted(ranked[:cap])
    return [doc_claims[i] for i in kept]


def build_subject_timelines(
    hits: Sequence[RetrievedClaim],
    documents_by_path: Mapping[str, CanonicalDocument],
    *,
    per_doc: int,
    doc_cap: int = DEFAULT_TIMELINE_DOC_CAP,
) -> list[TimelineBlock]:
    """The timeline blocks for the subjects the retrieval hit, most-hit subjects first.

    VOLUME-AWARE: a hit on any shard of a rolled-over subject — its active page or one of
    its frozen `aNN.md` history volumes — counts toward ONE subject, and expanding that
    subject projects its whole timeline: volumes oldest-first, then the active page. Without
    this, a retrieval that lands on an archive shard used to expand only that shard and miss
    the sibling volumes (and the active tail) of the very subject the question is about.

    Subjects are ranked by (hit count desc, first-hit RRF position) and the top `doc_cap`
    expanded — a subject the retrieval touched three times is more load-bearing for the
    question than one it grazed once. Only hits whose path is actually present in
    `documents_by_path` count (the hit's path is derived data; the canonical set is the
    authority). The caps are unchanged: `per_doc` bounds the claims kept per SUBJECT (all its
    pages together), so total size stays mechanically ≤ `per_doc × doc_cap` claims."""
    if per_doc <= 0 or doc_cap <= 0 or not hits or not documents_by_path:
        return []
    hit_count: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for position, hit in enumerate(hits):
        path = hit.document_path
        if path not in documents_by_path:
            continue
        subject = timeline_subject(path, documents_by_path)
        hit_count[subject] = hit_count.get(subject, 0) + 1
        first_seen.setdefault(subject, position)
    ordered = sorted(hit_count, key=lambda p: (-hit_count[p], first_seen[p]))

    hit_anchors = {str(hit.anchor) for hit in hits}
    blocks: list[TimelineBlock] = []
    for subject in ordered[:doc_cap]:
        doc_claims: list[ProjectedClaim] = []
        for page in subject_timeline_paths(subject, documents_by_path):
            doc_claims.extend(
                project_document_claims(documents_by_path[page], PROJECTION_V1)
            )
        kept = select_timeline_claims(doc_claims, hit_anchors, per_doc)
        if kept:
            blocks.append(
                TimelineBlock(
                    document_path=subject,
                    claims=tuple(kept),
                    total_claims=len(doc_claims),
                )
            )
    return blocks


def render_subject_timelines(blocks: Sequence[TimelineBlock]) -> str:
    """The timeline section: a self-describing header, then one dated block per document.

    Each line keeps the claim's text (its dates live there), its FIRST citation — enough for
    the answer to cite the span, without repeating a multi-citation tail that can outweigh the
    claim itself — and its anchor. The header explains the section inline because the
    byte-stable System contract (I5) must not change under an experiment flag."""
    parts = [prompt("recall.section.timelines_header", count=len(blocks))]
    for block in blocks:
        parts.append(
            prompt(
                "recall.fast.timeline.document",
                path=block.document_path,
                shown=len(block.claims),
                total=block.total_claims,
            )
        )
        for claim in block.claims:
            line = f"- {claim.text}"
            if claim.citations:
                cit = claim.citations[0]
                line += f" [cite: {cit.source_id} ¶{cit.block_start}-{cit.block_end}]"
            line += f" 〔c:{claim.anchor}〕"
            parts.append(line)
    return "\n".join(parts)


def render_full_documents(documents: Sequence[CanonicalDocument]) -> str:
    """The whole of each selected document, in supplied order, headed by its path.

    Rendered with the compile side's `render_document`, so frontmatter, claim anchors and
    inter-document links reach the answerer in exactly the form the compiler wrote them —
    which is what lets an answer cite a claim it read here the same way it cites a retrieved
    one, and lets the model see the links it could follow."""
    parts: list[str] = []
    for doc in documents:
        parts.append(prompt("recall.fast.select.document_heading", path=doc.path))
        parts.append(render_document(doc.frontmatter, doc.body).rstrip())
    return "\n".join(parts)


def recall_human(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
) -> str:
    """The volatile Human payload shared by fast and deep: profile → snapshot → glance →
    evidence → documents → as_of → input.

    Deterministic assembly order (I5 / prompt-cache discipline), input LAST: the owner profile
    (who is asking — the System tier explains what it is) → the snapshot declaration when the
    question is pinned to a past state of the base → the knowledge base glance (the library's
    shape, which is per-snapshot rather than per-question, so it sits high where a provider
    cache can reach it) → claim section → window section → any documents selected for
    full reading → as_of → the owner's input, so the live ask sits in the attention-hot tail
    below the evidence wall instead of above it. Section headers reuse the contract's exact
    names (owner profile / claim notes / raw excerpts) — what each IS is explained once, in the
    stable System tier, never re-explained per turn. Claims and windows live in disjoint id
    spaces (anchor vs block-span), so they are presented as two sections, never cross-fused.
    The profile is the reason it lives in the Human turn, not the byte-stable System (it is
    per-owner volatile).

    The snapshot declaration sits immediately ABOVE the glance because it governs everything
    below it: the glance, both evidence faces and every tool result are that snapshot. It is
    absent entirely for a HEAD question, so an unpinned prompt is unchanged.

    `window_notes` (default None = the two-section layout above, byte-for-byte) is the opt-in
    annotated layout: (window, notes) pairs whose claims have already been MOVED out of
    `claims` by `join_claims_to_windows`, rendered as footnotes under their own window. The
    two sections still exist and still hold disjoint content — what moves is where a joined
    claim is stated, not whether the claim section is there.

    `timelines` (default () = no section, byte-for-byte the layout above) is the opt-in
    subject-timeline expansion: one dated block per hit document, rendered directly below the
    claim notes it expands on, above the raw excerpts."""
    return _recall_human_evidence(
        claims,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
    ) + _recall_human_tail(question, as_of)


def _recall_human_evidence(
    claims: list[RetrievedClaim],
    *,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
) -> str:
    """Everything before the volatile clock/question tail in the Human message."""

    windows = windows or []
    sections: list[str] = []
    if profile:
        sections.append(f"{prompt('recall.section.profile_header')}\n{profile}")
    if snapshot:
        sections.append(snapshot)
    if glance:
        sections.append(glance)
    sections.append(
        prompt("recall.section.claims_header", count=len(claims))
        + "\n"
        + (render_claims(claims) or prompt("recall.section.claims_empty"))
    )
    if episode_summaries:
        sections.append(
            prompt(
                "recall.section.episode_summaries_header",
                count=len(episode_summaries),
            )
            + "\n"
            + render_episode_summaries(episode_summaries)
        )
    if timelines:
        sections.append(render_subject_timelines(timelines))
    if windows:
        sections.append(
            prompt("recall.section.windows_header", count=len(windows))
            + "\n"
            + (
                render_annotated_windows(window_notes)
                if window_notes is not None
                else _render_window_section(windows)
            )
        )
    if full_documents:
        sections.append(
            prompt("recall.fast.select.documents_header", count=len(full_documents))
            + "\n"
            + render_full_documents(full_documents)
        )
    return "\n\n".join(sections)


def _recall_human_tail(question: str, as_of: datetime) -> str:
    """Attention-hot Human tail, shared by text-only and native-image messages."""

    return f"\n\nas_of: {as_of.isoformat()}\n" + prompt(
        "recall.section.input", question=question
    )


def selector_messages(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
    answer_style: str = DEFAULT_ANSWER_STYLE,
) -> list[BaseMessage]:
    """[SystemMessage(fixed contract), HumanMessage(profile → snapshot → glance → evidence →
    as_of → input)]."""
    human = recall_human_content(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        images=images,
        image_mode=image_mode,
    )
    return [
        SystemMessage(content=selector_contract(answer_style)),
        HumanMessage(content=human),
    ]


def recall_human_content(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
) -> str | list[dict]:
    """Build the volatile Human content shared by direct and agentic recall.

    Original image bytes enter only when the query caller explicitly selected native
    delivery. Caption mode keeps the same block-aligned derived evidence in text form.
    """
    evidence = _recall_human_evidence(
        claims,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
    )
    tail = _recall_human_tail(question, as_of)
    if not images:
        return evidence + tail
    header = prompt("recall.section.images_header", count=len(images))
    if image_mode == "caption":
        return (
            evidence
            + "\n\n"
            + header
            + "\n"
            + "\n".join(_render_recall_image(image) for image in images)
            + tail
        )

    human: list[dict] = [{"type": "text", "text": evidence + "\n\n" + header}]
    for recall_image in images:
        if recall_image.data is None:
            raise ValueError(
                f"native image payload is missing for {recall_image.image.image_id!r}"
            )
        human.append(
            {"type": "text", "text": _render_recall_image(recall_image)}
        )
        human.append(
            create_image_block(
                base64=base64.b64encode(recall_image.data).decode("ascii"),
                mime_type=recall_image.image.mime_type,
                id=recall_image.image.image_id,
            )
        )
    human.append({"type": "text", "text": tail})
    return human


async def answer_with_selector(
    model: BaseChatModel,
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "recall.fast",
    reasoning_effort: str | None = None,
    answer_style: str = DEFAULT_ANSWER_STYLE,
) -> tuple[str, dict[str, int], dict[str, str]]:
    """One selector round: assemble → (pre-hook: alias source ids) → invoke → (answer,
    usage, handle→real_id map). The LLM only ever sees/copies short query-local `sNN`
    handles; the caller reverse-binds them (business side / UI).

    `reasoning_effort` — optional override of the answering model's reasoning effort
    (e.g. "high"/"xhigh"). None (the default) sends NOTHING: the request body is
    byte-identical to the pre-knob behavior and the provider default applies. When set,
    it rides the OpenAI-compatible `extra_body` as `{"reasoning": {"effort": ...}}` —
    the wire shape OpenRouter expects — bound to THIS answer invoke only (the glance
    pass and every other call are untouched). Measurement plumbing; product callers
    pass nothing."""
    system, human = selector_messages(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        images=images,
        image_mode=image_mode,
        answer_style=answer_style,
    )
    if isinstance(human.content, str):
        aliased_human, handle_map = alias_sources(human.content)
    else:
        aliaser = SessionAliaser()
        aliased_human = []
        for block in human.content:
            if isinstance(block, dict) and block.get("type") == "text":
                aliased_human.append(
                    {**block, "text": aliaser.alias(str(block.get("text") or ""))}
                )
            else:
                aliased_human.append(block)
        handle_map = aliaser.handle_map
    # `bind` rather than a constructor knob: the client instance is shared across roles
    # (wiring caches by model spec), so the override must live on this call, not the client.
    answering_model = (
        model.bind(extra_body={"reasoning": {"effort": reasoning_effort}})
        if reasoning_effort
        else model
    )
    response = await answering_model.ainvoke(
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config(run_name, callbacks, trace_metadata),
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    return text.strip(), extract_usage(response), handle_map


# ------------------------------------------------------- the glance selection pass (B)


class DocumentSelection(BaseModel):
    """Structured output of the glance pass: 0..K paths, and nothing else.

    A list of paths rather than free text because the result is CONSUMED mechanically (each
    path is looked up in the document set and dropped if absent) — a prose answer would have
    to be parsed, and a parse this pass cannot verify is a way to read a hallucinated path as
    an instruction."""

    paths: list[str] = Field(default_factory=list)


def glance_selection_contract(cap: int = DEFAULT_GLANCE_PICK_CAP) -> str:
    """The System contract for the glance pass — NOT the answer contract.

    Named apart from `selector_contract()` on purpose. That one is the fast lane's ANSWERING
    posture (it "selects" an answer out of evidence); this one selects DOCUMENTS to read and
    never answers anything. Two different jobs, two different contracts, no shared prose."""
    return prompt("recall.fast.select.contract", cap=cap)


def glance_selection_messages(
    question: str, glance: str, *, cap: int = DEFAULT_GLANCE_PICK_CAP
) -> list[BaseMessage]:
    """[SystemMessage(the pass's contract), HumanMessage(glance → question)]."""
    return [
        SystemMessage(content=glance_selection_contract(cap)),
        HumanMessage(
            content=prompt(
                "recall.fast.select.request", glance=glance, question=question, cap=cap
            )
        ),
    ]


async def select_glance_documents(
    model: BaseChatModel,
    question: str,
    glance: str,
    *,
    known_paths: Sequence[str],
    cap: int = DEFAULT_GLANCE_PICK_CAP,
    timeout: float | None = DEFAULT_GLANCE_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[tuple[str, ...], dict[str, int], str | None]:
    """One small structured call: glance + question → the paths worth reading in full.

    Returns `(paths, token_usage, degraded_reason)`. Fail-soft by construction, because this
    pass is ADDITIVE: a timeout, a provider error, a non-schema reply or a path that is not in
    `known_paths` all degrade to selecting less (or nothing) and let the answer proceed on
    retrieval alone. `degraded_reason` distinguishes "the pass ran and chose nothing" (None —
    the normal, common outcome) from "the pass never delivered" (telemetry).

    Selecting nothing is not a failure and is not retried: an empty selection is exactly what
    a question already covered by matching fragments should produce.
    """
    messages = glance_selection_messages(question, glance, cap=cap)
    config = invoke_config("recall.fast.select", callbacks, trace_metadata)
    try:
        # Inside the guard: a model that does not implement structured output at all raises
        # right here, and that is the same class of failure as a provider error — the lane
        # must keep answering, not 500 because a keyless model lacks a capability.
        structured = model.with_structured_output(DocumentSelection, include_raw=True)
        call = structured.ainvoke(messages, config=config)
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return (), zero_usage(), "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return (), zero_usage(), "error"

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, DocumentSelection):
        return (), usage, "error"

    # Only paths that actually exist survive: the glance is the model's whole view of the
    # library, so anything outside it is invented, and an invented path would otherwise be
    # reported as an expanded document.
    allowed = set(known_paths)
    picked: list[str] = []
    for raw_path in parsed.paths:
        path = str(raw_path or "").strip()
        if path in allowed and path not in picked:
            picked.append(path)
        if len(picked) >= cap:
            break
    return tuple(picked), usage, None


# ------------------------- the retrieval planning + claim rerank passes (both opt-in)

DEFAULT_PLAN_TIMEOUT_SECONDS = 15.0
DEFAULT_RERANK_TIMEOUT_SECONDS = 30.0

#: Safety ceiling on how many pooled candidates one rerank call may score. When a reranker
#: is on, the pool handed to it is the FULL deduped union of every query's hits — RRF is
#: score-blind, so pre-truncating with it would discard candidates the reranker exists to
#: judge. This cap only guards the provider's own per-call document limit (Cohere rerank
#: accepts up to 1000); the RRF head is what survives if the union ever exceeds it.
RERANK_POOL_HARD_CAP = 1000


class QueryPlan(BaseModel):
    """Structured output of the planning pass: 0..K extra retrieval queries.

    A list of strings consumed mechanically (deduped against the question and each other,
    truncated to the cap) — the pass proposes searches, it never controls anything else."""

    queries: list[str] = Field(default_factory=list)




async def plan_retrieval_queries(
    model: BaseChatModel,
    question: str,
    *,
    cap: int,
    timeout: float | None = DEFAULT_PLAN_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[tuple[str, ...], dict[str, int], str | None]:
    """One small structured call BEFORE retrieval: question → extra search queries.

    The fast lane's answer to multi-aspect questions without result-driven loops (those
    belong to deep recall): the model splits the question into the distinct things that
    must be found, each retrieved at full strength alongside the verbatim question.
    Fail-soft like the glance pass: timeout/provider error/non-schema reply all degrade to
    planning nothing, and an empty plan is the normal outcome for a single-aspect question.
    """
    messages = [
        SystemMessage(content=prompt("recall.fast.plan.contract", cap=cap)),
        HumanMessage(content=prompt("recall.fast.plan.request", question=question, cap=cap)),
    ]
    config = invoke_config("recall.fast.plan", callbacks, trace_metadata)
    try:
        structured = model.with_structured_output(QueryPlan, include_raw=True)
        call = structured.ainvoke(messages, config=config)
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return (), zero_usage(), "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return (), zero_usage(), "error"

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, QueryPlan):
        return (), usage, "error"

    seen = {question.strip().casefold()}
    picked: list[str] = []
    for raw_query in parsed.queries:
        query = str(raw_query or "").strip()
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        picked.append(query)
        if len(picked) >= cap:
            break
    return tuple(picked), usage, None


async def rerank_claims(
    reranker: "Reranker",
    question: str,
    candidates: Sequence[RetrievedClaim],
    *,
    cap: int,
    timeout: float | None = DEFAULT_RERANK_TIMEOUT_SECONDS,
) -> tuple[list[RetrievedClaim], str | None]:
    """Score the pooled candidates with a dedicated reranker and keep the best `cap`.

    RRF stays the candidate generator (cheap, score-blind); a cross-encoder reranker reads
    question and claim text together and returns real relevance scores — the magnitude
    judgement fusion cannot make. The answering model is deliberately NOT used here: it
    already reads every surviving claim while answering, so asking it to rank first would
    be the same judgement twice (a caller wanting deeper answer-time judgement raises
    `reasoning_effort` instead).

    Mechanics: valid scored indexes lead (score order, stamped into `.score`), the pool's
    own order backfills to the cap — so a sparse or partial rerank reorders evidence but
    never loses recall relative to the un-reranked lane. Fail-soft: timeout or provider
    error returns the pool head unchanged with a degradation marker."""
    if not candidates:
        return [], None
    fallback = list(candidates[:cap])
    try:
        call = reranker.rerank(
            question, [c.text for c in candidates], top_n=len(candidates)
        )
        results = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return fallback, "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return fallback, "error"

    scored: dict[int, float] = {}
    for result in results:
        index = int(result.index)
        if 0 <= index < len(candidates) and index not in scored:
            scored[index] = float(result.score)
    chosen = sorted(scored, key=lambda i: scored[i], reverse=True)[:cap]
    remainder = [i for i in range(len(candidates)) if i not in scored]
    ordered = [
        replace(candidates[i], score=scored[i]) if i in scored else candidates[i]
        for i in (*chosen, *remainder)
    ][:cap]
    return ordered, None


async def retrieve_windows(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_WINDOW_CAP,
) -> list[RecallHit]:
    """L1+L2 body windows for the answer's recall face (empty if raw indices absent).

    Lexical blocks, raw/caption vectors and episode-description vectors rank independently,
    then ordinary RRF and source-span overlap suppression produce one bounded evidence list. No path
    receives a quota: exact identifiers and dates remain able to outrank broad semantics.
    """
    if lexical is None or vectors is None or limit <= 0:
        return []
    return await rag_recall(
        user_id,
        query,
        lexical=lexical,
        vectors=vectors,
        embeddings=embeddings,
        limit=limit,
    )


async def assemble_windows(
    hits: list[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
    order: bool = True,
    assembly: Mapping[str, int] | None = None,
) -> list:
    """Post-retrieval assembly over raw window hits: lexical expansion → overlap dedup → per-source cap
    → lost-in-the-middle order. With no ContentStore (langchain-only path) the raw hits are
    returned unchanged so no caller breaks.

    `order=False` stops one step short, at score-descending order. Only the annotation join
    wants that: which windows are high-value is not known until the claims have been matched
    against them, so the positional ordering has to happen after the join, not before it.

    `assembly` (default None = `expand_and_merge`'s own defaults, byte-for-byte) is an
    override mapping forwarded verbatim to `expand_and_merge` — the assembly caps
    (`per_source_cap`, `forward_blocks`, `forward_char_budget`, `max_passage_chars`,
    `merge_gap_blocks`) stay defined in ONE place, and an unknown key fails loudly as a
    TypeError rather than being silently dropped. It exists for measurement work (the
    eval bench sweeps these caps); product callers pass nothing and are unchanged."""
    if content is None or not hits:
        return list(hits)
    passages = await expand_and_merge(
        hits, content=content, user_id=user_id, **dict(assembly or {})
    )
    return order_lost_in_middle(passages) if order else passages


async def fast_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    answer_model: BaseChatModel | None = None,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    media: MediaStore | None = None,
    image_mode: Literal["caption", "native"] = "caption",
    image_cap: int = DEFAULT_IMAGE_CAP,
    profile: str | None = None,
    cap: int = DEFAULT_CLAIM_CAP,
    claim_candidate_cap: int = DEFAULT_CLAIM_CANDIDATE_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    window_candidate_cap: int = DEFAULT_WINDOW_CANDIDATE_CAP,
    episode_summary_cap: int = DEFAULT_EPISODE_SUMMARY_CAP,
    # The SHAPE of the answer: "concise" (the bare exact value — graders, scripts),
    # "conversational" (a natural chat reply, the default), or "detailed" (a
    # self-contained written note). Style only — truth discipline is style-independent.
    answer_style: str = DEFAULT_ANSWER_STYLE,
    # The canonical documents at the answering snapshot. Supplied → the glance is rendered
    # into the prompt and the glance pass runs; omitted (None) → byte-for-byte the
    # retrieval-only lane, so no caller is forced to load canonical to ask a question.
    documents: Sequence[CanonicalDocument] | None = None,
    skill: object | None = None,
    packs: Sequence[object] = (),
    # The frozen snapshot this answer is pinned to, or None = today's base. It changes ONE
    # thing in this lane: the prompt states which snapshot is open. The evidence is already
    # snapshot-scoped upstream — the caller passed the snapshot tenant's indexes and the
    # document set read at its canonical ref.
    scope: SnapshotScope | None = None,
    # OFF by default, and the off path is byte-for-byte the lane above. On: every claim whose
    # cited span overlaps a retrieved window is MOVED out of the claim-notes section and hung
    # under that window as a footnote, and annotated windows are ordered as high-value units.
    # See `join_claims_to_windows` for why it is a move rather than a copy.
    annotate_windows: bool = False,
    window_note_cap: int = DEFAULT_WINDOW_NOTE_CAP,
    # None by default = `expand_and_merge`'s own assembly defaults, byte-for-byte. A mapping
    # here is forwarded verbatim through `assemble_windows` to `expand_and_merge` (e.g.
    # {"per_source_cap": 6}); the defaults stay defined in one place, and an unknown key
    # raises rather than silently doing nothing. Measurement plumbing — product callers
    # pass nothing.
    window_assembly: Mapping[str, int] | None = None,
    # OFF by default (0), and the off path is byte-for-byte the lane above. N > 0: every
    # document a retrieved claim lives in (top `timeline_doc_cap` by hit count, and only when
    # `documents` was supplied — the expansion reads canonical, never the index) is expanded
    # into a subject-timeline block of up to N sibling claims in document order. See
    # `build_subject_timelines`.
    timeline_expand: int = 0,
    timeline_doc_cap: int = DEFAULT_TIMELINE_DOC_CAP,
    glance_model: BaseChatModel | None = None,
    glance_pick_cap: int = DEFAULT_GLANCE_PICK_CAP,
    glance_timeout: float | None = DEFAULT_GLANCE_TIMEOUT_SECONDS,
    # OFF by default (0), and the off path is byte-for-byte the lane above. N > 0: one
    # planning call (on `plan_model`, falling back to `model`) derives up to N extra
    # retrieval queries BEFORE retrieval, and the claim face pools all queries through one
    # RRF fusion (`retrieve_claims_multi`). Planning sees only the question — result-driven
    # multi-round retrieval belongs to deep recall, not this lane.
    plan_queries_cap: int = 0,
    plan_model: BaseChatModel | None = None,
    plan_timeout: float | None = DEFAULT_PLAN_TIMEOUT_SECONDS,
    # OFF by default (None/0), and the off path is byte-for-byte the lane above. A Reranker
    # plus N > 0 widens claim retrieval to an N-candidate pool and lets the reranker's real
    # relevance scores pick the `cap` that survive (see `rerank_claims` for why the
    # answering model is not used for this).
    reranker: Reranker | None = None,
    rerank_candidates: int = 0,
    rerank_timeout: float | None = DEFAULT_RERANK_TIMEOUT_SECONDS,
    # `answer_model` splits the final generation from the cheap recall-role model used by
    # planning/glance. None preserves the historical one-model lane. A None reasoning effort
    # sends nothing; a value (e.g. "xhigh") overrides the ANSWERING call via OpenRouter's
    # `{"reasoning": {"effort": ...}}` extra_body — see `answer_with_selector`. The
    # glance pass never takes it. Measurement plumbing — product callers pass nothing.
    reasoning_effort: str | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> FastAnswer:
    """fast recall: the knowledge base glance + L3 claims + L1/L2 body windows → one answer.

    Two disjoint retrieval faces answer one question: claims give precision + citation
    provenance, body windows give recall over content never lifted into claims (e.g. a
    distill-treated record whose compile produced only abstract meta-claims). Each face
    is internally RRF-fused; they are presented as two sections, never cross-fused.

    When a ContentStore is wired the raw window hits go through the post-retrieval assembly
    pipeline (expand → merge/dedup → per-source cap → lost-in-the-middle order), so a bare
    hit carries its surrounding context; without one the raw hits render as before.

    TWO BRANCHES, ONE WALL CLOCK. When `documents` is supplied, retrieval (A) and the glance
    selection pass (B) are launched together under one `asyncio.gather`, so the lane costs
    max(A, B) + the answer call rather than A + B + the answer. B is a single small
    structured call whose output is a handful of paths, so it is normally the faster of the
    two. B is strictly additive: it selects nothing for most questions, and a timeout or
    provider error degrades to the retrieval-only answer with a `glance_degraded` marker —
    it can never fail or delay the answer past its own timeout.

    The glance itself is present whether or not B selects anything: the shape of the library
    is context for every question, not a reward for a successful selection.

    The retrieval faces are independent network work (each embeds the query + hits
    Meili/Qdrant), so they run concurrently on the event loop via `asyncio.gather` — the
    wall-clock is the slower face, not their sum, and the double query-embed overlaps
    instead of stacking. `gather` returns results in argument order, so `claims` and
    `raw_windows` bind exactly as they did under the previous thread-pool fan-out."""

    # The planning pass runs BEFORE retrieval (its whole output is retrieval input), so it
    # is the one stage that adds sequential wall-clock — which is why it is opt-in.
    planned: tuple[str, ...] = ()
    plan_usage = zero_usage()
    plan_degraded: str | None = None
    if plan_queries_cap > 0:
        planned, plan_usage, plan_degraded = await plan_retrieval_queries(
            plan_model or model,
            question,
            cap=plan_queries_cap,
            timeout=plan_timeout,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
        )

    # The claim face always retrieves beyond the final evidence wall. This is cheap index
    # work and leaves enough tail for containment dedup and multi-path disagreement. With a
    # reranker on, `rerank_candidates` may widen it further: it is the
    # per-query/per-face retrieval depth, and the reranker judges the FULL deduped union
    # against the original question (RRF pre-truncation would silently drop candidates it
    # never saw — fusion order is kept only for dedup, backfill and the failure fallback).
    # The final `cap` remains independent from either candidate depth.
    reranking = reranker is not None and rerank_candidates > 0
    claim_pool = max(
        cap,
        claim_candidate_cap,
        rerank_candidates if reranking else 0,
    )

    async def retrieve_claim_face() -> list[RetrievedClaim]:
        if planned or reranking:
            return await retrieve_claims_multi(
                user_id,
                (question, *planned),
                claim_lexical=claim_lexical,
                claim_vectors=claim_vectors,
                embeddings=embeddings,
                limit=claim_pool,
                pool_cap=RERANK_POOL_HARD_CAP if reranking else None,
            )
        return await retrieve_claims(
            user_id,
            question,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            limit=claim_pool,
        )

    async def retrieval_branch() -> tuple[list[RetrievedClaim], list[RecallHit]]:
        return await asyncio.gather(  # type: ignore[return-value]
            retrieve_claim_face(),
            retrieve_windows(
                user_id,
                question,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=max(window_cap, window_candidate_cap),
            ),
        )

    glance: str | None = None
    by_path: dict[str, CanonicalDocument] = {}
    if documents is not None:
        glance = render_canonical_glance(documents, skill, packs=packs)
        by_path = {doc.path: doc for doc in documents}

    selected: tuple[str, ...] = ()
    select_usage = zero_usage()
    degraded: str | None = None
    if glance and by_path:
        (claims_raw, raw_windows), (selected, select_usage, degraded) = await asyncio.gather(
            retrieval_branch(),
            select_glance_documents(
                glance_model or model,
                question,
                glance,
                known_paths=tuple(by_path),
                cap=glance_pick_cap,
                timeout=glance_timeout,
                callbacks=callbacks,
                trace_metadata=trace_metadata,
            ),
        )
    else:
        claims_raw, raw_windows = await retrieval_branch()

    rerank_degraded: str | None = None
    if reranking:
        claims, rerank_degraded = await rerank_claims(
            reranker, question, claims_raw, cap=cap, timeout=rerank_timeout
        )
    else:
        claims = claims_raw[:cap]
    # Built from the FULL capped hit set, before the annotation join may move claims out of
    # the notes section: which documents the retrieval touched is a property of retrieval,
    # not of where a claim happens to be rendered.
    timelines: list[TimelineBlock] = []
    if timeline_expand > 0 and by_path:
        timelines = build_subject_timelines(
            claims, by_path, per_doc=timeline_expand, doc_cap=timeline_doc_cap
        )
    episode_summaries = await build_episode_summaries(
        raw_windows,
        content=content,
        user_id=user_id,
        cap=episode_summary_cap,
    )
    windows = await assemble_windows(
        raw_windows[:window_cap],
        content=content,
        user_id=user_id,
        order=not annotate_windows,
        assembly=window_assembly,
    )
    images = await collect_window_images(
        user_id,
        windows,
        content=content,
        media=media,
        image_mode=image_mode,
        cap=image_cap,
    )
    window_notes: list[tuple[object, tuple[RetrievedClaim, ...]]] | None = None
    if annotate_windows:
        claims, paired = join_claims_to_windows(
            claims, windows, cap=window_note_cap
        )
        window_notes = order_lost_in_middle(paired, priority=lambda p: bool(p[1]))
        windows = [w for w, _ in window_notes]
    # Reading the selected documents is a local git read the caller already paid for (they
    # are in `documents`), so the expansion costs nothing on the wire.
    expanded = [by_path[path] for path in selected]
    answer_trace_metadata = {
        **(trace_metadata or {}),
        "image_count": len(images),
        "image_mode": image_mode,
    }
    answer, usage, citation_handles = await answer_with_selector(
        answer_model or model,
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=scope_declaration(scope),
        full_documents=expanded,
        window_notes=window_notes,
        timelines=timelines,
        images=images,
        image_mode=image_mode,
        callbacks=callbacks,
        trace_metadata=answer_trace_metadata,
        run_name="recall.fast",
        reasoning_effort=reasoning_effort,
        answer_style=answer_style,
    )
    return FastAnswer(
        answer=answer,
        used_claims=tuple(claims),
        token_usage=add_usage(add_usage(usage, select_usage), plan_usage),
        used_windows=tuple(windows),
        citation_handles=citation_handles,
        glance_chars=len(glance or ""),
        expanded_documents=selected,
        glance_degraded=degraded,
        annotated_claims=sum(len(n) for _, n in (window_notes or ())),
        annotated_windows=sum(1 for _, n in (window_notes or ()) if n),
        timeline_documents=tuple(block.document_path for block in timelines),
        timeline_claims=sum(len(block.claims) for block in timelines),
        planned_queries=planned,
        plan_degraded=plan_degraded,
        rerank_degraded=rerank_degraded,
        image_count=len(images),
        image_mode=image_mode,
        claim_candidates=len(claims_raw),
        window_candidates=len(raw_windows),
        used_episode_summaries=tuple(episode_summaries),
    )
