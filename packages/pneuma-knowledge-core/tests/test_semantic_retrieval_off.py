"""All answering lanes keep their lexical arms when embedding/vector ports are absent."""

from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.briefing import BriefingScope, briefing_ask, build_briefing
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall, retrieve_claims_multi
from pneuma_knowledge_core.recall.live_pipeline import evaluate_live_pipeline
from pneuma_knowledge_core.recall.rag import RAG_RETRIEVE_CHILDREN, RAG_STAGE_ORDER, rag_recall
from pneuma_knowledge_core.recall.stage_timing import StageRecorder

from test_deep_recall import FakeContent, _model, _tool_call
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeLexical, LexHit
from test_live_pipeline import FakeStructured, discovered, other, semantic_plan

USER = UserId("u-synthetic-lexical")
SID = SourceId("source-synthetic-survey")
AS_OF = datetime(2026, 8, 1, 12)
CLAIM = ClaimStub("abcd", "memory/topics/survey.md", "The delta marker is cobalt.",
                  citations=[{"source_id": str(SID), "block_start": 0, "block_end": 0}])


class Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"disabled vector arm touched {name}")


class Lexical(FakeLexical):
    def __init__(self):
        super().__init__([LexHit(SID, 0, "The delta marker is cobalt.")])
        self.queries = []

    async def search(self, user_id, query, **kwargs):
        assert user_id == USER
        self.queries.append(query)
        return await super().search(user_id, query, **kwargs)


class Claims(FakeClaimIndex):
    def __init__(self):
        super().__init__([CLAIM])
        self.queries = []

    async def search_claims(self, user_id, query, **kwargs):
        assert user_id == USER
        self.queries.append(query)
        return await super().search_claims(user_id, query, **kwargs)


def assert_skipped(result):
    stages = {stage.name: stage for stage in result.stages}
    for name in ("embed", "retrieve.vector", "episode_summaries"):
        assert stages[name].status == "skipped"
        assert stages[name].ms == 0


async def test_rag_keeps_exact_lexical_provenance_and_skips_embedding_and_both_vector_representations():
    stages = StageRecorder(RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN)
    hits = await rag_recall(USER, "cobalt", lexical=Lexical(), vectors=Forbidden(),
                            embeddings=None, stages=stages)
    assert hits and hits[0].paths == ("lexical",)
    assert (hits[0].source_id, hits[0].block_start, hits[0].block_end) == (SID, 0, 0)
    assert not hits[0].episode_summaries
    measured = {stage.name: stage for stage in stages.emit()}
    assert measured["embed"].status == "skipped"
    assert measured["retrieve.vector"].status == "skipped"
    assert measured["retrieve.lexical"].status == "ran"


@pytest.mark.parametrize("strategy", ["ranked", "all"])
async def test_fast_keeps_claims_and_raw_windows_but_never_builds_episode_summaries(monkeypatch, strategy):
    from pneuma_knowledge_core.recall import fast
    def forbidden(*args, **kwargs):
        raise AssertionError("episode summaries are disabled")
    monkeypatch.setattr(fast, "build_episode_summaries", forbidden)
    result = await fast_recall(
        USER, "cobalt", as_of=AS_OF, claim_lexical=Claims(), claim_vectors=Forbidden(),
        lexical=Lexical(), vectors=Forbidden(), embeddings=None, model=_model(AIMessage(content="Cobalt.")),
        evidence_only=True, evidence_strategy=strategy, fast_paths=(),
    )
    assert result.used_claims[0].paths == ("lexical",)
    assert result.used_windows and not result.used_episode_summaries
    assert any(ref.ref == f"{SID} ¶0" for ref in result.manifest)
    assert all(ref.kind != "episode" for ref in result.manifest)
    assert_skipped(result)


async def test_multiquery_claim_retrieval_does_not_embed():
    lexical = Claims()
    result = await retrieve_claims_multi(USER, ["cobalt", "delta"], claim_lexical=lexical,
                                         claim_vectors=Forbidden(), embeddings=None)
    assert result and result[0].paths == ("lexical",)
    assert lexical.queries == ["cobalt", "delta"]


async def test_deep_seed_and_mid_answer_searches_use_lexical_only():
    lexical, claims = Lexical(), Claims()
    model = _model(
        AIMessage(content="", tool_calls=[
            _tool_call("search_claims", {"query": "delta"}, "claims"),
            _tool_call("search_content", {"query": "marker"}, "content"),
        ]),
        AIMessage(content=f"Cobalt. [cite: {SID} ¶0]"),
    )
    result = await deep_recall(USER, "cobalt", as_of=AS_OF, claim_lexical=claims,
                               claim_vectors=Forbidden(), embeddings=None, model=model,
                               content=FakeContent(), lexical=lexical, vectors=Forbidden())
    assert claims.queries == ["cobalt", "delta"]
    assert lexical.queries == ["cobalt", "marker"]
    tool_texts = [str(message.content) for messages in model.seen for message in messages if isinstance(message, ToolMessage)]
    assert any("cobalt" in text for text in tool_texts)
    assert any(ref.ref == f"{SID} ¶0" for ref in result.evidence_manifest)
    assert all(ref.kind != "episode" for ref in result.evidence_manifest)
    assert_skipped(result)


async def test_briefing_build_and_followup_search_keep_both_lexical_faces():
    lexical, claims = Lexical(), Claims()
    briefing = await build_briefing(USER, BriefingScope(query="cobalt"),
                                    snapshot=SnapshotRef(ref="synthetic-snapshot"), snapshot_docs=[],
                                    claim_lexical=claims, claim_vectors=Forbidden(), embeddings=None,
                                    lexical=lexical, vectors=Forbidden())
    assert "cobalt" in briefing.system_prefix
    assert claims.queries == lexical.queries == ["cobalt"]
    assert_skipped(briefing)
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("search_knowledge", {"query": "delta"}, "search")]),
        AIMessage(content=f"Cobalt. [cite: {SID} ¶0]"),
    )
    answer = await briefing_ask(briefing, "marker", as_of=AS_OF, model=model, content=FakeContent(),
                                claim_lexical=claims, claim_vectors=Forbidden(), embeddings=None,
                                lexical=lexical, vectors=Forbidden())
    assert claims.queries == lexical.queries == ["cobalt", "delta"]
    assert answer.evidence_manifest
    assert_skipped(answer)


async def test_live_context_retrieves_lexical_candidates_with_no_embedding_client():
    lexical, claims = Lexical(), Claims()
    discover = FakeStructured([discovered(intent="Find the delta marker", plan=semantic_plan("cobalt"), worth=9)])
    result = await evaluate_live_pipeline(
        USER, [other("What is the delta marker?")], as_of=AS_OF,
        discover_model=discover, pick_model=FakeStructured([]), paths=(),
        claim_lexical=claims, claim_vectors=Forbidden(), lexical=lexical, vectors=Forbidden(), embeddings=None,
    )
    assert claims.queries == lexical.queries == ["cobalt"]
    assert result.candidates
    assert all(str(citation.source_id) == str(SID) for card in result.candidates for citation in card.citations)
    states = {stage.name: stage.status for stage in result.stages}
    assert states["retrieve.semantic"] == "skipped"
    assert states["retrieve.lexical"] == "ran"
    assert_skipped(result)
