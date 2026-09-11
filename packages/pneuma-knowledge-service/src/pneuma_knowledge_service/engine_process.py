"""Run the API and compile worker together on one event loop."""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import logging
import signal
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI

from .api.app import create_app
from .engine.contract import bootstrap_engine
from .infra_faults import infrastructure_fault
from .settings import Settings, get_settings
from .wiring import CONNECTION_ROLE
from .workers.compile_worker import run_forever

#: The names the engine's two roles give their Postgres connections (`application_name`).
API_CONNECTION_ROLE = "pkc-engine-api"
WORKER_CONNECTION_ROLE = "pkc-engine-worker"

#: How the engine restarts a worker that stopped because infrastructure was away: after
#: this long, doubling to the maximum, and back to the start once a worker has run for
#: `WORKER_HEALTHY_AFTER_S` — so a stack that keeps flapping never becomes a restart storm,
#: and one outage a day never pays for yesterday's.
WORKER_RESTART_START_S = 2.0
WORKER_RESTART_MAX_S = 60.0
WORKER_HEALTHY_AFTER_S = 60.0


#: Whose log lines the engine process shows: the library's own. An application standing
#: over the library names its own loggers when it starts the engine (`extra_loggers`) — the
#: library never knows which applications exist. Never the root logger: uvicorn configures
#: its own handlers with `propagate=False`, and a root handler added here would either
#: duplicate every request line or start printing whatever a dependency logs.
ENGINE_LOGGERS: tuple[str, ...] = ("pneuma_knowledge_service",)

#: One line, with the logger's name in it. The name is what makes the line actionable — the
#: reader of an engine log needs to know a warning came from the compile worker rather than
#: from an adapter — and it is the whole reason this is not `basicConfig`'s default format.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: The marker that makes this idempotent. An engine started twice in one process (a test, a
#: reload) must not get two handlers and print everything twice.
_HANDLER_MARK = "pneuma_engine_log"


