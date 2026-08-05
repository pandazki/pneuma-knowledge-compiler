"""Post-retrieval assembly pipeline: expand → merge/dedup(+bridge) → cap → order → render."""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.assembly import (
    Passage,
    expand_and_merge,
    order_lost_in_middle,
    render_passages,
)
from pneuma_knowledge_core.recall.rag import RecallHit

_USER = UserId("u-asm")


def _ns(source_id: str, block_texts: list[str], *, title: str, section_path=None):
    raw = RawSource(
        source_id=SourceId(source_id),
        user_id=_USER,
        kind="document",
        title=title,
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    sp = section_path or []
    blocks = [
        NormalizedBlock(index=i, text=t, section_path=list(sp))
        for i, t in enumerate(block_texts)
    ]
    structure = StructureMap(
        sections=[SectionSpan(path=list(sp), start_block=0, end_block=len(block_texts) - 1)]
        if sp
        else []
    )
    return NormalizedSource(raw=raw, blocks=blocks, structure=structure)


class FakeContent:
    def __init__(self, sources: dict[str, NormalizedSource]) -> None:
        self._sources = sources

    async def get(self, user_id, source_id):  # noqa: ANN001
        try:
            return self._sources[str(source_id)]
        except KeyError as exc:
            raise KeyError(source_id) from exc


def _hit(sid: str, start: int, end: int, text: str, score: float, paths=("lexical",)):
    return RecallHit(
        source_id=SourceId(sid),
        block_start=start,
        block_end=end,
        text=text,
        paths=tuple(paths),
        score=score,
    )


async def test_bare_block_expands_forward_to_its_own_record():
    # A bare 2-char name block [3,3] pulls in its FORWARD evaluation blocks and must NOT
    # bleed backward into the previous record (block 2).
    blocks = [f"块{i}的内容比较长一点用来撑开字符预算" * 2 for i in range(7)]
    blocks[3] = "孙羽"
    content = FakeContent({"s1": _ns("s1", blocks, title="面试记录", section_path=["候选人"])})

    passages = await expand_and_merge(
        [_hit("s1", 3, 3, "孙羽", 0.9)],
        content=content,
        user_id=_USER,
        forward_blocks=1,
        forward_char_budget=10_000,
    )
    assert len(passages) == 1
    p = passages[0]
    # forward_blocks=1 → anchor at 3, one block forward: [3,4]. No backward bleed into 2.
    assert (p.block_start, p.block_end) == (3, 4)
    assert p.text.startswith("孙羽")  # anchored at the hit's own block (paragraph start)
    assert blocks[4] in p.text  # forward evaluation now present
    assert blocks[2] not in p.text  # previous record NOT dragged in
    assert p.section_path == ("候选人",)
    assert p.source_title == "面试记录"


async def test_adjacent_hits_merge_into_one_passage():
    blocks = [f"block-{i}" for i in range(10)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    # Two hits whose expansions touch/near-touch → one merged passage (no radius here).
    passages = await expand_and_merge(
        [_hit("s1", 2, 2, "b2", 0.9), _hit("s1", 4, 4, "b4", 0.5)],
        content=content,
        user_id=_USER,
        forward_blocks=0,
        merge_gap_blocks=2,
    )
    assert len(passages) == 1
    p = passages[0]
    # gap between [2,2] and [4,4] is 1 block (block 3) ≤ merge_gap_blocks → bridged to [2,4].
    assert (p.block_start, p.block_end) == (2, 4)
    assert p.text == "block-2\nblock-3\nblock-4"  # bridged block 3 pulled in — continuous
    assert p.score == 0.9  # max of the merged seeds


async def test_far_hits_do_not_merge():
    blocks = [f"b{i}" for i in range(12)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    passages = await expand_and_merge(
        [_hit("s1", 1, 1, "b1", 0.9), _hit("s1", 9, 9, "b9", 0.8)],
        content=content,
        user_id=_USER,
        forward_blocks=0,
        merge_gap_blocks=2,
    )
    assert len(passages) == 2  # gap of 7 blocks → stays separate


async def test_per_source_cap_enforced():
    blocks = [f"b{i}" for i in range(30)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    hits = [_hit("s1", i, i, f"b{i}", score=1.0 - i / 100) for i in range(0, 30, 5)]
    passages = await expand_and_merge(
        hits,
        content=content,
        user_id=_USER,
        forward_blocks=0,
        merge_gap_blocks=0,
        per_source_cap=3,
    )
    assert len(passages) == 3  # one source can't flood the context
    # highest-score-first survive.
    assert [p.block_start for p in passages] == [0, 5, 10]


async def test_char_budget_bounds_expansion_and_max_passage_chars_truncates():
    big = "字" * 500
    blocks = [big for _ in range(9)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    passages = await expand_and_merge(
        [_hit("s1", 4, 4, big, 0.9)],
        content=content,
        user_id=_USER,
        forward_blocks=5,
        forward_char_budget=400,  # one 500-char block forward crosses the budget → stop
        max_passage_chars=600,
    )
    p = passages[0]
    # forward adds exactly one block before hitting the 400-char budget → [4,5]. No backward.
    assert (p.block_start, p.block_end) == (4, 5)
    # rendered text keeps the HEAD (records begin there) and drops the tail; the block
    # interval stays exact so deep can fetch_verbatim the rest.
    marker = prompt("recall.passage_truncated")
    assert "…(truncated;" in p.text
    assert p.text.startswith("字")  # head preserved, not middle-gutted
    assert len(p.text) <= 600 + len(marker)


async def test_missing_source_keeps_bare_hit():
    content = FakeContent({})  # source not present → KeyError → no expansion
    passages = await expand_and_merge(
        [_hit("gone", 5, 5, "bare", 0.7)],
        content=content,
        user_id=_USER,
    )
    assert len(passages) == 1
    p = passages[0]
    assert (p.block_start, p.block_end, p.text) == (5, 5, "bare")
    assert p.source_title == ""  # no title available → fallback


async def test_determinism():
    blocks = [f"b{i}" for i in range(20)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    hits = [_hit("s1", i, i, f"b{i}", score=0.5) for i in (7, 2, 14, 9)]
    a = await expand_and_merge(hits, content=content, user_id=_USER, forward_blocks=0)
    b = await expand_and_merge(list(reversed(hits)), content=content, user_id=_USER, forward_blocks=0)
    assert [(p.block_start, p.block_end) for p in a] == [(p.block_start, p.block_end) for p in b]


def _p(score: float, start: int) -> Passage:
    return Passage(
        source_id=SourceId("s"),
        block_start=start,
        block_end=start,
        text=f"t{start}",
        paths=("lexical",),
        score=score,
    )


def test_order_lost_in_middle_strongest_at_head_and_tail():
    # sorted by score desc: ranks 1..5.
    ranked = [_p(1.0, 1), _p(0.9, 2), _p(0.8, 3), _p(0.7, 4), _p(0.6, 5)]
    ordered = order_lost_in_middle(ranked)
    scores = [p.score for p in ordered]
    # strongest at head, 2nd strongest at tail, weakest sinks to the middle.
    assert scores[0] == 1.0
    assert scores[-1] == 0.9
    assert min(scores) == scores[len(scores) // 2]
    assert scores == [1.0, 0.8, 0.6, 0.7, 0.9]


def test_render_passages_carries_readable_provenance_header():
    p = Passage(
        source_id=SourceId("abcdef1234"),
        block_start=2,
        block_end=4,
        text="正文内容",
        paths=("lexical",),
        score=0.9,
        section_path=("候选人", "孙羽"),
        source_title="面试记录",
    )
    out = render_passages([p], header="原文摘录")
    assert "# 原文摘录" in out
    # fixed English [cite: …] marker carries the FULL resolvable source_id; the human title
    # + section breadcrumb ride AFTER it as readable context, outside the extractable marker.
    assert "[cite: abcdef1234 ¶2-4]" in out
    assert "面试记录 · 候选人 › 孙羽" in out
    assert "正文内容" in out


def test_render_passages_marker_has_full_source_id_even_without_title():
    p = Passage(
        source_id=SourceId("abcdef1234"),
        block_start=1,
        block_end=1,
        text="x",
        paths=("lexical",),
        score=0.1,
    )
    out = render_passages([p], header="")
    # full source_id in the marker (never truncated), no readable context when no title.
    assert "[cite: abcdef1234 ¶1-1]" in out
    assert not out.startswith("#")  # empty header → no title line


async def test_assemble_windows_assembly_override_passthrough():
    """`assemble_windows(assembly=...)` forwards overrides to `expand_and_merge` verbatim:
    None keeps today's behavior byte-for-byte, an override lifts exactly the named cap, and
    an unknown key fails loudly instead of silently doing nothing (measurement plumbing —
    a typo'd sweep knob must not masquerade as a null result)."""
    import pytest

    from pneuma_knowledge_core.recall.fast import assemble_windows

    blocks = [f"b{i}" for i in range(30)]
    content = FakeContent({"s1": _ns("s1", blocks, title="doc")})
    hits = [_hit("s1", i, i, f"b{i}", score=1.0 - i / 100) for i in range(0, 30, 5)]

    # No expansion/merge in play → the default per_source_cap=3 is what binds.
    capped = await assemble_windows(
        hits,
        content=content,
        user_id=_USER,
        assembly={"forward_blocks": 0, "merge_gap_blocks": 0},
    )
    assert len(capped) == 3

    # Same call + per_source_cap=6 → all six far-apart hits survive.
    raised = await assemble_windows(
        hits,
        content=content,
        user_id=_USER,
        assembly={"forward_blocks": 0, "merge_gap_blocks": 0, "per_source_cap": 6},
    )
    assert len(raised) == 6

    # assembly=None is byte-for-byte the no-argument call (the product default path).
    default = await assemble_windows(hits, content=content, user_id=_USER)
    explicit_none = await assemble_windows(hits, content=content, user_id=_USER, assembly=None)
    assert [
        (p.source_id, p.block_start, p.block_end, p.text) for p in default
    ] == [(p.source_id, p.block_start, p.block_end, p.text) for p in explicit_none]

    with pytest.raises(TypeError):
        await assemble_windows(
            hits, content=content, user_id=_USER, assembly={"per_source_caps": 6}
        )
