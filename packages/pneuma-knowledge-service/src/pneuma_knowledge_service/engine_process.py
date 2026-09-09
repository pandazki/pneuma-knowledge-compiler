"""Run the API and compile worker together on one event loop."""

from __future__ import annotations

import argparse
import asyncio
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI

from .api.app import create_app
from .engine.contract import bootstrap_engine
from .settings import Settings, get_settings
from .workers.compile_worker import run_forever


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


async def run_engine(
    settings: Settings,
    *,
    host: str = "127.0.0.1",
    port: int,
    static_dir: str | Path | None = None,
    worker: bool = True,
    app: FastAPI | None = None,
) -> None:
    """Serve until signalled, cancelled, or either task exits; close both before returning."""
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
        api_task = asyncio.create_task(_serve(server), name="engine-api")
        # The worker starts only once the API's lifespan has finished starting up. Both
        # build an AppContext, and two contexts starting at once against one database raced
        # on a real cold start: one still applying the schema (DDL) while the other's
        # component projections already wrote rows, and Postgres reported a deadlock. One
        # startup at a time, in a fixed order, is the whole fix; the advisory lock inside
        # `apply_schema` covers separate processes, not two contexts in one.
        while worker and not server.started and not api_task.done() and not stopping.is_set():
            await asyncio.sleep(0.05)
        worker_task = (
            asyncio.create_task(run_forever(settings), name="engine-worker")
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
