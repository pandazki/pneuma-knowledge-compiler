"""FastAPI application factory (architecture.md §1).

Lifespan wires settings → adapter singletons once and stashes the AppContext on
app.state; routes read it per-request. M1 mounts the /v1 surface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..settings import Settings, get_settings
from ..wiring import build_context
from .routes.live_context import root_router as live_context_root_router, router as live_context_router
from .routes.evolve import router as evolve_router
from .routes.v1 import root_router, router as v1_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = await build_context(settings)
        try:
            yield
        finally:
            await app.state.ctx.aclose()

    app = FastAPI(title="pneuma-knowledge-service", version=__version__, lifespan=lifespan)

    if settings.cors_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=settings.cors_allow_origin_regex,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(root_router)
    app.include_router(v1_router)
    app.include_router(evolve_router)
    # Live Context: same two prefixes, kept in its own module because the WS
    # session machinery has nothing in common with the request/response surface above.
    app.include_router(live_context_root_router)
    app.include_router(live_context_router)
    return app
