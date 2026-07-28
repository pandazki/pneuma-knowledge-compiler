"""PatchDraft: claim-level staging, system anchor/pneuma_id assignment, no whole-file
rewrite op, path ownership enforcement."""

import pytest

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.patch import PatchDraft, path_allowed
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]


def _draft(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), TEMPLATES)


def test_path_allowed_matches_templates_and_rejects_others():
    assert path_allowed("memory/profile.md", TEMPLATES)
    assert path_allowed("memory/people/cheng-ye-li.md", TEMPLATES)
    assert not path_allowed("memory/people/程野.md", TEMPLATES)  # not kebab-case
    assert not path_allowed("notes/random.md", TEMPLATES)
    assert not path_allowed("memory/profile.txt", TEMPLATES)


def test_create_document_assigns_pneuma_id_and_all_anchors_deterministically():
    draft = _draft()
    doc = draft.create_document(
        "memory/people/cheng-ye.md",
        {"type": "person", "slug": "cheng-ye"},
        "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶8]",
    )
    assert doc.frontmatter["pneuma_id"] == str(doc.pneuma_id)
    assert len(extract_anchors(doc.body)) == 2

    # Re-running the identical create in a fresh draft yields identical ids/anchors.
    again = _draft().create_document(
        "memory/people/cheng-ye.md",
        {"type": "person", "slug": "cheng-ye"},
        "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶8]",
    )
    assert again.pneuma_id == doc.pneuma_id
    assert extract_anchors(again.body) == extract_anchors(doc.body)


def test_create_document_rejects_foreign_path():
    with pytest.raises(AnchorToolError, match="ownership"):
        _draft().create_document("notes/x.md", {"type": "t", "slug": "x"}, "- hi")


def test_append_block_assigns_a_new_anchor():
    draft = _draft()
    draft.create_document(
        "memory/topics/q3-launch.md", {"type": "topic", "slug": "q3-launch"}, "## 承诺\n\n- 初始。[cite: src-01 ¶0]"
    )
    before = set(extract_anchors(draft.read("memory/topics/q3-launch.md").body))
    doc = draft.append_block("memory/topics/q3-launch.md", "承诺", "- 新承诺。[cite: src-02 ¶1]")
    after = set(extract_anchors(doc.body))
    assert len(after - before) == 1  # exactly one system-assigned anchor


def test_edit_claim_preserves_anchor():
    draft = _draft()
    doc = draft.create_document(
        "memory/people/mei.md", {"type": "person", "slug": "mei"}, "## Mei\n\n- 原始。[cite: src-01 ¶0]"
    )
    anchor = extract_anchors(doc.body)[0]
    edited = draft.edit_claim("memory/people/mei.md", anchor, "- 改写后。[cite: src-02 ¶1]")
    assert extract_anchors(edited.body) == [anchor]  # same anchor kept
    assert "改写后" in edited.body and "原始" not in edited.body


def test_there_is_no_whole_file_rewrite_operation():
    # The mechanism guarantee: the staging surface exposes only claim-level ops.
    assert not hasattr(PatchDraft, "write_file")
    assert not hasattr(PatchDraft, "replace_document")


def test_from_canonical_seeds_base_and_working():
    base = CanonicalDocument(
        pneuma_id=DocumentId("abc123"),
        path="memory/profile.md",
        frontmatter={"pneuma_id": "abc123", "type": "profile", "slug": "profile"},
        body="- 本人是产品经理。[cite: src-01 ¶0] <!-- c:1111 -->",
    )
    draft = _draft(base)
    assert draft.list_paths() == ["memory/profile.md"]
    assert not draft.is_dirty()
    draft.append_block("memory/profile.md", "偏好", "- 偏好远程办公。[cite: src-02 ¶1]")
    assert draft.is_dirty()
