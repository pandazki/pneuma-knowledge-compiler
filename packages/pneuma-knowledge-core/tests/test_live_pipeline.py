"""The three-stage Live Context lane: discover → retrieve → pick.

Keyless throughout — plain fakes, no provider, no middleware. Each test breaks exactly one
mechanism, so removing that mechanism turns exactly one test red:

* a skip must cost NOTHING (the ports assert they were never touched);
* `worth` below the floor is a skip for the same reason and by the same number;
* the plan's entries run CONCURRENTLY (measured as an interval overlap, not asserted);
* candidates are MECHANICAL — the delivered card's evidence is byte-equal to what
  retrieval rendered, and no model ever saw a chance to rewrite it;
* the pick's citation subset is copy-by-reference, and an unusable one falls back rather
  than failing the tick;
* the subject ledger holds a second introduction of the same subject however convincing
  the two model calls were, and lets a fact about it through.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from pneuma_knowledge_core.domain.canonical import CanonicalDocument, Citation
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.domain.suggestion import (
    DiscoverResult,
    PickResult,
    PlanArg,
    PlanEntry,
    WebCitation,
)
from pneuma_knowledge_core.prompts import chinese_overlay, prompt
from pneuma_knowledge_core.recall.fast import RetrievedClaim
from pneuma_knowledge_core.recall.live_pipeline import (
    LEDE_CHARS,
    SKIP_DUPLICATE,
    SKIP_LOW_CONFIDENCE,
    SKIP_LOW_WORTH,
    SKIP_NO_COVERAGE,
    SKIP_NONE_CHOSEN,
    SKIP_UNCITED,
    SKIP_UNPARSED,
    PROVENANCE_LIBRARY,
    PROVENANCE_WEB,
    WEB_FALLBACK,
    WEB_OFF,
    WEB_PLANNED,
    SubjectLedger,
    build_candidates,
    candidate_from_web,
    discover_contract,
    evaluate_live_pipeline,
    pick_contract,
    plan_runs,
    render_candidates,
    PLAN_WORDS_MAX,
    build_glance,
    coerce_density,
    plan_subjects,
    take_context,
    take_pending,
)
from pneuma_knowledge_core.ports.web_search import WebSearchAnswer
from pneuma_knowledge_core.recall.paths import PathResult

AS_OF = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
USER = UserId("u-1")
SRC = "11111111-1111-1111-1111-111111111111"
SRC2 = "22222222-2222-2222-2222-222222222222"


# --------------------------------------------------------------------------- fakes


def owner(text: str) -> ConversationTurn:
    return ConversationTurn(speaker="", text=text, role="owner")


def other(text: str, speaker_id: str = "im/2") -> ConversationTurn:
    return ConversationTurn(speaker="", text=text, role="other", speaker_id=speaker_id)


class FakeStructured:
    """One structured-output model, scripted. Records the message lists it was handed."""

    def __init__(self, envelopes: list[Any] | None = None) -> None:
        self._envelopes = list(envelopes or [])
        self.calls: list[list] = []
        self.schemas: list[Any] = []

    def with_structured_output(self, schema, *, include_raw: bool = False):  # noqa: ANN001
        self.schemas.append(schema)
        outer = self

        class _Runnable:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001
                outer.calls.append(messages)
                parsed = outer._envelopes.pop(0) if outer._envelopes else None
                return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None}

        return _Runnable()

    @property
    def system(self) -> str:
        return str(self.calls[0][0].content)

    @property
    def human(self) -> str:
        return str(self.calls[0][1].content)


class Recorder:
    """Every port below records the interval it was busy for, so 'concurrently' is measured."""

    def __init__(self) -> None:
        self.spans: dict[str, tuple[float, float]] = {}

    async def busy(self, name: str, seconds: float = 0.03) -> None:
        started = time.perf_counter()
        await asyncio.sleep(seconds)
        self.spans[name] = (started, time.perf_counter())

    def overlap(self, a: str, b: str) -> float:
        (a0, a1), (b0, b1) = self.spans[a], self.spans[b]
        return min(a1, b1) - max(a0, b0)


@dataclass
class ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class FakeClaimLexical:
    def __init__(self, rows: list[ClaimStub], recorder: Recorder | None = None) -> None:
        self._rows = rows
        self.queries: list[str] = []
        self._recorder = recorder

    async def search_claims(self, user_id, query, *, limit=40):  # noqa: ANN001
        self.queries.append(query)
        if self._recorder is not None:
            await self._recorder.busy("semantic")
        return self._rows[:limit]


class FakeClaimVectors:
    def __init__(self) -> None:
        self.calls = 0

    async def search_claims(self, user_id, embedding, *, limit=40):  # noqa: ANN001
        self.calls += 1
        return []


class FakeEmbeddings:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    async def aembed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [0.1, 0.2, 0.3]

    async def aembed_documents(self, texts):  # noqa: ANN001
        self.document_calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeWebSearch:
    """A `WebSearch` with no network behind it. `on` is the deployment/connection answer."""

    def __init__(
        self,
        answer: WebSearchAnswer | None = None,
        *,
        on: bool = True,
        recorder: Recorder | None = None,
        delay: float = 0.03,
        raises: BaseException | None = None,
    ) -> None:
        self._answer = answer or WebSearchAnswer(
            text="The DeepSeek harness is an open evaluation runner released on 2026-08-24.",
            citations=(WebCitation(title="Release notes", url="https://example.test/dsh"),),
            searches=2,
            cost=0.0141,
        )
        self._on = on
        self._recorder = recorder
        self._delay = delay
        self._raises = raises
        self.questions: list[str] = []

    def available(self) -> bool:
        return self._on

    async def search(self, question: str, *, max_results: int = 3) -> WebSearchAnswer:
        self.questions.append(question)
        if self._recorder is not None:
            await self._recorder.busy("web", self._delay)
        elif self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return self._answer


def web_plan(query: str) -> PlanEntry:
    return PlanEntry(kind="web", query=query)


WEB_ANSWER = WebSearchAnswer(
    text="The DeepSeek harness is an open evaluation runner released on 2026-08-24.",
    citations=(WebCitation(title="Release notes", url="https://example.test/dsh"),),
    searches=2,
    cost=0.0141,
)


class PersonArgs(BaseModel):
    alias: str = Field(default="", description="a name as written")
    identity: str = Field(default="", description="a source identity")


def claim(anchor: str, doc: str, text: str, *, overview: bool = False) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=anchor,  # type: ignore[arg-type]
        document_path=doc,
        section_path=("overview", "definition") if overview else ("ledger",),
        text=text,
        citations=(Citation(source_id=SourceId(SRC), block_start=1, block_end=2),),
    )


class FakePersonPath:
    name = "person"
    description = "Exact lookup of ONE person the owner knows, by the name the question uses."
    args_schema = PersonArgs
    cap = 24

    def __init__(self, result: PathResult, recorder: Recorder | None = None) -> None:
        self._result = result
        self.seen: list[dict] = []
        self._recorder = recorder

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        self.seen.append(args.model_dump())
        if self._recorder is not None:
            await self._recorder.busy("person")
        return self._result


PERSON_PAGE = PathResult(
    claims=(
        claim("a1", "people/lin-shu.md", "林舒 is the agent-memory lead.", overview=True),
        claim("a2", "people/lin-shu.md", "林舒 shipped the precision rewrite in July."),
    )
)


def discovered(**fields) -> DiscoverResult:
    return DiscoverResult(**fields)


def semantic_plan(query: str) -> list[PlanEntry]:
    return [PlanEntry(kind="semantic", query=query)]


def person_plan(alias: str) -> PlanEntry:
    return PlanEntry(kind="person", args=[PlanArg(name="alias", value=alias)])


async def run_lane(
    *,
    discover: DiscoverResult | None,
    pick: PickResult | None = None,
    paths=(),
    claims: list[ClaimStub] | None = None,
    turns: list[ConversationTurn] | None = None,
    recorder: Recorder | None = None,
    **kwargs,
):
    discover_model = FakeStructured([discover] if discover is not None else [])
    pick_model = FakeStructured([pick] if pick is not None else [])
    lexical = FakeClaimLexical(claims or [], recorder)
    vectors = FakeClaimVectors()
    embeddings = FakeEmbeddings()
    result = await evaluate_live_pipeline(
        USER,
        turns or [other("有人对 Agent 记忆更精确吗？")],
        as_of=AS_OF,
        discover_model=discover_model,
        pick_model=pick_model,
        embeddings=embeddings,
        claim_lexical=lexical,
        claim_vectors=vectors,
        paths=paths,
        **kwargs,
    )
    return result, discover_model, pick_model, lexical, vectors, embeddings


# ------------------------------------------------------- stage 1: a skip costs nothing


@pytest.mark.asyncio
async def test_a_discover_skip_touches_no_index_at_all():
    """The whole reason the stage exists. 「中午吃什么」 must not cost four round trips."""
    result, _, pick_model, lexical, vectors, embeddings = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        turns=[owner("中午吃什么")],
    )
    assert result.skipped == "small_talk"
    assert result.suggestions == ()
    assert lexical.queries == [], "a skip must not reach the lexical index"
    assert vectors.calls == 0, "a skip must not reach the vector index"
    assert embeddings.document_calls == 0 and embeddings.query_calls == 0
    assert pick_model.calls == [], "a skip must not spend the pick call either"


@pytest.mark.asyncio
async def test_worth_below_the_floor_is_a_skip_with_its_own_reason():
    result, _, _, lexical, _, embeddings = await run_lane(
        discover=discovered(intent="what is X", plan=semantic_plan("X"), worth=3),
        min_confidence=6,
    )
    assert result.skipped == SKIP_LOW_WORTH
    assert result.worth == 3
    assert lexical.queries == [] and embeddings.document_calls == 0


@pytest.mark.asyncio
async def test_an_unparsable_discover_is_silence_not_an_exception():
    result, _, _, lexical, _, _ = await run_lane(discover=None)
    assert result.skipped == SKIP_UNPARSED
    assert lexical.queries == []


# ------------------------------------------------ stage 2: concurrency and mechanics


@pytest.mark.asyncio
async def test_a_person_and_a_semantic_entry_run_concurrently():
    """Two lanes, one gather. Measured as an interval overlap: run sequentially and this
    goes to zero, which is the only way to test 'concurrently' without trusting a comment."""
    recorder = Recorder()
    path = FakePersonPath(PERSON_PAGE, recorder)
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="who works on agent memory precision",
            plan=[person_plan("林舒"), PlanEntry(kind="semantic", query="agent memory")],
            worth=8,
        ),
        pick=PickResult(choice=1, lede="你要找的人是林舒。", citations=[1], confidence=8),
        paths=[path],
        claims=[
            ClaimStub(
                anchor="c9",
                document_path="projects/agent-memory.md",
                text="The precision rewrite landed in July.",
                citations=[{"source_id": SRC2, "block_start": 3, "block_end": 4}],
            )
        ],
        recorder=recorder,
    )
    assert path.seen == [{"alias": "林舒", "identity": ""}]
    assert recorder.overlap("person", "semantic") > 0.0
    # both faces reached the candidate list
    origins = {c.origin for c in result.candidates}
    assert origins == {"path:person", "semantic.claims"}


@pytest.mark.asyncio
async def test_candidates_are_mechanical_and_keep_their_citations():
    cards = build_candidates(claims=[*PERSON_PAGE.claims])
    assert len(cards) == 1
    card = cards[0]
    assert card.index == 1
    assert card.subject == "people/lin-shu.md"
    assert card.kind == "concept", "its lede claim sits in the document's overview head"
    assert "林舒 is the agent-memory lead." in card.body
    assert card.citations == (Citation(source_id=SourceId(SRC), block_start=1, block_end=2),)


def test_a_claim_outside_the_overview_makes_a_fact_card_not_an_introduction():
    cards = build_candidates(claims=[claim("b1", "projects/p.md", "It shipped in July.")])
    assert cards[0].kind == "fact"


def test_plan_entries_naming_no_enabled_path_are_rejected_mechanically():
    runs, queries, web_queries, rejected = plan_runs(
        [person_plan("林舒"), PlanEntry(kind="timespan"), PlanEntry(kind="semantic", query="q")],
        [FakePersonPath(PERSON_PAGE)],
    )
    assert [p.name for p, _ in runs] == ["person"]
    assert queries == ["q"]
    assert web_queries == []
    assert rejected == ["timespan"], "an unenabled kind is rejected, never guessed at"


def test_a_web_entry_is_rejected_unless_the_web_lookup_was_offered():
    """The offer and the validation are one decision, applied at both ends.

    A `web` kind that was never advertised is treated exactly like a component name nobody
    registered: rejected and counted. Without this the toggle would be advisory — a model
    that happened to know the word could reach the internet on a connection that said no."""
    entries = [PlanEntry(kind="web", query="DeepSeek harness release")]

    _, _, web_queries, rejected = plan_runs(entries, [], web=False)
    assert web_queries == [] and rejected == ["web"]

    _, _, web_queries, rejected = plan_runs(entries, [], web=True)
    assert web_queries == ["DeepSeek harness release"] and rejected == []


# ------------------------------------------------------------------- stage 3: the pick


@pytest.mark.asyncio
async def test_the_chosen_candidate_is_delivered_verbatim_under_the_ledes_frame():
    result, _, pick_model, _, _, _ = await run_lane(
        discover=discovered(intent="who works on agent memory", plan=semantic_plan("q"), worth=8),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="people/lin-shu.md",
                text="林舒 is the agent-memory lead.",
                section_path=["overview", "definition"],
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=1, lede="你在找的人可能是林舒。", citations=[1], confidence=9),
    )
    assert len(result.suggestions) == 1
    card = result.suggestions[0]
    assert card.body == "你在找的人可能是林舒。", "the body is the guessed need"
    assert card.evidence == result.candidates[0].body, "byte-equal: nothing rewrote it"
    assert "林舒 is the agent-memory lead." in card.evidence
    assert card.trigger == "who works on agent memory", "the intent becomes the trigger"
    assert card.confidence == 9
    assert [str(c.source_id) for c in card.citations] == [SRC]
    # the pick stage saw numbered candidates and the live conversation, in that order
    human = str(pick_model.calls[0][1].content)
    assert human.index("# Candidates") < human.index("# The conversation")


@pytest.mark.asyncio
async def test_choosing_none_is_reported_as_no_coverage_not_as_a_low_score():
    """`choice: 0` is the contract's own answer for "the library holds nothing about this".

    It gets its own reason because the alternative — folding it into `low_confidence` or
    `none_chosen` — makes the two states a reader most needs to tell apart look identical on
    a silent tick: a weak answer that was held back, and no answer to hold back at all."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=8),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="d.md",
                text="t",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=0, confidence=9),
    )
    assert result.suggestions == ()
    assert result.skipped == SKIP_NO_COVERAGE


