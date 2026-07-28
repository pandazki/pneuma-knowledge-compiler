"""Integration fixtures. Each fixture probes its middleware and skips (only)
when unreachable — the sole sanctioned skip reason (M1 discipline)."""

from __future__ import annotations

import asyncio
import socket
import uuid
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.meilisearch import MeiliLexicalIndex
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.adapters.qdrant import QdrantVectorIndex
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_embeddings


def _port_open(host: str | None, port: int | None) -> bool:
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _hostport(url: str, default_port: int) -> tuple[str | None, int | None]:
    parsed = urlparse(url if "://" in url else f"//{url}")
    return parsed.hostname, parsed.port or default_port


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


# Test users all carry one of these id prefixes; the teardown reaps them from every
# reachable store so integration runs don't accumulate users in /v1/users (test hygiene).
_TEST_USER_PREFIXES = ("u-it-", "u-e2e-", "u-501-", "u-x")


def _is_test_user(uid: str) -> bool:
    return any(uid == p or uid.startswith(p) for p in _TEST_USER_PREFIXES)


async def _reap(settings: Settings) -> None:
    """The actual reap, on its own event loop (see the fixture below)."""
    store = PostgresStore(settings.pg_dsn)
    await store.open()
    meili = None
    qdrant = None
    try:
        await store.apply_schema()
        users = [UserId(u) for u in await store.list_users() if _is_test_user(u)]
        if not users:
            return

        m_host, m_port = _hostport(settings.meili_url, 7700)
        if _port_open(m_host, m_port):
            meili = MeiliLexicalIndex(settings.meili_url, settings.meili_key)

        q_host, q_port = _hostport(settings.qdrant_url, 6333)
        if _port_open(q_host, q_port):
            dim = len(await build_embeddings(settings).aembed_query("probe"))
            qdrant = QdrantVectorIndex(
                settings.qdrant_url, dim, collection=settings.qdrant_collection
            )
            await qdrant.ensure_collection()

        for uid in users:
            await store.delete_user(uid)
            if meili is not None:
                await meili.delete_user(uid)
            if qdrant is not None:
                await qdrant.delete_user(uid)
    finally:
        await store.aclose()
        if meili is not None:
            await meili.aclose()
        if qdrant is not None:
            await qdrant.aclose()


@pytest.fixture(scope="session", autouse=True)
def _reap_test_users(settings: Settings):
    """Session-end cleanup of test-created user data (PG rows, Meili index, Qdrant
    points). Best-effort and reachability-guarded: an unreachable store is skipped, the
    same discipline as the per-store fixtures.

    Deliberately a SYNC session fixture that spins its own loop with `asyncio.run`: the
    per-test loop is function-scoped, so a session-scoped async fixture would have to
    hold a session-scoped loop that no test shares. The reap owns short-lived clients
    that are created and closed entirely inside that one loop."""
    yield
    pg_host, pg_port = _hostport(settings.pg_dsn, 5432)
    if not _port_open(pg_host, pg_port):
        return  # PG is the user directory; without it there is nothing to enumerate
    asyncio.run(_reap(settings))


@pytest.fixture
def user() -> UserId:
    return UserId(f"u-it-{uuid.uuid4().hex[:12]}")


@pytest.fixture
async def pg_store(settings: Settings):
    host, port = _hostport(settings.pg_dsn, 5432)
    if not _port_open(host, port):
        pytest.skip(f"postgres unreachable at {host}:{port}")
    store = PostgresStore(settings.pg_dsn)
    await store.open()
    await store.apply_schema()
    yield store
    await store.aclose()


@pytest.fixture
async def meili(settings: Settings):
    host, port = _hostport(settings.meili_url, 7700)
    if not _port_open(host, port):
        pytest.skip(f"meilisearch unreachable at {host}:{port}")
    index = MeiliLexicalIndex(settings.meili_url, settings.meili_key)
    yield index
    await index.aclose()


@pytest.fixture
def embeddings(settings: Settings):
    return build_embeddings(settings)


@pytest.fixture
async def qdrant(settings: Settings, embeddings):
    host, port = _hostport(settings.qdrant_url, 6333)
    if not _port_open(host, port):
        pytest.skip(f"qdrant unreachable at {host}:{port}")
    dim = len(await embeddings.aembed_query("probe"))
    index = QdrantVectorIndex(
        settings.qdrant_url, dim, collection=settings.qdrant_collection
    )
    await index.ensure_collection()
    yield index
    await index.aclose()
