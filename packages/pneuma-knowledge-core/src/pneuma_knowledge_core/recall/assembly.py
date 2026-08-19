"""Post-retrieval assembly pipeline (standard RAG content organization).

`rag_recall` is a strong *recall* front-end (claim + window RRF fusion), but a raw
fused hit is a bare block: a lexical name hit can return just `[401,401]` = a bare name
with none of the surrounding evaluation, and a mid-document candidate is invisible when a
briefing packs only a 4-block sample. That is a missing *assembly* stage, not a recall gap.

This module is the standard post-retrieval pipeline, pure and deterministic (langchain-free):

    expand → overlap-dedup → per-source cap → lost-in-the-middle order → labeled render

- **expand_and_merge** grows a bare lexical-only hit FORWARD (anchored at its own block — a
  record flows forward from its match, so backward expansion would bleed the previous
  record in). Semantic raw/episode hits are already natural units and are not expanded
  again. Truly overlapping windows within a source coalesce; disjoint episodes never acquire
  unretrieved bridge blocks merely because they are nearby. The result is capped per source
  and rebuilt from authoritative blocks.
- **order_lost_in_middle** places the strongest passages at the head and tail and the
  weakest in the middle (the U-shaped "Lost in the Middle" positional bias).
- **render_passages** renders each passage with a human-readable provenance header
  (source *title* and occurrence date, section breadcrumb, exact block interval) so the
  model can attribute, time-anchor and discriminate between records.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from ..domain.ids import UserId, SourceId
from ..ports.content_store import ContentStore
from ..prompts import prompt
from .rag import RecallHit


@dataclass(frozen=True)
class Passage:
    """A context-expanded, merged retrieval passage addressed by an inclusive block span.

    The block interval `[block_start, block_end]` is exact provenance (citation round-trip
    and UI drill-down) even when `text` is truncated for payload bounding. `source_title`
    is the human title of the owning source for a readable provenance label;
    `source_occurred_on` is the source's own occurrence label (never ingest time); and
    `section_path` is the section breadcrumb of the highest-scoring seed hit."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    paths: tuple[str, ...]
    score: float
    section_path: tuple[str, ...] = ()
    source_title: str = ""
    source_occurred_on: str = ""


# ------------------------------------------------------------------- expand + merge


@dataclass
class _Interval:
    """Mutable working interval during expand/merge within one source."""

    start: int
    end: int
    score: float
    paths: list[str]
    seed_score: float
    section_path: tuple[str, ...]


def _union_paths(into: list[str], extra: Sequence[str]) -> None:
    for p in extra:
        if p not in into:
            into.append(p)


def _truncate(text: str, max_chars: int) -> str:
    """Bound a rendered passage to `max_chars`, keeping the HEAD and dropping the tail.

    A record's entry — its name / source label / first fields — lives at the head, so keep
    that. The old middle-drop (head + tail) silently gutted the body, where the answer often
    is. The block interval on the Passage stays exact, so deep can fetch_verbatim the rest.
    (Chunks are hard-capped at ingest, so this only fires for a whole-block lexical hit on an
    unusually large block.)"""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + prompt("recall.passage_truncated")
    )


def _expand_one(
    hit: RecallHit,
    block_map: dict[int, str],
    section_map: dict[int, tuple[str, ...]],
    *,
    forward_blocks: int,
    forward_char_budget: int,
) -> _Interval:
    """Asymmetric expansion (director's rule): anchor backward, grow forward.

    A block is a paragraph, so the passage's start stays at the hit's own block — we NEVER
    expand backward into earlier blocks. That is deliberate: a record flows forward from its
    match (a name block is followed by its evaluation), so backward expansion would only bleed
    the *previous* record's tail into this passage. We expand FORWARD only — crossing paragraph
    boundaries is fine — up to `forward_blocks` blocks or `forward_char_budget` chars (whichever
    first), clamped to the source boundary. This pulls a bare name block into its own evaluation
    without dragging in the neighbour above it."""
    start, end = hit.block_start, hit.block_end
    # Semantic raw and episode hits already cover the natural unit chosen at ingest. The
    # older generic assembly default predates those representations and expanded every hit
    # five blocks forward, turning an exact two-block episode into most of a chat session.
    # Keep forward context only for a lexical-only block hit, which is the case expansion
    # was designed to handle in the first place. Empty representation metadata is the legacy
    # and hand-built-test shape, so it keeps the historical lexical expansion behavior.
    if hit.representations and any(
        representation in {"raw", "episode"}
        for representation in hit.representations
    ):
        forward_blocks = 0
    fwd_chars = fwd_count = 0
    while fwd_count < forward_blocks and fwd_chars < forward_char_budget:
        nxt = end + 1
        if nxt not in block_map:
            break
        end = nxt
        fwd_chars += len(block_map[nxt])
        fwd_count += 1
    section_path = section_map.get(hit.block_start, ())
    return _Interval(
        start=start,
        end=end,
        score=hit.score,
        paths=list(hit.paths),
        seed_score=hit.score,
        section_path=section_path,
    )


