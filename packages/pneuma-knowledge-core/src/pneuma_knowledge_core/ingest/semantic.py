"""LLM topic/entity boundary detection for L2 chunking (chunk_strategy="semantic").

Motivation: an interview compilation has each candidate as a natural unit but NO
headings, so sentence/token chunking splits mid-candidate or merges two. This module
adopts nemori's *boundary-detection philosophy* — a topic/entity change is a boundary;
ignore filler/pleasantries; do not over-split; aim for coherent units — but NOT its
implementation: nemori rewrites content into narrative and loses provenance. Here the
LLM only returns BLOCK-INDEX boundaries over the EXISTING numbered blocks; chunk text is
always a verbatim slice of the block-joined string, so invariant I4 (dual char/block
addressing) is preserved exactly as on the chonkie path.

**Middleware-free (architecture.md §2).** Like recall/fast.py and persona/generate.py,
this depends only on langchain's `BaseChatModel` abstraction + `invoke_config`; the model
(the configured provider model) and any callbacks/trace metadata are injected by the service. A test
passes a fake whose `.with_structured_output(Segments)` returns fixed segment starts.
"""

from __future__ import annotations

import asyncio
import hashlib

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..domain.source import NormalizedBlock, StructureMap
from ..domain.ids import SourceId
from ..recall.fast import invoke_config
from .chunking import (
    Chunk,
    _covering_blocks,
    _effective_sections,
    enforce_max_chars,
    join_blocks,
)

# Each block's PROMPT preview is truncated to bound prompt size; the returned boundaries
# still index the REAL full blocks (only the preview the LLM reads is shortened).
_PREVIEW_CHARS = 240
# Default cap on blocks per LLM call; larger docs are processed in sequential windows.
DEFAULT_MAX_BLOCKS_PER_CALL = 200
# A single coherent segment longer than this many chars is sentence-sub-split so its
# embedding stays meaningful (an over-long unit is graceful-degraded, never dropped).
DEFAULT_MAX_CHUNK_CHARS = 2000


