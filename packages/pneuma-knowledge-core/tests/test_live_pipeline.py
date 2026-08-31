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

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import SourceId, UserId
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


def test_the_pick_contract_defines_confidence_as_intent_match_and_refuses_adjacency():
    """The actual fix for the overreach, pinned where it lives.

    Asked about a release the library had never heard of, the lane retrieved the nearest
    internal project page and the pick scored it 9 — the candidate was well written, richly
    cited and roughly in that area, all of which are facts about the library rather than
    answers to the question. Three clauses now carry that, and each is pinned because
    losing any one of them restores the failure:

    * confidence is the match between the INTENT and the candidate's OWN TEXT, not the
      candidate's quality;
    * adjacency — sharing a word, being the closest internal project — is NOT coverage;
    * what the library does not hold, it does not hold: choose 0.
    """
    english = pick_contract()
    for clause in (
        "HOW DIRECTLY THE CHOSEN CANDIDATE'S OWN TEXT ANSWERS THE STATED\n  INTENT",
        "Not how good the candidate is",
        "**Adjacency is not coverage.**",
        "being the closest internal project to what was mentioned",
        "**What the library does not hold, it does not hold**",
    ):
        assert clause in english, clause

    chinese = chinese_overlay()["recall.live.pick.contract"]
    for clause in (
        "**所选候选自己的文本，有多直接地回答了那句意图**",
        "不是这张候选有多好",
        "**沾边不等于覆盖。**",
        "只是库里离那个名字最近的一个内部",
        "**库里没有就是没有**",
    ):
        assert clause in chinese, clause


def test_the_pick_contract_forbids_writing_about_the_card_instead_of_its_substance():
    """The lede's grounding rule, tightened, in both packs.

    The delivered failure read 「这张卡说明了…」 — a sentence about the card rather than
    from it, which is how a lede can be fluent, in-register and still tell the reader
    nothing the library actually says. Two clauses hold it: say ONLY what the chosen
    candidate's own text says, and never claim the library answers a question it cannot."""
    english = pick_contract()
    assert "Never write ABOUT the card itself" in english
    assert '"this card explains…"' in english
    assert "never imply the library answers the\n  question when it does not" in english

    chinese = chinese_overlay()["recall.live.pick.contract"]
    assert "绝不要写**关于这张卡本身**的" in chinese
    assert "「这张卡说明了……」" in chinese
    assert "绝不要在知识库其实答不上来" in chinese


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
    _, discover_model, _, _, _, _ = await run_lane(
        discover=discovered(skip=True, reason="nothing_new"),
        turns=[owner(f"line {i}") for i in range(20)],
        max_pending_turns=5,
    )
    assert "15 earlier turns did not fit" in discover_model.human


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
    assert "**Where a candidate came from is not a ranking; the match is.**" in english
    assert "choose the web\none; when the reverse holds, choose the internal one" in english
    assert "When neither answers it, choose 0." in english

    chinese = chinese_overlay()["recall.live.pick.contract"]
    assert "**来源不是优先级，匹配度才是。**" in chinese
    assert "只是沾边、而 web 候选直接回答了意图时，就选 web；反之亦然；都不回答就选 0。" in chinese


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
