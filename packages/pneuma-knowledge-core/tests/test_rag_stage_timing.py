"""Per-stage wall-clock for the rag lane — the smallest fixed vocabulary of the four.

rag reaches no model at all: it embeds the question, asks two indexes, fuses the rankings and
merges the overlaps. So what is pinned here is the same set of properties the other fixed
vocabularies are pinned on, minus the ones a model call brings:

- the vocabulary is emitted COMPLETE and in `RAG_STAGE_ORDER`, children under their parent;
- a stage that did not run (a caller that already holds the query vector) is present and
  marked `skipped`, not missing — "was free" and "never happened" stay different facts;
- the two retrieval faces are SEQUENTIAL awaits, not a gather, so unlike the fast lane's the
  children sum to their parent rather than exceeding it, and a diagram is right to draw them
  as a chain;
- the live `end` events ARE the final list — one clock, so what a waiting reader watches and
  what the finished result carries cannot disagree;
- with no recorder passed, nothing changes: same hits, byte-for-byte.

Durations are asserted with floors only — a 40 ms sleep cannot report 10 ms — never with
ceilings: a loaded machine is allowed to be slow, and a test that failed when it was would be
measuring the box rather than the code.
"""

from __future__ import annotations

import asyncio

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.rag import (
    RAG_RETRIEVE_CHILDREN,
    RAG_STAGE_ORDER,
    rag_recall,
)
from pneuma_knowledge_core.recall.stage_timing import StageEvent, StageRecorder, child_name

from test_rag_recall import (
    USER,
    FakeEmbeddings,
    FakeLexHit,
    FakeLexical,
    FakeVecHit,
    FakeVector,
)


def _recorder(**kwargs) -> StageRecorder:
    return StageRecorder(RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN, **kwargs)


def _ports():
    lexical = FakeLexical([FakeLexHit(SourceId("s1"), 5, "shared span text", 0.9)])
    vectors = FakeVector([FakeVecHit(SourceId("s1"), 8, 9, "vector only", 0.4)])
    return lexical, vectors


class SlowEmbeddings(FakeEmbeddings):
    async def aembed_query(self, text):
        await asyncio.sleep(0.04)
        return [0.0, 0.0]


class SlowLexical(FakeLexical):
    async def search(self, user_id, query, *, limit=20):
        await asyncio.sleep(0.04)
        return await super().search(user_id, query, limit=limit)


async def test_the_rag_vocabulary_is_emitted_complete_and_in_order():
    lexical, vectors = _ports()
    timer = _recorder()
    await rag_recall(
        USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
        stages=timer,
    )
    assert [s.name for s in timer.emit()] == [
        "embed",
        "retrieve",
        "retrieve.lexical",
        "retrieve.vector",
        "fuse",
        "expand",
        "total",
    ]
    assert all(s.status == "ran" for s in timer.emit())


async def test_a_supplied_query_vector_makes_embed_skipped_rather_than_absent():
    """The fan-out lever (suggestion batches its embeddings) must read as a stage that did not
    happen, not as one that was free — and not as a gap in the strip."""
    lexical, vectors = _ports()
    timer = _recorder()
    await rag_recall(
        USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
        query_embedding=[0.0, 0.0],
        stages=timer,
    )
    embed = next(s for s in timer.emit() if s.name == "embed")
    assert (embed.status, embed.ms) == ("skipped", 0)
    assert [s.name for s in timer.emit()][0] == "embed"


async def test_the_retrieval_children_are_sequential_so_they_sum_to_their_parent():
    """Unlike the fast lane's gather. The lane was NOT restructured to measure it: one face is
    awaited after the other, and the diagram is entitled to draw a chain."""
    lexical, vectors = _ports()
    slow = SlowLexical([FakeLexHit(SourceId("s1"), 5, "shared span text", 0.9)])
    timer = _recorder()
    await rag_recall(
        USER,
        "q",
        lexical=slow,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
        stages=timer,
    )
    by_name = {s.name: s for s in timer.emit()}
    children = by_name["retrieve.lexical"].ms + by_name["retrieve.vector"].ms
    assert by_name["retrieve.lexical"].ms >= 35
    assert children <= by_name["retrieve"].ms
    # `total` wraps the lane, so it bounds every other stage.
    assert by_name["total"].ms >= max(s.ms for s in timer.emit() if s.name != "total")


async def test_embed_is_measured_where_the_embedding_is_actually_taken():
    lexical, vectors = _ports()
    timer = _recorder()
    await rag_recall(
        USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=SlowEmbeddings(),
        limit=10,
        stages=timer,
    )
    by_name = {s.name: s for s in timer.emit()}
    assert by_name["embed"].ms >= 35
    # …and outside the retrieval it used to sit behind, so the two never double-count.
    assert by_name["retrieve"].ms < by_name["embed"].ms


async def test_the_live_end_events_are_the_final_stages():
    """One clock. The last `end` per name carries exactly what the finished list carries, so
    a diagram drawn while the lane runs cannot disagree with the breakdown that follows it."""
    lexical, vectors = _ports()
    seen: list[StageEvent] = []
    timer = _recorder(on_event=seen.append)
    await rag_recall(
        USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
        stages=timer,
    )
    last_end = {e.name: e for e in seen if e.phase == "end"}
    for stage in timer.emit():
        if stage.status == "skipped":
            assert stage.name not in last_end
            continue
        event = last_end[stage.name]
        assert (event.ms, event.status, event.detail) == (
            stage.ms,
            stage.status,
            stage.detail,
        )


async def test_the_children_are_announced_inside_their_parent():
    """The fan-out/chain decision a viewer makes is structural: `retrieve` opens, both faces
    open and settle inside it, and only then does `retrieve` settle."""
    lexical, vectors = _ports()
    seen: list[StageEvent] = []
    timer = _recorder(on_event=seen.append)
    await rag_recall(
        USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        limit=10,
        stages=timer,
    )
    order = [(e.name, e.phase) for e in seen]
    # `total` opens FIRST here because it is measured as a context manager wrapping the lane
    # rather than recorded after the fact: the lane is short enough that a badge ticking from
    # the first frame is the honest picture. A viewer moves `total` out of the chain anyway.
    assert order == [
        ("total", "start"),
        ("embed", "start"),
        ("embed", "end"),
        ("retrieve", "start"),
        (child_name("lexical"), "start"),
        (child_name("lexical"), "end"),
        (child_name("vector"), "start"),
        (child_name("vector"), "end"),
        ("retrieve", "end"),
        ("fuse", "start"),
        ("fuse", "end"),
        ("expand", "start"),
        ("expand", "end"),
        ("total", "end"),
    ]


async def test_measuring_the_lane_does_not_change_what_it_returns():
    """No recorder → byte-identical. The instrument must not be part of the result."""
    lexical_a, vectors_a = _ports()
    lexical_b, vectors_b = _ports()
    plain = await rag_recall(
        USER, "q", lexical=lexical_a, vectors=vectors_a, embeddings=FakeEmbeddings(), limit=10
    )
    measured = await rag_recall(
        USER,
        "q",
        lexical=lexical_b,
        vectors=vectors_b,
        embeddings=FakeEmbeddings(),
        limit=10,
        stages=_recorder(),
    )
    assert plain == measured
