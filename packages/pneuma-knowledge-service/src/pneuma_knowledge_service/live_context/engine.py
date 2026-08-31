"""The I/O half of Live Context: bind a session's `EvaluationPlan` to core and app ports.

Deliberately thin. Every decision worth testing is either in `session.py` (pure policy) or
in core — `recall/live_pipeline.py` for the full-scope three-stage lane, `recall/suggestion.py`
for the briefing round and its four gates. What is left here is port wiring, the scope
branch, the briefing-pack lookup, and the `want_more` expansion.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.briefing import briefing_contract
from pneuma_knowledge_core.recall.live_pipeline import (
    PipelineResult,
    evaluate_live_pipeline,
)
from pneuma_knowledge_core.recall.paths import fast_paths_from_registry
from pneuma_knowledge_core.recall.suggestion import detail_contract, evaluate_live_context
from pneuma_knowledge_core.recall.fast import extract_usage, invoke_config, zero_usage
from langchain_core.messages import HumanMessage, SystemMessage

from ..wiring import llm_call_config
from .session import EvaluationPlan


def briefing_pack(system_prefix: str) -> str:
    """The knowledge pack alone, with the stored briefing's Q&A contract stripped off.

    `build_briefing` persists `system_prefix = briefing_contract() + "\\n" + pack + "\\n"`
    (briefing.py). The Live Context engine takes `pack` as data for the HUMAN turn, and core
    will not reach into service-persisted state to unpick it, so the split happens here.

    Handing the raw `system_prefix` through would inject a second, contradictory contract
    into the middle of the suggestion Human turn: it tells the model it is a Q&A engine answering
    a owner's question, advertises `search_knowledge` / `fetch_verbatim` tools that are
    not bound on this call, and closes with the very "no relevant record" clause the Live
    Context contract exists to replace — the one that produces an empty card. The active System
    contract would be arguing with a stale contract quoted underneath it.

    A prefix that does NOT start with the contract (an older or hand-written briefing) is
    returned unchanged: it is all pack as far as we can tell, and guessing is worse.
    An empty pack yields `""`, never None — the difference is load-bearing in core, where
    `pack is None` means "full scope, go retrieve" and `pack == ""` means "briefing scope,
    which happens to be empty; retrieve nothing"."""
    contract = briefing_contract()
    if not system_prefix.startswith(contract):
        return system_prefix
    return system_prefix[len(contract) :].strip()


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
    ledger: Any = None,
) -> PipelineResult:
    """One Live Context evaluation over a plan's pending window.

    Two scopes, and the branch is the whole of this function's judgement:

    * **briefing** (`pack` given) — the frozen pack IS the evidence. Nothing to plan, nothing
      to retrieve, nothing to choose between: one round, unchanged, and the result is
      adapted onto the pipeline's shape so both transports have one thing to report.
    * **full** (`pack is None`) — the three-stage lane, over whatever component paths this
      deployment enabled. `profile` is deliberately NOT passed: the discover stage reads the
      pending window and the session's own ledger, and an owner profile in front of it would
      buy a longer prompt on the one call whose whole argument is that it is short."""
    user = UserId(user_id)
    when = as_of or datetime.now(timezone.utc)
    if pack is not None:
        result = await evaluate_live_context(
            user,
            plan.turns,
            as_of=when,
            model=ctx.get_chat_model("live_context"),
            focus=plan.focus,
            profile=profile,
            pack=pack,
            already_shown=plan.already_shown,
            label_map=label_map,
            turn_window=plan.max_pending_turns,
            min_confidence=plan.min_confidence,
            **llm_call_config(
                ctx,
                operation="live_context.evaluate",
                user_id=user_id,
                extra={"focus": plan.focus, "briefing_id": plan.briefing_id},
            ),
        )
        return PipelineResult(
            suggestions=result.suggestions,
            token_usage=result.token_usage,
            skipped="" if result.suggestions else "briefing_empty",
            dropped=result.dropped,
        )

    return await evaluate_live_pipeline(
        user,
        plan.turns,
        as_of=when,
        discover_model=ctx.get_chat_model("live_discover"),
        pick_model=ctx.get_chat_model("live_pick"),
        embeddings=ctx.embeddings,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        content=ctx.store,
        # Two conditions, and BOTH are already resolved by here: the plan carries what this
        # connection allowed (clamped against the deployment's knob at the transport), and
        # `get_web_search` returns None unless the deployment enabled one. Core then asks the
        # adapter's own `available()` before it offers the lookup at all.
        web_search=ctx.get_web_search() if plan.web_search else None,
        paths=fast_paths_from_registry(user_id),
        focus=plan.focus,
        already_shown=plan.already_shown,
        ledger=ledger,
        label_map=label_map,
        max_pending_turns=plan.max_pending_turns,
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
        prompt(
            "recall.suggestion.detail_card",
            kind=suggestion.get("kind", ""),
            title=suggestion.get("title", ""),
            body=suggestion.get("body", ""),
            trigger=suggestion.get("trigger", ""),
        )
    ]
    if passages:
        blocks = []
        for p in passages:
            head = prompt(
                "recall.suggestion.detail_source_head",
                source_id=p["source_id"],
                block_start=p["block_start"],
                block_end=p["block_end"],
            )
            blocks.append(f"## {head}\n{p['text']}")
        parts.append(
            prompt("recall.suggestion.detail_sources_header", count=len(passages))
            + "\n"
            + "\n\n".join(blocks)
        )
    else:
        parts.append(prompt("recall.suggestion.detail_no_sources"))
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
            SystemMessage(content=detail_contract()),
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
