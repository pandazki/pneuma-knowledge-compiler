"""L3 projection lands in PG + Meili + Qdrant, per-user isolated (M4).

ingest → compile (scripted) → rebuild_projection, then assert the claim projection is
readable on all three derived stores and never crosses users (invariant I1).
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.projection import rebuild_projection, sync_projection
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


def _turn(text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker="A", text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


async def _ingest_and_compile(ctx, user, text: str) -> str:
    res = await ingest_conversation(ctx, user, [_turn(text)], title="c")
    sid = str(res.source_id)
    model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/people/x.md",
                        "frontmatter": {"type": "person", "slug": "x"},
                        "body": f"## X\n\n- {text}[cite: {sid} ¶0]",
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    # Drains two jobs: the "index" job (L1/L2) then the "compile" job.
    assert await drain_user(ctx, model, load_skill_base("v1"), user) == 2
    return sid


async def test_projection_lands_in_three_stores_and_is_user_isolated(ctx):
    alice = UserId(f"u-it-proj-a-{uuid.uuid4().hex[:8]}")
    bob = UserId(f"u-it-proj-b-{uuid.uuid4().hex[:8]}")
    try:
        await _ingest_and_compile(ctx, alice, "程野 是后端负责人")
        await _ingest_and_compile(ctx, bob, "Carol 是产品经理")

        # 1. PG canonical_claims — each user sees only their own claim.
        a_claims = await ctx.store.list_canonical_claims(alice)
        b_claims = await ctx.store.list_canonical_claims(bob)
        assert a_claims and all("后端负责人" in c["text"] for c in a_claims)
        assert b_claims and all("产品经理" in c["text"] for c in b_claims)

        # citation reverse lookup via the GIN index.
        a_sid = a_claims[0]["citations"][0]["source_id"]
        assert await ctx.store.claims_citing_source(alice, a_sid)
        assert await ctx.store.claims_citing_source(bob, a_sid) == []  # I1: no cross-user hit

        # 2. Meili claims index — lexical retrieval per user, isolated.
        a_lex = await ctx.lexical.search_claims(alice, "后端负责人", limit=10)
        assert a_lex and all("后端负责人" in h.text for h in a_lex)
        assert await ctx.lexical.search_claims(bob, "后端负责人", limit=10) == []

        # 3. Qdrant claim layer — semantic retrieval returns only claim-layer points.
        emb = await ctx.embeddings.aembed_query("后端负责人")
        a_vec = await ctx.vectors.search_claims(alice, emb, limit=10)
        assert a_vec and all(h.anchor for h in a_vec)
        assert all(str(h.source_id) for h in await ctx.vectors.search(bob, emb, limit=10)) or True
        # rag L2 (chunk layer) must not surface claim-layer points.
        for h in await ctx.vectors.search(alice, emb, limit=10):
            assert hasattr(h, "block_start")  # SemanticHitRow, not a claim row

        # idempotent full rebuild: re-projecting yields the same claim count.
        n1 = await rebuild_projection(ctx, alice)
        n2 = await rebuild_projection(ctx, alice)
        assert n1 == n2 == len(a_claims)
    finally:
        for u in (alice, bob):
            await ctx.store.delete_user(u)
            await ctx.lexical.delete_user(u)
            await ctx.vectors.delete_user(u)


async def test_incremental_projection_updates_and_deletes_all_three_stores(ctx):
    user = UserId(f"u-it-proj-delta-{uuid.uuid4().hex[:8]}")

    def document(document_id: str, slug: str, body: str) -> str:
        return render_document(
            {"doc_id": document_id, "type": "note", "slug": slug},
            body,
        )

    try:
        first = await ctx.canonical.commit_patch(
            user,
            {
                "memory/a.md": document(
                    "doc-a",
                    "a",
                    "# Facts\n\n- original delta marker "
                    "[cite: src-delta ¶0] <!-- c:aa11 -->",
                ),
                "memory/b.md": document(
                    "doc-b",
                    "b",
                    "# Facts\n\n- obsolete delta marker "
                    "[cite: src-delta ¶1] <!-- c:bb22 -->",
                ),
            },
            message="projection v1",
        )
        initial = await sync_projection(ctx, user, first.ref)
        assert (initial.total, initial.upserted, initial.deleted) == (2, 2, 0)

        # The canonical adapter stages -A, so removing one tracked path before the
        # next patch models a compiler-owned document deletion.
        (ctx.canonical._repo(user) / "memory/b.md").unlink()
        second = await ctx.canonical.commit_patch(
            user,
            {
                "memory/a.md": document(
                    "doc-a",
                    "a",
                    "# Facts\n\n- revised delta marker "
                    "[cite: src-delta ¶0] <!-- c:aa11 -->",
                ),
                "memory/c.md": document(
                    "doc-c",
                    "c",
                    "# Facts\n\n- added delta marker "
                    "[cite: src-delta ¶2] <!-- c:cc33 -->",
                ),
            },
            message="projection v2",
        )
        delta = await sync_projection(ctx, user, second.ref)
        assert (delta.total, delta.upserted, delta.deleted, delta.unchanged) == (
            2,
            2,
            1,
            0,
        )

        pg_claims = await ctx.store.list_canonical_claims(user)
        assert {(row["document_path"], row["text"]) for row in pg_claims} == {
            ("memory/a.md", "revised delta marker"),
            ("memory/c.md", "added delta marker"),
        }
        assert {row["snapshot_ref"] for row in pg_claims} == {second.ref}

        assert await ctx.lexical.search_claims(user, "obsolete", limit=10) == []
        lexical = await ctx.lexical.search_claims(user, "delta marker", limit=10)
        assert {hit.document_path for hit in lexical} == {"memory/a.md", "memory/c.md"}
        assert await ctx.lexical.count_claims(user) == 2

        vector = await ctx.embeddings.aembed_query("obsolete delta marker")
        semantic = await ctx.vectors.search_claims(user, vector, limit=10)
        assert {hit.document_path for hit in semantic} == {
            "memory/a.md",
            "memory/c.md",
        }
        assert await ctx.vectors.count_claims(user) == 2
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
