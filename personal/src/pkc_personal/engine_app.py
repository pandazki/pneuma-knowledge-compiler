"""The edition's engine entry: the library's own app, plus the home's routes over it.

A library engine started by `pkc_personal.engine` serves the library's API and the console's
`dist`. The console's home face (design §4.12, §10) needs three things more — the status of
the whole machine, every library with its engine's port so switching is a navigation, and the
`pkchome` verbs the tray also offers — and none of them belong to the library: they are the
EDITION's, and they are added here, to the same application, so one process still serves one
library and there is no second server to keep alive.

The routes read the home from disk and run `pkchome` as a subprocess. They need no AppContext,
so they answer while the middleware is down — which is exactly when a health page is read.
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import time
import shutil
import subprocess
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.engine_process import run_engine
from pneuma_knowledge_service.settings import Settings, get_settings
from pydantic import BaseModel

from pkc_personal import __version__, status
from pkc_personal.home import Home
from pkc_personal.library import Library, validate_name

# The verbs `pkchome` owns that the console and the tray may ask for.
ACTIONS = ("up", "down", "restart", "sync")
# Two of them stop THIS engine: run under the same process group they would kill nothing but
# themselves, so they are detached and the request is answered before the signal arrives.
SELF_STOPPING = frozenset({"down", "restart"})
ACTION_TIMEOUT = 300.0


class UseRequest(BaseModel):
    name: str


def pkchome_command(home: Home) -> str:
    """Where this installation put `pkchome`, as `config.yaml` recorded it."""
    try:
        recorded = home.config.install.pkchome
    except (OSError, ValueError):
        recorded = ""
    return recorded or shutil.which("pkchome") or "pkchome"


def _run(home: Home, argv: list[str]) -> dict:
    command = [pkchome_command(home), *argv]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=ACTION_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"{' '.join(argv)} timed out", "exit": None}
    except OSError as error:
        return {"ok": False, "stdout": "", "stderr": str(error), "exit": None}
    return {"ok": result.returncode == 0, "stdout": result.stdout,
            "stderr": result.stderr, "exit": result.returncode}


def _detach(home: Home, argv: list[str]) -> dict:
    """Start the command in its own session and answer without waiting for it."""
    command = [pkchome_command(home), *argv]
    try:
        log = (home.path / "run" / "actions.log").open("ab")
    except OSError:
        log = None
    try:
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log or subprocess.DEVNULL,
            stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, "PKC_HOME": str(home.path)},
        )
    except OSError as error:
        return {"ok": False, "detached": False, "stderr": str(error)}
    finally:
        if log is not None:
            log.close()
    return {"ok": True, "detached": True}


def home_document(home: Home, library: Library) -> dict:
    """The document `pkchome status --json` prints, as THIS engine sees the home.

    One row differs from the command's: `current` names the library this process serves, not
    the home's last `library use`. The console reads it to decide which tenant it is showing
    (design §10), and a console served by this engine is showing this library whatever another
    terminal has since selected.
    """
    document = status.status_document(home)
    for row in document["libraries"]:
        row["current"] = row["name"] == library.state.name
        if row["current"]:
            document["sync"] = row.get("sync")
    return document


class StatusCache:
    """The last computed status document, served instantly; refreshed off the loop.

    Computing the document runs probes (Docker, ports, a `pkc profile show` subprocess,
    git, the jobs endpoint) and takes seconds; the tray and the console's health page poll
    it every few seconds and want the last known state now (design §4.11, state first,
    then updates). So the document is computed on a timer and the route answers from the
    cache. The first request before any refresh computes once, synchronously.
    """

    def __init__(self, home: Home, library: Library, *, interval: float = 10.0):
        self.home, self.library, self.interval = home, library, interval
        self.document: dict | None = None
        self.computed_at: float | None = None
        self._lock = threading.Lock()

    def refresh(self) -> dict:
        document = home_document(self.home, self.library)
        with self._lock:
            self.document, self.computed_at = document, time.time()
        return document

    def current(self) -> dict:
        with self._lock:
            document = self.document
        if document is None:
            return self.refresh()
        return dict(document, computed_at=self.computed_at)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.refresh)
            except Exception as exc:  # noqa: BLE001 — a failed probe must not end the refresher
                print(f"[engine] home status refresh failed: {exc}", flush=True)
            await asyncio.sleep(self.interval)


def build_router(home: Home, library: Library, cache: StatusCache | None = None) -> APIRouter:
    router = APIRouter(prefix="/home", tags=["home"])
    cache = cache or StatusCache(home, library)

    # Every probe below reads files, opens sockets and runs git: blocking work, and one of the
    # probes calls THIS process's own API port. On the event loop that would deadlock the
    # engine against itself, so the whole document is produced in a worker thread.
    @router.get("/status")
    async def home_status() -> dict:
        return await asyncio.to_thread(cache.current)

    @router.get("/libraries")
    async def home_libraries() -> list[dict]:
        document = await asyncio.to_thread(cache.current)
        return document["libraries"]

    @router.get("/version")
    async def home_version() -> dict:
        return {"pkc_personal": __version__}

    # Declared before the verb route so `use` is never read as a verb.
    @router.post("/actions/use")
    async def use_library(request: UseRequest) -> dict:
        try:
            validate_name(request.name)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return await asyncio.to_thread(_run, home, ["library", "use", request.name])

    @router.post("/actions/{verb}")
    async def run_action(verb: str) -> dict:
        if verb not in ACTIONS:
            raise HTTPException(status_code=404, detail=f"unknown action: {verb}")
        if verb == "sync":
            return await asyncio.to_thread(_detach, home,
                                           ["sync", "--library", library.state.name, "--json"])
        if verb in SELF_STOPPING:
            return await asyncio.to_thread(_detach, home, [verb])
        return await asyncio.to_thread(_run, home, [verb])

    return router


def build_app(
    home: Home, library: Library, settings: Settings, static_dir: str | Path | None = None
) -> FastAPI:
    """The library's application with the home's routes added to it."""
    app = create_app(settings, static_dir=static_dir)
    cache = StatusCache(home, library)
    # After the console's SPA mount on purpose: the mount declines any path another route
    # claims, including routes added after it, so /home stays the edition's namespace.
    app.include_router(build_router(home, library, cache))
    app.state.home_status_cache = cache
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--static-dir", type=Path)
    parser.add_argument("--no-worker", action="store_true")
    args = parser.parse_args(argv)
    home = Home()
    library = Library.load(home, args.library)
    # The process environment is already the library's — `pkc_personal.engine.start` set it —
    # so the settings this app is built with are the settings the worker will use.
    settings = get_settings()
    # The app already carries the console mount, so `run_engine` is handed the application
    # and not the directory: it serves what it was given and builds nothing.
    app = build_app(home, library, settings, args.static_dir)

    async def serve() -> None:
        refresher = asyncio.create_task(app.state.home_status_cache.run(), name="home-status")
        try:
            await run_engine(
                settings, host=args.host, port=args.port,
                worker=not args.no_worker, app=app,
            )
        finally:
            refresher.cancel()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
