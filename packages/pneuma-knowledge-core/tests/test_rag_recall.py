"""rag_recall with in-memory fake ports: fusion order + dual-path markers."""

from dataclasses import dataclass

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.recall import fast as fast_module
from pneuma_knowledge_core.recall.fast import retrieve_windows
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
    representation: str = "raw"
    episode_summary_text: str = ""


class FakeLexical:
    def __init__(self, hits):
        self._hits = hits
        self.limits = []

    async def index_blocks(self, *a, **k):  # unused
        raise NotImplementedError

    async def search(self, user_id, query, *, limit=20):
        assert user_id == USER
        self.limits.append(limit)
        return self._hits[:limit]


class FakeVector:
    def __init__(self, raw_hits, episode_hits=()):
        self._hits = {"raw": list(raw_hits), "episode": list(episode_hits)}
        self.limits = []

    async def upsert_chunks(self, *a, **k):  # unused
        raise NotImplementedError

    async def search(self, user_id, embedding, *, limit=20, representation="raw"):
        assert user_id == USER
        self.limits.append((representation, limit))
        return self._hits[representation][:limit]


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


async def test_raw_and_episode_rank_independently_then_deduplicate_by_source_span():
    lexical = FakeLexical([])
    vectors = FakeVector(
        [FakeVecHit(SourceId("s1"), 2, 3, "verbatim episode", 0.9, "raw")],
        [
            FakeVecHit(
                SourceId("s1"),
                2,
                3,
                "verbatim episode",
                0.8,
                "episode",
                "[episode description] Weekend kayaking and safety planning",
            )
        ],
    )

    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=8
    )

    assert len(hits) == 1
    assert (hits[0].source_id, hits[0].block_start, hits[0].block_end) == (
        SourceId("s1"), 2, 3
    )
    assert hits[0].paths == ("vector",)
    assert set(hits[0].representations) == {"raw", "episode"}
    summary = hits[0].episode_summaries[0]
    assert (summary.source_id, summary.block_start, summary.block_end) == (
        SourceId("s1"),
        2,
        3,
    )
    assert summary.text == "[episode description] Weekend kayaking and safety planning"


async def test_broad_episode_ranking_signal_cannot_displace_precise_raw_evidence():
    lexical = FakeLexical([])
    vectors = FakeVector(
        [
            FakeVecHit(SourceId("other"), 0, 0, "other raw", 1.0, "raw"),
            FakeVecHit(SourceId("s1"), 3, 3, "precise caption and raw", 0.9, "raw"),
        ],
        [
            FakeVecHit(
                SourceId("s1"), 2, 5, "broad episode", 1.0, "episode",
                "[episode description] One broad but dense episode summary",
            )
        ],
    )

    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=8
    )

    by_source = {hit.source_id: hit for hit in hits}
    kept = by_source[SourceId("s1")]
    assert (kept.block_start, kept.block_end, kept.text) == (
        3,
        3,
        "precise caption and raw",
    )
    assert set(kept.representations) == {"raw", "episode"}
    # Ranking may attach an episode signal to the precise raw winner, but the summary keeps
    # the episode's own truthful source interval rather than inheriting the raw slice.
    assert (
        kept.episode_summaries[0].block_start,
        kept.episode_summaries[0].block_end,
    ) == (2, 5)
    # The episode still contributes prominence, but overlap does not multiply scores.
    assert kept.score == 1 / 60


async def test_lexical_raw_agreement_is_not_displaced_by_an_episode_only_hit():
    lexical = FakeLexical([FakeLexHit(SourceId("exact"), 4, "March 17", 1.0)])
    vectors = FakeVector(
        [FakeVecHit(SourceId("exact"), 4, 4, "March 17", 1.0, "raw")],
        [FakeVecHit(SourceId("broad"), 8, 12, "A broad timeline episode", 1.0, "episode")],
    )

    hits = await rag_recall(
        USER, "March 17", lexical=lexical, vectors=vectors,
        embeddings=FakeEmbeddings(), limit=2
    )

    assert hits[0].source_id == SourceId("exact")
    assert set(hits[0].paths) == {"lexical", "vector"}
    assert {hit.source_id for hit in hits} == {SourceId("exact"), SourceId("broad")}


async def test_raw_natural_unit_owns_overlapping_lexical_only_block():
    lexical = FakeLexical([FakeLexHit(SourceId("s1"), 20, "candidate name", 1.0)])
    vectors = FakeVector(
        [
            FakeVecHit(
                SourceId("s1"), 20, 21,
                "candidate name\nstrong evaluation", 1.0, "raw",
            )
        ],
        [],
    )

    hits = await rag_recall(
        USER, "candidate name", lexical=lexical, vectors=vectors,
        embeddings=FakeEmbeddings(), limit=8,
    )

    assert len(hits) == 1
    assert (hits[0].block_start, hits[0].block_end) == (20, 21)
    assert hits[0].text == "candidate name\nstrong evaluation"
    assert set(hits[0].representations) == {"lexical", "raw"}


async def test_post_retrieval_dedup_does_not_chain_overlapping_episodes_into_one_window():
    lexical = FakeLexical([])
    vectors = FakeVector(
        [
            FakeVecHit(SourceId("s1"), 0, 2, "raw A", 1.0, "raw"),
            FakeVecHit(SourceId("s1"), 4, 6, "raw C", 0.9, "raw"),
        ],
        [FakeVecHit(SourceId("s1"), 2, 4, "episode B", 1.0, "episode")],
    )

    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=8
    )

    # B overlaps A and C, but A and C are distinct evidence. Greedy rank-order suppression
    # drops the duplicate bridge instead of transitively expanding A+B+C into [0, 6].
    assert [(hit.block_start, hit.block_end) for hit in hits] == [(0, 2), (4, 6)]


async def test_each_path_overfetches_before_post_retrieval_dedup():
    lexical = FakeLexical([])
    vectors = FakeVector([], [])

    await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=8
    )

    assert lexical.limits == [16]
    assert vectors.limits == [("raw", 16), ("episode", 16)]


async def test_overlapping_representation_does_not_multiply_the_winning_span_score():
    lexical = FakeLexical([FakeLexHit(SourceId("s1"), 3, "exact", 1.0)])
    vectors = FakeVector(
        [FakeVecHit(SourceId("s1"), 3, 3, "exact", 1.0, "raw")],
        [FakeVecHit(SourceId("s1"), 2, 4, "broad episode", 1.0, "episode")],
    )

    hits = await rag_recall(
        USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings(), limit=8
    )

    assert len(hits) == 1
    assert (hits[0].block_start, hits[0].block_end) == (3, 3)
    assert hits[0].score == 2 / 60
    assert set(hits[0].paths) == {"lexical", "vector"}


async def test_answer_windows_use_ordinary_fusion_without_semantic_quota(monkeypatch):
    seen: dict[str, int] = {}

    async def fake_rag_recall(*args, **kwargs):  # noqa: ANN002, ANN003
        seen.update(limit=kwargs["limit"])
        assert "semantic_floor" not in kwargs
        return []

    monkeypatch.setattr(fast_module, "rag_recall", fake_rag_recall)
    await retrieve_windows(
        USER,
        "q",
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        embeddings=FakeEmbeddings(),
        limit=8,
    )

    assert seen == {"limit": 8}
