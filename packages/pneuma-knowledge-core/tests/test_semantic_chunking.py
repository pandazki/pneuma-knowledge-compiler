"""L2 semantic chunking (LLM boundary detection, char/block provenance, section clip).

Fully keyless — a fake model whose `.with_structured_output(Segments)` returns fixed
segment starts stands in for the configured model (mirrors test_persona_generate). Asserts the boundary
philosophy end-to-end: one chunk per coherent unit, exact I4 provenance, section clipping,
over-long sub-splitting, windowing, determinism, and boundary repair.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock, SectionSpan, StructureMap
from pneuma_knowledge_core.ingest.chunking import build_chunker, join_blocks
from pneuma_knowledge_core.ingest.semantic import (
    MANIFEST_VERSION,
    MAX_OVERLAP_BLOCKS,
    SemanticEpisode,
    Segments,
    SegmentSpans,
    blocks_content_digest,
    chunk_result_digest,
    decode_manifest_segments,
    decode_manifest_episodes,
    describe_semantic_episodes,
    encode_manifest_episodes,
    encode_manifest_segments,
    overlap_rejection,
    semantic_chunk_source,
    semantic_segments,
)

SID = SourceId("s1")


def _blocks(texts: list[str]) -> list[NormalizedBlock]:
    return [NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)]


def _global(blocks: list[NormalizedBlock]) -> str:
    text, _ = join_blocks(blocks)
    return text


class _FakeStructured:
    """The runnable `with_structured_output` returns: yields fixed segment starts and
    records every invoke (messages + config) so windowing/config can be asserted."""

    def __init__(self, starts: list[int]) -> None:
        self._starts = starts
        self.calls: list[tuple] = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls.append((messages, config))
        return Segments(segments=list(self._starts))


class _FakeModel:
    """A BaseChatModel stand-in returning the SAME fixed starts on every window call;
    per-window clamping in `semantic_segments` filters them to the window range."""

    def __init__(self, starts: list[int]) -> None:
        self._starts = starts
        self.schema = None
        self.structured = _FakeStructured(starts)

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schema = schema
        return self.structured


class _EpisodeStructured:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls.append((messages, config))
        return SimpleNamespace(
            segments=[
                SimpleNamespace(
                    start=0,
                    title="Weekend kayaking and safety planning",
                    description=(
                        "Caroline discussed a weekend kayaking trip and the safety "
                        "equipment she planned to bring."
                    ),
                )
            ]
        )


class _EpisodeModel:
    def __init__(self) -> None:
        self.schema = None
        self.structured = _EpisodeStructured()

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schema = schema
        return self.structured


# A CJK unit ending with 。 so the sub-splitter's CJK-aware delimiter can split it.
SENT = "记录显示候选人在这个项目里表现优异。"


async def test_one_structured_pass_adds_episode_representation_without_rewriting_source():
    blocks = _blocks(
        [
            "Caroline said she planned to go kayaking this weekend.",
            "Melanie reminded Caroline to bring a life jacket.",
        ]
    )
    model = _EpisodeModel()

    chunks = await semantic_chunk_source(
        SID,
        blocks,
        StructureMap(),
        model=model,
        source_context=["[source occurred_on] 2023-08-12"],
    )

    assert len(model.structured.calls) == 1
    assert len(chunks) == 1
    assert chunks[0].text == "\n".join(block.text for block in blocks)
    assert chunks[0].episode_title == "Weekend kayaking and safety planning"
    assert "safety equipment" in chunks[0].episode_description


async def test_episode_schema_and_prompt_put_meaning_before_grounding_coordinates():
    blocks = _blocks(["Caroline went kayaking yesterday."])
    model = _EpisodeModel()

    await semantic_chunk_source(
        SID,
        blocks,
        StructureMap(),
        model=model,
        source_context=["[source occurred_on] 2023-08-12"],
    )

    item_schema = model.schema.model_json_schema()["$defs"]["SegmentStart"]
    assert list(item_schema["properties"]) == ["title", "description", "start"]
    span_schema = SegmentSpans.model_json_schema()["$defs"]["SegmentSpan"]
    assert list(span_schema["properties"]) == [
        "title",
        "description",
        "start",
        "end",
    ]
    messages, _ = model.structured.calls[0]
    assert "detailed factual record" in messages[0].content
    assert "third-person narrative" in messages[0].content
    assert "relative" in messages[0].content
    assert "[source occurred_on] 2023-08-12" in messages[1].content


async def test_one_chunk_per_segment_headingless_multi_entity():
    # Three candidates, no headings; the LLM reports a boundary at each → one chunk each.
    blocks = _blocks(["候选人甲的完整评价", "甲的续评", "候选人乙的完整评价", "候选人丙的完整评价"])
    model = _FakeModel([0, 2, 3])  # segments: [0-1], [2], [3]
    chunks = await semantic_chunk_source(SID, blocks, StructureMap(), model=model)
    assert model.schema is Segments
    assert len(chunks) == 3
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 1), (2, 2), (3, 3)]


async def test_segments_cover_all_blocks_no_gaps_or_overlaps():
    blocks = _blocks([SENT, SENT, SENT, SENT, SENT])
    model = _FakeModel([0, 2, 4])
    chunks = await semantic_chunk_source(SID, blocks, StructureMap(), model=model)
    covered = [i for c in chunks for i in range(c.block_start, c.block_end + 1)]
    assert covered == [0, 1, 2, 3, 4]  # every block once, ascending — no gap, no overlap


async def test_char_and_block_provenance_is_exact():
    # I4: each chunk text is a verbatim slice of the block-joined string, and its covering
    # block interval encloses its char span.
    blocks = _blocks(["甲" * 20, "乙" * 20, "丙" * 20, "丁" * 20])
    _, ranges = join_blocks(blocks)
    g = _global(blocks)
    model = _FakeModel([0, 1, 3])
    chunks = await semantic_chunk_source(SID, blocks, StructureMap(), model=model)
    for c in chunks:
        assert g[c.char_start : c.char_end] == c.text
        assert ranges[c.block_start][0] <= c.char_start
        assert c.char_end <= ranges[c.block_end][1]


async def test_over_long_segment_is_sentence_sub_split():
    # One coherent unit far larger than max_chunk_chars → several sub-chunks over that one
    # segment; the short units stay one chunk each.
    big = SENT * 60
    blocks = _blocks([big, "候选人乙短评。", "候选人丙短评。"])
    model = _FakeModel([0, 1, 2])
    sub = build_chunker("sentence", chunk_size=80, chunk_overlap=20)
    chunks = await semantic_chunk_source(
        SID, blocks, StructureMap(), model=model, sub_chunker=sub, max_chunk_chars=200
    )
    from_block0 = [c for c in chunks if c.block_start == 0]
    from_block1 = [c for c in chunks if (c.block_start, c.block_end) == (1, 1)]
    assert len(from_block0) > 1  # the huge unit was sub-split
    assert len(from_block1) == 1  # the short unit stayed whole
    g = _global(blocks)
    for c in chunks:  # provenance still exact after sub-splitting
        assert g[c.char_start : c.char_end] == c.text


async def test_over_long_without_sub_chunker_stays_one_chunk():
    # No sub_chunker → the over-long unit is kept whole rather than dropped.
    blocks = _blocks([SENT * 60, "短评。"])
    model = _FakeModel([0, 1])
    chunks = await semantic_chunk_source(
        SID, blocks, StructureMap(), model=model, max_chunk_chars=200
    )
    assert len(chunks) == 2


async def test_section_boundaries_are_respected():
    # The LLM reports ONE segment over everything, but the doc has two sections → the
    # segment is clipped at the section boundary, so no chunk crosses it.
    blocks = _blocks([SENT, SENT, SENT, SENT])
    structure = StructureMap(
        sections=[
            SectionSpan(path=["A"], start_block=0, end_block=1),
            SectionSpan(path=["B"], start_block=2, end_block=3),
        ]
    )
    model = _FakeModel([0])  # one giant segment
    chunks = await semantic_chunk_source(SID, blocks, structure, model=model)
    for c in chunks:
        in_a = c.block_start >= 0 and c.block_end <= 1
        in_b = c.block_start >= 2 and c.block_end <= 3
        assert in_a or in_b, (c.block_start, c.block_end)
    # And it did split at the section boundary (2 chunks), not merge across it.
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 1), (2, 3)]


async def test_determinism_same_model_output_same_chunks():
    blocks = _blocks([SENT * 3, SENT * 3, SENT * 3])
    a = await semantic_chunk_source(SID, blocks, StructureMap(), model=_FakeModel([0, 2]))
    b = await semantic_chunk_source(SID, blocks, StructureMap(), model=_FakeModel([0, 2]))
    assert a == b


async def test_boundary_repair_coerces_insane_output():
    # Non-ascending, duplicated, out-of-range, and missing-0 → repaired to [0, 2, 5].
    blocks = _blocks([SENT] * 6)
    model = _FakeModel([5, 2, 2, 99, -1])  # note: no 0, unsorted, out of range
    segments = await semantic_segments(blocks, model=model)
    assert segments == [(0, 1), (2, 4), (5, 5)]
    chunks = await semantic_chunk_source(SID, blocks, StructureMap(), model=model)
    covered = [i for c in chunks for i in range(c.block_start, c.block_end + 1)]
    assert covered == [0, 1, 2, 3, 4, 5]  # still a clean partition


async def test_large_doc_windowing_carries_across_boundary():
    # 6 blocks, window size 3 → two LLM calls; the fake returns [0, 3] each time, clamped
    # per window to {0} then {3}. Boundaries: [0-2], [3-5].
    blocks = _blocks([SENT] * 6)
    model = _FakeModel([0, 3])
    segments = await semantic_segments(blocks, model=model, max_blocks_per_call=3)
    assert segments == [(0, 2), (3, 5)]
    assert len(model.structured.calls) == 2  # two sequential windows


async def test_windowing_no_forced_split_at_window_boundary():
    # If the model reports NO start inside the second window, the open segment carries
    # across the window boundary (nemori incremental) — a single segment over all blocks.
    blocks = _blocks([SENT] * 6)
    model = _FakeModel([0])  # only the very first block is a boundary
    segments = await semantic_segments(blocks, model=model, max_blocks_per_call=3)
    assert segments == [(0, 5)]


async def test_empty_blocks_yield_no_chunks_and_no_llm_call():
    model = _FakeModel([0])
    assert await semantic_chunk_source(SID, [], StructureMap(), model=model) == []
    assert await semantic_segments([], model=model) == []
    assert model.structured.calls == []  # the LLM is never called on empty input


class _DriftModel:
    """A model whose boundary output CHANGES on every use — stands in for the real
    non-determinism (same source re-indexed gave 17 vs 19 chunks). Used to prove that
    manifest replay (passing recorded segments) makes the rebuild model-independent."""

    def __init__(self, starts_sequence: list[list[int]]) -> None:
        self._seq = starts_sequence
        self._n = 0

    def with_structured_output(self, schema):  # noqa: ANN001
        starts = self._seq[min(self._n, len(self._seq) - 1)]
        self._n += 1
        return _FakeStructured(starts)


async def test_precomputed_segments_replay_needs_no_model():
    # A manifest replay passes recorded segments and must NOT require a model at all.
    blocks = _blocks(["候选人甲评价", "甲续评", "候选人乙评价"])
    chunks = await semantic_chunk_source(
        SID, blocks, StructureMap(), segments=[(0, 1), (2, 2)]
    )
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 1), (2, 2)]


async def test_missing_both_segments_and_model_raises():
    blocks = _blocks(["a", "b"])
    try:
        await semantic_chunk_source(SID, blocks, StructureMap())
    except ValueError as e:
        assert "segments" in str(e) and "model" in str(e)
    else:
        raise AssertionError("expected ValueError when neither segments nor model given")


async def test_replay_is_byte_identical_despite_model_drift():
    # Detect once with a drifting model, record its segments, then replay them: the rebuild
    # is byte-identical even though the model would now report DIFFERENT boundaries. This is
    # the determinism the chunk manifest buys — "rebuildable" → "byte-deterministic".
    blocks = _blocks([SENT * 2, SENT * 2, SENT * 2, SENT * 2])
    drift = _DriftModel([[0, 2], [0, 1, 3]])  # first detect vs. a later drifted detect

    first = await semantic_chunk_source(SID, blocks, StructureMap(), model=drift)
    recorded = await semantic_segments(  # the segments a first ingest would have recorded
        _blocks([SENT * 2, SENT * 2, SENT * 2, SENT * 2]), model=_FakeModel([0, 2])
    )
    replayed = await semantic_chunk_source(SID, blocks, StructureMap(), segments=recorded)

    # Replay reproduces the ORIGINAL layout; a fresh detect on the drifted model would not.
    assert [(c.char_start, c.char_end) for c in replayed] == [
        (c.char_start, c.char_end) for c in first
    ]
    drifted = await semantic_chunk_source(SID, blocks, StructureMap(), model=drift)
    assert [(c.block_start, c.block_end) for c in drifted] != [
        (c.block_start, c.block_end) for c in replayed
    ]


async def test_content_digest_stable_and_content_sensitive():
    a = _blocks(["候选人甲评价", "候选人乙评价"])
    b = _blocks(["候选人甲评价", "候选人乙评价"])  # same content, different objects
    c = _blocks(["候选人甲评价", "候选人丙评价"])  # one block changed
    assert blocks_content_digest(a) == blocks_content_digest(b)  # stable
    assert blocks_content_digest(a) != blocks_content_digest(c)  # content-sensitive
    assert blocks_content_digest(a) == blocks_content_digest(list(reversed(a)))  # index-ordered


async def test_result_digest_tracks_chunk_layout():
    blocks = _blocks([SENT, SENT, SENT])
    one = await semantic_chunk_source(SID, blocks, StructureMap(), segments=[(0, 2)])
    three = await semantic_chunk_source(SID, blocks, StructureMap(), segments=[(0, 0), (1, 1), (2, 2)])
    assert chunk_result_digest(one) != chunk_result_digest(three)
    # same layout twice → same fingerprint
    again = await semantic_chunk_source(SID, blocks, StructureMap(), segments=[(0, 2)])
    assert chunk_result_digest(one) == chunk_result_digest(again)


async def test_prompt_assembly_system_rubric_and_numbered_blocks():
    from pneuma_knowledge_core.prompts import prompt
    from langchain_core.messages import HumanMessage, SystemMessage

    blocks = _blocks(["候选人甲评价", "候选人乙评价"])
    model = _FakeModel([0, 1])
    cb = object()
    await semantic_segments(
        blocks, model=model, callbacks=[cb], trace_metadata={"operation": "chunk.semantic"}
    )
    msgs, config = model.structured.calls[0]
    assert isinstance(msgs[0], SystemMessage) and msgs[0].content == prompt("ingest.semantic.rubric")
    assert isinstance(msgs[1], HumanMessage)
    # grep -n / git grep convention: `<lineno>:<content>`, not an invented `#N` format.
    assert "0:候选人甲评价" in msgs[1].content
    assert "1:候选人乙评价" in msgs[1].content
    # invoke_config wiring: run_name + injected callbacks/metadata pass through.
    assert config["run_name"] == "chunk.semantic"
    assert config["callbacks"] == [cb]
    assert config["metadata"] == {"operation": "chunk.semantic"}


# ---------------------------------------------------------------------------
# Prompt preview rendering (_number_blocks): head+tail truncation boundaries.
# The preview only shapes what the model READS; chunk text elsewhere is asserted
# to be verbatim slices of the full blocks, so these tests pin the prompt side.
# ---------------------------------------------------------------------------

from pneuma_knowledge_core.ingest.semantic import (  # noqa: E402
    _PREVIEW_HEAD_CHARS,
    _PREVIEW_TAIL_CHARS,
    _number_blocks,
)

_BUDGET = _PREVIEW_HEAD_CHARS + _PREVIEW_TAIL_CHARS


def test_preview_at_budget_is_verbatim_and_unmarked():
    text = "x" * _BUDGET  # exactly at budget: shown whole, no marker
    line = _number_blocks(_blocks([text]), 0)
    assert line == f"0:{text}"
    assert "truncated" not in line


def test_preview_one_over_budget_elides_exactly_the_middle_char():
    text = "a" * _PREVIEW_HEAD_CHARS + "M" + "b" * _PREVIEW_TAIL_CHARS
    line = _number_blocks(_blocks([text]), 0)
    head, sep, tail = line.partition(" …(1 chars truncated)… ")
    assert sep, f"expected a labeled gap in: {line[:80]}…"
    assert head == "0:" + "a" * _PREVIEW_HEAD_CHARS
    assert tail == "b" * _PREVIEW_TAIL_CHARS
    assert "M" not in head and "M" not in tail


def test_preview_head_tail_are_verbatim_slices_and_count_is_exact():
    text = "".join(chr(ord("a") + i % 26) for i in range(2000))
    omitted = 2000 - _BUDGET
    marker = f" …({omitted} chars truncated)… "
    line = _number_blocks(_blocks([text]), 0)
    assert marker in line
    head, tail = line[len("0:") :].split(marker)
    assert head == text[:_PREVIEW_HEAD_CHARS]
    assert tail == text[-_PREVIEW_TAIL_CHARS:]


def test_preview_counts_characters_not_bytes_for_cjk():
    text = "知" * (_BUDGET + 5)  # 3 bytes per char in UTF-8; count must be by char
    line = _number_blocks(_blocks([text]), 0)
    marker = " …(5 chars truncated)… "
    assert marker in line
    head, tail = line[len("0:") :].split(marker)
    assert head == "知" * _PREVIEW_HEAD_CHARS
    assert tail == "知" * _PREVIEW_TAIL_CHARS


def test_preview_measures_after_whitespace_collapse():
    # Collapse happens BEFORE measuring: raw text far over budget can still fit whole.
    raw = ("word  \n" * 90).strip()  # collapses to 90 space-joined words (449 chars)
    collapsed = " ".join(raw.split())
    assert len(collapsed) <= _BUDGET < len(raw)
    line = _number_blocks(_blocks([raw]), 0)
    assert line == f"0:{collapsed}"
    assert "truncated" not in line


def test_preview_numbering_uses_global_offset_over_windows():
    lines = _number_blocks(_blocks(["a", "b"]), 40).splitlines()
    assert lines == ["40:a", "41:b"]


# ═════════════════════════════════════════════ semantic_overlap="smart": the second contract
#
# The episode-representation addition intentionally retires the old boundary-only prompt.
# These pins establish the new one-call baseline: future edits cannot silently mix numbers
# measured with different segmentation/description instructions.

import hashlib  # noqa: E402

from pneuma_knowledge_core.prompts import chinese_overlay, default_catalog, prompt  # noqa: E402

# ────────────────────────────────────────────────── the `off` request, pinned to the byte

# sha256 of the two clauses the zero-overlap segmentation call is built from, in both packs.
# Not "the prompt still reads sensibly" — the exact bytes. Any rewording retires measurements
# made with this episode-producing baseline, and that is checkable rather than reviewable.
_OFF_PROMPT_DIGESTS = {
    "en": {
        "ingest.semantic.rubric":
            "ee56af5f99b3d8028b4b4ba71b18dc6b3ceb3a5a432924c08991ee438961b9da",
        "ingest.semantic.human":
            "6e14703eb93128ede56f322995c98ff94663cba1ebf8762c7edac327c7f0cab2",
    },
    "zh": {
        "ingest.semantic.rubric":
            "b5ec53be7247312ca3113d61bbff0971c6ca325fc8adef852c6bc28b8405e3be",
        "ingest.semantic.human":
            "3c55210d506b3606ef4e873b5c38183168829e26954b2240425df6b008e1ad47",
    },
}


def test_the_off_mode_clauses_are_byte_for_byte_the_episode_baseline():
    for pack, catalog in (("en", default_catalog()), ("zh", chinese_overlay())):
        for key, digest in _OFF_PROMPT_DIGESTS[pack].items():
            actual = hashlib.sha256(catalog[key].encode("utf-8")).hexdigest()
            assert actual == digest, (
                f"{pack} {key} changed. It is the pinned episode-producing semantic "
                "baseline — changing it retires measurements made with these bytes."
            )


async def test_the_off_mode_request_is_assembled_from_exactly_those_clauses():
    """The digests pin the wording; this pins the zero-overlap episode call assembly."""
    blocks = _blocks(["候选人甲评价", "候选人乙评价"])
    model = _FakeModel([0, 1])
    await semantic_segments(blocks, model=model)
    msgs, _ = model.structured.calls[0]
    assert model.schema is Segments
    assert len(msgs) == 2
    assert msgs[0].content == prompt("ingest.semantic.rubric")
    assert msgs[1].content == prompt(
        "ingest.semantic.human",
        lo=0,
        hi=1,
        count=2,
        listing="0:候选人甲评价\n1:候选人乙评价",
        source_context="",
    )


def test_both_rubrics_state_the_same_boundary_philosophy():
    """The two contracts differ in their output format and in nothing else. The shared half
    is one Python constant precisely so this holds; the pin is here so a later edit to one
    rubric's philosophy cannot quietly leave the other's behind."""
    for catalog in (default_catalog(), chinese_overlay()):
        base = catalog["ingest.semantic.rubric"]
        overlap = catalog["ingest.semantic.rubric_overlap"]
        shared = base.split("\n\n")[:2]  # the intro and the rules list, not the output half
        assert shared, "the rubric lost its philosophy section"
        for paragraph in shared:
            assert paragraph in overlap
        assert base != overlap


# ────────────────────────────────────────────────────── the five gates, one red test each
#
# Each red breaks exactly ONE rule and leaves the other four satisfied, so a passing suite
# means five independent refusals rather than one catch-all rejection firing five times.

VALID = [(0, 4), (3, 9)]  # the rubric's own example, over blocks 0..9


def test_a_valid_interval_list_passes_every_gate():
    assert overlap_rejection(VALID, 0, 9) == ""


def test_gate1_an_endpoint_that_is_not_a_block_in_the_listing():
    assert "block range" in overlap_rejection([(0, 4), (3, 12)], 0, 9)
    # …and its other half: an interval that ends before it starts.
    assert "ends before it starts" in overlap_rejection([(4, 0)], 0, 4)


def test_gate2_starts_that_do_not_strictly_increase():
    # 0,1,1 — every other rule holds: cover is gapless, the widest overlap is 3, the count
    # is under the block count, every endpoint is real.
    spans = [(0, 2), (1, 3), (1, 5)]
    assert "strictly increasing" in overlap_rejection(spans, 0, 5)
    # The other four hold for the same list with the third start nudged forward.
    assert overlap_rejection([(0, 2), (1, 3), (2, 5)], 0, 5) == ""


def test_gate3_a_hole_no_segment_covers():
    assert "covered by no segment" in overlap_rejection([(0, 2), (5, 9)], 0, 9)


def test_gate3_the_cover_must_reach_both_ends():
    assert "not at block 0" in overlap_rejection([(1, 9)], 0, 9)
    assert "not at block 9" in overlap_rejection([(0, 8)], 0, 9)


def test_gate4_overlap_beyond_the_bound_is_the_degeneracy_guard():
    # Neighbours sharing 5 blocks — everything else is impeccable. Unbounded, the winning
    # move is "every segment is the whole document", which is why this is a number.
    assert "over the 3 allowed" in overlap_rejection([(0, 5), (1, 9)], 0, 9)
    # Exactly at the bound is allowed: the gate refuses degeneracy, not generosity.
    assert overlap_rejection([(0, 4), (2, 9)], 0, 9) == ""
    assert MAX_OVERLAP_BLOCKS == 3


def test_gate5_more_segments_than_blocks():
    assert "3 segments over 2 blocks" in overlap_rejection([(0, 0), (1, 1), (0, 1)], 0, 1)


# ────────────────────────────────────────────────────────────── smart mode, end to end


class _FakeSpanStructured:
    def __init__(self, spans) -> None:
        self._spans = spans
        self.calls: list[tuple] = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls.append((messages, config))
        return SegmentSpans(segments=[list(p) for p in self._spans])


class _FakeSpanModel:
    """Returns the SAME fixed intervals on every window call (windows are asserted
    separately with per-window spans)."""

    def __init__(self, spans) -> None:
        self.schema = None
        self.structured = _FakeSpanStructured(spans)

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schema = schema
        return self.structured


class _FakeWindowSpanModel:
    """A different interval list per window call — how a real segmenter behaves when the
    document is longer than one prompt."""

    def __init__(self, per_call) -> None:
        self._per_call = list(per_call)
        self._n = 0
        self.structured = None

    def with_structured_output(self, schema):  # noqa: ANN001
        spans = self._per_call[min(self._n, len(self._per_call) - 1)]
        self._n += 1
        self.structured = _FakeSpanStructured(spans)
        return self.structured


async def test_smart_mode_asks_for_intervals_with_the_overlap_clauses():
    blocks = _blocks(["甲", "乙", "丙"])
    model = _FakeSpanModel([(0, 1), (1, 2)])
    await semantic_segments(blocks, model=model, overlap="smart")
    msgs, config = model.structured.calls[0]
    assert model.schema is SegmentSpans
    assert msgs[0].content == prompt("ingest.semantic.rubric_overlap")
    assert msgs[1].content == prompt(
        "ingest.semantic.human_overlap",
        lo=0,
        hi=2,
        count=3,
        listing="0:甲\n1:乙\n2:丙",
        source_context="",
    )
    assert config["run_name"] == "chunk.semantic"


async def test_smart_mode_produces_the_hinge_twice_with_verbatim_provenance():
    # The rubric's own example: ten blocks, the turn is at 3-4, so 0-4 and 3-9.
    blocks = _blocks([f"第{i}块内容。" for i in range(10)])
    model = _FakeSpanModel([(0, 4), (3, 9)])
    segments = await semantic_segments(blocks, model=model, overlap="smart")
    assert segments == [(0, 4), (3, 9)]

    chunks = await semantic_chunk_source(
        SID, blocks, StructureMap(), model=_FakeSpanModel([(0, 4), (3, 9)]), overlap="smart"
    )
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 4), (3, 9)]
    # The hinge blocks are in BOTH chunks; every other block is in exactly one.
    seen = [i for c in chunks for i in range(c.block_start, c.block_end + 1)]
    assert [i for i in range(10) if seen.count(i) == 2] == [3, 4]
    assert all(seen.count(i) == 1 for i in (0, 1, 2, 5, 6, 7, 8, 9))
    # I4 is untouched by the duplication: both chunks are verbatim slices addressed by
    # char offsets into the same block-joined string.
    g = _global(blocks)
    for c in chunks:
        assert g[c.char_start : c.char_end] == c.text


async def test_smart_mode_falls_back_to_the_partition_when_a_gate_refuses():
    # A hole at blocks 3-4: the interval list is refused whole, and the window degrades to
    # the zero-overlap partition of the starts the model did report — the overlap is lost,
    # the segmentation is not, and no block falls out of L2.
    blocks = _blocks([SENT] * 8)
    model = _FakeSpanModel([(0, 2), (5, 7)])
    segments = await semantic_segments(blocks, model=model, overlap="smart")
    assert segments == [(0, 4), (5, 7)]
    covered = [i for s, e in segments for i in range(s, e + 1)]
    assert covered == list(range(8))


async def test_smart_mode_refusal_with_nothing_usable_still_covers_everything():
    blocks = _blocks([SENT] * 4)
    model = _FakeSpanModel([])  # the model returned nothing at all
    assert await semantic_segments(blocks, model=model, overlap="smart") == [(0, 3)]


async def test_smart_mode_windows_cover_their_own_window_exactly():
    # 6 blocks, window size 3 → two calls. Each window's intervals must cover that window
    # (gate 3 judges the range the model was actually shown), so a window boundary is a
    # segment boundary in this mode — unlike `off`, where an open segment carries across.
    blocks = _blocks([SENT] * 6)
    model = _FakeWindowSpanModel([[(0, 1), (1, 2)], [(3, 4), (4, 5)]])
    segments = await semantic_segments(
        blocks, model=model, max_blocks_per_call=3, overlap="smart"
    )
    assert segments == [(0, 1), (1, 2), (3, 4), (4, 5)]


async def test_an_unknown_overlap_mode_is_refused_rather_than_guessed():
    import pytest

    with pytest.raises(ValueError, match="semantic_overlap"):
        await semantic_segments(_blocks(["a"]), model=_FakeModel([0]), overlap="fixed-2")


async def test_off_mode_is_untouched_by_the_new_contract():
    """Same blocks, same fake starts, both before and after: the partition is a partition."""
    blocks = _blocks([SENT] * 6)
    segments = await semantic_segments(blocks, model=_FakeModel([0, 2, 4]))
    assert segments == [(0, 1), (2, 3), (4, 5)]


async def test_sections_clip_overlapping_segments_without_flattening_them():
    # Two sections, and segments that straddle the boundary. No chunk may cross a section;
    # the overlap INSIDE a section must survive, because a neighbour's start falling inside
    # a segment is the hinge, not a cut.
    blocks = _blocks([SENT] * 6)
    structure = StructureMap(
        sections=[
            SectionSpan(path=["A"], start_block=0, end_block=2),
            SectionSpan(path=["B"], start_block=3, end_block=5),
        ]
    )
    chunks = await semantic_chunk_source(
        SID, blocks, structure, segments=[(0, 3), (2, 5)]
    )
    spans = [(c.block_start, c.block_end) for c in chunks]
    assert spans == [(0, 2), (3, 3), (2, 2), (3, 5)]
    for start, end in spans:
        assert (end <= 2) or (start >= 3), (start, end)  # never crosses the section
    seen = [i for s, e in spans for i in range(s, e + 1)]
    assert seen.count(2) == 2 and seen.count(3) == 2  # the overlap survived the clip


async def test_a_segment_repeated_identically_is_stored_once():
    """Overlap is two segments sharing blocks, not one segment stored twice — the second
    copy would embed the same text under the same span and buy nothing."""
    blocks = _blocks([SENT] * 3)
    chunks = await semantic_chunk_source(
        SID, blocks, StructureMap(), segments=[(0, 1), (0, 1), (2, 2)]
    )
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 1), (2, 2)]


# ─────────────────────────────────────────────────────── the versioned manifest record


async def test_the_manifest_envelope_round_trips_with_its_mode():
    segments = [(0, 4), (3, 9)]
    record = encode_manifest_segments(segments, overlap="smart")
    assert record == {
        "version": MANIFEST_VERSION,
        "overlap": "smart",
        "episodes": [
            {"title": "", "description": "", "start": 0, "end": 4},
            {"title": "", "description": "", "start": 3, "end": 9},
        ],
    }
    assert decode_manifest_segments(record, block_indices=list(range(10))) == (
        segments,
        "smart",
    )


def test_manifest_round_trips_episode_representation_in_meaning_first_order():
    episodes = [
        SemanticEpisode(
            title="Weekend kayaking and safety planning",
            description="Caroline discussed a kayaking trip and safety equipment.",
            start=3,
            end=8,
        )
    ]

    record = encode_manifest_episodes(episodes, overlap="smart")

    assert list(record["episodes"][0]) == ["title", "description", "start", "end"]
    assert decode_manifest_episodes(record, block_indices=list(range(10))) == (
        episodes,
        "smart",
    )


async def test_legacy_description_upgrade_cannot_change_recorded_boundaries():
    blocks = _blocks([SENT] * 4)
    recorded = [
        SemanticEpisode(title="", description="", start=0, end=1),
        SemanticEpisode(title="", description="", start=2, end=3),
    ]
    # The model tries to replace both fixed episodes with one broad episode. Migration must
    # ignore that span instead of silently re-segmenting the source.
    model = _FakeSpanModel([(0, 3)])

    upgraded = await describe_semantic_episodes(blocks, recorded, model=model)

    assert [(episode.start, episode.end) for episode in upgraded] == [(0, 1), (2, 3)]
    assert all(not episode.description for episode in upgraded)


async def test_a_replayed_envelope_reproduces_the_chunks_byte_for_byte():
    blocks = _blocks([SENT * 2] * 10)
    detected = await semantic_segments(
        blocks, model=_FakeSpanModel([(0, 4), (3, 9)]), overlap="smart"
    )
    first = await semantic_chunk_source(SID, blocks, StructureMap(), segments=detected)
    record = encode_manifest_segments(detected, overlap="smart")
    replayed_segments, mode = decode_manifest_segments(
        record, block_indices=[b.index for b in blocks]
    )
    replayed = await semantic_chunk_source(
        SID, blocks, StructureMap(), segments=replayed_segments
    )
    assert mode == "smart"
    assert chunk_result_digest(first) == chunk_result_digest(replayed)
    assert first == replayed


def test_a_pre_envelope_pair_list_replays_as_written():
    """The shape written before the envelope existed. Its mode is read off the data — a
    touching partition is what `off` produces, overlapping pairs are what `smart` produces —
    so a library recorded under either does not re-detect to learn what it already says."""
    idx = list(range(6))
    assert decode_manifest_segments([[0, 2], [3, 5]], block_indices=idx) == (
        [(0, 2), (3, 5)],
        "off",
    )
    assert decode_manifest_segments([[0, 3], [2, 5]], block_indices=idx) == (
        [(0, 3), (2, 5)],
        "smart",
    )


def test_a_pre_envelope_starts_only_list_expands_through_the_old_partition_rule():
    idx = [0, 1, 2, 3, 4, 5]
    assert decode_manifest_segments([0, 2, 4], block_indices=idx) == (
        [(0, 1), (2, 3), (4, 5)],
        "off",
    )
    # Non-contiguous block indexes (a source with holes) map through positions, not maths.
    sparse = [0, 3, 7, 9]
    assert decode_manifest_segments([0, 7], block_indices=sparse) == (
        [(0, 3), (7, 9)],
        "off",
    )


def test_an_unreadable_manifest_declines_to_replay_rather_than_guessing():
    idx = list(range(4))
    assert decode_manifest_segments({"version": 99, "spans": [[0, 3]]}, block_indices=idx) is None
    assert decode_manifest_segments(
        {"version": MANIFEST_VERSION, "overlap": "fixed", "spans": [[0, 3]]},
        block_indices=idx,
    ) is None
    assert decode_manifest_segments([], block_indices=idx) is None
    assert decode_manifest_segments(None, block_indices=idx) is None
    assert decode_manifest_segments([[0, 1, 2]], block_indices=idx) is None


class _UndecodableStructured:
    """`with_structured_output(...)` that raises the way a truncated tool-call payload does:
    the failure happens while DECODING the reply, before any segment reaches the gates."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise json.JSONDecodeError("Expecting value", "{\n", 2)
        return Segments(segments=[0])


class _UndecodableModel:
    def __init__(self, fail_times: int) -> None:
        self.structured = _UndecodableStructured(fail_times)

    def with_structured_output(self, schema):  # noqa: ANN001
        return self.structured


async def test_undecodable_reply_retries_once_then_degrades_instead_of_raising():
    """A reply that cannot be decoded must not kill the run.

    The window gates judge what the model SAID; a truncated tool-call payload never reaches
    them — `with_structured_output` raises while parsing. That exception used to escape the
    chunker and fail the index job permanently (nothing retries an index job), leaving the
    source unindexed for good. One retry, then this window degrades to a single segment."""
    blocks = _blocks(["one.", "two.", "three."])

    # Transient: the retry succeeds, so segmentation is the model's own.
    transient = _UndecodableModel(fail_times=1)
    assert await semantic_segments(blocks, model=transient) == [(0, 2)]
    assert transient.structured.calls == 2

    # Persistent: both attempts fail — no exception, total coverage preserved.
    persistent = _UndecodableModel(fail_times=99)
    segments = await semantic_segments(blocks, model=persistent)
    assert segments == [(0, 2)]
    assert persistent.structured.calls == 2

    # Same discipline on the smart-overlap contract.
    smart = _UndecodableModel(fail_times=99)
    assert await semantic_segments(blocks, model=smart, overlap="smart") == [(0, 2)]
    assert smart.structured.calls == 2
