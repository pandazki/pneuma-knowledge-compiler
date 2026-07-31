"""Official canonical source import API: bundle expansion and async persistence."""

import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs


def _open(url: str, default: int) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or default), timeout=1.5
        ):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            client.app = app
            yield client


@pytest.fixture
async def client():
    settings = Settings()
    if not (
        _open(settings.pg_dsn, 5432)
        and _open(settings.meili_url, 7700)
        and _open(settings.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(settings)) as value:
        yield value


async def test_official_import_expands_natural_citation_units(client):
    uid = f"u-it-official-{uuid.uuid4().hex[:10]}"
    user = UserId(uid)
    base = f"/v1/users/{uid}"
    ctx = client.app.state.ctx
    try:
        meeting = {
            "schema": "pneuma.source.meeting/v1",
            "provider": "mock",
            "meeting_id": "m-api-1",
            "title": "客户发现会议",
            "started_at": "2026-07-28T09:00:00+08:00",
            "owner_participant_ids": ["p1"],
            "participants": [
                {"participant_id": "p1", "display_name": "测试用户"},
                {"participant_id": "p2", "display_name": "陈澄"},
            ],
            "segments": [
                {
                    "segment_id": "s1",
                    "speaker_id": "p2",
                    "started_at": "2026-07-28T09:00:01+08:00",
                    "text": "先覆盖三个项目组。",
                }
            ],
        }
        response = await client.post(f"{base}/sources/import", json=meeting)
        assert response.status_code == 200, response.text
        assert response.json()["contract_schema"] == "pneuma.source.meeting/v1"
        assert len(response.json()["sources"]) == 1
        assert response.json()["sources"][0]["deduplicated"] is False
        jobs_before_dedup = len(await ctx.store.list_jobs(user))

        duplicate = await client.post(f"{base}/sources/import", json=meeting)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["sources"][0]["deduplicated"] is True
        assert len(await ctx.store.list_jobs(user)) == jobs_before_dedup

        library = {
            "schema": "pneuma.source.document-library/v1",
            "provider": "mock",
            "library_id": "v-api-1",
            "title": "工作库",
            "documents": [
                {
                    "document_id": "d1",
                    "path": "Clients/Acme.md",
                    "title": "Acme",
                    "content": "# 决策\n\n先覆盖三个项目组。",
                    "frontmatter": {"status": "active"},
                    "tags": ["client"],
                    "links": [],
                },
                {
                    "document_id": "d2",
                    "path": "Projects/Pneuma.md",
                    "title": "Pneuma",
                    "content": "# 下一步\n\n周四交方案。",
                    "frontmatter": {},
                    "tags": [],
                    "links": [],
                },
            ],
        }
        response = await client.post(f"{base}/sources/import", json=library)
        assert response.status_code == 200, response.text
        assert len(response.json()["sources"]) == 2

        listed = (await client.get(f"{base}/sources")).json()["items"]
        assert {item["kind"] for item in listed} == {"meeting", "document_library"}
        assert {item["origin"] for item in listed} == {"mock"}
        assert len(listed) == 3
        # The first import's compile job remains ahead of the second import in the
        # user-serialized queue; this helper intentionally drains index jobs only.
        assert await drain_index_jobs(ctx, user) == 1
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
