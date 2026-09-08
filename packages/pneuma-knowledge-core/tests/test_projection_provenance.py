"""Synthetic source navigation over canonical chains, independent of index freshness."""

from dataclasses import replace

import pytest

from pneuma_knowledge_core.compile.gate import check_claim_provenance
from pneuma_knowledge_core.domain.canonical import CanonicalDocument, Citation
from pneuma_knowledge_core.recall.projection import (
    PROJECTION_V1, PROJECTION_V2, project_document_claims, project_snapshot_claims,
)
from pneuma_knowledge_core.recall.provenance import CanonicalProvenance, hydrate_claim_citations


def doc(path, body):
    return CanonicalDocument(doc_id=path, path=path, frontmatter={}, body=body)


def locators(citations):
    return [(str(c.source_id), c.block_start, c.block_end) for c in citations]


def chain_docs():
    return [
        doc("notes/a.md", "- Original. [cite: source-a ¶2-3] <!-- c:aa11 -->"),
        doc("notes/b.md", "- Derived. (c:aa11) <!-- c:bb22 -->"),
        doc("notes/c.md", "- Further inference. c:bb22 <!-- c:cc33 -->"),
    ]


def test_projection_follows_the_cross_document_chain_admitted_by_the_write_gate():
    docs = chain_docs()
    assert check_claim_provenance({d.path: d for d in docs}, {}) == []
    claims = project_snapshot_claims(docs)
    assert [locators(c.citations) for c in claims] == [[("source-a", 2, 3)]] * 3
    assert claims[1].text == "Derived. (c:aa11)"
    assert claims == project_snapshot_claims(list(reversed(docs)))


@pytest.mark.parametrize("source", ["", " [cite: source-a ¶2-3]"])
def test_cycles_terminate_and_only_source_reachable_cycles_provide_citations(source):
    docs = [doc("notes/a.md", f"- A c:bb22{source} <!-- c:aa11 -->\n"
                "- B c:aa11 <!-- c:bb22 -->")]
    expected = [("source-a", 2, 3)] if source else []
    # Resolve in both orders to catch a partial-cache result from a cycle traversal.
    for anchors in [("aa11", "bb22"), ("bb22", "aa11")]:
        resolver = CanonicalProvenance(docs)
        for anchor in anchors:
            assert locators(resolver.resolve("notes/a.md", anchor).citations) == expected


def test_self_and_supersession_markers_are_not_grounding_edges():
    docs = [doc("notes/a.md", "- Old. [cite: source-a ¶0] <!-- c:aa11 -->\n"
                "- Self reference c:bb22. <!-- c:bb22 --> <!-- supersedes: c:aa11 -->")]
    assert not CanonicalProvenance(docs).resolve("notes/a.md", "bb22").source_backed


def test_missing_branch_is_reported_even_when_another_branch_reaches_a_source():
    docs = chain_docs()
    docs[1] = doc("notes/b.md", "- Derived c:aa11 and c:ffff. <!-- c:bb22 -->")
    result = CanonicalProvenance(docs).resolve("notes/c.md", "cc33")
    assert result.source_backed
    assert result.missing_anchors == ("ffff",)
    assert result.root_found


@pytest.mark.parametrize("same_document", [True, False])
@pytest.mark.parametrize("identical", [True, False])
def test_duplicate_anchors_do_not_arbitrarily_choose_or_union_sources(same_document, identical):
    first = "- First. [cite: source-a ¶0] <!-- c:aa11 -->"
    second = "- Second. [cite: source-b ¶4] <!-- c:aa11 -->"
    if identical:
        second = first
    docs = ([doc("notes/a.md", first + "\n" + second)] if same_document else
            [doc("notes/a.md", first), doc("notes/b.md", second)])
    docs.append(doc("notes/c.md", "- Derived c:aa11. <!-- c:cc33 -->"))
    resolver = CanonicalProvenance(docs)
    result = resolver.resolve("notes/c.md", "cc33")
    assert result.citations == ()
    assert result.ambiguous_anchors == ("aa11",)
    assert resolver.resolve("notes/a.md", "aa11").ambiguous_anchors == ("aa11",)


def test_citations_are_deduplicated_by_exact_locator_without_merging_spans():
    docs = [doc("notes/a.md", "- Root c:bb22 c:cc33. [cite: z-source ¶9] <!-- c:aa11 -->\n"
                "- B. [cite: source-a ¶2-3] <!-- c:bb22 -->\n"
                "- C. [cite: source-a ¶2-3,3-4,7] <!-- c:cc33 -->")]
    expected = [("z-source", 9, 9), ("source-a", 2, 3), ("source-a", 3, 4), ("source-a", 7, 7)]
    assert locators(CanonicalProvenance(docs).resolve("notes/a.md", "aa11").citations) == expected