@pytest.mark.asyncio
async def test_a_choice_naming_no_candidate_stays_none_chosen():
    """A malformed index is not a judgement about coverage, and does not borrow its word."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=8),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="d.md",
                text="t",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=9, confidence=9),
    )
    assert result.skipped == SKIP_NONE_CHOSEN


@pytest.mark.asyncio
async def test_a_candidate_carrying_no_citation_is_held_as_uncited():
    """The belt under a construction that already attaches provenance.

    Nothing normally reaches here uncited — retrieval hands every claim its citations — and
    that is exactly why the refusal is written down: it is what makes the sentence checkable
    rather than trusted, and it is counted where the briefing lane counts the same fact."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=8),
        claims=[ClaimStub(anchor="c1", document_path="d.md", text="t", citations=[])],
        pick=PickResult(choice=1, lede="here it is", confidence=10),
    )
    assert result.suggestions == ()
    assert result.skipped == SKIP_UNCITED
    assert result.dropped == {"uncited": 1}


@pytest.mark.asyncio
async def test_a_high_score_on_a_candidate_off_the_intent_is_still_delivered():
    """The overreach fix is the CONTRACT, and nothing here second-guesses the model.

    A mechanism that compared the intent's words against the candidate's would be guessing
    about language — the failure it would be reaching for (a loosely related internal page
    scored 9 for a brand-new external release) is a judgement error, and the judgement is
    what the pick call is bought for. So this pins the design decision: the lane delivers
    what the model chose, and `test_the_pick_contract_defines_confidence_as_intent_match`
    below is where the actual fix is held."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="what is the DeepSeek harness released last week",
            plan=semantic_plan("DeepSeek harness"),
            worth=9,
        ),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="projects/inbound-router.md",
                text="The inbound router batches retries every 30s.",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=1, lede="here is what you need", confidence=9),
    )
    assert len(result.suggestions) == 1
    assert result.skipped == ""


def test_the_pick_contract_states_one_criterion_and_derives_the_rest_from_it():
    """The rewrite's whole shape, pinned in both packs.

    Discover writes a question; pick answers exactly one thing about each candidate — does
    that candidate's OWN TEXT answer it. Every other clause on the surface is that criterion
    applied, and the contract says so in that many words, because a list of four coordinate
    rules is what the surface was before and what it drifts back into as soon as the head is
    lost."""
    english = pick_contract()
    assert "**One criterion: does that candidate's OWN TEXT answer the question?**" in english
    assert "Everything below is\nthat criterion applied." in english
    assert "Four consequences of that one criterion:" in english

    chinese = chinese_overlay()["recall.live.pick.contract"]
    assert "**唯一的标准：这张候选自己的文本，回答了那个问题吗？**" in chinese
    assert "下面每一条都只是这条标准的推论" in chinese
    assert "这条唯一标准的四个推论：" in chinese


def test_the_pick_contract_scores_the_answer_and_refuses_adjacency():
    """The actual fix for the overreach, pinned where it lives.

    Asked about a release the library had never heard of, the lane retrieved the nearest
    internal project page and the pick scored it 9 — the candidate was well written, richly
    cited and roughly in that area, all of which are facts about the library rather than
    answers to the question. Three clauses carry that, and each is pinned because losing any
    one of them restores the failure:

    * confidence is how directly the candidate's OWN TEXT answers the question, not the
      candidate's quality;
    * adjacency — sharing a word, being the closest internal project — is NOT an answer;
    * what the library does not hold, it does not hold: choose 0.
    """
    english = pick_contract()
    for clause in (
        "HOW DIRECTLY THAT TEXT ANSWERS THE QUESTION",
        "Not how good the\n  candidate is",
        "**Adjacency is not an answer.**",
        "being the closest internal project to what was mentioned",
        "What the library does not hold, it does not hold.",
    ):
        assert clause in english, clause

    chinese = chinese_overlay()["recall.live.pick.contract"]
    for clause in (
        "**那段文本有多直接地回答了那个问题**",
        "不是这张候选有多好",
        "**沾边不是回答。**",
        "只是库里离那个名字最近的一个内部",
        "**库里没有就是没有。**",
    ):
        assert clause in chinese, clause


def test_the_pick_contract_refuses_a_candidate_that_says_it_cannot_answer():
    """A card whose body states an ABSENCE, delivered at confidence 9.

    The live failure: the room asked for a colleague who could present DeepSeek Harness, the
    web face came back with 「目前还缺少团队名单或可检索的内部资料，无法确定哪位同事…」 — the
    search engine explaining that it could not answer — and the pick chose it and shipped it
    with a citation. The text was fluent, on-topic and cited, and it told the reader nothing
    except that nobody knows. Choosing it is worse than choosing none, and the contract now
    says so in that many words, in both packs."""
    english = pick_contract()
    for clause in (
        "**Text that cannot answer, answers nothing.**",
        "something cannot be determined",
        "that reports\n  an ABSENCE",
        "Choose 0 over it.",
        "must ADD something the reader did not have",
    ):
        assert clause in english, clause

    chinese = chinese_overlay()["recall.live.pick.contract"]
    for clause in (
        "**答不上来的文本，什么都没回答。**",
        "说无法确定",
        "它陈述的\n  是一处**空缺**",
        "宁可填 0",
        "必须给\n  读者**添**上他原本没有的",
    ):
        assert clause in chinese, clause


def test_the_pick_contract_allows_a_marked_nearest_fit_recommendation():
    """The clause that keeps the honesty rules from forbidding the RIGHT answer.

    Asked who could present X, the useful card names the engineer the library evidences as
    closest to that work and says so as an inference — which is what the fast lane already
    does ("现有记录没有明确提到 DeepSeek harness，因此这是基于相关经验做的推荐"). Read without
    this clause, the adjacency and never-imply-coverage rules above would read as a ban on
    it, and the lane would be left with only silence and the non-answer. The allowance is
    narrow and mechanical in its own way: the marking is what separates it from adjacency."""
    english = pick_contract()
    for clause in (
        "**A marked nearest-fit RECOMMENDATION is an answer**",
        "to a who-could question",
        "mark the step you took",
        "not a record of the thing itself",
        "unmarked, it claims a match the library does not hold",
    ):
        assert clause in english, clause

    chinese = chinese_overlay()["recall.live.pick.contract"]
    for clause in (
        "**有标记的近邻推荐，是对「谁能做这件事」的回答。**",
        "**标明你这一步**",
        "不是关于那件事本身的记录",
        "不标明，\n  它就是在宣称一个库里",
    ):
        assert clause in chinese, clause


def test_the_pick_contract_forbids_writing_about_the_card_instead_of_its_substance():
    """The lede's grounding rule, tightened, in both packs.

    The delivered failure read 「这张卡说明了…」 — a sentence about the card rather than
    from it, which is how a lede can be fluent, in-register and still tell the reader
    nothing the library actually says. Two clauses hold it: say ONLY what the chosen
    candidate's own text says, and never claim the library answers a question it cannot."""
    english = pick_contract()
    assert "Never write ABOUT\n  the card" in english
    assert '"this card explains…"' in english
    assert "you may not imply an answer the text does not contain" in english
    assert "sentences ANSWERING the question in the room's own language" in english

    chinese = chinese_overlay()["recall.live.pick.contract"]
    assert "绝不要写**关于\n  这张卡本身**的" in chinese
    assert "「这张卡说明了……」" in chinese
    assert "不可以暗示一个文本里并不存在的答案" in chinese
    assert "用屋里自己的话**回答那个问题**" in chinese


