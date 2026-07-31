#!/usr/bin/env python
"""End-to-end fast / deep / briefing walkthrough with scripted (keyless) models.

conversation ingest → compile worker (scripted → git commit + L3 projection) → fast
recall → build a source-anchored briefing → two asks (verifying the SystemMessage is
byte-stable across as_of, I5) → one deep recall. No provider key. Exit code is non-zero
on any failure. Run after `docker compose -f infra/docker-compose.yml up -d --wait`.
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
from examples import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.briefing import (
    BriefingScope,
    assemble_messages,
    briefing_ask,
    build_briefing,
)
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, llm_call_config
from pneuma_knowledge_service.workers.compile_worker import drain_user

RUN = uuid.uuid4().hex[:8]


def _turn(speaker: str, text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


async def main() -> int:
    tmp = tempfile.mkdtemp(prefix="pneuma_knowledge-briefing-e2e-")
    # Recall/briefing chat model: fast → ask1 → ask2 → deep (direct answer, no tools).
    recall_script = Path(tmp) / "recall.json"
    recall_script.write_text(
        json.dumps(
            {
                "turns": [
                    {"content": "程野"},
                    {"content": "公开发布前需通过端到端测试和许可证扫描"},
                    {"content": "公开发布前需通过端到端测试和许可证扫描"},
                    {"content": "程野"},
                ]
            }
        ),
        encoding="utf-8",
    )
    ctx = await build_context(
        Settings(
            canonical_root=tmp,
            qdrant_collection=f"pneuma_knowledge_briefing_e2e_{RUN}",
            llm_model=f"scripted:{recall_script}",
        )
    )
    failures: list[str] = []
    try:
        user = UserId(f"u-e2e-briefing-{RUN}")
        print(f"== ingest (user={user}) ==")
        res = await ingest_conversation(
            ctx,
            user,
            [
                _turn("演示用户", "程野 负责 Atlas 的本地导出模块。"),
                _turn("程野", "公开预览版的发布门禁是通过端到端测试和许可证扫描。"),
            ],
            title="Atlas 发布检查",
        )
        sid = str(res.source_id)
        print(f"  source {sid[:8]}…")

        compile_model = ScriptedChatModel(
            turns=[
                [
                    {
                        "name": "create_document",
                        "args": {
                            "path": "memory/people/cheng-ye.md",
                            "frontmatter": {"type": "person", "slug": "cheng-ye"},
                            "body": f"## 程野\n\n- 程野负责 Atlas 的本地导出模块。[cite: {sid} ¶0]",
                        },
                    },
                    {
                        "name": "create_document",
                        "args": {
                            "path": "materials/atlas-release-checklist.md",
                            "frontmatter": {
                                "type": "material",
                                "slug": "atlas-release-checklist",
                            },
                            "body": (
                                "## Atlas 发布门禁\n\n"
                                f"公开发布前需通过端到端测试和许可证扫描。[cite: {sid} ¶1]"
                            ),
                        },
                    },
                    {"name": "finish_compile"},
                ]
            ]
        )
        print("== compile worker (scripted) → git commit + L3 projection ==")
        n = await drain_user(ctx, compile_model, load_builtin_skill(), user)
        print(f"  processed {n} job(s)")
        # index (L1/L2) + compile (L3) — see compile_e2e for the same note.
        if n != 2:
            failures.append(f"expected 2 jobs (index + compile), got {n}")

        claims = await ctx.store.list_canonical_claims(user)
        print(f"== canonical_claims projected: {len(claims)} ==")
        for c in claims:
            print(f"  c:{c['anchor']}  {c['document_path']}  :: {c['text']}")
        if len(claims) < 2:
            failures.append("expected >= 2 projected claims")

        as_of = datetime(2026, 7, 25, tzinfo=timezone.utc)

        print("== fast recall ==")
        fa = await fast_recall(
            user,
            "谁负责本地导出模块",
            as_of=as_of,
            claim_lexical=ctx.lexical,
            claim_vectors=ctx.vectors,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
            content=ctx.store,
            embeddings=ctx.embeddings,
            model=ctx.get_chat_model(),
            **llm_call_config(ctx, operation="recall.fast", user_id=str(user)),
        )
        print(f"  answer={fa.answer!r}  used_claims={len(fa.used_claims)}  usage={fa.token_usage}")
        if not fa.used_claims:
            failures.append("fast recall surfaced no claims")
        if "cache_read" not in fa.token_usage:
            failures.append("token_usage missing cache fields")

        print("== build briefing (source-anchored) ==")
        snaps = await ctx.canonical.snapshots(user)
        head = snaps[0] if snaps else SnapshotRef(ref="")
        briefing = await build_briefing(
            user,
            BriefingScope(source_ids=[SourceId(sid)]),
            snapshot=head,
            snapshot_docs=await ctx.canonical.list(user),
            content=ctx.store,
            claim_lexical=ctx.lexical,
            claim_vectors=ctx.vectors,
            embeddings=ctx.embeddings,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
        )
        print(
            f"  claims={briefing.claims_count} sources={briefing.source_count} "
            f"chars={briefing.char_count}"
        )
        if "Atlas 发布门禁" not in briefing.system_prefix:
            failures.append("briefing missing release checklist")
        if "程野负责 Atlas 的本地导出模块" not in briefing.system_prefix:
            failures.append("briefing missing citing claim")

        # I5: SystemMessage byte-stable across two asks with different as_of.
        sys1 = assemble_messages(briefing, "q1", as_of=datetime(2026, 7, 25))[0].content
        sys2 = assemble_messages(briefing, "q2", as_of=datetime(2026, 8, 1))[0].content
        print(f"== briefing ask ×2 (SystemMessage byte-stable: {sys1 == sys2}) ==")
        if sys1 != sys2:
            failures.append("briefing SystemMessage not byte-stable across as_of")

        ask_cfg = llm_call_config(ctx, operation="briefing.ask", user_id=str(user))
        ask_idx = dict(
            claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
            embeddings=ctx.embeddings, lexical=ctx.lexical, vectors=ctx.vectors,
        )
        a1 = await briefing_ask(briefing, "公开发布还缺什么检查", as_of=datetime(2026, 7, 25), model=ctx.get_chat_model(), content=ctx.store, **ask_idx, **ask_cfg)
        a2 = await briefing_ask(briefing, "Atlas 的发布门禁是什么", as_of=datetime(2026, 8, 1), model=ctx.get_chat_model(), content=ctx.store, **ask_idx, **ask_cfg)
        print(f"  ask1={a1.answer!r}  ask2={a2.answer!r}")
        if not a1.answer or not a2.answer:
            failures.append("briefing ask returned empty answer")

        print("== deep recall (agentic search) ==")
        da = await deep_recall(
            user,
            "谁负责本地导出模块",
            as_of=as_of,
            claim_lexical=ctx.lexical,
            claim_vectors=ctx.vectors,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
            embeddings=ctx.embeddings,
            model=ctx.get_chat_model(),
            content=ctx.store,
            **llm_call_config(ctx, operation="recall.deep", user_id=str(user)),
        )
        print(f"  answer={da.answer!r}  claims={len(da.used_claims)}  trail={list(da.trail)}")
        if not da.answer:
            failures.append("deep recall produced no answer")

        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
    finally:
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: briefing e2e passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
