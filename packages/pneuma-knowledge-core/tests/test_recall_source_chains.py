"""Old direct-only indexes must navigate canonical source chains during real recall."""

from datetime import datetime

import pytest
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.canonical import CanonicalDocument, Citation
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.recall import fast as fast_module
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import EvidenceSelection, StructuredRecallAnswer

from test_deep_recall import ScriptedToolModel
from test_fast_recall import ClaimStub, FakeEmbeddings
from test_quality_context_selection import StructuredModel


USER = UserId("source-chain-owner")
SOURCE = SourceId("synthetic-valve-review")
AS_OF = datetime(2026, 1, 15)
ROOT_PATH = "subjects/shipping.md"
ROOT_TEXT = "Valve shipping approval remains conditional (c:cc33)."
SOURCE_TEXT = (
    "Indoor testing passed.",
    "Outdoor shipping still requires a corrosion assessment.",
)
EXPECTED_CITATIONS = (
    Citation(source_id=SOURCE, block_start=0, block_end=1),
)


class OldClaimIndex:
    """Only the dependent claim is retrieved; its old projection has no source locator."""

    def __init__(self, *, empty=False):
        self.rows = [] if empty else [ClaimStub("bb22", ROOT_PATH, ROOT_TEXT)]
        self.calls = []

    async def search_claims(self, user_id, query_or_embedding, *, limit=40, include_archived=False):
        assert user_id == USER
        self.calls.append((query_or_embedding, include_archived))
        return self.rows[:limit]


class SourceContent:
    def __init__(self, *, archived=False):
        self.archived = archived
        self.reads = []
        self.source = NormalizedSource.model_validate({
            "raw": {
                "source_id": SOURCE, "user_id": USER, "kind": "document",
                "title": "Valve review", "mime": "text/plain", "checksum": "synthetic",
                "created_at": "2026-01-14T00:00:00Z",
            },
            "blocks": [{"index": index, "text": text} for index, text in enumerate(SOURCE_TEXT)],
            "structure": {"sections": []},
        })

    async def archived_source_ids(self, user_id):
        assert user_id == USER
        return {SOURCE} if self.archived else set()

    async def get(self, user_id, source_id):
        assert user_id == USER
        assert source_id == SOURCE
        self.reads.append((user_id, source_id))
        return self.source


def documents(kind):
    root = CanonicalDocument(
        doc_id="shipping", path=ROOT_PATH,
        body=f"# Shipping\n\n- {ROOT_TEXT} <!-- c:bb22 -->\n",
    )
    middle = CanonicalDocument(
        doc_id="release", path="subjects/release.md",
        body="# Release\n\n- Valve release follows the review (c:aa11). <!-- c:cc33 -->\n",
    )
    ancestor = CanonicalDocument(
        doc_id="valve", path=("archive/" if kind == "archived" else "") + "subjects/valve.md",
        body=(
            "# Valve\n\n- Approval is conditional "
            + ("(c:bb22)." if kind == "source_free" else f"[cite: {SOURCE} ¶0-1]")
            + " <!-- c:aa11 -->\n"
        ),
    )
    return [root, middle, ancestor]


SCOPES = [
    pytest.param("live", False, True, id="live-cross-document-chain"),
    pytest.param("archived", False, False, id="archived-ancestor-excluded"),
    pytest.param("archived", True, True, id="archived-ancestor-requested"),
    pytest.param("source_free", False, False, id="source-free-cycle"),
]


