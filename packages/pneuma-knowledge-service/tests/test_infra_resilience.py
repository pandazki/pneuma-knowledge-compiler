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
from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore, InMemoryJobQueue
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.api import app as app_module
from pneuma_knowledge_service.infra_faults import infrastructure_fault
from pneuma_knowledge_service.job_lanes import DERIVED_LANE
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


def test_a_bare_transport_error_is_the_outage_even_when_no_client_wrapped_it():
    """Live, after the first fix shipped: a Qdrant blip raised `httpx.ReadError()` straight
    out — not inside the `ResponseHandlingException` this module knew to open — so it was
    read as an answer about the work. The windowed episodes job it hit was completed
    `worker error: ` (the class carries an empty message) with nothing logged anywhere. Every
    client here speaks over httpx, so a transport error is the peer being gone whoever let it
    through; which peer, a bare one does not say, and the fault says so too."""
    for exc in (httpx.ReadError(""), httpx.ConnectTimeout("timed out"), httpx.RemoteProtocolError("")):
        fault = infrastructure_fault(exc)
        assert fault is not None and fault.kind == "http"
    assert infrastructure_fault(httpx.ReadError("")).reason == "ReadError"
    # …and the exclusions above it still decide first, or stand.
    assert infrastructure_fault(ResponseHandlingException(ValueError("1 validation error"))) is None
    assert infrastructure_fault(ResponseHandlingException(httpx.ConnectError(REFUSED))).kind == "qdrant"


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
        #: Which lane's claim the failures are for. A library drains two lanes at once
        #: (`job_lanes.py`), so "the database went away at the claim" is a thing that happens
        #: to ONE of them; the jobs in these tests are `index` jobs, whose lane is the
        #: derived one, and it is that lane's wait and recovery they are about.
        self.fail_lane = DERIVED_LANE
        self.complete_failures = 0
        self.down = 0  # probes that still find the database away
        self.pings = 0
        self.unwritten_completions: dict[tuple[str, str], dict] = {}

    async def list_users(self) -> list[str]:
        return [str(USER)]

    async def claim_next(self, user_id, *, lane=None, **kwargs):  # noqa: ANN001
        if self.claim_failures and lane in (None, self.fail_lane):
            self.claim_failures -= 1
            exc = psycopg.OperationalError(DROPPED)
            if self.claim_lands:
                job = await super().claim_next(user_id, lane=lane, **kwargs)
                if job is not None:
                    exc.unsettled_claim = (str(user_id), job.job_id)
            raise exc
        return await super().claim_next(user_id, lane=lane, **kwargs)

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
    def __init__(self, store, *, vectors=None, settings=None, flush=None) -> None:  # noqa: ANN001
        self.settings = settings or worker_settings()
        self.store = store
        self.vectors = vectors
        self.lexical = None
        self.media = None
        #: What the per-job trace flush does. It runs in the drain's `finally`, AFTER the
        #: job's own body — the one place a failure carries no job id at all.
        self.flush = flush

    @property
    def compile_executor(self):
        return wiring.executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        if self.flush is not None:
            self.flush()


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_START_S", 0.01)
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_MAX_S", 0.02)
    monkeypatch.setattr(compile_worker, "IDLE_SWEEP_S", 0.01)
    compile_worker._INFRA_STRIKES.clear()
    compile_worker._IN_FLIGHT.clear()
    yield
    compile_worker._INFRA_STRIKES.clear()
    compile_worker._IN_FLIGHT.clear()


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
    """Run the worker's sweep loop until every named job is done and the drain holds nothing,
    then stop it. A loop that exits on its own is a failure surfaced as its exception."""
    task = asyncio.create_task(compile_worker.drain_forever(ctx, None))
    try:
        async with asyncio.timeout(timeout):
            while True:
                if task.done():
                    await task
                    pytest.fail("the drain returned on its own")
                rows = {r["job_id"]: r["status"] for r in await ctx.store.list_jobs(USER)}
                # Both halves: a job can be `done` while the lane that ran it is still
                # riding an outage out, and it is what that recovery DID that these tests
                # are about (`_IN_FLIGHT`).
                if all(rows.get(j) == "done" for j in job_ids) and not compile_worker.in_flight_jobs():
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
        f"[compile-worker] {DERIVED_LANE} lane: infrastructure unavailable "
        f"(postgres: {DROPPED}); retrying in 0.01s"
        in out
    )
    # Nothing was claimed when the database went: the line says so rather than saying nothing.
    assert f"[compile-worker] {DERIVED_LANE} lane: infrastructure back after " in out
    assert "resuming (no job in flight)" in out


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
    assert f"(1 completion(s) written, job {a} completed)" in capsys.readouterr().out


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
    assert (
        f"[compile-worker] {DERIVED_LANE} lane: infrastructure unavailable "
        f"(qdrant: {REFUSED}); retrying in 0.01s"
    ) in out
    assert f"(job {a} requeued)" in out


