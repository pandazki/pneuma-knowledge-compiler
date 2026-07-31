"""Gate: five mechanical checks, each with a reject case and a repaired pass case."""

from datetime import datetime, timezone

from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import DraftDoc, PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]


def _source(source_id: str, n_blocks: int) -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId(source_id),
            user_id=UserId("u-1"),
            kind="conversation",
            title="t",
            mime="text/plain",
            checksum=source_id,
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(n_blocks)],
        structure=StructureMap(),
    )


SOURCES = [_source("src-01", 5)]


def _draft() -> PatchDraft:
    return PatchDraft.from_canonical([], TEMPLATES)


def _kinds(violations) -> set[str]:
    return {v.kind for v in violations}


# --- 1. anchor continuity -----------------------------------------------------


def test_anchor_continuity_rejects_vanished_base_anchor():
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    # Simulate a body where the base anchor was dropped (only reachable by poking the
    # working doc directly; no claim-level op can do this).
    draft.documents()["memory/people/cheng-ye.md"].body = "- 原始改写但丢锚。[cite: src-01 ¶0]"
    v = run_gate(draft, SOURCES)
    assert "anchor_continuity" in _kinds(v)


def test_anchor_continuity_passes_when_preserved():
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    draft.edit_claim("memory/people/cheng-ye.md", "aa11", "- 改写但保锚。[cite: src-01 ¶1]")
    assert "anchor_continuity" not in _kinds(run_gate(draft, SOURCES))


# --- 2. anchor uniqueness -----------------------------------------------------


def test_anchor_uniqueness_rejects_duplicate_across_repo():
    draft = _draft()
    draft._working["memory/people/a.md"] = DraftDoc(
        "memory/people/a.md", DocumentId("d1"),
        {"doc_id": "d1", "type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶0] <!-- c:dddd -->",
    )
    draft._working["memory/people/b.md"] = DraftDoc(
        "memory/people/b.md", DocumentId("d2"),
        {"doc_id": "d2", "type": "person", "slug": "b"},
        "- y。[cite: src-01 ¶1] <!-- c:dddd -->",
    )
    assert "anchor_uniqueness" in _kinds(run_gate(draft, SOURCES))


def test_anchor_uniqueness_passes_for_distinct_anchors():
    draft = _draft()
    draft.create_document("memory/people/a.md", {"type": "person", "slug": "a"}, "- x。[cite: src-01 ¶0]")
    draft.create_document("memory/people/b.md", {"type": "person", "slug": "b"}, "- y。[cite: src-01 ¶1]")
    assert "anchor_uniqueness" not in _kinds(run_gate(draft, SOURCES))


# --- 3. citation legality -----------------------------------------------------


def test_citation_rejects_unknown_source_and_out_of_range():
    draft = _draft()
    draft.create_document("memory/people/a.md", {"type": "person", "slug": "a"}, "- x。[cite: src-99 ¶0]")
    draft.create_document("memory/people/b.md", {"type": "person", "slug": "b"}, "- y。[cite: src-01 ¶9]")
    v = [x for x in run_gate(draft, SOURCES) if x.kind == "citation"]
    assert len(v) == 2  # unknown source + out-of-range block


def test_citation_passes_in_range():
    draft = _draft()
    draft.create_document("memory/people/a.md", {"type": "person", "slug": "a"}, "- x。[cite: src-01 ¶0-4]")
    assert "citation" not in _kinds(run_gate(draft, SOURCES))


# --- 3b. citation marker SHAPE ------------------------------------------------
#
# The legality check can only judge markers it can parse, so a marker that does NOT parse was
# never judged at all — and the provenance check accepted the claim carrying it, because a
# `[cite:` had been typed. Three states: parses, does not parse, and "parses as the other
# provenance form in the wrong container".


def test_every_legal_marker_spelling_passes_the_shape_check():
    draft = _draft()
    draft.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- single。[cite: src-01 ¶0]\n"
        "- range。[cite: src-01 ¶1-3]\n"
        "- grouped。[cite: src-01 ¶0-1,4]\n"
        "- spaced。[cite: src-01 ¶ 0 - ¶ 4]",
    )
    assert "citation" not in _kinds(run_gate(draft, SOURCES))