class _StderrHandler(logging.StreamHandler):
    """A stream handler that resolves `sys.stderr` when it EMITS, not when it is built.

    The stdlib's own last-resort handler is written this way, for this reason: whatever
    replaced the process's stderr after configuration — an application wrapping the engine,
    a harness capturing output — is where the line has to go, or the engine's account of
    itself ends up in a stream nobody is reading.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self):  # noqa: ANN201 — the stdlib's own signature
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:  # noqa: ANN001 — `StreamHandler.__init__` assigns it
        pass


def configure_logging(settings: Settings, extra_loggers: Sequence[str] = ()) -> None:
    """Send this deployment's own log lines to stderr, once, where the engine log reads them.

    A worker's `log.info` is the only account anyone has of what an unattended round did:
    which harness was launched, what it exited with, how long the tenant is cooling. Until
    this existed none of it was configured, so `logging`'s last-resort handler dropped
    everything below WARNING and an engine log captured from this process held only
    `print()`ed lines and uvicorn's own INFO — a compile worker that had just failed a job
    appeared, in the one file an Owner reads, to have done nothing at all.

    stderr, because that is the stream an engine log captures. `PNEUMA_KNOWLEDGE_LOG_LEVEL`
    sets the level; an unreadable name is INFO. `extra_loggers` are an application's own,
    configured the same way.
    """
    level = logging.getLevelNamesMapping().get(
        str(getattr(settings, "log_level", "") or "INFO").strip().upper(), logging.INFO
    )
    for name in dict.fromkeys((*ENGINE_LOGGERS, *extra_loggers)):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # These loggers print through this handler and are not handed up to the root, so a
        # deployment that configures its own root logging gets no second copy of the line.
        logger.propagate = False
        if any(getattr(h, _HANDLER_MARK, False) for h in logger.handlers):
            continue
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        setattr(handler, _HANDLER_MARK, True)
        logger.addHandler(handler)


class _EngineServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, stopping: asyncio.Event):
        super().__init__(config)
        self.stopping = stopping

    def capture_signals(self) -> nullcontext[None]:
        # The engine owns shutdown for both tasks. Uvicorn's default handler only stops
        # HTTP and re-raises captured signals, which can interrupt the worker's cleanup.
        return nullcontext()

    @contextmanager
    def engine_signals(self) -> Iterator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        previous = {}
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, self._stop)
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    def _stop(self, signum: int, _frame: FrameType | None) -> None:
        print(f"[engine] received {signal.Signals(signum).name}; stopping", flush=True)
        self.should_exit = True
        self.stopping.set()


async def _serve(server: uvicorn.Server) -> None:
    try:
        await server.serve()
    except SystemExit as exc:
        # Uvicorn exits on a failed lifespan or bind. A child task must report that
        # failure to its owner instead of terminating the loop before cleanup can run.
        raise RuntimeError(f"[engine] API startup failed (exit {exc.code})") from exc


def _in_role(role: str) -> contextvars.Context:
    """A context whose tasks name their connections `role` (`wiring.CONNECTION_ROLE`)."""
    context = contextvars.copy_context()
    context.run(CONNECTION_ROLE.set, role)
    return context


async def _supervise_worker(settings: Settings) -> None:
    """Run the worker; restart it in place when infrastructure took it down.

    The worker waits out an outage that meets its drain on its own (`compile_worker.
    ride_out`). What reaches here is an outage it met where there is nothing to wait in —
    building its context, the startup self-heal — and the answer is the same: this is not
    a reason to stop serving the API. One line per restart, with a bounded backoff. A worker
    that stopped for any other reason propagates, so the engine exits and a supervisor sees
    it, as it always did.
    """
    loop = asyncio.get_running_loop()
    delay = WORKER_RESTART_START_S
    while True:
        started = loop.time()
        try:
            await run_forever(settings)
            return
        except Exception as exc:
            fault = infrastructure_fault(exc)
            if fault is None:
                raise
        if loop.time() - started >= WORKER_HEALTHY_AFTER_S:
            delay = WORKER_RESTART_START_S
        print(
            f"[engine] worker stopped: infrastructure unavailable ({fault.describe()}); "
            f"restarting in {delay:g}s",
            flush=True,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, WORKER_RESTART_MAX_S)


async def run_engine(
    settings: Settings,
    *,
    host: str = "127.0.0.1",
    port: int,
    static_dir: str | Path | None = None,
    worker: bool = True,
    app: FastAPI | None = None,
    extra_loggers: Sequence[str] = (),
) -> None:
    """Serve until signalled, cancelled, or either task exits; close both before returning."""
    # Before anything else logs: the API's startup and the worker's first sweep both speak,
    # and a line printed before the handlers exist is a line nobody ever sees. An application
    # that hands in its own app names its own loggers too.
    configure_logging(settings, extra_loggers)
    # A framework entry point standing in a deployment has neither the deployment's contract
    # nor its wording until it asks the engine directory for them (engine/contract.py,
    # `bootstrap_engine`): an application's own driver registers both before it starts a
    # server; this process is the library's own entry and must do the same, or it would serve
    # sources and never a skill. A deployment without an engine directory is left as it is.
    bootstrap_engine(settings)
    # An application standing over the library builds the same app with its own routes added
    # and hands it in: those routes are the application's, while the contract bootstrap above
    # and the task ownership below stay the library's, so an application that adds a surface
    # of its own still runs one engine and not two.
    app = create_app(settings, static_dir=static_dir) if app is None else app
    stopping = asyncio.Event()
    server = _EngineServer(uvicorn.Config(app, host=host, port=port), stopping)
    with server.engine_signals():
        print(f"[engine] starting http://{host}:{port} worker={worker}", flush=True)
        api_task = asyncio.create_task(
            _serve(server), name="engine-api", context=_in_role(API_CONNECTION_ROLE)
        )
        # The worker starts only once the API's lifespan has finished starting up. Both
        # build an AppContext, and two contexts starting at once against one database raced
        # on a real cold start: one still applying the schema (DDL) while the other's
        # component projections already wrote rows, and Postgres reported a deadlock. One
        # startup at a time, in a fixed order, is the whole fix; the advisory lock inside
        # `apply_schema` covers separate processes, not two contexts in one.
        while worker and not server.started and not api_task.done() and not stopping.is_set():
            await asyncio.sleep(0.05)
        # Supervised: infrastructure taking the worker down restarts the worker, and never
        # takes the API with it (`_supervise_worker`).
        worker_task = (
            asyncio.create_task(
                _supervise_worker(settings),
                name="engine-worker",
                context=_in_role(WORKER_CONNECTION_ROLE),
            )
            if worker and server.started
            else None
        )
        stop_task = asyncio.create_task(stopping.wait(), name="engine-stop")
        tasks = [api_task, stop_task]
        if worker_task is not None:
            tasks.append(worker_task)
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            print("[engine] stopping API and worker", flush=True)
            server.should_exit = True
            if worker_task is not None and not worker_task.done():
                worker_task.cancel()
            stop_task.cancel()
            # Let uvicorn finish its lifespan normally so the API closes its pools too.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            print("[engine] stopped", flush=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--static-dir", type=Path)
    parser.add_argument("--no-worker", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(
            run_engine(
                get_settings(), host=args.host, port=args.port,
                static_dir=args.static_dir, worker=not args.no_worker,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
