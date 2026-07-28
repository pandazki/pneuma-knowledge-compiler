"""deep recall: bounded agentic search over the four-level tool face (M4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.recall.deep import _DEEP_CONTRACT, _DEEP_TOOL_BUDGET, deep_recall
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from test_fast_recall import (
    ClaimStub,
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
    LexHit,
    VecHit,
)

_AS_OF = datetime(2026, 7, 20, 12, 0, 0)
_USER = UserId("u-deep")


class FakeContent:
    """ContentStore stub: fetch returns raw text for cited spans; get is absent-source
    (raises KeyError) so expand_and_merge falls back to the bare hit span."""

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        return f"raw text for {source_id} {locator}"

    async def get(self, user_id, source_id):  # noqa: ANN001
        raise KeyError(source_id)


class ScriptedToolModel(BaseChatModel):
    """Replays scripted assistant turns; records every prompt it was invoked with.

    A turn is an AIMessage (with or without tool_calls). bind_tools returns self, so
    the same script drives both the tool loop and the tool-less finalize."""

    turns: list[Any] = []
    seen: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-tool-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        return ChatResult(generations=[ChatGeneration(message=turn)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face. BaseChatModel's default _agenerate delegates _generate to a
        # thread pool; scripting `turns`/`seen` from another thread would make the replay
        # order an implementation detail of that pool. Replay natively on the loop instead.
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        return ChatResult(generations=[ChatGeneration(message=turn)])


def _model(*turns: AIMessage) -> ScriptedToolModel:
    return ScriptedToolModel(turns=list(turns), seen=[])


def _tool_call(name: str, args: dict, cid: str) -> dict:
    return {"name": name, "args": args, "id": cid}


async def test_direct_answer_over_seed_evidence_no_tools():
    # The seed Human payload is fast's assembly under the deep contract; a confident
    # model answers in one turn, trail stays empty.
    a = ClaimStub("aaaa", "p1", "负责人是 程野", citations=[{"source_id": "s1", "block_start": 0, "block_end": 0}])
    model = _model(AIMessage(content="程野"))

    result = await deep_recall(
        _USER,
        "谁是后端负责人",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([a]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert result.answer == "程野"
    assert [str(c.anchor) for c in result.used_claims] == ["aaaa"]
    assert result.trail == ()
    # System is the byte-stable deep contract; the live input closes the Human turn.
    system, human = model.seen[0][0], model.seen[0][1]
    assert system.content == _DEEP_CONTRACT
    assert "# claim 注记" in human.content
    assert human.content.rstrip().endswith("本人输入：谁是后端负责人")


async def test_search_content_surfaces_uncompiled_body_the_jack_regression():
    # Seed claims are irrelevant meta-claims; the agent re-searches the raw body face
    # and the searched window lands in used_windows + trail.
    body = "候选人李四：SRE 值班经验丰富。"
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("search_content", {"query": "SRE 候选人"}, "c1")]),
        AIMessage(content="李四"),
    )

    result = await deep_recall(
        _USER,
        "谁适合 SRE",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        lexical=FakeLexical([LexHit(SourceId("srcbody2"), 7, body)]),
        vectors=FakeVector([VecHit(SourceId("srcbody2"), 7, 7, body)]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert result.answer == "李四"
    assert len(result.trail) == 1
    step = result.trail[0]
    assert (step["tool"], step["query"], step["hits"]) == ("search_content", "SRE 候选人", 1)
    assert step["result"]  # each step carries its rendered result for the UI trail
    assert [(w.block_start, w.block_end) for w in result.used_windows] == [(7, 7)]
    # The tool result reached the model as a ToolMessage before it answered.
    tool_msgs = [m for m in model.seen[1] if m.type == "tool"]
    assert len(tool_msgs) == 1 and body in tool_msgs[0].content


async def test_fetch_verbatim_verifies_a_claim_agentically():
    # Verification is an agentic act: the model pulls the cited span from L0, then answers.
    a = ClaimStub("aaaa", "p1", "合同付款期三十日", citations=[{"source_id": "s1", "block_start": 5, "block_end": 6}])
    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("fetch_verbatim", {"source_id": "s1", "locator": {"blocks": [5, 6]}}, "c1")]),
        AIMessage(content="三十日 (出处 s1 ¶5-6)"),
    )

    result = await deep_recall(
        _USER,
        "合同付款期多久",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([a]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert result.answer == "三十日 (出处 s1 ¶5-6)"
    assert result.trail[0]["tool"] == "fetch_verbatim"
    assert result.trail[0]["source_id"] == "s1"
    assert "chars" in result.trail[0]
    tool_msgs = [m for m in model.seen[1] if m.type == "tool"]
    assert "raw text for s1" in tool_msgs[0].content


async def test_search_claims_merges_and_dedups_into_used_claims():
    # A re-search surfacing the seed claim again must not duplicate it; new ones append.
    a = ClaimStub("aaaa", "p1", "seed claim")
    b = ClaimStub("bbbb", "p2", "found claim")

    class SwitchingClaimIndex:
        """Seed retrieval returns [a]; the tool's re-search returns [a, b]."""

        def __init__(self) -> None:
            self.calls = 0

        async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
            self.calls += 1
            return [a] if self.calls == 1 else [a, b]

    model = _model(
        AIMessage(content="", tool_calls=[_tool_call("search_claims", {"query": "换个角度"}, "c1")]),
        AIMessage(content="答"),
    )

    result = await deep_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=SwitchingClaimIndex(),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert [str(c.anchor) for c in result.used_claims] == ["aaaa", "bbbb"]
    assert len(result.trail) == 1
    step = result.trail[0]
    assert (step["tool"], step["query"], step["hits"]) == ("search_claims", "换个角度", 2)
    assert step["result"]  # each step carries its rendered result for the UI trail


async def test_full_budget_then_answer_completes_normally():
    # Exactly _DEEP_TOOL_BUDGET tool rounds then an answer fits inside recursion_limit.
    looping = [
        AIMessage(content="", tool_calls=[_tool_call("search_claims", {"query": f"q{i}"}, f"c{i}")])
        for i in range(_DEEP_TOOL_BUDGET)
    ]
    model = _model(*looping, AIMessage(content="用满预算的答案"))

    result = await deep_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert result.answer == "用满预算的答案"
    assert len(result.trail) == _DEEP_TOOL_BUDGET
    assert model.turns == []


async def test_budget_exhaustion_forces_toolless_finalize():
    # A model that never stops calling tools trips GraphRecursionError; ONE forced
    # tool-less invoke then closes the run — the loop always terminates with an answer.
    looping = [
        AIMessage(content="", tool_calls=[_tool_call("search_claims", {"query": f"q{i}"}, f"c{i}")])
        for i in range(_DEEP_TOOL_BUDGET + 1)
    ]
    model = _model(*looping, AIMessage(content="预算收尾答案"))

    result = await deep_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
    )

    assert result.answer == "预算收尾答案"
    assert len(result.trail) == _DEEP_TOOL_BUDGET + 1  # bounded: budget + the cut round
    assert model.turns == []  # the finalize invoke really consumed the last turn
    # The finalize prompt is provider-valid: it ends on a tool RESULT (executed or
    # budget-notice), never on a dangling assistant tool call.
    finalize_input = model.seen[-1]
    assert finalize_input[-1].type == "tool"
