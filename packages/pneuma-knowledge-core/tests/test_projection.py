"""Canonical → claim projection parsing (M4)."""

from __future__ import annotations

from pneuma_knowledge_core.domain.canonical import (
    CanonicalDocument,
    iter_canonical_citations,
    normalize_canonical_citation_markers,
    resolve_canonical_citation_source_prefixes,
)
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId
from pneuma_knowledge_core.recall.projection import (
    PROJECTION_V1,
    PROJECTION_V2,
    claims_citing,
    project_document_claims,
    project_snapshot_claims,
)

_BODY = (
    "## 程野\n\n"
    "- 程野 是后端负责人。[cite: s1 ¶0] <!-- c:aaaa -->\n"
    "- 别名「欧文」。[cite: s1 ¶2] <!-- c:bbbb -->\n\n"
    "## 交付\n\n"
    "下周交付演示稿。[cite: s2 ¶1-3] <!-- c:cccc -->\n"
)


def _doc(path: str = "memory/people/cheng-ye.md", body: str = _BODY) -> CanonicalDocument:
    return CanonicalDocument(
        pneuma_id=DocumentId("doc-cheng-ye"), path=path, frontmatter={"type": "person"}, body=body
    )


def test_projects_one_claim_per_anchor_with_section_and_citations():
    claims = project_document_claims(_doc())
    assert [str(c.anchor) for c in claims] == ["aaaa", "bbbb", "cccc"]

    a = claims[0]
    assert a.section_path == ("程野",)
    assert a.text == "程野 是后端负责人。"  # bullet, cite marker, anchor all stripped
    assert len(a.citations) == 1
    assert str(a.citations[0].source_id) == "s1"
    assert (a.citations[0].block_start, a.citations[0].block_end) == (0, 0)

    c = claims[2]
    assert c.section_path == ("交付",)
    assert c.text == "下周交付演示稿。"
    assert (c.citations[0].block_start, c.citations[0].block_end) == (1, 3)


def test_projection_accepts_repeated_paragraph_marker_in_range():
    claims = project_document_claims(
        _doc(
            body=(
                "## 证据\n\n"
                "- 模型生成的自然区间写法。"
                "[cite: s1 ¶ 1 - ¶ 3] <!-- c:dddd -->"
            )
        )
    )
    assert claims[0].text == "模型生成的自然区间写法。"
    assert [
        (
            str(citation.source_id),
            citation.block_start,
            citation.block_end,
        )
        for citation in claims[0].citations
    ] == [("s1", 1, 3)]


def test_canonical_citation_normalizer_emits_one_stable_spelling():
    normalized, changes = normalize_canonical_citation_markers(
        "A [cite: s1 ¶ 1 - ¶ 3] B [cite: s2 ¶ 7]"
    )
    assert changes == 2
    assert normalized == "A [cite: s1 ¶1-3] B [cite: s2 ¶7]"


def test_grouped_citation_normalizes_and_expands_to_one_span_per_citation():
    grouped = "A [cite: s1 ¶ 1 - ¶ 2, 6, ¶ 8 - 9]"
    normalized, changes = normalize_canonical_citation_markers(grouped)
    assert changes == 1
    assert normalized == "A [cite: s1 ¶1-2] [cite: s1 ¶6] [cite: s1 ¶8-9]"
    assert [
        (str(citation.source_id), citation.block_start, citation.block_end)
        for citation in iter_canonical_citations(grouped)
    ] == [("s1", 1, 2), ("s1", 6, 6), ("s1", 8, 9)]


def test_projection_strips_grouped_marker_and_keeps_every_span_structured():
    claims = project_document_claims(
        _doc(
            body=(
                "## 证据\n\n"
                "- 同一来源的离散证据。"
                "[cite: s1 ¶1-2,6,8-9] <!-- c:eeee -->"
            )
        )
    )
    assert claims[0].text == "同一来源的离散证据。"
    assert "[cite:" not in claims[0].text
    assert [
        (str(citation.source_id), citation.block_start, citation.block_end)
        for citation in claims[0].citations
    ] == [("s1", 1, 2), ("s1", 6, 6), ("s1", 8, 9)]


def test_canonical_citation_prefix_repair_requires_one_unique_real_source():
    valid_ids = {
        "352690b742381abc55c984a706b1c6c0",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab",
    }
    repaired, changes, unresolved = resolve_canonical_citation_source_prefixes(
        "A [cite: 352690b742381abc55c984a706b1c6 ¶1-4] "
        "B [cite: aaaaaaaaaaaaaaaa ¶0] "
        "C [cite: missing-source ¶2]",
        valid_ids,
    )
    assert changes == 1
    assert repaired == (
        "A [cite: 352690b742381abc55c984a706b1c6c0 ¶1-4] "
        "B [cite: aaaaaaaaaaaaaaaa ¶0] "
        "C [cite: missing-source ¶2]"
    )
    assert unresolved == {"aaaaaaaaaaaaaaaa", "missing-source"}


def test_snapshot_projection_is_deterministic_by_path():
    docs = [
        _doc(path="memory/people/cheng-ye.md"),
        _doc(path="memory/topics/delivery.md", body="## T\n\n事项。[cite: s3 ¶0] <!-- c:dddd -->"),
    ]
    first = project_snapshot_claims(docs)
    second = project_snapshot_claims(list(reversed(docs)))
    # Sorted by document_path — input order does not matter.
    assert [(c.document_path, str(c.anchor)) for c in first] == [
        (c.document_path, str(c.anchor)) for c in second
    ]
    assert first[0].document_path == "memory/people/cheng-ye.md"


def test_projection_strategy_v2_folds_section_context_without_changing_rows():
    # M5 Path A: a derived projection-strategy upgrade re-renders the same claims from
    # the same canonical body — same row count + same anchors, enriched retrieval text.
    v1 = project_document_claims(_doc(), PROJECTION_V1)
    v2 = project_document_claims(_doc(), PROJECTION_V2)
    assert [str(c.anchor) for c in v1] == [str(c.anchor) for c in v2]  # rows unchanged
    # v1 text is bare; v2 text carries the section breadcrumb so the claim is
    # self-contained for lexical/semantic retrieval.
    assert v1[0].text == "程野 是后端负责人。"
    assert v2[0].text == "[程野] 程野 是后端负责人。"
    assert v2[2].text == "[交付] 下周交付演示稿。"
    # Default strategy is v1 (existing callers/worker unchanged).
    assert [c.text for c in project_document_claims(_doc())] == [c.text for c in v1]


def test_claims_citing_reverse_lookup():
    claims = project_document_claims(_doc())
    citing_s1 = claims_citing(claims, SourceId("s1"))
    assert {str(c.anchor) for c in citing_s1} == {"aaaa", "bbbb"}
    assert [str(c.anchor) for c in claims_citing(claims, SourceId("s2"))] == ["cccc"]