def test_a_marker_with_no_readable_locator_is_rejected():
    """It has the LOOK of provenance and resolves to nothing — worse than a missing one,
    because it survives review by resembling an answer."""
    draft = _draft()
    draft.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01] <!-- c:aa11 -->",
    )
    details = [x.detail for x in run_gate(draft, SOURCES) if x.kind == "citation"]
    shape = [d for d in details if "does not parse as a locator" in d]
    assert len(shape) == 1
    assert "[cite: src-01]" in shape[0]
    # And the claim is uncited after all — an unreadable marker is not provenance, which is
    # precisely what the provenance check used to be fooled by.
    assert any("no provenance at all" in d for d in details)


def test_a_marker_carrying_trailing_bytes_after_the_locator_is_rejected():
    """Full-match, not search: a parse that leaves bytes over inside the brackets read a
    locator the author did not write."""
    draft = _draft()
    draft.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶0 and thereabouts] <!-- c:aa11 -->",
    )
    assert "citation" in _kinds(run_gate(draft, SOURCES))


def test_anchor_provenance_written_inside_the_brackets_gets_its_own_instruction():
    """The legal second provenance form in the wrong container. Telling the author "this does
    not parse" when the fix is "move it out of the brackets" is a riddle, so it is a separate
    violation text."""
    draft = _draft()
    draft.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: c:8820c773] <!-- c:aa11 -->",
    )
    details = [x.detail for x in run_gate(draft, SOURCES) if x.kind == "citation"]
    shape = [d for d in details if "not inside [cite:]" in d]
    assert len(shape) == 1
    assert "c:8820c773" in shape[0]
    assert not any("does not parse as a locator" in d for d in details)


def test_a_malformed_marker_already_in_canonical_is_rejected_rather_than_grandfathered():
    """The malformed markers this check was written for are ALREADY committed. Exempting a
    carried-over one would preserve exactly the state the check exists to end, and the next
    compile that touches the document is the only channel that can repair it."""
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/a.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "a"},
        body="- 老债。[cite: c:735cd6cf] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    assert "citation" in _kinds(run_gate(draft, SOURCES))


def test_citation_range_accepts_repeated_marker_and_still_checks_bounds():
    valid = _draft()
    valid.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶ 0 - ¶ 4]",
    )
    assert "citation" not in _kinds(run_gate(valid, SOURCES))

    invalid = _draft()
    invalid.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶0-¶9]",
    )
    assert "citation" in _kinds(run_gate(invalid, SOURCES))


def test_grouped_citation_validates_every_span():
    valid = _draft()
    valid.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶0,2-4]",
    )
    assert "citation" not in _kinds(run_gate(valid, SOURCES))

    invalid = _draft()
    invalid.create_document(
        "memory/people/a.md",
        {"type": "person", "slug": "a"},
        "- x。[cite: src-01 ¶0,6]",
    )
    violations = [item for item in run_gate(invalid, SOURCES) if item.kind == "citation"]
    assert len(violations) == 1
    assert "¶6-6" in violations[0].detail


def test_citation_grandfathers_untouched_base_doc_citing_old_source():
    # M5 Path B: a forward-only compile supplies only src-05; an untouched base doc
    # citing the old src-00 (not supplied now) must NOT be re-rejected — its citation
    # was validated at its own commit and is carried over verbatim.
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 老事实。[cite: src-00 ¶0] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    # New source src-05 compiled into a new doc; old cheng-ye.md left untouched.
    draft.create_document("memory/people/mei.md", {"type": "person", "slug": "mei"}, "- 新事实。[cite: src-05 ¶0]")
    v = run_gate(draft, [_source("src-05", 3)])
    assert "citation" not in _kinds(v)  # old src-00 citation grandfathered


def test_citation_full_inventory_revalidates_untouched_base_provenance():
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 老事实。[cite: src-truncated ¶0] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    draft.create_document(
        "memory/people/mei.md",
        {"type": "person", "slug": "mei"},
        "- 新事实。[cite: src-05 ¶0]",
    )
    violations = [
        item
        for item in run_gate(
            draft,
            [_source("src-05", 3)],
            known_source_bounds={"src-00": 2, "src-05": 3},
        )
        if item.kind == "citation"
    ]
    assert len(violations) == 1
    assert "src-truncated" in violations[0].detail


def test_citation_full_inventory_accepts_valid_historical_source():
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 老事实。[cite: src-00 ¶0-1] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    draft.create_document(
        "memory/people/mei.md",
        {"type": "person", "slug": "mei"},
        "- 新事实。[cite: src-05 ¶0]",
    )
    assert "citation" not in _kinds(
        run_gate(
            draft,
            [_source("src-05", 3)],
            known_source_bounds={"src-00": 2, "src-05": 3},
        )
    )


