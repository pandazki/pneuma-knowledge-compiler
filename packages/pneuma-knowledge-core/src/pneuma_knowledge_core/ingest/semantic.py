"""LLM topic/entity boundary detection for L2 chunking (chunk_strategy="semantic").

Motivation: an interview compilation has each candidate as a natural unit but NO
headings, so sentence/token chunking splits mid-candidate or merges two. This module
adopts the *boundary-detection philosophy* of nemori
(https://github.com/nemori-ai/nemori) — a topic/entity change is a boundary;
ignore filler/pleasantries; do not over-split; aim for coherent units — but NOT its
implementation: nemori rewrites content into narrative and loses provenance. Here the
LLM only returns BLOCK-INDEX boundaries over the EXISTING numbered blocks; chunk text is
always a verbatim slice of the block-joined string, so invariant I4 (dual char/block
addressing) is preserved exactly as on the chonkie path.

**Two output contracts, one philosophy** (`semantic_overlap`, the `PNEUMA_KNOWLEDGE_SEMANTIC_OVERLAP`
setting). `off` is the original: the model returns start block numbers, segment i runs to
the block before segment i+1, and overlap is impossible by construction. `smart` asks for
closed intervals instead, so a hinge block — the sentence that closes one topic while
opening the next — can belong to BOTH neighbouring segments. Overlap is a judgement the
model makes per boundary, not a fixed stride: the degenerate answer ("every segment is the
whole document") is not argued out of the model, it is refused by `overlap_rejection`
below, whose five gates every returned interval list must pass or be replaced by the
zero-overlap partition. `off` is the mode all existing measurements were taken in and its
request bytes are pinned; `smart` is the shipped default awaiting a same-harness A/B.

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
from ..prompts import prompt
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
# A long block keeps BOTH ends: the head is where a new topic announces itself, the tail
# is where the block has drifted to — the signal for whether the NEXT block starts
# something new. Blocks within the budget are shown whole; only the rare long block pays
# the ellipsis. Units are str characters (code points), not tokens — for CJK that is
# roughly 1 token per character.
_PREVIEW_HEAD_CHARS = 320
_PREVIEW_TAIL_CHARS = 160
# Default cap on blocks per LLM call; larger docs are processed in sequential windows.
DEFAULT_MAX_BLOCKS_PER_CALL = 200
# A single coherent segment longer than this many chars is sentence-sub-split so its
# embedding stays meaningful (an over-long unit is graceful-degraded, never dropped).
DEFAULT_MAX_CHUNK_CHARS = 2000

# The two segmentation output contracts. `off` is the historical (and measured) one.
OVERLAP_OFF = "off"
OVERLAP_SMART = "smart"
OVERLAP_MODES = (OVERLAP_OFF, OVERLAP_SMART)

# Ceiling on how many blocks two neighbouring segments may share, in `smart` mode.
#
# This is the anti-degeneracy gate, and it is a gate rather than a sentence in the rubric
# for a mechanical reason: "segments may overlap where the content serves both" has a
# trivially optimal reading — make every segment the whole document, and every segment is
# then guaranteed to contain the answer. A model that reads the rubric that way would
# collapse L2 into N copies of the source, and no amount of prompt wording makes that
# reading unavailable. A hard bound does. Three is one more than the "one or two blocks"
# the rubric describes as a hinge, so an honest hinge is never rejected for being one block
# generous, while a swallowed neighbour always is.
MAX_OVERLAP_BLOCKS = 3

# The manifest envelope version. v2 is the first that records WHICH output contract
# produced the spans; anything recorded before it is a bare list (see
# `decode_manifest_segments`), which stays replayable exactly as written.
MANIFEST_VERSION = 2


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


# ─────────────────────────────────────────────────────── the chunk-manifest record shape


def encode_manifest_segments(
    segments: list[tuple[int, int]], *, overlap: str
) -> dict:
    """The versioned record a first detection writes into `chunk_manifests.segments`.

    The mode rides WITH the spans rather than beside them because it is a property of how
    these spans were produced, not of the deployment that reads them later: replay compares
    the recorded mode with the current one, and a mismatch re-detects. That is what makes
    `semantic_overlap` honestly a `derived_rebuild` knob — flipping it and rebuilding
    actually re-cuts, instead of replaying yesterday's layout forever."""
    return {
        "version": MANIFEST_VERSION,
        "overlap": overlap,
        "spans": [[int(s), int(e)] for s, e in segments],
    }


