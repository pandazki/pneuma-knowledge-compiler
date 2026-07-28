"""MarkdownDocumentAdapter: heading-cut section tree + paragraph fallback (M3b)."""

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import RawSource
from pneuma_knowledge_core.ingest.adapters import MarkdownDocumentAdapter, PlainDocumentInput


def _raw() -> RawSource:
    return RawSource(
        source_id=SourceId("s1"),
        user_id=UserId("u-it-md"),
        kind="document",
        source_class="reference",
        title="doc",
        mime="text/markdown",
        checksum="c",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )


def _norm(text: str):
    return MarkdownDocumentAdapter().normalize(
        PlainDocumentInput(raw=_raw(), text=text)
    )


def test_headings_cut_sections_with_hierarchy_path():
    ns = _norm(
        "# 合同\n\n付款条款在交付后三十日内结清。\n\n"
        "## 第五条 违约金\n\n违约金按日万分之五计算。\n\n上限为合同额。"
    )
    assert [b.text for b in ns.blocks] == [
        "付款条款在交付后三十日内结清。",
        "违约金按日万分之五计算。",
        "上限为合同额。",
    ]
    # nested heading path = full hierarchy.
    assert ns.blocks[0].section_path == ["合同"]
    assert ns.blocks[1].section_path == ["合同", "第五条 违约金"]
    assert ns.blocks[2].section_path == ["合同", "第五条 违约金"]
    spans = [(s.path, s.start_block, s.end_block) for s in ns.structure.sections]
    assert spans == [(["合同"], 0, 0), (["合同", "第五条 违约金"], 1, 2)]


def test_paragraph_fallback_no_headings():
    ns = _norm("第一段。\n\n第二段。\n\n第三段。")
    assert len(ns.blocks) == 3
    assert all(b.section_path == [] for b in ns.blocks)
    # a single implicit (preamble) section spanning all blocks.
    assert len(ns.structure.sections) == 1
    span = ns.structure.sections[0]
    assert (span.path, span.start_block, span.end_block) == ([], 0, 2)


def test_multiline_paragraph_is_one_block():
    ns = _norm("line one\nline two of same paragraph\n\nnext paragraph")
    assert len(ns.blocks) == 2
    assert ns.blocks[0].text == "line one\nline two of same paragraph"


def test_preamble_before_first_heading_is_its_own_section():
    ns = _norm("引言段落。\n\n# 正文\n\n正文段落。")
    assert ns.blocks[0].section_path == []
    assert ns.blocks[1].section_path == ["正文"]
    spans = [(s.path, s.start_block, s.end_block) for s in ns.structure.sections]
    assert spans == [([], 0, 0), (["正文"], 1, 1)]
