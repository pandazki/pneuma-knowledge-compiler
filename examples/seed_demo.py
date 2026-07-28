#!/usr/bin/env python
"""Build the bundled OPC demo through the real four-layer pipeline, without credentials.

The fixture is synthetic and deliberately small, but the processing is not a UI stub:
three structured context streams enter L0, the worker builds L1/L2, a scripted compile
model proposes canonical writes, the mechanical gate validates citations, and Git-backed
L3 plus every derived projection are persisted for the API and Web UI.

The named demo tenant is reset by default so every run starts from the same authored
material. Pass ``--keep`` to exercise ingestion dedup against an existing local run.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401  (localhost proxy bypass before middleware imports)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user

USER = UserId("u-opc-lin")
# The documented demo runs from the repository root. Keeping this model spec
# repository-relative makes exported lineage portable and safe to publish.
RECALL_SCRIPT = Path("examples/data/opc-demo/recall-script.json")

STREAMS = [
    (
        "Atlas MVP 决策记录",
        [
            ("林知远", "Atlas 是我正在开发的本地优先 AI 研究助手，目标用户是独立开发者。", "owner"),
            ("林知远", "首个 MVP 只保留来源导入、混合检索和带引用回答，暂不做团队权限。", "owner"),
            ("宋遥", "发布门禁定为：离线演示可跑、引用可回到原文、关键流程有端到端测试。", "other"),
        ],
    ),
    (
        "混合检索实验复盘",
        [
            ("林知远", "实验 EXP-014 比较纯向量召回和 BM25 加向量的 RRF 融合。", "owner"),
            ("林知远", "在 24 条合成任务上，融合方案减少了专有名词漏召回；这只是内部合成结果。", "owner"),
            ("顾宁", "下一轮要固定数据集版本，并把失败样本和查询改写分开记录。", "other"),
        ],
    ),
    (
        "一人公司发布检查",
        [
            ("林知远", "每次公开发布前先跑单测、生产构建和无密钥 mock 全链路。", "owner"),
            ("林知远", "密钥只从本地环境读取，日志、canonical 和示例数据都禁止写入凭据。", "owner"),
            ("程野", "README 要写清能力边界、快速开始、恢复路径和已知限制。", "other"),
        ],
    ),
]


def _turn(speaker: str, text: str, role: str, index: int) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker,
        text=text,
        role=role,
        speaker_id="owner" if role == "owner" else f"peer-{speaker}",
        at=datetime.fromisoformat(f"2026-07-{18 + index:02d}T09:00:00+08:00"),
    )


def _compile_turns() -> list[list[dict]]:
    """One scripted, mechanically valid tool-call turn per source compile job.

    Every job receives exactly one source, so the runner aliases it to ``s01``.
    """
    documents = [
        (
            "work/products/atlas.md",
            {"type": "product", "slug": "atlas"},
            (
                "# Atlas\n\n"
                "## 定位\n\n"
                "- Atlas 是面向独立开发者的本地优先 AI 研究助手。[cite: s01 ¶0]\n"
                "- MVP 范围是来源导入、混合检索和带引用回答；团队权限明确不在首版。[cite: s01 ¶1]\n\n"
                "## 发布门禁\n\n"
                "- 离线演示、引用回溯和关键流程端到端测试全部通过后才可发布。[cite: s01 ¶2]"
            ),
        ),
        (
            "work/experiments/hybrid-retrieval.md",
            {"type": "experiment", "slug": "hybrid-retrieval"},
            (
                "# EXP-014 · 混合检索\n\n"
                "- 实验比较纯向量召回与 BM25 + 向量的 RRF 融合。[cite: s01 ¶0]\n"
                "- 24 条合成任务中融合方案减少了专有名词漏召回；结果只代表内部合成数据。[cite: s01 ¶1]\n"
                "- 下一轮必须固定数据集版本，并把失败样本与查询改写分开记录。[cite: s01 ¶2]"
            ),
        ),
        (
            "work/operations/release-checklist.md",
            {"type": "operation", "slug": "release-checklist"},
            (
                "# 公开发布检查\n\n"
                "- 发布前运行单测、生产构建和无密钥 mock 全链路。[cite: s01 ¶0]\n"
                "- 凭据只从本地环境读取，禁止进入日志、canonical 与示例数据。[cite: s01 ¶1]\n"
                "- README 必须覆盖能力边界、快速开始、恢复路径和已知限制。[cite: s01 ¶2]"
            ),
        ),
    ]
    return [
        [
            {
                "name": "create_document",
                "args": {"path": path, "frontmatter": frontmatter, "body": body},
            },
            {"name": "finish_compile"},
        ]
        for path, frontmatter, body in documents
    ]


async def _reset(ctx, settings: Settings) -> None:
    await ctx.store.delete_user(USER)
    await ctx.lexical.delete_user(USER)
    await ctx.vectors.delete_user(USER)

    root = Path(settings.canonical_root).resolve()
    target = (root / str(USER)).resolve()
    if target.parent != root or target.name != str(USER):
        raise RuntimeError(f"refusing unsafe canonical reset target: {target}")
    if target.exists():
        shutil.rmtree(target)


async def run(*, reset: bool = True) -> int:
    settings = Settings(
        llm_model=f"scripted:{RECALL_SCRIPT.as_posix()}",
        embedding_model="fake:64",
        chunk_strategy="sentence",
    )
    ctx = await build_context(settings)
    try:
        if reset:
            await _reset(ctx, settings)

        profile = await ctx.user_info.get_profile(USER)
        await ctx.store.upsert_user_profile(
            USER, profile.model_dump(mode="json", exclude={"level_style"})
        )

        source_ids: list[str] = []
        for stream_index, (title, rows) in enumerate(STREAMS):
            turns = [
                _turn(speaker, text, role, stream_index + turn_index)
                for turn_index, (speaker, text, role) in enumerate(rows)
            ]
            result = await ingest_conversation(
                ctx,
                USER,
                turns,
                title=title,
                origin="context_stream",
                meta={"synthetic": True, "fixture": "opc-demo-v1"},
            )
            source_ids.append(str(result.source_id))
            print(
                f"  {'dedup' if result.deduplicated else 'ingest'} "
                f"{str(result.source_id)[:8]}  {title}"
            )

        model = ScriptedChatModel(turns=_compile_turns())
        processed = await drain_user(ctx, model, load_builtin_skill(), USER)

        sources = await ctx.store.list(USER)
        claims = await ctx.store.list_canonical_claims(USER)
        documents = await ctx.canonical.list(USER)
        snapshots = await ctx.canonical.snapshots(USER)
        print(
            "  pipeline "
            f"sources={len(sources)} jobs={processed} docs={len(documents)} "
            f"claims={len(claims)} snapshots={len(snapshots)}"
        )

        if reset:
            assert len(sources) == 3
            assert processed == 6
            assert len(documents) == 3
            assert len(claims) == 9
            assert len(snapshots) == 3
        assert all(source_ids)
    finally:
        await ctx.aclose()

    print(f"OK: synthetic OPC demo ready → {USER}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the existing tenant and exercise source dedup instead of resetting",
    )
    args = parser.parse_args()
    return asyncio.run(run(reset=not args.keep))


if __name__ == "__main__":
    sys.exit(main())
