"""Infrastructure jitter does not take the service down.

The night this was written a Postgres backend crashed, the postmaster reset every
connection, and ten minutes later the worker drew one of the dead connections its pool had
kept. The error ended the worker task; the engine, which stops both halves when either
ends, took the API down with it, and the queue stood still until a person restarted it.

Pinned here, keyless: the classifier that says which failures are an outage; a drain that
waits one out and puts back what it interrupted — neither losing a job nor running one
twice; an engine that restarts its worker instead of exiting; an API that answers 503
meanwhile; a pool that checks what it hands out and names every connection by process role.
The same outage against a real Postgres restart is
`integration/test_worker_survives_pg_restart.py`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import botocore.exceptions
import httpx
import psycopg
import psycopg.errors
import pytest
from fastapi.testclient import TestClient
from meilisearch_python_sdk.errors import MeilisearchCommunicationError
from psycopg_pool import AsyncConnectionPool, PoolClosed, PoolTimeout
from qdrant_client.http.exceptions import ResponseHandlingException

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service import engine_process, wiring
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.api import app as app_module
from pneuma_knowledge_service.infra_faults import infrastructure_fault
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker

from test_engine_process import engine  # noqa: F401 — the engine fixture, reused as is

USER = UserId("u-outage")
DROPPED = "consuming input failed: server closed the connection unexpectedly"
REFUSED = "[Errno 61] Connection refused"


# ───────────────────────────────────────────────────────────── which failures are an outage


@pytest.mark.parametrize(
    "exc,kind,reason",
    [
        (psycopg.OperationalError(DROPPED), "postgres", DROPPED),
        (PoolTimeout("couldn't get a connection after 30.00 sec"), "postgres", "couldn't get"),
        (
            psycopg.errors.AdminShutdown("terminating connection due to administrator command"),
            "postgres", "terminating connection",
        ),
        (psycopg.errors.CannotConnectNow("the database system is starting up"), "postgres", "starting up"),
        (psycopg.InterfaceError("the connection is lost"), "postgres", "the connection is lost"),
        (ResponseHandlingException(httpx.ConnectError(REFUSED)), "qdrant", REFUSED),
        (MeilisearchCommunicationError("All connection attempts failed"), "meilisearch", "All connection attempts failed"),
        (
            botocore.exceptions.EndpointConnectionError(endpoint_url="http://127.0.0.1:19000/media"),
            "s3", "Could not connect to the endpoint URL",
        ),
        (botocore.exceptions.ReadTimeoutError(endpoint_url="http://127.0.0.1:19000/media"), "s3", "Read timeout"),
    ],
)
def test_an_outage_is_named_by_the_service_that_went_away(exc, kind, reason):
    fault = infrastructure_fault(exc)
    assert fault is not None and fault.kind == kind
    assert reason in fault.reason and "\n" not in fault.reason


@pytest.mark.parametrize(
    "exc",
    [
        psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
        psycopg.errors.DeadlockDetected("deadlock detected"),
        psycopg.errors.LockNotAvailable("could not obtain lock"),
        psycopg.errors.UniqueViolation("duplicate key value"),
        PoolClosed("the pool 'pool-1' is already closed"),
        ResponseHandlingException(ValueError("1 validation error for CollectionInfo")),
        RuntimeError("worker startup failed"),
        ValueError("a payload nobody can compile"),
    ],
)
def test_an_answer_about_the_work_is_not_an_outage(exc):
    """A statement timeout, a deadlock, a duplicate key — the server answered, about the
    work. Retrying those forever would be the bug, so they keep the path they always had."""
    assert infrastructure_fault(exc) is None


def test_an_error_raised_from_a_dropped_connection_is_still_the_outage():
    try:
        try:
            raise psycopg.OperationalError(DROPPED)
        except psycopg.OperationalError as exc:
            raise RuntimeError("could not record the job") from exc
    except RuntimeError as wrapped:
        assert infrastructure_fault(wrapped).kind == "postgres"
    # A second failure while handling the first is the one that decides.
    try:
        try:
            raise psycopg.OperationalError(DROPPED)
        except psycopg.OperationalError:
            raise ValueError("a bug in the handler")  # noqa: B904 — the implicit context is the point
    except ValueError as second:
        assert infrastructure_fault(second) is None


# ─────────────────────────────────────────────────────── the drain waits an outage out


def worker_settings(**kwargs) -> Settings:
    """Every model role stated, so a deployment's `.env` cannot decide a test."""
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
    }
    return Settings(_env_file=None, **{**base, **kwargs})