@pytest.mark.asyncio
async def test_confidence_below_the_floor_holds_the_card_back():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=9),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="d.md",
                text="t",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=1, lede="x", confidence=3),
        min_confidence=6,
    )
    assert result.suggestions == ()
    assert result.skipped == SKIP_LOW_CONFIDENCE


def test_the_lede_is_capped_mechanically_not_merely_asked_for():
    from pneuma_knowledge_core.recall.live_pipeline import deliver

    cards = build_candidates(claims=[*PERSON_PAGE.claims])
    card, reason = deliver(
        PickResult(choice=1, lede="很长的一句话。" * 80, confidence=9),
        cards,
        min_confidence=1,
    )
    assert reason == ""
    assert len(card.body) <= LEDE_CHARS


def test_a_citation_index_out_of_range_falls_back_to_the_whole_list():
    from pneuma_knowledge_core.recall.live_pipeline import pick_citations

    cards = build_candidates(claims=[*PERSON_PAGE.claims])
    card = cards[0]
    assert pick_citations(card, [99]) == list(card.citations)
    assert pick_citations(card, []) == list(card.citations)
    assert pick_citations(card, [1]) == [card.citations[0]]


@pytest.mark.asyncio
async def test_a_card_already_shown_this_session_is_not_shown_again():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=9),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="people/lin-shu.md",
                text="林舒 is the agent-memory lead.",
                section_path=["overview", "definition"],
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=1, lede="x", confidence=9),
        already_shown=[{"kind": "concept", "title": "lin-shu"}],
    )
    assert result.suggestions == ()
    assert result.skipped == SKIP_DUPLICATE


