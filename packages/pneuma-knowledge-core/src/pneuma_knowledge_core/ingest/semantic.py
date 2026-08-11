"""LLM topic/entity boundary detection for L2 chunking (chunk_strategy="semantic").

Motivation: an interview compilation has each candidate as a natural unit but NO
headings, so sentence/token chunking splits mid-candidate or merges two. This module
adopts the *boundary-detection philosophy* of nemori
(https://github.com/nemori-ai/nemori) — a topic/entity change is a boundary;
ignore filler/pleasantries; do not over-split; aim for coherent units — but NOT its
implementation: nemori rewrites content into narrative and loses provenance. Here the
LLM returns each BLOCK-INDEX boundary together with a title and factual episode description.
Those derived fields enrich the vector input only; chunk text is always a verbatim slice of
the block-joined string, so invariant I4 (dual char/block addressing) is preserved exactly
as on the chonkie path and generated prose never becomes citation evidence.

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
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, model_validator

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

# A description is an embedding aid, not a second copy of the source. These mechanical
# ceilings bound vector input and manifest growth even if a provider ignores the prompt.
MAX_EPISODE_TITLE_CHARS = 200
MAX_EPISODE_DESCRIPTION_CHARS = 1600

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

# The manifest envelope version. v2 first recorded the boundary contract; v3 adds the
# title/description produced in the same segmentation response. Older spans remain readable.
MANIFEST_VERSION = 3
_BOUNDARY_ONLY_MANIFEST_VERSION = 2


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


def encode_manifest_episodes(
    episodes: list[SemanticEpisode], *, overlap: str
) -> dict:
    """Persist one segmentation response, including its derived retrieval representation.

    The mode rides WITH the spans rather than beside them because it is a property of how
    these spans were produced, not of the deployment that reads them later: replay compares
    the recorded mode with the current one, and a mismatch re-detects. That is what makes
    `semantic_overlap` honestly a `derived_rebuild` knob — flipping it and rebuilding
    actually re-cuts, instead of replaying yesterday's layout forever."""
    return {
        "version": MANIFEST_VERSION,
        "overlap": overlap,
        "episodes": [
            {
                "title": episode.title,
                "description": episode.description,
                "start": int(episode.start),
                "end": int(episode.end),
            }
            for episode in episodes
        ],
    }


def encode_manifest_segments(
    segments: list[tuple[int, int]], *, overlap: str
) -> dict:
    """Compatibility encoder for callers that only hold spans."""
    return encode_manifest_episodes(
        [
            SemanticEpisode(title="", description="", start=start, end=end)
            for start, end in segments
        ],
        overlap=overlap,
    )


