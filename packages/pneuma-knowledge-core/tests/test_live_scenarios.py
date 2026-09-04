"""Golden scenarios: the week's real Live Context conversations, as synthetic twins.

WHY A TABLE AND NOT MORE TESTS
------------------------------
`test_live_pipeline.py` breaks one MECHANISM per test — a skip touches no index, the plan's
entries run concurrently, the ledger holds a second introduction. That is the right unit for
a mechanism and the wrong unit for a REGRESSION: what went wrong live was never one
mechanism, it was a whole conversation arriving at the wrong ending. Four days of case-law
accreted in the discover contract that way — a clause for role references, one for
first-mention business nouns, one for negative web cards — each added after a specific room
got a specific wrong answer, and none of them checkable afterwards except by talking to the
real stack again.

So this module is a TABLE. One row per conversation the lane actually met, replayed as a
synthetic twin: the owner's real names and products never enter the repository, and what is
kept is the SHAPE — the same turn count, the same latency of the question, the same kind of
subject, the same posture. Adding a scenario is adding a row.

Everything here is keyless. Where a model turn is unavoidable its output is SCRIPTED, and
the assertion is on what the pipeline did with it plus, where that is the point, on the
bytes of the prompt the stage was actually handed. A scripted discover proves the plumbing
carries a decision; the prompt assertion proves the decision was ASKABLE from what the model
could see. Neither is enough alone: the context-loss twin (row 3) failed live with correct
plumbing and a window that could not support the right answer.

THE PRINCIPLE THESE ROWS ARE ABOUT
----------------------------------
Discover's job is to write, on the room's behalf, the ONE QUESTION most worth asking right
now. Every row is that principle meeting a room:

    small talk            → no question worth asking            → skip
    a mined subject again → the room already knows the answer   → skip
    a lost domain         → the question must still name it     → the context tail
    an unnamed role       → "who is that?"                      → density decides
    a first mention       → "what is that?"                     → once, then mined
    a find-a-person ask   → "who here knows X best?"            → people, not a definition
    a negative web answer → answers the question? no            → nothing is delivered
    a defined subject     → the library's own sentence, now     → the glance short-circuit
    …and nothing behind it→ the ending is named all the same    → the glance settles alone
    two things in one turn→ one query each, one merged pool     → the semantic fan-out
    a closed-volume hit  → whose history am I reading?         → the parent's identity

Live mode: `PNEUMA_SCENARIOS_LIVE=1` is deliberately NOT implemented. Every row here scripts
the model turn it is about, so a live variant would have to script nothing and assert nothing
— it would be an eyeballing harness wearing a test's clothes, and the same eyeballing is one
`pnpm dev` away against a real library. What replaced it is the assertion on rendered prompt
bytes: that is the part of a live run a keyless test can actually keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from pydantic import BaseModel, Field

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.domain.suggestion import (
    ContextDensity,
    DiscoverResult,
    PickResult,
    PlanArg,
    PlanEntry,
    WebCitation,
)
from pneuma_knowledge_core.ports.web_search import WebSearchAnswer
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.live_pipeline import (
    GLANCE_ALONE,
    GLANCE_HIT,
    GLANCE_SETTLED,
    GLANCE_UPGRADED,
    SKIP_NO_COVERAGE,
    SubjectLedger,
)
from pneuma_knowledge_core.recall.paths import PathResult

# The mechanism suite's fakes, reused rather than copied: a second `FakeStructured` would be
# a second thing to keep true about how a structured call is made.
from test_live_pipeline import (  # noqa: E402
    ClaimStub,
    FakeWebSearch,
    LUMEN,
    LUMEN_VOLUME,
    SRC,
    claim,
    other,
    owner,
    run_lane,
)

# ─────────────────────────────────────────────────────────── the synthetic vocabulary
#
# Lumen Lab (an internal optical-bench programme) and Apex Bench (a public evaluation
# harness) are the repository's existing synthetic subjects; Mei Lin and Ke Zhou are its
# existing synthetic people. Every row below is written in that vocabulary and in no other,
# so a real product name cannot arrive here by being convenient.

MEI_LIN = PathResult(
    claims=(
        claim("p1", "people/mei-lin.md", "Mei Lin leads the optical-bench programme."),
        claim("p2", "people/mei-lin.md", "Mei Lin ran the second bench's calibration."),
    )
)

KE_ZHOU_PAGE = CanonicalDocument(
    doc_id=DocumentId("d-ke-zhou"),
    path="people/ke-zhou.md",
    frontmatter={"doc_id": "d-ke-zhou", "type": "person", "slug": "ke-zhou", "title": "Ke Zhou"},
    body=(
        "# Ke Zhou\n\n"
        "<!-- overview -->\n\n"
        "<!-- overview:definition -->\n### definition\n\n"
        "Ke Zhou runs the Lumen Lab side of the bench programme. c:3c3c "
        "<!-- c:9f9f -->\n\n"
        "<!-- /overview -->\n\n"
        "## Log\n\n"
        f"- Ke Zhou took over Lumen Lab in March. [cite: {SRC} ¶2-3] <!-- c:3c3c -->\n"
    ),
)

#: The one outcome the negative-web row is about: a search that ran, was billed, cited a
#: page — and whose text is the search engine saying it could not find out.
NO_ANSWER_FROM_THE_WEB = WebSearchAnswer(
    text=(
        "I could not determine which colleague works on Apex Bench: there is no public "
        "roster, and I have no access to the internal directory."
    ),
    citations=(WebCitation(title="Apex Bench docs", url="https://example.test/apex"),),
    searches=1,
    cost=0.011,
)


class SubjectArgs(BaseModel):
    subject: str = Field(default="", description="the subject to find people around")


class PeopleAroundPath:
    """The `people_around` retrieval path, as the people component registers it.

    A local fake and not an import: core knows no component, and a scenario table that
    depended on the service package to state its plan shape would be asserting about wiring
    rather than about the contract."""

    name = "people_around"
    description = "The people around a subject: who works on it, who is named beside it."
    args_schema = SubjectArgs
    cap = 24

    def __init__(self, result: PathResult) -> None:
        self._result = result
        self.seen: list[dict] = []

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        self.seen.append(args.model_dump())
        return self._result


def people_plan(subject: str) -> PlanEntry:
    return PlanEntry(kind="people_around", args=[PlanArg(name="subject", value=subject)])


def semantic(query: str) -> PlanEntry:
    return PlanEntry(kind="semantic", query=query)


# ───────────────────────────────────────────────────────────────── the scenario shape


@dataclass(frozen=True)
class Scenario:
    """One conversation, end to end, plus what must be true when the tick lands.

    `expected` is the OUTCOME CLASS and nothing finer: `skip:<reason>`, `deliver`, or
    `silent:<reason>` (the tick ran a real retrieval and delivered nothing). It is the thing
    a row is really about — a scenario that asserted a lede's wording would be re-testing the
    scripted string it supplied."""

    #: What live conversation this is the synthetic twin of. Read as the row's title.
    twin_of: str
    turns: tuple[ConversationTurn, ...]
    expected: str
    density: ContextDensity = "balanced"
    context_turns: tuple[ConversationTurn, ...] = ()
    #: The scripted discover emission. `None` scripts a model that returns nothing at all.
    discover: DiscoverResult | None = None
    pick: PickResult | None = None
    paths: tuple[Any, ...] = ()
    #: A tuple is one return for every query; a DICT keyed by query is the fan-out shape.
    claims: tuple[ClaimStub, ...] | dict[str, list[ClaimStub]] = ()
    #: The canonical tree this tick was handed. `None` — the default — is "this scenario does
    #: not model canonical at all", which is what the lane's own `documents=None` means; an
    #: empty TUPLE says "the library has no page" instead. Neither pins anything in these
    #: rows: they model libraries with no archive, and the stale-path pin does not run until
    #: something has been archived (core `recall/archive_filter._pin`).
    documents: tuple[CanonicalDocument, ...] | None = None
    already_shown: tuple[dict, ...] = ()
    ledger: SubjectLedger | None = None
    web_search: Any = None
    #: Extra assertions, given the whole tick: `(result, discover_model, pick_model)`.
    check: Callable[..., None] | None = None


async def play(scenario: Scenario):
    """The one driver. Every row runs through here, so a row is a row and not a test."""
    kwargs: dict[str, Any] = {}
    if scenario.web_search is not None:
        kwargs["web_search"] = scenario.web_search
    result, discover_model, pick_model, lexical, _, _ = await run_lane(
        discover=scenario.discover,
        pick=scenario.pick,
        turns=list(scenario.turns),
        density=scenario.density,
        context_turns=list(scenario.context_turns),
        paths=list(scenario.paths),
        claims=(
            dict(scenario.claims)
            if isinstance(scenario.claims, dict)
            else list(scenario.claims)
        ),
        documents=(
            list(scenario.documents) if scenario.documents is not None else None
        ),
        already_shown=list(scenario.already_shown),
        ledger=scenario.ledger,
        **kwargs,
    )

    kind, _, detail = scenario.expected.partition(":")
    if kind == "deliver":
        assert result.skipped == "", f"{scenario.twin_of}: {result.skipped}"
        assert len(result.suggestions) == 1, scenario.twin_of
    else:
        assert result.suggestions == (), scenario.twin_of
        assert result.skipped == detail, (scenario.twin_of, result.skipped)
    if kind == "skip":
        # A skip is decided BEFORE any index is touched — that is the whole reason the
        # discover call exists, and the row would pass without it if the check were only on
        # the reason string.
        assert lexical.queries == [], f"{scenario.twin_of}: a skip paid for retrieval"
        assert pick_model.calls == [], f"{scenario.twin_of}: a skip reached the pick stage"

    # A tick that delivered a provisional card ALWAYS names which of the three endings it
    # reached. The transport's settling frame is keyed on that ending, so an unnamed one is
    # a badge left reading 「细节补充中…」 after the tick behind it has finished. Asserted in
    # the DRIVER rather than in a row, so it holds for every row written after this one.
    if result.glance_state == GLANCE_HIT:
        assert result.glance_outcome in (GLANCE_UPGRADED, GLANCE_SETTLED, GLANCE_ALONE), (
            scenario.twin_of,
            result.glance_outcome,
        )

    if scenario.check is not None:
        scenario.check(result, discover_model, pick_model)
    return result, discover_model, pick_model


# ══════════════════════════════════════════════════════════════════════ the rows
#
# 1. Small talk. The lane's steady state and the reason discover is cheap.

SMALL_TALK = Scenario(
    twin_of="lunch talk in the middle of a working session",
    turns=(owner("中午吃什么？"), other("楼下那家还行吧。")),
    discover=DiscoverResult(skip=True, reason="small_talk"),
    expected="skip:small_talk",
)


# 2. The same subject, a second time. The room already knows the answer, so there is no
#    question left worth asking — and the ledger says so before the model is even asked to
#    judge it.

def _mined_reaches_the_stage(result, discover_model, pick_model) -> None:
    assert "Lumen Lab" in discover_model.human, "the mined card rides the discover turn"
    assert prompt("recall.live.section.mined_header", count=1) in discover_model.human


ALREADY_MINED = Scenario(
    twin_of="a project named again two minutes after its card went out",
    turns=(other("Lumen Lab 那边的进度怎么样了？"),),
    already_shown=(
        {"kind": "concept", "title": "Lumen Lab", "body": "Lumen Lab builds optical benches."},
    ),
    discover=DiscoverResult(skip=True, reason="already_mined"),
    expected="skip:already_mined",
    check=_mined_reaches_the_stage,
)


# 3. The context-loss twin. Four turns established the domain, a quiet tick consumed them,
#    and the fifth turn arrived alone — live, that produced an intent about the wrong
#    domain entirely. Two assertions, and they are about different failures: the tail must
#    REACH the prompt (a window that cannot support the right answer), and a discover that
#    names the domain must be carried through (the plumbing).

BENCH_TALK = (
    other("Apex Bench 上周发了新的评测集。"),
    owner("我看了，跑分方式换了。"),
    other("对，光学台那套基准也受影响。"),
    owner("我们自己的台子要不要跟着改？"),
)
FIFTH_TURN = owner("也可以看看其他团队有没有这方面的专家。")


def _the_tail_carries_the_domain(result, discover_model, pick_model) -> None:
    human = discover_model.human
    head = human.index(prompt("recall.live.section.context_header", turns=4))
    fold = human.index(prompt("recall.live.section.pending_header", turns=1))
    assert head < fold, "understanding above, new content below"
    for turn in BENCH_TALK:
        assert turn.text in human[head:fold], turn.text
    assert FIFTH_TURN.text in human[fold:]
    # The domain the fifth turn cannot state on its own is legible from where the stage is
    # allowed to read it, and nowhere else.
    assert "Apex Bench" in human[head:fold]
    assert "Apex Bench" not in human[fold:]
    # …and the intent that names it survives the trip.
    assert "Apex Bench" in result.intent


CONTEXT_LOSS = Scenario(
    twin_of="four turns about one product, then a fifth turn that names none",
    turns=(FIFTH_TURN,),
    context_turns=BENCH_TALK,
    discover=DiscoverResult(
        intent="谁在 Apex Bench 这类评测基准上有经验？",
        plan=[people_plan("Apex Bench"), semantic("做过评测基准或光学台校准的人")],
        worth=8,
    ),
    pick=PickResult(choice=1, lede="Mei Lin 做过这套基准的校准。", citations=[1], confidence=8),
    paths=(PeopleAroundPath(MEI_LIN),),
    expected="deliver",
    check=_the_tail_carries_the_domain,
)


# 4. An unnamed role. The turn hands work to a person nobody names — "who is that?" is the
#    question — and the same turn is a lookup under `eager` and a skip under `quiet`,
#    because the density's only remaining job is HOW LATENT the question may be.

ROLE_TURN = owner("建议这个事情还是交给我们 Lumen Lab 那边的负责人来做吧。")


def _the_plan_is_person_shaped(result, discover_model, pick_model) -> None:
    assert prompt("recall.live.discover.mining.eager") in discover_model.system
    assert result.plan and result.plan[0].startswith("people_around")
    assert result.density == "eager"


UNNAMED_ROLE_EAGER = Scenario(
    twin_of="work handed to a role nobody names, on the eager posture",
    turns=(ROLE_TURN,),
    density="eager",
    discover=DiscoverResult(
        intent="Lumen Lab 那边现在是谁在负责？",
        plan=[people_plan("Lumen Lab")],
        worth=7,
    ),
    pick=PickResult(choice=1, lede="Ke Zhou 在管 Lumen Lab 这一摊。", citations=[1], confidence=7),
    paths=(PeopleAroundPath(PathResult(claims=(claim("k1", "people/ke-zhou.md", "Ke Zhou runs Lumen Lab."),))),),
    expected="deliver",
    check=_the_plan_is_person_shaped,
)

def _the_quiet_clause_reached_the_model(result, discover_model, pick_model) -> None:
    assert prompt("recall.live.discover.mining.quiet") in discover_model.system
    assert result.density == "quiet", "the record says which posture produced this skip"


UNNAMED_ROLE_QUIET = Scenario(
    twin_of="the same turn on the quiet posture — nobody actually asked",
    turns=(ROLE_TURN,),
    density="quiet",
    discover=DiscoverResult(skip=True, reason="nothing_new"),
    expected="skip:nothing_new",
    check=_the_quiet_clause_reached_the_model,
)


# 5. A business noun on its first mention: "what is that?" is worth asking exactly once. The
#    second mention is the same question with a known answer.

FIRST_MENTION = Scenario(
    twin_of="an internal programme named for the first time in a meeting",
    turns=(other("这块我们打算走 Lumen Lab 那条路。"),),
    density="eager",
    discover=DiscoverResult(
        intent="Lumen Lab 是什么？",
        plan=[semantic("Lumen Lab 是什么，做什么的")],
        worth=6,
    ),
    pick=PickResult(choice=1, lede="Lumen Lab 是做光学台的。", citations=[1], confidence=7),
    claims=(
        ClaimStub(
            anchor="c1",
            document_path="projects/lumenlab.md",
            text="Lumen Lab builds optical benches.",
            citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
        ),
    ),
    expected="deliver",
)

SECOND_MENTION = Scenario(
    twin_of="the same programme named again after its card went out",
    turns=(other("那还是按 Lumen Lab 那条路走吧。"),),
    density="eager",
    already_shown=(
        {"kind": "concept", "title": "Lumen Lab", "body": "Lumen Lab builds optical benches."},
    ),
    discover=DiscoverResult(skip=True, reason="already_mined"),
    expected="skip:already_mined",
)


# 6. Find a person for X. The question is "who here knows X best" — so the plan is the
#    people AROUND X plus a people-shaped similarity query, and never a definition of X.

def _people_reach_the_pick_stage(result, discover_model, pick_model) -> None:
    # The plan the contract steers toward, as the pipeline actually ran it.
    assert result.plan[0].startswith("people_around"), result.plan
    assert any(entry.startswith("semantic") for entry in result.plan), result.plan
    # The people results, rendered as candidates and shown to the pick stage.
    human = str(pick_model.calls[0][1].content)
    assert "Mei Lin" in human
    assert "people/mei-lin.md" in human
    assert prompt("recall.live.section.intent", intent=result.intent) in human


FIND_A_PERSON = Scenario(
    twin_of="looking for a colleague to present a public tool",
    turns=(owner("我想找个团队里的同事来分享一下 Apex Bench。"),),
    discover=DiscoverResult(
        intent="团队里谁最懂 Apex Bench 这类评测工具？",
        plan=[people_plan("Apex Bench"), semantic("做过 Apex Bench 或同类评测工作的人")],
        worth=8,
    ),
    pick=PickResult(
        choice=1,
        lede="Mei Lin 做过光学台校准，是库里离这件事最近的经验（这是推断，不是记录）。",
        citations=[1],
        confidence=7,
    ),
    paths=(PeopleAroundPath(MEI_LIN),),
    expected="deliver",
    check=_people_reach_the_pick_stage,
)


# 7. A web answer that is the search engine saying it could not find out. It is fluent,
#    on-topic and cited — and it answers nothing, so the pick chooses 0 and the tick is
#    silent. `no_coverage`, not `low_confidence`: the two look identical from outside and
#    mean opposite things about whether the lane is working.

def _the_criterion_is_in_the_prompt(result, discover_model, pick_model) -> None:
    system = str(pick_model.calls[0][0].content)
    assert "**One criterion: does that candidate's OWN TEXT answer the question?**" in system
    assert "**Text that cannot answer, answers nothing.**" in system
    assert "Choose 0 over it." in system
    # And the non-answer really was in the pool it chose 0 out of.
    assert any(c.provenance == "web" for c in result.candidates), result.candidates


NEGATIVE_WEB_ANSWER = Scenario(
    twin_of="a web search that came back saying it could not find out",
    turns=(owner("有没有人做过 Apex Bench？"),),
    discover=DiscoverResult(
        intent="团队里谁做过 Apex Bench？",
        plan=[PlanEntry(kind="web", query="Apex Bench")],
        worth=8,
    ),
    pick=PickResult(choice=0, confidence=9),
    web_search=FakeWebSearch(NO_ANSWER_FROM_THE_WEB),
    expected="silent:" + SKIP_NO_COVERAGE,
    check=_the_criterion_is_in_the_prompt,
)


# 8. The glance short-circuit on a subject the library defines. The mechanism's own tests
#    live in `test_live_pipeline.py` (delivery timing, the tie, the miss, the failing
#    transport); this row is the CONVERSATION — a plan names a defined subject and the
#    reader gets the library's own sentence before retrieval has finished, then the full
#    card takes its place.

def _the_glance_upgraded(result, discover_model, pick_model) -> None:
    assert result.glance is not None and result.glance.kind == "glance"
    assert result.glance.body == "Ke Zhou runs the Lumen Lab side of the bench programme."
    assert result.glance_state == "hit"
    assert result.glance_outcome == "upgraded"
    assert result.suggestions[0].subject == result.glance.subject


GLANCE_THEN_UPGRADE = Scenario(
    twin_of="a room naming a person the library already defines",
    turns=(other("Ke Zhou 那边怎么说？"),),
    discover=DiscoverResult(
        intent="Ke Zhou 负责的是哪一块？",
        plan=[people_plan("Ke Zhou")],
        worth=8,
    ),
    pick=PickResult(choice=1, lede="Ke Zhou 三月起接手了 Lumen Lab。", citations=[1], confidence=8),
    paths=(PeopleAroundPath(PathResult(claims=(claim("k9", "people/ke-zhou.md", "Ke Zhou took over in March."),))),),
    documents=(KE_ZHOU_PAGE, LUMEN),
    expected="deliver",
    check=_the_glance_upgraded,
)


# 9. The SAME room, and the ending the row above could not see. The glance goes out, the
#    pipeline behind it runs to completion — and comes back with nothing that answers the
#    question, so the reader is left holding the provisional card alone.
#
#    This row exists because its absence hid a live defect. Row 8 asserted `upgraded` and
#    only `upgraded`, so the table said nothing about the two OTHER endings a glancing tick
#    has — and a transport that settled the provisional card on one of the three was green.
#    What the table now states is the property the transport is built on: a tick that
#    delivered a glance always NAMES which ending it reached, and 「什么都没找到」 is one of
#    the three rather than the absence of one.

def _the_glance_stands_alone_and_says_so(result, discover_model, pick_model) -> None:
    assert result.glance is not None, "the reader is holding a card"
    assert result.suggestions == (), "…and it is the only one this tick produced"
    assert result.glance_state == "hit"
    assert result.glance_outcome == "alone", "the ending is NAMED, not left empty"


GLANCE_THEN_NOTHING = Scenario(
    twin_of="the same room, where the full pipeline answered nothing",
    turns=(other("Ke Zhou 那边怎么说？"),),
    discover=DiscoverResult(
        intent="Ke Zhou 负责的是哪一块？",
        plan=[people_plan("Ke Zhou")],
        worth=8,
    ),
    # The pick read every candidate against the intent and none of them covers it.
    pick=PickResult(choice=0, confidence=9),
    paths=(PeopleAroundPath(PathResult(claims=(claim("k9", "people/ke-zhou.md", "Ke Zhou took over in March."),))),),
    documents=(KE_ZHOU_PAGE, LUMEN),
    expected="silent:" + SKIP_NO_COVERAGE,
    check=_the_glance_stands_alone_and_says_so,
)


# 10. A room asking about TWO things in one breath. The plan the contract now asks for is one
#     `semantic` entry per thing rather than one string carrying both — measured live, the
#     crammed string starved the fused face and a library that held both answers returned
#     `no_coverage`. This row is the fan-out end to end: both queries retrieve, their returns
#     merge into ONE pool, and a page both of them found is one candidate.

SHARED_PAGE = ClaimStub(
    anchor="c-shared",
    document_path="projects/bench-programme.md",
    text="The bench programme covers both the optical bench and the evaluation set.",
    citations=[{"source_id": SRC, "block_start": 1, "block_end": 2}],
)


def _both_queries_ran_and_the_pool_is_one(result, discover_model, pick_model) -> None:
    assert result.plan == (
        "semantic(Lumen Lab 校准流程现在卡在哪)",
        "semantic(Apex Bench 评测集要怎么换)",
    ), result.plan
    subjects = [card.subject for card in result.candidates]
    # Each query's own page reached the pick stage — neither entry was planned and dropped.
    assert "projects/lumenlab.md" in subjects, subjects
    assert "projects/apex-bench.md" in subjects, subjects
    # …and the page both queries found is in the pool once, not twice.
    assert subjects.count("projects/bench-programme.md") == 1, subjects


TWO_THINGS_AT_ONCE = Scenario(
    twin_of="one turn asking about two separate workstreams at once",
    turns=(owner("我们到底先修 Lumen Lab 的校准，还是先把 Apex Bench 的评测集换掉？"),),
    discover=DiscoverResult(
        intent="Lumen Lab 的校准和 Apex Bench 的评测集，各自现在卡在哪？",
        plan=[
            semantic("Lumen Lab 校准流程现在卡在哪"),
            semantic("Apex Bench 评测集要怎么换"),
        ],
        worth=8,
    ),
    claims={
        "Lumen Lab 校准流程现在卡在哪": [
            SHARED_PAGE,
            ClaimStub(
                anchor="c-lumen",
                document_path="projects/lumenlab.md",
                text="The calibration pass is waiting on a new reference mirror.",
                citations=[{"source_id": SRC, "block_start": 3, "block_end": 4}],
            ),
        ],
        "Apex Bench 评测集要怎么换": [
            SHARED_PAGE,
            ClaimStub(
                anchor="c-apex",
                document_path="projects/apex-bench.md",
                text="The evaluation set is scheduled to be replaced after the next release.",
                citations=[{"source_id": SRC, "block_start": 5, "block_end": 6}],
            ),
        ],
    },
    pick=PickResult(
        choice=1,
        lede="校准这边在等一块新的参考镜。",
        citations=[1],
        confidence=8,
    ),
    expected="deliver",
    check=_both_queries_ran_and_the_pool_is_one,
)


# 11. The incident this table exists to hold: the room is talking about ONE product, and
#     what retrieval surfaces is a claim living in ANOTHER product's frozen rollover volume.
#     Live, the candidate reached the pick stage titled `a02` — a filename — and the model,
#     with no way to see whose history it was reading, wrote a lede that put the room's
#     product where the evidence's belonged. The evidence was real; the subject was invented.
#
#     What the row asserts is the MECHANISM, not the model's good behaviour: the parent's
#     identity is on the card before any model sees it. Then, with a pick scripted to choose
#     that card anyway, the delivered card is named after the document the volume is history
#     of — so even the worst choice available cannot be delivered under a name that names
#     nothing.

WRONG_SUBJECT_TURN = owner("我现在的一个习惯，是在 Apex Bench 里直接侧拉叫那个小助手。")

CLOSED_VOLUME_ASSISTANT = ClaimStub(
    anchor="c-a02",
    document_path="projects/lumenlab/a02.md",
    text="The bench console opens a side panel for simple lookups.",
    citations=[{"source_id": SRC, "block_start": 8, "block_end": 9}],
)


def _the_parent_identity_is_on_the_card_before_the_model_sees_it(
    result, discover_model, pick_model
) -> None:
    human = str(pick_model.calls[0][1].content)
    # The title names the active document, with the volume noted…
    assert "## 1 · [fact] Lumen Lab (vol. a02)" in human
    # …and the orientation line says, in the library's own words, what that document is.
    assert (
        "about: projects/lumenlab/a02.md — Lumen Lab (projects/lumenlab.md) — "
        "Lumen Lab builds optical benches for the agent-memory group." in human
    )
    # The string that started the incident is not what the card is called any more.
    assert "[fact] a02" not in human
    # And a pick that chose it anyway cannot deliver it under a name that names nothing.
    (card,) = result.suggestions
    assert card.title == "Lumen Lab (vol. a02)"
    assert card.evidence.startswith("about: Lumen Lab (projects/lumenlab.md) — ")


CLOSED_VOLUME_KEEPS_ITS_SUBJECT = Scenario(
    twin_of="a habit stated about one product, answered from another product's earlier volume",
    turns=(WRONG_SUBJECT_TURN,),
    discover=DiscoverResult(
        intent="Apex Bench 里那个侧拉的小助手是怎么设计的？",
        plan=[semantic("侧拉助手是怎么设计的")],
        worth=8,
    ),
    pick=PickResult(
        choice=1,
        lede="控制台里侧拉开的那个面板，是用来做简单查询的。",
        citations=[1],
        confidence=8,
    ),
    claims=(CLOSED_VOLUME_ASSISTANT,),
    documents=(LUMEN, LUMEN_VOLUME),
    expected="deliver",
    check=_the_parent_identity_is_on_the_card_before_the_model_sees_it,
)


SCENARIOS: tuple[Scenario, ...] = (
    SMALL_TALK,
    ALREADY_MINED,
    CONTEXT_LOSS,
    UNNAMED_ROLE_EAGER,
    UNNAMED_ROLE_QUIET,
    FIRST_MENTION,
    SECOND_MENTION,
    FIND_A_PERSON,
    NEGATIVE_WEB_ANSWER,
    GLANCE_THEN_UPGRADE,
    GLANCE_THEN_NOTHING,
    TWO_THINGS_AT_ONCE,
    CLOSED_VOLUME_KEEPS_ITS_SUBJECT,
)


# ═══════════════════════════════════════════════════════════════════════ the driver


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.twin_of)
async def test_scenario(scenario: Scenario) -> None:
    await play(scenario)


def test_every_row_states_which_live_conversation_it_is_a_twin_of():
    """A row whose twin is unnamed is a test nobody can retire when the conversation is.

    It is also the discipline that keeps the owner's real material out: every row had to be
    TRANSLATED to say what it is a twin of, and a translation is where a real product name
    would have to be dropped."""
    assert len({s.twin_of for s in SCENARIOS}) == len(SCENARIOS)
    for scenario in SCENARIOS:
        assert len(scenario.twin_of.split()) >= 4, scenario.twin_of


def test_the_table_is_written_in_the_synthetic_vocabulary_and_no_other():
    """The names in this file are the repository's own synthetic ones.

    Not a hygiene denylist (that is operator-local and skips when absent) — a positive
    check: every capitalised subject a row names is one of four, and a fifth would have to
    be added here deliberately."""
    text = "".join(
        turn.text for s in SCENARIOS for turn in (*s.context_turns, *s.turns)
    ) + "".join(str(s.discover.intent if s.discover else "") for s in SCENARIOS)
    for name in ("Lumen Lab", "Apex Bench", "Mei Lin", "Ke Zhou"):
        text = text.replace(name, "")
    # What is left is Chinese connective tissue and punctuation: no Latin proper noun.
    assert not any(ch.isascii() and ch.isalpha() for ch in text), text