# ------------------------------------------------------------------ the subject ledger


def test_the_ledger_holds_a_second_introduction_and_lets_a_new_fact_through():
    ledger = SubjectLedger()
    ledger.deliver("projects/lumenlab.md", "concept", "lumenlab")
    assert ledger.held_as_duplicate("projects/lumenlab.md", "concept")
    assert not ledger.held_as_duplicate("projects/lumenlab.md", "fact")


def test_an_alias_and_a_full_name_are_one_subject_because_the_page_is_one_page():
    """Normalisation is not a matcher written here: retrieval already resolved both to the
    same canonical document, so the document path IS the normalised identity."""
    by_alias = build_candidates(claims=[claim("a1", "people/lin-shu.md", "x", overview=True)])
    by_full = build_candidates(claims=[claim("a2", "people/lin-shu.md", "y", overview=True)])
    assert by_alias[0].subject == by_full[0].subject == "people/lin-shu.md"


def test_the_digest_names_a_recurring_subject_nobody_asked_about():
    ledger = SubjectLedger()
    for _ in range(3):
        ledger.touch("projects/lumenlab.md", "lumenlab")
    ledger.deliver("projects/lumenlab.md", "concept", "lumenlab")
    ledger.touch("people/one-off.md", "one-off")
    digest = ledger.digest()
    assert "lumenlab" in digest
    assert "already introduced" in digest and "nobody asked about it" in digest
    assert "one-off" not in digest, "a subject seen once carries no repetition signal"


@pytest.mark.asyncio
async def test_the_ledger_digest_reaches_the_discover_stage():
    ledger = SubjectLedger()
    for _ in range(4):
        ledger.touch("projects/lumenlab.md", "lumenlab")
    ledger.deliver("projects/lumenlab.md", "concept", "lumenlab")
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="already_mined"), ledger=ledger
    )
    human = discover_model.human
    assert "lumenlab" in human and "already introduced" in human
    assert "Subjects this conversation keeps returning to" in human


@pytest.mark.asyncio
async def test_the_subject_gate_holds_a_repeat_the_two_models_both_wanted():
    """Both calls agreed to deliver; the ledger refuses anyway. That is the backstop."""
    ledger = SubjectLedger()
    ledger.deliver("people/lin-shu.md", "concept", "lin-shu")
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=9),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="people/lin-shu.md",
                text="林舒 is the agent-memory lead.",
                section_path=["overview", "definition"],
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        pick=PickResult(choice=1, lede="x", confidence=10),
        ledger=ledger,
    )
    assert result.suggestions == ()
    assert result.skipped == SKIP_DUPLICATE


# ------------------------------------------------------- the pending window and I5


def test_the_pending_window_states_what_did_not_fit_instead_of_dropping_it_silently():
    turns = [owner(f"line {i}") for i in range(20)]
    window = take_pending(turns, max_pending_turns=12)
    assert len(window.turns) == 12
    assert window.turns[0].text == "line 8"
    assert window.overflowed == 8


@pytest.mark.asyncio
async def test_the_overflow_count_reaches_the_model():
    """20 turns, 5 of them pending: 8 of the other 15 now ride above as the read-only
    context tail, so exactly 7 reached NEITHER block. The count says "did not fit", and it
    would be false about turns printed two lines higher."""
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="nothing_new"),
        turns=[owner(f"line {i}") for i in range(20)],
        max_pending_turns=5,
    )
    assert "7 earlier turns did not fit" in discover_model.human
    assert "line 7" in discover_model.human, "the context tail starts at the 8th-from-last"
    assert "line 6" not in discover_model.human, "…and nothing older reaches the model"


# ───────────────────────── the read-only context tail (intent formation ≠ mining)
#
# Observed live: 「好像苹果要开新的发布会了」→「好像有折叠屏的手机要发」→「APP 需不需要在折叠
# 屏上适配」→「我们这边 iOS 负责的同学应该会关注的」 were consumed by a quiet tick that skipped
# (`nothing_new` — consumption is by design). The next turn, 「也可以看看其他团队有没有这方面的
# 专家」, arrived alone, and discover invented the domain: an intent about **Android** foldables.
# The subject had not changed; the window had.

APPLE = [
    other("好像苹果要开新的发布会了"),
    other("好像有折叠屏的手机要发"),
    owner("APP 需不需要在折叠屏上适配"),
    owner("我们这边 iOS 负责的同学应该会关注的"),
]
FIFTH = other("也可以看看其他团队有没有这方面的专家")


def test_the_context_tail_is_the_processed_turns_minus_whatever_is_pending():
    assert take_context(APPLE, [FIFTH]) == tuple(APPLE)
    # bounded, newest kept
    assert take_context(APPLE, [FIFTH], max_context_turns=2) == tuple(APPLE[-2:])
    assert take_context(APPLE, [FIFTH], max_context_turns=0) == ()
    # a turn that is still pending is never ALSO context: it would be read twice
    assert take_context([*APPLE, FIFTH], [FIFTH]) == tuple(APPLE)


@pytest.mark.asyncio
async def test_the_turns_a_skip_consumed_still_reach_the_next_tick_as_understanding():
    """The exact live shape: four turns consumed by a skip tick, the fifth alone pending."""
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        turns=[FIFTH],
        context_turns=APPLE,
    )
    human = discover_model.human
    context_head = human.index(prompt("recall.live.section.context_header", turns=4))
    pending_head = human.index(prompt("recall.live.section.pending_header", turns=1))
    assert context_head < pending_head, "understanding above, new content below"
    for turn in APPLE:
        assert turn.text in human[context_head:pending_head]
    assert FIFTH.text in human[pending_head:]
    assert FIFTH.text not in human[context_head:pending_head]


@pytest.mark.asyncio
async def test_the_contract_tells_the_stage_to_read_the_tail_and_never_mine_it():
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        turns=[FIFTH],
        context_turns=APPLE,
    )
    contract = discover_model.system
    assert "TWO parts" in contract or "两部分" in contract
    assert "Never mine it" in contract or "绝不要去挖它" in contract


@pytest.mark.asyncio
async def test_no_processed_turns_renders_exactly_the_turn_the_lane_always_rendered():
    """A first tick has no tail, and its Human turn must be what it has always been."""
    _, with_tail, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"), turns=[FIFTH], context_turns=()
    )
    assert prompt("recall.live.section.context_header", turns=0) not in with_tail.human
    assert "# " + prompt("recall.live.section.context_header", turns=1) not in with_tail.human


@pytest.mark.asyncio
async def test_the_context_tail_shares_one_labelling_pass_with_the_pending_window():
    """A participant number that meant one person above the fold and another below it is
    worse than no number at all."""
    speaker = other("我是第三个人", speaker_id="im/9")
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        turns=[other("同一个人又说话了", speaker_id="im/9")],
        context_turns=[speaker],
        label_map={},
    )
    human = discover_model.human
    label = human.split("我是第三个人")[0].rsplit("\n", 1)[-1]
    assert label and label in human.split("同一个人又说话了")[0].rsplit("\n", 1)[-1]


# ───────────────────────────── the density posture (three wordings of one contract)
#
# Observed live on the EAGER preset: 「建议这个事情还是交给我们日本市场的负责人来做吧。」 was
# skipped — delivered 0, no retrieval at all. The floors were already low; what the contract
# said was worth mining had not moved, so a ROLE standing in for a person nobody named was
# not a gap the stage recognised. A preset that is only numbers moves how MUCH gets through
# and never WHAT is looked for.


