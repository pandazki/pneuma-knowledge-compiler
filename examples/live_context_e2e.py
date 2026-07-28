#!/usr/bin/env python
"""End-to-end Live Context walkthrough with a scripted (keyless) model.

ingest → index (L1/L2) → suggestion evaluation over a transcript window → the mechanical gates
→ handle resolution → want_more expansion. No provider key. Exit code is non-zero on any
failure. Run after `docker compose -f infra/docker-compose.yml up -d --wait`.

Scope note: this drives the CORE engine, like `briefing_e2e.py` does — the two transports
(`POST …/live-context/stream` and `WS …/live-context/ws`) are covered by
`packages/pneuma-knowledge-service/tests/test_live_context_stream.py` and
`test_live_context_ws.py`.

The scripted suggestion bodies cite `s01`, not a real source id, and that is not a shortcut: the
model only ever sees query-local alias handles (`recall/citation_alias.py`), so `s01` is
literally what a real model would emit. It also makes the script independent of the random
source id minted each run.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.suggestion import CONTEXT_FOCUSES
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.suggestion import LIVE_CONTEXT_CONTRACTS, evaluate_live_context
from pneuma_knowledge_service.live_context.engine import expand_suggestion
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs

RUN = uuid.uuid4().hex[:8]

MATERIAL = [
    ConversationTurn(
        speaker="林知远",
        text=(
            "Atlas 采用 Apache-2.0 许可证；公开发布前必须完成依赖许可证扫描，"
            "并确认导出包不含未脱敏实验材料。"
        ),
        at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
]

# The live conversation the owner is in. The owner speaks first, the counterparty asks
# the suggestion-worthy question — which is what makes `focus` observable.
WINDOW = [
    ConversationTurn(speaker="林知远", text="我在整理 Atlas 的公开发布清单。", role="owner",
                     at=datetime(2026, 7, 25, 10, tzinfo=timezone.utc)),
    ConversationTurn(speaker="协作者", text="依赖的许可证兼容性需要怎么确认？",
                     role="other", at=datetime(2026, 7, 25, 10, 1, tzinfo=timezone.utc)),
]


def _suggestion_script(path: Path) -> Path:
    """Three cards, chosen so each surviving gate is observable in one run."""
    batch = {
        "name": "SuggestionBatch",
        "args": {
            "suggestions": [
                {  # survives: grounded + confident
                    "kind": "concept", "title": "许可证兼容性", "confidence": 9,
                    "trigger": "协作者：许可证兼容性需要怎么确认",
                    "body": "发布前必须完成依赖许可证扫描。[cite: s01 ¶0-0]",
                },
                {  # dropped by the confidence gate
                    "kind": "fact", "title": "项目许可证", "confidence": 3,
                    "trigger": "协作者：Atlas 使用什么许可证",
                    "body": "Atlas 采用 Apache-2.0 许可证。[cite: s01 ¶0-0]",
                },
                {  # dropped by the grounding gate — no citation at all
                    "kind": "concept", "title": "凭空的卡片", "confidence": 10,
                    "trigger": "x", "body": "这条没有任何来源标记。",
                },
            ]
        },
    }
    # turn 1: the evaluation. turn 2: plain text, for the want_more expansion.
    path.write_text(
        json.dumps(
            {
                "turns": [
                    [batch],
                    {
                        "content": (
                            "先导出依赖清单，再逐项核对许可证文本与分发条件；"
                            "任何不确定项都应阻断公开发布。"
                        )
                    },
                ]
            },
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return path


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="pneuma_knowledge-suggestion-e2e-"))
    # One scripted model for the whole run, wired through Settings the way briefing_e2e
    # does: `expand_suggestion` reaches for `ctx.get_chat_model("live_context")`, so handing the evaluation
    # its own instance would leave the expansion trying to build a real provider client.
    # One instance also means one cursor — turn 1 is the evaluation, turn 2 the expansion.
    script = _suggestion_script(tmp / "suggestion.json")
    ctx = await build_context(
        Settings(
            canonical_root=str(tmp),
            qdrant_collection=f"pneuma_knowledge_live_context_e2e_{RUN}",
            llm_model=f"scripted:{script}",
        )
    )
    failures: list[str] = []
    try:
        user = UserId(f"u-e2e-suggestion-{RUN}")
        print(f"== ingest (user={user}) ==")
        res = await ingest_conversation(ctx, user, MATERIAL, title="Atlas 发布规范")
        sid = str(res.source_id)
        print(f"  source {sid[:8]}…")

        # Ingest only writes L0 + enqueues. Without the index job there is no L1/L2, so
        # retrieval returns nothing, the alias map is empty, and EVERY card would be eaten
        # by the grounding gate — a green-looking run that proved nothing.
        n = await drain_index_jobs(ctx, user)
        print(f"== index jobs drained: {n} ==")
        if n != 1:
            failures.append(f"expected 1 index job, got {n}")

        print("== suggestion evaluation (focus=other, min_confidence=6) ==")
        result = await evaluate_live_context(
            user, WINDOW,
            as_of=datetime(2026, 7, 25, 10, 2, tzinfo=timezone.utc),
            model=ctx.get_chat_model("live_context"), embeddings=ctx.embeddings,
            claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
            lexical=ctx.lexical, vectors=ctx.vectors, content=ctx.store,
            focus="other", min_confidence=6,
        )
        print(f"  suggestions={len(result.suggestions)}  dropped={result.dropped}")
        for c in result.suggestions:
            print(f"    [{c.kind}] {c.title!r} conf={c.confidence} cites={len(c.citations)}")
            print(f"      body: {c.body}")

        if len(result.suggestions) != 1:
            failures.append(f"expected 1 surviving suggestion, got {len(result.suggestions)}")
        if result.dropped.get("uncited") != 1:
            failures.append(f"grounding gate did not fire: {result.dropped}")
        if result.dropped.get("low_confidence") != 1:
            failures.append(f"confidence gate did not fire: {result.dropped}")

        if result.suggestions:
            suggestion = result.suggestions[0]
            # The handle must be resolved and stripped server-side: the client never sees sNN.
            if "[cite:" in suggestion.body:
                failures.append("citation handle leaked into the delivered body")
            if not suggestion.citations:
                failures.append("surviving suggestion carries no structured citations")
            elif str(suggestion.citations[0].source_id) != sid:
                failures.append(
                    f"handle resolved to the wrong source: {suggestion.citations[0].source_id} != {sid}"
                )

        # focus is posture in the System tier — three fixed contracts, byte-stable (I5).
        print(f"== focus contracts: {len(LIVE_CONTEXT_CONTRACTS)} ==")
        if len({LIVE_CONTEXT_CONTRACTS[f] for f in LIVE_CONTEXT_CONTRACTS}) != 3:
            failures.append("the three focus contracts are not distinct")
        if {o.key for o in CONTEXT_FOCUSES} != set(LIVE_CONTEXT_CONTRACTS):
            failures.append("focus vocabulary and contracts disagree")

        print("== want_more (zero retrieval, verbatim by the card's own citations) ==")
        if result.suggestions:
            detail = await expand_suggestion(
                ctx, str(user),
                {
                    "kind": result.suggestions[0].kind, "title": result.suggestions[0].title,
                    "body": result.suggestions[0].body, "trigger": result.suggestions[0].trigger,
                    "citations": [
                        {"source_id": str(c.source_id), "block_start": c.block_start,
                         "block_end": c.block_end}
                        for c in result.suggestions[0].citations
                    ],
                },
            )
            print(f"  title={detail['title']!r}")
            print(f"  detail={detail['detail']}")
            if not detail["detail"].strip():
                failures.append("want_more returned an empty expansion")
            if not detail["citations"]:
                failures.append("want_more lost the citations")

        await ctx.store.delete_user(user)
    finally:
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: suggestion e2e passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
