"""Engine task ownership, signal handling, and startup cleanup without middleware."""

import asyncio
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pneuma_knowledge_service import engine_process, wiring
from pneuma_knowledge_service.api import app as app_module
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker


@pytest.fixture
def engine(monkeypatch):
    started = asyncio.Event()
    worker_started = asyncio.Event()
    worker_closed = asyncio.Event()
    ctx = SimpleNamespace(aclose=AsyncMock())
    build_context = AsyncMock(return_value=ctx)
    monkeypatch.setattr(app_module, "build_context", build_context)
    servers = []

    async def serve(server):
        servers.append(server)
        with server.capture_signals():
            async with server.config.app.router.lifespan_context(server.config.app):
                server.started = True  # what uvicorn sets once the lifespan startup completed
                started.set()
                while not server.should_exit:
                    await asyncio.sleep(0.01)

    async def worker(settings):
        assert settings is build_context.call_args.args[0]
        worker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            worker_closed.set()

    monkeypatch.setattr(engine_process._EngineServer, "serve", serve)
    worker_mock = AsyncMock(side_effect=worker)
    monkeypatch.setattr(engine_process, "run_forever", worker_mock)
    return SimpleNamespace(
        started=started, worker_started=worker_started, worker_closed=worker_closed,
        ctx=ctx, build_context=build_context, worker=worker_mock, servers=servers,
    )