def test_the_three_postures_differ_in_exactly_one_clause_and_nothing_else():
    made = {d: discover_contract("general", (), density=d) for d in ("eager", "balanced", "quiet")}
    assert len({*made.values()}) == 3
    for density, contract in made.items():
        clause = prompt(f"recall.live.discover.mining.{density}")
        assert clause in contract
        # the SHARED half is byte-identical across all three
        assert contract.replace(clause, "«MINING»") == made["balanced"].replace(
            prompt("recall.live.discover.mining.balanced"), "«MINING»"
        )


def test_each_posture_is_byte_stable_and_carries_nothing_volatile():
    for density in ("eager", "balanced", "quiet"):
        contract = discover_contract("general", (), density=density)
        assert contract == discover_contract("general", (), density=density)
        assert "2026" not in contract


def test_the_default_and_every_unknown_value_are_the_middle_posture():
    """A density arrives from a preset pill, from an older client that has none, and from a
    custom setting carrying only numbers. None of those is a reason to fail a connection."""
    balanced = discover_contract("general", ())
    assert balanced == discover_contract("general", (), density="balanced")
    for junk in ("", "  ", "AGGRESSIVE", None, 7):
        assert discover_contract("general", (), density=junk) == balanced
    assert coerce_density("EAGER") == "eager", "the vocabulary is casefolded, not rejected"


def test_every_posture_varies_only_how_latent_the_question_may_be():
    """The rewrite's density axis, named in all three wordings and in both packs.

    Before, the three clauses were three different things — a definition of what is "worth a
    lookup" each time. Under one principle there is only one thing left for a density to
    move: how far below the surface the question may sit."""
    for density in ("eager", "balanced", "quiet"):
        assert prompt(f"recall.live.discover.mining.{density}").startswith(
            "**How latent may the question be**"
        ), density
        assert chinese_overlay()[f"recall.live.discover.mining.{density}"].startswith(
            "**这个问题可以有多隐**"
        ), density


def test_the_eager_posture_names_the_role_shape_as_a_class_never_as_a_transcript_line():
    eager = prompt("recall.live.discover.mining.eager")
    assert "a role or reference standing in for a person nobody named" in eager
    assert '"whoever runs X"' in eager, "an example CLASS, with a placeholder subject"
    assert "日本" not in eager and "Japan" not in eager, "never the owner's own transcript"


def test_the_eager_posture_widens_first_mention_curiosity_and_not_repetition():
    """The composition the owner asked for: on eager the question may be one the room has
    not realised it should ask — which reaches a business noun the FIRST time it appears —
    and the ledger's already-mined rule is untouched by that."""
    eager = prompt("recall.live.discover.mining.eager")
    assert "does not yet realise it should" in eager
    assert "FIRST mention" in eager and "internal project or product name" in eager
    assert "already answered is still `already_mined`" in eager
    # …and the shared rules it composes with are still in the contract above it
    contract = discover_contract("general", (), density="eager")
    assert "COMMON GROUND" in contract and "`already_mined`" in contract


def test_the_quiet_posture_asks_for_a_question_and_refuses_an_unnamed_gap():
    quiet = prompt("recall.live.discover.mining.quiet")
    assert "not at all" in quiet
    assert "actually ASKED" in quiet
    assert "A gap nobody named is not one." in quiet


def test_every_posture_aims_a_find_a_person_ask_at_the_people_and_not_at_a_definition():
    """The one steer that stays a RULE and not an example, in the SHARED half — so all three
    postures carry it.

    A conversation looking for somebody to present a public tool is a find-a-person question
    wearing an external subject, and the plan it deserves is the people around that subject
    PLUS a people-shaped similarity query. Aimed at the subject instead, the lane retrieves
    what the tool IS — an answer to a question nobody asked. The clause is about WHERE a
    lookup points, and how latent a question may be (the density axis) does not touch that.

    "BOTH entries" is load-bearing and measured: on the live stack the one-entry plan is the
    shape that comes back empty, because the people path can only answer for a subject the
    contact book already holds, and the similarity query is what reaches the nearest
    expertise when it does not."""
    for density in ("eager", "balanced", "quiet"):
        contract = discover_contract("general", (), density=density)
        for clause in (
            "A question about WHO takes BOTH entries and is answered by neither alone.",
            "whichever offered lookup is about people",
            "spend the OTHER on a similarity",
            '("who has worked on X, or on that kind of work")',
            "reaches the nearest expertise when the subject itself is not in the",
            "a definition of the subject answers nothing here",
        ):
            assert clause in contract, (density, clause)

    chinese = chinese_overlay()["recall.live.discover.contract"]
    for clause in (
        "问「谁」的问题要用掉**两条**，少一条都答不上",
        "把主体交给上面任何一条关于人的查询",
        "「做过 X 或同类工作的人」",
        "把主体解释一遍，在这里什么都没回答",
    ):
        assert clause in chinese, clause


def test_the_person_steering_names_no_component_path_it_cannot_know_is_enabled():
    """It says "whichever offered lookup is about people", never `people_around`.

    The offered kinds are a function of the registered components (I5's byte-stability rests
    on that), so a shared clause naming a path by name would advertise a lookup a deployment
    without the people component does not have — the same defect the web offer avoids by
    being a line that only renders when a search is behind it."""
    contract = discover_contract("general", ())
    assert "people_around" not in contract
    assert "`person`" not in contract
    assert "whichever offered lookup is about people" in contract


def test_the_web_offer_points_a_mixed_ask_at_the_outside_subject():
    """And it lives on the OFFER line, which renders only where a search exists.

    The steer belongs with the kind it steers: a deployment with no web search must not read
    a sentence about where its `web` query should go."""
    off, on = discover_contract("general", ()), discover_contract("general", (), web=True)
    assert "this query goes to X ITSELF" in on
    assert "this query goes to X ITSELF" not in off
    assert "the library lookups take the person half" in on

    chinese = chinese_overlay()["recall.live.discover.web_offer"]
    assert "这条查询就指向 **X 本身**" in chinese
    assert "找人那一半交给库里的查询" in chinese


def test_the_pick_contract_does_not_vary_by_density():
    """Delivery honesty is not a density matter: a card the library cannot support is not
    more deliverable because the connection asked for more of them."""
    import inspect

    assert "density" not in inspect.signature(pick_contract).parameters


@pytest.mark.asyncio
async def test_the_posture_reaches_the_model_and_is_recorded_on_the_tick():
    result, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"), density="eager"
    )
    assert prompt("recall.live.discover.mining.eager") in discover_model.system
    assert result.density == "eager", "the record says which posture produced this skip"


@pytest.mark.asyncio
async def test_a_tick_with_no_posture_stated_records_the_middle_one():
    result, _, _, _, _, _ = await run_lane(discover=discovered(skip=True, reason="small_talk"))
    assert result.density == "balanced"


def test_with_no_component_registered_only_semantic_is_offered():
    contract = discover_contract("general", ())
    assert "`semantic`" in contract
    assert "`person`" not in contract and "`timespan`" not in contract
    # byte-stable: nothing volatile, and the same call twice is the same bytes
    assert contract == discover_contract("general", ())
    assert "2026" not in contract


def test_an_enabled_path_introduces_itself_in_the_contract_and_nowhere_else():
    contract = discover_contract("general", (FakePersonPath(PERSON_PAGE),))
    assert "`person`" in contract
    assert "alias, identity" in contract, "the path's OWN argument schema, not a copy"
    assert contract != discover_contract("general", ())


def test_the_two_focus_postures_change_the_discover_system_and_only_that():
    general = discover_contract("general", ())
    owner_focus = discover_contract("owner", ())
    assert general != owner_focus
    assert general.split("**Scope of attention")[0] == owner_focus.split("**Scope of attention")[0]


# ------------------------------------------------------- the supplementary web face


