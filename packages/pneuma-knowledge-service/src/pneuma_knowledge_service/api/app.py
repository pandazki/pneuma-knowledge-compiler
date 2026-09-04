"""FastAPI application factory (architecture.md §1).

Lifespan wires settings → adapter singletons once and stashes the AppContext on
app.state; routes read it per-request. M1 mounts the /v1 surface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..archive_service import ArchiveRequestError
from ..settings import Settings, get_settings
from ..snapshot_tenant import SnapshotTenantWriteError
from ..wiring import build_context
from .routes.archive import router as archive_router
from .routes.live_context import root_router as live_context_root_router, router as live_context_router
from .routes.engine import router as engine_router
from .routes.evolve import router as evolve_router
from .routes.v1 import drain_recording_tasks, root_router, router as v1_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = await build_context(settings)
        try:
            yield
        finally:
            # The consultation recordings still in flight get a bounded moment to land.
            # Bounded on purpose: the record is best-effort fire-and-forget (routes/v1.py
            # `_spawn_recording`), and a process that would not exit while one slow write is
            # outstanding is the same wrong promise, moved to shutdown.
            await drain_recording_tasks()
            await app.state.ctx.aclose()

    app = FastAPI(title="pneuma-knowledge-service", version=__version__, lifespan=lifespan)
    # The settings this app was built with, available to routes that need configuration but
    # no middleware (the engine console reads a directory, not a database) — so they stay
    # serveable and testable without a live AppContext behind them.
    app.state.settings = settings

    if settings.cors_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=settings.cors_allow_origin_regex,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # One handler, every write route. The guard is raised by the SERVICE functions
    # (snapshot_tenant.assert_writable), so no route has to remember to catch it — a new write
    # endpoint inherits the 409 for free, which is the only way a fail-closed invariant stays
    # closed as the surface grows.
    @app.exception_handler(SnapshotTenantWriteError)
    async def _snapshot_write_refused(
        _request: Request, exc: SnapshotTenantWriteError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "tenant_id": exc.tenant_id},
        )

    # The archive's refusals, in one place for the same reason: `stale`, `not_proposed`,
    # `unknown_item` and `empty` are the SERVICE's judgements, so every archive endpoint —
    # including any written later — answers them in one shape, with a machine-readable code
    # beside the sentence a human reads.
    @app.exception_handler(ArchiveRequestError)
    async def _archive_request_refused(
        _request: Request, exc: ArchiveRequestError
    ) -> JSONResponse:
        content: dict[str, object] = {"detail": str(exc), "code": exc.code}
        if exc.proposal is not None:
            # A refusal that MOVED the row carries it back. `stale` is the case: the confirm
            # writes the new status before it answers, so a console holding only the error
            # would keep rendering a `proposed` row that no longer exists in that state.
            content["proposal"] = exc.proposal
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(root_router)
    app.include_router(v1_router)
    app.include_router(evolve_router)
    # The archive: propose / confirm / drop / inventory. Its own module because the proposal
    # lifecycle has nothing in common with the ingest and recall surface in v1.
    app.include_router(archive_router)
    # Engine Console: deployment-scoped (no user_id — see the module docstring) and a 404
    # surface unless PNEUMA_KNOWLEDGE_ENGINE_DIR names a directory.
    app.include_router(engine_router)
    # Live Context: same two prefixes, kept in its own module because the WS
    # session machinery has nothing in common with the request/response surface above.
    app.include_router(live_context_root_router)
    app.include_router(live_context_router)
    return app
