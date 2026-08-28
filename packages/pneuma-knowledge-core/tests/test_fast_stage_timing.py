"""Per-stage wall-clock for the fast lane (recall/stage_timing.py).

The lane is several model calls around one concurrent gather, so "it took 9 seconds" is not
an answer to which part. These tests pin the properties a UI and an operator can rely on:
the vocabulary is fixed and complete (a stage that did not run is still there, marked
`skipped` at 0 ms), a stage that ran reports its OWN duration, a routed component path shows
up as a child of `retrieve`, `total` bounds everything, and a degraded stage carries the
lane's existing reason rather than a second one invented here.

Durations are asserted with generous floors (a sleep of 60 ms cannot report 20 ms) and never
with ceilings — a loaded CI box is allowed to be slow, and a test that fails when it is would
be measuring the machine, not the code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from pneuma_knowledge_core.domain.ids import AnchorId, UserId
from pneuma_knowledge_core.ports.reranker import RerankResult
from pneuma_knowledge_core.recall.fast import RetrievedClaim, fast_recall
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.stage_timing import (
    RETRIEVE_CHILDREN,
    STAGE_ORDER,
    StageRecorder,
    child_name,
)

from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings  # noqa: E402

USER = UserId("u-stages")
AS_OF = datetime(2026, 8, 26, tzinfo=timezone.utc)

#: The order every result must arrive in, expanded once here so a vocabulary change has to be
#: made deliberately in two places rather than drifting in one.
EXPECTED_ORDER = (
    "plan",
    "retrieve",
    *(child_name(c) for c in RETRIEVE_CHILDREN),
    "route",
    "rerank",
    "select",
    "assemble",
    "answer",
    "total",
)


# ------------------------------------------------------------------ fakes


class _Model(BaseChatModel):
    """Answers with `answer` after `delay` seconds; a bound clone (the routing turn) returns
    `route_calls` instead, after `route_delay`."""

    answer: str = "ok"
    delay: float = 0.0
    route_calls: list = []
    route_delay: float = 0.0
    bound: bool = False

    @property
    def _llm_type(self) -> str:
        return "stage-fake"

    def bind_tools(self, tools, **kw):  # noqa: ANN001, ARG002
        return type(self)(
            answer=self.answer,
            delay=self.delay,
            route_calls=self.route_calls,
            route_delay=self.route_delay,
            bound=True,
        )

    def _generate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ARG002
        usage = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
        message = (
            AIMessage(content="", tool_calls=list(self.route_calls), usage_metadata=usage)
            if self.bound
            else AIMessage(content=self.answer, usage_metadata=usage)
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001
        await asyncio.sleep(self.route_delay if self.bound else self.delay)
        return self._generate(messages, stop, run_manager, **kw)


class _SlowClaimIndex(FakeClaimIndex):
    """The claim face, with a controllable network delay."""

    def __init__(self, claims, delay: float) -> None:
        super().__init__(claims)
        self._delay = delay

    async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
        await asyncio.sleep(self._delay)
        return await super().search_claims(user_id, query_or_embedding, limit=limit)


class _PersonArgs(BaseModel):
    alias: str = Field(default="")


class _PersonPath:
    name = "person"
    description = "look up one person page by alias"
    args_schema = _PersonArgs
    cap = 3

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay, self.fail = delay, fail

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return PathResult(
            claims=(
                RetrievedClaim(
                    anchor=AnchorId("c07e"),
                    document_path="memory/people/lin-wei.md",
                    section_path=("职务",),
                    text="林薇现任采购总监",
                    citations=(),
                ),
            )
        )


class _HangingReranker:
    """A reranker that never comes back — the lane's timeout is the whole point."""

    async def rerank(self, query, documents, *, top_n):  # noqa: ANN001, ARG002
        await asyncio.sleep(10)
        return [RerankResult(index=0, score=1.0)]


def _kwargs(model, **extra):
    index = extra.pop(
        "index",
        FakeClaimIndex(
            [
                ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责恒印印刷的对接"),
                ClaimStub("b2d0", "memory/people/lin-wei.md", "林薇先给排期再谈价"),
            ]
        ),
    )
    return dict(
        as_of=AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=model,
        **extra,
    )


def _by_name(stages) -> dict:
    return {stage.name: stage for stage in stages}


# ------------------------------------------------------------------ the recorder itself


def test_the_emitted_order_is_the_vocabulary_and_nothing_is_ever_omitted():
    """Order is a property of STAGE_ORDER, not of which branches a run happened to take."""
    recorder = StageRecorder()
    recorder.record("answer", 12.0)
    stages = recorder.emit()
    assert tuple(s.name for s in stages) == EXPECTED_ORDER
    assert all(s.ms == 0 and s.status == "skipped" for s in stages if s.name != "answer")
    assert len(STAGE_ORDER) + len(RETRIEVE_CHILDREN) == len(stages)


