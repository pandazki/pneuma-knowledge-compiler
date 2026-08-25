"""compile worker end-to-end over real middleware with a scripted model (M3b).

Drives one full compile: ingest → enqueue → worker drains the PG queue → git commit +
compile_events in PG + digested stamp + a non-empty dataset projection.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.dataset import build_dataset
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers import compile_worker
from pneuma_knowledge_service.workers.compile_worker import drain_user


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def ctx(tmp_path):
    s = Settings(canonical_root=str(tmp_path / "canonical"))
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    c = await build_context(s)
    yield c
    await c.aclose()


def _turn(speaker: str, text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


async def test_worker_compiles_one_job_end_to_end(ctx):
    user = UserId(f"u-it-worker-{uuid.uuid4().hex[:8]}")
    result = await ingest_conversation(
        ctx,
        user,
        [
            _turn("Alice", "程野 是后端负责人，下周交付演示稿。"),
            _turn("Bob", "验收条件是通过端到端测试。"),
            _turn("Alice", "别名叫欧文。"),
        ],
        title="项目同步",
    )
    sid = str(result.source_id)

    # Scripted model: create one person doc citing the supplied source (¶ within range).
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
                            f"- 程野 是后端负责人。[cite: {sid} ¶0]\n"
                            f"- 别名「欧文」。[cite: {sid} ¶2]"
                        ),
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )

    # Two jobs now drain: the "index" job (L1/L2, enqueued first) then the "compile" job.
    processed = await drain_user(ctx, model, load_skill_base("v1"), user)
    assert processed == 2

    # git commit exists on the canonical layer.
    snaps = await ctx.canonical.snapshots(user)
    assert snaps, "expected a git commit"

    # compile_events landed in PG.
    events = await ctx.store.list_compile_events(user)
    assert len(events) == 2
    assert all(e["type"] == "claim_added" for e in events)

    # source stamped digested.
    assert (await ctx.store.digested_map(user))[sid] is not None

    # job completed ok, with the resulting snapshot ref.
    job = (await ctx.store.list_jobs(user))[0]
    assert job["status"] == "done" and job["ok"] is True
    assert job["snapshot_ref"] == snaps[0].ref

    # dataset projection is non-empty for documents + graph.
    ds = await build_dataset(ctx, user)
    assert ds["documents"]["documents"], "expected canonical documents"
    assert any(n["id"] == "doc-cheng-ye" or n["type"] == "person" for n in ds["graph"]["nodes"])
    assert ds["timeline"]["patches"], "expected a patch record"
    assert ds["journal"], "expected journal events"

    # idempotent compile enqueue: the digested source is not re-enqueued.
    assert await ctx.store.undigested_source_ids(user) == []

    # cleanup PG rows (git repo is under tmp_path, auto-removed).
    await ctx.store.delete_user(user)


async def test_projection_failure_keeps_source_retryable_and_noop_repairs_it(
    ctx, monkeypatch
):
    user = UserId(f"u-it-worker-retry-{uuid.uuid4().hex[:8]}")
    result = await ingest_conversation(
        ctx,
        user,
        [_turn("Alice", "程野负责投影重试验收。")],
        title="投影重试",
    )
    sid = str(result.source_id)
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
                            f"- 程野负责投影重试验收。[cite: {sid} ¶0]"
                        ),
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    real_sync = compile_worker.sync_projection
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic projection outage")
        return await real_sync(*args, **kwargs)

    monkeypatch.setattr(compile_worker, "sync_projection", fail_once)

    try:
        # The canonical commit succeeds, but its first derived projection fails.
        assert await drain_user(ctx, model, load_skill_base("v1"), user) == 2
        assert (await ctx.store.digested_map(user))[sid] is None
        failed = [
            job
            for job in await ctx.store.list_jobs(user)
            if job["kind"] == "compile"
        ][0]
        assert failed["status"] == "done" and failed["ok"] is False
        assert "synthetic projection outage" in failed["detail"]

        # POST /compile would select this undigested source. Replaying it is a
        # canonical noop, but must repair all derived stores before digestion.
        assert await ctx.store.undigested_source_ids(user) == [sid]
        await ctx.store.enqueue(user, "compile", {"source_ids": [sid]})
        assert await drain_user(ctx, model, load_skill_base("v1"), user) == 1

        assert calls == 2
        assert (await ctx.store.digested_map(user))[sid] is not None
        retry = [
            job
            for job in await ctx.store.list_jobs(user)
            if job["kind"] == "compile"
        ][0]
        assert retry["ok"] is True
        assert retry["detail"].startswith("projection:")
        assert await ctx.store.list_canonical_claims(user)
        assert await ctx.lexical.count_claims(user) == 1
        assert await ctx.vectors.count_claims(user) == 1
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)


async def test_worker_records_brief_when_enabled(ctx, monkeypatch):
    """brief_enabled: the derived narration lands on the job row and rides /history.

    Default-off is covered by the end-to-end test above (no brief model is ever built
    there); this exercises the enabled path with a fake narration model on the `brief`
    role only, so compile/index behavior stays byte-identical.
    """
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    user = UserId(f"u-it-worker-brief-{uuid.uuid4().hex[:8]}")
    result = await ingest_conversation(
        ctx,
        user,
        [_turn("Alice", "程野 是后端负责人。")],
        title="简报验证",
    )
    sid = str(result.source_id)
    model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/people/cheng-ye.md",
                        "frontmatter": {"type": "person", "slug": "cheng-ye"},
                        "body": f"## 程野\n\n- 程野 是后端负责人。[cite: {sid} ¶0]",
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )

    narration = "记录了程野的后端负责人身份。"
    monkeypatch.setattr(ctx.settings, "brief_enabled", True)
    real_get = ctx.get_chat_model

    def get_chat_model(role: str = "default"):
        if role == "brief":
            return GenericFakeChatModel(messages=iter([AIMessage(content=narration)]))
        return real_get(role)

    monkeypatch.setattr(ctx, "get_chat_model", get_chat_model)

    try:
        assert await drain_user(ctx, model, load_skill_base("v1"), user) == 2

        job = [
            j for j in await ctx.store.list_jobs(user) if j["kind"] == "compile"
        ][0]
        assert job["ok"] is True

        rows, _, _ = await ctx.store.list_history_page(user, limit=10, kind="patch")
        assert rows and rows[0]["payload"]["brief"] == narration
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
