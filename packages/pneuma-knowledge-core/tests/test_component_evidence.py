"""Component evidence v2: paths return everything, the framework orders and truncates.

The failure these pin: a routed lookup returned the first N items of a page or a range in
DOCUMENT order, so the claim that answered the question fell past the cap while sixty
irrelevant ones sat inside it. Every test here is one half of the replacement — a
deterministic order against the question, a cap spent on THAT order under floors, a
truncation that describes what it dropped, dedup that never disturbs the ranked faces, and
a selector that sees component results as candidates rather than being bypassed by them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.ports.reranker import RerankResult
from pneuma_knowledge_core.recall.component_rank import (
    apply_cap,
    rank_candidates,
    truncate_window,
)
from pneuma_knowledge_core.recall.fast import (
    EvidenceSelection,
    RetrievedClaim,
    component_candidate_pool,
    evidence_selection_messages,
    fast_recall,
    select_evidence,
)
from pneuma_knowledge_core.recall.paths import (
    ComponentEvidence,
    PathResult,
    merge_component_evidence,
)
from pneuma_knowledge_core.recall.rag import RecallHit

from test_fast_paths import PersonArgs, _Model  # noqa: E402
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings  # noqa: E402
from test_quality_context_selection import StructuredModel  # noqa: E402

USER = UserId("u-component")
AS_OF = datetime(2026, 8, 25, tzinfo=timezone.utc)


def claim(
    anchor: str,
    text: str,
    *,
    section: str = "位置",
    labels: tuple[str, ...] = (),
    cite: tuple[str, int, int] | None = None,
    path: str = "memory/people/jia-ning.md",
) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=AnchorId(anchor),
        document_path=path,
        section_path=(section,) if section else (),
        text=text,
        citations=(
            (Citation(source_id=SourceId(cite[0]), block_start=cite[1], block_end=cite[2]),)
            if cite
            else ()
        ),
        paths=("people",),
        labels=labels,
    )


def window(source: str, start: int, end: int, text: str) -> RecallHit:
    return RecallHit(
        source_id=SourceId(source),
        block_start=start,
        block_end=end,
        text=text,
        paths=("time",),
        score=1.0,
    )


# ------------------------------------------------------------------------------- ranking


def test_a_cjk_question_ranks_the_claim_that_answers_it_first():
    """The pathology verbatim: the answer is LAST in document order, and no model is
    involved in fixing that."""
    page = [claim(f"p{i:02d}", f"贾宁的日常协作备注之{i}", section="工作方式") for i in range(20)]
    page.append(claim("c07e", "贾宁现在在新华印务任采购总监", labels=("current",)))
    ranked = rank_candidates("贾宁现在在哪家公司任职", page, [])
    assert str(ranked.claims[0].anchor) == "c07e"
    assert ranked.claims[0].score > ranked.claims[1].score


def test_a_latin_question_ranks_by_word_overlap_not_by_position():
    page = [
        claim("w0", "Caroline enjoys weekend kayaking.", section="hobbies"),
        claim("w1", "Caroline moved to the Berlin office in March.", section="location"),
        claim("w2", "Caroline prefers written updates.", section="working style"),
    ]
    ranked = rank_candidates("Which office does Caroline work from?", page, [])
    assert str(ranked.claims[0].anchor) == "w1"


def test_current_beats_superseded_at_equal_overlap_and_strong_words_still_win():
    live = claim("live", "贾宁在新华印务", labels=("current",))
    dead = claim("dead", "贾宁在新华印务", labels=("superseded",))
    ranked = rank_candidates("贾宁在哪", [dead, live], [])
    assert [str(c.anchor) for c in ranked.claims] == ["live", "dead"]
    # …unless the question is asking about the older state in its own words: the penalty is
    # a nudge, not a wall.
    history = claim("dead", "贾宁曾是恒印印刷的对接人", labels=("superseded",))
    other = claim("live", "贾宁喜欢先看排期", labels=("current",))
    ranked = rank_candidates("贾宁以前在恒印印刷做什么", [other, history], [])
    assert str(ranked.claims[0].anchor) == "dead"


def test_a_date_in_the_question_pulls_the_candidate_from_that_day_forward():
    """The candidate's day comes from its citation when the caller knows it — the same
    `source_id` addressing everything else uses (I4)."""
    june = claim("jun", "采购价格改为分段计费", section="定价", cite=("s_june", 0, 1))
    may = claim("may", "采购价格改为分段计费", section="定价", cite=("s_may", 0, 1))
    ranked = rank_candidates(
        "2026-06 的采购价格是怎么定的",
        [may, june],
        [],
        source_days={"s_june": "2026-06-12", "s_may": "2026-05-02"},
    )
    assert str(ranked.claims[0].anchor) == "jun"


def test_a_window_is_dated_by_the_day_its_own_first_line_states():
    days = [window("s1", i * 10, i * 10 + 2, f"2026-06-{i + 10:02d} (Mon) 采购例会") for i in range(5)]
    ranked = rank_candidates("2026-06-12 的例会说了什么", [], days)
    assert ranked.windows[0].text.startswith("2026-06-12")


def test_the_reranker_replaces_the_lexical_term_and_fails_soft_back_to_it():
    candidates = [claim("a", "first"), claim("b", "second"), claim("c", "third")]
    # scores in [*claims, *windows] order — the reranker likes the LAST one
    ranked = rank_candidates("q", candidates, [], reranker_scores=[0.1, 0.2, 0.9])
    assert [str(c.anchor) for c in ranked.claims] == ["c", "b", "a"]
    # a wrong-length score list is ignored rather than misaligned onto the candidates
    ranked = rank_candidates("q", candidates, [], reranker_scores=[0.9])
    assert [str(c.anchor) for c in ranked.claims] == ["a", "b", "c"]


class _Reranker:
    """Scores by position from the end, so its order is unmistakably not the input order."""

    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, []

    async def rerank(self, query, documents, *, top_n):  # noqa: ANN001
        self.calls.append((query, list(documents)))
        if self.fail:
            raise RuntimeError("reranker down")
        return [
            RerankResult(index=index, score=float(index))
            for index in range(min(top_n, len(documents)))
        ]


class _ThreePath:
    name = "person"
    description = "one person page"
    args_schema = PersonArgs
    cap = 3

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        return PathResult(
            claims=(claim("a", "alpha"), claim("b", "beta"), claim("c", "gamma"))
        )


def _lane_kwargs(model, **extra):
    index = FakeClaimIndex([])
    return dict(
        as_of=AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=model,
        **extra,
    )


async def test_the_lane_hands_the_component_candidates_to_a_wired_reranker():
    model = _Model(
        answer="A",
        route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}],
    )
    reranker = _Reranker()
    fa = await fast_recall(
        USER, "q", fast_paths=[_ThreePath()], reranker=reranker, **_lane_kwargs(model)
    )
    assert reranker.calls and reranker.calls[0][1] == ["alpha", "beta", "gamma"]
    [ev] = fa.used_component_evidence
    assert [str(c.anchor) for c in ev.claims] == ["c", "b", "a"]
    assert fa.component_rerank_degraded is None


async def test_a_failing_reranker_leaves_the_lexical_order_and_a_marker():
    model = _Model(
        answer="A",
        route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}],
    )
    fa = await fast_recall(
        USER, "q", fast_paths=[_ThreePath()], reranker=_Reranker(fail=True), **_lane_kwargs(model)
    )
    [ev] = fa.used_component_evidence
    assert [str(c.anchor) for c in ev.claims] == ["a", "b", "c"]
    assert fa.component_rerank_degraded == "error"


# ---------------------------------------------------------------------------- truncation


def test_the_cap_is_spent_after_ordering_and_interleaves_both_kinds():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    claims = [claim(f"c{i}", f"note about {word}", section=f"s{i}") for i, word in enumerate(words)]
    windows = [window("s1", i, i, f"excerpt about {word}") for i, word in enumerate(words)]
    ranked = rank_candidates("what do foxtrot and echo say", claims, windows)
    capped = apply_cap(ranked, 4)
    # both kinds present — never a fixed 50/50, and never claims-then-windows-if-room
    assert capped.claims and capped.windows
    assert len(capped.claims) + len(capped.windows) == 4
    assert "foxtrot" in capped.claims[0].text or "echo" in capped.claims[0].text
    assert "foxtrot" in capped.windows[0].text or "echo" in capped.windows[0].text


def test_one_window_survives_even_a_cap_full_of_better_claims():
    claims = [claim(f"c{i}", "exactly the question words", section=f"s{i}") for i in range(6)]
    windows = [window("s9", 0, 0, "nothing to do with it")]
    capped = apply_cap(rank_candidates("exactly the question words", claims, windows), 3)
    assert len(capped.windows) == 1 and len(capped.claims) == 2


def test_every_section_keeps_its_best_claim_before_any_section_gets_a_second():
    claims = [
        claim("a1", "位置 一", section="位置"),
        claim("a2", "位置 二", section="位置"),
        claim("a3", "位置 三", section="位置"),
        claim("b1", "工作方式 一", section="工作方式"),
        claim("c1", "偏好 一", section="偏好"),
    ]
    capped = apply_cap(rank_candidates("位置", claims, []), 3)
    sections = {" › ".join(c.section_path) for c in capped.claims}
    assert sections == {"位置", "工作方式", "偏好"}


def test_what_the_cap_dropped_is_described_per_section_not_merely_counted():
    claims = [
        *[claim(f"p{i}", f"位置 {i}", section="位置") for i in range(4)],
        *[claim(f"w{i}", f"工作方式 {i}", section="工作方式") for i in range(6)],
    ]
    capped = apply_cap(rank_candidates("位置", claims, []), 3)
    assert capped.dropped == 7
    # 位置 keeps two slots (it answers the question), 工作方式 keeps one by the section floor
    assert dict(capped.dropped_summary) == {"位置": 2, "工作方式": 5}
    assert sum(count for _, count in capped.dropped_summary) == capped.dropped


def test_an_over_long_window_is_cut_at_a_block_boundary_that_names_the_lost_blocks():
    body = "\n".join(f"block {i} " + "x" * 40 for i in range(10))
    hit = window("s1", 12, 21, body)
    cut, omitted = truncate_window(hit, 150)
    assert omitted is not None
    start, end = omitted
    assert end == 21 and 12 < start <= 21
    assert cut.text.splitlines()[-1].startswith(f"block {start - 12 - 1}")
    # …and a window whose lines cannot be mapped to blocks claims no range at all
    dense = window("s1", 0, 3, "one very long line " * 40)
    cut, omitted = truncate_window(dense, 100)
    assert omitted is None and len(cut.text) <= 100


def test_the_character_budget_holds_the_whole_face_and_says_what_it_cost():
    long_claims = [claim(f"c{i}", f"第{i}条：" + "详" * 300, section=f"s{i}") for i in range(8)]
    evidence = ComponentEvidence(
        path="person", args={"alias": "x"}, cap=8, claims=tuple(long_claims)
    )
    merged, _ = merge_component_evidence(
        [evidence], claims=[], windows=[], budget_chars=1200
    )
    from pneuma_knowledge_core.recall.paths import render_component_evidence

    rendered = render_component_evidence(merged)
    assert len(rendered) <= 1200
    assert merged[0].dropped == 8 - len(merged[0].claims)
    assert sum(count for _, count in merged[0].dropped_summary) == merged[0].dropped
    assert "…not shown:" in rendered


def test_the_budget_covers_the_whole_face_including_the_blocks_it_cannot_shrink():
    """A degraded path still costs a header; the ceiling is over the FACE, not over the
    paths that happen to be trimmable."""
    from pneuma_knowledge_core.recall.paths import render_component_evidence

    rows = [
        ComponentEvidence(path="timespan", args={"since": "2026-06-01"}, degraded="timeout"),
        ComponentEvidence(
            path="person",
            args={"alias": "贾宁"},
            cap=6,
            claims=tuple(claim(f"a{i}", f"第{i}条：" + "详" * 200, section=f"s{i}") for i in range(6)),
        ),
        ComponentEvidence(
            path="topic",
            args={"name": "采购"},
            cap=6,
            claims=tuple(claim(f"b{i}", f"另{i}条：" + "详" * 200, section=f"t{i}") for i in range(6)),
        ),
    ]
    merged, _ = merge_component_evidence(rows, claims=[], windows=[], budget_chars=1500)
    assert len(render_component_evidence(merged)) <= 1500
    assert "(lookup did not deliver: timeout)" in render_component_evidence(merged)


def test_a_budget_cut_window_carries_its_omitted_block_range_into_the_face():
    body = "\n".join(f"块 {i}：" + "内容" * 60 for i in range(12))
    evidence = ComponentEvidence(
        path="timespan",
        args={"since": "2026-06-01", "until": "2026-06-02"},
        cap=4,
        windows=(window("s1", 0, 11, body),),
    )
    merged, _ = merge_component_evidence(
        [evidence], claims=[], windows=[], budget_chars=900
    )
    from pneuma_knowledge_core.recall.paths import render_component_evidence

    rendered = render_component_evidence(merged)
    assert "not shown)" in rendered and "¶" in rendered
    assert len(rendered) <= 900


# --------------------------------------------------------------------------------- dedup


def test_a_claim_whose_evidence_is_inside_a_window_of_the_same_face_is_folded_into_it():
    covered = claim("c1", "六月定了分段计费", section="定价", cite=("s1", 2, 3))
    outside = claim("c2", "七月复盘了这次改动", section="定价", cite=("s2", 0, 0))
    evidence = ComponentEvidence(
        path="timespan",
        args={},
        cap=10,
        claims=(covered, outside),
        windows=(window("s1", 0, 5, "2026-06-12 (Fri) 逐字记录"),),
    )
    merged, _ = merge_component_evidence([evidence], claims=[], windows=[])
    assert [str(c.anchor) for c in merged[0].claims] == ["c2"]
    assert merged[0].covered_by_windows == 1
    from pneuma_knowledge_core.recall.paths import render_component_evidence

    assert "1 claims covered by the excerpts here" in render_component_evidence(merged)


def test_one_address_returned_by_two_paths_is_shown_once_and_names_both():
    shared = claim("both", "同一条断言", cite=("s1", 0, 0))
    first = ComponentEvidence(path="person", args={}, cap=5, claims=(shared,))
    second = ComponentEvidence(path="timespan", args={}, cap=5, claims=(shared,))
    merged, _ = merge_component_evidence([first, second], claims=[], windows=[])
    assert [str(c.anchor) for c in merged[0].claims] == ["both"]
    assert merged[1].claims == ()
    assert "via:person,timespan" in merged[0].claims[0].labels


def test_text_duplicates_inside_one_face_collapse_into_the_more_complete_statement():
    short = claim("s", "贾宁在新华印务")
    long = claim("l", "贾宁在新华印务任采购总监")
    evidence = ComponentEvidence(path="person", args={}, cap=5, claims=(short, long))
    merged, _ = merge_component_evidence([evidence], claims=[], windows=[])
    assert [str(c.anchor) for c in merged[0].claims] == ["l"]
    assert merged[0].dropped == 1


# -------------------------------------------------------------------------------- select


class _MixedPath:
    name = "person"
    description = "one person page"
    args_schema = PersonArgs
    cap = 6

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        return PathResult(
            claims=(claim("k0", "贾宁任采购总监", labels=("current",)),),
            windows=(window("s7", 0, 1, "2026-06-12 (Fri) 会议原文"),),
        )


def test_the_selector_sees_component_results_as_a_group_it_can_pick_from():
    evidence = [
        ComponentEvidence(
            path="person",
            args={"alias": "贾宁"},
            cap=4,
            claims=(claim("k0", "贾宁任采购总监"),),
            windows=(window("s7", 0, 1, "会议原文"),),
        )
    ]
    pool = component_candidate_pool(evidence)
    assert [c.kind for c in pool] == ["claim", "window"]
    messages = evidence_selection_messages(
        "贾宁在哪",
        claims=[],
        episode_summaries=[],
        windows=[],
        components=pool,
        claim_cap=4,
        episode_summary_cap=2,
        window_cap=2,
    )
    human = messages[1].content
    assert "# component-lookup candidates" in human
    assert '## component:person(alias="贾宁")' in human
    assert "K0: [claim;" in human and "K1: [window;" in human
    # the contract states the component cap like every other cap
    assert "component indexes" in messages[0].content


async def test_invented_component_coordinates_are_rejected_like_every_other_index():
    pool = component_candidate_pool(
        [ComponentEvidence(path="person", args={}, cap=4, claims=(claim("k0", "x"),))]
    )
    model = StructuredModel(parsed=EvidenceSelection(component_items=[0, 7, -3]), seen=[])
    selected, _usage, degraded = await select_evidence(
        model, "q", claims=[], episode_summaries=[], windows=[], components=pool
    )
    assert degraded is None
    assert selected is not None and selected.component_indexes == (0,)
    assert selected.model_component_count == 1


class _SelectLane(BaseChatModel):
    """One fake standing in for all three calls the select lane makes: the routing turn
    (`bind_tools`), the selection call (`with_structured_output`), and the answer."""

    parsed: object = None
    seen: list = []
    answered: list = []
    error: Exception | None = None

    @property
    def _llm_type(self) -> str:
        return "select-lane-test"

    def bind_tools(self, tools, **kw):  # noqa: ANN001, ARG002
        class _Bound:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "person",
                            "args": {"alias": "贾宁"},
                            "id": "t",
                            "type": "tool_call",
                        }
                    ],
                )

        return _Bound()

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self

        class _Bound:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.seen.append(list(messages))
                if outer.error is not None:
                    raise outer.error
                return {"raw": AIMessage(content=""), "parsed": outer.parsed, "parsing_error": None}

        return _Bound()

    def _generate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001
        self.answered.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="A"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001
        return self._generate(messages, stop, run_manager, **kw)


async def test_in_select_mode_chosen_component_items_join_the_ordinary_faces():
    """No separate section: the selector composed the whole context, and what it took is
    rendered as what it is — a claim among the notes, a window among the excerpts."""
    lane = _SelectLane(parsed=EvidenceSelection(component_items=[0, 1]), seen=[])
    index = FakeClaimIndex([ClaimStub("z1", "memory/topics/x.md", "无关命中")])
    fa = await fast_recall(
        USER,
        "贾宁在哪",
        fast_paths=[_MixedPath()],
        evidence_strategy="select",
        as_of=AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=lane,
    )
    human = lane.answered[-1][-1].content
    assert "# component lookups" not in human  # the face is not a section in select mode
    assert fa.model_selected_component_items == 2
    picked = next(c for c in fa.used_claims if str(c.anchor) == "k0")
    assert "via:person" in picked.labels
    assert any(str(w.source_id) == "s7" for w in fa.used_windows)
    # the audit trail of what was looked up survives the composition choice
    assert fa.used_component_evidence and fa.route_chosen


async def test_a_selector_failure_falls_back_to_the_rendered_component_face():
    """Fail-soft keeps the §B/§C rendering: the lookup still reaches the answer, under its
    own header, rather than vanishing because one call broke."""
    lane = _SelectLane(parsed=EvidenceSelection(), seen=[], error=RuntimeError("provider down"))
    index = FakeClaimIndex([])
    fa = await fast_recall(
        USER,
        "贾宁在哪",
        fast_paths=[_MixedPath()],
        evidence_strategy="select",
        as_of=AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=lane,
    )
    assert fa.evidence_selection_degraded == "error"
    human = lane.answered[-1][-1].content
    assert "# component lookups" in human and "## person(" in human