async def test_an_error_that_is_transient_only_in_name_fails_the_job_after_the_bound(
    monkeypatch, fast, caplog
):
    """Every probe answers and the same job meets the same "transient" error every time:
    that is not an outage for this job, whatever it is for the stack. After the bound the job
    is failed and the rest of the queue drains — and the row SAYS which of the two happened.

    What it said before: `worker error: qdrant_client.ResponseHandlingException`, on a live
    episodes job whose Qdrant write had in fact been interrupted three times and given up on
    at the fourth. The class of the last attempt is not the reason; the count is."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    b = await store.enqueue(USER, "index", {})
    runs = index_body(
        monkeypatch,
        fail=lambda job, attempt: psycopg.OperationalError(DROPPED) if job.job_id == a else None,
    )

    with caplog.at_level("WARNING"):
        await drain_until_done(Ctx(store), a, b)

    strikes = compile_worker.INFRA_JOB_INTERRUPTIONS + 1
    assert runs.count(a) == strikes
    assert outcomes(store) == [(a, False), (b, True)]
    said = f"infrastructure repeated: postgres ({DROPPED}) interrupted this job {strikes} times; failed"
    assert store.completed[0]["detail"] == said
    # The same words in the log, once, with the last attempt's stack still under them.
    gave_up = [r for r in caplog.records if said in r.getMessage()]
    assert len(gave_up) == 1 and gave_up[0].levelname == "WARNING" and gave_up[0].exc_info
    assert f"job {a}" in gave_up[0].getMessage() and DERIVED_LANE in gave_up[0].getMessage()


# ───────────────────────────────────── a claim is never left behind, wherever the fault was


def agent_body(monkeypatch, fail=lambda job, attempt: None) -> list[str]:  # noqa: ANN001
    """Stub one agent round: the harness runs, and then the work that FOLLOWS it happens.

    The episodes job's shape (`cli/episodes.cmd_finish`): the round ends, the manifest is
    recorded, the source's L2 vectors are rewritten, and only then is the job completed. A
    fault in that tail is the one the recovery used not to cover."""
    runs: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)  # the round itself, which ended cleanly
        exc = fail(job, runs.count(job.job_id))
        if exc is not None:
            raise exc  # …the projection/vector write after it
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="episodes: 3")

    monkeypatch.setattr(compile_worker, "process_agent_job", body)
    monkeypatch.setattr("pneuma_knowledge_service.cli.episodes.split_oversized", AsyncMock(return_value=None))
    return runs


async def test_a_fault_after_an_episodes_round_leaves_no_claim_behind(monkeypatch, fast, capsys):
    """The live leak: a derived-lane episodes job whose round finished `exit 0`, and whose
    vector write met a Qdrant that had gone away for two seconds. The job stayed `claimed`
    with its draft open, so the derived lane could claim nothing more — and because every
    compile waits on its own source's derived work, the canonical lane idled too: 542 jobs
    pending, nothing finished for half an hour, until a person restarted the engine."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "episodes", {"source_id": "s-1"})
    b = await store.enqueue(USER, "episodes", {"source_id": "s-2"})
    vectors = SimpleNamespace(ping=AsyncMock(return_value=None))
    runs = agent_body(
        monkeypatch,
        fail=lambda job, attempt: (
            ResponseHandlingException(httpx.ReadError("")) if job.job_id == a and attempt == 1
            else None
        ),
    )
    ctx = Ctx(store, vectors=vectors, settings=worker_settings(llm_model_compile="agent:codex"))

    await drain_until_done(ctx, a, b)

    assert runs == [a, a, b], "the interrupted round did not come back, or ran somebody else's job"
    assert outcomes(store) == [(a, True), (b, True)]
    assert compile_worker.in_flight_jobs() == (), "the drain still thinks it holds a job"
    assert f"(job {a} requeued)" in capsys.readouterr().out