def test_the_web_lookup_is_offered_only_when_a_search_is_actually_behind_it():
    """The offer costs the small model attention, so it is made on evidence.

    Two shapes of one contract, and the line is the whole difference — which is why both
    are byte-pinned in `test_prompt_surfaces.py` rather than only asserted about here."""
    off, on = discover_contract("general", ()), discover_contract("general", (), web=True)
    assert "`web`" not in off
    assert "`web`" in on
    web_line = prompt("recall.live.discover.web_offer")
    assert on == off.replace(
        prompt("recall.live.discover.semantic_offer"),
        prompt("recall.live.discover.semantic_offer") + "\n" + web_line,
    ), "the offer is one appended line and nothing else moves"


@pytest.mark.asyncio
async def test_an_unavailable_search_is_not_offered_even_when_one_was_passed():
    """`available()` is the deployment's own answer and it is asked before the assembly.

    A search object that is wired but unconfigured (no key) must not put a `web` line in
    front of the model: the plan it would invite is one `plan_runs` then rejects."""
    result, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        web_search=FakeWebSearch(on=False),
    )
    assert "`web`" not in discover_model.system
    assert result.skipped == "small_talk"


@pytest.mark.asyncio
async def test_the_web_face_runs_concurrently_with_the_library_faces():
    """Measured as an interval overlap, like the component/semantic pair above.

    A supplement that ran after the library would add its latency to every tick that used
    it; inside the same gather it adds at most the difference."""
    recorder = Recorder()
    path = FakePersonPath(PERSON_PAGE, recorder)
    web = FakeWebSearch(WEB_ANSWER, recorder=recorder)
    await run_lane(
        discover=discovered(
            intent="what is the DeepSeek harness",
            plan=[person_plan("林舒"), web_plan("DeepSeek harness")],
            worth=9,
        ),
        pick=PickResult(choice=1, lede="l", confidence=9),
        paths=[path],
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="d.md",
                text="t",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        recorder=recorder,
        web_search=web,
    )
    assert recorder.overlap("person", "web") > 0, "the web face must not run after the rest"


@pytest.mark.asyncio
async def test_a_web_answer_becomes_one_card_carrying_its_urls_and_no_source_spans():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="what is the DeepSeek harness",
            plan=[web_plan("DeepSeek harness")],
            worth=9,
        ),
        pick=PickResult(choice=1, lede="It shipped last week.", confidence=9),
        web_search=FakeWebSearch(WEB_ANSWER),
    )
    (card,) = result.suggestions
    assert card.kind == "web"
    assert card.title == "DeepSeek harness"
    # The provider's own sentence, unrewritten: the evidence is the answer, byte for byte.
    assert card.evidence == WEB_ANSWER.text
    assert card.citations == [], "a web card points at no source block"
    assert [c.url for c in card.web_citations] == ["https://example.test/dsh"]
    assert result.web_searches == 2 and result.web_cost == pytest.approx(0.0141)
    assert result.web_pages == 1


def test_a_web_answer_naming_no_page_is_never_built_into_a_card():
    """The web face's whole citation gate, applied where the card is built.

    There is no source block to resolve and nothing to check a sentence against, so the one
    mechanical thing available is "it named at least one page" — and an answer that named
    none is dropped in silence rather than delivered as unsourced prose."""
    assert candidate_from_web(WebSearchAnswer(text="probably yes"), "q", 1) is None
    assert candidate_from_web(
        WebSearchAnswer(text="", citations=(WebCitation(url="https://x.test"),)), "q", 1
    ) is None
    assert candidate_from_web(WEB_ANSWER, "q", 1) is not None


@pytest.mark.asyncio
async def test_a_dead_web_search_degrades_the_face_and_never_blocks_the_tick():
    """Fail-soft, both ways it can fail. The library card still ships."""
    for search in (
        FakeWebSearch(delay=0.5),
        FakeWebSearch(raises=RuntimeError("provider is down")),
    ):
        result, _, _, _, _, _ = await run_lane(
            discover=discovered(
                intent="i",
                plan=[PlanEntry(kind="semantic", query="q"), web_plan("w")],
                worth=9,
            ),
            pick=PickResult(choice=1, lede="l", confidence=9),
            claims=[
                ClaimStub(
                    anchor="c1",
                    document_path="d.md",
                    text="t",
                    citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
                )
            ],
            web_search=search,
            min_confidence=6,
            web_timeout=0.05,
        )
        assert len(result.suggestions) == 1, "a dead supplement must not cost the card"
        web_stage = next(s for s in result.stages if s.name == "retrieve.web")
        assert web_stage.status == "degraded"
        assert web_stage.detail in ("timeout", "RuntimeError")


@pytest.mark.asyncio
async def test_the_same_web_query_twice_is_held_by_the_ledger():
    """A web card is a subject like any other, so the (subject × kind) backstop covers it.

    The subject is the QUERY, normalised — asking the internet the same thing twice in one
    conversation is the same repetition the ledger exists to refuse for library cards."""
    ledger = SubjectLedger()
    kwargs = dict(
        discover=discovered(intent="i", plan=[web_plan("DeepSeek harness")], worth=9),
        pick=PickResult(choice=1, lede="l", confidence=9),
        web_search=FakeWebSearch(WEB_ANSWER),
        ledger=ledger,
    )
    first, _, _, _, _, _ = await run_lane(**kwargs)
    (card,) = first.suggestions
    ledger.deliver(card.subject, card.kind, card.subject_label)

    second, _, _, _, _, _ = await run_lane(
        **{**kwargs, "discover": discovered(intent="i", plan=[web_plan("  DeepSeek Harness ")], worth=9)}
    )
    assert second.suggestions == ()
    assert second.skipped == SKIP_DUPLICATE


# ------------------------------------------- one pool, one picker: origin and the tiers


def test_every_candidate_states_which_pool_it_came_out_of():
    """The precondition for the contract's source-blind rule.

    The rule says where a candidate came from is not a ranking and the match is — which is
    a rule about something only if the two pools are legible on the card. A model left to
    infer the pool from a title would infer it, and would infer it from the wrong things."""
    cards = build_candidates(
        claims=[claim("c1", "projects/inbound-router.md", "It batches retries.")],
        web=[(WEB_ANSWER, "DeepSeek harness")],
    )
    assert [c.provenance for c in cards] == [PROVENANCE_LIBRARY, PROVENANCE_WEB]
    rendered = render_candidates(cards)
    assert "source: the owner's own knowledge base" in rendered
    assert "source: a live internet search" in rendered
    # And the web card's provenance is its pages, numbered exactly as a library card's spans
    # are, so the pick stage prunes both by the same index rule.
    assert "[1] Release notes — https://example.test/dsh" in rendered


def test_the_pick_contract_ranks_by_match_and_never_by_which_pool_a_card_came_from():
    """The noise rule, stated for the two-pool world, pinned in both packs.

    Without it the lane has a new failure available to it: an internal candidate that merely
    brushes the intent beating a web candidate that answers it, because it is "ours"."""
    english = pick_contract()
    assert "**Where a candidate came from is not a ranking; the answer is.**" in english
    assert "Read every candidate\n  against the question the same way, whichever pool it came out of." in english

    chinese = chinese_overlay()["recall.live.pick.contract"]
    assert "**来源不是优先级，回答才是。**" in chinese
    assert "都用同一把尺子、对着那个问题读每一张候选" in chinese


@pytest.mark.asyncio
async def test_the_fallback_tier_fires_only_on_an_empty_library_pool():
    """Tier (b). Not a second delivery route — a second way to reach the SAME pool.

    Sequential, and that is the design: until the library came back empty there was nothing
    worth paying a search for, and once it has, the only alternatives are a web card and
    silence."""
    search = FakeWebSearch(WEB_ANSWER)
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="what is the DeepSeek harness",
            plan=semantic_plan("DeepSeek harness"),
            worth=9,
        ),
        pick=PickResult(choice=1, lede="It shipped last week.", confidence=9),
        claims=[],  # the library has nothing at all
        web_search=search,
    )
    assert result.web_tier == WEB_FALLBACK
    assert search.questions == ["what is the DeepSeek harness"], "the intent is the query"
    (card,) = result.suggestions
    assert card.kind == "web"