def test_only_supplied_documents_are_traversed_and_closed_volumes_remain_live():
    source = doc("archive/notes/a.md", "- Original. [cite: source-a ¶2-3] <!-- c:aa11 -->")
    root = doc("notes/b.md", "- Derived c:aa11. <!-- c:bb22 -->")
    result = CanonicalProvenance([root]).resolve(root.path, "bb22")
    assert result.citations == () and result.missing_anchors == ("aa11",)
    assert CanonicalProvenance([root, source]).resolve(root.path, "bb22").source_backed
    closed = source.model_copy(update={"path": "notes/a/a01.md"})
    assert CanonicalProvenance([root, closed]).resolve(root.path, "bb22").source_backed


def test_overviews_may_be_roots_but_are_not_ledger_reference_targets():
    overview = doc("notes/head.md", "<!-- overview -->\n<!-- overview:definition -->\n"
                   "Summary c:aa11. <!-- c:dd44 -->\n<!-- /overview -->")
    docs = [*chain_docs(), overview,
            doc("notes/other.md", "- Another head c:dd44. <!-- c:ee55 -->")]
    resolver = CanonicalProvenance(docs)
    assert resolver.resolve(overview.path, "dd44").source_backed
    result = resolver.resolve("notes/other.md", "ee55")
    assert result.citations == () and result.missing_anchors == ("dd44",)


@pytest.mark.parametrize("strategy", [PROJECTION_V1, PROJECTION_V2])
def test_hydration_replaces_stale_citations_only_with_matching_display_text(strategy):
    docs = chain_docs()
    docs[1] = docs[1].model_copy(update={"body": "## Notes\n" + docs[1].body})
    row = project_document_claims(docs[1], strategy)[0]
    row = replace(row, citations=(Citation(
        source_id="stale-source", block_start=8, block_end=8),))
    hydrated, results = hydrate_claim_citations([row], docs)
    assert hydrated[0] == replace(row, citations=results[(row.document_path, str(row.anchor))].citations)
    assert locators(hydrated[0].citations) == [("source-a", 2, 3)]
    assert row.text == hydrated[0].text
    assert results[(row.document_path, str(row.anchor))].text_matches
    assert locators(row.citations) == [("stale-source", 8, 8)]


def test_hydration_does_not_attach_new_sources_to_stale_text_under_the_same_anchor():
    before = doc("notes/a.md", "- Former state. [cite: old-source ¶0] <!-- c:aa11 -->")
    after = doc("notes/a.md", "- Corrected state. [cite: new-source ¶4] <!-- c:aa11 -->")
    row = project_document_claims(before)[0]
    hydrated, results = hydrate_claim_citations([row], [after])
    result = results[(row.document_path, str(row.anchor))]
    assert result.root_found and result.text_matches is False
    assert locators(result.citations) == [("new-source", 4, 4)]
    assert hydrated == [row] and hydrated[0] is row
    assert locators(hydrated[0].citations) == [("old-source", 0, 0)]


def test_missing_root_is_distinct_from_missing_ancestor_and_no_snapshot_is_a_noop():
    row = project_document_claims(chain_docs()[0])[0]
    assert hydrate_claim_citations([row], None) == ([row], {})
    hydrated, results = hydrate_claim_citations([row], [])
    result = results[(row.document_path, str(row.anchor))]
    assert hydrated == [row] and not result.root_found and result.text_matches is None
    assert not CanonicalProvenance([]).has_claim(row.document_path, str(row.anchor))
    resolver = CanonicalProvenance([chain_docs()[1]])
    assert resolver.has_claim("notes/b.md", "bb22")
    assert resolver.resolve("notes/b.md", "bb22").root_found


def test_long_reference_chain_does_not_use_python_recursion():
    blocks = [f"- Step c:{i + 1:04x}. <!-- c:{i:04x} -->" for i in range(1100)]
    blocks.append("- End. [cite: source-a ¶0] <!-- c:044c -->")
    result = CanonicalProvenance([doc("notes/a.md", "\n".join(blocks))]).resolve("notes/a.md", "0000")
    assert locators(result.citations) == [("source-a", 0, 0)]


def test_glance_uses_only_definition_slot_and_follows_cross_document_chains():
    from pneuma_knowledge_core.recall.live_pipeline import _definition_citations

    head = doc("notes/head.md", "<!-- overview -->\n<!-- overview:definition -->\n"
               "Definition c:cc33. <!-- c:dd44 -->\n<!-- overview:summary -->\n"
               "Unrelated summary. [cite: summary-source ¶9] <!-- c:ee55 -->\n<!-- /overview -->")
    docs = [*chain_docs(), head]
    assert locators(_definition_citations(head, {d.path: d for d in docs})) == [("source-a", 2, 3)]
    assert _definition_citations(head, {head.path: head}) == ()


def test_glance_preserves_a_directly_cited_definition_without_using_other_slots():
    from pneuma_knowledge_core.recall.live_pipeline import _definition_citations

    head = doc("notes/head.md", "<!-- overview -->\n<!-- overview:definition -->\n"
               "Definition. [cite: definition-source ¶4] <!-- c:dd44 -->\n"
               "<!-- overview:summary -->\nSummary. [cite: summary-source ¶9] <!-- c:ee55 -->\n"
               "<!-- /overview -->")
    assert locators(_definition_citations(head, {head.path: head})) == [("definition-source", 4, 4)]
