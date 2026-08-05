"""The fast lane's opt-in retrieval stages: query planning and claim reranking.

Both stages are additive by contract: planning degrades to the single verbatim query,
reranking degrades to the fused pool head, and neither can lose recall relative to the
un-staged lane. These tests pin exactly those guarantees plus the mechanical consumption
of model output (dedup, cap, index validation)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ports.reranker import RerankResult
from pneuma_knowledge_core.recall.fast import (
    QueryPlan,
    plan_retrieval_queries,
    rerank_claims,
    retrieve_claims,
    retrieve_claims_multi,
    RetrievedClaim,
)

UID = UserId("u-rerank-test")


# ------------------------------------------------------------------ fakes


class _PlanModel(BaseChatModel):
    """Structured-output fake returning one scripted `QueryPlan` (or failing on demand)."""

    queries: list[str] = []
    raise_with: Any = None
    parsed_override: Any = "__unset__"
    seen: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "plan-fake"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self

        class _Structured:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.seen.append(list(messages))
                if outer.raise_with is not None:
                    raise outer.raise_with
                parsed = (
                    QueryPlan(queries=list(outer.queries))
                    if outer.parsed_override == "__unset__"
                    else outer.parsed_override
                )
                return {
                    "raw": AIMessage(
                        content="",
                        usage_metadata={
                            "input_tokens": 5,
                            "output_tokens": 2,
                            "total_tokens": 7,
                        },
                    ),
                    "parsed": parsed,
                    "parsing_error": None,
                }

        return _Structured()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="x"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages)


@dataclass
class ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class QueryKeyedClaimIndex:
    """Claim index whose hits depend on the query (lexical face) or on which embedding
    arrives (vector face) — enough to observe the multi-query pooling."""

    def __init__(self, by_query: dict[str, list[ClaimStub]], default: list[ClaimStub] | None = None) -> None:
        self._by_query = by_query
        self._default = default or []

    async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
        key = query_or_embedding if isinstance(query_or_embedding, str) else "__vector__"
        return list(self._by_query.get(key, self._default))[:limit]


class FakeEmbeddings:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class ScriptedReranker:
    def __init__(self, results: list[RerankResult] | None = None, raise_with: Any = None, delay: float = 0.0) -> None:
        self.results = results or []
        self.raise_with = raise_with
        self.delay = delay
        self.seen: list[tuple[str, list[str], int]] = []

    async def rerank(self, query, documents, *, top_n):  # noqa: ANN001
        self.seen.append((query, list(documents), top_n))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.results)


def _claim(anchor: str, text: str) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=anchor, document_path="work/p.md", section_path=(), text=text, citations=()
    )


# ------------------------------------------------------------------ planning pass


async def test_planning_dedupes_against_the_question_and_caps():
    model = _PlanModel(
        queries=["  Milestone Date ", "milestone date", "WHO OWNS IT", "", "extra", "over-cap"],
        seen=[],
    )
    planned, usage, degraded = await plan_retrieval_queries(
        model, "milestone date", cap=2
    )
    # The question itself is never replanned (case-insensitive), blanks vanish, cap holds.
    assert planned == ("WHO OWNS IT", "extra")
    assert degraded is None
    assert usage["input_tokens"] == 5


async def test_planning_failure_degrades_to_no_extra_queries():
    model = _PlanModel(raise_with=RuntimeError("provider down"), seen=[])
    planned, usage, degraded = await plan_retrieval_queries(model, "q", cap=3)
    assert planned == ()
    assert degraded == "error"
    model = _PlanModel(parsed_override=None, seen=[])
    planned, _usage, degraded = await plan_retrieval_queries(model, "q", cap=3)
    assert planned == ()
    assert degraded == "error"


# ------------------------------------------------------------------ multi-query pooling


async def test_single_query_multi_is_byte_identical_to_retrieve_claims():
    hits = [ClaimStub("a1", "work/p.md", "claim one"), ClaimStub("a2", "work/p.md", "claim two")]
    lexical = QueryKeyedClaimIndex({"q": hits})
    vectors = QueryKeyedClaimIndex({"__vector__": hits})
    single = await retrieve_claims(
        UID, "q", claim_lexical=lexical, claim_vectors=vectors, embeddings=FakeEmbeddings(), limit=10
    )
    pooled = await retrieve_claims_multi(
        UID, ["q"], claim_lexical=lexical, claim_vectors=vectors, embeddings=FakeEmbeddings(), limit=10
    )
    assert pooled == single


async def test_containment_dedup_keeps_the_complete_statement_at_the_better_rank():
    # Same fact filed twice (a compensation compile re-stating a claim, longer): the
    # contained/equal text is dropped, the complete one takes the earlier rank, and the
    # freed slot refills from the tail instead of shrinking the budget.
    short = ClaimStub("a1", "work/p.md", "里程碑定在 8 月 15 日")
    long = ClaimStub("b7", "work/q.md", "里程碑定在 8 月 15 日，验收人是林知远")
    other = ClaimStub("c2", "work/r.md", "另一条无关的事实")
    lexical = QueryKeyedClaimIndex({"q": [short, long, other]})
    vectors = QueryKeyedClaimIndex({}, default=[])
    claims = await retrieve_claims(
        UID, "q", claim_lexical=lexical, claim_vectors=vectors,
        embeddings=FakeEmbeddings(), limit=3,
    )
    # The contained duplicate is gone, the complete statement holds its better rank, and
    # nothing else is lost.
    assert [c.anchor for c in claims] == ["b7", "c2"]


async def test_pool_cap_hands_the_full_union_past_the_per_query_limit():
    # `limit` is per-query/per-face retrieval depth; with a larger pool_cap the fused
    # union is NOT pre-truncated by score-blind RRF — a reranking caller must see every
    # candidate, or reranking judges a pool that fusion already amputated.
    a = [ClaimStub(f"a{i}", "work/p.md", f"claim a{i}") for i in range(3)]
    b = [ClaimStub(f"b{i}", "work/p.md", f"claim b{i}") for i in range(3)]
    lexical = QueryKeyedClaimIndex({"qa": a, "qb": b})
    vectors = QueryKeyedClaimIndex({}, default=[])
    truncated = await retrieve_claims_multi(
        UID, ["qa", "qb"], claim_lexical=lexical, claim_vectors=vectors,
        embeddings=FakeEmbeddings(), limit=3,
    )
    assert len(truncated) == 3  # default: pool_cap = limit (today's behavior)
    full = await retrieve_claims_multi(
        UID, ["qa", "qb"], claim_lexical=lexical, claim_vectors=vectors,
        embeddings=FakeEmbeddings(), limit=3, pool_cap=100,
    )
    assert {c.anchor for c in full} == {c.anchor for c in a + b}


async def test_multi_query_pool_surfaces_each_querys_hits():
    # Query A finds only claim-a lexically, query B only claim-b; the pool carries both —
    # exactly what one blended query cannot guarantee.
    claim_a = ClaimStub("a", "work/p.md", "aspect A fact")
    claim_b = ClaimStub("b", "work/p.md", "aspect B fact")
    lexical = QueryKeyedClaimIndex({"aspect A": [claim_a], "aspect B": [claim_b]})
    vectors = QueryKeyedClaimIndex({}, default=[])
    pooled = await retrieve_claims_multi(
        UID,
        ["aspect A", "aspect B"],
        claim_lexical=lexical,
        claim_vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
    )
    assert {c.anchor for c in pooled} == {"a", "b"}


# ------------------------------------------------------------------ rerank pass


async def test_rerank_orders_by_score_and_stamps_scores():
    candidates = [_claim("a", "noise"), _claim("b", "the answer"), _claim("c", "context")]
    reranker = ScriptedReranker(
        [RerankResult(1, 0.95), RerankResult(2, 0.40), RerankResult(0, 0.05)]
    )
    ordered, degraded = await rerank_claims(reranker, "q", candidates, cap=2)
    assert [c.anchor for c in ordered] == ["b", "c"]
    assert ordered[0].score == 0.95  # the reranker's judgement is kept, not hidden
    assert degraded is None
    # The whole pool was submitted for scoring.
    assert reranker.seen[0][1] == ["noise", "the answer", "context"]


async def test_rerank_ignores_invalid_indexes_and_backfills_from_the_pool():
    candidates = [_claim("a", "first"), _claim("b", "second"), _claim("c", "third")]
    reranker = ScriptedReranker([RerankResult(9, 0.9), RerankResult(1, 0.8)])
    ordered, degraded = await rerank_claims(reranker, "q", candidates, cap=3)
    # Index 9 does not exist → discarded; unscored claims backfill in pool order, so
    # nothing retrieved is ever lost to a sparse rerank.
    assert [c.anchor for c in ordered] == ["b", "a", "c"]
    assert degraded is None


async def test_rerank_failure_returns_the_pool_head_unchanged():
    candidates = [_claim("a", "first"), _claim("b", "second"), _claim("c", "third")]
    ordered, degraded = await rerank_claims(
        ScriptedReranker(raise_with=RuntimeError("boom")), "q", candidates, cap=2
    )
    assert [c.anchor for c in ordered] == ["a", "b"]
    assert degraded == "error"
    ordered, degraded = await rerank_claims(
        ScriptedReranker(delay=0.05), "q", candidates, cap=2, timeout=0.01
    )
    assert [c.anchor for c in ordered] == ["a", "b"]
    assert degraded == "timeout"


async def test_rerank_of_nothing_is_nothing():
    ordered, degraded = await rerank_claims(ScriptedReranker(), "q", [], cap=5)
    assert ordered == [] and degraded is None