def _rebuild_text(block_map: dict[int, str], start: int, end: int) -> str:
    """Join a contiguous block interval in index order (bridged holes included)."""
    parts = [block_map[i] for i in range(start, end + 1) if i in block_map]
    return "\n".join(parts)


async def expand_and_merge(
    hits: Sequence[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
    forward_blocks: int = 1,
    forward_char_budget: int = 700,
    max_passage_chars: int = 2500,
    per_source_cap: int = 3,
    merge_gap_blocks: int = -1,
) -> list[Passage]:
    """Standard expand → overlap-dedup → per-source cap over fused recall hits.

    Groups hits by source; fetches each source once (cached). For each source it expands
    lexical-only hits FORWARD (anchoring at the hit's own block — never bleeding backward
    into the previous record; see `_expand_one`). Semantic raw/episode hits keep their
    recorded span. The default `merge_gap_blocks=-1` coalesces only overlapping intervals;
    callers can explicitly request bridge blocks for a measured domain that needs them.
    Merged passages take the max score, the union of retrieval paths, and the section
    breadcrumb of their highest-scoring seed. Text is rebuilt from the source's blocks and
    truncated past `max_passage_chars` while the block interval stays exact. At most
    `per_source_cap` passages survive per source (highest score first) so one document can't
    flood the context. Deterministic throughout: stable tie-break by (source_id, block_start).
    Falls back to the hit's own text/span for a source that can't be fetched (missing source
    or `content is None`)."""
    # Group hits by source, preserving fused order for stability.
    by_source: dict[str, list[RecallHit]] = {}
    for hit in hits:
        by_source.setdefault(str(hit.source_id), []).append(hit)

    cache: dict[str, object] = {}

    async def _source(sid: str):
        if sid not in cache:
            if content is None:
                cache[sid] = None
            else:
                try:
                    cache[sid] = await content.get(user_id, SourceId(sid))
                except KeyError:
                    cache[sid] = None
        return cache[sid]

    passages: list[Passage] = []
    for sid, group in by_source.items():
        ns = await _source(sid)
        if ns is None:
            # No source content: keep each hit's own text/span (no expansion/merge).
            capped = sorted(group, key=lambda h: (-h.score, h.block_start))[:per_source_cap]
            for h in capped:
                passages.append(
                    Passage(
                        source_id=SourceId(sid),
                        block_start=h.block_start,
                        block_end=h.block_end,
                        text=h.text,
                        paths=tuple(h.paths),
                        score=h.score,
                        section_path=(),
                        source_title="",
                        source_occurred_on="",
                    )
                )
            continue

        block_map = {b.index: b.text for b in ns.blocks}
        section_map = {b.index: tuple(b.section_path) for b in ns.blocks}
        title = getattr(ns.raw, "title", "") or ""
        occurred_on = ns.raw.occurred_on()

        # Expand each hit, then merge left-to-right over sorted intervals.
        intervals = [
            _expand_one(
                h,
                block_map,
                section_map,
                forward_blocks=forward_blocks,
                forward_char_budget=forward_char_budget,
            )
            for h in group
        ]
        intervals.sort(key=lambda iv: (iv.start, iv.end))

        merged: list[_Interval] = []
        for iv in intervals:
            if merged:
                last = merged[-1]
                gap = iv.start - last.end - 1  # blocks strictly between (negative = overlap)
                if gap <= merge_gap_blocks:
                    last.end = max(last.end, iv.end)
                    last.score = max(last.score, iv.score)
                    _union_paths(last.paths, iv.paths)
                    if iv.seed_score > last.seed_score:
                        last.seed_score = iv.seed_score
                        last.section_path = iv.section_path
                    continue
            merged.append(iv)

        source_passages = [
            Passage(
                source_id=SourceId(sid),
                block_start=iv.start,
                block_end=iv.end,
                text=_truncate(_rebuild_text(block_map, iv.start, iv.end), max_passage_chars),
                paths=tuple(iv.paths),
                score=iv.score,
                section_path=iv.section_path,
                source_title=title,
                source_occurred_on=occurred_on,
            )
            for iv in merged
        ]
        source_passages.sort(key=lambda p: (-p.score, p.block_start))
        passages.extend(source_passages[:per_source_cap])

    passages.sort(key=lambda p: (-p.score, str(p.source_id), p.block_start))
    return passages


# ------------------------------------------------------------- lost-in-the-middle order


_Unit = TypeVar("_Unit")


def order_lost_in_middle(
    passages: Sequence[_Unit], *, priority: Callable[[_Unit], bool] | None = None
) -> list[_Unit]:
    """LongContextReorder: strongest passages to the HEAD and TAIL, weakest in the MIDDLE.

    Long-context models attend most to the beginning and end of the context and least to
    the middle (the U-shaped "Lost in the Middle" positional bias, Liu et al. 2023). Given
    passages already sorted by score descending, we place ranked items alternately toward
    the front and back: rank 1 lands at the head, rank 2 at the tail, and the weakest sink
    into the low-attention middle. Deterministic.

    `priority` (default None = the ranking above, unchanged byte-for-byte) marks units whose
    VALUE does not come from their retrieval score. They are stably lifted ahead of the rest
    before the alternating placement, so they take the attention-hot end slots and the
    unmarked ones sink into the middle. fast's annotated windows are the case that needs it:
    a window carrying claim notes is a fused evidence unit rather than a lone excerpt, and
    its rank as an excerpt says nothing about that.

    Generic in the unit, not fixed to `Passage`: the caller may order (window, notes) pairs
    with the same rule rather than having to re-derive the pairing after ordering."""
    ordered = list(passages)
    if priority is not None:
        ordered = [p for p in ordered if priority(p)] + [
            p for p in ordered if not priority(p)
        ]
    head: list[_Unit] = []
    tail: list[_Unit] = []
    for i, p in enumerate(ordered):
        (head if i % 2 == 0 else tail).append(p)
    return head + tail[::-1]


# ---------------------------------------------------------------------- labeled render


def _provenance(passage: Passage) -> str:
    """`[cite: <source_id> ¶start-end] <title> › <section>` — the provenance marker.

    The `[cite: …]` token is a FIXED English/ASCII marker the app extracts into a citation
    component; it is never translated to the answer's language, and its `source_id` is the
    FULL resolvable id (never truncated) so a cited span always resolves. Any human title /
    section rides AFTER the token as readable context, never inside the extractable marker."""
    token = f"[cite: {passage.source_id} ¶{passage.block_start}-{passage.block_end}]"
    ctx: list[str] = []
    if passage.source_title.strip():
        ctx.append(passage.source_title.strip())
    if (
        passage.source_occurred_on.strip()
        and passage.source_occurred_on not in passage.source_title
    ):
        ctx.append(f"occurred_on={passage.source_occurred_on.strip()}")
    if passage.section_path:
        ctx.append(" › ".join(passage.section_path))
    return f"{token} {' · '.join(ctx)}".rstrip()


def render_passages(passages: Sequence[Passage], *, header: str | None = None) -> str:
    """Render passages with a per-passage provenance header line so the model can attribute
    and discriminate between records. `header` optionally titles the whole block (empty =
    no title line; the caller supplies its own section header). Replaces the flat single-line
    window rendering."""
    if header is None:
        header = prompt("recall.section.passages_header")
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
    for p in passages:
        lines.append(_provenance(p))
        lines.append(p.text)
    return "\n".join(lines)
