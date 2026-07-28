"""Meilisearch L1 against live compose — CJK is the hard acceptance (ADR-002)."""

from __future__ import annotations

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock

SID = SourceId("meili-src")


def _blocks(texts: list[str]) -> list[NormalizedBlock]:
    return [NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)]


async def test_chinese_japanese_english_recall(meili, user):
    await meili.index_blocks(
        user,
        SID,
        _blocks(
            [
                "这份合同的付款条款约定：买方应于交付后三十日内支付全部款项。",  # 0 zh
                "違約金の計算方法は契約書の第五条に規定されています。",  # 1 ja
                "The warranty period covers twelve months from delivery.",  # 2 en
                "今天天气不错，我们去公园散步吧。",  # 3 zh (distractor)
            ]
        ),
    )

    # Chinese multi-keyword query hits the contract-payment block.
    zh = await meili.search(user, "合同 付款 条款", limit=10)
    assert any(h.block_index == 0 for h in zh), [h.block_index for h in zh]
    assert zh[0].block_index == 0

    # Japanese query hits the Japanese clause block.
    ja = await meili.search(user, "違約金 契約書", limit=10)
    assert any(h.block_index == 1 for h in ja), [h.block_index for h in ja]

    # English query hits the English warranty block.
    en = await meili.search(user, "warranty period delivery", limit=10)
    assert any(h.block_index == 2 for h in en), [h.block_index for h in en]

    # Hits carry unified addressing + snippet + score (I4).
    top = zh[0]
    assert top.source_id == SID
    assert "付款" in top.text
    assert top.score > 0
