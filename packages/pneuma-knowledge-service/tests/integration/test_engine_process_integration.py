"""One event loop serves HTTP and runs the worker with real, cleanly closed middleware."""

import asyncio
import socket
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import httpx
import pytest

from pneuma_knowledge_service import engine_process, wiring
from pneuma_knowledge_service.api import app as app_module
from pneuma_knowledge_service.workers import compile_worker


async def test_engine_health_and_cancellation(settings, tmp_path, monkeypatch, caplog, recwarn):
    for url, default_port in (
        (settings.pg_dsn, 5432), (settings.qdrant_url, 6333), (settings.meili_url, 7700)
    ):
        parsed = urlparse(url)
        try:
            with socket.create_connection((parsed.hostname, parsed.port or default_port), timeout=1.5):
                pass
        except OSError:
            pytest.skip("middleware unreachable")

    settings = settings.model_copy(update={
        "canonical_root": str(tmp_path / "canonical"),
        "llm_model_compile": "agent:codex",
        "agent_unattended": False,
        "agent_probe_on_start": False,
        "components": "",
    })
    # Exercise real worker startup and idle polling without claiming a live tenant's jobs.
    monkeypatch.setattr(compile_worker, "requeue_orphaned_jobs", AsyncMock(return_value=0))
    monkeypatch.setattr(compile_worker, "_users_with_jobs", AsyncMock(return_value=[]))
    contexts = []
    worker_ready = asyncio.Event()

    async def build_context(passed_settings):
        assert passed_settings is settings
        ctx = await wiring.build_context(passed_settings)
        contexts.append(ctx)
        if len(contexts) == 2:
            worker_ready.set()
        return ctx

    monkeypatch.setattr(app_module, "build_context", build_context)
    monkeypatch.setattr(compile_worker, "build_context", build_context)
    closed = []
    original_close = wiring.AppContext.aclose

    async def close_context(ctx):
        await original_close(ctx)
        closed.append(ctx)

    monkeypatch.setattr(wiring.AppContext, "aclose", close_context)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    task = asyncio.create_task(engine_process.run_engine(settings, port=port))
    try:
        async with asyncio.timeout(15):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                while True:
                    if task.done():
                        await task
                        pytest.fail("engine exited before serving healthz")
                    try:
                        response = await client.get("/healthz")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
            await worker_ready.wait()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    assert len(contexts) == len(closed) == 2
    assert {id(ctx) for ctx in contexts} == {id(ctx) for ctx in closed}
    assert not [warning for warning in recwarn if issubclass(warning.category, ResourceWarning)]
    assert not [record for record in caplog.records if "unclosed" in record.getMessage().lower()]