class FlakyQueue(InMemoryJobQueue):
    """The in-memory queue, with a database that goes away when the test says so.

    It keeps a completion the outage swallowed exactly as `PostgresStore` does
    (`unwritten_completions`), so the drain's recovery is exercised against the contract the
    real store offers; that store's side of it is pinned below against a fake pool."""

    def __init__(self) -> None:
        super().__init__()
        self.claim_failures = 0
        self.claim_lands = False  # the claim's UPDATE landed before the connection went
        self.complete_failures = 0
        self.down = 0  # probes that still find the database away
        self.pings = 0
        self.unwritten_completions: dict[tuple[str, str], dict] = {}

    async def list_users(self) -> list[str]:
        return [str(USER)]

    async def claim_next(self, user_id, **kwargs):  # noqa: ANN001
        if self.claim_failures:
            self.claim_failures -= 1
            exc = psycopg.OperationalError(DROPPED)
            if self.claim_lands:
                job = await super().claim_next(user_id, **kwargs)
                if job is not None:
                    exc.unsettled_claim = (str(user_id), job.job_id)
            raise exc
        return await super().claim_next(user_id, **kwargs)

    async def complete(self, user_id, job_id, **fields):  # noqa: ANN001
        if self.complete_failures:
            self.complete_failures -= 1
            self.unwritten_completions[(str(user_id), job_id)] = fields
            raise psycopg.OperationalError(DROPPED)
        await super().complete(user_id, job_id, **fields)

    async def write_unwritten_completions(self) -> int:
        written = 0
        for (uid, job_id), fields in list(self.unwritten_completions.items()):
            await super().complete(UserId(uid), job_id, **fields)
            del self.unwritten_completions[(uid, job_id)]
            written += 1
        return written

    async def ping(self) -> None:
        self.pings += 1
        if self.down:
            self.down -= 1
            raise psycopg.OperationalError("connection to server at 127.0.0.1 failed: Connection refused")


class Ctx:
    def __init__(self, store, *, vectors=None) -> None:  # noqa: ANN001
        self.settings = worker_settings()
        self.store = store
        self.vectors = vectors
        self.lexical = None
        self.media = None

    @property
    def compile_executor(self):
        return wiring.executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_START_S", 0.01)
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_MAX_S", 0.02)
    monkeypatch.setattr(compile_worker, "IDLE_SWEEP_S", 0.01)
    compile_worker._INFRA_STRIKES.clear()
    yield
    compile_worker._INFRA_STRIKES.clear()


def index_body(monkeypatch, fail=lambda job, attempt: None) -> list[str]:  # noqa: ANN001
    """Stub the index job's body: record each run, raise what `fail` says, else complete."""
    runs: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)
        exc = fail(job, runs.count(job.job_id))
        if exc is not None:
            raise exc
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    return runs


async def drain_until_done(ctx, *job_ids: str, timeout: float = 5.0) -> None:  # noqa: ANN001
    """Run the worker's sweep loop until every named job is done, then stop it. A loop that
    exits on its own is a failure surfaced as its exception."""
    task = asyncio.create_task(compile_worker.drain_forever(ctx, None))
    try:
        async with asyncio.timeout(timeout):
            while True:
                if task.done():
                    await task
                    pytest.fail("the drain returned on its own")
                rows = {r["job_id"]: r["status"] for r in await ctx.store.list_jobs(USER)}
                if all(rows.get(j) == "done" for j in job_ids):
                    return
                await asyncio.sleep(0.005)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def outcomes(store: FlakyQueue) -> list[tuple[str, bool]]:
    return [(r["job_id"], r["ok"]) for r in store.completed]


async def test_the_drain_waits_out_a_database_that_went_away_at_the_claim(monkeypatch, fast, capsys):
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    b = await store.enqueue(USER, "index", {})
    runs = index_body(monkeypatch)
    store.claim_failures, store.down = 1, 2

    await drain_until_done(Ctx(store), a, b)

    assert runs == [a, b]
    assert outcomes(store) == [(a, True), (b, True)]
    assert store.pings == 3, "the drain resumed before the database answered"
    out = capsys.readouterr().out
    assert out.count("infrastructure unavailable") == 1, "one outage, one line"
    assert (
        f"[compile-worker] infrastructure unavailable (postgres: {DROPPED}); retrying in 0.01s"
        in out
    )
    assert "[compile-worker] infrastructure back after " in out


