"""fast mode — canonical-annotation-dense recall (architecture.md §7; milestone M4).

Three seals, all mechanical (§0 discipline 1), not prose pleas:

1. **Fixed answer contract.** The SystemMessage is `_SELECTOR_CONTRACT` verbatim — a
   byte-stable string (I5). It is a top-down account (identity → the two evidence forms
   → world-facts about the evidence → answer shape), not a rule list; it never carries
   a timestamp, the question, or claim content, so the provider cache is earned by
   assembly order.
2. **Annotation cap + dedup.** Claims come from a dual-path retrieval (Meili claims +
   Qdrant claim layer) fused by RRF, deduped by (document_path, anchor), then capped to
   `cap` (default 40) before rendering.
3. **Everything volatile in the Human turn, question LAST.** Evidence sections render
   first (claim 注记 → 原文摘录), then as_of + question close the message — the live
   ask sits in the attention-hot tail instead of drowning above a 40-claim wall.

`token_usage` passes through the provider's cache_read / cache_creation fields
(defaulting to 0 when absent — scripted/keyless models report 0).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..domain.canonical import Citation
from ..domain.ids import AnchorId, UserId, SourceId
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from .citation_alias import alias_sources
from .spine import CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY, spine
from .assembly import (
    Passage,
    expand_and_merge,
    order_lost_in_middle,
    render_passages,
)
from .rag import RecallHit, _rrf_scores, rag_recall, rrf_fuse

DEFAULT_CLAIM_CAP = 40
DEFAULT_WINDOW_CAP = 8


def invoke_config(
    run_name: str,
    callbacks: list | None,
    trace_metadata: dict | None,
) -> dict:
    """Assemble the langchain `config` passed to every `model.ainvoke` in core.

    core stays middleware-free (architecture.md §2): it depends only on langchain's
    callback abstraction. A langfuse handler (or any BaseCallbackHandler) is injected by
    the service via `callbacks`; `trace_metadata` rides `config["metadata"]` so a trace
    can be filtered by operation / user_id / snapshot. Both default to no-ops, so
    the keyless path (callbacks=None) is byte-for-byte the pre-tracing behavior.
    """
    return {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": run_name,
    }


# I5: byte-stable. No timestamp, no question, no claim/window content — posture only.
_SELECTOR_CONTRACT = (
    """\
# Pneuma 快速知识回答

你是 Pneuma Knowledge Compiler 的快速回答引擎。用户需要在工作流中快速得到可追溯答案，
所以先给结论，再给必要证据。用户的对话、文档、项目与实验材料被编译成两种证据形态：

- **claim 注记**——已编译的结构化个人知识，逐条带锚点（c:…）与出处。
- **原文摘录**——尚未编译为 claim 的原始内容片段，同样带出处，与 claim 注记同等可信，
  可直接作为作答依据。

