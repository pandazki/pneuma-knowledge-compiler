"""deep mode — bounded agentic search over the four-level access model (architecture.md
§3 tool face + §7; milestone M4).

deep = fast's seed retrieval + a bounded agentic loop (langchain `create_agent`, via
`recall.agentic.run_agent_loop`). The model starts warm on the SAME dual-face evidence
fast answers over (byte-identical Human assembly via `recall_human`), then works the
four-level tool face on demand:

- `search_claims(query)`   — L3: re-search the compiled claim face from a new angle
- `search_content(query)`  — L1/L2: re-search raw body windows (+ context assembly)
- `fetch_verbatim(source_id, locator)` — L0: exact raw text for a cited span

Verification is an agentic act — fetch the cited span and read it — not a fixed batch
protocol. What stays mechanical (§0 discipline 1): the tool budget (recursion_limit +
forced finalize, see `agentic.py`), the `trail` record per tool call, and the
byte-stable `_DEEP_CONTRACT` (I5) — input, as_of, and all evidence ride the
HumanMessage / ToolMessages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool

from ..domain.ids import UserId, SourceId
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from .agentic import run_agent_loop
from .spine import CITE_PRECISE, CLOSE_ANSWER_HONESTLY, spine
from .assembly import Passage
from .fast import (
    DEFAULT_CLAIM_CAP,
    DEFAULT_WINDOW_CAP,
    RetrievedClaim,
    _render_window_section,
    assemble_windows,
    recall_human,
    render_claims,
    retrieve_claims,
    retrieve_windows,
)
from .rag import RecallHit

_DEEP_TOOL_BUDGET = 6  # tool rounds before the forced tool-less finalize
_SEARCH_CLAIM_CAP = 8
_SEARCH_WINDOW_CAP = 4
_TRAIL_PREVIEW_CHARS = 1500  # per-step result kept for the UI trail (full text still goes to the model)


class _NotifyingTrail(list):
    """A trail list that invokes a callback on every append — so a caller can stream each
    agentic step the moment a tool records it, without changing the tools."""

    def __init__(self, on_append: "Callable[[dict], None] | None" = None) -> None:
        super().__init__()
        self._on_append = on_append

    def append(self, item: dict) -> None:  # noqa: D102
        super().append(item)
        if self._on_append is not None:
            self._on_append(item)


def _trail_preview(text: str) -> str:
    """Cap a tool's result text for the UI trail so the response payload stays bounded;
    the model still receives the full return value."""
    if len(text) <= _TRAIL_PREVIEW_CHARS:
        return text
    return text[:_TRAIL_PREVIEW_CHARS].rstrip() + "\n…（略）"

# I5: byte-stable. No timestamp, no input, no evidence content — posture only.
_DEEP_CONTRACT = (
    """\
# Pneuma 深度知识核验

你是 Pneuma Knowledge Compiler 的深度核验代理。用户的对话、文档、项目与实验材料
按四级访问面组织，你可以使用：

- 随输入附上的**初检证据**：claim 注记（已编译的结构化个人知识，带锚点与出处）与
  原文摘录（未编译的原始内容片段，带出处）——一轮宽召回的结果。
- `search_claims(query)`：换关键词、换角度再检 claim 注记。
- `search_content(query)`：再检原文片段（带上下文与出处），覆盖从未编译成 claim 的内容。
- `fetch_verbatim(source_id, locator)`：逐字直取某来源的原文，locator 形如
  {"blocks": [start, end]} 或 {"section": [...]}——核对出处与取原件的途径。

深查的本分是不满足于初检——证据可疑、相互矛盾或不完整时换角度再检，关键结论回原文核对，
答案只建立在核对得住出处的证据上。查证有预算，每次调用都带着一个明确的待证问题。

