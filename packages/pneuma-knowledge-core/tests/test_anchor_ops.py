"""Ported Pneuma Compiler anchor_tools regression suite (adapted imports; sidecar/preflight
helpers dropped per M3a — v1 has no write_file tool and no transition sidecar)."""

import pytest

from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    anchored_blocks,
    append_block_text,
    assign_anchor,
    assign_document_anchors,
    edit_claim_text,
    missing_anchors,
    normalize_repeated_heading_markers,
    unanchored_blocks,
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


def test_edit_claim_keeps_a_list_item_a_list_item():
    """A wording fix must not quietly promote a bullet out of its list.

    A real model corrected one word and sent the sentence back without its bullet; the claim
    left the list it belonged to. `supersede_claim_text` already keeps the predecessor's
    form for its successor, and an edit is the same mechanical alignment — the block's shape
    is the document's structure, not the wording the edit was about.
    """
    out = edit_claim_text(DOC, "aa11", "程野 是团队后端负责人（架构方向）。[cite: src-01 ¶3]")
    assert "- 程野 是团队后端负责人（架构方向）。[cite: src-01 ¶3] <!-- c:aa11 -->" in out
    assert extract_anchors(out) == ["aa11", "bb22"]


def test_edit_claim_does_not_bullet_a_paragraph_claim():
    """The converse: form is PRESERVED, never imposed. A paragraph claim stays a paragraph."""
    doc = "# T\n\n## S\n\n程野 是团队后端负责人。[cite: src-01 ¶3] <!-- c:aa11 -->\n"
    out = edit_claim_text(doc, "aa11", "程野 转任架构师。[cite: src-02 ¶5]")
    assert "\n程野 转任架构师。[cite: src-02 ¶5] <!-- c:aa11 -->\n" in out
    assert "- 程野" not in out


def test_edit_claim_rejects_unknown_and_foreign_anchor():
    with pytest.raises(AnchorToolError, match="is not in this document"):
        edit_claim_text(DOC, "dead", "- x [inferred]")
    with pytest.raises(AnchorToolError, match="contains other anchors"):
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
    with pytest.raises(AnchorToolError, match="the system assigns it"):
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


# ---- _block_span anchor-boundary regression (evermembench model-compare-01) ----
# A blank-line-free run of adjacent single-line anchored claims: editing one claim's
# block must never swallow a neighboring claim's anchored line. Reproduced defect:
# editing the run's LAST claim (c:563837bc) computed the block as the whole run and
# silently deleted the four anchors above it.

PACKED_DOC = """\
# 碳排放核算平台

## Key participants and responsibilities

张伟华 任项目负责人。[cite: src-01 ¶2] <!-- c:08fd9324 -->
李明志 负责技术线。[cite: src-01 ¶3] <!-- c:9319210c -->
黄建国 负责运营线。[cite: src-01 ¶4] <!-- c:a1480228 -->
周丽珍 负责财务线。[cite: src-01 ¶5] <!-- c:fca40036 -->
苏宇 与 侯鹏 负责数据接入。[cite: src-01 ¶6] <!-- c:563837bc -->

## 关联

- [承诺](../commitments.md)
"""

PACKED_NEIGHBOR_LINES = [
    "张伟华 任项目负责人。[cite: src-01 ¶2] <!-- c:08fd9324 -->",
    "李明志 负责技术线。[cite: src-01 ¶3] <!-- c:9319210c -->",
    "黄建国 负责运营线。[cite: src-01 ¶4] <!-- c:a1480228 -->",
    "周丽珍 负责财务线。[cite: src-01 ¶5] <!-- c:fca40036 -->",
]


def test_edit_last_claim_in_packed_anchored_run_preserves_neighbor_anchors():
    # The exact reproduced case: one legal edit_claim on the run's last claim.
    out = edit_claim_text(
        PACKED_DOC, "563837bc", "苏宇 与 侯鹏 已确认 ERP 视图权限。[cite: src-02 ¶4]"
    )
    # The four neighboring anchored lines survive byte-identical.
    out_lines = out.split("\n")
    for line in PACKED_NEIGHBOR_LINES:
        assert line in out_lines
    assert "苏宇 与 侯鹏 已确认 ERP 视图权限。[cite: src-02 ¶4] <!-- c:563837bc -->" in out_lines
    assert "负责数据接入" not in out
    assert extract_anchors(out) == [
        "08fd9324",
        "9319210c",
        "a1480228",
        "fca40036",
        "563837bc",
    ]
    # The write-time conservation check (the gate's anchor_continuity source) is clean.
    assert missing_anchors(PACKED_DOC, out) == []