def decode_manifest_episodes(
    recorded, *, block_indices: list[int]
) -> tuple[list[SemanticEpisode], str] | None:
    """A manifest → `(episodes, boundary mode)`, preserving every legacy span.

    v3 carries episode representations. v2 and the two bare-list shapes carry boundaries
    only; they decode to episodes with empty derived text so their layout replays exactly.

    * `{"version": 3, "overlap": …, "episodes": […]}` — what is written today.
    * `{"version": 2, "overlap": …, "spans": [[s, e], …]}` — boundary-only envelope.
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
        mode = recorded.get("overlap")
        if mode not in OVERLAP_MODES:
            return None
        version = recorded.get("version")
        if version == MANIFEST_VERSION:
            raw_episodes = recorded.get("episodes")
            if not isinstance(raw_episodes, list) or not raw_episodes:
                return None
            episodes: list[SemanticEpisode] = []
            for item in raw_episodes:
                if not isinstance(item, dict):
                    return None
                try:
                    start, end = int(item["start"]), int(item["end"])
                except (KeyError, TypeError, ValueError):
                    return None
                episodes.append(
                    SemanticEpisode(
                        title=_clean_episode_text(
                            item.get("title", ""), limit=MAX_EPISODE_TITLE_CHARS
                        ),
                        description=_clean_episode_text(
                            item.get("description", ""),
                            limit=MAX_EPISODE_DESCRIPTION_CHARS,
                        ),
                        start=start,
                        end=end,
                    )
                )
            return episodes, mode
        if version != _BOUNDARY_ONLY_MANIFEST_VERSION:
            return None
        spans = _coerce_spans(recorded.get("spans"))
        if not spans:
            return None
        return (
            [
                SemanticEpisode(title="", description="", start=start, end=end)
                for start, end in spans
            ],
            mode,
        )
    if not isinstance(recorded, list) or not recorded:
        return None
    if all(isinstance(item, int) and not isinstance(item, bool) for item in recorded):
        order = list(block_indices)
        positions = sorted({order.index(i) for i in recorded if i in set(order)})
        if not positions:
            return None
        expanded = _partition_from_starts(positions, 0, len(order) - 1)
        spans = [(order[s], order[e]) for s, e in expanded]
        return (
            [
                SemanticEpisode(title="", description="", start=start, end=end)
                for start, end in spans
            ],
            OVERLAP_OFF,
        )
    spans = _coerce_spans(recorded)
    if len(spans) != len(recorded):
        return None
    mode = (
        OVERLAP_SMART
        if any(e >= s_next for (_, e), (s_next, _) in zip(spans, spans[1:]))
        else OVERLAP_OFF
    )
    return (
        [
            SemanticEpisode(title="", description="", start=start, end=end)
            for start, end in spans
        ],
        mode,
    )


def decode_manifest_segments(
    recorded, *, block_indices: list[int]
) -> tuple[list[tuple[int, int]], str] | None:
    """Compatibility view over `decode_manifest_episodes`: boundaries only."""
    decoded = decode_manifest_episodes(recorded, block_indices=block_indices)
    if decoded is None:
        return None
    episodes, mode = decoded
    return [(episode.start, episode.end) for episode in episodes], mode


@dataclass(frozen=True)
class SemanticEpisode:
    """One model-detected topic unit plus its derived retrieval representation.

    Field order is deliberate and shared with the structured-output schema and manifest:
    a person reads what the episode means before the source interval that grounds it.
    ``title`` and ``description`` are derived search aids, never source or citation text.
    """

    title: str
    description: str
    start: int
    end: int


class SegmentStart(BaseModel):
    """One zero-overlap episode; its end is implied by the next start."""

    title: str = ""
    description: str = ""
    start: int


class Segments(BaseModel):
    """The zero-overlap structured output: episode representations plus start blocks."""

    segments: list[SegmentStart] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_integer_tests(cls, value):  # noqa: ANN001
        """Keep old recorded/fake starts constructible; the model schema remains objects."""
        if isinstance(value, dict) and isinstance(value.get("segments"), list):
            value = dict(value)
            value["segments"] = [
                {"start": item} if isinstance(item, int) and not isinstance(item, bool) else item
                for item in value["segments"]
            ]
        return value


class SegmentSpan(BaseModel):
    """One smart-overlap episode with an explicit closed source interval."""

    title: str = ""
    description: str = ""
    start: int
    end: int


class SegmentSpans(BaseModel):
    """The `semantic_overlap="smart"` structured-output contract: CLOSED block intervals.

    The extra boundary freedom over `Segments` is exactly one degree — a segment may end
    after the next one starts, so a hinge block is read as both close and opening. The title
    and description remain derived retrieval text; every boundary rule is still enforced by
    `overlap_rejection`, not trusted to prose."""

    segments: list[SegmentSpan] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_pair_tests(cls, value):  # noqa: ANN001
        """Keep old pair-shaped fakes constructible without exposing a union to the model."""
        if isinstance(value, dict) and isinstance(value.get("segments"), list):
            value = dict(value)
            converted = []
            for item in value["segments"]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    converted.append({"start": item[0], "end": item[1]})
                else:
                    converted.append(item)
            value["segments"] = converted
        return value


# Byte-stable, volatile-free rubric (I5 / prompt-cache discipline), resolved from the prompt
# catalog. Encodes the nemori-derived boundary philosophy. No block content here — the
# numbered blocks ride the Human turn.


def _number_blocks(
    window: list[NormalizedBlock], offset: int, *, use_block_indices: bool = False
) -> str:
    """`<lineno>:<preview>` listing over a window (grep -n / git grep convention — the
    standard way to express line numbers, not an invented `#N` format). The number before
    the colon is the block's global position; that is exactly what the model returns."""
    lines: list[str] = []
    for local, b in enumerate(window):
        pos = b.index if use_block_indices else offset + local
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


