"""The voice call's three doors (docs/design/voice-call.md §4).

- `GET  /v1/users/{uid}/call` — whether a call can be placed here, and if not, the one
  thing missing. The console draws its button from this.
- `POST /v1/users/{uid}/call` — the browser's SDP offer in, the provider's SDP answer out.
  The project key is used HERE and nowhere else; what the browser receives is an answer
  and two ids. Creating a session is billed, so this is only ever called from a click.
- `WS   /v1/users/{uid}/call/{call_id}` — what the engine knows about the call that the
  browser's own data channel does not: each delegation's card, usage, the close.

One call per owner. A second `POST` ends the first: the usual reason a first one is still
open is a tab that died mid-call, and that session is still billing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ...call import (
    CallSession,
    CallSessions,
    LibraryLibrarian,
    LiveUnavailable,
    OpenAILiveGateway,
    call_status,
    session_config,
)
from ...coding_agent.launcher import scrub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users/{user_id}")

PING_INTERVAL = 30.0
#: A call whose browser never opened its socket, or whose socket went away, is closed after
#: this long: nobody is listening to it and it bills by the minute.
ORPHAN_SECONDS = 20.0


class CallIn(BaseModel):
    sdp: str = Field(min_length=1)
    locale: str | None = None


def calls_of(app) -> CallSessions:  # noqa: ANN001
    registry = getattr(app.state, "call_sessions", None)
    if registry is None:
        registry = CallSessions()
        app.state.call_sessions = registry
    return registry


async def close_calls(app) -> None:  # noqa: ANN001
    """API shutdown: no session outlives the process that pays for it."""
    registry = getattr(app.state, "call_sessions", None)
    if registry is not None:
        await registry.aclose()


def _gateway(app, settings) -> Any:  # noqa: ANN001
    stated = getattr(app.state, "call_gateway", None)
    if stated is not None:
        return stated
    gateway = OpenAILiveGateway(settings.openai_api_key)
    app.state.call_gateway = gateway
    return gateway


@router.get("/call")
async def get_call(user_id: str, request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    return call_status(ctx.settings, live=calls_of(request.app).live(user_id))


@router.post("/call", status_code=201)
async def post_call(user_id: str, body: CallIn, request: Request) -> dict[str, Any]:
    from .v1 import _subject_zone
    from pneuma_knowledge_core.domain.ids import UserId

    app = request.app
    ctx = app.state.ctx
    status = call_status(ctx.settings, live=False)
    if not status["configured"]:
        raise HTTPException(
            status_code=503,
            detail={"code": "call_not_configured", "reason": status["reason"], "message": status["detail"]},
        )
    registry = calls_of(app)
    await registry.replace(user_id)
    gateway = _gateway(app, ctx.settings)
    zone = await _subject_zone(ctx, UserId(user_id))
    try:
        created = await gateway.create(session=session_config(ctx.settings, zone=zone), offer_sdp=body.sdp)
    except LiveUnavailable as exc:
        message = scrub(str(exc), secrets=[ctx.settings.openai_api_key])
        raise HTTPException(
            status_code=502, detail={"code": "live_unavailable", "message": message}
        ) from None

    librarian_factory = getattr(app.state, "call_librarian", None) or LibraryLibrarian
    session = CallSession(
        user_id=user_id,
        librarian=librarian_factory(ctx, user_id),
        idle_seconds=float(ctx.settings.call_idle_seconds),
        max_seconds=float(ctx.settings.call_max_seconds),
    )
    session.session_id = created.session_id

    async def run() -> None:
        try:
            async with gateway.attach(created.session_id) as channel:
                orphan = asyncio.create_task(_end_if_orphaned(session))
                try:
                    await session.run(channel)
                finally:
                    orphan.cancel()
        except Exception as exc:  # noqa: BLE001 — a call that cannot attach ends; the API does not
            logger.warning("call %s: could not attach: %s", session.call_id, type(exc).__name__)
            session.close_reason = session.close_reason or "attach_failed"
            session.closed.set()

    registry.start(session, asyncio.create_task(run()))
    return {
        "call_id": session.call_id,
        "session_id": created.session_id,
        "sdp": created.sdp,
        "expires_at": None,
    }


async def _end_if_orphaned(session: CallSession) -> None:
    """End a call nobody is watching. Checked on a clock, because a socket that never
    opened raises nothing anywhere."""
    unwatched = 0.0
    while not session.closed.is_set():
        await asyncio.sleep(1.0)
        unwatched = 0.0 if session.watched else unwatched + 1.0
        if unwatched >= ORPHAN_SECONDS:
            await session.end("orphaned")
            return


@router.websocket("/call/{call_id}")
async def call_ws(websocket: WebSocket, user_id: str, call_id: str) -> None:
    await websocket.accept()
    session = calls_of(websocket.app).get(call_id)
    if session is None or str(session.user_id) != str(user_id):
        await websocket.send_json({"type": "error", "code": "unknown_call", "detail": "no such call"})
        await websocket.close()
        return
    queue = session.attach()

    async def send_loop() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)
            if frame.get("type") == "closed":
                return

    async def ping_loop() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await websocket.send_json({"type": "ping"})

    sender = asyncio.create_task(send_loop())
    pinger = asyncio.create_task(ping_loop())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "end":
                await session.end("close_requested")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(sender, 15.0)
                break
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        pinger.cancel()
        session.detach(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


__all__ = ["calls_of", "close_calls", "router"]
