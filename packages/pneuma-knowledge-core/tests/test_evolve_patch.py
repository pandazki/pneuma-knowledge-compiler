"""PatchDraft evolve-only merge channel: move_claim / delete_claim (schema-evolve §B2).

move preserves the claim byte-for-byte and its anchor; delete drops it. Neither leaks into
the daily compile tool face (asserted in test_evolve_runner.py against _build_tools)."""

import pytest

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
    "memory/products/{slug}.md",
    "materials/{slug}.md",
]


def _topic(slug: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/topics/{slug}.md",
        frontmatter={"doc_id": f"d-{slug}", "type": "topic", "slug": slug},
        body=body,
    )


def _draft(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), TEMPLATES)


def test_move_claim_relocates_anchor_verbatim_and_removes_from_source():
    src = _topic(
        "atlas",
        "## 计划\n\n- Atlas 计划 Q3 发布。[cite: src-01 ¶2] <!-- c:aa11 -->\n"
        "- 无关杂项。[cite: src-01 ¶3] <!-- c:bb22 -->",
    )
    draft = _draft(src)
    draft.create_document(
        "memory/products/atlas.md", {"type": "product", "slug": "atlas"}, "## 产品\n"
    )

    draft.move_claim("memory/topics/atlas.md", "aa11", "memory/products/atlas.md", "产品")

    src_body = draft.read("memory/topics/atlas.md").body
    dst_body = draft.read("memory/products/atlas.md").body
    # anchor now lives in the new document, gone from the old one.
    assert "c:aa11" in dst_body and "c:aa11" not in src_body
    assert "c:bb22" in src_body  # the untouched claim stayed
    # moved claim text is byte-identical (verbatim, incl. its anchor comment).
    assert "- Atlas 计划 Q3 发布。[cite: src-01 ¶2] <!-- c:aa11 -->" in dst_body
    assert "Q3 发布" not in src_body


def test_move_claim_rejects_missing_target_document():
    src = _topic("atlas", "- 计划发布。[cite: src-01 ¶0] <!-- c:aa11 -->")
    draft = _draft(src)
    with pytest.raises(AnchorToolError, match="create_document"):
        draft.move_claim(
            "memory/topics/atlas.md", "aa11", "memory/products/atlas.md", "产品"
        )


def test_move_claim_same_document_resection_ok():
    src = _topic(
        "atlas",
        "## 旧节\n\n- 计划发布。[cite: src-01 ¶0] <!-- c:aa11 -->\n\n## 新节\n",
    )
    draft = _draft(src)
    draft.move_claim("memory/topics/atlas.md", "aa11", "memory/topics/atlas.md", "新节")
    body = draft.read("memory/topics/atlas.md").body
    # still exactly one aa11, now under the 新节 section.
    assert body.count("c:aa11") == 1
    assert extract_anchors(body) == ["aa11"]
    assert "新节" in body.split("计划发布")[0]  # claim now sits after 新节 heading


def test_delete_claim_removes_anchor():
    src = _topic(
        "atlas",
        "- 计划发布。[cite: src-01 ¶0] <!-- c:aa11 -->\n"
        "- 冗余重复。[cite: src-01 ¶0] <!-- c:bb22 -->",
    )
    draft = _draft(src)
    draft.delete_claim("memory/topics/atlas.md", "bb22")
    body = draft.read("memory/topics/atlas.md").body
    assert "c:bb22" not in body and "c:aa11" in body
    assert extract_anchors(body) == ["aa11"]


def test_delete_claim_rejects_unknown_anchor():
    src = _topic("atlas", "- 计划发布。[cite: src-01 ¶0] <!-- c:aa11 -->")
    draft = _draft(src)
    with pytest.raises(AnchorToolError, match="is not in this document"):
        draft.delete_claim("memory/topics/atlas.md", "dead")