def _clean_episode_text(value, *, limit: int) -> str:  # noqa: ANN001
    """Normalize one model-written retrieval field without making it source evidence."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _episode_fields(item) -> tuple[str, str]:  # noqa: ANN001
    return (
        _clean_episode_text(
            getattr(item, "title", ""), limit=MAX_EPISODE_TITLE_CHARS
        ),
        _clean_episode_text(
            getattr(item, "description", ""),
            limit=MAX_EPISODE_DESCRIPTION_CHARS,
        ),
    )


def _source_context_section(lines: list[str] | None) -> str:
    cleaned = [" ".join(line.split()) for line in (lines or []) if line.strip()]
    if not cleaned:
        return ""
    return prompt("ingest.semantic.source_context", context="\n".join(cleaned))


async def _ask_structured(
    model: BaseChatModel,
    schema: type,
    messages: list,
    *,
    callbacks: list | None,
    trace_metadata: dict | None,
    attempts: int = 2,
    operation: str = "chunk.semantic",
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
    sentence-sub-split downstream at the deployment's chunk-size ceiling. Coarser chunking for one
    window, instead of a source that never gets indexed at all."""
    structured = model.with_structured_output(schema)
    config = invoke_config(operation, callbacks, trace_metadata)
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
    source_context: list[str] | None,
) -> dict[int, tuple[str, str]]:
    """Ask for episode starts plus retrieval descriptions within one window.

    Positions are global (offset..offset+len-1). Out-of-window / non-int starts are
    dropped here; ascending/dedup/ensure-0 is finished by `semantic_episodes`."""
    listing = _number_blocks(window, offset)
    lo, hi = offset, offset + len(window) - 1
    human = prompt(
        "ingest.semantic.human",
        lo=lo,
        hi=hi,
        count=len(window),
        listing=listing,
        source_context=_source_context_section(source_context),
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
    starts: dict[int, tuple[str, str]] = {}
    for seg in getattr(result, "segments", []) or []:
        try:
            s = int(getattr(seg, "start", seg))
        except (TypeError, ValueError):
            continue
        if lo <= s <= hi:
            title, description = _episode_fields(seg)
            previous = starts.get(s, ("", ""))
            starts[s] = (title or previous[0], description or previous[1])
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
        if hasattr(item, "start") and hasattr(item, "end"):
            pair = [getattr(item, "start"), getattr(item, "end")]
        else:
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
    source_context: list[str] | None,
) -> list[SemanticEpisode]:
    """Ask for closed episode intervals and descriptions; gate them, or degrade.

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
        source_context=_source_context_section(source_context),
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
    items = getattr(result, "segments", []) or []
    spans = _coerce_spans(items)
    fields_by_start: dict[int, tuple[str, str]] = {}
    for item in items:
        try:
            raw_start = (
                getattr(item, "start")
                if hasattr(item, "start")
                else item[0]
            )
            start = int(raw_start)
        except (TypeError, ValueError, IndexError):
            continue
        title, description = _episode_fields(item)
        fields_by_start[start] = (title, description)
    if overlap_rejection(spans, lo, hi):
        spans = _partition_from_starts((s for s, _ in spans), lo, hi)
    return [
        SemanticEpisode(
            title=fields_by_start.get(start, ("", ""))[0],
            description=fields_by_start.get(start, ("", ""))[1],
            start=start,
            end=end,
        )
        for start, end in spans
    ]


async def semantic_episodes(
    blocks: list[NormalizedBlock],
    *,
    model: BaseChatModel,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
    overlap: str = OVERLAP_OFF,
    source_context: list[str] | None = None,
) -> list[SemanticEpisode]:
    """One LLM pass → grounded episode representations covering ALL blocks.

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

    The returned episodes are in REAL block-index space (mapped from ordered positions).
    Their title/description are derived retrieval text; source chunks remain verbatim.
    """
    if overlap not in OVERLAP_MODES:
        raise ValueError(f"unknown semantic_overlap mode {overlap!r}; expected one of {OVERLAP_MODES}")
    ordered = sorted(blocks, key=lambda b: b.index)
    n = len(ordered)
    if n == 0:
        return []
    idx = [b.index for b in ordered]

    if overlap == OVERLAP_SMART:
        episodes: list[SemanticEpisode] = []
        for w_start in range(0, n, max_blocks_per_call):
            w_end = min(w_start + max_blocks_per_call, n)  # exclusive
            episodes.extend(
                await _segment_window_spans(
                    ordered[w_start:w_end],
                    w_start,
                    model=model,
                    callbacks=callbacks,
                    trace_metadata=trace_metadata,
                    source_context=source_context,
                )
            )
        return [
            SemanticEpisode(
                title=episode.title,
                description=episode.description,
                start=idx[episode.start],
                end=idx[episode.end],
            )
            for episode in episodes
        ]

    # position 0 is always a boundary (first must be 0). The empty representation is
    # replaced by the model's value when it correctly returns the first episode.
    starts: dict[int, tuple[str, str]] = {0: ("", "")}
    for w_start in range(0, n, max_blocks_per_call):
        w_end = min(w_start + max_blocks_per_call, n)  # exclusive
        window = ordered[w_start:w_end]
        detected = await _segment_window_starts(
            window,
            w_start,
            model=model,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
            source_context=source_context,
        )
        for start, fields in detected.items():
            previous = starts.get(start, ("", ""))
            starts[start] = (fields[0] or previous[0], fields[1] or previous[1])

    return [
        SemanticEpisode(
            title=starts.get(position, ("", ""))[0],
            description=starts.get(position, ("", ""))[1],
            start=idx[position],
            end=idx[end],
        )
        for position, end in _partition_from_starts(starts, 0, n - 1)
    ]


async def semantic_segments(
    blocks: list[NormalizedBlock],
    *,
    model: BaseChatModel,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
    overlap: str = OVERLAP_OFF,
    source_context: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Compatibility view over `semantic_episodes`: return only grounded block spans."""
    episodes = await semantic_episodes(
        blocks,
        model=model,
        callbacks=callbacks,
        trace_metadata=trace_metadata,
        max_blocks_per_call=max_blocks_per_call,
        overlap=overlap,
        source_context=source_context,
    )
    return [(episode.start, episode.end) for episode in episodes]