@pytest.mark.parametrize("kind,include_archived,source_backed", SCOPES)
async def test_fast_select_resolves_old_index_chain_before_selection_and_l0_assembly(
    monkeypatch, kind, include_archived, source_backed,
):
    content = SourceContent(archived=kind == "archived")
    index = OldClaimIndex()
    selector = StructuredModel(parsed=EvidenceSelection(claims=[0]), seen=[])
    answerer = StructuredModel(parsed=StructuredRecallAnswer(
        answer_kind="fact", answer="Review checked.",
        citations=["[cite: s01 ¶0-1]"] if source_backed else [],
    ), seen=[])
    offered = []
    select_evidence = fast_module.select_evidence

    async def observe_selection(*args, **kwargs):
        # Observe the native selector's input; its model call, validation and assembly run.
        offered.extend(kwargs["claims"])
        return await select_evidence(*args, **kwargs)

    monkeypatch.setattr(fast_module, "select_evidence", observe_selection)
    result = await fast_module.fast_recall(
        USER, "Can the valve ship outdoors?", as_of=AS_OF,
        claim_lexical=index, claim_vectors=OldClaimIndex(empty=True),
        embeddings=FakeEmbeddings(), model=selector, answer_model=answerer,
        content=content, documents=documents(kind), fast_paths=(),
        evidence_strategy="select", answer_format="structured", include_archived=include_archived,
        archive_active=kind == "archived",
    )

    expected = EXPECTED_CITATIONS if source_backed else ()
    assert len(offered) == 1 and offered[0].citations == expected
    assert result.used_claims[0].citations == expected
    assert index.rows[0].citations == []  # No reindex or mutation is needed.
    assert result.model_selected_claims == 1
    assert result.evidence_selection_degraded is None
    assert result.answer_format_degraded is None
    assert len(selector.seen) == 1 and "C0:" in selector.seen[0][1].content
    assert result.expanded_documents == ()
    human = answerer.seen[0][1].content
    if source_backed:
        assert content.reads == [(USER, SOURCE)]
        assert len(result.used_windows) == 1
        passage = result.used_windows[0]
        assert (passage.source_id, passage.block_start, passage.block_end) == (SOURCE, 0, 1)
        assert passage.text == "\n".join(SOURCE_TEXT)
        assert passage.archived is (kind == "archived")
        assert SOURCE_TEXT[1] in human
        handle = next(handle for handle, source in result.citation_handles.items() if source == SOURCE)
        assert f"[cite: {handle} ¶0-1]" in human
        assert f"[cite: {handle} ¶0-1]" in result.answer
    else:
        assert content.reads == []
        assert result.used_windows == ()
        assert result.citation_handles == {}
        assert "[cite:" not in human
        assert SOURCE_TEXT[1] not in human


@pytest.mark.parametrize("kind,include_archived,source_backed", SCOPES)
async def test_deep_seed_and_search_claims_expose_only_scoped_source_chain_locators(
    kind, include_archived, source_backed,
):
    content = SourceContent(archived=kind == "archived")
    index = OldClaimIndex()
    model = ScriptedToolModel(turns=[
        AIMessage(content="", tool_calls=[{
            "name": "search_claims", "args": {"query": "valve approval"}, "id": "review",
        }]),
        AIMessage(content="Review located."),
    ], seen=[])
    result = await deep_recall(
        USER, "Which source supports the valve shipping condition?", as_of=AS_OF,
        claim_lexical=index, claim_vectors=OldClaimIndex(empty=True),
        embeddings=FakeEmbeddings(), model=model, content=content,
        documents=documents(kind), include_archived=include_archived,
        archive_active=kind == "archived",
    )

    seed = model.seen[0][1].content
    searched = next(message.content for message in model.seen[-1] if message.type == "tool")
    expected = EXPECTED_CITATIONS if source_backed else ()
    assert result.used_claims[0].citations == expected
    assert len(index.calls) == 2  # Both seed search and the real agent tool execute.
    assert all(archived is include_archived for _, archived in index.calls)
    assert index.rows[0].citations == []
    assert content.reads == []  # Locators come from canonical; L0 is still available to fetch.
    for evidence in (seed, searched):
        assert ROOT_TEXT in evidence
        if source_backed:
            assert f"[cite: {SOURCE} ¶0-1]" in evidence
        else:
            assert "[cite:" not in evidence
            assert SOURCE not in evidence