async def test_a_claim_that_landed_as_the_connection_dropped_is_put_back_not_orphaned(
    monkeypatch, fast, capsys
):
    """Without the recovery the row would sit `claimed` by a body that never runs it, and
    the per-user single-in-flight rule would refuse that tenant everything until a restart."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    runs = index_body(monkeypatch)
    store.claim_failures, store.claim_lands = 1, True

    await drain_until_done(Ctx(store), a)

    assert runs == [a]
    assert outcomes(store) == [(a, True)]
    assert f"(job {a} requeued)" in capsys.readouterr().out


async def test_work_that_finished_as_the_database_dropped_is_recorded_not_run_again(
    monkeypatch, fast, capsys
):
    """The job's work was done; only its last row did not land. Running it a second time
    would be the double run — the kept completion is written instead."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    b = await store.enqueue(USER, "index", {})
    runs = index_body(monkeypatch)
    store.complete_failures = 1

    await drain_until_done(Ctx(store), a, b)

    assert runs == [a, b], "a job whose work was done was run again"
    assert outcomes(store) == [(a, True), (b, True)]
    assert "(1 completion(s) written)" in capsys.readouterr().out


async def test_a_job_the_vector_store_dropped_under_comes_back_instead_of_failing(
    monkeypatch, fast, capsys
):
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    vectors = SimpleNamespace(
        ping=AsyncMock(side_effect=[ResponseHandlingException(httpx.ConnectError(REFUSED)), None])
    )
    runs = index_body(
        monkeypatch,
        fail=lambda job, attempt: (
            ResponseHandlingException(httpx.ConnectError(REFUSED)) if attempt == 1 else None
        ),
    )

    await drain_until_done(Ctx(store, vectors=vectors), a)

    assert runs == [a, a]
    assert outcomes(store) == [(a, True)], "an outage was recorded as the job's failure"
    assert vectors.ping.await_count == 2
    out = capsys.readouterr().out
    assert f"infrastructure unavailable (qdrant: {REFUSED}); retrying in 0.01s" in out
    assert f"(job {a} requeued)" in out