async def describe_semantic_episodes(
    blocks: list[NormalizedBlock],
    episodes: list[SemanticEpisode],
    *,
    model: BaseChatModel,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    source_context: list[str] | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
) -> list[SemanticEpisode]:
    """Add retrieval text to fixed legacy boundaries without permitting re-segmentation.

    New sources get boundaries and descriptions in one call through `semantic_episodes`.
    This compatibility path exists only for boundary-only manifests. It batches fixed
    episodes while keeping a hard source-block budget; a provider reply contributes text
    only when its `(start, end)` exactly matches a recorded pair. Any changed or omitted
    coordinate leaves that episode's representation empty and its boundary untouched.
    """
    if not episodes:
        return []
    ordered_blocks = sorted(blocks, key=lambda block: block.index)
    by_index = {block.index: block for block in ordered_blocks}
    upgraded = list(episodes)

    groups: list[list[int]] = []
    current: list[int] = []
    current_blocks: set[int] = set()
    for position, episode in enumerate(episodes):
        covered = {
            index
            for index in by_index
            if episode.start <= index <= episode.end
        }
        # A legacy episode wider than the normal segmentation window is left verbatim-only:
        # silently truncating it would invite a confident but incomplete description.
        if len(covered) > max_blocks_per_call:
            if current:
                groups.append(current)
                current, current_blocks = [], set()
            continue
        if current and len(current_blocks | covered) > max_blocks_per_call:
            groups.append(current)
            current, current_blocks = [], set()
        current.append(position)
        current_blocks |= covered
    if current:
        groups.append(current)

    for positions in groups:
        fixed = [episodes[position] for position in positions]
        wanted = {(episode.start, episode.end) for episode in fixed}
        selected = [
            block
            for block in ordered_blocks
            if any(ep.start <= block.index <= ep.end for ep in fixed)
        ]
        listing = _number_blocks(selected, 0, use_block_indices=True)
        boundaries = "\n".join(
            f"- start={episode.start}, end={episode.end}" for episode in fixed
        )
        human = prompt(
            "ingest.semantic.describe_human",
            source_context=_source_context_section(source_context),
            boundaries=boundaries,
            listing=listing,
        )
        result = await _ask_structured(
            model,
            SegmentSpans,
            [
                SystemMessage(content=prompt("ingest.semantic.describe_rubric")),
                HumanMessage(content=human),
            ],
            callbacks=callbacks,
            trace_metadata=trace_metadata,
            operation="chunk.semantic.describe",
        )
        returned: dict[tuple[int, int], tuple[str, str]] = {}
        for item in getattr(result, "segments", []) or []:
            try:
                span = (int(getattr(item, "start")), int(getattr(item, "end")))
            except (AttributeError, TypeError, ValueError):
                continue
            if span in wanted:
                returned[span] = _episode_fields(item)
        for position in positions:
            episode = episodes[position]
            title, description = returned.get(
                (episode.start, episode.end),
                (episode.title, episode.description),
            )
            upgraded[position] = SemanticEpisode(
                title=title,
                description=description,
                start=episode.start,
                end=episode.end,
            )
    return upgraded


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
    episodes: list[SemanticEpisode] | None = None,
    sub_chunker=None,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
    overlap: str = OVERLAP_OFF,
    source_context: list[str] | None = None,
) -> list[Chunk]:
    """One Chunk per coherent unit, with exact char/block provenance (I4).

    - Episodes come from one `semantic_episodes` call: the model returns each boundary plus
      a search-oriented title and factual description. A manifest replay supplies recorded
      `episodes` and skips the LLM entirely; legacy callers may still supply bare `segments`.
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

    if episodes is not None and segments is not None:
        raise ValueError("pass either `episodes` or legacy `segments`, not both")
    if episodes is None and segments is not None:
        episodes = [
            SemanticEpisode(title="", description="", start=start, end=end)
            for start, end in segments
        ]
    if episodes is None:
        if model is None:
            raise ValueError(
                "semantic_chunk_source needs precomputed `episodes`/`segments` "
                "(manifest replay) or a `model` to detect them"
            )
        episodes = await semantic_episodes(
            blocks,
            model=model,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
            max_blocks_per_call=max_blocks_per_call,
            overlap=overlap,
            source_context=source_context,
        )
    sections = _effective_sections(block_indices, structure)
    intervals = _refine_by_sections(
        block_indices,
        [(episode.start, episode.end) for episode in episodes],
        sections,
    )

    def representation_for(start: int, end: int) -> tuple[str, str]:
        # Exact-start wins in an overlap hinge; containment is the section/sub-split path.
        candidates = [
            episode
            for episode in episodes
            if episode.start <= start and end <= episode.end
        ]
        if not candidates:
            return "", ""
        episode = next(
            (candidate for candidate in candidates if candidate.start == start),
            candidates[0],
        )
        return episode.title, episode.description

    chunks: list[Chunk] = []
    for seg_start, seg_end in intervals:
        episode_title, episode_description = representation_for(seg_start, seg_end)
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
                        episode_title=episode_title,
                        episode_description=episode_description,
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
                    episode_title=episode_title,
                    episode_description=episode_description,
                )
            )
    return enforce_max_chars(chunks, ranges)
