"""Changed canonical claims must not inherit admission merely by keeping their id."""

import pytest

from pneuma_knowledge_core.compile.gate import check_claim_provenance, run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors
from pneuma_knowledge_core.evolve.gate import run_evolve_gate


TEMPLATES = ["people/{slug}.md"]
PATH = "people/alice.md"


def _doc(path, body):
    slug = path.split("/")[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(slug), path=path,
        frontmatter={"doc_id": slug, "type": "person", "slug": slug}, body=body,
    )


def _draft(body="- Alice visited Canada. [cite: source-a ¶0] <!-- c:aa11 -->"):
    return PatchDraft.from_canonical([_doc(PATH, body)], TEMPLATES)


async def _gate(draft, channel):
    if channel == "compile":
        return run_gate(draft, [], known_source_bounds={"source-a": 1})

    async def bounds(source_id):
        assert source_id == "source-a"
        return 1

    violations, _ = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES,
    )
    return violations


@pytest.mark.parametrize("channel", ["compile", "evolve"])
@pytest.mark.parametrize("text", ["Alice visited Mars.", "Alice visited Mars. c:aa11"])
async def test_edit_tool_cannot_remove_provenance_or_cite_itself(channel, text):
    draft = _draft()
    edit = next(tool for tool in _build_tools(draft) if tool.name == "edit_claim")
    edit.invoke({"path": PATH, "anchor_id": "aa11", "new_text": text})
    assert any("no provenance at all" in v.detail for v in await _gate(draft, channel))


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_unchanged_uncited_claim_does_not_block_unrelated_edit_but_remains_auditable(channel):
    draft = _draft("- Legacy note. <!-- c:bb22 -->\n"
                   "- Alice visited Canada. [cite: source-a ¶0] <!-- c:aa11 -->")
    draft.edit_claim(PATH, "aa11", "Alice travelled to Canada. [cite: source-a ¶0]")
    assert await _gate(draft, channel) == []
    audit = check_claim_provenance(draft.documents(), draft.base_documents(), audit=True)
    assert len(audit) == 1 and "c:bb22" in audit[0].detail


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_revision_can_derive_from_existing_cross_document_claim(channel):
    draft = PatchDraft.from_canonical([
        _doc(PATH, "- Alice travelled. [cite: source-a ¶0] <!-- c:aa11 -->"),
        _doc("people/bob.md", "- Bob accompanied Alice. [cite: source-a ¶0] <!-- c:bb22 -->"),
    ], TEMPLATES)
    draft.edit_claim(PATH, "aa11", "Alice had a travelling companion. c:bb22")
    assert await _gate(draft, channel) == []


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_anchor_prefix_is_not_a_reference(channel):
    draft = _draft()
    draft.append_block(PATH, "Notes", "A derived claim. c:aa11extra")
    assert any("no provenance at all" in v.detail for v in await _gate(draft, channel))


@pytest.mark.parametrize("body", ["A new assertion.", "A claim. [cite: source-a]"])
async def test_evolve_checks_new_claim_provenance_and_citation_shape(body):
    draft = _draft()
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"}, body)
    violations = await _gate(draft, "evolve")
    assert any(v.kind == "citation" for v in violations)
    if "[cite:" in body:
        assert any("does not parse as a locator" in v.detail for v in violations)


async def test_evolve_preserves_a_legacy_defect_across_a_verbatim_move():
    draft = _draft("- Legacy note. <!-- c:aa11 -->")
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"}, "## Notes\n")
    draft.move_claim(PATH, "aa11", "people/bob.md", "Notes")
    assert await _gate(draft, "evolve") == []
    audit = check_claim_provenance(draft.documents(), draft.base_documents(), audit=True)
    assert len(audit) == 1 and audit[0].path == "people/bob.md"


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_reference_cycle_without_a_source_is_not_provenance(channel):
    draft = PatchDraft.from_canonical([
        _doc(PATH, "- First fact. [cite: source-a ¶0] <!-- c:aa11 -->"),
        _doc("people/bob.md", "- Second fact. [cite: source-a ¶0] <!-- c:bb22 -->"),
    ], TEMPLATES)
    draft.edit_claim(PATH, "aa11", "First inference. c:bb22")
    draft.edit_claim("people/bob.md", "bb22", "Second inference. c:aa11")
    assert len([v for v in await _gate(draft, channel) if "no provenance" in v.detail]) == 2


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_new_derivation_can_reach_a_source_through_another_new_claim(channel):
    draft = _draft()
    updated = draft.append_block(PATH, "Notes", "A supported inference. c:aa11")
    middle = next(anchor for anchor in extract_anchors(updated.body) if anchor != "aa11")
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"},
                          f"Another inference. c:{middle}")
    assert await _gate(draft, channel) == []


async def test_evolve_cannot_derive_from_a_deleted_anchor():
    draft = _draft()
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"}, "Derived. c:aa11")
    draft.delete_claim(PATH, "aa11")
    assert any("no provenance at all" in v.detail for v in await _gate(draft, "evolve"))


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_new_catalog_metadata_cannot_exempt_an_authored_claim(channel):
    draft = _draft("- An ungrounded claim. <!-- c:aa11 -->")
    draft.edit_claim(PATH, "aa11", "A revised ungrounded claim.")
    draft.documents()[PATH].frontmatter["rollover_catalog_anchors"] = "aa11"
    assert any("no provenance" in v.detail for v in await _gate(draft, channel))


@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_legacy_admission_is_not_evidence_for_a_new_claim(channel):
    draft = _draft("- Legacy assertion. <!-- c:aa11 -->")
    draft.append_block(PATH, "Notes", "A new assertion based on legacy text. c:aa11")
    violations = await _gate(draft, channel)
    assert len(violations) == 1 and "A new assertion" in violations[0].detail


async def test_unchanged_transitive_dependants_are_rejected_when_evolve_deletes_their_basis():
    draft = PatchDraft.from_canonical([
        _doc(PATH, "- Original fact. [cite: source-a ¶0] <!-- c:aa11 -->"),
        _doc("people/bob.md", "- Derived fact. c:aa11 <!-- c:bb22 -->\n"
             "- Further inference. c:bb22 <!-- c:cc33 -->"),
    ], TEMPLATES)
    draft.delete_claim(PATH, "aa11")
    violations = await _gate(draft, "evolve")
    assert len(violations) == 2
    assert all(v.path == "people/bob.md" for v in violations)


def test_an_uncited_archived_claim_does_not_block_a_live_compile():
    archived = "archive/people/retired.md"
    draft = PatchDraft.from_canonical([
        _doc(archived, "- Old uncited assertion. <!-- c:bb22 -->"),
        _doc(PATH, "- Live fact. [cite: source-a ¶0] <!-- c:aa11 -->"),
    ], TEMPLATES)
    draft.edit_claim(PATH, "aa11", "A revised live fact. [cite: source-a ¶0]")
    assert run_gate(draft, [], known_source_bounds={"source-a": 1}) == []
    audit = check_claim_provenance(draft.documents(), draft.base_documents(), audit=True)
    assert len(audit) == 1 and audit[0].path == archived
