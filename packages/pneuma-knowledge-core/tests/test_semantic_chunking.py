"""L2 semantic chunking (LLM boundary detection, char/block provenance, section clip).

Fully keyless — a fake model whose `.with_structured_output(Segments)` returns fixed
segment starts stands in for the configured model (mirrors test_persona_generate). Asserts the boundary
philosophy end-to-end: one chunk per coherent unit, exact I4 provenance, section clipping,
over-long sub-splitting, windowing, determinism, and boundary repair.
"""

from __future__ import annotations

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock, SectionSpan, StructureMap
from pneuma_knowledge_core.ingest.chunking import build_chunker, join_blocks
from pneuma_knowledge_core.ingest.semantic import (
    Segments,
    blocks_content_digest,
    chunk_result_digest,
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


# A CJK unit ending with 。 so the sub-splitter's CJK-aware delimiter can split it.
SENT = "记录显示候选人在这个项目里表现优异。"


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
