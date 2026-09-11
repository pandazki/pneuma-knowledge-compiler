"""Qdrant stopped under an episodes job's vector write: the claim comes back and the queue
keeps moving, in the same process, which never exits.

This is the live leak, reproduced (`workers/compile_worker._IN_FLIGHT`). A derived-lane
episodes job's round ended cleanly; the work that FOLLOWS the round — the source's L2 vector
write — met a Qdrant that had gone away. The job stayed `claimed`, so its lane could claim
nothing more, and because every compile waits on its own source's derived work, the canonical
lane idled behind it: 542 jobs pending, nothing finished for half an hour, until a person
restarted the engine.

It stops and starts the repository's own compose Qdrant (`infra/docker-compose.yml`, service
`qdrant`) and nothing else, and only when the configured URL points at that container's
published port. Anything else — no docker, the stack not running, a URL aimed elsewhere —
skips with the reason.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.job_lanes import DERIVED_LANE
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


def _compose_qdrant(url: str) -> str:
    """The compose Qdrant container id, when the URL is aimed at it; "" otherwise."""
    if shutil.which("docker") is None:
        return ""
    try:
        container = _compose("ps", "-q", "qdrant")
        published = _compose("port", "qdrant", "6333")
    except (OSError, subprocess.SubprocessError):
        return ""
    if not container or not published:
        return ""
    _host, port = _hostport(url, 6333)
    return container if published.rsplit(":", 1)[-1] == str(port) else ""


async def _statuses(store: PostgresStore, user, *job_ids: str) -> list[str]:  # noqa: ANN001
    try:
        return [getattr(await store.get_job(user, j), "status", "") for j in job_ids]
    except (psycopg.OperationalError, psycopg.InterfaceError):
        return []


async def test_the_worker_rides_out_a_qdrant_outage_under_an_episodes_job(
    settings, user, qdrant, monkeypatch, capsys
):
    container = _compose_qdrant(settings.qdrant_url)
    if not container:
        pytest.skip("middleware unreachable: the compose qdrant container is not running here")
    pg_host, pg_port = _hostport(settings.pg_dsn, 5432)
    store = PostgresStore(settings.pg_dsn, application_name="pkc-test-qdrant-outage")
    try:
        await store.open()
        await store.apply_schema()
    except (psycopg.OperationalError, psycopg.InterfaceError):
        pytest.skip(f"middleware unreachable: postgres at {pg_host}:{pg_port}")

    vectors = qdrant
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_START_S", 0.5)
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_MAX_S", 2.0)
    monkeypatch.setattr(compile_worker, "IDLE_SWEEP_S", 0.1)
    compile_worker._INFRA_STRIKES.clear()
    compile_worker._IN_FLIGHT.clear()

    stopped = asyncio.Event()
    runs: list[str] = []

    async def round_and_its_tail(ctx, user_id, job):  # noqa: ANN001
        """One episodes job: the round (which ends cleanly), then its vector write."""
        runs.append(job.job_id)
        if len(runs) == 1:
            await stopped.wait()
        # `cli/episodes.cmd_finish`: the source's L2 is rewritten before the job is completed.
        await ctx.vectors.delete_source_chunks(user_id, "s-outage")
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="episodes: 0")

    monkeypatch.setattr(compile_worker, "process_agent_job", round_and_its_tail)
    monkeypatch.setattr(
        "pneuma_knowledge_service.cli.episodes.split_oversized", AsyncMock(return_value=None)
    )

    first = await store.enqueue(user, "episodes", {"source_id": "s-outage"})
    second = await store.enqueue(user, "episodes", {"source_id": "s-outage-2"})
    config = settings.model_copy(update={
        # This tenant only: the drain never looks at any other row on the shared database.
        "worker_tenants": str(user),
        "llm_model_compile": "agent:codex",  # episodes are an agent round's job
        "llm_model_evolve": "openrouter:x/evolve",
        "worker_selfheal_s": 0,  # the recovery under test is the drain's own, not the sweep's
    })
    ctx = SimpleNamespace(
        settings=config, store=store, vectors=vectors, lexical=None, media=None,
        compile_executor=executor_for(config, "compile"), flush_traces=AsyncMock(),
    )

    task = asyncio.create_task(compile_worker.drain_forever(ctx, None))
    try:
        async with asyncio.timeout(30):
            while not runs:
                await asyncio.sleep(0.05)
        await asyncio.to_thread(
            subprocess.run, ["docker", "stop", "-t", "5", container],
            check=True, capture_output=True, timeout=120,
        )
        stopped.set()
        # The job is now in the tail of its round with nowhere to write. Bring Qdrant back.
        await asyncio.sleep(1.0)
        await asyncio.to_thread(
            subprocess.run, ["docker", "start", container],
            check=True, capture_output=True, timeout=120,
        )
        async with asyncio.timeout(120):
            while await _statuses(store, user, first, second) != ["done", "done"]:
                if task.done():
                    await task
                    pytest.fail("the drain exited")
                await asyncio.sleep(0.2)
        assert not task.done(), "the drain exited"
    finally:
        stopped.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(
            subprocess.run, ["docker", "start", container], capture_output=True, timeout=120
        )

    try:
        assert runs == [first, first, second], "the interrupted round did not come back"
        rows = {r["job_id"]: r for r in await store.list_jobs(user)}
        assert rows[first]["ok"] is True and rows[second]["ok"] is True
        assert compile_worker.in_flight_jobs() == (), "the drain still thinks it holds a job"
        out = capsys.readouterr().out
        # Which name the outage comes back under is the client's business and varies with
        # where in the request the container went: `qdrant:` when its own wrapper carried the
        # transport error, `http:` when the transport error reached the drain bare (both are
        # `infra_faults`, and the second is the shape that used to fail the job outright).
        assert re.search(
            rf"\[compile-worker\] {DERIVED_LANE} lane: infrastructure unavailable "
            rf"\((qdrant|http): ",
            out,
        ), out
        assert f"(job {first} requeued)" in out
    finally:
        await store.aclose()