def test_citation_still_rejects_new_claim_with_fabricated_source():
    # Grandfathering only covers verbatim carry-overs; a NEWLY introduced citation to an
    # unsupplied/fabricated source in an edited doc is still rejected.
    base = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body="- 老事实。[cite: src-00 ¶0] <!-- c:aa11 -->",
    )
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    draft.append_block("memory/people/cheng-ye.md", "cheng-ye", "- 新增引用幽灵来源。[cite: src-99 ¶0]")
    v = [x for x in run_gate(draft, [_source("src-05", 3)]) if x.kind == "citation"]
    assert len(v) == 1 and "src-99" in v[0].detail


# --- 4. frontmatter completeness ---------------------------------------------


def test_frontmatter_rejects_missing_required_fields():
    draft = _draft()
    draft._working["memory/people/a.md"] = DraftDoc(
        "memory/people/a.md", DocumentId("d1"),
        {"doc_id": "d1"},  # missing type + slug
        "- x。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    v = [x for x in run_gate(draft, SOURCES) if x.kind == "frontmatter"]
    assert len(v) == 2  # type + slug both missing


def test_frontmatter_passes_when_complete():
    draft = _draft()
    draft.create_document("memory/people/a.md", {"type": "person", "slug": "a"}, "- x。[cite: src-01 ¶0]")
    assert "frontmatter" not in _kinds(run_gate(draft, SOURCES))


# --- 5. path ownership --------------------------------------------------------


def test_path_ownership_rejects_foreign_path():
    draft = _draft()
    draft._working["notes/x.md"] = DraftDoc(
        "notes/x.md", DocumentId("d1"),
        {"doc_id": "d1", "type": "note", "slug": "x"},
        "- x。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    assert "path" in _kinds(run_gate(draft, SOURCES))


def test_path_ownership_passes_for_template_path():
    draft = _draft()
    draft.create_document("materials/contract.md", {"type": "material", "slug": "contract"}, "- x。[cite: src-01 ¶0]")
    assert "path" not in _kinds(run_gate(draft, SOURCES))


def test_clean_draft_has_no_violations():
    draft = _draft()
    draft.create_document(
        "memory/people/cheng-ye.md", {"type": "person", "slug": "cheng-ye"},
        "## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]",
    )
    assert run_gate(draft, SOURCES) == []


# --- 4b. anchor coverage ------------------------------------------------------


def test_anchor_coverage_flags_unanchored_block():
    # A doc with a browse-visible but unanchored block → it would never enter the L3
    # claim index (the orphaned-claim bug); the gate must reject it.
    draft = _draft()
    draft._working["memory/topics/x.md"] = DraftDoc(
        path="memory/topics/x.md",
        doc_id=DocumentId("d1"),
        frontmatter={"doc_id": "d1", "type": "topic", "slug": "x"},
        body="第一段有锚。 <!-- c:aa11 -->\n\n第二段无锚，会被漏掉。",
    )
    assert "anchor_coverage" in _kinds(run_gate(draft, SOURCES))


def test_anchor_coverage_passes_when_every_block_anchored():
    draft = _draft()
    draft._working["memory/topics/x.md"] = DraftDoc(
        path="memory/topics/x.md",
        doc_id=DocumentId("d1"),
        frontmatter={"doc_id": "d1", "type": "topic", "slug": "x"},
        body="第一段。 <!-- c:aa11 -->\n\n- 列表项。 <!-- c:bb22 -->",
    )
    assert "anchor_coverage" not in _kinds(run_gate(draft, SOURCES))


# --- 3b. citation via compile-boundary handle (alias_map) ---------------------


def test_citation_handle_accepted_via_alias_map():
    # The model cites a short per-job handle `s01`; alias_map resolves it to the real
    # source for bounds validation. Both a handle and a raw id are accepted.
    draft = _draft()
    draft._working["memory/topics/x.md"] = DraftDoc(
        path="memory/topics/x.md",
        doc_id=DocumentId("d1"),
        frontmatter={"doc_id": "d1", "type": "topic", "slug": "x"},
        body="事实。[cite: s01 ¶0-2] <!-- c:aa11 -->",
    )
    assert "citation" not in _kinds(run_gate(draft, SOURCES, alias_map={"s01": "src-01"}))
    # without the map, `s01` is an unknown source → rejected.
    assert "citation" in _kinds(run_gate(draft, SOURCES))
