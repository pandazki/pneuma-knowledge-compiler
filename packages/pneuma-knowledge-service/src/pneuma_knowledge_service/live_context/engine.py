"""The I/O half of Live Context: bind a session's `EvaluationPlan` to core and app ports.

Deliberately thin. Every decision worth testing is either in `session.py` (pure policy)
or in `pneuma_knowledge_core.recall.suggestion` (the contract and the four gates); what is left here is
port wiring, the briefing-pack lookup, and the `want_more` expansion.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.recall.briefing import _BRIEFING_CONTRACT
from pneuma_knowledge_core.recall.suggestion import DETAIL_CONTRACT, LiveContextResult, evaluate_live_context
from pneuma_knowledge_core.recall.fast import extract_usage, invoke_config, zero_usage
from langchain_core.messages import HumanMessage, SystemMessage

from ..wiring import llm_call_config
from .session import EvaluationPlan


def briefing_pack(system_prefix: str) -> str:
    """The knowledge pack alone, with the stored briefing's Q&A contract stripped off.

    `build_briefing` persists `system_prefix = _BRIEFING_CONTRACT + "\\n" + pack + "\\n"`
    (briefing.py). The Live Context engine takes `pack` as data for the HUMAN turn, and core
    will not reach into service-persisted state to unpick it, so the split happens here.

    Handing the raw `system_prefix` through would inject a second, contradictory contract
    into the middle of the suggestion Human turn: it tells the model it is a Q&A engine answering
    a owner's question, advertises `search_knowledge` / `fetch_verbatim` tools that are
    not bound on this call, and closes with the very 「无相关记录」 clause the Live Context
    contract exists to replace — the one that produces an empty card. The active System
    contract would be arguing with a stale contract quoted underneath it.

    A prefix that does NOT start with the contract (an older or hand-written briefing) is
    returned unchanged: it is all pack as far as we can tell, and guessing is worse.
    An empty pack yields `""`, never None — the difference is load-bearing in core, where
    `pack is None` means "full scope, go retrieve" and `pack == ""` means "briefing scope,
    which happens to be empty; retrieve nothing"."""
    if not system_prefix.startswith(_BRIEFING_CONTRACT):
        return system_prefix
    return system_prefix[len(_BRIEFING_CONTRACT) :].strip()


async def load_briefing_pack(ctx: Any, user: UserId, briefing_id: str) -> str:
    """The stored briefing's pack, contract stripped. Raises KeyError when unknown."""
    row = await ctx.store.get_briefing(user, briefing_id)
    if row is None:
        raise KeyError(f"briefing not found: {briefing_id}")
    return briefing_pack(row["system_prefix"])


async def run_evaluation(
    ctx: Any,
    user_id: str,
    plan: EvaluationPlan,
    *,
    label_map: dict[str, str] | None = None,
    profile: str | None = None,
    pack: str | None = None,
    as_of: datetime | None = None,
) -> LiveContextResult:
    """One Live Context evaluation over a plan's window. `pack` given ⇒ briefing scope."""
    user = UserId(user_id)
    return await evaluate_live_context(
        user,
        plan.turns,
        as_of=as_of or datetime.now(timezone.utc),
        model=ctx.get_chat_model("live_context"),
        embeddings=ctx.embeddings,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        content=ctx.store,
        focus=plan.focus,
        profile=profile,
        pack=pack,
        already_shown=plan.already_shown,
        label_map=label_map,
        turn_window=plan.turn_window,
        max_suggestions=plan.max_suggestions,
        min_confidence=plan.min_confidence,
        **llm_call_config(
            ctx,
            operation="live_context.evaluate",
            user_id=user_id,
            extra={"focus": plan.focus, "briefing_id": plan.briefing_id},
        ),
    )


# ------------------------------------------------------------------------ want_more


def _detail_human(suggestion: dict[str, Any], passages: Sequence[dict[str, Any]]) -> str:
    parts = [
        f"# 卡片\nkind: {suggestion.get('kind', '')}\n标题：{suggestion.get('title', '')}\n"
        f"正文：{suggestion.get('body', '')}\n触发片段：{suggestion.get('trigger', '')}"
    ]
    if passages:
        blocks = []
        for p in passages:
            head = f"来源 {p['source_id']} 区块 [{p['block_start']}, {p['block_end']}]"
            blocks.append(f"## {head}\n{p['text']}")
        parts.append(f"# 引用来源原文（{len(passages)} 段）\n" + "\n\n".join(blocks))
    else:
        parts.append("# 引用来源原文\n（本卡片没有可直取的引用，只能基于卡片本身展开）")
    return "\n\n".join(parts)


def _citations_of(suggestion: dict[str, Any]) -> list[Citation]:
    out: list[Citation] = []
    for raw in suggestion.get("citations") or []:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(
                Citation(
                    source_id=SourceId(str(raw["source_id"])),
                    block_start=int(raw["block_start"]),
                    block_end=int(raw["block_end"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            # A malformed citation is one fewer passage, never a failed expansion.
            continue
    return out


async def expand_suggestion(
    ctx: Any, user_id: str, suggestion: dict[str, Any]
) -> dict[str, Any]:
    """`want_more`: fetch the card's OWN citations verbatim, then one LLM round.

    Zero retrieval and zero embedding, by construction — the client hands back the whole
    card it received, and its `citations` already carry real source ids and block spans, so
    there is nothing left to search for. That also makes the operation stateless across a
    reconnect or a deploy: the server need not remember having emitted the card.

    Fetches run in citation order and a failing one is skipped, not raised: a partial
    expansion is worth more to someone mid-conversation than an error."""
    user = UserId(user_id)
    passages: list[dict[str, Any]] = []
    for cit in _citations_of(suggestion):
        try:
            text = await ctx.store.fetch(
                user,
                cit.source_id,
                {"blocks": [cit.block_start, cit.block_end]},
            )
        except (KeyError, ValueError):
            continue
        passages.append(
            {
                "source_id": str(cit.source_id),
                "block_start": cit.block_start,
                "block_end": cit.block_end,
                "text": text,
            }
        )

    model = ctx.get_chat_model("live_context")
    response = await model.ainvoke(
        [
            SystemMessage(content=DETAIL_CONTRACT),
            HumanMessage(content=_detail_human(suggestion, passages)),
        ],
        config=invoke_config(
            "live_context.expand",
            **llm_call_config(
                ctx,
                operation="live_context.expand",
                user_id=user_id,
            ),
        ),
    )
    detail = str(getattr(response, "content", "") or "").strip()
    if not detail:
        # An empty expansion is the one failure mode that must NOT be delivered. The owner
        # tapped a card and is waiting; handing back a blank one is worse than saying it
        # failed, and it contradicts the discipline the whole feature rests on — never deliver
        # an empty card. The WS handler turns this into a non-fatal `error`
        # frame, so the socket survives and the card stays as it was.
        raise ValueError("expansion came back empty")

    return {
        "title": str(suggestion.get("title", "")),
        "detail": detail,
        "citations": [
            {
                "source_id": p["source_id"],
                "block_start": p["block_start"],
                "block_end": p["block_end"],
            }
            for p in passages
        ],
        "token_usage": extract_usage(response) if response is not None else zero_usage(),
    }
