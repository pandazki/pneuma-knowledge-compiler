#!/usr/bin/env python
"""Real-provider smoke: OpenRouter chat model through the full chain, tracing to Langfuse.

Unlike the scripted examples, the compile step drives a REAL model over the claim-level
tools (it decides what documents/claims to write); fast/deep/briefing then run real asks.
Every LLM call is traced to the local Langfuse project via the injected callback.

Run after `docker compose -f infra/docker-compose.yml up -d --wait`, with .env holding
OPENROUTER_API_KEY + LANGFUSE_*. Model overridable via PNEUMA_KNOWLEDGE_LLM_MODEL (must be an
`openrouter:<model>` that supports tool calling). Costs a few cents. Exit non-zero on failure.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
from examples import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.briefing import BriefingScope, briefing_ask, build_briefing
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, llm_call_config, resolve_model_name
from pneuma_knowledge_service.workers.compile_worker import drain_user

RUN = uuid.uuid4().hex[:8]


def _turn(speaker: str, text: str, day: int) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, day, 9, tzinfo=timezone.utc)
    )


async def _timed(label: str, coro):
    # Takes a coroutine, not a thunk: a coroutine object runs nothing until awaited, so
    # the clock still starts immediately before execution (same measurement as before).
    t0 = time.perf_counter()
    out = await coro
    print(f"  [{label}] {time.perf_counter() - t0:.1f}s")
    return out


async def main() -> int:
    # Models come from .env per-operation routing (PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE/_RECALL/_DEEP).
    tmp = tempfile.mkdtemp(prefix="pneuma_knowledge-smoke-")
    settings = Settings(
        canonical_root=tmp,
        qdrant_collection=f"pneuma_knowledge_smoke_{RUN}",
    )
    ctx = await build_context(settings)
    if ctx.langfuse_handler() is None:
        print("WARN: Langfuse not configured — traces will not be recorded")
    print(f"== real-provider smoke  langfuse={'on' if ctx.langfuse_handler() else 'off'} ==")
    for role in ("compile", "recall", "deep"):
        print(f"  model[{role}] = {resolve_model_name(settings, role)}")
    failures: list[str] = []
    user = UserId(f"u-e2e-smoke-{RUN}")
    try:
        print(f"== ingest (user={user}) ==")
        res = await ingest_conversation(
            ctx,
            user,
            [
                _turn("演示用户", "我准备把 Atlas 作为开源项目发布，程野负责本地导出模块。", 20),
                _turn("演示用户", "0.1.0 的门禁包括端到端测试、许可证扫描和演示数据脱敏。", 20),
                _turn("程野", "本地导出已经跑通，计划在下个月中旬进入公开预览。", 20),
            ],
            title="Atlas 开源发布同步",
        )
        sid = str(res.source_id)
        print(f"  source {sid[:8]}…  intake={res.intake_plan.canonical_treatment}/{res.intake_plan.semantic_indexing}")

        print("== compile (REAL model over claim-level tools) → git commit + L3 projection ==")
        n = await _timed("compile", drain_user(ctx, ctx.get_chat_model("compile"), load_builtin_skill(), user))
        print(f"  processed {n} job(s)")
        jobs = await ctx.store.list_jobs(user)
        for j in jobs:
            print(f"  job {j['job_id']}: ok={j.get('ok')} detail={str(j.get('detail'))[:80]}")

        snaps = await ctx.canonical.snapshots(user)
        print(f"== canonical snapshots: {len(snaps)} ==")
        docs = await ctx.canonical.list(user)
        for d in docs:
            print(f"  {d.path}  ({len(d.body.splitlines())} lines)")
        if not docs:
            failures.append("compile produced no canonical documents")

        claims = await ctx.store.list_canonical_claims(user)
        print(f"== L3 claims projected: {len(claims)} ==")
        for c in claims[:8]:
            print(f"  c:{c['anchor']}  {c['document_path']}  :: {c['text'][:60]}")

        as_of = datetime(2026, 7, 25, tzinfo=timezone.utc)

        if claims:
            print("== fast recall: 谁负责本地导出模块 ==")
            fa = await _timed("fast", fast_recall(
                user, "谁负责本地导出模块", as_of=as_of,
                claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
                lexical=ctx.lexical, vectors=ctx.vectors, content=ctx.store,
                embeddings=ctx.embeddings, model=ctx.get_chat_model("recall"),
                **llm_call_config(ctx, operation="recall.fast", user_id=str(user)),
            ))
            print(f"  answer={fa.answer!r}  claims={len(fa.used_claims)}  windows={len(fa.used_windows)}  usage={fa.token_usage}")

            print("== deep recall: Atlas 什么时候进入公开预览 ==")
            da = await _timed("deep", deep_recall(
                user, "Atlas 什么时候进入公开预览", as_of=as_of,
                claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
                lexical=ctx.lexical, vectors=ctx.vectors,
                embeddings=ctx.embeddings, model=ctx.get_chat_model("deep"), content=ctx.store,
                **llm_call_config(ctx, operation="recall.deep", user_id=str(user)),
            ))
            print(f"  answer={da.answer!r}  claims={len(da.used_claims)}  windows={len(da.used_windows)}  trail={list(da.trail)}")

            print("== briefing (source-anchored on the release sync) + ask ==")
            head = snaps[0] if snaps else SnapshotRef(ref="")
            briefing = await build_briefing(
                user, BriefingScope(source_ids=[SourceId(sid)]), snapshot=head,
                snapshot_docs=docs, content=ctx.store,
                claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
                embeddings=ctx.embeddings, lexical=ctx.lexical, vectors=ctx.vectors,
            )
            print(f"  pack: claims={briefing.claims_count} sources={briefing.source_count} chars={briefing.char_count}")
            ask_cfg = llm_call_config(ctx, operation="briefing.ask", user_id=str(user))
            a1 = await _timed("ask", briefing_ask(
                briefing, "0.1.0 的发布门禁是什么", as_of=as_of,
                model=ctx.get_chat_model("recall"), content=ctx.store,
                claim_lexical=ctx.lexical, claim_vectors=ctx.vectors,
                embeddings=ctx.embeddings, lexical=ctx.lexical, vectors=ctx.vectors,
                **ask_cfg,
            ))
            print(f"  answer={a1.answer!r}  usage={a1.token_usage}")
        else:
            failures.append("no projected claims — skipped recall/briefing")

        await ctx.flush_traces()
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
    except Exception as e:  # real provider: surface the failure, still clean up
        failures.append(f"{type(e).__name__}: {e}")
    finally:
        try:
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)
        except Exception:
            pass
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: real-provider smoke passed — traces in Langfuse (operation filter: compile/recall.fast/recall.deep/briefing.ask)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
