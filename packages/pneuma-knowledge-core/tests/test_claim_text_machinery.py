"""A claim's TEXT is words; the markers around it are the system's.

THE DEFECT THIS PINS
--------------------
A production library held claims like

    ... 发布协作 [cite: a97e… ¶0-18] <!-- c:__AUTO__ --> <!-- c:359a518a -->

— two statements the model meant to submit separately, glued into ONE claim by a separator
it invented. Nothing in the framework ever wrote `__AUTO__`: `ANCHOR_MARK_RE` matches
`[0-9a-f]{4,}` only, so the placeholder was not an anchor, `append_block_text`'s "the system
assigns anchors" guard looked straight through it, `_iter_content_blocks` read the whole line
as one block, and `assign_document_anchors` appended a REAL anchor at the end of the line —
leaving the dead marker standing in the middle of the sentence, indexed as part of the claim.

The cure is mechanical at both ends: the four write faces refuse the text, and the gate
refuses a page this round wrote that still carries one. A legacy page nobody touched is left
alone — and the display path renders it clean, which is exactly why the defect went unseen.
"""

from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.canonical_glance import claim_display_text
from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    block_text,
    text_machinery,
)
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.recall.projection import project_document_claims

TEMPLATES = ["memory/people/{slug}.md", "memory/topics/{slug}.md"]
PATH = "memory/people/cheng-ye.md"

#: The real shape, transcribed from the live library: two claims and an invented separator.
GLUED = (
    "【中】程野 跟进 CLI 上传。[cite: src-01 ¶0-2] <!-- c:__AUTO__ --> "
    "他同时向对方提供样本。[cite: src-01 ¶3]"
)


def _source() -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="conversation",
            title="t",
            mime="text/plain",
            checksum="src-01",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(6)],
        structure=StructureMap(),
    )


SOURCES = [_source()]


def _doc(body: str, path: str = PATH) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId("d1"),
        path=path,
        frontmatter={"doc_id": "d1", "type": "person", "slug": "cheng-ye"},
        body=body,
    )


# --- the pure helpers ---------------------------------------------------------


def test_block_text_stops_where_the_systems_markers_begin():
    block = "- 程野 转任架构师。[cite: src-01 ¶2] <!-- c:aa11 --> <!-- supersedes: c:bb22 -->"
    assert block_text(block) == "- 程野 转任架构师。[cite: src-01 ¶2]"
    assert text_machinery(block) is None


@pytest.mark.parametrize(
    "block",
    [
        GLUED,
        "- A <!-- c:aa11 --> B [cite: src-01 ¶1]",  # a REAL anchor, mid-text
        "- 归属待确认 <!-- c:__NEW__ --> [cite: src-01 ¶1]",
        "- 待补 __AUTO__ [cite: src-01 ¶1]",  # the bare placeholder, no comment wrapper
        "- 备注 <!-- TODO 补引用 [cite: src-01 ¶1]",  # a comment that never closes
    ],
)
def test_text_machinery_names_what_must_go(block):
    assert text_machinery(block) is not None


# --- the four write faces -----------------------------------------------------


def _draft() -> PatchDraft:
    draft = PatchDraft.from_canonical(
        [_doc("- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->")], TEMPLATES
    )
    draft.mark_read(PATH)
    return draft


def test_append_block_refuses_two_claims_glued_by_an_invented_marker():
    with pytest.raises(AnchorToolError) as err:
        _draft().append_block(PATH, "协作", GLUED)
    assert "append_block" in str(err.value)
    assert "two blocks" in str(err.value) or "两个块" in str(err.value)


def test_edit_claim_refuses_it_too():
    with pytest.raises(AnchorToolError):
        _draft().edit_claim(PATH, "aa11", GLUED)


def test_edit_claim_still_accepts_the_claims_own_trailing_anchor():
    """The refusal is about TEXT. Resubmitting the block's own anchor where the format puts
    it — at the end — has always been legal and stays legal."""
    doc = _draft().edit_claim(PATH, "aa11", "- 改写后。[cite: src-01 ¶1] <!-- c:aa11 -->")
    assert "aa11" in doc.body
    assert "__AUTO__" not in doc.body


def test_supersede_claim_refuses_it_too():
    with pytest.raises(AnchorToolError):
        _draft().supersede_claim(PATH, "aa11", GLUED)


def test_create_document_refuses_it_too():
    with pytest.raises(AnchorToolError):
        PatchDraft.from_canonical([], TEMPLATES).create_document(
            "memory/people/mei-lin.md",
            {"type": "person", "slug": "mei-lin"},
            GLUED,
        )


def test_a_clean_write_is_untouched_by_the_check():
    draft = _draft()
    draft.append_block(PATH, "协作", "- 他跟进了 CLI 上传。[cite: src-01 ¶2]")
    assert run_gate(draft, SOURCES) == []


# --- the gate -----------------------------------------------------------------


def test_the_gate_refuses_a_page_this_round_changed():
    """The final arbiter, for anything that reaches a draft without passing the tool face."""
    draft = PatchDraft.from_canonical(
        [_doc("- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->")], TEMPLATES
    )
    draft.documents()[PATH].body = f"- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->\n\n- {GLUED} <!-- c:bb22 -->"
    violations = run_gate(draft, SOURCES)
    assert "claim_text" in {v.kind for v in violations}
    assert any("__AUTO__" in v.detail for v in violations if v.kind == "claim_text")


def test_an_untouched_legacy_page_is_grandfathered():
    """32 pages of a real library carry this. A compile that is not writing them has no
    channel to repair them, and aborting over a page it never touched would strand the whole
    library. They converge on their next write — where the tool face refuses the text."""
    legacy = _doc(f"- {GLUED} <!-- c:bb22 -->")
    other = _doc("- 另一页。[cite: src-01 ¶1] <!-- c:cc33 -->", path="memory/topics/x.md")
    draft = PatchDraft.from_canonical([legacy, other], TEMPLATES)
    draft.mark_read("memory/topics/x.md")
    draft.append_block("memory/topics/x.md", "进展", "- 新的一条。[cite: src-01 ¶2]")
    assert [v for v in run_gate(draft, SOURCES) if v.kind == "claim_text"] == []


def test_but_the_same_page_answers_for_it_the_moment_the_round_writes_it():
    legacy = _doc(f"- {GLUED} <!-- c:bb22 -->")
    draft = PatchDraft.from_canonical([legacy], TEMPLATES)
    draft.mark_read(PATH)
    draft.append_block(PATH, "进展", "- 新的一条。[cite: src-01 ¶2]")
    assert "claim_text" in {v.kind for v in run_gate(draft, SOURCES)}


# --- what a person and an index see -------------------------------------------


def test_the_display_path_renders_a_legacy_claim_clean():
    """`claim_display_text` strips every comment — which is why this was invisible for so
    long. It stays that way: a reader of a grandfathered page should see the words, not the
    machinery. The gate, not the renderer, is where the defect is now named."""
    rendered = claim_display_text(f"- {GLUED} <!-- c:bb22 -->")
    assert "__AUTO__" not in rendered and "<!--" not in rendered
    assert "程野 跟进 CLI 上传" in rendered


def test_and_the_claim_index_no_longer_carries_the_marker_either():
    """The projection used to strip only the two markers it could name, so `__AUTO__` was
    indexed and searched as part of the claim. Derived layers rebuild; this lands on the next
    `rebuild_derived`."""
    claims = project_document_claims(_doc(f"- {GLUED} <!-- c:bb22 -->"))
    assert claims and "__AUTO__" not in claims[0].text and "<!--" not in claims[0].text
