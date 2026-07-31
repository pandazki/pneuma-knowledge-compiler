#!/usr/bin/env python
"""End-to-end compile walkthrough with a scripted (keyless) model.

Conversation ingest → compile worker (scripted model → git commit) → snapshots + the
four-view dataset projection. Exercises the whole path with no provider key. Exit code
is non-zero on any failure. Run after
`docker compose -f infra/docker-compose.yml up -d --wait`.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from datetime import datetime, timezone

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
from examples import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.dataset import build_dataset
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user

RUN = uuid.uuid4().hex[:8]


def _turn(speaker: str, text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


async def main() -> int:
    tmp = tempfile.mkdtemp(prefix="pneuma_knowledge-compile-e2e-")
    ctx = await build_context(
        Settings(
            canonical_root=tmp,
            qdrant_collection=f"pneuma_knowledge_compile_e2e_{RUN}",
        )
    )
    failures: list[str] = []
    try:
        user = UserId(f"u-e2e-compile-{RUN}")
        print(f"== ingest (user={user}) ==")
        res = await ingest_conversation(
            ctx,
            user,
            [
                _turn("演示用户", "程野 负责 Atlas 的本地导出模块。"),
                _turn("程野", "公开预览版的门禁是端到端测试和许可证扫描全部通过。"),
                _turn("演示用户", "程野 的协作账号是 chengye-labs。"),
            ],
            title="Atlas 发布同步",
        )
        sid = str(res.source_id)
        print(f"  source {sid[:8]}… plan={res.intake_plan.canonical_treatment}/{res.intake_plan.semantic_indexing}")

        model = ScriptedChatModel(
            turns=[
                [
                    {
                        "name": "create_document",
                        "args": {
                            "path": "memory/people/cheng-ye.md",
                            "frontmatter": {"type": "person", "slug": "cheng-ye"},
                            "body": (
                                "## 程野\n\n"
                                f"- 程野负责 Atlas 的本地导出模块。[cite: {sid} ¶0]\n"
                                f"- 协作账号为 `chengye-labs`。[cite: {sid} ¶2]"
                            ),
                        },
                    },
                    {"name": "finish_compile"},
                ]
            ]
        )

        print("== compile worker (scripted) ==")
        n = await drain_user(ctx, model, load_builtin_skill(), user)
        print(f"  processed {n} job(s)")
        # Two: ingest enqueues `index` (L1/L2) AND `compile` (L3), and drain_user is
        # kind-agnostic so it processes both. The old `== 1` predates the enqueue-only
        # ingest refactor.
        if n != 2:
            failures.append(f"expected 2 jobs processed (index + compile), got {n}")

        snaps = await ctx.canonical.snapshots(user)
        print(f"== snapshots ({len(snaps)}) ==")
        for s in snaps:
            print(f"  {s.ref[:12]}  {s.label or ''}")
        if not snaps:
            failures.append("no git commit produced")

        events = await ctx.store.list_compile_events(user)
        print(f"== compile_events: {len(events)} ==")
        for e in events:
            print(f"  {e['type']:14s} {e['path']}  c:{e['anchor']}")
        if not events:
            failures.append("no compile events persisted")

        digested = (await ctx.store.digested_map(user)).get(sid)
        print(f"== digested_at[{sid[:8]}…] = {digested} ==")
        if digested is None:
            failures.append("source not marked digested")

        ds = await build_dataset(ctx, user)
        docs = ds["documents"]["documents"]
        nodes = ds["graph"]["nodes"]
        print(f"== dataset: {len(docs)} documents, {len(nodes)} graph nodes, "
              f"{len(ds['timeline']['patches'])} patches, {len(ds['journal'])} journal events ==")
        for d in docs:
            print(f"  {d['path']}  ({len(d['claims'])} claims)")
        if not docs:
            failures.append("dataset documents empty")
        if not nodes:
            failures.append("dataset graph empty")

        await ctx.store.delete_user(user)
    finally:
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: compile e2e passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
