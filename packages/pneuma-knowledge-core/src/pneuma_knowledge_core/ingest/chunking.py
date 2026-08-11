"""Structure-aware chunking for L2 semantic indexing (architecture.md §7).

Chunking is delegated to **chonkie** (a production chunking library) but constrained
by the StructureMap so a chunk never crosses a section boundary (§3, §7). For each
effective section we join that section's block texts and hand the resulting substring
to the configured chonkie chunker; chonkie splits it at sentence boundaries with real
overlap. Because we chunk per section, a chunk can never straddle two sections.

**Dual addressing (invariant I4).** Every chunk carries two provenance faces:

- ``char_start`` / ``char_end`` — half-open offsets into the *source-global
  block-joined string* (all blocks in index order joined by ``"\n"``). This is the
  chunk's exact, unique identity: a single oversized block (e.g. a 30-minute narration)
  is now split into several sub-block chunks, and their char spans distinguish them
  where the block interval no longer can.
- ``block_start`` / ``block_end`` — the inclusive interval of *covering* blocks (every
  block whose char range intersects the chunk span). For a sub-block chunk this is a
  single block; it still round-trips to L0 verbatim (a superset of the chunk text is
  always fetchable), so drill-down / provenance resolution is preserved.

``char_start`` / ``char_end`` are relative to the block-joined string built by
``join_blocks`` — deterministic given the blocks, so a fresh ingest and a re-index
produce identical offsets. ``chunk_source`` is pure and deterministic given a chunker.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..domain.ids import SourceId
from ..domain.source import NormalizedBlock, RawSource, StructureMap

# chonkie's default 'character' tokenizer counts ~1 token/char, so for CJK text chunk_size
# is effectively a character budget (768 ≈ a comfortable paragraph). See build_chunker.
DEFAULT_CHUNK_STRATEGY = "sentence"
DEFAULT_CHUNK_SIZE = 768
DEFAULT_CHUNK_OVERLAP = 128

# Hard ceiling on a chunk's char length. chonkie splits at sentence boundaries only, so
# delimiter-less content (a version-history table, a single very long line) comes back as
# ONE oversized chunk — bad for embeddings and it leaks into recall as a giant, mid-truncated
# passage. Any chunk over this is hard-split by length so a chunk is always embeddable and
# bounded, regardless of punctuation. ~1.5× the token target to leave sentence chunks intact.
HARD_MAX_CHUNK_CHARS = 1200

# chonkie's SentenceChunker default delimiters are ASCII-only ('. ', '! ', '? ', '\n')
# — they require a trailing space, so CJK narration (。！？ with no spaces) would never
# split. We add the CJK sentence terminators so Chinese/Japanese text splits at real
# sentence boundaries; the ASCII delimiters are kept for mixed / English content.
_SENTENCE_DELIMS = [
    "\n",
    ". ",
    "! ",
    "? ",
    "。",
    "！",
    "？",
    "；",
    "…",
]


@dataclass(frozen=True)
class Chunk:
    """A structure-aware chunk with dual provenance (char span + covering blocks)."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EmbeddedChunk:
    """A Chunk plus its embedding — the concrete VectorIndex.upsert_chunks input."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    char_start: int
    char_end: int
    embedding: list[float]


def embedding_text_for_chunk(
    chunk: Chunk,
    blocks: list[NormalizedBlock],
    *,
    raw: RawSource | None = None,
) -> str:
    """The L2 vector input for one verbatim chunk.

    The stored chunk text and its exact char span remain a byte-for-byte L0 slice.
    Source title/occurrence context and labelled caption/OCR text attached to any covered
    block are appended only to the embedding input. Semantic search can therefore find a
    dated episode or image by meaning without turning metadata/derived text into fake
    source prose or inventing a second citation space.
    """

    context_lines = raw.retrieval_context_lines() if raw is not None else []
    media_lines = [
        line
        for block in sorted(blocks, key=lambda item: item.index)
        if chunk.block_start <= block.index <= chunk.block_end
        for line in block.derived_media_index_lines()
    ]
    if not context_lines and not media_lines:
        return chunk.text
    return "\n".join([*context_lines, chunk.text, *media_lines])


def build_chunker(
    strategy: str = DEFAULT_CHUNK_STRATEGY,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
):
    """Build a chonkie chunker instance (the single place chonkie is configured).

    - ``"sentence"`` (default) → ``SentenceChunker`` with CJK-aware delimiters and real
      overlap — sentence boundaries + overlap directly answer the "no overlap" gap.
    - ``"recursive"`` → ``RecursiveChunker`` for structure-heavy documents (no overlap).

    chonkie's default ``character`` tokenizer runs fully offline and counts ~1 token per
    character, so ``chunk_size`` roughly equals a character budget for CJK text.
    """
    from chonkie import RecursiveChunker, SentenceChunker

    if strategy == "sentence":
        return SentenceChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            delim=_SENTENCE_DELIMS,
            include_delim="prev",
        )
    if strategy == "recursive":
        return RecursiveChunker(chunk_size=chunk_size)
    raise ValueError(
        f"unknown chunk strategy {strategy!r} (expected 'sentence' or 'recursive')"
    )


def join_blocks(blocks: list[NormalizedBlock]) -> tuple[str, dict[int, tuple[int, int]]]:
    """The source-global block-joined string + each block's half-open char range.

    Blocks are joined in index order by ``"\n"`` (one char per separator). Returns the
    joined string and ``{block_index: (char_lo, char_hi)}``. Deterministic — the sole
    definition of the char-offset space char_start/char_end address into.
    """
    ordered = sorted(blocks, key=lambda b: b.index)
    ranges: dict[int, tuple[int, int]] = {}
    parts: list[str] = []
    pos = 0
    for n, b in enumerate(ordered):
        if n > 0:
            pos += 1  # the "\n" separator between blocks
        ranges[b.index] = (pos, pos + len(b.text))
        pos += len(b.text)
        parts.append(b.text)
    return "\n".join(parts), ranges


def _effective_sections(
    block_indices: list[int], structure: StructureMap
) -> list[tuple[int, int]]:
    """Return inclusive (start, end) section intervals covering every block.

    Sections declared by the StructureMap are honoured verbatim; any blocks left
    uncovered (no structure, or gaps) are grouped into their own contiguous runs so
    that no block is dropped from L2.
    """
    covered: set[int] = set()
    intervals: list[tuple[int, int]] = []
    for span in structure.sections:
        intervals.append((span.start_block, span.end_block))
        covered.update(range(span.start_block, span.end_block + 1))

    run_start: int | None = None
    prev: int | None = None
    for idx in block_indices:
        if idx in covered:
            continue
        if run_start is None:
            run_start, prev = idx, idx
        elif prev is not None and idx == prev + 1:
            prev = idx
        else:
            intervals.append((run_start, prev))  # type: ignore[arg-type]
            run_start, prev = idx, idx
    if run_start is not None:
        intervals.append((run_start, prev))  # type: ignore[arg-type]

    return sorted(intervals)


def _covering_blocks(
    char_start: int, char_end: int, ranges: dict[int, tuple[int, int]]
) -> tuple[int, int]:
    """Inclusive (min, max) index of every block whose char range intersects the span.

    Half-open intersection: block [lo, hi) covers the chunk if ``lo < char_end`` and
    ``char_start < hi``. Blocks are contiguous in the joined string, so the covering
    set is a contiguous run — round-trips to L0 (a superset of the chunk text)."""
    covering = [
        idx
        for idx, (lo, hi) in ranges.items()
        if lo < char_end and char_start < hi
    ]
    if not covering:
        # A degenerate span landing exactly on a separator: fall back to the nearest
        # block starting at char_start (keeps every chunk block-addressable, I4).
        nearest = min(
            ranges,
            key=lambda i: abs(ranges[i][0] - char_start),
        )
        return nearest, nearest
    return min(covering), max(covering)


def enforce_max_chars(
    chunks: list[Chunk],
    ranges: dict[int, tuple[int, int]],
    *,
    limit: int = HARD_MAX_CHUNK_CHARS,
) -> list[Chunk]:
    """Hard-split any chunk whose text exceeds ``limit`` into contiguous ≤limit slices.

    The fallback for delimiter-less content chonkie won't split (tables, long single lines).
    Each slice keeps exact dual provenance: its char span is the parent's shifted by the byte
    offset (chunk text is verbatim ``global_text[char_start:char_end]``), and its covering
    block interval is recomputed from that span. Order-preserving and deterministic."""
    out: list[Chunk] = []
    for ch in chunks:
        if len(ch.text) <= limit:
            out.append(ch)
            continue
        for off in range(0, len(ch.text), limit):
            sub = ch.text[off : off + limit]
            cs = ch.char_start + off
            ce = cs + len(sub)
            b_start, b_end = _covering_blocks(cs, ce, ranges)
            out.append(
                Chunk(
                    source_id=ch.source_id,
                    block_start=b_start,
                    block_end=b_end,
                    text=sub,
                    char_start=cs,
                    char_end=ce,
                )
            )
    return out


async def chunk_source(
    source_id: SourceId,
    blocks: list[NormalizedBlock],
    structure: StructureMap,
    *,
    chunker=None,
) -> list[Chunk]:
    """Split blocks into section-bounded, sentence-level chunks via chonkie. Pure and
    deterministic given ``chunker`` (default: ``build_chunker()`` — the shipped
    sentence chunker with overlap).

    Each effective section (``_effective_sections``) is joined and chunked independently
    so no chunk crosses a section. chonkie's char offsets into the section substring are
    translated into source-global offsets (``char_start`` / ``char_end``); the covering
    block interval is derived from those offsets.

    ``async`` only so the caller can stay on the event loop: chonkie's ``.chunk()`` is
    CPU-bound, synchronous, and NOT async — it is genuinely run on a worker thread via
    ``asyncio.to_thread``, not awaited as real I/O. The thread is what keeps a large
    source from stalling the loop; nothing here overlaps."""
    by_index = {b.index: b for b in blocks}
    if not by_index:
        return []
    block_indices = sorted(by_index)
    global_text, ranges = join_blocks(blocks)
    if chunker is None:
        chunker = build_chunker()

    chunks: list[Chunk] = []
    for sec_start, sec_end in _effective_sections(block_indices, structure):
        present = [i for i in range(sec_start, sec_end + 1) if i in by_index]
        if not present:
            continue
        base = ranges[present[0]][0]
        end = ranges[present[-1]][1]
        section_text = global_text[base:end]
        if not section_text.strip():
            continue
        # CPU-bound chonkie work → a real worker thread, not a fake await.
        for piece in await asyncio.to_thread(chunker.chunk, section_text):
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

    return enforce_max_chars(chunks, ranges)
