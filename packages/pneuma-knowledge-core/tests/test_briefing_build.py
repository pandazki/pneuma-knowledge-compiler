"""Briefing build: source anchoring + byte-stable determinism (M4)."""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.recall.briefing import BriefingScope, build_briefing

_USER = UserId("u-brief")
_S1 = SourceId("s1")

_PEOPLE = CanonicalDocument(
    pneuma_id=DocumentId("doc-cheng-ye"),
    path="memory/people/cheng-ye.md",
    frontmatter={"type": "person"},
    body="## 程野\n\n- 程野 是后端负责人。[cite: s1 ¶0] <!-- c:aaaa -->",
)
_CARD = CanonicalDocument(
    pneuma_id=DocumentId("doc-card"),
    path="materials/contract.md",
    frontmatter={"type": "material"},
    body="## 合同卡片\n\n关键条款蒸馏。[cite: s1 ¶0,2-3] <!-- c:dddd -->",
)


def _source() -> NormalizedSource:
    raw = RawSource(
        source_id=_S1,
        user_id=_USER,
        kind="document",
        title="合同",
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    blocks = [NormalizedBlock(index=i, text=f"原文块{i}", section_path=["第一章"]) for i in range(4)]
    structure = StructureMap(
        sections=[SectionSpan(path=["第一章"], start_block=0, end_block=3)]
    )
    return NormalizedSource(raw=raw, blocks=blocks, structure=structure)


class FakeContent:
    def __init__(self, ns: NormalizedSource) -> None:
        self._ns = ns

    async def get(self, user_id, source_id):  # noqa: ANN001
        return self._ns

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        return "verbatim"


async def _build(docs, snapshot="deadbeef"):
    scope = BriefingScope(source_ids=[_S1], budget_chars=8000)
    return await build_briefing(
        _USER,
        scope,
        snapshot=SnapshotRef(ref=snapshot),
        snapshot_docs=docs,
        content=FakeContent(_source()),
    )


async def test_source_anchoring_includes_card_claims_and_excerpt():
    briefing = await _build([_PEOPLE, _CARD])
    sp = briefing.system_prefix
    assert "关键条款蒸馏。" in sp  # ① materials card
    assert "程野 是后端负责人。" in sp  # ② claim citing the source (reverse lookup)
    assert "原文块0" in sp  # ③ raw excerpt (first block of first section)
    assert briefing.source_count == 1
    assert briefing.claims_count >= 2  # people claim + materials claim both cite s1
    assert briefing.snapshot.ref == "deadbeef"  # snapshot frozen into the briefing


async def test_same_input_builds_byte_identical_system_prefix():
    a = await _build([_PEOPLE, _CARD])
    b = await _build([_CARD, _PEOPLE])  # different doc order — must not change bytes
    assert a.system_prefix == b.system_prefix


async def test_different_snapshot_docs_change_the_pack():
    a = await _build([_PEOPLE, _CARD])
    b = await _build([_PEOPLE])  # a different snapshot's document set
    assert a.system_prefix != b.system_prefix


async def test_system_prefix_has_no_timestamp():
    briefing = await _build([_PEOPLE, _CARD])
    # I5: byte-stable pack carries no volatile time content.
    assert "2026-07-20" not in briefing.system_prefix
    assert "T00:00" not in briefing.system_prefix