async def test_an_error_that_is_transient_only_in_name_fails_the_job_after_the_bound(
    monkeypatch, fast
):
    """Every probe answers and the same job meets the same "transient" error every time:
    that is not an outage. After the bound it is failed like any other error, and the rest
    of the queue drains."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    b = await store.enqueue(USER, "index", {})
    runs = index_body(
        monkeypatch,
        fail=lambda job, attempt: psycopg.OperationalError(DROPPED) if job.job_id == a else None,
    )

    await drain_until_done(Ctx(store), a, b)

    assert runs.count(a) == compile_worker.INFRA_JOB_INTERRUPTIONS + 1
    assert outcomes(store) == [(a, False), (b, True)]
    assert store.completed[0]["detail"] == f"worker error: {DROPPED}"


async def test_any_other_error_still_stops_the_drain(monkeypatch, fast):
    store = FlakyQueue()
    await store.enqueue(USER, "index", {})

    async def broken(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("the claim query is wrong")

    monkeypatch.setattr(store, "claim_next", broken)
    with pytest.raises(RuntimeError, match="the claim query is wrong"):
        await asyncio.wait_for(compile_worker.drain_forever(Ctx(store), None), timeout=2)


# ─────────────────────────────────────────────── the engine restarts its worker in place


async def test_a_worker_that_met_an_outage_is_restarted_and_the_api_keeps_serving(
    engine, monkeypatch, capsys  # noqa: F811 — the imported fixture
):
    monkeypatch.setattr(engine_process, "WORKER_RESTART_START_S", 0.01)
    roles: list[str | None] = []

    async def worker(settings):  # noqa: ANN001
        roles.append(wiring.CONNECTION_ROLE.get())
        if len(roles) == 1:
            raise psycopg.OperationalError("connection to server at 127.0.0.1 failed: Connection refused")
        engine.worker_started.set()
        await asyncio.Event().wait()

    engine.worker.side_effect = worker
    task = asyncio.create_task(engine_process.run_engine(Settings(_env_file=None), port=18004))
    try:
        await asyncio.wait_for(engine.worker_started.wait(), timeout=2)
        assert not task.done(), "the engine exited because its worker met an outage"
        assert not engine.servers[0].should_exit, "the API was told to stop"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    assert roles == ["pkc-engine-worker", "pkc-engine-worker"]
    out = capsys.readouterr().out
    assert out.count("[engine] worker stopped") == 1
    assert (
        "[engine] worker stopped: infrastructure unavailable (postgres: connection to server "
        "at 127.0.0.1 failed: Connection refused); restarting in 0.01s"
    ) in out


async def test_the_engine_names_its_api_and_worker_connections_apart(engine, monkeypatch):  # noqa: F811
    roles: dict[str, str] = {}
    real = engine.build_context

    async def api_context(settings):  # noqa: ANN001
        roles["api"] = wiring.connection_role()
        return await real(settings)

    async def worker(settings):  # noqa: ANN001
        roles["worker"] = wiring.connection_role()
        engine.worker_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(app_module, "build_context", api_context)
    engine.worker.side_effect = worker
    task = asyncio.create_task(engine_process.run_engine(Settings(_env_file=None), port=18005))
    try:
        await asyncio.wait_for(engine.worker_started.wait(), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert roles == {"api": "pkc-engine-api", "worker": "pkc-engine-worker"}


# ─────────────────────────────────────────────── the API answers 503 during an outage


class Users:
    def __init__(self, *failures: Exception) -> None:
        self.failures = list(failures)

    async def list_users(self) -> list[str]:
        if self.failures:
            raise self.failures.pop(0)
        return ["u-a"]


def _client(store) -> TestClient:  # noqa: ANN001
    app = app_module.create_app(Settings(_env_file=None))
    app.state.ctx = SimpleNamespace(store=store)
    return TestClient(app, raise_server_exceptions=False)


def test_a_request_during_an_outage_is_a_short_503_and_the_next_one_is_served():
    client = _client(Users(psycopg.OperationalError(DROPPED)))
    response = client.get("/v1/users")
    assert response.status_code == 503
    assert response.json() == {
        "detail": f"infrastructure unavailable (postgres: {DROPPED})",
        "code": "infrastructure_unavailable",
    }
    assert response.headers["retry-after"] == "5"
    # Same process, same lifespan, same context: the next request is simply served.
    again = client.get("/v1/users")
    assert again.status_code == 200 and again.json() == ["u-a"]


def test_a_database_error_that_is_not_an_outage_is_not_dressed_up_as_one():
    client = _client(Users(psycopg.errors.QueryCanceled("canceling statement due to statement timeout")))
    assert client.get("/v1/users").status_code == 500


# ───────────────────────────────── the pool hands out live connections, each named


DSN = "postgresql://pkc@127.0.0.1:1/pkc"


def test_the_pool_checks_every_connection_before_handing_it_out_and_names_it(monkeypatch):
    monkeypatch.delenv("PGAPPNAME", raising=False)
    store = PostgresStore(DSN, application_name="pkc-engine-worker")
    assert store._pool._check is AsyncConnectionPool.check_connection
    assert store._pool.kwargs == {"application_name": "pkc-engine-worker"}
    assert PostgresStore(DSN)._pool._check is AsyncConnectionPool.check_connection


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://pkc@127.0.0.1:1/pkc?application_name=ops-console",
        "host=127.0.0.1 port=1 dbname=pkc application_name=ops-console",
    ],
)
def test_a_name_the_operator_wrote_into_the_dsn_is_never_overridden(dsn, monkeypatch):
    monkeypatch.delenv("PGAPPNAME", raising=False)
    store = PostgresStore(dsn, application_name="pkc-engine-api")
    assert store.application_name is None and not store._pool.kwargs


def test_a_name_the_operator_set_through_libpq_is_never_overridden(monkeypatch):
    monkeypatch.setenv("PGAPPNAME", "ops-console")
    assert not PostgresStore(DSN, application_name="pkc-engine-api")._pool.kwargs


class _Stop(Exception):
    """Raised by a stand-in once it has seen what it was asked to record."""


async def test_every_context_names_its_connections_by_process_role(monkeypatch):
    names: list[str | None] = []

    def store(dsn, **kwargs):  # noqa: ANN001, ANN003
        names.append(kwargs.get("application_name"))
        raise _Stop

    monkeypatch.setattr(wiring, "PostgresStore", store)
    config = Settings(_env_file=None, embedding_model="fake:384")
    with pytest.raises(_Stop):
        await wiring.build_context(config)
    with wiring.connection_role_as("pkc-engine-worker"):
        with pytest.raises(_Stop):
            await wiring.build_context(config)
    with pytest.raises(_Stop):
        await wiring.build_context(config, application_name="pkc-cli:draft")
    assert names == ["pkc-service", "pkc-engine-worker", "pkc-cli:draft"]


async def test_the_standalone_worker_and_api_name_themselves(monkeypatch):
    seen: list[str] = []

    async def build(settings, **_kwargs):  # noqa: ANN001, ANN003
        seen.append(wiring.connection_role())
        raise _Stop

    monkeypatch.setattr(compile_worker, "build_context", build)
    with pytest.raises(_Stop):
        await compile_worker.run_forever(Settings(_env_file=None))
    monkeypatch.setattr(app_module, "build_context", build)
    app = app_module.create_app(Settings(_env_file=None))
    with pytest.raises(_Stop):
        async with app.router.lifespan_context(app):
            pass
    assert seen == ["pkc-worker", "pkc-api"]


async def test_a_pkc_command_names_its_connections_by_command_family(monkeypatch):
    from pneuma_knowledge_service import cli

    seen: list[str | None] = []

    async def build(settings, **kwargs):  # noqa: ANN001, ANN003
        seen.append(kwargs.get("application_name"))
        raise _Stop

    monkeypatch.setattr(wiring, "build_context", build)
    args = cli.build_parser().parse_args(["--user", "u-x", "jobs"])
    with pytest.raises(_Stop):
        await cli._run(args, (), cli.build_parser)
    assert seen == ["pkc-cli:jobs"]


# ─────────────────────────── the store keeps what an outage swallowed, and names its claim


class _Cursor:
    def __init__(self, row=None) -> None:  # noqa: ANN001
        self.row = row
        self.rowcount = 1

    async def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, script: list) -> None:
        self.script = script
        self.sent: list[tuple[str, tuple]] = []

    async def execute(self, sql, params=()):  # noqa: ANN001
        self.sent.append((sql, tuple(params)))
        step = self.script.pop(0) if self.script else None
        if isinstance(step, BaseException):
            raise step
        return step if step is not None else _Cursor()

    @asynccontextmanager
    async def transaction(self):
        yield


class _Pool:
    def __init__(self, *script) -> None:  # noqa: ANN002
        self.conn = _Conn(list(script))

    @asynccontextmanager
    async def connection(self, timeout=None):  # noqa: ANN001
        yield self.conn


async def test_a_completion_the_outage_swallowed_is_kept_and_written_once_the_database_is_back():
    store = PostgresStore(DSN)
    store._pool = _Pool(psycopg.OperationalError(DROPPED))
    with pytest.raises(psycopg.OperationalError):
        await store.complete(USER, "job-1", ok=True, detail="indexed")
    assert list(store.unwritten_completions) == [(str(USER), "job-1")]

    assert await store.write_unwritten_completions() == 1
    sql, params = store._pool.conn.sent[-1]
    assert sql.startswith("UPDATE compile_jobs SET status = 'done'")
    assert "indexed" in params and "job-1" in params and str(USER) in params
    assert store.unwritten_completions == {}


async def test_a_completion_refused_for_any_other_reason_is_not_kept():
    store = PostgresStore(DSN)
    store._pool = _Pool(psycopg.errors.QueryCanceled("canceling statement due to statement timeout"))
    with pytest.raises(psycopg.errors.QueryCanceled):
        await store.complete(USER, "job-1", ok=True, detail="indexed")
    assert store.unwritten_completions == {}


async def test_a_claim_whose_commit_was_lost_names_the_job_it_may_now_hold():
    store = PostgresStore(DSN)
    store._pool = _Pool(
        _Cursor((True,)),  # the draft lock was free
        _Cursor(),  # the per-user claim lock
        _Cursor(("job-9", "index", {}, None)),  # the row it chose
        psycopg.OperationalError(DROPPED),  # and the connection went with its UPDATE
    )
    with pytest.raises(psycopg.OperationalError) as caught:
        await store.claim_next(USER)
    assert caught.value.unsettled_claim == (str(USER), "job-9")
