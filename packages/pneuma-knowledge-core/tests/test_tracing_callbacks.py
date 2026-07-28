"""core LLM call sites propagate langchain callbacks + trace config to model.invoke.

Proves the tracing assembly line reaches every core invoke without core importing any
tracing library: a fake BaseCallbackHandler injected via `callbacks=` fires on every
chat-model start, and the `run_name` / `trace_metadata` we pass ride the langchain
config through to that callback (run_name → kwargs["name"], trace_metadata ⊆ metadata).

The models here are the same scripted / GenericFakeChatModel fakes the other core tests
use — they go through langchain's standard BaseChatModel.generate path, so callbacks are
honored with no special handling. (Confirms ScriptedChatModel needs no change to trace.)
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.compile.runner import run_compile
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.briefing import Briefing, briefing_ask
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.skill import load_builtin_skill

# Reuse the compile scenario fakes and the recall index/embedding/content stubs.
from test_runner import FakeCanonicalStore, ScriptedChatModel, _source, tc
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings
from test_deep_recall import FakeContent


class PlainAnswerModel(BaseChatModel):
    """A minimal tool-capable fake (GenericFakeChatModel has no bind_tools): answers with
    fixed text and no tool calls, so briefing_ask's loop breaks after one traced invoke."""

    answer: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "plain-answer-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        msg = AIMessage(content=self.answer)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face — do not lean on BaseChatModel's thread-pool _agenerate default.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)



class RecordingHandler(BaseCallbackHandler):
    """Records every chat-model / llm / chain start with run name + trace metadata."""

    def __init__(self) -> None:
        self.starts: list[dict] = []
        self.chain_starts: list[dict] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):  # noqa: ANN001
        self.starts.append(kwargs)

    def on_llm_start(self, serialized, prompts, **kwargs):  # noqa: ANN001
        self.starts.append(kwargs)

    def on_chain_start(self, serialized, inputs, **kwargs):  # noqa: ANN001
        self.chain_starts.append(kwargs)

    def run_names(self) -> list[str]:
        return [s.get("name") for s in self.starts]

    def chain_names(self) -> list[str]:
        return [s.get("name") for s in self.chain_starts]

    def metadatas(self) -> list[dict]:
        return [s.get("metadata") or {} for s in self.starts]


_META = {"operation": "op", "user_id": "u-it-trace", "env": "local"}


def _assert_meta_propagated(handler: RecordingHandler) -> None:
    for md in handler.metadatas():
        for k, v in _META.items():
            assert md.get(k) == v, f"metadata missing {k}={v}: {md}"


async def test_run_compile_propagates_callbacks_and_run_name():
    store = FakeCanonicalStore()
    sources = [_source("src-01", 4)]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/people/cheng-ye.md",
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    handler = RecordingHandler()
    result = await run_compile(
        user_id=UserId("u-it-trace"),
        model=model,
        store=store,
        sources=sources,
        skill=load_builtin_skill(),
        callbacks=[handler],
        trace_metadata=_META,
    )
    assert result.status == "committed"
    # Tool loop invoked the model at least once; each start carries run_name="compile".
    assert handler.starts, "no chat-model start observed — callbacks not propagated"
    assert set(handler.run_names()) == {"compile"}
    _assert_meta_propagated(handler)


def _recall_indexes():
    a = ClaimStub(
        "aaaa", "p1", "supported", citations=[{"source_id": "s1", "block_start": 0, "block_end": 0}]
    )
    return FakeClaimIndex([a]), FakeClaimIndex([])


async def test_fast_recall_propagates_run_name():
    lexical, vectors = _recall_indexes()
    handler = RecordingHandler()
    model = GenericFakeChatModel(messages=iter([AIMessage(content="程野")]))
    await fast_recall(
        UserId("u-it-trace"),
        "谁是后端负责人",
        as_of=datetime(2026, 7, 20, 12),
        claim_lexical=lexical,
        claim_vectors=vectors,
        embeddings=FakeEmbeddings(),
        model=model,
        callbacks=[handler],
        trace_metadata=_META,
    )
    assert handler.run_names() == ["recall.fast"]
    _assert_meta_propagated(handler)


async def test_deep_recall_propagates_run_name():
    lexical, vectors = _recall_indexes()
    handler = RecordingHandler()
    # Direct answer, no tool calls → the agentic loop makes exactly one traced invoke.
    model = PlainAnswerModel(answer="程野")
    await deep_recall(
        UserId("u-it-trace"),
        "谁是后端负责人",
        as_of=datetime(2026, 7, 20, 12),
        claim_lexical=lexical,
        claim_vectors=vectors,
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
        callbacks=[handler],
        trace_metadata=_META,
    )
    # Under the create_agent graph the run_name lands on the ROOT chain run; every
    # nested chat-model start still carries the trace metadata.
    assert handler.starts, "no chat-model start observed — callbacks not propagated"
    assert "recall.deep" in handler.chain_names()
    _assert_meta_propagated(handler)


async def test_briefing_ask_propagates_run_name():
    handler = RecordingHandler()
    briefing = Briefing(
        user_id=UserId("u-it-trace"),
        snapshot=SnapshotRef(ref="deadbeef"),
        system_prefix="KNOWLEDGE PACK\n",
        tool_names=("fetch_verbatim",),
    )
    model = PlainAnswerModel(answer="合同交付后三十日结清")
    await briefing_ask(
        briefing,
        "合同讲了什么",
        as_of=datetime(2026, 7, 20, 12),
        model=model,
        content=FakeContent(),
        callbacks=[handler],
        trace_metadata=_META,
    )
    assert handler.starts, "no chat-model start observed — callbacks not propagated"
    assert "briefing.ask" in handler.chain_names()
    _assert_meta_propagated(handler)
