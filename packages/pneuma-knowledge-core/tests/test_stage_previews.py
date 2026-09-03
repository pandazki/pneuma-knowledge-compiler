"""What a stage was HANDED and what came out — the preview beside the duration.

A duration says a stage was slow. It never says what it was slow AT: `retrieve.claims 812ms`
is the same line whether the face returned two claims or eighty, and `route 1.4s` is the same
line whether the routing turn chose a lookup or nothing at all. Every stage carries a small
object of its own inputs and results, so the strip answers the second question too.

WHAT AN ENTRY SAYS, NOT WHICH ENTRY IT IS. The first version of this listed addresses —
`c1a2b3c4 projects/pricing.md`, `d4e5f6a7 ¶7-7` — and named every item while describing
none of them. So an entry now leads with a bounded head of the item's own words, then where
it lives, then the id as a trailing tag; a routed call reads as the call it was
(`person(alias="…")`); and a selection reads as a sentence about each face. Most of what this
file pins is that shape, per lane.

The property that makes that safe is that the bound is MECHANICAL. A preview reaches a
`StageTiming` only through `bound_preview`, which caps the serialized object at ~1 KB by
truncating lists, shedding an item's decoration in a fixed order and eliding strings at
successively harder rungs, and finally by dropping trailing keys. A call site therefore cannot
leak evidence by writing a careless preview: evidence reaches a reader through the answer and
its citations, and a telemetry frame is not a second, unbounded way out of the library. Which
half a squeeze takes is itself pinned here — the words outlive the id, never the other way
round.

The keys themselves belong to the STAGE, exactly as the stage names do. What is asserted here
is that each lane's stages carry the keys they document, not that any module downstream knows
what they mean — a viewer prints whatever rows it is given.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.agentic import AgentTimings, timed_tools
from pneuma_knowledge_core.recall.briefing import BriefingScope, build_briefing
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.recall.rag import (
    RAG_RETRIEVE_CHILDREN,
    RAG_STAGE_ORDER,
    rag_recall,
)
from pneuma_knowledge_core.recall.stage_timing import (
    ELLIPSIS,
    PREVIEW_BUDGET_CHARS,
    PREVIEW_TEXT_CHARS,
    StageRecorder,
    bound_preview,
    child_name,
    preview_head,
)

from test_fast_recall import (
    ClaimStub,
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
    LexHit,
    VecHit,
)
from test_fast_stage_timing import _Model, _PersonPath
from test_stage_events import Watcher

_USER = UserId("u-stage-previews")
_AS_OF = datetime(2026, 8, 26, 9, 0, 0, tzinfo=timezone.utc)


def _size(preview) -> int:
    return len(json.dumps(preview, ensure_ascii=False))


# ------------------------------------------------------------------ the bound


def test_a_ten_kilobyte_list_comes_back_under_the_cap():
    """The whole point of the helper: whatever a call site assembles, this is what escapes."""
    huge = {"items": [f"c:{i:04d} " + "x" * 300 for i in range(400)], "hits": 400}
    out = bound_preview(huge)
    assert _size(huge) > 100_000
    assert _size(out) <= PREVIEW_BUDGET_CHARS
    # Truncation is STATED, never silent: a reader can tell a short list from a cut one.
    assert any(ELLIPSIS in str(item) for item in out["items"])
    assert out["hits"] == 400


def test_a_squeeze_drops_the_id_before_it_shortens_what_an_item_says():
    """The owner's ranking, made mechanical: text > where > id.

    A rung that cut `text` to twenty characters while keeping `id` would spend the budget on
    exactly the half of an entry that was not a preview. So the ladder sheds `id`, then
    `span`, then the title, and only then shortens the words."""
    said = (
        "The pilot ends in March and the renewal is decided in April, once the second "
        "site has reported its numbers and the board has read them."
    )
    crowded = {
        "hits": 40,
        "items": [{"text": said, "doc": "Pilot", "id": f"{i:08x}"} for i in range(40)],
    }
    out = bound_preview(crowded)
    assert _size(out) <= PREVIEW_BUDGET_CHARS
    kept = [row for row in out["items"] if isinstance(row, dict)]
    assert kept, "a squeeze must not empty the list"
    assert all("id" not in row for row in kept)
    # Where it is outlives the id, and what it says outlives both.
    assert all(row["doc"] == "Pilot" for row in kept)
    assert kept[0]["text"].startswith("The pilot ends in March")
    # Counts are a stage's own keys and are never mistaken for an entry's decoration.
    assert out["hits"] == 40


def test_a_preview_head_is_display_text_bounded_and_cut_on_a_word():
    """One strip, shared with the glance line: markdown, citations and anchors are form."""
    assert preview_head("**Fixed price** for Q3 [cite: s1 ¶2-3] <!-- c:1a2b3c4d -->") == (
        "Fixed price for Q3"
    )
    long = "The pilot ends in March " * 10
    head = preview_head(long)
    assert len(head) <= PREVIEW_TEXT_CHARS + len(ELLIPSIS)
    assert head.endswith(ELLIPSIS) and not head.endswith(" " + ELLIPSIS)


def test_one_enormous_string_is_elided_rather_than_dropped():
    out = bound_preview({"query": "长" * 50_000})
    assert _size(out) <= PREVIEW_BUDGET_CHARS
    assert out["query"].endswith(ELLIPSIS)


def test_many_large_keys_lose_the_last_ones_rather_than_the_bound():
    """The rungs cannot always fit an object with a hundred keys. Dropping trailing keys is
    the terminating fall-back, because the empty object always fits."""
    out = bound_preview({f"k{i}": "y" * 400 for i in range(100)})
    assert _size(out) <= PREVIEW_BUDGET_CHARS
    assert out and set(out) < {f"k{i}" for i in range(100)}


def test_nothing_previewed_is_none_and_never_an_empty_panel():
    assert bound_preview(None) is None
    assert bound_preview({}) is None


def test_a_preview_recorded_across_two_passes_merges_instead_of_clobbering():
    """fast's `assemble` is five passes and ONE stage. A pass describing the windows must not
    erase what the pass before it said about the episode summaries."""
    recorder = StageRecorder()
    with recorder.measure("assemble"):
        recorder.preview("assemble", {"episode_summaries": 3})
    with recorder.measure("assemble"):
        recorder.preview("assemble", {"windows": 8})
    stage = next(s for s in recorder.emit() if s.name == "assemble")
    assert stage.preview == {"episode_summaries": 3, "windows": 8}


def test_a_preview_rides_the_end_event_and_never_a_start():
    """A `start` has measured nothing and produced nothing; a preview on one would be the
    only value in the frame that was not observed."""
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    with recorder.measure("plan"):
        recorder.preview("plan", {"queries": ["a", "b"]})
    assert [e.preview for e in watcher.starts] == [None]
    assert watcher.settled()["plan"].preview == {"queries": ["a", "b"]}
    # One clock, one fact: the live frame and the final entry carry the same object.
    assert watcher.settled()["plan"].preview == recorder.emit()[0].preview


def test_a_preview_that_arrives_after_the_stage_settled_corrects_it_in_place():
    watcher = Watcher()
    recorder = StageRecorder(on_event=watcher)
    with recorder.measure("plan"):
        pass
    recorder.preview("plan", {"queries": ["a"]})
    recorder.preview("plan", {"cap": 3})
    ends = [e for e in watcher.ends if e.name == "plan"]
    # A second `end` per correction, same key — last end wins, and it MERGES rather than
    # replacing, which is the rule the multi-pass test pins, seen live.
    assert [e.preview for e in ends] == [
        None,
        {"queries": ["a"]},
        {"queries": ["a"], "cap": 3},
    ]


# ------------------------------------------------------------------ the fast lane


async def _fast(**extra):
    index = FakeClaimIndex(
        [
            ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责恒印印刷的对接"),
            ClaimStub("b2d0", "memory/people/lin-wei.md", "林薇先给排期再谈价"),
        ]
    )
    return await fast_recall(
        _USER,
        "林薇现在负责什么",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_Model(answer="A"),
        **extra,
    )


_ROUTE_CALL = {"name": "person", "args": {"alias": "林薇"}, "id": "t1", "type": "tool_call"}


async def test_the_fast_lanes_stages_carry_the_keys_they_document():
    watcher = Watcher()
    fa = await _fast(
        fast_paths=(_PersonPath(),),
        route_model=_Model(answer="A", route_calls=[_ROUTE_CALL]),
        on_event=watcher,
    )
    by_name = {s.name: s for s in fa.stages}

    claims = by_name[child_name("claims")].preview
    assert set(claims) >= {"hits", "items", "pool"}
    # WHAT THE CLAIM SAYS first, then where it lives, then the anchor as a tag. The document
    # is named by its stem here because this lane was handed no documents to title it with.
    assert claims["items"][0] == {
        "text": "林薇负责恒印印刷的对接",
        "doc": "lin-wei",
        "id": "a1f3",
    }

    route = by_name["route"].preview
    # The call as the call it was — a name and its arguments read together, or not at all.
    assert route["tool_calls"] == ['person(alias="林薇")']

    path = by_name[child_name("path:person")].preview
    assert set(path) >= {"call", "hits", "items"}
    assert path["call"] == 'person(alias="林薇")'
    assert path["items"][0]["text"]

    assemble = by_name["assemble"].preview
    assert set(assemble) >= {"windows", "window_chars", "sections"}
    # The counts stay; the line is what a person reads at a glance.
    assert assemble["sections"] == "claims 2 · 20 chars"
    answer = by_name["answer"].preview
    assert answer["format"] == "text" and answer["turns"] == 1
    assert set(answer) >= {"input_chars", "claims", "windows", "sections"}
    assert answer["sections"].endswith(" chars")

    # Every preview that reached the wire is inside the bound, whatever the lane assembled.
    for stage in fa.stages:
        if stage.preview is not None:
            assert _size(stage.preview) <= PREVIEW_BUDGET_CHARS, stage.name


async def test_the_two_faces_that_need_ports_preview_their_hits_and_their_picks():
    """`retrieve.windows` needs a raw index wired and `retrieve.glance` needs documents, so
    neither runs in the bare lane above. Both are documented, so both are pinned here."""
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId, SourceId

    body = "林薇在会上确认了排期"
    doc = CanonicalDocument(
        doc_id=DocumentId("d-p1"),
        path="memory/people/lin-wei.md",
        frontmatter={"title": "林薇"},
        body=(
            "# 林薇\n\n<!-- overview -->\n<!-- overview:definition -->\n"
            "恒印印刷的采购对接人。 <!-- c:a1f3 -->\n<!-- /overview -->\n\n采购对接"
        ),
    )
    fa = await _fast(
        fast_paths=(),
        lexical=FakeLexical([LexHit(SourceId("srcbody1"), 3, body)]),
        vectors=FakeVector([VecHit(SourceId("srcbody1"), 3, 3, body)]),
        documents=[doc],
        glance_model=_Model(
            answer="A",
            route_calls=[
                {
                    "name": "DocumentSelection",
                    "args": {"paths": ["memory/people/lin-wei.md"]},
                    "id": "g1",
                    "type": "tool_call",
                }
            ],
        ),
    )
    by_name = {s.name: s for s in fa.stages}

    windows = by_name[child_name("windows")].preview
    assert windows["hits"] == 1
    # A raw hit has no title of its own, so the source id stands in for the location — but
    # the passage's own words lead, which is the half a reader can actually use.
    assert windows["items"] == [
        {"text": "林薇在会上确认了排期", "source": "srcbody1", "span": "¶3-3"}
    ]

    glance = by_name[child_name("glance")].preview
    assert glance["offered"] == 1
    assert glance["hits"] == 1
    # A chosen page previews as what it says it IS — its definition, under its title. A path
    # was never a preview of a page; it is where the page is filed.
    assert glance["items"] == [{"text": "恒印印刷的采购对接人。", "doc": "林薇"}]

    # Handed documents, the claim face names the PAGE rather than the file it sits in.
    assert by_name[child_name("claims")].preview["items"][0]["doc"] == "林薇"


async def test_a_claim_in_a_frozen_volume_previews_under_the_page_it_is_history_of():
    """The fast lane's half of the volume-provenance fix.

    `a02` is a rollover volume's filename and the only name that document has — its body
    carries no `# ` heading, because the rollover leaves the title on the active page. A
    preview naming it `a02` tells a reader nothing, and it is the same string that, on the
    Live Context lane, let a card be delivered about the wrong subject entirely. Every
    document name in this lane is read off ONE mapping, so this is that mapping."""
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId

    active = CanonicalDocument(
        doc_id=DocumentId("d-lin-wei"),
        path="memory/people/lin-wei.md",
        frontmatter={"title": "林薇"},
        body=(
            "# 林薇\n\n<!-- overview -->\n<!-- overview:definition -->\n"
            "恒印印刷的采购对接人。 <!-- c:a1f3 -->\n<!-- /overview -->\n\n采购对接"
        ),
    )
    volume = CanonicalDocument(
        doc_id=DocumentId("d-lin-wei-a02"),
        path="memory/people/lin-wei/a02.md",
        frontmatter={"archived_from": "memory/people/lin-wei.md", "rollover_volume": "02"},
        body="## 归档\n\n- 林薇去年谈下了首批排期 <!-- c:c3e1 -->\n",
    )
    index = FakeClaimIndex(
        [ClaimStub("c3e1", "memory/people/lin-wei/a02.md", "林薇去年谈下了首批排期")]
    )
    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_Model(answer="A"),
        fast_paths=(),
        documents=[active, volume],
    )
    claims = {s.name: s for s in fa.stages}[child_name("claims")].preview
    # English pack in tests; the live Chinese deployment renders 「林薇（分卷 a02）」.
    assert claims["items"][0]["doc"] == "林薇 (vol. a02)"
    assert claims["items"][0]["doc"] != "a02"


async def test_the_selection_stage_reads_as_a_sentence_per_face_and_lists_what_it_kept(
    monkeypatch,
):
    """The old `select` preview was two count objects and a list of ids — how much, never what.

    So the line stays (a selector that kept almost nothing is the thing you look for) and the
    picks are listed under it in their own words, grouped by the face they came from."""
    from pneuma_knowledge_core.domain.ids import SourceId
    from pneuma_knowledge_core.recall import fast as fast_module
    from pneuma_knowledge_core.recall.fast import SelectedEvidence

    async def choose(*args, **kwargs):
        return (
            SelectedEvidence(
                claim_indexes=(1,), episode_indexes=(), window_indexes=(0,)
            ),
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            None,
        )

    monkeypatch.setattr(fast_module, "select_evidence", choose)
    body = "林薇在会上确认了排期"
    fa = await _fast(
        fast_paths=(),
        evidence_strategy="select",
        lexical=FakeLexical([LexHit(SourceId("srcbody1"), 3, body)]),
        vectors=FakeVector([VecHit(SourceId("srcbody1"), 3, 3, body)]),
    )
    select = {s.name: s for s in fa.stages}["select"]
    # Faces with no candidates are left out: they were not a choice, they are a face this
    # deployment does not have.
    assert select.preview["faces"] == "claims 2 → 1, windows 1 → 1"
    assert select.preview["claims"] == [
        {"text": "林薇先给排期再谈价", "doc": "lin-wei", "id": "b2d0"}
    ]
    assert select.preview["windows"] == [
        {"text": "林薇在会上确认了排期", "source": "srcbody1", "span": "¶3-3"}
    ]


async def test_a_selection_that_failed_says_so_beside_the_faces_it_was_offered(
    monkeypatch,
):
    from pneuma_knowledge_core.recall import fast as fast_module

    async def fail(*args, **kwargs):
        return None, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "timeout"

    monkeypatch.setattr(fast_module, "select_evidence", fail)
    fa = await _fast(fast_paths=(), evidence_strategy="select")
    select = {s.name: s for s in fa.stages}["select"]
    assert select.status == "degraded" and select.detail == "timeout"
    assert select.preview == {"faces": "claims 2 → 0", "chosen": "none"}


async def test_a_stage_that_did_not_run_previews_nothing():
    fa = await _fast(fast_paths=())
    by_name = {s.name: s for s in fa.stages}
    assert by_name["plan"].status == "skipped" and by_name["plan"].preview is None
    assert by_name["route"].status == "skipped" and by_name["route"].preview is None


async def test_a_routing_turn_that_chose_nothing_says_so_rather_than_going_blank():
    """"none" is a finding about the question — the reason no path ran — not an absence."""
    fa = await _fast(fast_paths=(_PersonPath(),), route_model=_Model(answer="", calls=[]))
    route = {s.name: s for s in fa.stages}["route"]
    # And it names the paths it declined, not how many there were: a reader who cannot see
    # which paths existed cannot tell a sensible decline from a broken router.
    assert route.preview["tool_calls"] == "no path chosen — offered: person"


# ------------------------------------------------------------------ rag


async def test_the_rag_lanes_stages_carry_counts_and_the_first_few_addresses():
    timer = StageRecorder(RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN)
    await rag_recall(
        _USER,
        "报价",
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        embeddings=FakeEmbeddings(),
        limit=5,
        stages=timer,
    )
    by_name = {s.name: s for s in timer.emit()}
    assert by_name["embed"].preview["dimensions"] > 0
    assert set(by_name[child_name("lexical")].preview) >= {"hits", "top", "candidates"}
    assert set(by_name[child_name("vector")].preview) >= {"raw", "episode", "hits"}
    assert set(by_name["fuse"].preview) >= {"rankings", "hits"}
    assert set(by_name["expand"].preview) >= {"fused", "hits"}


# ------------------------------------------------------------------ the briefing build


async def test_the_briefing_build_previews_what_each_half_retrieved_and_packed():
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId
    from pneuma_knowledge_core.domain.snapshot import SnapshotRef

    index = FakeClaimIndex(
        [ClaimStub("a1f3", "memory/topics/print.md", "恒印印刷的报价流程")]
    )
    # The snapshot has to CONTAIN the page the claim names: a pack is pinned to its own
    # snapshot, and a claim on a page the snapshot does not hold is dropped before any
    # preview is written (core `recall/archive_filter._off_pin`).
    briefing = await build_briefing(
        _USER,
        BriefingScope(query="报价", source_ids=[], budget_chars=4000),
        snapshot_docs=[
            CanonicalDocument(
                doc_id=DocumentId("d-print"),
                path="memory/topics/print.md",
                body="# 恒印印刷\n\n报价流程。 <!-- c:a1f3 -->",
            )
        ],
        snapshot=SnapshotRef(ref="ref-previews"),
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
    )
    by_name = {s.name: s for s in briefing.stages}
    assert set(by_name[child_name("claims")].preview) >= {"cap", "hits", "items"}
    assert by_name[child_name("claims")].preview["items"][0]["text"] == "恒印印刷的报价流程"
    assert set(by_name["pack"].preview) >= {"pack_chars", "budget_chars", "sections"}


# ------------------------------------------------------------------ the agentic lanes


async def test_a_tool_call_previews_its_arguments_and_the_SIZE_of_what_came_back():
    """The result is evidence, so only its size and first line travel. A telemetry frame that
    carried tool results would be a second, unbounded way out of the library."""
    from langchain_core.tools import tool

    @tool
    async def search_claims(query: str) -> str:
        """Search."""
        return "c:1a2b 林薇负责对接\nc:3c4d 林薇先给排期"

    timings = AgentTimings()
    wrapped = timed_tools([search_claims], timings)[0]
    await wrapped.coroutine(query="林薇")
    step = timings.stages()[0]
    assert step.name == "tool:search_claims"
    assert step.preview["call"] == 'search_claims(query="林薇")'
    assert step.preview["result_chars"] == len(
        "c:1a2b 林薇负责对接\nc:3c4d 林薇先给排期"
    )
    # A head of what came back, as one line of display text — not the result, and not the
    # addressing the result opens with.
    assert step.preview["result"] == "c:1a2b 林薇负责对接 c:3c4d 林薇先给排期"


async def test_a_tool_that_raised_still_previews_what_it_was_asked_for():
    from langchain_core.tools import tool

    @tool
    async def fetch_verbatim(source_id: str) -> str:
        """Fetch."""
        raise RuntimeError("no such source")

    timings = AgentTimings()
    wrapped = timed_tools([fetch_verbatim], timings)[0]
    try:
        await wrapped.coroutine(source_id="s-gone")
    except RuntimeError:
        pass
    step = timings.stages()[0]
    assert step.status == "degraded"
    assert step.preview == {"call": 'fetch_verbatim(source_id="s-gone")'}


def test_a_model_turn_previews_the_tool_calls_it_issued():
    from langchain_core.messages import AIMessage

    from pneuma_knowledge_core.recall.agentic import _turn_preview

    called = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_claims", "args": {"query": "林薇"}, "id": "1", "type": "tool_call"}
        ],
    )
    assert _turn_preview(called) == {"tool_calls": ['search_claims(query="林薇")']}
    # The closing turn calls nothing, and that is the finding — not a blank.
    assert _turn_preview(AIMessage(content="林薇负责采购")) == {"tool_calls": "none"}