async def test_a_bare_read_error_after_an_episodes_round_is_ridden_out_not_failed(
    monkeypatch, fast, capsys
):
    """The second half of the live leak, exactly as it was recorded: the same windowed
    episodes job came back after the restart, its round ended `exit 0`, and the vector write
    after it raised a bare `httpx.ReadError()`. It was completed `ok=False`, detail
    `worker error: `, and the queue moved on as if a judgement had been made. Now it is an
    outage: the drain waits, the job comes back, and the round is judged."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "episodes", {"source_id": "90a4", "window": {"start": 2376, "end": 2448}})
    vectors = SimpleNamespace(ping=AsyncMock(return_value=None))
    runs = agent_body(
        monkeypatch,
        fail=lambda job, attempt: httpx.ReadError("") if attempt == 1 else None,
    )
    ctx = Ctx(store, vectors=vectors, settings=worker_settings(llm_model_compile="agent:codex"))

    await drain_until_done(ctx, a)

    assert runs == [a, a]
    assert outcomes(store) == [(a, True)], "an outage was recorded as the job's judgement"
    out = capsys.readouterr().out
    assert f"[compile-worker] {DERIVED_LANE} lane: infrastructure unavailable (http: ReadError)" in out
    assert f"(job {a} requeued)" in out


async def test_a_failure_is_never_written_without_a_reason_or_a_traceback(
    monkeypatch, fast, caplog
):
    """Two shapes of the same rule. A job row holds one sentence, so that sentence must at
    least name the class when the exception carries no words; and the stack that produced it
    goes to the log, which is where an operator looks and where — the night this was written
    — there was nothing at all."""
    store = FlakyQueue()
    blank = await store.enqueue(USER, "index", {})
    spoken = await store.enqueue(USER, "index", {})
    index_body(
        monkeypatch,
        fail=lambda job, attempt: (
            ValueError() if job.job_id == blank else ValueError("a payload nobody can compile")
        ),
    )

    with caplog.at_level("ERROR"):
        await drain_until_done(Ctx(store), blank, spoken)

    details = {row["job_id"]: row["detail"] for row in store.completed}
    assert details[blank] == "worker error: ValueError"
    assert details[spoken] == "worker error: a payload nobody can compile"
    logged = [r for r in caplog.records if "job %s failed" in r.msg]
    assert [r.args[1] for r in logged] == [blank, spoken]
    assert all(r.args[0] == DERIVED_LANE and r.exc_info for r in logged), "no traceback was kept"


async def test_a_fault_that_names_no_job_still_puts_this_body_s_claim_back(
    monkeypatch, fast, capsys
):
    """What the job id must NOT depend on: the exception.

    The recovery used to read the in-flight job off `InfrastructureInterrupted`, which only
    the claim and the completion raise. A fault anywhere else — here the per-job trace flush,
    which runs after the body in the drain's own `finally` — arrived carrying nothing, so the
    recovery requeued nothing and said nothing while the claim stood. The drain now remembers
    what it claimed, so the exception's silence costs nothing."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    faults = [ResponseHandlingException(httpx.ReadError(""))]

    def flush():
        if faults:
            raise faults.pop()

    runs: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)
        if runs.count(job.job_id) > 1:
            # The second run completes; the first is the one the flush interrupted.
            await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    vectors = SimpleNamespace(ping=AsyncMock(return_value=None))

    await drain_until_done(Ctx(store, vectors=vectors, flush=flush), a)

    assert runs == [a, a]
    assert compile_worker.in_flight_jobs() == ()
    assert f"(job {a} requeued)" in capsys.readouterr().out


