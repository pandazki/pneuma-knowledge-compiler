"""The console's Steward view: one socket per Owner over the harness's own session (§5.6).

    GET /v1/users/{user_id}/steward
        {"configured": bool, "backend": str, "label": str, "protocol": str,
         "live": bool, "exited": bool, "exit_code": int|null, "agent_session_id": str,
         "project_dir": str}
      What the view needs before it draws anything: whether this deployment compiles with a
      coding agent at all, and whether a session is already up. `configured: false` is the
      empty state, not an error — a library compiled by a model has no Steward to talk to.

    WS  /v1/users/{user_id}/steward

      client → server
        {"type": "user", "text": str}   one Owner turn. Recorded in `steward_turns` BEFORE
                                        the harness sees it (ruling 13). A turn sent while
                                        another is in flight is QUEUED, never steered.
        {"type": "start"}               the harness died and the Owner asked for a fresh
                                        session. The ONLY way a new process appears after an
                                        exit: nothing restarts silently (§5.6).
        {"type": "end"}                 end the session and reap the process group.
        {"type": "ping"}                ignored; a client keepalive.

      server → client
        {"type": "snapshot", "configured": ..., "backend": ..., "live": ...,
         "agent_session_id": ..., "events": [event, …]}
          On attach, and again after `start`. The events are the bounded tail the session
          holds (`SNAPSHOT_LIMIT`), so a reconnecting tab repaints rather than starting blank.
        {"type": "not_configured", "detail": str}
          This deployment's compile role is a model. No process is spawned and the socket
          closes; the view shows how to change it.
        every event of the vocabulary (`coding_agent/steward_events.py`), verbatim:
          session_started · turn_started · text_delta · step_started · step_finished ·
          permission_request · turn_finished · session_exited · notice
        {"type": "error", "detail": str}   one bad frame never drops the socket.

The session itself lives in the API process (`app.state.steward_sessions`) exactly as the
live-context socket holds its run: the library's authority is Postgres and canonical, and
what is held here is a handle to a process. Two tabs on one library JOIN one session and see
the same events — one person at two windows, not two Stewards.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from pneuma_knowledge_core.domain.ids import UserId

from ...coding_agent.backends import backend as backend_manifest
from ...coding_agent.steward_session import StewardSessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users/{user_id}")

#: How often the server pings an idle socket. A Steward session's steady state is silence —
#: the Owner is reading — and a proxy would drop the connection at ~100s idle.
PING_INTERVAL = 30.0


def sessions_of(app) -> StewardSessions:  # noqa: ANN001
    """The one registry this API process holds, made on first use."""
    registry = getattr(app.state, "steward_sessions", None)
    if registry is None:
        registry = StewardSessions()
        app.state.steward_sessions = registry
    return registry


async def close_sessions(app) -> None:  # noqa: ANN001
    """API shutdown: no harness outlives the process that owns it."""
    registry = getattr(app.state, "steward_sessions", None)
    if registry is not None:
        await registry.aclose()


def project_dir(ctx: Any) -> str:
    """Where a Steward session runs: the setting, or the directory the API was started from.

    The default is the API's own cwd because that is the project the skill was installed
    into — the same convention `pkc` and the unattended worker follow — so the harness reads
    this deployment's `AGENTS.md` / `CLAUDE.md` and finds the skill beside them.
    """
    stated = str(getattr(ctx.settings, "project_dir", "") or "").strip()
    return stated or os.getcwd()


def _status(ctx: Any, registry: StewardSessions, user_id: str) -> dict[str, Any]:
    executor = ctx.compile_executor
    session = registry.get(user_id)
    manifest = backend_manifest(str(executor.backend)) if executor.is_agent else None
    return {
        "configured": bool(executor.is_agent),
        "backend": executor.backend or "",
        "label": manifest.display_label if manifest else "",
        "protocol": manifest.wire_protocol if manifest else "",
        "spec": executor.spec,
        "live": bool(session is not None and session.live),
        "exited": bool(session is not None and session.exited),
        "exit_code": session.exit_code if session is not None else None,
        "agent_session_id": session.agent_session_id if session is not None else "",
        "project_dir": project_dir(ctx),
    }


def not_configured_detail(ctx: Any) -> str:
    """Why there is no Steward here, in the words the console repeats."""
    return (
        f"this deployment compiles with {ctx.compile_executor.spec or 'a model'}; "
        "the Steward view needs a coding agent"
    )


@router.get("/steward")
async def steward_status(user_id: str, request: Request) -> dict[str, Any]:
    """Whether this deployment has a Steward to talk to, and whether one is up."""
    ctx = request.app.state.ctx
    return _status(ctx, sessions_of(request.app), user_id)


@router.websocket("/steward")
async def steward_ws(websocket: WebSocket, user_id: str) -> None:
    """The conversation. See the module docstring for the protocol."""
    await websocket.accept()
    ctx = websocket.app.state.ctx
    registry = sessions_of(websocket.app)

    executor = ctx.compile_executor
    if not executor.is_agent:
        # No process, and no pretending: the view draws its empty state from this frame.
        await websocket.send_json(
            {"type": "not_configured", "detail": not_configured_detail(ctx)}
        )
        await websocket.close()
        return

    manifest = backend_manifest(str(executor.backend))
    idle_s = float(getattr(ctx.settings, "steward_session_idle", 1800) or 0)
    turn_store = getattr(ctx, "steward_turns", None)

    async def open_session(*, restart: bool = False):
        return await registry.open(
            UserId(user_id),
            manifest=manifest,
            project_dir=project_dir(ctx),
            idle_s=idle_s,
            turn_store=turn_store,
            spawn=getattr(websocket.app.state, "steward_spawn", None),
            restart=restart,
        )

    try:
        session = await open_session()
    except Exception as exc:  # noqa: BLE001 — a harness that will not start is not a 500
        await websocket.send_json(
            {"type": "not_configured", "detail": f"{manifest.display_label}: {exc}"}
        )
        await websocket.close()
        return

    queue = session.attach()

    def snapshot_frame(current) -> dict[str, Any]:  # noqa: ANN001
        return {
            "type": "snapshot",
            **_status(ctx, registry, user_id),
            "session_id": current.session_id,
            "events": current.snapshot(),
        }

    async def send_loop() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)

    async def ping_loop() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await websocket.send_json({"type": "ping"})

    workers = [asyncio.create_task(c) for c in (send_loop(), ping_loop())]
    await websocket.send_json(snapshot_frame(session))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("frame must be a JSON object")
            except ValueError as exc:
                await websocket.send_json({"type": "error", "detail": f"bad frame: {exc}"})
                continue
            kind = message.get("type")
            try:
                if kind == "user":
                    text = str(message.get("text") or "")
                    if not text.strip():
                        raise ValueError("a turn nobody typed is not a turn")
                    await session.send_user_turn(text)
                elif kind == "start":
                    # The Owner pressed "start again" after an exit. Detach from the old
                    # session first so its idle clock does not outlive this socket.
                    session.detach(queue)
                    session = await open_session(restart=True)
                    queue = session.attach()
                    for task in workers:
                        task.cancel()
                    workers = [asyncio.create_task(c) for c in (send_loop(), ping_loop())]
                    await websocket.send_json(snapshot_frame(session))
                elif kind == "end":
                    await registry.end(user_id, detail="ended by the owner")
                    break
                elif kind in ("ping", "pong"):
                    pass
                else:
                    raise ValueError(f"unknown message type: {kind!r}")
            except Exception as exc:  # noqa: BLE001 — one bad frame never drops the socket
                await websocket.send_json({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        for task in workers:
            task.cancel()
        session.detach(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


__all__ = ["PING_INTERVAL", "close_sessions", "project_dir", "router", "sessions_of"]