def decode_manifest_segments(
    recorded, *, block_indices: list[int]
) -> tuple[list[tuple[int, int]], str] | None:
    """A recorded manifest → `(segments, the mode that produced them)`, or None if unusable.

    Three shapes are accepted, and the two legacy ones replay exactly as written — a record
    from before this envelope existed is a rebuild that must stay byte-identical, so it is
    read, never migrated:

    * `{"version": 2, "overlap": …, "spans": [[s, e], …]}` — what is written today.
    * `[[s, e], …]` — the pre-envelope record. Its mode is read off the data itself
      (touching neighbours = `off`, overlapping = `smart`) rather than assumed, so a
      deployment already running the shipped default does not re-detect its whole library
      to learn what the spans already say.
    * `[i, i, …]` — bare start block numbers, the oldest shape; expanded through the same
      partition rule the start-only contract has always used.

    Anything else (a future version, a malformed blob) returns None: no replay, re-detect.
    That is the safe direction — a wrong replay is a silently wrong index, a re-detect is
    one model call.
    """
    if isinstance(recorded, dict):
        if recorded.get("version") != MANIFEST_VERSION:
            return None
        mode = recorded.get("overlap")
        if mode not in OVERLAP_MODES:
            return None
        spans = _coerce_spans(recorded.get("spans"))
        return (spans, mode) if spans else None
    if not isinstance(recorded, list) or not recorded:
        return None
    if all(isinstance(item, int) and not isinstance(item, bool) for item in recorded):
        order = list(block_indices)
        positions = sorted({order.index(i) for i in recorded if i in set(order)})
        if not positions:
            return None
        expanded = _partition_from_starts(positions, 0, len(order) - 1)
        return ([(order[s], order[e]) for s, e in expanded], OVERLAP_OFF)
    spans = _coerce_spans(recorded)
    if len(spans) != len(recorded):
        return None
    mode = (
        OVERLAP_SMART
        if any(e >= s_next for (_, e), (s_next, _) in zip(spans, spans[1:]))
        else OVERLAP_OFF
    )
    return spans, mode


class Segments(BaseModel):
    """The structured-output contract: the ascending list of segment START BLOCK NUMBERS.

    The model returns ONLY integers (the block index each segment opens at) — never any
    content, never titles. Segment i spans [start_i, start_{i+1} - 1], the last to the
    final block — so gaps/overlaps are impossible by construction; any disorder is
    repaired mechanically in `semantic_segments`. Keeping the output a bare int list is
    deliberate: chunk text is always a verbatim slice of the source, so the LLM's only
    job is boundary detection — it must not regenerate/summarize content."""

    segments: list[int] = Field(default_factory=list)


class SegmentSpans(BaseModel):
    """The `semantic_overlap="smart"` structured-output contract: CLOSED block intervals.

    `segments` is a list of `[start, end]` pairs, both ends inclusive, ordered by start.
    Still integers only, still no content: the extra freedom the model gets over `Segments`
    is exactly one degree — a segment may end AFTER the next one starts, so a hinge block is
    read once as the close of what came before and once as the opening of what follows.
    Everything the pairs are allowed to be is enforced by `overlap_rejection`, not asked for
    in prose."""

    segments: list[list[int]] = Field(default_factory=list)


# Byte-stable, volatile-free rubric (I5 / prompt-cache discipline), resolved from the prompt
# catalog. Encodes the nemori-derived boundary philosophy. No block content here — the
# numbered blocks ride the Human turn.


def _number_blocks(window: list[NormalizedBlock], offset: int) -> str:
    """`<lineno>:<preview>` listing over a window (grep -n / git grep convention — the
    standard way to express line numbers, not an invented `#N` format). The number before
    the colon is the block's global position; that is exactly what the model returns."""
    lines: list[str] = []
    for local, b in enumerate(window):
        pos = offset + local
        preview = " ".join(b.text.split())  # collapse whitespace/newlines for the preview
        if len(preview) > _PREVIEW_HEAD_CHARS + _PREVIEW_TAIL_CHARS:
            omitted = len(preview) - _PREVIEW_HEAD_CHARS - _PREVIEW_TAIL_CHARS
            # The gap is labeled with its size: "how much is missing" is itself boundary
            # signal (a huge elision means the block is long and has room to drift).
            preview = (
                preview[:_PREVIEW_HEAD_CHARS]
                + f" …({omitted} chars truncated)… "
                + preview[-_PREVIEW_TAIL_CHARS:]
            )
        lines.append(f"{pos}:{preview}")
    return "\n".join(lines)


