"""LLM reranker adapter (core `Reranker` port) — the default rerank provider.

A cheap chat call plays the cross-encoder's role: read the numbered candidate texts
against the query and return the indexes that bear on answering, best first. With a
non-reasoning effort pin ("reasoning": {"effort": "none"}) the call is input-heavy and
output-tiny (a few dozen index tokens), which prices it an order of magnitude below
dedicated rerank endpoints that bill per search unit. A Cohere-style `/rerank` endpoint
adapter existed briefly as an alternative provider and was retired after head-to-head
measurement on LoCoMo-refined: no score gain over this adapter or over no reranking at
all, at a per-search-unit price above the tokens it saved.

Scores are ordinal, not calibrated: the model returns an ordering, and the adapter
synthesizes descending scores from it so downstream consumers (rank-then-drop, score
stamping) work identically across providers. Anything the model does not pick is simply
unscored — `rerank_claims` backfills it in pool order, so a sparse pick never loses
recall.

Fail-fast like the endpoint adapter: transport/provider/schema failures raise, and the
caller (`rerank_claims`) degrades to the fused order under its own timeout.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from pneuma_knowledge_core.ports.reranker import RerankResult
from pneuma_knowledge_core.prompts import prompt

# Per-document length budget. The reranking model reads (query, candidates) inside a
# ~33k-token context; CJK runs ≈1 token/char, so 24k chars leaves headroom without being
# conservative. An over-long document is NOT dropped and NOT head-only truncated: it is
# spliced head + tail (answers hide at both ends of long material; the middle is the
# cheapest part to lose), with an explicit marker so the text never silently pretends to
# be complete.
_MAX_DOC_CHARS = 24_000
_CLIP_MARKER = " … [middle truncated] … "


def clip_document(text: str, max_chars: int = _MAX_DOC_CHARS) -> str:
    """Head+tail splice for an over-long document; identity for anything within budget."""
    if len(text) <= max_chars:
        return text
    keep = max_chars - len(_CLIP_MARKER)
    head = (keep * 2) // 3
    tail = keep - head
    return text[:head] + _CLIP_MARKER + text[-tail:]


class _Selection(BaseModel):
    """Structured output: indexes into the numbered candidate list, best first."""

    indexes: list[int] = Field(default_factory=list)


class LLMReranker:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]:
        if not documents:
            return []
        numbered = "\n".join(
            f"{index}. {clip_document(text)}" for index, text in enumerate(documents)
        )
        cap = min(top_n, len(documents))
        messages = [
            SystemMessage(content=prompt("recall.rerank.llm.system", cap=cap)),
            HumanMessage(
                content=prompt(
                    "recall.rerank.llm.request", candidates=numbered, query=query, cap=cap
                )
            ),
        ]
        structured = self._model.with_structured_output(_Selection, include_raw=True)
        raw = await structured.ainvoke(messages)
        parsed = raw.get("parsed") if isinstance(raw, Mapping) else raw
        if not isinstance(parsed, _Selection):
            raise ValueError("LLM reranker returned no parsable selection")

        chosen: list[int] = []
        for raw_index in parsed.indexes:
            if isinstance(raw_index, int) and 0 <= raw_index < len(documents) and raw_index not in chosen:
                chosen.append(raw_index)
            if len(chosen) >= cap:
                break
        # Ordinal scores: rank order is the model's judgement; the magnitude is synthetic
        # and only promises "earlier pick > later pick > unscored".
        total = len(chosen)
        return [
            RerankResult(index=index, score=(total - position) / total)
            for position, index in enumerate(chosen)
        ]

    async def aclose(self) -> None:  # symmetry with the endpoint adapter
        return None