@pytest.mark.asyncio
async def test_the_fallback_tier_does_not_fire_when_the_library_answered():
    """A library card, however weak, is not an empty pool: the supplement stays unpaid."""
    search = FakeWebSearch(WEB_ANSWER)
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=9),
        pick=PickResult(choice=1, lede="l", confidence=9),
        claims=[
            ClaimStub(
                anchor="c1",
                document_path="d.md",
                text="t",
                citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
            )
        ],
        web_search=search,
    )
    assert result.web_tier == WEB_OFF
    assert search.questions == [], "an answered library must not trigger a paid search"


@pytest.mark.asyncio
async def test_the_fallback_tier_does_not_fire_with_the_toggle_off():
    search = FakeWebSearch(WEB_ANSWER, on=False)
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=semantic_plan("q"), worth=9),
        claims=[],
        web_search=search,
    )
    assert result.web_tier == WEB_OFF
    assert search.questions == []


@pytest.mark.asyncio
async def test_a_planned_web_lookup_is_reported_as_the_planned_tier():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[web_plan("DeepSeek harness")], worth=9),
        pick=PickResult(choice=1, lede="l", confidence=9),
        web_search=FakeWebSearch(WEB_ANSWER),
    )
    assert result.web_tier == WEB_PLANNED


@pytest.mark.asyncio
async def test_a_delivered_web_card_carries_its_pages_and_honours_the_pruned_subset():
    """The evidence surface is UNIFORM across pools.

    A web card's pages arrive where a library card's spans arrive, numbered the same way,
    and the pick's citation subset selects into them by the same index rule — including the
    fallback-to-all that stops a typo from stripping a card of its provenance."""
    answer = WebSearchAnswer(
        text="The DeepSeek harness is an open evaluation runner.",
        citations=(
            WebCitation(title="Release notes", url="https://example.test/a"),
            WebCitation(title="Benchmark table", url="https://example.test/b"),
        ),
        searches=1,
        cost=0.008,
    )
    kwargs = dict(
        discover=discovered(intent="i", plan=[web_plan("DeepSeek harness")], worth=9),
        web_search=FakeWebSearch(answer),
    )

    picked, _, _, _, _, _ = await run_lane(
        **kwargs, pick=PickResult(choice=1, lede="l", citations=[2], confidence=9)
    )
    (card,) = picked.suggestions
    assert [c.url for c in card.web_citations] == ["https://example.test/b"]
    assert card.citations == [], "a web card carries no source span, ever"

    unusable, _, _, _, _, _ = await run_lane(
        **kwargs, pick=PickResult(choice=1, lede="l", citations=[7], confidence=9)
    )
    (card,) = unusable.suggestions
    assert [c.url for c in card.web_citations] == [
        "https://example.test/a",
        "https://example.test/b",
    ], "an unusable subset falls back to all of them rather than stripping the card"


def test_a_talkative_library_can_never_truncate_the_web_candidate_out_of_the_pool():
    """Found live, on the real library, and it had already been paid for.

    Six adjacent project pages filled the candidate list; the web search had run, cost
    $0.023 and returned an answer — and the pool handed to the pick stage contained none of
    it, because the limit was applied in list order and the supplement sat last. The pick
    then answered `no_coverage`, correctly, about a list it had never been shown the answer
    in. So the web rows are RESERVED: the bound still holds, and what it drops is a library
    card rather than the one candidate that was bought."""
    crowd = [
        claim(f"c{i}", f"projects/p{i}.md", f"Project {i} batches retries.")
        for i in range(10)
    ]
    cards = build_candidates(claims=crowd, web=[(WEB_ANSWER, "DeepSeek harness")])
    assert len(cards) == 6, "the bound still holds"
    assert cards[-1].provenance == PROVENANCE_WEB, "and the supplement survives it"
    assert [c.index for c in cards] == [1, 2, 3, 4, 5, 6], "renumbered with no gaps"
    # Order is unchanged: the library is still read first. The reserve is about survival.
    assert [c.provenance for c in cards[:5]] == [PROVENANCE_LIBRARY] * 5


@pytest.mark.asyncio
async def test_a_search_that_named_no_page_is_reported_as_paid_for_and_empty():
    """The one outcome that would otherwise be invisible, made legible.

    The answer is refused at construction (no page, no card) — correctly — but the tick had
    still run a search and been billed for it. Without `web_pages` the record shows a cost
    beside an absent candidate and says nothing about which gate ate it, which is exactly
    the kind of silent hole this lane's telemetry exists to close."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[web_plan("q")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        web_search=FakeWebSearch(
            WebSearchAnswer(text="probably yes", citations=(), searches=2, cost=0.019)
        ),
    )
    assert result.web_tier == WEB_PLANNED
    assert result.web_searches == 2 and result.web_cost == pytest.approx(0.019)
    assert result.web_pages == 0, "billed, and it named nothing"
    assert all(c.provenance == PROVENANCE_LIBRARY for c in result.candidates)


# ════════════════════════════════════════════════ the glance short-circuit
#
# By the end of discover the lane already knows what the room is looking for — and where the
# plan names a subject the library holds, the library already holds one grounded sentence
# about it. That sentence goes out immediately, verbatim, marked provisional, while stages 2
# and 3 keep running. No extra model call: a resolution and a parse.

LUMEN = CanonicalDocument(
    doc_id=DocumentId("d-lumen"),
    path="projects/lumenlab.md",
    frontmatter={"doc_id": "d-lumen", "type": "project", "slug": "lumenlab", "title": "Lumen Lab"},
    body=(
        "# Lumen Lab\n\n"
        "<!-- overview -->\n\n"
        "<!-- overview:definition -->\n### definition\n\n"
        "Lumen Lab builds optical benches for the agent-memory group. c:1a1a "
        "<!-- c:0d0d -->\n\n"
        "<!-- /overview -->\n\n"
        "## Log\n\n"
        f"- Lumen Lab shipped its second bench. [cite: {SRC} ¶4-5] <!-- c:1a1a -->\n"
    ),
)

#: Same page, no overview at all — the miss case, and every page written before the region
#: existed looks exactly like this.
BENCH = CanonicalDocument(
    doc_id=DocumentId("d-bench"),
    path="projects/apex-bench.md",
    frontmatter={"doc_id": "d-bench", "type": "project", "slug": "apex-bench"},
    body=f"# Apex Bench\n\n- Apex Bench reuses the optics. [cite: {SRC} ¶0-1] <!-- c:2b2b -->\n",
)


def subject_plan(value: str, kind: str = "people_around") -> PlanEntry:
    return PlanEntry(kind=kind, args=[PlanArg(name="subject", value=value)])


class SlowPath(FakePersonPath):
    """Retrieval that has not finished when the glance card is asserted on."""

    name = "people_around"

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return await super().run(user_id, args, scope=scope, documents=documents, as_of=as_of)


class Glances:
    """A transport: records what it was handed and WHEN, relative to the tick."""

    def __init__(self) -> None:
        self.cards: list = []
        self.at: list[float] = []
        self._t0 = time.perf_counter()

    async def __call__(self, card) -> None:  # noqa: ANN001
        self.cards.append(card)
        self.at.append(time.perf_counter() - self._t0)


@pytest.mark.asyncio
async def test_the_definition_goes_out_before_retrieval_has_finished():
    """The whole claim of the mechanism is WHEN it lands."""
    seen = Glances()
    path = SlowPath(PathResult(claims=(claim("z1", "projects/lumenlab.md", "later"),)))
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="what is Lumen Lab", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=1, lede="here", citations=[1], confidence=9),
        paths=[path],
        documents=[LUMEN, BENCH],
        on_glance=seen,
    )
    [card] = seen.cards
    assert card.kind == "glance" and card.provisional is True
    assert card.body == "Lumen Lab builds optical benches for the agent-memory group."
    assert card.subject == "projects/lumenlab.md"
    assert seen.at[0] < 0.05, "delivered while the 50ms retrieval was still running"
    assert result.glance_state == "hit"
    assert result.glance_ms > 0.0


@pytest.mark.asyncio
async def test_the_definition_carries_the_citations_of_the_claims_it_rests_on():
    """No second store: the overview's rule is that every block rests on a ledger claim, so
    following the `c:xxxx` reference IS the provenance."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("lumenlab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN],
    )
    assert [(str(c.source_id), c.block_start, c.block_end) for c in result.glance.citations] == [
        (SRC, 4, 5)
    ]


