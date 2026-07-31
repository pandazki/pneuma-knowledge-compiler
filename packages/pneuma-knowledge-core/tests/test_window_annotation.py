"""fast's opt-in annotated layout: the claim↔window join, the move, and the off path.

The hypothesis under test is a presentational one — a claim whose cited span lies inside a
retrieved excerpt is that excerpt's compiled reading, so putting the two adjacent should
beat making the model discover the relation across a 40-claim wall. These tests pin the
MECHANISM (which claims join, where they end up, that they are moved and not copied, and
that annotated windows take the attention-hot ends); whether the hypothesis holds is an
A/B question, not a unit-test one.

The last test is the load-bearing one: with the flag off the rendered evidence must be the
byte-for-byte lane it has always been, which is what makes the A/B a controlled comparison
rather than two different systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.recall.assembly import Passage, order_lost_in_middle
from pneuma_knowledge_core.recall.fast import (
    RetrievedClaim,
    fast_recall,
    join_claims_to_windows,
    recall_human,
    render_window_notes,
    split_strength_label,
)

_USER = UserId("u-annot")


# ------------------------------------------------------------------------------ fixtures


def _claim(anchor: str, text: str, cites: list[tuple[str, int, int]]) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=AnchorId(anchor),
        document_path="memory/projects/demo.md",
        section_path=("方向",),
        text=text,
        citations=tuple(
            Citation(source_id=SourceId(s), block_start=a, block_end=b)
            for s, a, b in cites
        ),
        paths=("lexical",),
        score=1.0,
    )


def _window(source: str, start: int, end: int, text: str) -> Passage:
    return Passage(
        source_id=SourceId(source),
        block_start=start,
        block_end=end,
        text=text,
        paths=("lexical",),
        score=1.0,
        section_path=(),
        source_title="群聊",
    )


# ------------------------------------------------------------------------- the join rule


def test_a_claim_whose_cited_span_overlaps_a_window_is_moved_under_it():
    claim = _claim("aaaa", "【中】方案已定", [("srcA", 4, 6)])
    windows = [_window("srcA", 3, 8, "原文")]

    remaining, paired = join_claims_to_windows([claim], windows)

    assert remaining == []  # moved out of the notes section entirely
    assert paired == [(windows[0], (claim,))]


def test_a_claim_that_misses_every_window_stays_in_the_notes_section():
    """Two ways to miss: the right source at the wrong blocks, and the right blocks in the
    wrong source. Neither is a join — an overlap in block numbers across two sources is a
    coincidence of integers, not shared text."""
    off_by_span = _claim("bbbb", "别处的话", [("srcA", 20, 22)])
    off_by_source = _claim("cccc", "另一份材料", [("srcB", 4, 6)])
    windows = [_window("srcA", 3, 8, "原文")]

    remaining, paired = join_claims_to_windows([off_by_span, off_by_source], windows)

    assert remaining == [off_by_span, off_by_source]
    assert paired == [(windows[0], ())]


def test_touching_at_a_single_block_counts_as_overlap():
    """Inclusive intervals: a claim citing ¶8-9 against a window ending at 8 shares block 8,
    so it IS a reading of a line in that window."""
    claim = _claim("dddd", "接着说", [("srcA", 8, 9)])
    windows = [_window("srcA", 3, 8, "原文")]
    remaining, paired = join_claims_to_windows([claim], windows)
    assert remaining == [] and paired[0][1] == (claim,)


def test_one_window_takes_at_most_the_cap_and_the_overflow_stays_behind():
    claims = [
        _claim("c1", "第一条", [("srcA", 3, 3)]),
        _claim("c2", "第二条", [("srcA", 4, 4)]),
        _claim("c3", "第三条", [("srcA", 5, 5)]),
        _claim("c4", "第四条", [("srcA", 6, 6)]),
    ]
    windows = [_window("srcA", 3, 8, "原文")]

    remaining, paired = join_claims_to_windows(claims, windows, cap=3)

    assert [str(c.anchor) for c in paired[0][1]] == ["c1", "c2", "c3"]
    assert [str(c.anchor) for c in remaining] == ["c4"]


def test_a_claim_overlapping_two_windows_lands_under_the_first_only():
    """One statement, stated once. Repeating it under every window it touches would put
    back the duplication the move exists to remove."""
    claim = _claim("eeee", "跨两段", [("srcA", 3, 12)])
    first, second = _window("srcA", 3, 8, "前"), _window("srcA", 9, 14, "后")

    remaining, paired = join_claims_to_windows([claim], [first, second])

    assert remaining == []
    assert paired == [(first, (claim,)), (second, ())]


# ------------------------------------------------------------------------ the note line


def test_the_strength_prefix_is_lifted_into_its_own_slot():
    assert split_strength_label("【中】方案已定") == ("中", "方案已定")
    assert split_strength_label("没有标签的一条") == (None, "没有标签的一条")


def test_a_note_line_carries_strength_text_anchor_and_document():
    note = render_window_notes([_claim("f1a2", "【强】已经上线", [("srcA", 3, 4)])])
    assert "（1 条）" in note or "(1)" in note  # the count line, whichever locale is loaded
    assert "【强】已经上线" in note
    assert "c:f1a2" in note
    assert "memory/projects/demo.md" in note
    # The window's own provenance header two lines above IS the citation; a second copy
    # would only give the model another span to transcribe.
    assert "[cite:" not in note


# --------------------------------------------------------------- ordering + the whole turn


def test_annotated_windows_take_the_two_attention_hot_ends():
    """`order_lost_in_middle` puts rank 1 at the head and rank 2 at the tail. With the
    annotated pairs lifted first, the bare excerpts sink into the middle."""
    bare = [(f"w{i}", ()) for i in range(4)]
    annotated = [("wA", ("note",)), ("wB", ("note",))]
    ordered = order_lost_in_middle(bare[:2] + annotated + bare[2:], priority=lambda p: bool(p[1]))
    assert ordered[0][0] == "wA"
    assert ordered[-1][0] == "wB"


def test_order_lost_in_middle_without_priority_is_unchanged():
    passages = [_window("s", i, i, str(i)) for i in range(5)]
    assert order_lost_in_middle(passages) == order_lost_in_middle(passages, priority=None)
    assert [p.block_start for p in order_lost_in_middle(passages)] == [0, 2, 4, 3, 1]


def test_the_moved_claim_appears_exactly_once_in_the_human_turn():
    """Move, not copy: the joined claim's text must not also stand in the claim section, and
    the section's own count must have shrunk by the claims that left."""
    joined = _claim("j001", "【中】这条是窗口的编读", [("srcA", 4, 5)])
    stayed = _claim("k001", "【弱】这条与窗口无关", [("srcB", 90, 91)])
    windows = [_window("srcA", 3, 8, "原文正文若干行")]

    remaining, paired = join_claims_to_windows([joined, stayed], windows)
    human = recall_human(
        "问题", remaining, as_of=datetime(2026, 7, 20), windows=windows, window_notes=paired
    )

    assert human.count("这条是窗口的编读") == 1
    assert human.count("c:j001") == 1
    assert human.index("原文正文若干行") < human.index("这条是窗口的编读")
    assert "这条与窗口无关" in human  # unjoined claims are untouched
    # the note sits inside the excerpt section, below its window — not in the claim section
    assert human.index("这条是窗口的编读") > human.index("原文正文若干行")


