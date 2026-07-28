"""L2 chunking (chonkie-backed, section-bounded, dual char/block addressing)."""

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock, SectionSpan, StructureMap
from pneuma_knowledge_core.ingest.chunking import build_chunker, chunk_source, join_blocks

SID = SourceId("s1")

# A CJK sentence unit (~16 chars, ends with 。 so the CJK-aware delimiter splits it).
SENT = "记录显示候选人在这个项目里表现优异。"


def _blocks(texts: list[str]) -> list[NormalizedBlock]:
    return [NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)]


def _global(blocks: list[NormalizedBlock]) -> str:
    text, _ = join_blocks(blocks)
    return text


async def test_chunk_char_span_round_trips_to_the_block_joined_string():
    # Every chunk's char span is an exact slice of the source-global joined string (I4).
    blocks = _blocks([SENT * 6, SENT * 6, SENT * 6])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=2)]
    )
    g = _global(blocks)
    chunker = build_chunker(chunk_size=80, chunk_overlap=20)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    assert chunks
    for c in chunks:
        assert g[c.char_start : c.char_end] == c.text


async def test_chunks_never_cross_a_section_boundary():
    # Each section is chunked independently, so no chunk's covering blocks span two
    # sections. Blocks are long enough that a naive packer might have merged them.
    blocks = _blocks([SENT * 5, SENT * 5, SENT * 5, SENT * 5])
    structure = StructureMap(
        sections=[
            SectionSpan(path=["A"], start_block=0, end_block=1),
            SectionSpan(path=["B"], start_block=2, end_block=3),
        ]
    )
    chunker = build_chunker(chunk_size=200, chunk_overlap=40)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    for c in chunks:
        in_a = c.block_start >= 0 and c.block_end <= 1
        in_b = c.block_start >= 2 and c.block_end <= 3
        assert in_a or in_b, (c.block_start, c.block_end)


async def test_oversized_single_block_splits_into_distinct_char_chunks():
    # One block far larger than chunk_size → several chunks, all covering the SAME single
    # block, distinguished by (char_start, char_end). This is the collision the char span
    # fixes: block-only addressing would make them identical.
    blocks = _blocks([SENT * 30])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=0)]
    )
    chunker = build_chunker(chunk_size=80, chunk_overlap=20)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    assert len(chunks) > 1
    assert all((c.block_start, c.block_end) == (0, 0) for c in chunks)
    spans = {(c.char_start, c.char_end) for c in chunks}
    assert len(spans) == len(chunks)  # every char span distinct


async def test_adjacent_chunks_overlap_in_char_range_and_text():
    # chunk_overlap>0 → each chunk (bar the first) starts before the previous ends, and
    # they share overlapping text — directly the "no overlap" gap being closed.
    blocks = _blocks([SENT * 30])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=0)]
    )
    chunker = build_chunker(chunk_size=80, chunk_overlap=20)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start < a.char_end  # char ranges overlap
        # The overlap region is shared text present in both chunks.
        overlap = _global(blocks)[b.char_start : a.char_end]
        assert overlap and overlap in a.text and overlap in b.text


async def test_no_overlap_when_overlap_zero():
    blocks = _blocks([SENT * 30])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=0)]
    )
    chunker = build_chunker(chunk_size=80, chunk_overlap=0)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start >= a.char_end  # contiguous, no overlap


async def test_covering_block_interval_actually_covers_the_char_span():
    # For every chunk, the covering blocks' char ranges enclose the chunk's char span.
    blocks = _blocks([SENT * 4, SENT * 4, SENT * 4, SENT * 4])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=3)]
    )
    _, ranges = join_blocks(blocks)
    chunker = build_chunker(chunk_size=120, chunk_overlap=30)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    for c in chunks:
        cover_lo = ranges[c.block_start][0]
        cover_hi = ranges[c.block_end][1]
        assert cover_lo <= c.char_start
        assert c.char_end <= cover_hi


async def test_every_block_is_covered_by_some_chunk():
    # I4: no block is dropped from L2 — the union of covering intervals hits every block.
    blocks = _blocks([SENT * 3, SENT * 7, SENT * 2])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=2)]
    )
    chunker = build_chunker(chunk_size=90, chunk_overlap=20)
    chunks = await chunk_source(SID, blocks, structure, chunker=chunker)
    covered = {i for c in chunks for i in range(c.block_start, c.block_end + 1)}
    assert covered == {0, 1, 2}


async def test_no_structure_treats_all_blocks_as_one_implicit_section():
    blocks = _blocks([SENT, SENT, SENT])
    chunker = build_chunker(chunk_size=800, chunk_overlap=100)
    chunks = await chunk_source(SID, blocks, StructureMap(), chunker=chunker)
    assert chunks
    covered = {i for c in chunks for i in range(c.block_start, c.block_end + 1)}
    assert covered == {0, 1, 2}


async def test_determinism_same_input_same_chunks():
    blocks = _blocks([SENT * 10, SENT * 10])
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=1)]
    )
    a = await chunk_source(SID, blocks, structure, chunker=build_chunker(chunk_size=80, chunk_overlap=20))
    b = await chunk_source(SID, blocks, structure, chunker=build_chunker(chunk_size=80, chunk_overlap=20))
    assert a == b


async def test_empty_blocks_yield_no_chunks():
    assert await chunk_source(SID, [], StructureMap()) == []
