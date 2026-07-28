"""Ported Pneuma Compiler anchor_tools regression suite (adapted imports; sidecar/preflight
helpers dropped per M3a — v1 has no write_file tool and no transition sidecar)."""

import pytest

from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    append_block_text,
    assign_anchor,
    assign_document_anchors,
    edit_claim_text,
    missing_anchors,
    normalize_repeated_heading_markers,
)
from pneuma_knowledge_core.domain.ids import extract_anchors

DOC = """\
# 人物与关系

## 程野

- 程野 是团队后端负责人。[cite: src-01 ¶3] <!-- c:aa11 -->
- 早期 ASR 写法「欧文」，本人纠正为 程野。[cite: src-01 ¶8] <!-- c:bb22 -->

## 关联

- [承诺](../commitments.md)
"""


def test_extract_anchors_ordered():
    assert extract_anchors(DOC) == ["aa11", "bb22"]


def test_missing_anchors_detects_whole_file_rewrite_loss():
    rewritten = DOC.replace(" <!-- c:bb22 -->", "")
    assert missing_anchors(DOC, rewritten) == ["bb22"]
    assert missing_anchors(DOC, DOC) == []


def test_missing_anchors_respects_allowed_removals():
    rewritten = DOC.replace(" <!-- c:bb22 -->", "")
    assert missing_anchors(DOC, rewritten, allowed_removals={"bb22"}) == []


def test_normalize_repeated_heading_markers_preserves_level_content_and_anchors():
    damaged = (
        "# 标题\n\n"
        "## ## 行动项\n"
        "- A <!-- c:aa11 -->\n\n"
        "```md\n"
        "## ## 代码示例保持原样\n"
        "```\n\n"
        "### ## ## 细节\n"
        "- B <!-- c:bb22 -->\n"
    )
    repaired, changes = normalize_repeated_heading_markers(damaged)
    assert changes == 2
    assert repaired == (
        "# 标题\n\n"
        "## 行动项\n"
        "- A <!-- c:aa11 -->\n\n"
        "```md\n"
        "## ## 代码示例保持原样\n"
        "```\n\n"
        "### 细节\n"
        "- B <!-- c:bb22 -->\n"
    )
    assert extract_anchors(repaired) == ["aa11", "bb22"]


def test_edit_claim_rewrites_in_place_and_restores_anchor():
    out = edit_claim_text(DOC, "aa11", "- 程野 转任架构师。[cite: src-02 ¶5]")
    assert "- 程野 转任架构师。[cite: src-02 ¶5] <!-- c:aa11 -->" in out
    assert "后端负责人" not in out
    assert extract_anchors(out) == ["aa11", "bb22"]


def test_edit_claim_accepts_block_carrying_own_anchor():
    out = edit_claim_text(DOC, "bb22", "- 别名台账更新。[cite: src-02 ¶6] <!-- c:bb22 -->")
    assert out.count("<!-- c:bb22 -->") == 1


def test_edit_claim_rejects_unknown_and_foreign_anchor():
    with pytest.raises(AnchorToolError, match="不在该文档中"):
        edit_claim_text(DOC, "dead", "- x [inferred]")
    with pytest.raises(AnchorToolError, match="含有其它锚"):
        edit_claim_text(DOC, "aa11", "- x [inferred] <!-- c:ffff -->")


def test_append_block_into_existing_section():
    out = append_block_text(
        DOC, "程野", "- 程野 下周休假。[cite: src-03 ¶2]", document_path="memory/people/cheng-ye.md"
    )
    anchors = extract_anchors(out)
    assert anchors[:2] == ["aa11", "bb22"] and len(anchors) == 3
    section = out.split("## 关联")[0]
    assert "下周休假" in section  # 落在 程野 小节内、下一同级标题之前


def test_append_block_creates_missing_section_and_rejects_model_anchor():
    out = append_block_text(DOC, "Open Questions", "- 归属待确认。[inferred]")
    assert "## Open Questions" in out and len(extract_anchors(out)) == 3
    with pytest.raises(AnchorToolError, match="锚由系统分配"):
        append_block_text(DOC, "程野", "- x [inferred] <!-- c:1234 -->")


def test_assign_anchor_deterministic_and_collision_safe():
    a1 = assign_anchor("memory/people/x.md", "- 同一内容", set())
    a2 = assign_anchor("memory/people/x.md", "- 同一内容", set())
    assert a1 == a2
    a3 = assign_anchor("memory/people/x.md", "- 同一内容", {a1})
    assert a3 != a1


def test_assign_document_anchors_anchors_every_claim_deterministically():
    body = "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶8]"
    out = assign_document_anchors(body, "memory/people/cheng-ye.md")
    anchors = extract_anchors(out)
    assert len(anchors) == 2  # one per bullet claim, heading skipped
    # Deterministic: same input → same anchors.
    assert extract_anchors(assign_document_anchors(body, "memory/people/cheng-ye.md")) == anchors


def test_append_block_anchors_every_block_not_just_last():
    # A multi-paragraph append must anchor EACH block, or the earlier ones are orphaned
    # (browse-visible, never indexed as claims).
    from pneuma_knowledge_core.compile.anchor_ops import append_block_text
    from pneuma_knowledge_core.domain.ids import extract_anchors

    body = "# 文档\n\n## 清理\n"
    text = "一段承诺。\n\n二段回应。\n\n- 三段列表项。"
    out = append_block_text(body, "清理", text, document_path="memory/topics/x.md")
    assert len(extract_anchors(out)) == 3
