"""FastAPI application factory (architecture.md §1).

Lifespan wires settings → adapter singletons once and stashes the AppContext on
app.state; routes read it per-request. M1 mounts the /v1 surface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .. import __version__
from ..archive_service import ArchiveRequestError
from ..infra_faults import infrastructure_exception_types, infrastructure_fault
from ..settings import Settings, get_settings
from ..snapshot_tenant import SnapshotTenantWriteError
from ..wiring import CONNECTION_ROLE, build_context, connection_role_as
from .routes.archive import router as archive_router
from .routes.live_context import root_router as live_context_root_router, router as live_context_router
from .routes.engine import router as engine_router
from .routes.evolve import router as evolve_router
from .routes.steward import close_sessions as close_steward_sessions, router as steward_router
from .routes.v1 import drain_recording_tasks, root_router, router as v1_router


class _SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD"):
                raise
            return await super().get_response("index.html", scope)


class _SPAMount(Mount):
    """Leave API namespaces and routes added by the host application to its router."""

    def __init__(self, app: FastAPI, directory: str | Path):
        super().__init__("/", app=_SPAStaticFiles(directory=directory), name="console")
        self.api_routes = app.routes

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] != "http":
            return Match.NONE, {}
        # Included API routers all live under /v1. Top-level routes also reserve their
        # namespace, including FastAPI's docs and routes the hosting application adds.
        prefixes = {"/v1"}
        for route in self.api_routes:
            if route is self:
                continue
            path = getattr(route, "path", "")
            if path and path != "/":
                prefixes.add("/" + path.strip("/").split("/", 1)[0])
            if route.matches(scope)[0] != Match.NONE:
                return Match.NONE, {}
        path = scope["path"].removeprefix(scope.get("root_path", ""))
        if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes):
            return Match.NONE, {}
        return super().matches(scope)


def create_app(
    settings: Settings | None = None, *, static_dir: str | Path | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The engine starts the API in a task named `pkc-engine-api`; served on its own
        # (uvicorn over `create_app`), the API names its connections `pkc-api`.
        with connection_role_as(CONNECTION_ROLE.get() or "pkc-api"):
            app.state.ctx = await build_context(settings)
        try:
            yield
        finally:
            # The consultation recordings still in flight get a bounded moment to land.
            # Bounded on purpose: the record is best-effort fire-and-forget (routes/v1.py
            # `_spawn_recording`), and a process that would not exit while one slow write is
            # outstanding is the same wrong promise, moved to shutdown.
            await drain_recording_tasks()
            # No harness outlives the process that owns it: every live Steward session's
            # process group is reaped here (docs/design/coding-agent-mode.md §5.6).
            await close_steward_sessions(app)
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

    # The canonical library holding somebody else's uncommitted changes, in one handler for
    # the same reason as the two above: the ADAPTER raises it, and any route whose request
    # path commits — the skill manifest write behind `/evolve/skill`, an evolve adopt —
    # answers 409 with one machine code, including routes written later. 409 and not 500:
    # nothing is broken, the library is simply in a state only a person can resolve, and the
    # same request succeeds once they have committed, stashed or reverted their work.
    @app.exception_handler(CanonicalDirtyError)
    async def _canonical_dirty(
        _request: Request, exc: CanonicalDirtyError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": exc.code, "paths": list(exc.paths)},
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

    # Infrastructure away for a moment — Postgres restarting, Qdrant or Meilisearch being
    # recreated, RustFS dropping a connection. The request fails, briefly and legibly, with a
    # 503 the console can retry; the process and its lifespan stay as they are, because the
    # pool reconnects on its own (`PostgresStore`'s connection check) and so do the HTTP
    # clients. One handler per class that CAN carry such a failure, each asking the one
    # classifier: the same class also carries failures that are not transient (a statement
    # timeout is an OperationalError), and those keep the unhandled path they always had.
    async def _infrastructure_unavailable(_request: Request, exc: Exception) -> JSONResponse:
        fault = infrastructure_fault(exc)
        if fault is None:
            raise exc
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"infrastructure unavailable ({fault.describe()})",
                "code": "infrastructure_unavailable",
            },
            headers={"Retry-After": "5"},
        )

    for exc_class in infrastructure_exception_types():
        app.add_exception_handler(exc_class, _infrastructure_unavailable)

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
    # The console's Steward view: one WebSocket per Owner over the harness's own session,
    # plus the GET the view reads its empty/disabled state from.
    app.include_router(steward_router)
    if static_dir is not None:
        app.router.routes.append(_SPAMount(app, static_dir))
    return app
