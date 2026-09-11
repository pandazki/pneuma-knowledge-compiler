"""A Postgres restart mid-drain: the worker waits it out, puts back the job it was running,
and drains the queue afterwards — in the same process, which never exits.

This is the live failure, reproduced: a job's body holds a pooled connection, Postgres is
restarted under it, and the next statement on that connection fails the way the engine's
did (`server closed the connection unexpectedly` / `terminating connection due to
administrator command`).

It restarts the repository's own compose Postgres (`infra/docker-compose.yml`, service
`postgres`) and nothing else, and only when the configured DSN points at that container's
published port. Anything else — no docker, the stack not running, a DSN aimed elsewhere —
skips with the reason.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.wiring import executor_for
from pneuma_knowledge_service.workers import compile_worker

from conftest import _hostport

COMPOSE = Path(__file__).resolve().parents[4] / "infra" / "docker-compose.yml"


def _compose(*args: str) -> str:
    out = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), *args],
        capture_output=True, text=True, timeout=30,
    )
    return out.stdout.strip() if out.returncode == 0 else ""


def _compose_postgres(dsn: str) -> str:
    """The compose Postgres container id, when the DSN is aimed at it; "" otherwise."""
    if shutil.which("docker") is None:
        return ""
    try:
        container = _compose("ps", "-q", "postgres")
        published = _compose("port", "postgres", "5432")
    except (OSError, subprocess.SubprocessError):
        return ""
    if not container or not published:
        return ""
    _host, port = _hostport(dsn, 5432)
    return container if published.rsplit(":", 1)[-1] == str(port) else ""


async def _statuses(store: PostgresStore, user, *job_ids: str) -> list[str]:  # noqa: ANN001
    try:
        return [getattr(await store.get_job(user, j), "status", "") for j in job_ids]
    except (psycopg.OperationalError, psycopg.InterfaceError):
        return []  # the database is still coming back; ask again


async def test_the_worker_rides_out_a_postgres_restart(settings, user, monkeypatch, capsys):
    container = _compose_postgres(settings.pg_dsn)
    if not container:
        pytest.skip("middleware unreachable: the compose postgres container is not running here")

    store = PostgresStore(settings.pg_dsn, application_name="pkc-test-outage-worker")
    await store.open()
    await store.apply_schema()
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_START_S", 0.5)
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_MAX_S", 2.0)
    monkeypatch.setattr(compile_worker, "IDLE_SWEEP_S", 0.1)
    compile_worker._INFRA_STRIKES.clear()

    held = asyncio.Event()
    restarted = asyncio.Event()
    runs: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)
        if len(runs) == 1:
            # Hold one pooled connection across the restart, as the live worker did.
            async with store._pool.connection() as conn:
                held.set()
                await restarted.wait()
                await conn.execute("SELECT 1")  # the connection the restart killed
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    first = await store.enqueue(user, "index", {})
    second = await store.enqueue(user, "index", {})
    config = settings.model_copy(update={
        # This tenant only: the drain never looks at any other row on the shared database.
        "worker_tenants": str(user),
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
    })
    ctx = SimpleNamespace(
        settings=config, store=store, vectors=None, lexical=None, media=None,
        compile_executor=executor_for(config, "compile"), flush_traces=AsyncMock(),
    )

    task = asyncio.create_task(compile_worker.drain_forever(ctx, None))
    try:
        async with asyncio.timeout(30):
            await held.wait()
        await asyncio.to_thread(
            subprocess.run, ["docker", "restart", "-t", "5", container],
            check=True, capture_output=True, timeout=120,
        )
        restarted.set()
        async with asyncio.timeout(120):
            while await _statuses(store, user, first, second) != ["done", "done"]:
                if task.done():
                    await task
                    pytest.fail("the drain exited")
                await asyncio.sleep(0.2)
        assert not task.done(), "the drain exited"
    finally:
        restarted.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    try:
        assert runs == [first, first, second]
        rows = {r["job_id"]: r for r in await store.list_jobs(user)}
        assert rows[first]["ok"] is True and rows[second]["ok"] is True
        out = capsys.readouterr().out
        assert "[compile-worker] infrastructure unavailable (postgres: " in out
        assert f"(job {first} requeued)" in out
    finally:
        await store.aclose()
