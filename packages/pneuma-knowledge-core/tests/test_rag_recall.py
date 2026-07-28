"""rag_recall with in-memory fake ports: fusion order + dual-path markers."""

from dataclasses import dataclass

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.recall.rag import rag_recall

USER = UserId("u-test")


@dataclass
class FakeLexHit:
    source_id: SourceId
    block_index: int
    text: str
    score: float


@dataclass
class FakeVecHit:
    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    score: float


class FakeLexical:
    def __init__(self, hits):
        self._hits = hits

    async def index_blocks(self, *a, **k):  # unused
        raise NotImplementedError

    async def search(self, user_id, query, *, limit=20):
        assert user_id == USER
        return self._hits[:limit]


class FakeVector:
    def __init__(self, hits):
        self._hits = hits

    async def upsert_chunks(self, *a, **k):  # unused
        raise NotImplementedError

    async def search(self, user_id, embedding, *, limit=20):
        assert user_id == USER
        return self._hits[:limit]


class FakeEmbeddings:
    async def aembed_query(self, text):
        return [0.0, 0.0]

    async def aembed_documents(self, texts):
        return [[0.0, 0.0] for _ in texts]


async def test_span_hit_from_both_paths_is_marked_lexical_and_vector_and_ranks_first():
    # Lexical block 5 and a vector chunk [5,5] address the SAME span → one fused
    # hit carrying both markers, and agreement lifts it above single-path hits.
    lexical = FakeLexical(
        [
            FakeLexHit(SourceId("s1"), 5, "shared span text", 0.9),
            FakeLexHit(SourceId("s1"), 1, "lexical only", 0.5),
        ]
    )
    vectors = FakeVector(
        [
            FakeVecHit(SourceId("s1"), 5, 5, "shared span text", 0.8),
            FakeVecHit(SourceId("s1"), 8, 9, "vector only", 0.4),
        ]
    )
    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=10
    )

    top = hits[0]
    assert (top.source_id, top.block_start, top.block_end) == (SourceId("s1"), 5, 5)
    assert set(top.paths) == {"lexical", "vector"}

    by_span = {(h.block_start, h.block_end): h for h in hits}
    assert by_span[(1, 1)].paths == ("lexical",)
    assert by_span[(8, 9)].paths == ("vector",)
    # Union of both paths, no span lost.
    assert set(by_span) == {(5, 5), (1, 1), (8, 9)}


async def test_lexical_only_recall_still_returns_hits_when_vector_empty():
    lexical = FakeLexical([FakeLexHit(SourceId("s1"), 0, "only lexical", 0.7)])
    vectors = FakeVector([])
    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=10
    )
    assert len(hits) == 1
    assert hits[0].paths == ("lexical",)
    assert hits[0].text == "only lexical"


async def test_limit_is_respected():
    lexical = FakeLexical([FakeLexHit(SourceId("s1"), i, f"t{i}", 1.0) for i in range(5)])
    vectors = FakeVector([FakeVecHit(SourceId("s2"), i, i, f"v{i}", 1.0) for i in range(5)])
    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=3
    )
    assert len(hits) == 3