async def _ask_structured(
    model: BaseChatModel,
    schema: type,
    messages: list,
    *,
    callbacks: list | None,
    trace_metadata: dict | None,
    attempts: int = 2,
):
    """One structured-output round trip, degrading instead of raising.

    The window gates below judge what the model SAID; they never see a call whose reply
    could not be decoded at all — a truncated or prose-wrapped tool-call payload makes
    `with_structured_output` raise while parsing, upstream of every gate. That exception
    used to escape the chunker and kill the whole index job, permanently: nothing retries
    an index job, so one malformed reply left a source unindexed for good (seen on a real
    corpus — the same window parsed fine on a plain re-run).

    So the discipline the gates already follow — the model not cooperating degrades the
    result, never the run — is extended one layer out: retry once, then give up on THIS
    window and return None. A None reply reports no boundaries for the window, which the
    existing repair reads as "one segment here", and an over-long segment is already
    sentence-sub-split downstream (DEFAULT_MAX_CHUNK_CHARS). Coarser chunking for one
    window, instead of a source that never gets indexed at all."""
    structured = model.with_structured_output(schema)
    config = invoke_config("chunk.semantic", callbacks, trace_metadata)
    for attempt in range(attempts):
        try:
            return await structured.ainvoke(messages, config=config)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception:  # noqa: BLE001 — any undecodable reply degrades this window
            if attempt == attempts - 1:
                return None
    return None


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
    human = prompt(
        "ingest.semantic.human",
        lo=lo,
        hi=hi,
        count=len(window),
        listing=listing,
    )
    messages = [
        SystemMessage(content=prompt("ingest.semantic.rubric")),
        HumanMessage(content=human),
    ]
    result = await _ask_structured(
        model,
        Segments,
        messages,
        callbacks=callbacks,
        trace_metadata=trace_metadata,
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


# ───────────────────────────────────────────── smart overlap: the gate and the fallback


def _coerce_spans(raw) -> list[tuple[int, int]]:
    """Structured output → `[(start, end), …]`, dropping only what is not a pair of ints.

    Shape coercion ONLY: an endpoint outside the window, a reversed pair, a start that goes
    backwards — none of that is repaired here, because every one of those is a gate below
    and repairing it silently would be the gate's opposite. A dropped malformed entry turns
    into a coverage hole, which the gate then catches."""
    spans: list[tuple[int, int]] = []
    for item in raw or []:
        pair = list(item) if isinstance(item, (list, tuple)) else None
        if pair is None or len(pair) != 2:
            continue
        try:
            spans.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError):
            continue
    return spans


def overlap_rejection(
    spans: list[tuple[int, int]],
    lo: int,
    hi: int,
    *,
    max_overlap: int = MAX_OVERLAP_BLOCKS,
) -> str:
    """"" when this interval list is acceptable, else the reason it is refused.

    Five mechanical gates over one window of blocks `lo..hi`. They are written as a total
    check on the returned data rather than as instructions the model is trusted to have
    followed, and a single violation rejects the WHOLE output — a partly-honoured contract
    is not a weaker contract, it is an unknown one.

    1. **Real, ordered endpoints** — every number is a block that was actually in the
       listing, and no interval ends before it starts.
    2. **Strictly increasing starts** — one segment opens per position, in reading order.
    3. **Gapless cover** — the first starts at `lo`, the last ends at `hi`, and no segment
       opens more than one block past the previous one's end. No block of the source may
       fall out of L2 because the model forgot it.
    4. **Bounded overlap** — neighbours share at most `max_overlap` blocks. See
       `MAX_OVERLAP_BLOCKS`: without this, "the whole document, N times" satisfies gates
       1-3 perfectly.
    5. **Sane segment count** — never more segments than there are blocks, the same
       implicit bound the start-only contract gets for free from deduplicating positions.
    """
    if not spans:
        return "no segments returned"
    blocks = hi - lo + 1
    if len(spans) > blocks:
        return f"{len(spans)} segments over {blocks} blocks"
    for s, e in spans:
        if not (lo <= s <= hi) or not (lo <= e <= hi):
            return f"segment [{s}, {e}] leaves the block range {lo}..{hi}"
        if e < s:
            return f"segment [{s}, {e}] ends before it starts"
    if spans[0][0] != lo:
        return f"first segment starts at {spans[0][0]}, not at block {lo}"
    if spans[-1][1] != hi:
        return f"last segment ends at {spans[-1][1]}, not at block {hi}"
    for (s, e), (s_next, _) in zip(spans, spans[1:]):
        if s_next <= s:
            return f"segment starts are not strictly increasing at {s_next}"
        if s_next > e + 1:
            return f"blocks {e + 1}..{s_next - 1} are covered by no segment"
        shared = e - s_next + 1
        if shared > max_overlap:
            return f"segments share {shared} blocks at {s_next}, over the {max_overlap} allowed"
    return ""


