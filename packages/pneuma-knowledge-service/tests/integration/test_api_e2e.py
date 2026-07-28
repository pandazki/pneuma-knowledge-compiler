"""API e2e against the live stack over an ASGI-transport httpx client (the app lifespan
wires the real adapters, on the test's own event loop)."""

from __future__ import annotations

import json
import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs, drain_user


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _client(app):
    """Run the app's lifespan and yield an ASGI-transport client, all on the TEST's event
    loop. Starlette's TestClient would drive the app from a separate portal thread with
    its own loop, which the loop-bound adapters (PG pool, httpx clients) cannot survive.
    `app` is attached to the client so tests can still reach `client.app.state.ctx`."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app
            yield c


@pytest.fixture
async def client():
    s = Settings()
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(s)) as c:
        yield c


@pytest.fixture
async def scripted_client(tmp_path):
    """App whose recall/briefing chat model is a scripted (keyless) model. The script
    replays fast-answer, deep-answer (direct, no tool calls), briefing-answer in order."""
    script = tmp_path / "recall.json"
    script.write_text(
        json.dumps(
            {
                "turns": [
                    {"content": "后端负责人"},
                    {"content": "初答"},
                    {"content": "简报回答"},
                ]
            }
        ),
        encoding="utf-8",
    )
    s = Settings(
        canonical_root=str(tmp_path / "canonical"),
        llm_model=f"scripted:{script}",
    )
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(s)) as c:
        yield c


async def test_conversation_intake_recall_fetch_flow(client):
    uid = f"u-e2e-{uuid.uuid4().hex[:10]}"
    base = f"/v1/users/{uid}"

    resp = await client.post(
        f"{base}/sources/conversation",
        json={
            "title": "契约会议",
            "turns": [
                {"speaker": "甲方", "text": "这份合同的付款条款需要在交付后三十日内结清。", "at": "2026-07-20T09:00:00Z"},
                {"speaker": "乙方", "text": "关于违约金，我们参考契约書第五条。", "at": "2026-07-20T09:05:00Z"},
                {"speaker": "甲方", "text": "The warranty covers twelve months.", "at": "2026-07-21T10:00:00Z"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    source_id = body["source_id"]
    assert body["intake_plan"]["canonical_treatment"] == "full"
    assert body["deduplicated"] is False

    # List surfaces the source with its intake plan + block count (for M2 UI).
    listed = (await client.get(f"{base}/sources")).json()
    entry = next(s for s in listed if s["source_id"] == source_id)
    assert entry["intake_plan"]["semantic_indexing"] == "full"
    assert entry["block_count"] >= 1

    # The user directory (UI switcher) surfaces this uid.
    users = (await client.get("/v1/users")).json()
    assert uid in users

    # Single-source detail: meta + intake_plan + blocks + structure map (M2 UI).
    detail = await client.get(f"{base}/sources/{source_id}")
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["source_id"] == source_id
    assert d["intake_plan"]["canonical_treatment"] == "full"
    assert len(d["blocks"]) == entry["block_count"]
    assert any("付款条款" in b["text"] for b in d["blocks"])
    assert isinstance(d["structure"]["sections"], list) and d["structure"]["sections"]

    # Unknown source id → 404.
    assert (await client.get(f"{base}/sources/does-not-exist")).status_code == 404

    # Indexing is async now: L1/L2 are written by the background "index" job, not during
    # the ingest request. Drain only the index job (this fixture has no real compile model)
    # so recall has something to hit.
    ctx = client.app.state.ctx
    assert await drain_index_jobs(ctx, UserId(uid)) == 1

    # rag recall on a Chinese query returns dual-path hits.
    recall = await client.post(f"{base}/recall", json={"query": "合同 付款 条款", "mode": "rag", "limit": 10})
    assert recall.status_code == 200, recall.text
    hits = recall.json()
    assert hits, "expected recall hits"
    assert any("付款" in h["text"] for h in hits)
    assert all(set(h["paths"]) <= {"lexical", "vector"} and h["paths"] for h in hits)

    # L0 verbatim fetch by section (calendar date).
    fetched = await client.post(f"{base}/sources/{source_id}/fetch", json={"locator": {"section": ["2026-07-20"]}})
    assert fetched.status_code == 200
    assert "付款条款" in fetched.json()["text"]

    # Content dedup: re-post identical turns → same source, nothing re-indexed.
    again = await client.post(
        f"{base}/sources/conversation",
        json={
            "title": "契约会议",
            "turns": [
                {"speaker": "甲方", "text": "这份合同的付款条款需要在交付后三十日内结清。", "at": "2026-07-20T09:00:00Z"},
                {"speaker": "乙方", "text": "关于违约金，我们参考契约書第五条。", "at": "2026-07-20T09:05:00Z"},
                {"speaker": "甲方", "text": "The warranty covers twelve months.", "at": "2026-07-21T10:00:00Z"},
            ],
        },
    )
    assert again.json()["deduplicated"] is True
    assert again.json()["source_id"] == source_id


async def test_indexing_is_async_recall_empty_until_index_job_drains(client):
    """Ingest is enqueue-only: L1/L2 are NOT written during the request — recall stays
    empty until the background "index" job drains, then returns hits."""
    ctx = client.app.state.ctx
    uid = f"u-e2e-async-{uuid.uuid4().hex[:10]}"
    user = UserId(uid)
    base = f"/v1/users/{uid}"
    try:
        resp = await client.post(
            f"{base}/sources/conversation",
            json={
                "title": "异步索引",
                "turns": [
                    {"speaker": "甲", "text": "供应商交期从两周缩短到五天。", "at": "2026-07-20T09:00:00Z"},
                    {"speaker": "乙", "text": "季度目标是提升客户留存率。", "at": "2026-07-20T09:05:00Z"},
                ],
            },
        )
        assert resp.status_code == 200, resp.text

        # An "index" job is queued; L1/L2 are not populated yet → recall is empty.
        kinds = [j["kind"] for j in await ctx.store.list_jobs(user)]
        assert "index" in kinds
        empty = await client.post(
            f"{base}/recall", json={"query": "供应商 交期", "mode": "rag", "limit": 10}
        )
        assert empty.status_code == 200, empty.text
        assert empty.json() == [], "recall must be empty before the index job drains"

        # Drain only the index job (this fixture has no real compile model) → L1/L2 land.
        assert await drain_index_jobs(ctx, user) == 1

        hits = (
            await client.post(
                f"{base}/recall",
                json={"query": "供应商 交期", "mode": "rag", "limit": 10},
            )
        ).json()
        assert hits, "recall must return hits once the index job has drained"
        assert any("交期" in h["text"] for h in hits)
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)


async def test_fast_deep_and_briefing_flow(scripted_client):
    """ingest → compile (drain) → L3 projection → fast/deep recall + briefing ask (M4)."""
    client = scripted_client
    ctx = client.app.state.ctx
    uid = f"u-e2e-m4-{uuid.uuid4().hex[:8]}"
    user = UserId(uid)
    base = f"/v1/users/{uid}"

    resp = await client.post(
        f"{base}/sources/conversation",
        json={
            "title": "项目同步",
            "turns": [
                {"speaker": "Alice", "text": "程野 是后端负责人，下周交付演示稿。", "at": "2026-07-20T09:00:00Z"},
                {"speaker": "Bob", "text": "验收条件是通过端到端测试。", "at": "2026-07-20T09:05:00Z"},
                {"speaker": "Alice", "text": "别名叫欧文。", "at": "2026-07-20T09:10:00Z"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["source_id"]

    # Drain the ingest-enqueued compile job with a scripted compile model → projection.
    compile_model = ScriptedChatModel(
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
    # Two jobs drain: the "index" job (L1/L2) then the ingest-enqueued "compile" job.
    processed = await drain_user(ctx, compile_model, load_builtin_skill(), user)
    assert processed == 2

    # L3 projection landed the claim in PG canonical_claims.
    claims = await ctx.store.list_canonical_claims(user)
    assert claims and any(str(sid) == c["citations"][0]["source_id"] for c in claims if c["citations"])

    snaps = (await client.get(f"{base}/snapshots")).json()
    assert snaps, "expected a snapshot"

    # fast recall → answer over capped claims (usage carries cache fields).
    fast = await client.post(
        f"{base}/recall",
        json={"query": "谁是后端负责人", "mode": "fast", "as_of": "2026-07-25T00:00:00Z"},
    )
    assert fast.status_code == 200, fast.text
    fbody = fast.json()
    assert fbody["mode"] == "fast" and fbody["answer"] == "后端负责人"
    assert fbody["used_claims"], "fast should surface at least one claim"
    assert set(fbody["token_usage"]) >= {"cache_read", "cache_creation"}

    # deep recall → agentic loop (scripted model answers directly → empty tool trail).
    deep = await client.post(
        f"{base}/recall",
        json={"query": "谁是后端负责人", "mode": "deep", "as_of": "2026-07-25T00:00:00Z"},
    )
    assert deep.status_code == 200, deep.text
    dbody = deep.json()
    assert dbody["mode"] == "deep" and dbody["answer"] == "初答"
    assert dbody["used_claims"], "deep should surface the seed claims"
    assert dbody["trail"] == []

    # briefing build (source-anchored) → summary counts.
    built = await client.post(f"{base}/briefings", json={"source_ids": [sid]})
    assert built.status_code == 200, built.text
    bbody = built.json()
    assert bbody["source_count"] == 1
    assert bbody["claims_count"] >= 1
    assert bbody["char_count"] > 0
    briefing_id = bbody["briefing_id"]

    assert any(
        b["briefing_id"] == briefing_id
        for b in (await client.get(f"{base}/briefings")).json()
    )

    # briefing ask → answer + usage (as_of injected server-side).
    asked = await client.post(
        f"{base}/briefings/{briefing_id}/ask", json={"question": "合同讲了什么"}
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"] == "简报回答"

    await client.get(f"{base}/briefings")  # listing works post-ask
    await ctx.store.delete_user(user)


async def test_cors_allows_vite_dev_origin(client):
    """The browser UI (vite dev server) must be allowed to call the API cross-origin."""
    origin = "http://localhost:5173"
    r = await client.get("/v1/users", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    # Preflight for a POST from the same origin is permitted.
    pre = await client.options(
        "/v1/users/u-x/recall",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == origin


async def test_profile_put_persists_and_get_reflects(client):
    uid = f"u-e2e-{uuid.uuid4().hex[:10]}"
    base = f"/v1/users/{uid}"

    # Un-onboarded id: mock synthesis.
    before = await client.get(f"{base}/profile")
    assert before.status_code == 200
    assert before.json()["source"] == "mock"
    base_role = before.json()["role"]

    put = await client.put(
        f"{base}/profile",
        json={
            "display_name": "IT Onboard",
            "industry": "tech",
            "role": "engineering",
            "level": "staff",
            "locale": {"city": "深圳"},
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["source"] == "user"
    assert (body["industry"], body["role"], body["level"]) == ("tech", "engineering", "staff")
    assert body["locale"]["city"] == "深圳"

    # Persisted picture is returned on subsequent GET (persisted-first).
    after = (await client.get(f"{base}/profile")).json()
    assert after["source"] == "user"
    assert after["display_name"] == "IT Onboard"
    assert after["level"] == "staff"

    # A different, un-onboarded id is unaffected (still mock).
    other = (await client.get(f"/v1/users/u-e2e-{uuid.uuid4().hex[:8]}/profile")).json()
    assert other["source"] == "mock"

    # Bad enum → 422.
    assert (await client.put(f"{base}/profile", json={"level": "god"})).status_code == 422

    await client.app.state.ctx.store.delete_user(UserId(uid))
