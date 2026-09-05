"""Changed canonical claims must not inherit admission merely by keeping their id."""

import pytest

from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
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
async def test_cited_revision_and_unchanged_legacy_claim_remain_admissible(channel):
    draft = _draft("- Legacy note. <!-- c:bb22 -->\n"
                   "- Alice visited Canada. [cite: source-a ¶0] <!-- c:aa11 -->")
    draft.edit_claim(PATH, "aa11", "Alice travelled to Canada. [cite: source-a ¶0]")
    assert await _gate(draft, channel) == []


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


async def test_evolve_keeps_unchanged_legacy_claim_when_moved():
    draft = _draft("- Legacy note. <!-- c:aa11 -->")
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"}, "## Notes\n")
    draft.move_claim(PATH, "aa11", "people/bob.md", "Notes")
    assert await _gate(draft, "evolve") == []


async def test_evolve_cannot_derive_from_a_deleted_anchor():
    draft = _draft()
    draft.create_document("people/bob.md", {"type": "person", "slug": "bob"}, "Derived. c:aa11")
    draft.delete_claim(PATH, "aa11")
    assert any("no provenance at all" in v.detail for v in await _gate(draft, "evolve"))