def test_edit_middle_claim_in_packed_run_touches_only_its_line():
    out = edit_claim_text(PACKED_DOC, "a1480228", "黄建国 转岗至合规线。[cite: src-02 ¶7]")
    out_lines = out.split("\n")
    for line in PACKED_NEIGHBOR_LINES:
        if "a1480228" in line:
            continue
        assert line in out_lines
    assert "苏宇 与 侯鹏 负责数据接入。[cite: src-01 ¶6] <!-- c:563837bc -->" in out_lines
    assert "黄建国 转岗至合规线。[cite: src-02 ¶7] <!-- c:a1480228 -->" in out_lines
    assert "负责运营线" not in out
    assert missing_anchors(PACKED_DOC, out) == []


def test_blank_line_separated_paragraph_span_unchanged():
    # Non-anchored span semantics are untouched: a multi-line paragraph still folds its
    # unanchored continuation lines upward to the blank-line boundary, and blank-line
    # separated neighbors are never part of the span.
    doc = (
        "# 主题\n"
        "\n"
        "## 进展\n"
        "\n"
        "第一段首行续写,\n"
        "第一段收尾。[cite: src-01 ¶1] <!-- c:aaaa1111 -->\n"
        "\n"
        "第二段独立成块。[cite: src-01 ¶2] <!-- c:bbbb2222 -->\n"
    )
    out = edit_claim_text(doc, "aaaa1111", "第一段改写后的单行。[cite: src-02 ¶1]")
    # Both lines of the multi-line paragraph were replaced (upward fold preserved)...
    assert "首行续写" not in out and "收尾" not in out
    assert "第一段改写后的单行。[cite: src-02 ¶1] <!-- c:aaaa1111 -->" in out
    # ...and the blank-line-separated neighbor is byte-identical.
    assert "第二段独立成块。[cite: src-01 ¶2] <!-- c:bbbb2222 -->" in out.split("\n")
    assert missing_anchors(doc, out) == []


def test_anchor_conservation_holds_for_every_edit_in_packed_run():
    # Property: for EVERY claim in the packed run, a legal edit conserves all anchors.
    anchors = extract_anchors(PACKED_DOC)
    assert len(anchors) == 5
    for anchor in anchors:
        out = edit_claim_text(PACKED_DOC, anchor, f"更新后的第 {anchor} 条内容。[cite: src-02 ¶1]")
        assert missing_anchors(PACKED_DOC, out) == []
        assert extract_anchors(out) == anchors


def test_append_block_anchors_every_block_not_just_last():
    # A multi-paragraph append must anchor EACH block, or the earlier ones are orphaned
    # (browse-visible, never indexed as claims).
    from pneuma_knowledge_core.compile.anchor_ops import append_block_text
    from pneuma_knowledge_core.domain.ids import extract_anchors

    body = "# 文档\n\n## 清理\n"
    text = "一段承诺。\n\n二段回应。\n\n- 三段列表项。"
    out = append_block_text(body, "清理", text, document_path="memory/topics/x.md")
    assert len(extract_anchors(out)) == 3


# ---- block segmentation: an anchor ends the block it sits on --------------------


def test_an_unanchored_multi_line_paragraph_is_still_one_block():
    """The anchor stop must not shorten ordinary paragraphs: a paragraph WITHOUT an anchor
    runs to the blank line, so `assign_document_anchors` gives it exactly one anchor and the
    gate sees no orphan."""
    body = "## 背景\n\n第一行叙述。\n第二行叙述。[cite: src-01 ¶3]\n\n- 一条列表。[cite: src-01 ¶4]"
    out = assign_document_anchors(body, "memory/topics/t.md")
    assert len(extract_anchors(out)) == 2  # the paragraph as ONE claim, plus the bullet
    lines = out.split("\n")
    assert "<!-- c:" not in lines[2] and "<!-- c:" in lines[3]  # anchor on the last line
    assert unanchored_blocks(out) == []
    assert anchored_blocks(out) == ["第一行叙述。\n" + lines[3], lines[5]]


def test_two_adjacent_anchored_paragraph_claims_are_two_blocks():
    body = (
        "单身。[cite: src-01 ¶1] <!-- c:aaaa1111 -->\n"
        "在与 Jon 交往。[cite: src-01 ¶5] <!-- c:bbbb2222 --> <!-- supersedes: c:aaaa1111 -->"
    )
    assert anchored_blocks(body) == body.split("\n")
    assert unanchored_blocks(body) == []