"""
    + spine(CITE_PRECISE, CLOSE_ANSWER_HONESTLY)
)


@dataclass(frozen=True)
class DeepAnswer:
    answer: str
    # Every claim surfaced to the model (seed + search_claims), deduped by
    # (document_path, anchor) — drill-downable provenance for the UI.
    used_claims: tuple[RetrievedClaim, ...]
    token_usage: dict[str, int]
    # Every body window surfaced (seed + search_content), deduped by block span.
    used_windows: tuple[RecallHit | Passage, ...] = ()
    # The agentic search trace: one record per tool call, in execution order.
    trail: tuple[dict, ...] = ()


def _search_claims_tool(
    user_id: UserId,
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    found: list[RetrievedClaim],
    trail: list[dict],
) -> StructuredTool:
    async def search_claims(query: str) -> str:
        """换关键词/角度再检 claim 注记（结构化个人知识），返回带锚点与出处的命中。"""
        claims = await retrieve_claims(
            user_id,
            query,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            limit=_SEARCH_CLAIM_CAP,
        )
        found.extend(claims)
        out = (
            render_claims(claims)
            if claims
            else "（未命中 claim 注记；可换关键词重试，或用 search_content 检未编译的原文）"
        )
        trail.append(
            {"tool": "search_claims", "query": query, "hits": len(claims),
             "result": _trail_preview(out)}
        )
        return out

    return StructuredTool.from_function(
        coroutine=search_claims,
        description="换关键词/角度再检 claim 注记（结构化知识面）。",
    )


def _search_content_tool(
    user_id: UserId,
    *,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    content: ContentStore | None,
    found: list,
    trail: list[dict],
) -> StructuredTool:
    async def search_content(query: str) -> str:
        """检索原文片段（含上下文与出处），覆盖未编译成 claim 的原始内容。"""
        hits = await retrieve_windows(
            user_id,
            query,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            limit=_SEARCH_WINDOW_CAP,
        )
        windows = await assemble_windows(
            hits, content=content, user_id=user_id
        )
        found.extend(windows)
        out = (
            _render_window_section(windows)
            if windows
            else "（未命中原文片段；可换关键词重试，或用 search_claims 检结构化知识）"
        )
        trail.append(
            {"tool": "search_content", "query": query, "hits": len(windows),
             "result": _trail_preview(out)}
        )
        return out

    return StructuredTool.from_function(
        coroutine=search_content,
        description="检索原文片段（未编译内容面，带上下文与出处）。",
    )


def _fetch_verbatim_tool(
    user_id: UserId,
    content: ContentStore,
    trail: list[dict],
) -> StructuredTool:
    async def fetch_verbatim(source_id: str, locator: dict) -> str:
        """逐字直取某来源的原文片段。locator 形如 {"blocks": [start, end]} 或 {"section": [...]}。"""
        try:
            text = await content.fetch(user_id, SourceId(source_id), locator)
        except (KeyError, ValueError) as exc:
            trail.append(
                {"tool": "fetch_verbatim", "source_id": source_id,
                 "locator": locator, "error": str(exc)}
            )
            return (
                f"fetch_verbatim 失败：{exc}。source_id 取证据出处标注的来源 id，"
                'locator 形如 {"blocks": [start, end]} 或 {"section": [...]}'
            )
        out = text if text else "（该 locator 未取到内容）"
        trail.append(
            {"tool": "fetch_verbatim", "source_id": source_id, "locator": locator,
             "chars": len(text), "result": _trail_preview(out)}
        )
        return out

    return StructuredTool.from_function(
        coroutine=fetch_verbatim,
        description="逐字直取指定来源的原文片段（核对出处 / 取原件）。",
    )


def _merge_claims(
    seed: list[RetrievedClaim], found: list[RetrievedClaim]
) -> tuple[RetrievedClaim, ...]:
    seen: set[tuple[str, str]] = set()
    merged: list[RetrievedClaim] = []
    for c in [*seed, *found]:
        key = (c.document_path, str(c.anchor))
        if key not in seen:
            seen.add(key)
            merged.append(c)
    return tuple(merged)


def _merge_windows(seed: list, found: list) -> tuple:
    seen: set[tuple[str, int, int]] = set()
    merged: list = []
    for w in [*seed, *found]:
        key = (str(w.source_id), w.block_start, w.block_end)
        if key not in seen:
            seen.add(key)
            merged.append(w)
    return tuple(merged)


async def deep_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    content: ContentStore,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    profile: str | None = None,
    on_step: "Callable[[dict], None] | None" = None,
    cap: int = DEFAULT_CLAIM_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> DeepAnswer:
    """Seed with fast's dual-face retrieval, then run the bounded agentic loop.

    The seed Human payload is byte-identical to fast's (`recall_human`) under the deep
    contract; the loop is `run_agent_loop` (create_agent + budget + forced finalize).
    All model calls trace under run_name "recall.deep".

    Deep does NOT alias source ids to query-local `sNN` handles (unlike fast): its agentic
    loop re-retrieves across rounds, so one source would get different handles in different
    tool results within the same chained context (s01 here, s15 there) — inconsistent and
    hard to maintain across turns. Deep answers over the real ids and manages its own
    citations; the citation_alias hook is fast-lane only."""
    # Two independent retrieval faces (each embeds the query + hits Meili/Qdrant) → run
    # them concurrently on the event loop via asyncio.gather; wall-clock is the slower
    # face, not their sum. gather preserves argument order, so the two results bind the
    # same way the previous thread-pool fan-out bound them.
    seed_claims_raw, raw_windows = await asyncio.gather(
        retrieve_claims(
            user_id,
            question,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            limit=cap,
        ),
        retrieve_windows(
            user_id,
            question,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            limit=window_cap,
        ),
    )
    seed_claims = seed_claims_raw[:cap]
    seed_windows = await assemble_windows(
        raw_windows, content=content, user_id=user_id
    )

    found_claims: list[RetrievedClaim] = []
    found_windows: list = []
    # A trail that fires on_step as each tool records a step → the agentic search can be
    # streamed one step at a time (the tools stay unchanged; they just .append as before).
    trail: list[dict] = _NotifyingTrail(on_step) if on_step else []
    tools = [
        _search_claims_tool(
            user_id,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            found=found_claims,
            trail=trail,
        ),
        _search_content_tool(
            user_id,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            content=content,
            found=found_windows,
            trail=trail,
        ),
        _fetch_verbatim_tool(user_id, content, trail),
    ]

    answer, usage, _transcript = await run_agent_loop(
        model,
        tools,
        system_prompt=_DEEP_CONTRACT,
        human=recall_human(
            question, seed_claims, as_of=as_of, windows=seed_windows, profile=profile
        ),
        tool_budget=_DEEP_TOOL_BUDGET,
        run_name="recall.deep",
        callbacks=callbacks,
        trace_metadata=trace_metadata,
    )

    return DeepAnswer(
        answer=answer,
        used_claims=_merge_claims(seed_claims, found_claims),
        token_usage=usage,
        used_windows=_merge_windows(seed_windows, found_windows),
        trail=tuple(trail),
    )