def test_a_repeated_stage_accumulates_but_a_repeated_path_keeps_the_longer_run():
    """Two rerank passes are sequential (they add up); two runs of one path are concurrent
    (their sum is not a duration anything took)."""
    recorder = StageRecorder()
    recorder.record("rerank", 10.0)
    recorder.record("rerank", 15.0)
    recorder.record_path("person", 40.0)
    recorder.record_path("person", 25.0)
    stages = _by_name(recorder.emit())
    assert stages["rerank"].ms == 25
    assert stages[child_name("path:person")].ms == 40


# ------------------------------------------------------------------ the lane


async def test_every_stage_is_present_in_order_and_the_ones_that_did_not_run_are_skipped():
    fa = await fast_recall(USER, "林薇现在负责什么", fast_paths=(), **_kwargs(_Model(answer="A")))
    assert tuple(s.name for s in fa.stages) == EXPECTED_ORDER
    stages = _by_name(fa.stages)
    # Nothing was wired for these, and "did not happen" is reported as such — not as 0 ms of
    # work that did happen.
    for name in ("plan", "route", "rerank", "select", child_name("windows"), child_name("glance")):
        assert stages[name].status == "skipped", name
        assert stages[name].ms == 0, name
    for name in ("retrieve", child_name("claims"), "assemble", "answer", "total"):
        assert stages[name].status == "ran", name


async def test_a_slow_lane_reports_its_own_duration_and_total_bounds_every_stage():
    slow = _SlowClaimIndex(
        [ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责恒印印刷的对接")], delay=0.06
    )
    fa = await fast_recall(
        USER,
        "林薇现在负责什么",
        fast_paths=(),
        **_kwargs(_Model(answer="A", delay=0.04), index=slow),
    )
    stages = _by_name(fa.stages)
    # The claim face awaits the delay twice (lexical, then vector), so 60 ms is a floor with
    # room to spare; the gather cannot be shorter than the arm inside it.
    assert stages[child_name("claims")].ms >= 60
    assert stages["retrieve"].ms >= stages[child_name("claims")].ms
    assert stages["answer"].ms >= 40
    assert all(stages["total"].ms >= s.ms for s in fa.stages)


async def test_a_routed_path_appears_as_a_child_of_retrieve_beside_its_routing_turn():
    model = _Model(
        answer="A",
        route_calls=[
            {"name": "person", "args": {"alias": "林薇"}, "id": "t1", "type": "tool_call"}
        ],
        route_delay=0.03,
    )
    fa = await fast_recall(
        USER, "林薇现在负责什么", fast_paths=[_PersonPath(delay=0.05)], **_kwargs(model)
    )
    names = tuple(s.name for s in fa.stages)
    # The dynamic child follows the fixed ones, still inside the `retrieve` block.
    assert names.index(child_name("path:person")) == names.index(child_name("glance")) + 1
    assert names.index(child_name("path:person")) < names.index("route")
    stages = _by_name(fa.stages)
    assert stages[child_name("path:person")].status == "ran"
    assert stages[child_name("path:person")].ms >= 50
    # The routing turn ran INSIDE the gather, so it is reported on its own and overlaps.
    assert stages["route"].status == "ran" and stages["route"].ms >= 30
    assert stages["retrieve"].ms >= stages["route"].ms


async def test_a_failed_path_is_degraded_with_the_lanes_own_reason_and_still_carries_time():
    model = _Model(
        answer="A",
        route_calls=[
            {"name": "person", "args": {"alias": "林薇"}, "id": "t1", "type": "tool_call"}
        ],
    )
    fa = await fast_recall(
        USER,
        "林薇现在负责什么",
        fast_paths=[_PersonPath(delay=0.04, fail=True)],
        **_kwargs(model),
    )
    child = _by_name(fa.stages)[child_name("path:person")]
    assert child.status == "degraded" and child.detail == "error"
    assert child.ms >= 40  # what it spent before giving up is the fact worth having


async def test_a_degraded_rerank_carries_its_reason_and_the_time_the_timeout_cost():
    fa = await fast_recall(
        USER,
        "林薇现在负责什么",
        fast_paths=(),
        reranker=_HangingReranker(),
        rerank_candidates=10,
        rerank_timeout=0.05,
        **_kwargs(_Model(answer="A")),
    )
    assert fa.rerank_degraded == "timeout"
    rerank = _by_name(fa.stages)["rerank"]
    assert rerank.status == "degraded" and rerank.detail == "timeout"
    assert rerank.ms >= 45