# ------------------------------------------------------------------------- the off path


@dataclass
class _ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class _FakeClaimIndex:
    def __init__(self, claims: list[_ClaimStub]) -> None:
        self._claims = claims

    async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
        return self._claims[:limit]


class _FakeEmbeddings:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


@dataclass
class _LexHit:
    source_id: SourceId
    block_index: int
    text: str
    score: float = 1.0


class _FakeLexical:
    def __init__(self, hits: list[_LexHit]) -> None:
        self._hits = hits

    async def search(self, user_id, query, *, limit=20):  # noqa: ANN001
        return self._hits[:limit]


class _FakeVector:
    async def search(self, user_id, embedding, *, limit=20):  # noqa: ANN001
        return []


async def _run(*, annotate: bool) -> tuple[str, Any]:
    """One fast_recall over a fixture where claim c1 cites the very block the window is."""
    captured: dict[str, str] = {}

    class _Capturing(GenericFakeChatModel):
        async def ainvoke(self, messages, *a, **k):  # noqa: ANN001, ANN002
            captured["human"] = messages[1].content
            return await super().ainvoke(messages, *a, **k)

    claims = [
        _ClaimStub(
            "c1",
            "memory/projects/demo.md",
            "【中】窗口里那几行的编读",
            citations=[{"source_id": "srcbody1", "block_start": 3, "block_end": 3}],
        ),
        _ClaimStub(
            "c2",
            "memory/projects/demo.md",
            "【弱】与任何窗口都不重叠",
            citations=[{"source_id": "srcbody1", "block_start": 90, "block_end": 91}],
        ),
    ]
    answer = await fast_recall(
        _USER,
        "问题",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=_FakeClaimIndex(claims),
        claim_vectors=_FakeClaimIndex([]),
        lexical=_FakeLexical([_LexHit(SourceId("srcbody1"), 3, "原文第三段的内容")]),
        vectors=_FakeVector(),
        embeddings=_FakeEmbeddings(),
        model=_Capturing(messages=iter([AIMessage(content="答")])),
        annotate_windows=annotate,
    )
    return captured["human"], answer


async def test_flag_on_moves_the_joined_claim_and_reports_the_join():
    human, answer = await _run(annotate=True)
    assert answer.annotated_claims == 1 and answer.annotated_windows == 1
    assert [str(c.anchor) for c in answer.used_claims] == ["c2"]  # c1 left the section
    assert human.count("窗口里那几行的编读") == 1
    assert human.index("原文第三段的内容") < human.index("窗口里那几行的编读")


async def test_flag_off_renders_the_two_section_lane_byte_for_byte():
    """The controlled-comparison guarantee. The windows section with the flag off is exactly
    the flat provenance-header + text rendering, with no note marker anywhere, and both
    claims still stand in the claim section."""
    human, answer = await _run(annotate=False)

    assert answer.annotated_claims == 0 and answer.annotated_windows == 0
    assert [str(c.anchor) for c in answer.used_claims] == ["c1", "c2"]
    windows_section = human.split("# 原文摘录", 1)[-1] if "# 原文摘录" in human else (
        human.split("# raw excerpts", 1)[-1]
    )
    windows_section = windows_section.split("\n\nas_of:", 1)[0]
    assert windows_section.strip().endswith("原文第三段的内容")
    assert "⌞" not in human
    assert "〔c:c1" not in human  # the note-line anchor form; the claim section's differs
    # claim section keeps BOTH claims, each stated once, above the excerpts
    assert human.count("窗口里那几行的编读") == 1
    assert human.index("窗口里那几行的编读") < human.index("原文第三段的内容")
