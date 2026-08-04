"""PatchDraft: claim-level staging, system anchor/doc_id assignment, no whole-file
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


def test_create_document_assigns_doc_id_and_all_anchors_deterministically():
    draft = _draft()
    doc = draft.create_document(
        "memory/people/cheng-ye.md",
        {"type": "person", "slug": "cheng-ye"},
        "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶8]",
    )
    assert doc.frontmatter["doc_id"] == str(doc.doc_id)
    assert len(extract_anchors(doc.body)) == 2

    # Re-running the identical create in a fresh draft yields identical ids/anchors.
    again = _draft().create_document(
        "memory/people/cheng-ye.md",
        {"type": "person", "slug": "cheng-ye"},
        "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶8]",
    )
    assert again.doc_id == doc.doc_id
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


def test_append_block_normalizes_markdown_heading_syntax_from_model():
    draft = _draft()
    draft.create_document(
        "memory/topics/q3-launch.md",
        {"type": "topic", "slug": "q3-launch"},
        "## 承诺\n\n- 初始。[cite: src-01 ¶0]",
    )
    doc = draft.append_block(
        "memory/topics/q3-launch.md",
        "### 承诺",
        "- 新承诺。[cite: src-02 ¶ 1 - ¶ 1]",
    )
    assert [line for line in doc.body.splitlines() if line.startswith("#")] == [
        "## 承诺"
    ]
    assert "## ##" not in doc.body
    assert "[cite: src-02 ¶1]" in doc.body


def test_append_block_rejects_heading_with_no_title():
    draft = _draft()
    draft.create_document(
        "memory/topics/q3-launch.md",
        {"type": "topic", "slug": "q3-launch"},
        "## 承诺\n\n- 初始。[cite: src-01 ¶0]",
    )
    with pytest.raises(AnchorToolError, match="section heading cannot be empty"):
        draft.append_block(
            "memory/topics/q3-launch.md",
            "###",
            "- 新承诺。[cite: src-02 ¶1]",
        )


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


def _rolled_over_world() -> tuple[PatchDraft, str, str]:
    """An active page plus one of its frozen history volumes, as a later draft sees them."""
    active_path = "memory/topics/orion.md"
    volume_path = "memory/topics/orion/a01.md"
    active = CanonicalDocument(
        doc_id=DocumentId("d-orion"),
        path=active_path,
        frontmatter={"doc_id": "d-orion", "type": "topic", "slug": "orion"},
        body="# Orion\n\n## Delivery\n\n- Sprint 9 done. [cite: src-01 ¶0] <!-- c:aaaa1111 -->\n",
    )
    volume = CanonicalDocument(
        doc_id=DocumentId("d-orion-a01"),
        path=volume_path,
        frontmatter={
            "doc_id": "d-orion-a01",
            "type": "topic",
            "slug": "a01",
            "archived_from": active_path,
            "rollover_volume": "01",
        },
        body="# Orion\n\n## Delivery\n\n- Sprint 1 done. [cite: src-01 ¶0] <!-- c:bbbb2222 -->\n",
    )
    return _draft(active, volume), active_path, volume_path


def test_every_claim_mutation_refuses_a_frozen_history_volume_early_and_teachably():
    """The write tools are where the frozen-volume trap must be caught: before this guard the
    first "frozen" a model heard came from the gate, after the whole round was spent. The
    refusal is early, names the volume's owner, and states the corrective action — write to
    the active page — so a repair round has something to act on."""
    draft, active_path, volume_path = _rolled_over_world()

    with pytest.raises(AnchorToolError, match="frozen history volume") as err:
        draft.edit_claim(volume_path, "bbbb2222", "- Sprint 1 shipped. [cite: src-02 ¶0]")
    assert "edit_claim rejected" in str(err.value)
    assert f"active page: use edit_claim / append_block on `{active_path}`" in str(err.value)

    with pytest.raises(AnchorToolError, match="frozen history volume"):
        draft.append_block(volume_path, "Delivery", "- New fact. [cite: src-02 ¶1]")
    # the evolve-only merge channel is bound by the same freeze, in both directions
    with pytest.raises(AnchorToolError, match="frozen history volume"):
        draft.move_claim(volume_path, "bbbb2222", active_path, "Delivery")
    with pytest.raises(AnchorToolError, match="frozen history volume"):
        draft.move_claim(active_path, "aaaa1111", volume_path, "Delivery")
    with pytest.raises(AnchorToolError, match="frozen history volume"):
        draft.delete_claim(volume_path, "bbbb2222")

    # nothing above touched the draft, and the active page itself still takes writes
    assert not draft.is_dirty()
    draft.append_block(active_path, "Delivery", "- Sprint 10 kicked off. [cite: src-02 ¶2]")
    assert draft.is_dirty()


def test_the_volume_stays_readable_even_though_it_is_frozen():
    draft, _, volume_path = _rolled_over_world()
    assert "Sprint 1 done." in draft.read(volume_path).body


def test_from_canonical_seeds_base_and_working():
    base = CanonicalDocument(
        doc_id=DocumentId("abc123"),
        path="memory/profile.md",
        frontmatter={"doc_id": "abc123", "type": "profile", "slug": "profile"},
        body="- 本人是产品经理。[cite: src-01 ¶0] <!-- c:1111 -->",
    )
    draft = _draft(base)
    assert draft.list_paths() == ["memory/profile.md"]
    assert not draft.is_dirty()
    draft.append_block("memory/profile.md", "偏好", "- 偏好远程办公。[cite: src-02 ¶1]")
    assert draft.is_dirty()
