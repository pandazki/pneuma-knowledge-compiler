"""Schema-evolve HTTP surface e2e (schema-evolve §2.5, C6): trigger + 409, review list /
detail (changed_files), adopt (202) → skill flip, drop, lazy draft expiry, and /skill shape.

Runs the app's real lifespan over an ASGI-transport client (same pattern as test_api_e2e),
then overrides the wired ctx's evolve model with a scripted one and drains the queue by hand
(the API only enqueues — a worker drains)."""

from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import drain_user


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app
            yield c


_ATLAS_BODY = (
    "## 产品计划\n\n"
    "- Atlas Q3 发布。[cite: s-evolve ¶0] <!-- c:aa11 -->\n"
    "- Atlas 的技术决策由测试用户负责。[cite: s-evolve ¶1] <!-- c:bb22 -->"
)


def _proposed_model() -> ScriptedChatModel:
    return ScriptedChatModel(
        turns=[
            [
                {
                    "name": "_EvolveDraft",
                    "args": {
                        "needs_change": True,
                        "rationale": "topics 下已积累多个个人产品主题。",
                        "families": [
                            {
                                "family": "products",
                                "path_template": "memory/products/{slug}.md",
                                "instructions": "收编个人产品台账。",
                                "evidence": "Atlas 产品规划主题。",
                            }
                        ],
                    },
                }
            ],
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/products/atlas.md",
                        "frontmatter": {"type": "product", "slug": "atlas"},
                        "body": "## 产品\n",
                    },
                },
                {
                    "name": "move_claim",
                    "args": {
                        "from_path": "memory/topics/atlas.md",
                        "anchor_id": "aa11",
                        "to_path": "memory/products/atlas.md",
                        "heading": "产品",
                    },
                },
                {
                    "name": "move_claim",
                    "args": {
                        "from_path": "memory/topics/atlas.md",
                        "anchor_id": "bb22",
                        "to_path": "memory/products/atlas.md",
                        "heading": "产品",
                    },
                },
                {"name": "finish_evolve"},
            ],
        ]
    )


@pytest.fixture
async def env(tmp_path):
    s = Settings(canonical_root=str(tmp_path / "canonical"), evolve_auto_trigger=False)
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(s)) as c:
        ctx = c.app.state.ctx
        ctx.get_chat_model = lambda role="default": _proposed_model()  # noqa: ARG005
        user = UserId(f"u-it-evapi-{uuid.uuid4().hex[:8]}")
        files = {
            "memory/topics/atlas.md": render_document(
                {"doc_id": "d-atlas", "type": "topic", "slug": "atlas"}, _ATLAS_BODY
            )
        }
        await ctx.canonical.commit_patch(user, files, message="seed base")
        try:
            yield c, ctx, user
        finally:
            await ctx.store.delete_user(user)


async def _drain(ctx, user):
    await drain_user(ctx, ScriptedChatModel(turns=[]), None, user)


async def test_trigger_review_adopt_full_cycle(env):
    client, ctx, user = env
    base = f"/v1/users/{user}"

    # /skill before any evolve — base templates, no products family.
    r = await client.get(f"{base}/skill")
    assert r.status_code == 200
    skill0 = r.json()
    assert "memory/products/{slug}.md" not in skill0["path_templates"]
    assert skill0["base_version"]
    # skill declares the §5强/中/弱 claim-prefix vocabulary — the UI's generic badge vocabulary.
    assert [x["label"] for x in skill0["claim_labels"]] == ["firm", "forming", "loose"]
    assert all(
        {"label", "name", "description", "tier"} <= x.keys() for x in skill0["claim_labels"]
    )

    # manual trigger → queued; a second trigger is 409 (single-flight).
    r = await client.post(f"{base}/evolve")
    assert r.status_code == 200 and r.json()["job_id"]
    assert (await client.post(f"{base}/evolve")).status_code == 409

    # drain the evolve job → a draft task.
    await _drain(ctx, user)

    r = await client.get(f"{base}/evolve")
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 1 and tasks[0]["status"] == "draft"
    task_id = tasks[0]["task_id"]
    # The list row names what the task adds (derived from the stored proposal) so a timeline
    # row / schema-snapshot axis needs no per-task detail fetch.
    assert tasks[0]["families"] == ["products"]
    assert tasks[0]["path_templates"] == ["memory/products/{slug}.md"]

    # detail carries the review payload: summary, rationale, changed_files (base vs branch).
    r = await client.get(f"{base}/evolve/{task_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["families"] == ["products"]
    assert detail["path_templates"] == ["memory/products/{slug}.md"]
    assert detail["summary"]["moved_claims"] == 2
    assert "topics" in detail["rationale"] or detail["rationale"]
    changed = {c["path"] for c in detail["changed_files"]}
    assert "memory/products/atlas.md" in changed  # new on the branch
    assert "memory/topics/atlas.md" in changed  # emptied on the branch

    # adopt → 202 accepted (queued); drain runs the merge.
    r = await client.post(f"{base}/evolve/{task_id}/adopt")
    assert r.status_code == 202 and r.json()["job_id"]
    await _drain(ctx, user)

    # task decided adopted; changed_files degrades to summary-only (branch gone).
    r = await client.get(f"{base}/evolve/{task_id}")
    assert r.json()["status"] == "adopted"
    assert r.json()["changed_files"] == []

    # a second adopt is 409 (not a draft anymore).
    assert (await client.post(f"{base}/evolve/{task_id}/adopt")).status_code == 409

    # /skill now composes the evolved products pack.
    r = await client.get(f"{base}/skill")
    skill1 = r.json()
    assert "memory/products/{slug}.md" in skill1["path_templates"]
    assert any(p["origin"] == "evolved" for p in skill1["packs"])
    # the evolved-composed skill still declares the same vocabulary (packs are additive).
    assert [x["label"] for x in skill1["claim_labels"]] == ["firm", "forming", "loose"]


async def test_drop_discards_draft(env):
    client, ctx, user = env
    base = f"/v1/users/{user}"
    await client.post(f"{base}/evolve")
    await _drain(ctx, user)
    task_id = (await client.get(f"{base}/evolve")).json()[0]["task_id"]

    r = await client.post(f"{base}/evolve/{task_id}/drop")
    assert r.status_code == 200 and r.json()["dropped"] is True
    assert (await client.get(f"{base}/evolve/{task_id}")).json()["status"] == "dropped"
    # branch gone; a second drop is 409.
    assert (await client.post(f"{base}/evolve/{task_id}/drop")).status_code == 409


async def test_list_lazily_expires_stale_draft(env):
    client, ctx, user = env
    base = f"/v1/users/{user}"
    await client.post(f"{base}/evolve")
    await _drain(ctx, user)
    task_id = (await client.get(f"{base}/evolve")).json()[0]["task_id"]
    branch = f"evolve/{task_id}"
    assert await ctx.canonical.branch_head(user, branch) is not None

    # Any positive age now exceeds a zero TTL → the next read expires the draft.
    ctx.settings.evolve_draft_ttl_hours = 0.0
    tasks = (await client.get(f"{base}/evolve")).json()
    assert tasks[0]["status"] == "expired"
    # its branch was deleted as part of the lazy expiry.
    assert await ctx.canonical.branch_head(user, branch) is None