def _partition_from_starts(starts, lo: int, hi: int) -> list[tuple[int, int]]:
    """Start positions → the zero-overlap partition of `lo..hi` they imply.

    The repair the start-only contract has always run, factored out because it is also the
    FALLBACK the overlap gate falls back TO: a rejected interval list still told us where
    the model thought segments began, and the partition built from those starts is the
    behavior this deployment would have had with `semantic_overlap` off. So a refused output
    costs the overlap, never the segmentation."""
    positions = sorted({p for p in starts if lo <= p <= hi})
    if not positions or positions[0] != lo:
        positions = [lo, *positions]
    return [
        (p, positions[i + 1] - 1 if i + 1 < len(positions) else hi)
        for i, p in enumerate(positions)
    ]


async def _segment_window_spans(
    window: list[NormalizedBlock],
    offset: int,
    *,
    model: BaseChatModel,
    callbacks: list | None,
    trace_metadata: dict | None,
) -> list[tuple[int, int]]:
    """Ask the model for closed segment intervals over one window; gate them, or degrade.

    Positions are global (offset..offset+len-1). The gate covers the WINDOW, because the
    window is what the model was shown: it is the only range in which "you left block 7 out"
    is a statement about this call rather than about the document."""
    listing = _number_blocks(window, offset)
    lo, hi = offset, offset + len(window) - 1
    human = prompt(
        "ingest.semantic.human_overlap",
        lo=lo,
        hi=hi,
        count=len(window),
        listing=listing,
    )
    messages = [
        SystemMessage(content=prompt("ingest.semantic.rubric_overlap")),
        HumanMessage(content=human),
    ]
    result = await _ask_structured(
        model,
        SegmentSpans,
        messages,
        callbacks=callbacks,
        trace_metadata=trace_metadata,
    )
    spans = _coerce_spans(getattr(result, "segments", []))
    if overlap_rejection(spans, lo, hi):
        return _partition_from_starts((s for s, _ in spans), lo, hi)
    return spans


