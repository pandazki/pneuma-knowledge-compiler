"""Document intake two-step API (M3b): preview (no side effects) → confirm.

Covers the three matrix strategies: contract → distill/full, novel (declared or >80k) →
card/summary, note → full/full. Runs against the live stack over an ASGI-transport client.
"""

from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings


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


CONTRACT = (
    "# 服务合同\n\n本合同约定付款条款：交付后三十日内结清全部款项。\n\n"
    "## 第五条 违约金\n\n违约金按每日万分之五计算，上限为合同总额。"
)
NOTE = "# 随手记\n\n记得周五之前把演示稿发给 程野。\n\n顺便订下周的会议室。"


async def test_preview_is_side_effect_free_and_proposes_plan(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document/preview",
        json={"title": "服务合同", "text": CONTRACT, "declared_type": "contract"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposed_plan"]["canonical_treatment"] == "distill"
    assert body["proposed_plan"]["semantic_indexing"] == "full"
    assert body["normalized"]["block_count"] >= 2
    assert body["normalized"]["section_tree"]  # heading-cut sections
    # No source was created by preview.
    assert (await client.get(f"/v1/users/{uid}/sources")).json()["items"] == []


async def test_contract_distill_full_confirm(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={"title": "服务合同", "text": CONTRACT, "declared_type": "contract"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intake_plan"]["canonical_treatment"] == "distill"
    assert body["intake_plan"]["semantic_indexing"] == "full"
    listed = (await client.get(f"/v1/users/{uid}/sources")).json()["items"]
    entry = next(s for s in listed if s["source_id"] == body["source_id"])
    assert entry["kind"] == "document"
    assert entry["digested_at"] is None  # not compiled yet (worker does that)


async def test_declared_novel_card_summary(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={"title": "长篇小说节选", "text": "第一章\n\n很久以前……", "declared_type": "novel"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["intake_plan"]["canonical_treatment"] == "card"
    assert r.json()["intake_plan"]["semantic_indexing"] == "summary"


async def test_big_reference_without_declaration_is_card_summary(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    big = "# 大部头\n\n" + ("这是一段很长的正文。" * 9000)  # >80k chars
    r = await client.post(
        f"/v1/users/{uid}/sources/document/preview",
        json={"title": "大部头", "text": big, "source_class": "reference"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["proposed_plan"]["canonical_treatment"] == "card"


async def test_note_full_full_confirm(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={"title": "随手记", "text": NOTE, "declared_type": "note"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["intake_plan"]["canonical_treatment"] == "full"
    assert r.json()["intake_plan"]["semantic_indexing"] == "full"


async def test_plan_override_is_honored(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={
            "title": "服务合同",
            "text": CONTRACT,
            "declared_type": "contract",
            "plan_override": {"canonical_treatment": "full", "semantic_indexing": "full"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["intake_plan"]["canonical_treatment"] == "full"
    assert r.json()["intake_plan"]["user_confirmed"] is True


# ------------------------------------------------------------- intake archetypes


async def test_archetypes_endpoint_lists_the_four_intents(client):
    r = await client.get("/v1/intake/archetypes")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [a["key"] for a in rows] == ["digest", "distill", "archive", "searchable"]
    distill = next(a for a in rows if a["key"] == "distill")
    assert distill["canonical_treatment"] == "distill"
    assert distill["semantic_indexing"] == "full"
    assert distill["label"] and distill["summary"] and distill["examples"]


async def test_preview_archetype_drives_plan_and_reports_itself(client):
    # A chosen archetype selects the plan regardless of content shape/genre.
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document/preview",
        json={"title": "随手记", "text": NOTE, "intake_archetype": "archive"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposed_plan"]["canonical_treatment"] == "card"
    assert body["proposed_plan"]["semantic_indexing"] == "summary"
    assert body["proposed_archetype"] == "archive"


async def test_preview_auto_reports_the_mechanical_archetype(client):
    # No archetype → mechanical propose; the response tells the UI which one it matches.
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document/preview",
        json={"title": "服务合同", "text": CONTRACT, "declared_type": "contract"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["proposed_archetype"] == "distill"


async def test_source_collection_uses_context_bound_cursor_pages(client):
    uid = f"u-it-source-page-{uuid.uuid4().hex[:8]}"
    base = f"/v1/users/{uid}"
    for title in ["Alpha brief", "Beta notes", "Alpha decision", "Gamma log", "Alpha mail"]:
        response = await client.post(
            f"{base}/sources/document",
            json={"title": title, "text": f"# {title}\n\n正文 {title}"},
        )
        assert response.status_code == 200, response.text

    first = await client.get(f"{base}/sources", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["page"]["limit"] == 2
    assert body["page"]["total"] == 5
    assert body["page"]["next_cursor"]

    second = await client.get(
        f"{base}/sources",
        params={"limit": 2, "cursor": body["page"]["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert len(body2["items"]) == 2
    assert {row["source_id"] for row in body["items"]}.isdisjoint(
        row["source_id"] for row in body2["items"]
    )

    filtered = await client.get(
        f"{base}/sources",
        params={"limit": 10, "query": "alpha"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["page"]["total"] == 3
    assert all("alpha" in row["title"].lower() for row in filtered.json()["items"])

    assert (
        await client.get(f"{base}/sources", params={"cursor": "not-a-cursor"})
    ).status_code == 422
    assert (
        await client.get(
            f"{base}/sources",
            params={"cursor": body["page"]["next_cursor"], "query": "different"},
        )
    ).status_code == 422


async def test_job_collection_uses_bounded_filtered_pages(client):
    uid = f"u-it-job-page-{uuid.uuid4().hex[:8]}"
    base = f"/v1/users/{uid}"
    store = client.app.state.ctx.store
    job_ids = [
        await store.enqueue(
            uid,
            "index" if index % 2 == 0 else "compile",
            {"source_ids": [f"sid-{index}"]},
        )
        for index in range(7)
    ]
    await store.complete(uid, job_ids[0], ok=True)
    await store.complete(uid, job_ids[1], ok=False, detail="expected test failure")

    first = await client.get(f"{base}/jobs", params={"limit": 3})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 3
    assert body["page"]["total"] == 7
    assert body["page"]["next_cursor"]

    second = await client.get(
        f"{base}/jobs",
        params={"limit": 3, "cursor": body["page"]["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert {row["job_id"] for row in body["items"]}.isdisjoint(
        row["job_id"] for row in second.json()["items"]
    )

    queued_index = await client.get(
        f"{base}/jobs",
        params={"limit": 10, "status": "queued", "kind": "index"},
    )
    assert queued_index.status_code == 200, queued_index.text
    assert queued_index.json()["page"]["total"] == 3
    assert all(
        row["status"] == "queued" and row["kind"] == "index"
        for row in queued_index.json()["items"]
    )


async def test_workspace_summary_counts_without_collection_payloads(client):
    uid = f"u-it-summary-{uuid.uuid4().hex[:8]}"
    base = f"/v1/users/{uid}"
    imported = await client.post(
        f"{base}/sources/document",
        json={"title": "Summary source", "text": "# Summary\n\nOne source."},
    )
    assert imported.status_code == 200, imported.text

    response = await client.get(f"{base}/summary")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sources": 1,
        "jobs": 2,
        "documents": 0,
        "claims": 0,
        "snapshots": 0,
    }


async def test_history_collection_pages_the_unified_audit_ledger(client):
    uid = f"u-it-history-{uuid.uuid4().hex[:8]}"
    base = f"/v1/users/{uid}"
    imported = await client.post(
        f"{base}/sources/document",
        json={"title": "History source", "text": "# History\n\nOne decision."},
    )
    assert imported.status_code == 200, imported.text
    source_id = imported.json()["source_id"]

    store = client.app.state.ctx.store
    compile_job = next(
        row for row in await store.list_jobs(uid) if row["kind"] == "compile"
    )
    await store.complete(uid, compile_job["job_id"], snapshot_ref="ref-history-api")
    await store.record_compile_events(
        uid,
        compile_job["job_id"],
        "ref-history-api",
        [
            {
                "type": "claim_added",
                "path": "work/products/history.md",
                "anchor": "a001",
                "after": "One decision.",
            }
        ],
    )

    first = await client.get(f"{base}/history", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["counts"] == {
        "patches": 1,
        "jobs": 2,
        "snapshots": 1,
        "total": 4,
    }
    assert len(body["items"]) == 2
    assert body["page"]["next_cursor"]

    second = await client.get(
        f"{base}/history",
        params={"limit": 2, "cursor": body["page"]["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 2
    assert {(row["kind"], row["ref"]) for row in body["items"]}.isdisjoint(
        (row["kind"], row["ref"]) for row in second.json()["items"]
    )
    assert second.json()["page"]["next_cursor"] is None
    assert (
        await client.get(f"{base}/history", params={"cursor": "not-a-cursor"})
    ).status_code == 422


async def test_ingest_archetype_selects_plan_and_confirms(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={"title": "服务合同", "text": CONTRACT, "intake_archetype": "searchable"},
    )
    assert r.status_code == 200, r.text
    plan = r.json()["intake_plan"]
    assert (plan["canonical_treatment"], plan["semantic_indexing"]) == ("none", "none")
    assert plan["user_confirmed"] is True


async def test_plan_override_wins_over_archetype(client):
    # Precedence: plan_override (raw knobs) > intake_archetype (named intent).
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document",
        json={
            "title": "服务合同",
            "text": CONTRACT,
            "intake_archetype": "searchable",
            "plan_override": {"canonical_treatment": "full", "semantic_indexing": "full"},
        },
    )
    assert r.status_code == 200, r.text
    plan = r.json()["intake_plan"]
    assert (plan["canonical_treatment"], plan["semantic_indexing"]) == ("full", "full")


async def test_unknown_archetype_is_rejected(client):
    uid = f"u-it-doc-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        f"/v1/users/{uid}/sources/document/preview",
        json={"title": "x", "text": NOTE, "intake_archetype": "nope"},
    )
    assert r.status_code == 422, r.text
