"""PatchDraft: claim-level staging, system anchor/doc_id assignment, no whole-file
rewrite op, path ownership enforcement."""

import pytest

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.documents import Overview, parse_document, render_document
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


# ─────────────────────────────────────────────────────── the derived frontmatter `title`
#
# A document's name is the `# ` line at the top of it. Before this was mechanical the
# frontmatter `title` was whatever the model felt like — measured on a real library: empty
# on 58 of 85 pages, a person's JOB title ("Director of Technology, …") on two. So it is
# derived like the doc_id is assigned: the system reads it off the H1 on every write, and
# nobody else may set it.


def _person_with_stale_title() -> tuple[PatchDraft, str]:
    doc = CanonicalDocument(
        doc_id=DocumentId("abc123"),
        path="memory/people/mei-lin.md",
        frontmatter={
            "doc_id": "abc123",
            "type": "person",
            "slug": "mei-lin",
            "title": "Director of Technology, Northwind Freight",
        },
        body="# Mei Lin\n\n## Role\n\n- Mei Lin joined in 2024. [cite: src-01 ¶0] <!-- c:1111 -->",
    )
    return _draft(doc), doc.path


def test_create_document_replaces_a_model_written_title_with_the_one_on_the_page():
    draft = _draft()
    doc = draft.create_document(
        "memory/people/mei-lin.md",
        {"type": "person", "slug": "mei-lin", "title": "Director of Technology"},
        "# Mei Lin\n\n- Mei Lin leads platform. [cite: src-01 ¶3]",
    )
    # replaced, not refused: the contract asked models for a title for months.
    assert doc.frontmatter["title"] == "Mei Lin"
    committed, _ = parse_document(draft.to_files()["memory/people/mei-lin.md"])
    assert committed["title"] == "Mei Lin"


def test_create_document_derives_the_title_when_the_model_wrote_none():
    draft = _draft()
    doc = draft.create_document(
        "memory/topics/q3-launch.md",
        {"type": "topic", "slug": "q3-launch"},
        "# Q3 launch <!-- c:dead --> \n\n- Kickoff was 2026-07-01. [cite: src-01 ¶0]",
    )
    # anchor marks and trailing comments on the heading are machinery, not the name
    assert doc.frontmatter["title"] == "Q3 launch"


def test_a_body_without_an_h1_gets_no_title_at_all():
    draft = _draft()
    doc = draft.create_document(
        "memory/topics/q3-launch.md",
        {"type": "topic", "slug": "q3-launch", "title": "Whatever the model felt like"},
        "## Commitments\n\n- Kickoff was 2026-07-01. [cite: src-01 ¶0]",
    )
    assert "title" not in doc.frontmatter
    committed, _ = parse_document(draft.to_files()["memory/topics/q3-launch.md"])
    assert "title" not in committed


def test_set_fields_refuses_title_and_says_where_it_comes_from():
    draft, path = _person_with_stale_title()
    draft.mark_read(path)
    for call in (
        lambda: draft.set_fields(path, {"title": "Director of Technology"}),
        lambda: draft.rewrite_overview(path, Overview(definition="x c:1111"), {"title": "x"}),
    ):
        with pytest.raises(AnchorToolError) as err:
            call()
        assert "`title`" in str(err.value)
        assert "`# ` heading" in str(err.value)
    assert draft.read(path).frontmatter["title"] == "Director of Technology, Northwind Freight"


def test_a_stale_title_is_corrected_by_the_next_ordinary_write_of_its_page():
    draft, path = _person_with_stale_title()
    draft.append_block(path, "Role", "- Mei Lin moved to Ops. [cite: src-02 ¶4]")
    frontmatter, _ = parse_document(draft.to_files()[path])
    # the round wrote a claim; the title rides along in the same commit
    assert frontmatter["title"] == "Mei Lin"


def test_a_clean_library_full_of_stale_titles_is_still_a_noop():
    draft, path = _person_with_stale_title()
    assert not draft.is_dirty()
    # and the file is handed to the commit exactly as it stood
    assert draft.to_files()[path].splitlines()[1:5] == [
        "doc_id: abc123",
        "slug: mei-lin",
        "title: Director of Technology, Northwind Freight",
        "type: person",
    ]


def test_a_page_this_round_never_touched_stays_byte_identical():
    """The reason the derivation runs over the CHANGED set only: a commit carries the whole
    file table, so deriving over all of it would drag every stale title in the library into
    the diff of one unrelated claim."""
    stale = CanonicalDocument(
        doc_id=DocumentId("abc123"),
        path="memory/people/mei-lin.md",
        frontmatter={
            "doc_id": "abc123",
            "type": "person",
            "slug": "mei-lin",
            "title": "Director of Technology, Northwind Freight",
        },
        body="# Mei Lin\n\n- Mei Lin joined in 2024. [cite: src-01 ¶0] <!-- c:1111 -->",
    )
    other = CanonicalDocument(
        doc_id=DocumentId("def456"),
        path="memory/topics/q3-launch.md",
        frontmatter={"doc_id": "def456", "type": "topic", "slug": "q3-launch"},
        body="# Q3 launch\n\n## Commitments\n\n- Kickoff 2026-07-01. [cite: src-01 ¶0] <!-- c:2222 -->",
    )
    draft = _draft(stale, other)
    before = render_document(stale.frontmatter, stale.body)
    draft.append_block(other.path, "Commitments", "- Beta shipped. [cite: src-02 ¶2]")
    files = draft.to_files()
    assert draft.is_dirty()
    assert files[stale.path] == before
    # the page that WAS written this round got its own title derived
    assert parse_document(files[other.path])[0]["title"] == "Q3 launch"


# --- component-owned fields: DELETED ------------------------------------------------------
# This file once tested a `component_owned_fields` seam: a component could declare that a
# frontmatter field's ENTRIES were its own tool's to introduce, and the write faces plus a
# gate check (7b) refused a generic write that added one. It existed for exactly one field,
# `people.declined_terms` — the address terms a person page had ruled were not its subject's
# name — and that field is gone: canonical records what is KNOWN about a person, not a memo
# about what not to ask again. With its only user deleted the seam had no second one, so the
# machinery went with it rather than standing as an unexercised capability. The tests that
# covered it (a forged entry, the internal write face, the carry-or-drop snapshot rule) are
# deleted here for the same reason — they tested a mechanism, not a behaviour anyone has.