async def test_a_round_whose_commit_already_happened_is_completed_not_run_again(
    monkeypatch, fast, capsys
):
    """The other half of "never left behind": a compile whose commit landed and whose tail
    met the outage. Its completion is the record of work that IS done, so the recovery keeps
    it and says so — re-running the round would compile the same sources twice."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "compile", {"source_ids": ["s-1"]})
    runs: list[str] = []

    async def body(ctx, chat_model, skill, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="compiled")
        raise ResponseHandlingException(httpx.ReadError(""))  # the usage/trace tail

    monkeypatch.setattr(compile_worker, "process_job", body)
    monkeypatch.setattr(compile_worker, "_resolve_user_skill", AsyncMock(return_value=None))
    vectors = SimpleNamespace(ping=AsyncMock(return_value=None))

    await drain_until_done(Ctx(store, vectors=vectors), a)

    assert runs == [a], "a job whose commit had landed was run again"
    assert outcomes(store) == [(a, True)]
    assert f"(job {a} completed)" in capsys.readouterr().out


async def test_the_recovery_always_says_what_became_of_the_job_in_flight(fast):
    """Three shapes, and no fourth one called silence (`_recover`)."""
    store = FlakyQueue()
    ctx = Ctx(store)
    assert await compile_worker._recover(ctx, None) == ["no job in flight"]

    a = await store.enqueue(USER, "index", {})
    await store.claim_next(USER, lane=DERIVED_LANE)
    assert await compile_worker._recover(ctx, (str(USER), a)) == [f"job {a} requeued"]

    await store.claim_next(USER, lane=DERIVED_LANE)
    await store.complete(USER, a, ok=True, detail="indexed")
    assert await compile_worker._recover(ctx, (str(USER), a)) == [f"job {a} completed"]


# ─────────────────────────────────────────── the self-heal runs on a clock, not on a restart


async def test_the_periodic_self_heal_requeues_a_dead_claim_and_spares_a_live_one(fast, capsys):
    """A leaked claim now costs a minute, not a restart — and the sweep never takes a claim
    this process is running: an index job carries no draft and no launch lease, so nothing on
    its row tells a live one from an orphan. Only the body running it knows."""
    store = FlakyQueue()
    a = await store.enqueue(USER, "index", {})
    assert (await store.claim_next(USER, lane=DERIVED_LANE)).job_id == a
    ctx = Ctx(store, settings=worker_settings(worker_selfheal_s=0.02))

    compile_worker._IN_FLIGHT[DERIVED_LANE] = (str(USER), a)  # this body is running it
    task = asyncio.create_task(compile_worker._selfheal_forever(ctx))
    try:
        await asyncio.sleep(0.1)
        rows = {r["job_id"]: r["status"] for r in await store.list_jobs(USER)}
        assert rows[a] == "claimed", "the sweep requeued a job this body is running"
        assert capsys.readouterr().out == ""

        compile_worker._IN_FLIGHT.clear()  # the body that held it is gone
        async with asyncio.timeout(2):
            while (await store.get_job(USER, a)).status != "queued":
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert "[compile-worker self-heal] reclaimed 1 orphaned claimed job(s) → requeued" in (
        capsys.readouterr().out
    )


async def test_the_periodic_self_heal_keeps_the_lease_rules_it_inherits(fast):
    """The sweep on the clock is the startup sweep's own call, so a round whose launch lease
    is live is spared and the same round is requeued once that launch is gone — the rule
    `requeue_claimed_jobs` states and `test_draft_ownership.py` pins."""
    store = FlakyQueue()
    store.drafts = InMemoryDraftStore(store)
    a = await store.enqueue(USER, "episodes", {"source_id": "s-1"})
    claimed = await store.claim_next(USER, lane=DERIVED_LANE, claimed_by="worker:codex:live")
    assert claimed.job_id == a
    ctx = Ctx(store, settings=worker_settings(worker_selfheal_s=0.02))

    async with store.drafts.launch(USER, "worker:codex:live"):
        task = asyncio.create_task(compile_worker._selfheal_forever(ctx))
        try:
            await asyncio.sleep(0.1)
            assert (await store.get_job(USER, a)).status == "claimed", "a live launch was cut"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert await store.requeue_claimed_jobs(draft_ttl=3600, tenants=[str(USER)]) == 1


async def test_the_periodic_self_heal_is_off_when_its_interval_is(fast):
    ctx = Ctx(FlakyQueue(), settings=worker_settings(worker_selfheal_s=0))
    await asyncio.wait_for(compile_worker._selfheal_forever(ctx), timeout=1)


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
        # A claim naming no lane is about the whole tenant, so it takes both lanes'
        # command locks and both lanes' claim locks (adapters/postgres.py `_command_lock`).
        _Cursor((True,)),  # no command holds the canonical lane
        _Cursor((True,)),  # …nor the derived one
        _Cursor(),  # the canonical lane's claim lock
        _Cursor(),  # …and the derived lane's
        _Cursor(("job-9", "index", {}, None)),  # the row it chose
        psycopg.OperationalError(DROPPED),  # and the connection went with its UPDATE
    )
    with pytest.raises(psycopg.OperationalError) as caught:
        await store.claim_next(USER)
    assert caught.value.unsettled_claim == (str(USER), "job-9")