def blocks_content_digest(blocks: list[NormalizedBlock]) -> str:
    """sha256 of the block-joined source text — the exact input to semantic chunking.

    This is the manifest key: it changes iff the normalized L0 content changes, so a
    recorded segmentation is reused only for byte-identical content (a source edit misses
    the cache and re-detects). Ordered by block index to match `semantic_chunk_source`."""
    text, _ = join_blocks(sorted(blocks, key=lambda b: b.index))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_result_digest(chunks: list[Chunk]) -> str:
    """sha256 over the produced chunk char spans — an audit fingerprint of the final L2
    layout. Two rebuilds that reuse the same segments produce the same digest; a drift
    (code change, different segments) shows up as a different fingerprint."""
    joined = ";".join(f"{c.char_start}-{c.char_end}" for c in chunks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class Segments(BaseModel):
    """The structured-output contract: the ascending list of segment START BLOCK NUMBERS.

    The model returns ONLY integers (the block index each segment opens at) — never any
    content, never titles. Segment i spans [start_i, start_{i+1} - 1], the last to the
    final block — so gaps/overlaps are impossible by construction; any disorder is
    repaired mechanically in `semantic_segments`. Keeping the output a bare int list is
    deliberate: chunk text is always a verbatim slice of the source, so the LLM's only
    job is boundary detection — it must not regenerate/summarize content."""

    segments: list[int] = Field(default_factory=list)


# Byte-stable, volatile-free rubric (I5 / prompt-cache discipline). Encodes the
# nemori-derived boundary philosophy. No block content here — the numbered blocks ride
# the Human turn.
_SEGMENTER_RUBRIC = """\
你在为个人知识库切分一段按顺序编号的内容。目标：把内容切成若干「语义段」，理想情况下一个自然单元（例如一位候选人、一个主题）= 一段。

切分规则（按优先级）：
- 以「实质话题 / 主体（如某个候选人、某个具体主题）的转变」作为最高优先级的切分点。
- 忽略寒暄、过渡、客套这类填充内容，不要因为它们而切分。
- 不要过度切分——把属于同一主体 / 同一话题的连续内容并为一段。
- 每个自然单元（如对某一位候选人的完整评价）尽量完整地落在同一段里。

只需给出每个语义段的「起始块编号」（segments，升序整数）。段 i 覆盖 [start_i, start_{i+1}-1]，最后一段直到最末一块；因此你无需给出结束编号。编号必须是列表里出现过的真实块编号。
"""


def _number_blocks(window: list[NormalizedBlock], offset: int) -> str:
    """`<lineno>:<preview>` listing over a window (grep -n / git grep convention — the
    standard way to express line numbers, not an invented `#N` format). The number before
    the colon is the block's global position; that is exactly what the model returns."""
    lines: list[str] = []
    for local, b in enumerate(window):
        pos = offset + local
        preview = " ".join(b.text.split())  # collapse whitespace/newlines for the preview
        if len(preview) > _PREVIEW_CHARS:
            preview = preview[:_PREVIEW_CHARS] + "…"
        lines.append(f"{pos}:{preview}")
    return "\n".join(lines)


async def _segment_window_starts(
    window: list[NormalizedBlock],
    offset: int,
    *,
    model: BaseChatModel,
    callbacks: list | None,
    trace_metadata: dict | None,
) -> set[int]:
    """Ask the model for segment start positions within one window; return the clamped set.

    Positions are global (offset..offset+len-1). Out-of-window / non-int starts are
    dropped here; ascending/dedup/ensure-0 is finished by `semantic_segments`."""
    listing = _number_blocks(window, offset)
    lo, hi = offset, offset + len(window) - 1
    human = (
        f"以下是编号 {lo}..{hi} 的内容块（共 {len(window)} 块），每行格式为 "
        f"「行号:内容」（行号即冒号前的整数，与 grep -n 一致）。"
        f"请返回每个语义段的起始行号：\n\n{listing}"
    )
    messages = [
        SystemMessage(content=_SEGMENTER_RUBRIC),
        HumanMessage(content=human),
    ]
    structured = model.with_structured_output(Segments)
    result = await structured.ainvoke(
        messages,
        config=invoke_config("chunk.semantic", callbacks, trace_metadata),
    )
    starts: set[int] = set()
    for seg in getattr(result, "segments", []) or []:
        try:
            s = int(seg)
        except (TypeError, ValueError):
            continue
        if lo <= s <= hi:
            starts.add(s)
    return starts


async def semantic_segments(
    blocks: list[NormalizedBlock],
    *,
    model: BaseChatModel,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
) -> list[tuple[int, int]]:
    """LLM boundary detection → contiguous inclusive block intervals covering ALL blocks.

    Segment i = [start_i, end_i] with end_i = start_{i+1} - 1 and the last ending at the
    final block, so the intervals partition the blocks with no gaps or overlaps.

    **Large-doc windowing (nemori-style incremental carry).** When there are more than
    `max_blocks_per_call` blocks, the blocks are processed in sequential windows. Only the
    very first block (position 0) is a *forced* boundary; a later window's first block is
    NOT forced to start a segment, so an open segment carries across the window boundary
    unless the model itself reports a new start there. Start positions from every window
    are unioned, then repaired (dedup, clamp, ensure 0) into the final partition.

    **Repair.** Returned starts are coerced to ints, clamped to the valid position range,
    deduped, sorted ascending, and 0 is guaranteed present — so a non-ascending /
    out-of-range / missing-0 model output still yields a sane partition.

    The returned intervals are in REAL block-index space (mapped from ordered positions),
    so they compose with `join_blocks` / `_effective_sections` / `_covering_blocks`.
    """
    ordered = sorted(blocks, key=lambda b: b.index)
    n = len(ordered)
    if n == 0:
        return []
    idx = [b.index for b in ordered]

    start_positions: set[int] = {0}  # position 0 is always a boundary (first must be 0)
    for w_start in range(0, n, max_blocks_per_call):
        w_end = min(w_start + max_blocks_per_call, n)  # exclusive
        window = ordered[w_start:w_end]
        start_positions |= await _segment_window_starts(
            window,
            w_start,
            model=model,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
        )

    positions = sorted(p for p in start_positions if 0 <= p < n)
    if not positions or positions[0] != 0:
        positions = [0, *positions]  # defensive: guarantee the first boundary
    intervals: list[tuple[int, int]] = []
    for i, p in enumerate(positions):
        e = positions[i + 1] - 1 if i + 1 < len(positions) else n - 1
        intervals.append((idx[p], idx[e]))
    return intervals


def _refine_by_sections(
    block_indices: list[int],
    seg_intervals: list[tuple[int, int]],
    sections: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Common refinement of the LLM segments and the StructureMap sections.

    A new boundary is opened at every segment start AND every section start, so the
    result never crosses a section (section starts are cuts) while otherwise following the
    LLM's segment boundaries. For a headingless doc (one big section) the only section cut
    is the first block, so the LLM boundaries fully drive it (a no-op)."""
    cuts = {iv[0] for iv in seg_intervals} | {iv[0] for iv in sections}
    result: list[tuple[int, int]] = []
    cur_start: int | None = None
    prev: int | None = None
    for i in block_indices:
        if cur_start is None:
            cur_start, prev = i, i
        elif i in cuts:
            result.append((cur_start, prev))  # type: ignore[arg-type]
            cur_start, prev = i, i
        else:
            prev = i
    if cur_start is not None:
        result.append((cur_start, prev))  # type: ignore[arg-type]
    return result


async def semantic_chunk_source(
    source_id: SourceId,
    blocks: list[NormalizedBlock],
    structure: StructureMap,
    *,
    model: BaseChatModel | None = None,
    segments: list[tuple[int, int]] | None = None,
    sub_chunker=None,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
) -> list[Chunk]:
    """One Chunk per coherent unit, with exact char/block provenance (I4).

    - Segments come from `semantic_segments` (LLM boundaries over the numbered blocks) —
      UNLESS `segments` is supplied (a manifest replay), which skips the LLM entirely for
      a byte-deterministic rebuild. Everything downstream of segmentation is deterministic,
      so replaying the recorded segments reproduces the exact same chunks.
    - Segments are refined against `_effective_sections`: a segment is clipped at section
      boundaries when the doc HAS real sections, so a chunk never crosses a section; a
      headingless doc (one implicit section) is fully driven by the LLM boundaries.
    - Each resulting interval becomes ONE Chunk over that block interval — text is the
      verbatim block-joined slice, char_start/char_end are source-global offsets, and the
      covering block interval is derived from those offsets (reusing the chonkie machinery).
    - **Over-long safeguard:** a segment whose joined text exceeds `max_chunk_chars` is
      sentence-sub-split with `sub_chunker` (the chonkie SentenceChunker built from
      settings) so embeddings stay meaningful; the sub-chunks keep exact char/block spans.

    Deterministic given a fixed model output.
    """
    by_index = {b.index: b for b in blocks}
    if not by_index:
        return []
    block_indices = sorted(by_index)
    global_text, ranges = join_blocks(blocks)

    if segments is None:
        if model is None:
            raise ValueError(
                "semantic_chunk_source needs either precomputed `segments` "
                "(manifest replay) or a `model` to detect them"
            )
        segments = await semantic_segments(
            blocks,
            model=model,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
            max_blocks_per_call=max_blocks_per_call,
        )
    sections = _effective_sections(block_indices, structure)
    intervals = _refine_by_sections(block_indices, segments, sections)

    chunks: list[Chunk] = []
    for seg_start, seg_end in intervals:
        present = [i for i in range(seg_start, seg_end + 1) if i in by_index]
        if not present:
            continue
        base = ranges[present[0]][0]
        end = ranges[present[-1]][1]
        seg_text = global_text[base:end]
        if not seg_text.strip():
            continue
        if len(seg_text) > max_chunk_chars and sub_chunker is not None:
            # A single unit too large to embed as one vector: sentence-sub-split it. Each
            # piece's offsets are translated back into the source-global char space.
            # CPU-bound chonkie sub-split → a real worker thread, not a fake await.
            for piece in await asyncio.to_thread(sub_chunker.chunk, seg_text):
                cs = base + piece.start_index
                ce = base + piece.end_index
                b_start, b_end = _covering_blocks(cs, ce, ranges)
                chunks.append(
                    Chunk(
                        source_id=source_id,
                        block_start=b_start,
                        block_end=b_end,
                        text=piece.text,
                        char_start=cs,
                        char_end=ce,
                    )
                )
        else:
            b_start, b_end = _covering_blocks(base, end, ranges)
            chunks.append(
                Chunk(
                    source_id=source_id,
                    block_start=b_start,
                    block_end=b_end,
                    text=seg_text,
                    char_start=base,
                    char_end=end,
                )
            )
    return enforce_max_chars(chunks, ranges)
