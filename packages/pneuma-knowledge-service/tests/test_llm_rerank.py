"""LLM reranker adapter: selection → ordinal scores, mechanical index hygiene, and the
wiring's provider selection by spec shape."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_service.adapters.llm_rerank import LLMReranker, _Selection


class _SelectionModel(BaseChatModel):
    indexes: list[Any] = []
    parsed_override: Any = "__unset__"
    seen: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "rerank-fake"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self

        class _Structured:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.seen.append(list(messages))
                parsed = (
                    _Selection(indexes=list(outer.indexes))
                    if outer.parsed_override == "__unset__"
                    else outer.parsed_override
                )
                return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None}

        return _Structured()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="x"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages)


async def test_selection_becomes_ordinal_descending_scores():
    model = _SelectionModel(indexes=[2, 0], seen=[])
    results = await LLMReranker(model).rerank("q", ["a", "b", "c"], top_n=2)
    assert [(r.index, r.score) for r in results] == [(2, 1.0), (0, 0.5)]
    human = model.seen[0][1].content
    assert "0. a" in human and "2. c" in human and "Question: q" in human


async def test_invalid_and_duplicate_indexes_are_discarded():
    model = _SelectionModel(indexes=[9, 1, 1, 0], seen=[])
    results = await LLMReranker(model).rerank("q", ["a", "b"], top_n=5)
    assert [r.index for r in results] == [1, 0]


async def test_unparsable_selection_raises_for_the_caller_to_degrade():
    model = _SelectionModel(parsed_override=None, seen=[])
    with pytest.raises(ValueError):
        await LLMReranker(model).rerank("q", ["a"], top_n=1)


async def test_empty_documents_short_circuit():
    model = _SelectionModel(indexes=[0], seen=[])
    assert await LLMReranker(model).rerank("q", [], top_n=3) == []
    assert model.seen == []  # no call was made


def test_wiring_selects_the_provider_by_spec_shape(monkeypatch):
    from pneuma_knowledge_service.adapters.openrouter_rerank import OpenRouterReranker
    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.wiring import AppContext

    def ctx_with(spec: str) -> AppContext:
        settings = Settings(
            recall_rerank_model=spec,
            llm_model="scripted:unused",
            OPENROUTER_API_KEY="k",
        )
        return AppContext(
            settings=settings, store=None, canonical=None, lexical=None,
            vectors=None, embeddings=None, registry=None,
        )

    assert ctx_with("").get_reranker() is None
    # "llm" resolves the recall role — scripted base keeps this keyless in tests.
    monkeypatch.setattr(
        "pneuma_knowledge_service.wiring.load_scripted_model",
        lambda path: _SelectionModel(seen=[]),
    )
    assert type(ctx_with("llm").get_reranker()).__name__ == "LLMReranker"
    assert isinstance(ctx_with("cohere/rerank-4-pro").get_reranker(), OpenRouterReranker)


def test_clip_is_identity_within_budget_and_splices_head_and_tail_beyond():
    from pneuma_knowledge_service.adapters.llm_rerank import _CLIP_MARKER, clip_document

    assert clip_document("short", 100) == "short"
    long = "H" * 900 + "M" * 900 + "T" * 900
    clipped = clip_document(long, 300)
    assert len(clipped) == 300
    assert _CLIP_MARKER in clipped
    assert clipped.startswith("H") and clipped.endswith("T")
