"""Briefing agentic search_knowledge: reaches a mid-document item absent from the static
pack (a regression where the candidate evaluation lives deep in a headed doc)."""

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
from pneuma_knowledge_core.recall.briefing import BriefingScope, briefing_ask, build_briefing
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from test_fast_recall import (
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
    LexHit,
    VecHit,
)

_USER = UserId("u-brief-search")
_SID = "s-interview"


def _source() -> NormalizedSource:
    # 30 blocks; the candidate 孙羽 and their evaluation live deep at ¶20-21, far past the
    # 4-block static sample the briefing pre-packs.
    blocks = [f"第{i}段普通内容。" for i in range(30)]
    blocks[20] = "孙羽"
    blocks[21] = "架构能力强，主导过大型系统迁移，强烈推荐进入终面。"
    raw = RawSource(
        source_id=SourceId(_SID),
        user_id=_USER,
        kind="document",
        title="面试记录",
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    nblocks = [
        NormalizedBlock(index=i, text=t, section_path=["候选人评估"])
        for i, t in enumerate(blocks)
    ]
    structure = StructureMap(
        sections=[SectionSpan(path=["候选人评估"], start_block=0, end_block=29)]
    )
    return NormalizedSource(raw=raw, blocks=nblocks, structure=structure)


class FakeContent:
    def __init__(self, ns: NormalizedSource) -> None:
        self._ns = ns

    async def get(self, user_id, source_id):  # noqa: ANN001
        if str(source_id) == _SID:
            return self._ns
        raise KeyError(source_id)

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        return "verbatim"


class SearchThenAnswerModel(BaseChatModel):
    """Calls search_knowledge('孙羽') on the first turn, then answers with whatever the
    tool returned (so the test can assert the mid-doc evaluation was reachable)."""

    seen_tool_output: str = ""
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "search-then-answer"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Capture any ToolMessage already in the transcript.
        for m in messages:
            if isinstance(m, ToolMessage):
                object.__setattr__(self, "seen_tool_output", str(m.content))
        if self._turn == 0:
            object.__setattr__(self, "_turn", 1)
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "search_knowledge", "args": {"query": "孙羽"}, "id": "c1"}],
            )
        else:
            msg = AIMessage(content=self.seen_tool_output or "（无）")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face — do not lean on BaseChatModel's thread-pool _agenerate default.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def test_search_knowledge_reaches_mid_document_item_absent_from_static_pack():
    ns = _source()
    content = FakeContent(ns)

    briefing = await build_briefing(
        _USER,
        BriefingScope(source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        content=content,
    )
    # Precondition: the deep evaluation is NOT in the static pack (only the first blocks are).
    assert "强烈推荐进入终面" not in briefing.system_prefix
    assert briefing.source_ids == (_SID,)
    # The structure outline IS present, so the model knows the doc holds candidate content.
    assert "Document structure (section outline)" in briefing.system_prefix

    model = SearchThenAnswerModel()
    ans = await briefing_ask(
        briefing,
        "孙羽这个候选人评价如何",
        as_of=datetime(2026, 7, 25),
        model=model,
        content=content,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([LexHit(SourceId(_SID), 20, "孙羽")]),
        vectors=FakeVector(
            [
                VecHit(
                    SourceId(_SID), 20, 21,
                    "孙羽\n架构能力强，主导过大型系统迁移，强烈推荐进入终面。",
                )
            ]
        ),
    )
    # The raw semantic natural unit wins over the overlapping lexical-only name block, so
    # search_knowledge surfaces the deep evaluation without guessing a forward radius.
    assert "强烈推荐进入终面" in ans.answer
    # rendered with the readable source title alongside the [cite: …] marker.
    assert "面试记录" in ans.answer


class DirectAnswerModel(BaseChatModel):
    """Answers immediately without calling any tool (isolates contract/pack aliasing)."""

    answer_text: str = "答案。"

    @property
    def _llm_type(self) -> str:
        return "direct-answer"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ARG002
        msg = AIMessage(content=self.answer_text)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face — do not lean on BaseChatModel's thread-pool _agenerate default.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def test_briefing_alias_never_captures_contract_template_tokens():
    # The fixed contract shows `[cite: <source_id> ¶a-b]` / `[cite: …]` as syntax examples.
    # Aliasing must skip the contract — else those placeholders become junk handles AND push
    # every real source's handle number up. With no tool call and no claims, the pack carries
    # no real cite marker, so a correct aliaser yields an EMPTY handle map here.
    content = FakeContent(_source())
    briefing = await build_briefing(
        _USER,
        BriefingScope(source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        content=content,
    )
    ans = await briefing_ask(
        briefing,
        "问题",
        as_of=datetime(2026, 7, 25),
        model=DirectAnswerModel(),
        content=content,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        citation_alias=True,
    )
    assert ans.citation_handles == {}
    assert "<source_id>" not in ans.citation_handles.values()
    assert "…" not in ans.citation_handles.values()


async def test_search_knowledge_scoped_to_anchored_sources():
    ns = _source()
    content = FakeContent(ns)
    briefing = await build_briefing(
        _USER,
        BriefingScope(source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        content=content,
    )
    model = SearchThenAnswerModel()
    # A hit from an OUT-OF-SCOPE source must be filtered away by search_knowledge.
    await briefing_ask(
        briefing,
        "孙羽",
        as_of=datetime(2026, 7, 25),
        model=model,
        content=content,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([LexHit(SourceId("other-src"), 0, "无关内容")]),
        vectors=FakeVector([VecHit(SourceId("other-src"), 0, 0, "无关内容")]),
    )
    # out-of-scope source filtered → the tool reported nothing in scope.
    assert "nothing relevant found" in model.seen_tool_output