async def semantic_segments(
    blocks: list[NormalizedBlock],
    *,
    model: BaseChatModel,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
    overlap: str = OVERLAP_OFF,
) -> list[tuple[int, int]]:
    """LLM boundary detection → inclusive block intervals covering ALL blocks.

    With `overlap="off"` (the historical contract) segment i = [start_i, end_i] with
    end_i = start_{i+1} - 1 and the last ending at the final block, so the intervals
    partition the blocks with no gaps or overlaps. With `overlap="smart"` the model returns
    the intervals itself and neighbours may share up to `MAX_OVERLAP_BLOCKS` hinge blocks;
    coverage is still total and gapless, enforced per window by `overlap_rejection`.

    **Large-doc windowing (nemori-style incremental carry).** When there are more than
    `max_blocks_per_call` blocks, the blocks are processed in sequential windows. In `off`
    mode only the very first block (position 0) is a *forced* boundary; a later window's
    first block is NOT forced to start a segment, so an open segment carries across the
    window boundary unless the model itself reports a new start there. Start positions from
    every window are unioned, then repaired (dedup, clamp, ensure 0) into the final
    partition. `smart` mode cannot carry an open segment across a window: gate 3 requires
    each window's intervals to cover that window exactly, which is the only range the model
    was shown and therefore the only range its output can be judged against. A window
    boundary is a segment boundary there — the same cost the windowing already pays for
    prompt size, made explicit.

    **Repair.** In `off` mode returned starts are coerced to ints, clamped to the valid
    position range, deduped, sorted ascending, and 0 is guaranteed present — so a
    non-ascending / out-of-range / missing-0 model output still yields a sane partition. In
    `smart` mode a window whose intervals fail any gate falls back to exactly that repair
    over the starts it did report: the overlap is refused, the segmentation is not.

    The returned intervals are in REAL block-index space (mapped from ordered positions),
    so they compose with `join_blocks` / `_effective_sections` / `_covering_blocks`.
    """
    if overlap not in OVERLAP_MODES:
        raise ValueError(f"unknown semantic_overlap mode {overlap!r}; expected one of {OVERLAP_MODES}")
    ordered = sorted(blocks, key=lambda b: b.index)
    n = len(ordered)
    if n == 0:
        return []
    idx = [b.index for b in ordered]

    if overlap == OVERLAP_SMART:
        spans: list[tuple[int, int]] = []
        for w_start in range(0, n, max_blocks_per_call):
            w_end = min(w_start + max_blocks_per_call, n)  # exclusive
            spans.extend(
                await _segment_window_spans(
                    ordered[w_start:w_end],
                    w_start,
                    model=model,
                    callbacks=callbacks,
                    trace_metadata=trace_metadata,
                )
            )
        return [(idx[s], idx[e]) for s, e in spans]

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

    return [
        (idx[p], idx[e]) for p, e in _partition_from_starts(start_positions, 0, n - 1)
    ]


def _close_gaps(
    block_indices: list[int], seg_intervals: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Segments → segments that between them touch every block, ends only ever extended.

    Both contracts already guarantee total coverage (`off` by construction, `smart` by gate
    3), so on real input this is the identity. It exists for the one caller that is not a
    contract — `segments=` handed in directly, e.g. a manifest written by an older build —
    where a hole would silently drop source blocks out of L2. A hole is closed by extending
    the interval BEFORE it, never by inventing one, so overlap is untouched."""
    first, last = block_indices[0], block_indices[-1]
    segs = sorted((int(s), int(e)) for s, e in seg_intervals)
    if not segs:
        return [(first, last)]
    if segs[0][0] > first:
        segs.insert(0, (first, segs[0][0] - 1))
    closed = [
        (s, max(e, segs[i + 1][0] - 1) if i + 1 < len(segs) else e)
        for i, (s, e) in enumerate(segs)
    ]
    if closed[-1][1] < last:
        closed[-1] = (closed[-1][0], last)
    return closed


def _refine_by_sections(
    block_indices: list[int],
    seg_intervals: list[tuple[int, int]],
    sections: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Common refinement of the LLM segments and the StructureMap sections.

    Each segment is cut at every section start that falls inside it, so no chunk ever
    crosses a section, while the LLM's own boundaries otherwise stand. For a headingless doc
    (one big section) the only section start is the first block, so the LLM boundaries fully
    drive it (a no-op).

    Refinement is per SEGMENT rather than over a global set of cut points, which for a
    partition is the same thing and for overlapping segments is the only correct thing: a
    neighbour's start falling inside a segment is exactly the hinge the overlap was asked
    for, so it must not also be read as a cut."""
    section_starts = {iv[0] for iv in sections}
    result: list[tuple[int, int]] = []
    for seg_start, seg_end in _close_gaps(block_indices, seg_intervals):
        present = [i for i in block_indices if seg_start <= i <= seg_end]
        if not present:
            continue
        cur, prev = present[0], present[0]
        for i in present[1:]:
            if i in section_starts:
                result.append((cur, prev))
                cur = i
            prev = i
        result.append((cur, prev))
    # Two identical intervals would embed and store the same text twice under the same
    # span — not overlap, just a duplicate. Order is preserved (dict, not set).
    return list(dict.fromkeys(result))


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
    overlap: str = OVERLAP_OFF,
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
    - **Overlap** (`overlap="smart"`) puts a hinge block into two chunks. That duplication
      lives entirely in the derived layer (I2): L0 is untouched, both chunks address the
      same source blocks through the one addressing scheme (I4), and retrieval already
      coalesces overlapping windows into a single passage (`recall/assembly.py`), so a hinge
      retrieved through both of its chunks reads once.

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
            overlap=overlap,
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
