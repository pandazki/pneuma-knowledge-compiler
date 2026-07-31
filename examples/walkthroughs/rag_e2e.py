#!/usr/bin/env python
"""End-to-end ingest + rag walkthrough against the compose stack (architecture.md §3, §7).

Two users each ingest a few mixed zh/en/ja conversations, then:
  - rag recall (L2+L1 dual-path + RRF) for Chinese / Japanese / English queries
  - L0 verbatim fetch by section locator
  - I1 isolation check: user A's query never surfaces user B's sources

Exit code is non-zero on any failure (empty recall, cross-user leak, error).
Run after `docker compose -f infra/docker-compose.yml up -d --wait`.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
from examples import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.rag import rag_recall
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs

RUN = uuid.uuid4().hex[:8]


def _turn(speaker: str, text: str, day: int) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, day, 9, tzinfo=timezone.utc)
    )


OWNER_A_CONVOS = [
    (
        "开源发布检查",
        [
            _turn("演示用户", "发布前必须完成许可证扫描、生产构建和无密钥端到端测试。", 20),
            _turn("审阅 agent", "README 还需要写清数据恢复路径和已知限制。", 20),
        ],
    ),
    (
        "Atlas 检索实验",
        [
            _turn("演示用户", "The hybrid retrieval experiment combines BM25 and vector search.", 21),
            _turn("实验 agent", "下一轮要固定合成数据集版本，并单独记录失败查询。", 21),
        ],
    ),
]

OWNER_B_CONVOS = [
    (
        "个人研究助手实验",
        [
            _turn("独立开发者", "语义分块先保留为可选能力，默认继续使用机械句子切分。", 20),
            _turn("研究 agent", "来週の実験で新しい埋め込みモデルを比較します。", 20),
        ],
    ),
]


async def _ingest_all(ctx, user, convos) -> list[SourceId]:
    ids = []
    for title, turns in convos:
        result = await ingest_conversation(ctx, user, turns, title=title)
        print(f"  ingested {result.source_id[:8]}… '{title}' plan={result.intake_plan.canonical_treatment}/{result.intake_plan.semantic_indexing}")
        ids.append(result.source_id)
    return ids


async def _recall(ctx, user, query: str) -> list:
    hits = await rag_recall(user, query, lexical=ctx.lexical, vectors=ctx.vectors, embeddings=ctx.embeddings, limit=5)
    print(f"  recall {query!r}: {len(hits)} hits")
    for h in hits[:3]:
        print(f"    [{'+'.join(h.paths)}] {h.source_id[:8]}…#{h.block_start}-{h.block_end} score={h.score:.4f} :: {h.text[:40]}")
    return hits


async def main() -> int:
    ctx = await build_context(Settings())
    failures: list[str] = []
    try:
        owner_a = UserId(f"u-rag-lab-a-{RUN}")
        owner_b = UserId(f"u-rag-lab-b-{RUN}")

        print(f"== ingest (owner_a={owner_a}, owner_b={owner_b}) ==")
        owner_a_ids = set(await _ingest_all(ctx, owner_a, OWNER_A_CONVOS))
        owner_b_ids = set(await _ingest_all(ctx, owner_b, OWNER_B_CONVOS))

        # Ingest only writes L0 and ENQUEUES; L1/L2 are built by the worker. Without this
        # every recall below returns 0 hits — which is exactly what this script did before.
        # `drain_index_jobs` rather than `drain_user`: this is the keyless demo, so there is
        # no real compile model, and it deliberately leaves the compile job queued.
        print("== drain index jobs (L1/L2) ==")
        for who, uid in (("owner_a", owner_a), ("owner_b", owner_b)):
            print(f"  {who}: {await drain_index_jobs(ctx, uid)} index job(s)")

        print("== owner A recall ==")
        for query in ["许可证 生产构建", "hybrid retrieval vector", "失败查询 数据集"]:
            hits = await _recall(ctx, owner_a, query)
            if not hits:
                failures.append(f"owner A recall empty for {query!r}")
            # I1: owner A's recall must never surface owner B's sources.
            if any(h.source_id in owner_b_ids for h in hits):
                failures.append(f"I1 LEAK: owner B source in owner A recall for {query!r}")

        print("== owner B recall (japanese) ==")
        hits = await _recall(ctx, owner_b, "実験 埋め込みモデル")
        if not hits:
            failures.append("owner B japanese recall empty")
        if any(h.source_id in owner_a_ids for h in hits):
            failures.append("I1 LEAK: owner A source in owner B recall")

        print("== L0 verbatim fetch by section ==")
        first = sorted(owner_a_ids)[0] if owner_a_ids else None
        for sid in owner_a_ids:
            try:
                text = await ctx.store.fetch(owner_a, sid, {"section": ["2026-07-20"]})
            except KeyError:
                continue  # this source has no 2026-07-20 section; try the next
            if text:
                print(f"  fetch {sid[:8]}… section 2026-07-20 :: {text[:50]}")
                break
        else:
            if first is not None:
                failures.append("L0 fetch returned empty")
    finally:
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: rag e2e passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