"""
    + spine(CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY)
)


@dataclass(frozen=True)
class RetrievedClaim:
    """A claim surfaced by the L3 retrieval face, carrying provenance (I4)."""

    anchor: AnchorId
    document_path: str
    section_path: tuple[str, ...]
    text: str
    citations: tuple[Citation, ...]
    paths: tuple[str, ...] = field(default_factory=tuple)  # ("lexical","vector") subset
    score: float = 0.0


@dataclass(frozen=True)
class FastAnswer:
    answer: str
    used_claims: tuple[RetrievedClaim, ...]
    token_usage: dict[str, int]
    # {handle: real_source_id} for the query-local `sNN` citation handles the answer uses —
    # the business/UI side reverse-binds each `[cite: sNN]` to its real source.
    citation_handles: dict[str, str] = field(default_factory=dict)
    # L1/L2 body windows fused into the answer alongside claims (uncompiled content).
    # Merged Passages when a ContentStore is wired (expand→merge assembly); raw RecallHits
    # in the langchain-only fallback. Both expose source_id/block_start/block_end/text.
    used_windows: tuple[RecallHit | Passage, ...] = field(default_factory=tuple)


def zero_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
    }


def extract_usage(response: BaseMessage) -> dict[str, int]:
    """Pull usage + provider cache fields off a chat response (cache defaults 0)."""
    meta: Mapping = getattr(response, "usage_metadata", None) or {}
    details: Mapping = meta.get("input_token_details") or {}
    return {
        "input_tokens": int(meta.get("input_tokens", 0) or 0),
        "output_tokens": int(meta.get("output_tokens", 0) or 0),
        "total_tokens": int(meta.get("total_tokens", 0) or 0),
        "cache_read": int(details.get("cache_read", 0) or 0),
        "cache_creation": int(details.get("cache_creation", 0) or 0),
    }


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in zero_usage()}


def _claim_from_hit(hit, paths: list[str], score: float) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=AnchorId(hit.anchor),
        document_path=hit.document_path,
        section_path=tuple(hit.section_path or ()),
        text=hit.text,
        citations=tuple(
            Citation(
                source_id=SourceId(str(c["source_id"])),
                block_start=int(c["block_start"]),
                block_end=int(c["block_end"]),
            )
            for c in (hit.citations or [])
        ),
        paths=tuple(paths),
        score=score,
    )


async def retrieve_claims(
    user_id: UserId,
    query: str,
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_CLAIM_CAP,
    query_embedding: list[float] | None = None,
) -> list[RetrievedClaim]:
    """Dual-path claim retrieval fused by RRF, deduped by (document_path, anchor).

    Mirrors rag_recall's fusion but over the claim face; a claim keyed the same in both
    paths fuses into one hit carrying both path markers.

    `query_embedding` (default None = embed here, i.e. today's behavior verbatim) lets a
    caller that already holds the vector skip the round trip — see `rag_recall`."""
    lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    vector_hits = await claim_vectors.search_claims(
        user_id, query_embedding, limit=limit
    )

    info: dict[tuple, dict] = {}
    lexical_ranking: list[str] = []
    for hit in lexical_hits:
        key = (hit.document_path, hit.anchor)
        lexical_ranking.append(repr(key))
        entry = info.setdefault(key, {"hit": hit, "paths": []})
        if "lexical" not in entry["paths"]:
            entry["paths"].append("lexical")

    vector_ranking: list[str] = []
    for hit in vector_hits:
        key = (hit.document_path, hit.anchor)
        vector_ranking.append(repr(key))
        entry = info.setdefault(key, {"hit": hit, "paths": []})
        if "vector" not in entry["paths"]:
            entry["paths"].append("vector")

    fused = rrf_fuse([lexical_ranking, vector_ranking])
    scores = _rrf_scores([lexical_ranking, vector_ranking], 60)
    by_repr = {repr(k): k for k in info}

    claims: list[RetrievedClaim] = []
    for key_repr in fused:
        entry = info[by_repr[key_repr]]
        claims.append(
            _claim_from_hit(entry["hit"], entry["paths"], scores[key_repr])
        )
        if len(claims) >= limit:
            break
    return claims


def render_claims(claims: list[RetrievedClaim]) -> str:
    """Compact deterministic claim payload for the Human turn (input order preserved)."""
    lines: list[str] = []
    for c in claims:
        section = " › ".join(c.section_path) if c.section_path else ""
        head = f"[c:{c.anchor} · {c.document_path}"
        head += f" · {section}]" if section else "]"
        # Provenance as the fixed English `[cite: …]` marker (full source_id) — the model
        # cites by copying it; the app extracts it into a component, so it is never
        # translated to the answer's language.
        cites = " ".join(
            f"[cite: {cit.source_id} ¶{cit.block_start}-{cit.block_end}]"
            for cit in c.citations
        )
        line = f"{head} {c.text}"
        if cites:
            line += f"  {cites}"
        lines.append(line)
    return "\n".join(lines)


def render_windows(windows: list[RecallHit]) -> str:
    """Compact deterministic body-window payload for the Human turn (full block text).

    Windows are the recall lever over uncompiled content, so each line carries the FULL
    block text (capped by count upstream, never truncated). The provenance label uses the
    same `来源:` grammar as render_passages (I4: one addressing vocabulary everywhere)."""
    lines: list[str] = []
    for w in windows:
        # Same fixed English `[cite: …]` marker with the FULL source_id (never truncated),
        # so a window-sourced citation resolves like a claim's.
        lines.append(f"[cite: {w.source_id} ¶{w.block_start}-{w.block_end}] {w.text}")
    return "\n".join(lines)


def _render_window_section(windows: list) -> str:
    """Render the window payload: assembled Passages (labeled, context-expanded) when the
    hits carry a section_path, else the flat RecallHit rendering (langchain-only fallback)."""
    if windows and hasattr(windows[0], "section_path"):
        return render_passages(windows, header="")
    return render_windows(windows)


def recall_human(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
) -> str:
    """The volatile Human payload shared by fast and deep: 画像 → evidence → as_of → input.

    Deterministic assembly order (I5 / prompt-cache discipline), input LAST: 本人画像
    (who is asking — the System tier explains what it is) → claim section → window section
    → as_of → 本人输入, so the live ask sits in the attention-hot tail below the evidence
    wall instead of above it. Section headers reuse the contract's exact names (本人画像 /
    claim 注记 / 原文摘录) — what each IS is explained once, in the stable System tier, never
    re-explained per turn. Claims and windows live in disjoint id spaces (anchor vs
    block-span), so they are presented as two sections, never cross-fused. The 画像 is the
    reason it lives in the Human turn, not the byte-stable System (it is per-owner volatile)."""
    windows = windows or []
    sections: list[str] = []
    if profile:
        sections.append(f"# 本人画像\n{profile}")
    sections.append(
        f"# claim 注记（{len(claims)} 条）\n"
        f"{render_claims(claims) or '（本次检索无命中）'}"
    )
    if windows:
        sections.append(
            f"# 原文摘录（{len(windows)} 条）\n{_render_window_section(windows)}"
        )
    return (
        "\n\n".join(sections)
        + f"\n\nas_of: {as_of.isoformat()}\n本人输入：{question}"
    )


def selector_messages(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
) -> list[BaseMessage]:
    """[SystemMessage(fixed contract), HumanMessage(画像 → evidence → as_of → input)]."""
    human = recall_human(question, claims, as_of=as_of, windows=windows, profile=profile)
    return [SystemMessage(content=_SELECTOR_CONTRACT), HumanMessage(content=human)]


async def answer_with_selector(
    model: BaseChatModel,
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "recall.fast",
) -> tuple[str, dict[str, int], dict[str, str]]:
    """One selector round: assemble → (pre-hook: alias source ids) → invoke → (answer,
    usage, handle→real_id map). The LLM only ever sees/copies short query-local `sNN`
    handles; the caller reverse-binds them (business side / UI)."""
    system, human = selector_messages(
        question, claims, as_of=as_of, windows=windows, profile=profile
    )
    aliased_human, handle_map = alias_sources(human.content)
    response = await model.ainvoke(
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config(run_name, callbacks, trace_metadata),
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    return text.strip(), extract_usage(response), handle_map


async def retrieve_windows(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_WINDOW_CAP,
) -> list[RecallHit]:
    """L1+L2 body windows for the answer's recall face (empty if raw indices absent).

    Reuses rag_recall verbatim; capped by count so uncompiled content still surfaces
    even when a source produced only abstract meta-claims."""
    if lexical is None or vectors is None or limit <= 0:
        return []
    return await rag_recall(
        user_id,
        query,
        lexical=lexical,
        vectors=vectors,
        embeddings=embeddings,
        limit=limit,
    )


async def assemble_windows(
    hits: list[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
) -> list:
    """Post-retrieval assembly over raw window hits: expand → merge/dedup → per-source cap
    → lost-in-the-middle order. With no ContentStore (langchain-only path) the raw hits are
    returned unchanged so no caller breaks."""
    if content is None or not hits:
        return list(hits)
    passages = await expand_and_merge(hits, content=content, user_id=user_id)
    return order_lost_in_middle(passages)


async def fast_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    profile: str | None = None,
    cap: int = DEFAULT_CLAIM_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> FastAnswer:
    """fast recall: L3 claims + L1/L2 body windows → fixed-contract selector.

    Two disjoint retrieval faces answer one question: claims give precision + citation
    provenance, body windows give recall over content never lifted into claims (e.g. a
    distill-treated record whose compile produced only abstract meta-claims). Each face
    is internally RRF-fused; they are presented as two sections, never cross-fused.

    When a ContentStore is wired the raw window hits go through the post-retrieval assembly
    pipeline (expand → merge/dedup → per-source cap → lost-in-the-middle order), so a bare
    hit carries its surrounding context; without one the raw hits render as before.

    The two retrieval faces are independent network work (each embeds the query + hits
    Meili/Qdrant), so they run concurrently on the event loop via `asyncio.gather` — the
    wall-clock is the slower face, not their sum, and the double query-embed overlaps
    instead of stacking. `gather` returns results in argument order, so `claims` and
    `raw_windows` bind exactly as they did under the previous thread-pool fan-out."""
    claims_raw, raw_windows = await asyncio.gather(
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
    claims = claims_raw[:cap]
    windows = await assemble_windows(
        raw_windows, content=content, user_id=user_id
    )
    answer, usage, citation_handles = await answer_with_selector(
        model,
        question,
        claims,
        as_of=as_of,
        windows=windows,
        profile=profile,
        callbacks=callbacks,
        trace_metadata=trace_metadata,
        run_name="recall.fast",
    )
    return FastAnswer(
        answer=answer,
        used_claims=tuple(claims),
        token_usage=usage,
        used_windows=tuple(windows),
        citation_handles=citation_handles,
    )
