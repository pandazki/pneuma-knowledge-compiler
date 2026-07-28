from datetime import datetime

import pytest

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import (
    ConversationTurn,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.ingest.adapters import (
    AdapterRegistry,
    PlainConversationAdapter,
    PlainConversationInput,
)


def test_resolve_section_returns_block_interval():
    sm = StructureMap(
        sections=[
            SectionSpan(path=["第一章"], start_block=0, end_block=4),
            SectionSpan(path=["第二章"], start_block=5, end_block=9),
        ]
    )
    assert sm.resolve({"section": ["第一章"]}) == (0, 4)
    assert sm.resolve({"section": ["第二章"]}) == (5, 9)


def test_resolve_blocks_passthrough():
    sm = StructureMap()
    assert sm.resolve({"blocks": [2, 7]}) == (2, 7)


def test_resolve_unknown_section_raises():
    sm = StructureMap(sections=[SectionSpan(path=["a"], start_block=0, end_block=1)])
    with pytest.raises(KeyError):
        sm.resolve({"section": ["missing"]})


def test_resolve_bad_locator_raises():
    with pytest.raises(ValueError):
        StructureMap().resolve({"nonsense": 1})


def _raw() -> RawSource:
    return RawSource(
        source_id=SourceId("s-1"),
        user_id=UserId("u-1"),
        kind="conversation",
        title="chat",
        mime="application/json",
        checksum="x",
        created_at=datetime(2026, 1, 1),
    )


def test_conversation_adapter_blocks_and_date_sections():
    turns = [
        ConversationTurn(speaker="A", text="hi", at=datetime(2026, 1, 1, 9)),
        ConversationTurn(speaker="B", text="hey", at=datetime(2026, 1, 1, 10)),
        ConversationTurn(speaker="A", text="next day", at=datetime(2026, 1, 2, 9)),
    ]
    ns = PlainConversationAdapter().normalize(
        PlainConversationInput(raw=_raw(), turns=turns)
    )

    assert [b.index for b in ns.blocks] == [0, 1, 2]
    assert ns.blocks[0].text == "A: hi"
    # Day 1 covers blocks 0-1, day 2 covers block 2.
    assert ns.structure.resolve({"section": ["2026-01-01"]}) == (0, 1)
    assert ns.structure.resolve({"section": ["2026-01-02"]}) == (2, 2)


def test_registry_resolves_by_kind_fallback():
    reg = AdapterRegistry()
    adapter = PlainConversationAdapter()
    reg.register(adapter, kind="conversation")
    assert reg.find("conversation", "any/mime") is adapter
    with pytest.raises(KeyError):
        reg.find("document")