async def test_no_worker_constructs_no_chat_model(engine, monkeypatch):
    model = Mock(side_effect=AssertionError("no chat model should be constructed"))
    monkeypatch.setattr(wiring, "_build_from_name", model)
    monkeypatch.setattr(compile_worker, "build_chat_model_for", model)
    settings = Settings(_env_file=None)
    task = asyncio.create_task(engine_process.run_engine(settings, port=18001, worker=False))
    try:
        await asyncio.wait_for(engine.started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    engine.worker.assert_not_called()
    model.assert_not_called()
    engine.build_context.assert_awaited_once_with(settings)
    engine.ctx.aclose.assert_awaited_once()


@pytest.mark.parametrize("stop", ["cancel", signal.SIGINT, signal.SIGTERM])
async def test_stop_awaits_both_tasks_and_restores_signals(engine, stop):
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    settings = Settings(_env_file=None)
    task = asyncio.create_task(engine_process.run_engine(settings, port=18001))
    try:
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        await asyncio.wait_for(engine.worker_started.wait(), timeout=1)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        else:
            signal.getsignal(stop)(stop, None)
            await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert engine.worker_closed.is_set()
    assert engine.servers[0].should_exit
    engine.worker.assert_awaited_once_with(settings)
    engine.ctx.aclose.assert_awaited_once()
    assert {sig: signal.getsignal(sig) for sig in previous} == previous


async def test_worker_failure_stops_api_and_propagates(engine):
    engine.worker.side_effect = RuntimeError("worker startup failed")
    with pytest.raises(RuntimeError, match="worker startup failed"):
        await asyncio.wait_for(
            engine_process.run_engine(Settings(_env_file=None), port=18001), timeout=1
        )
    engine.ctx.aclose.assert_awaited_once()


async def test_signals_remain_owned_until_worker_cleanup_finishes(engine):
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def worker(settings):
        engine.worker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    engine.worker.side_effect = worker
    task = asyncio.create_task(engine_process.run_engine(Settings(_env_file=None), port=18001))
    try:
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        await asyncio.wait_for(engine.worker_started.wait(), timeout=1)
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        async with asyncio.timeout(1):
            while not engine.ctx.aclose.await_count:
                await asyncio.sleep(0.01)
        assert signal.getsignal(signal.SIGTERM) == handler
        assert not task.done()
    finally:
        release_cleanup.set()
        await asyncio.wait_for(task, timeout=1)


async def test_api_failure_stops_worker_without_exiting_loop(engine, monkeypatch):
    """The API fails AFTER it started serving: the worker, started behind it, is closed."""
    async def failed_serve(server):
        await engine.build_context(server.config.app.state.settings)
        server.started = True
        await engine.worker_started.wait()
        raise SystemExit(3)

    monkeypatch.setattr(engine_process._EngineServer, "serve", failed_serve)
    with pytest.raises(RuntimeError, match="API startup failed .*exit 3"):
        await asyncio.wait_for(
            engine_process.run_engine(Settings(_env_file=None), port=18001), timeout=1
        )
    assert engine.worker_closed.is_set()


async def test_api_failure_before_it_started_never_starts_the_worker(engine, monkeypatch):
    async def failed_serve(server):
        raise SystemExit(3)

    monkeypatch.setattr(engine_process._EngineServer, "serve", failed_serve)
    with pytest.raises(RuntimeError, match="API startup failed .*exit 3"):
        await asyncio.wait_for(
            engine_process.run_engine(Settings(_env_file=None), port=18001), timeout=1
        )
    assert not engine.worker_started.is_set()


@pytest.mark.parametrize("explicit", [True, False])
async def test_worker_uses_supplied_settings_and_closes_on_startup_cancel(monkeypatch, explicit):
    settings = Settings(_env_file=None, llm_model_compile="agent:codex", agent_unattended=False)
    getter = Mock(return_value=settings)
    ctx = SimpleNamespace(aclose=AsyncMock())
    builder = AsyncMock(return_value=ctx)
    monkeypatch.setattr(compile_worker, "get_settings", getter)
    monkeypatch.setattr(compile_worker, "build_context", builder)
    monkeypatch.setattr(
        compile_worker, "requeue_orphaned_jobs", AsyncMock(side_effect=asyncio.CancelledError)
    )
    if explicit:
        await compile_worker.run_forever(settings)
        getter.assert_not_called()
    else:
        await compile_worker.run_forever()
        getter.assert_called_once_with()
    builder.assert_awaited_once_with(settings)
    ctx.aclose.assert_awaited_once()


async def test_worker_closes_context_when_model_construction_fails(monkeypatch):
    ctx = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(compile_worker, "build_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(
        compile_worker, "build_chat_model_for", Mock(side_effect=ValueError("invalid model"))
    )
    with pytest.raises(ValueError, match="invalid model"):
        await compile_worker.run_forever(Settings(_env_file=None, llm_model="openrouter:test/model"))
    ctx.aclose.assert_awaited_once()


@pytest.mark.parametrize("failure", [RuntimeError("startup failed"), asyncio.CancelledError()])
async def test_partial_context_startup_closes_open_adapters(monkeypatch, failure):
    store = SimpleNamespace(open=AsyncMock(), apply_schema=AsyncMock(), aclose=AsyncMock())
    lexical = SimpleNamespace(aclose=AsyncMock())
    vectors = SimpleNamespace(ensure_collection=AsyncMock(side_effect=failure), aclose=AsyncMock())
    monkeypatch.setattr(wiring, "PostgresStore", Mock(return_value=store))
    monkeypatch.setattr(wiring, "MeiliLexicalIndex", Mock(return_value=lexical))
    monkeypatch.setattr(wiring, "QdrantVectorIndex", Mock(return_value=vectors))
    with pytest.raises(type(failure)):
        await wiring.build_context(Settings(_env_file=None, embedding_model="fake:384"))
    store.aclose.assert_awaited_once()
    lexical.aclose.assert_awaited_once()
    vectors.aclose.assert_awaited_once()


def test_main_passes_engine_options(monkeypatch, tmp_path):
    settings = Settings(_env_file=None)
    run_engine = AsyncMock()
    monkeypatch.setattr(engine_process, "get_settings", lambda: settings)
    monkeypatch.setattr(engine_process, "run_engine", run_engine)
    monkeypatch.setattr(
        "sys.argv", ["engine_process", "--port", "18001", "--host", "127.0.0.2",
                     "--static-dir", str(tmp_path), "--no-worker"]
    )
    engine_process.main()
    run_engine.assert_awaited_once_with(
        settings, host="127.0.0.2", port=18001, static_dir=tmp_path, worker=False
    )


async def test_the_engine_registers_the_deployments_contract_before_serving(engine, monkeypatch):
    """The engine process is the library's own entry point standing in a deployment: like
    `pkc`, it must ask the engine directory for the contract and the wording before it
    serves anything (engine/contract.py `bootstrap_engine`), or it would serve sources and
    never a skill."""
    calls: list[object] = []
    monkeypatch.setattr(engine_process, "bootstrap_engine", lambda s: calls.append(s) or "en")
    settings = Settings(_env_file=None)
    task = asyncio.create_task(engine_process.run_engine(settings, port=18002, worker=False))
    try:
        await asyncio.wait_for(engine.started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls == [settings]


async def test_a_supplied_app_is_served_instead_of_building_one(engine, monkeypatch):
    """An application over the library (the personal edition's engine entry) builds the same
    app with its own routes added and hands it in; the bootstrap and the task ownership stay
    the library's, so one process serves both surfaces under one lifecycle."""
    settings = Settings(_env_file=None)
    app = app_module.create_app(settings)
    bootstrapped: list[object] = []
    monkeypatch.setattr(engine_process, "bootstrap_engine", lambda s: bootstrapped.append(s))
    monkeypatch.setattr(
        engine_process, "create_app",
        Mock(side_effect=AssertionError("a supplied app must be served as it was handed in")),
    )
    task = asyncio.create_task(
        engine_process.run_engine(settings, port=18003, worker=False, app=app)
    )
    try:
        await asyncio.wait_for(engine.started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    assert engine.servers[0].config.app is app
    assert bootstrapped == [settings]


async def test_the_worker_starts_only_after_the_api_finished_starting(engine, monkeypatch):
    """Two AppContexts starting at once against one database deadlocked on a real cold
    start (schema DDL against a component's first rows); the engine starts them in order."""
    order: list[str] = []
    real_build = engine.build_context

    async def build_context(settings):
        order.append("api-context")
        return await real_build(settings)

    monkeypatch.setattr(app_module, "build_context", build_context)

    async def worker(settings):
        order.append("worker")
        await asyncio.Event().wait()

    engine.worker.side_effect = worker
    settings = Settings(_env_file=None)
    task = asyncio.create_task(engine_process.run_engine(settings, port=18003))
    try:
        await asyncio.wait_for(engine.worker_started.wait(), timeout=1)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["api-context", "worker"]