@pytest.mark.asyncio
async def test_a_full_card_about_the_same_subject_upgrades_the_provisional_one():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=1, lede="the bench programme moved", citations=[1], confidence=9),
        paths=[SlowPath(PathResult(claims=(claim("z1", "projects/lumenlab.md", "moved"),)))],
        documents=[LUMEN],
    )
    assert result.glance_outcome == "upgraded"
    [card] = result.suggestions
    assert card.subject == result.glance.subject, "the same bubble, filled in"


@pytest.mark.asyncio
async def test_a_full_card_about_a_different_subject_settles_the_glance_and_queues_beside_it():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=1, lede="a different matter", citations=[1], confidence=9),
        paths=[SlowPath(PERSON_PAGE)],
        documents=[LUMEN],
    )
    assert result.glance_outcome == "settled"
    [card] = result.suggestions
    assert card.subject != result.glance.subject


@pytest.mark.asyncio
async def test_a_pick_that_chose_none_settles_the_glance_silently():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PERSON_PAGE)],
        documents=[LUMEN],
    )
    assert result.glance_outcome == "alone"
    assert result.suggestions == ()
    assert result.glance is not None, "the reader keeps the true sentence they were shown"


@pytest.mark.asyncio
async def test_a_subject_with_no_definition_is_a_miss_and_nothing_is_delivered_early():
    seen = Glances()
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Apex Bench")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN, BENCH],
        on_glance=seen,
    )
    assert (result.glance_state, result.glance_outcome, result.glance) == ("miss", "", None)
    assert seen.cards == []


@pytest.mark.asyncio
async def test_a_tie_glances_at_nothing_rather_than_at_one_of_them():
    """Two documents equally named is precisely when an instant one-sentence answer would be
    confidently wrong; the pipeline behind it has a question in hand and this does not."""
    twin = CanonicalDocument(
        doc_id=DocumentId("d-twin"),
        path="topics/lumenlab.md",
        frontmatter={"doc_id": "d-twin", "slug": "lumen-topic", "title": "Lumen Lab"},
        body=LUMEN.body,
    )
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN, twin],
    )
    assert result.glance_state == "miss"


@pytest.mark.asyncio
async def test_a_skip_never_reaches_the_short_circuit():
    seen = Glances()
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="small_talk"),
        documents=[LUMEN],
        on_glance=seen,
    )
    assert seen.cards == [] and result.glance_state == "miss"


@pytest.mark.asyncio
async def test_the_repetition_rules_apply_to_a_glance_like_any_other_card():
    ledger = SubjectLedger()
    ledger.deliver("projects/lumenlab.md", "glance", "lumenlab")
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN],
        ledger=ledger,
    )
    assert result.glance_state == "miss", "no second introduction of a subject already glanced"


@pytest.mark.asyncio
async def test_a_card_the_client_already_holds_is_not_glanced_at_again():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN],
        already_shown=[{"kind": "glance", "title": "Lumen Lab"}],
    )
    assert result.glance_state == "miss"


@pytest.mark.asyncio
async def test_with_no_canonical_passed_the_lane_is_what_it_always_was():
    """The mechanism is opt-in at the wiring: a deployment that hands the lane no documents
    gets no short-circuit and no behaviour change at all."""
    seen = Glances()
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        on_glance=seen,
    )
    assert seen.cards == [] and result.glance_state == "miss" and result.glance_ms == 0.0


@pytest.mark.asyncio
async def test_a_failing_transport_callback_never_fails_the_tick_behind_it():
    async def explode(card) -> None:  # noqa: ANN001
        raise RuntimeError("socket gone")

    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN],
        on_glance=explode,
    )
    assert result.glance_state == "hit", "built and recorded; only the delivery failed"


def test_the_plan_subjects_are_read_without_core_knowing_one_argument_name():
    """Core names no component, so it cannot ask for `subject` — it offers every value to an
    exact resolution that answers for almost none of them. Whole values first, then their
    own words: a routed path's argument is often the subject exactly, but a semantic query
    is a sentence, and a sentence is never equal to a document's title."""
    assert plan_subjects(
        [
            PlanEntry(kind="people_around", args=[PlanArg(name="subject", value="Lumen Lab")]),
            PlanEntry(kind="semantic", query="what is Lumenlab, exactly?"),
            PlanEntry(kind="person", args=[PlanArg(name="identity", value="")]),
        ]
    ) == [
        "Lumen Lab",
        "what is Lumenlab, exactly?",
        "Lumen",
        "Lab",
        "what",
        "is",
        "Lumenlab",
        "exactly",
    ]


def test_a_long_query_cannot_turn_one_lookup_into_a_hundred():
    subjects = plan_subjects([PlanEntry(kind="semantic", query=" ".join(f"w{n}" for n in range(60)))])
    assert len(subjects) == 1 + PLAN_WORDS_MAX


@pytest.mark.asyncio
async def test_a_subject_named_inside_a_semantic_question_still_gets_its_definition():
    """The live shape this exists for: 「lumenlab 是什么？」 plans one semantic query, and the
    sentence is not equal to any document's title."""
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="what is Lumen Lab",
            plan=semantic_plan("lumenlab 是什么？我一直没搞清楚。"),
            worth=9,
        ),
        pick=PickResult(choice=0, confidence=9),
        documents=[LUMEN, BENCH],
    )
    assert result.glance_state == "hit"
    assert result.glance.title == "Lumen Lab"


@pytest.mark.asyncio
async def test_a_document_the_plan_names_outright_beats_a_word_inside_another_value():
    result, _, _, _, _, _ = await run_lane(
        discover=discovered(
            intent="i",
            plan=[
                subject_plan("Apex Bench"),
                PlanEntry(kind="semantic", query="how does lumenlab compare"),
            ],
            worth=9,
        ),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        documents=[LUMEN, BENCH],
    )
    # `Apex Bench` resolves first and carries no definition, so the glance falls through to
    # the next candidate rather than stopping — but a WHOLE value is always tried before any
    # word, which is what keeps the plan's own naming authoritative.
    assert result.glance_state == "hit" and result.glance.title == "Lumen Lab"


@pytest.mark.asyncio
async def test_a_skip_never_pays_the_canonical_read_the_short_circuit_would_have_used():
    """A skip is this lane's steady state. A tick that read the whole library before
    deciding a stretch was small talk would make the cheap stage expensive to protect a card
    it was never going to deliver."""
    reads = []

    async def load():
        reads.append(1)
        return [LUMEN]

    await run_lane(discover=discovered(skip=True, reason="small_talk"), load_documents=load)
    assert reads == []


@pytest.mark.asyncio
async def test_a_real_plan_pays_it_exactly_once():
    reads = []

    async def load():
        reads.append(1)
        return [LUMEN]

    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PathResult())],
        load_documents=load,
    )
    assert reads == [1] and result.glance_state == "hit"


@pytest.mark.asyncio
async def test_a_failing_canonical_read_costs_the_glance_and_never_the_tick():
    async def broken():
        raise RuntimeError("git is busy")

    result, _, _, _, _, _ = await run_lane(
        discover=discovered(intent="i", plan=[subject_plan("Lumen Lab")], worth=9),
        pick=PickResult(choice=0, confidence=9),
        paths=[SlowPath(PATH_HIT := PathResult(claims=(claim("z9", "d.md", "still here"),)))],
        load_documents=broken,
    )
    assert result.glance_state == "miss"
    assert result.skipped != "", "the tick itself ran to its own ending"
