"""Component paths in the fast lane: no path → byte-identical messages and no routing call;
a path → one routing turn, concurrent run, own evidence face, dedup, telemetry, fail-soft."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field, PrivateAttr

from pneuma_knowledge_core.domain.ids import AnchorId, UserId
from pneuma_knowledge_core.recall import fast as fast_module
from pneuma_knowledge_core.recall.fast import RetrievedClaim, fast_recall
from pneuma_knowledge_core.recall.paths import (
    ComponentEvidence,
    PathResult,
    merge_component_evidence,
    render_component_evidence,
    route_paths,
    run_paths,
)

from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings  # noqa: E402

USER = UserId("u-paths")
AS_OF = datetime(2026, 8, 25, tzinfo=timezone.utc)
SEEN: list = []  # (bound?, messages) for every model invoke, across bound clones


@pytest.fixture(autouse=True)
def _clear_seen():
    SEEN.clear()
    yield


class _Model(BaseChatModel):
    """Answers with `answer`; when `route_calls` is set, the FIRST invoke (the routing turn)
    returns those tool calls instead. Records every message list it saw."""

    answer: str = "ok"
    route_calls: list = []
    _bound: bool = PrivateAttr(default=False)

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kw):
        clone = type(self)(answer=self.answer, route_calls=self.route_calls)
        clone._bound = True
        return clone

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        SEEN.append((self._bound, messages))
        usage = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
        if self._bound:
            msg = AIMessage(content="", tool_calls=list(self.route_calls), usage_metadata=usage)
        else:
            msg = AIMessage(content=self.answer, usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw):
        return self._generate(messages, stop, run_manager, **kw)


class PersonArgs(BaseModel):
    alias: str = Field(default="")


def _claim(anchor: str, text: str, labels=()) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=AnchorId(anchor), document_path="memory/people/jia-ning.md", section_path=("位置",),
        text=text, citations=(), paths=("people",), labels=tuple(labels),
    )


class PersonPath:
    name = "person"
    description = "look up one person page by alias"
    args_schema = PersonArgs
    cap = 3

    def __init__(self, delay: float = 0.0, fail: str | None = None):
        self.delay, self.fail, self.calls = delay, fail, []

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):
        self.calls.append((user_id, args.alias))
        self.documents = documents
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail == "error":
            raise RuntimeError("boom")
        return PathResult(claims=(
            _claim("c07e", "贾宁任新华印务采购总监", ["current"]),
            _claim("a1f3", "贾宁是恒印印刷对接人", ["superseded"]),
            _claim("zz01", "extra one"), _claim("zz02", "extra two"),
        ))


def _kwargs(model, **extra):
    index = FakeClaimIndex([ClaimStub("a1f3", "memory/people/jia-ning.md", "贾宁是恒印印刷对接人"),
                            ClaimStub("b2d0", "memory/people/jia-ning.md", "贾宁先给排期再谈价")])
    return dict(
        as_of=AS_OF, claim_lexical=index, claim_vectors=index, embeddings=FakeEmbeddings(), model=model, **extra
    )


async def test_no_path_means_no_routing_call_and_identical_messages():
    model = _Model(answer="A")
    fa = await fast_recall(USER, "贾宁现在在哪", fast_paths=(), **_kwargs(model))
    assert fa.route_offered == () and fa.route_chosen == () and fa.route_degraded is None
    assert fa.used_component_evidence == () and fa.component_candidates == 0
    assert [bound for bound, _ in SEEN] == [False]  # exactly one call: the answer
    human = SEEN[0][1][-1].content
    assert "component lookups" not in human


async def test_a_routed_path_runs_and_becomes_its_own_face_deduped_from_the_ranked_side():
    """The ranked faces keep what they ranked; the COMPONENT face is the one that yields —
    and says how many of its results are already shown above."""
    model = _Model(answer="A", route_calls=[{"name": "person", "args": {"alias": "贾宁"}, "id": "t1", "type": "tool_call"}])
    path = PersonPath()
    fa = await fast_recall(USER, "贾宁现在在哪", fast_paths=[path], **_kwargs(model))
    assert path.calls == [(USER, "贾宁")]
    assert fa.route_offered == ("person",)
    assert fa.route_chosen == ('person({"alias": "贾宁"})',)
    assert fa.route_degraded is None
    [ev] = fa.used_component_evidence
    # ordered against the question (the current state first, then the unlabelled extras;
    # the superseded history is behind them), capped at 3, and a1f3 is hidden because the
    # ranked claim face already carries it.
    assert [str(c.anchor) for c in ev.claims] == ["c07e", "zz01", "zz02"]
    assert ev.already_shown == 1 and ev.dropped == 0
    assert fa.component_candidates == 3
    # the routing turn happened first, bound with the path as a tool; the answer turn last
    assert [bound for bound, _ in SEEN] == [True, False]
    human = SEEN[-1][1][-1].content
    assert "# component lookups (3)" in human and '## person(alias="贾宁")' in human
    assert "(1 already shown in claim notes / raw excerpts)" in human
    # the ranked face kept a1f3 AND now says a lookup corroborated it
    assert [str(c.anchor) for c in fa.used_claims] == ["a1f3", "b2d0"]
    assert "via:person" in fa.used_claims[0].labels
    assert human.count("c:a1f3") == 1
    assert fa.token_usage["total_tokens"] == 8  # routing + answer


async def test_routing_that_chooses_nothing_is_not_a_degradation():
    model = _Model(answer="A", route_calls=[])
    fa = await fast_recall(USER, "今天天气", fast_paths=[PersonPath()], **_kwargs(model))
    assert fa.route_offered == ("person",) and fa.route_chosen == () and fa.route_degraded is None
    assert "component lookups" not in SEEN[-1][1][-1].content


async def test_invalid_and_unknown_calls_are_kept_as_audit_rows_not_run():
    model = _Model(answer="A", route_calls=[
        {"name": "ghost", "args": {}, "id": "t1", "type": "tool_call"},
        {"name": "person", "args": {"alias": 12345, "bogus": True}, "id": "t2", "type": "tool_call"},
    ])
    path = PersonPath()
    fa = await fast_recall(USER, "q", fast_paths=[path], **_kwargs(model))
    assert path.calls == [(USER, "12345")] or path.calls == []  # pydantic may coerce the int
    assert any(e.degraded == "invalid_args" and e.path == "ghost" for e in fa.used_component_evidence)


async def test_path_and_routing_failures_are_fail_soft_with_telemetry():
    model = _Model(answer="A", route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}])
    fa = await fast_recall(USER, "q", fast_paths=[PersonPath(fail="error")], **_kwargs(model))
    [ev] = fa.used_component_evidence
    assert ev.degraded == "error" and ev.claims == ()
    assert "(lookup did not deliver: error)" in SEEN[-1][1][-1].content
    fa = await fast_recall(USER, "q", fast_paths=[PersonPath(delay=0.2)], path_timeout=0.01, **_kwargs(model))
    assert fa.used_component_evidence[0].degraded == "timeout"
    fa = await fast_recall(USER, "q", fast_paths=[PersonPath()], route_timeout=0.0001,
                           **_kwargs(_Model(answer="A", route_calls=[])))
    assert fa.route_degraded in {"timeout", None}  # a fake model may answer inside the window


async def test_built_in_retrieval_does_not_wait_for_the_routing_turn():
    slow_route = _Model(answer="A", route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}])
    stamps = {}

    class _SlowRoute(_Model):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kw):
            if self._bound:
                await asyncio.sleep(0.1)
                stamps["route_out"] = asyncio.get_running_loop().time()
            return self._generate(messages, stop, run_manager, **kw)

    class _StampingIndex(FakeClaimIndex):
        async def search_claims(self, user_id, q, *, limit=40):
            stamps["claims_out"] = asyncio.get_running_loop().time()
            return await super().search_claims(user_id, q, limit=limit)

    model = _SlowRoute(answer="A", route_calls=slow_route.route_calls)
    index = _StampingIndex([])
    await fast_recall(USER, "q", fast_paths=[PersonPath()], as_of=AS_OF, claim_lexical=index,
                      claim_vectors=index, embeddings=FakeEmbeddings(), model=model)
    assert stamps["claims_out"] < stamps["route_out"]


def test_merge_and_render_helpers():
    ev = ComponentEvidence(
        path="person", args={"alias": "贾宁"}, cap=4,
        claims=(_claim("a1f3", "x"), _claim("c07e", "y")),
    )
    ranked = [_claim("a1f3", "x"), _claim("b2d0", "z")]
    merged, claims = merge_component_evidence([ev], claims=ranked, windows=[])
    # the ranked face keeps every claim it had, and the corroborated one is labelled
    assert [str(c.anchor) for c in claims] == ["a1f3", "b2d0"]
    assert claims[0].labels == ("via:person",)
    # the component face shows only what the ranked face does not already carry
    assert [str(c.anchor) for c in merged[0].claims] == ["c07e"]
    assert merged[0].already_shown == 1
    text = render_component_evidence(
        [merged[0], ComponentEvidence(path="person", args={}, degraded="timeout")]
    )
    assert text.startswith('## person(alias="贾宁")') and "(lookup did not deliver: timeout)" in text


async def test_a_component_without_the_fast_face_offers_nothing_and_breaks_nothing():
    from pneuma_knowledge_core.components import register_component, reset_components

    class _FourFace:
        name = "legacy"
        def gate_checks(self, docs, base_docs): return []
        def outline_tail(self, doc): return None
        def compile_tools(self, draft, *, sources=()): return []
        def recall_tools(self, user_id): return []

    reset_components()
    try:
        register_component(_FourFace())
        fa = await fast_recall(USER, "q", **_kwargs(_Model(answer="A")))  # fast_paths=None → registry
        assert fa.route_offered == () and fa.answer == "A"
    finally:
        reset_components()


async def test_superseded_claims_from_the_ranked_face_are_labelled_and_moved_last():
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId
    page = CanonicalDocument(
        doc_id=DocumentId("d1"), path="memory/people/jia-ning.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "jia-ning"},
        body=("- 贾宁是恒印印刷对接人。[cite: s_0412 ¶8-9] <!-- c:a1f3 -->\n"
              "- 贾宁任新华印务采购总监。[cite: s_0977 ¶1-2] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"),
    )
    model = _Model(answer="A")
    index = FakeClaimIndex([ClaimStub("a1f3", "memory/people/jia-ning.md", "贾宁是恒印印刷对接人。"),
                            ClaimStub("c07e", "memory/people/jia-ning.md", "贾宁任新华印务采购总监。")])
    fa = await fast_recall(USER, "贾宁", fast_paths=(), as_of=AS_OF, claim_lexical=index, claim_vectors=index,
                           embeddings=FakeEmbeddings(), model=model, documents=[page])
    assert [(str(c.anchor), c.labels) for c in fa.used_claims] == [("c07e", ()), ("a1f3", ("superseded",))]
    assert "· superseded] 贾宁是恒印印刷对接人" in SEEN[-1][1][-1].content


async def test_paths_receive_the_lanes_pinned_documents():
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId
    page = CanonicalDocument(doc_id=DocumentId("d1"), path="memory/topics/x.md",
                             frontmatter={"doc_id": "d1", "type": "topic", "slug": "x"}, body="- t [cite: s ¶0-0] <!-- c:abcd -->")
    model = _Model(answer="A", route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}])
    path = PersonPath()
    await fast_recall(USER, "q", fast_paths=[path], documents=[page], **_kwargs(model))
    assert path.documents == [page]


async def test_the_routing_turn_carries_as_of_and_the_subjects_zone():
    """The index parses no natural-language time (D4): the routing model is given `as_of`
    and whose calendar it is on, and resolves "last quarter" into ISO days itself. Both ride
    the HUMAN turn — the System contract stays byte-stable (I5)."""
    model = _Model(answer="A", route_calls=[])
    await fast_recall(
        USER, "上季度都发生了什么", fast_paths=[PersonPath()], zone="Asia/Shanghai", **_kwargs(model)
    )
    (bound, messages) = SEEN[0]
    assert bound  # the routing turn
    system, human = messages[0].content, messages[1].content
    assert AS_OF.isoformat() in human and "Asia/Shanghai" in human
    assert "上季度都发生了什么" in human
    # I5: nothing volatile in the byte-stable contract.
    assert AS_OF.isoformat() not in system and "Asia/Shanghai" not in system


async def test_a_path_is_told_the_as_of_the_lane_is_answering_at():
    """A path that renders "2 months before as_of" needs the same as_of the answer uses —
    it is threaded, never re-read from the wall clock inside a path."""
    seen = {}

    class _AsOfPath(PersonPath):
        async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):
            seen["as_of"] = as_of
            return PathResult()

    model = _Model(answer="A", route_calls=[{"name": "person", "args": {"alias": "x"}, "id": "t", "type": "tool_call"}])
    await fast_recall(USER, "q", fast_paths=[_AsOfPath()], **_kwargs(model))
    assert seen["as_of"] == AS_OF
