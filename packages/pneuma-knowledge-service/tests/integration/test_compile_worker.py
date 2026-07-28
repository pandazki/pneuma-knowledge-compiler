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
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.dataset import build_dataset
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
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
    processed = await drain_user(ctx, model, load_builtin_skill(), user)
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
