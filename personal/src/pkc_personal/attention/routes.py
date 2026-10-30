"""Personal-only routes bound to this engine's library, with no caller-selected tenant."""

from __future__ import annotations
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import kernel
from .store import Store, stamp

WEB = Path(__file__).with_name("web")


def local_request(request: Request):
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(403, "attention is local to this library engine")
    origin = request.headers.get("origin")
    if request.method != "GET" and origin:
        parsed = urlsplit(origin)
        if parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
            raise HTTPException(403, "cross-origin attention write refused")


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    batch_id: str = Field(min_length=1, max_length=128)
    event_seq: int = Field(ge=0)


def build_router(library) -> APIRouter:
    router = APIRouter(
        prefix="/home/attention",
        tags=["attention"],
        dependencies=[Depends(local_request)],
    )

    def store():
        return Store(library.path / "attention")

    @router.get("/state")
    def current():
        storage = store()
        state = storage.read()
        now = time.time()
        return {
            "library": library.state.name,
            "tenant": library.state.tenant,
            "preferences": storage.preferences().model_dump(),
            "state": kernel.project_state(state["snapshot"], stamp(now)),
            "status": {
                key: state[key]
                for key in (
                    "running",
                    "last_run",
                    "last_attempt",
                    "retry_at",
                    "error",
                    "heartbeat",
                    "pending_count",
                )
            },
            "reflection": state.get("reflection"),
            "landscape": state.get("landscape"),
            "worker_alive": state["heartbeat"] is not None
            and now - state["heartbeat"] < 660,
            "frames": storage.frame_headers(),
        }

    @router.get("/frames")
    def frames(
        before: int | None = Query(None, ge=1), limit: int = Query(100, ge=1, le=100)
    ):
        return store().frame_headers(before, limit)

    @router.get("/history")
    def history(
        before: int | None = Query(None, ge=1), limit: int = Query(60, ge=1, le=100)
    ):
        import json

        with store().connect() as db:
            rows = db.execute(
                "SELECT id, at, json_extract(body, '$.state'), json_extract(body, '$.reflection'), "
                "json_extract(body, '$.signal') FROM frames WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before or 2**63 - 1, limit),
            ).fetchall()
        return [
            {
                "id": identity,
                "at": at,
                "state": json.loads(state),
                "reflection": json.loads(reflection) if reflection else None,
                "signal": json.loads(signal),
            }
            for identity, at, state, reflection, signal in rows
        ]

    @router.get("/frames/{identity}")
    def frame(identity: int):
        result = store().frame(identity)
        if result is None:
            raise HTTPException(404, "attention frame not found")
        return result

    @router.get("/evidence")
    def evidence(ref: str = Query(min_length=1, max_length=2000)):
        import json

        with store().connect() as db:
            row = db.execute(
                "SELECT e.value FROM frames, json_each(frames.body, '$.evidence') e "
                "WHERE json_extract(e.value, '$.ref')=? LIMIT 1",
                (ref,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "recorded evidence not found in this library")
        return json.loads(row[0])

    @router.patch("/preferences")
    def preferences(changes: dict):
        try:
            return store().configure(changes).model_dump()
        except ValidationError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/review", status_code=202)
    def review():
        store().request()
        return {"queued": True}

    @router.post("/annotations")
    def annotate(body: Annotation):
        try:
            storage = store()
            return storage.annotate(
                body.item, body.text, body.batch_id, time.time(), body.event_seq
            )
        except kernel.FoldError as error:
            raise HTTPException(422, error.to_dict()) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/view")
    def view():
        return FileResponse(
            WEB / "index.html",
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'",
            },
        )

    @router.get("/assets/{name}")
    def asset(name: str):
        if name not in {"board.js", "board.css", "visuals.js", "drop-field.js"}:
            raise HTTPException(404)
        return FileResponse(WEB / name, headers={"Cache-Control": "no-cache"})

    return router
