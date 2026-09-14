"""`GET`/`WS /v1/users/{id}/steward` — the console's end of the bridge (§5.6).

Thin, like the live-context socket's tests: the vocabulary is asserted against the adapters
and the lifecycle against the session, so what is left here is the transport contract — the
frames in each direction, the snapshot a reconnecting tab repaints from, and the one answer a
deployment that compiles with a MODEL gets, which is a clear refusal and no process at all.

The harness is `tests/fake_harness/`, first on `PATH`: a real subprocess speaking the real
interactive wire, with no subscription anywhere near it.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pneuma_knowledge_service.api.routes import steward as steward_module
from pneuma_knowledge_service.coding_agent.steward_turns import (
    MAX_IMAGE_BYTES,
    InMemoryStewardTurnStore,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import Executor

FAKE_DIR = Path(__file__).parent / "fake_harness"
USER = "u-steward-route"


def app_for(executor: Executor, **settings_over) -> FastAPI:
    app = FastAPI()
    app.include_router(steward_module.router)
    app.state.ctx = SimpleNamespace(
        settings=Settings(**settings_over),
        compile_executor=executor,
        steward_turns=InMemoryStewardTurnStore(),
    )
    return app


@pytest.fixture
def fake_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", f"{FAKE_DIR}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PKC_FAKE_LOG", str(tmp_path / "invocations.jsonl"))
    monkeypatch.setenv("PKC_FAKE_COMMAND", "pkc owner say --text-file -")
    monkeypatch.delenv("PKC_FAKE_MODE", raising=False)
    return tmp_path


def agent_app(**over) -> FastAPI:
    return app_for(
        Executor(kind="agent", spec="agent:codex", backend="codex"),
        project_dir=os.getcwd(),
        **over,
    )


def model_app() -> FastAPI:
    return app_for(Executor(kind="langchain", spec="openrouter:some/model"))


# ── the deployment that has no Steward ─────────────────────────────────────────────────────


def test_a_model_compiled_deployment_says_so_and_spawns_nothing():
    app = model_app()
    with TestClient(app) as client:
        body = client.get(f"/v1/users/{USER}/steward").json()
        assert body["configured"] is False
        assert body["backend"] == "" and body["live"] is False
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            frame = ws.receive_json()
    assert frame["type"] == "not_configured"
    assert "openrouter:some/model" in frame["detail"]
    # No session was ever made, so nothing has to be reaped.
    assert steward_module.sessions_of(app).sessions == {}


# ── the deployment that has one ────────────────────────────────────────────────────────────


def test_the_status_route_reports_the_backend_before_anything_is_spawned(fake_path):
    with TestClient(agent_app()) as client:
        body = client.get(f"/v1/users/{USER}/steward").json()
    assert body["configured"] is True
    assert (body["backend"], body["label"], body["protocol"]) == ("codex", "Codex", "jsonrpc")
    assert body["live"] is False
    assert body["project_dir"] == os.getcwd()


def read_until(ws, kind: str, limit: int = 60) -> list[dict]:
    out = []
    for _ in range(limit):
        frame = ws.receive_json()
        if frame["type"] == "ping":
            continue
        out.append(frame)
        if frame["type"] == kind:
            return out
    raise AssertionError(f"never saw a {kind!r} frame; got {[f['type'] for f in out]}")


def test_a_turn_streams_back_as_the_one_vocabulary(fake_path):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert first["configured"] is True and first["events"] == []

            ws.send_json({"type": "user", "text": "what came in this week?"})
            frames = read_until(ws, "turn_finished")
            kinds = [f["type"] for f in frames]
            assert "session_started" in kinds and "step_started" in kinds
            step = next(f for f in frames if f["type"] == "step_started")
            assert step["command"] == "pkc owner say --text-file -"

            # The transcript is written before the harness sees the turn (ruling 13).
            session = steward_module.sessions_of(app).get(USER)
            turns = app.state.ctx.steward_turns.turns
            assert turns[(USER, session.session_id)] == ["what came in this week?"]

            ws.send_json({"type": "end"})
        assert steward_module.sessions_of(app).sessions == {}
        # …and the transcript went with the session.
        assert app.state.ctx.steward_turns.turns == {}


def test_a_reconnecting_tab_is_repainted_from_the_snapshot(fake_path):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json({"type": "user", "text": "hello"})
            read_until(ws, "turn_finished")

        # The tab closed; the session is still up, and the next socket JOINS it.
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["live"] is True
            assert snapshot["agent_session_id"]
            kinds = [e["type"] for e in snapshot["events"]]
            # The whole turn is there to repaint with, ending where it ended.
            assert "turn_started" in kinds and kinds[-1] == "turn_finished"
            ws.send_json({"type": "end"})
        assert steward_module.sessions_of(app).sessions == {}


def test_a_blank_turn_is_refused_without_dropping_the_socket(fake_path):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json({"type": "user", "text": "   "})
            error = ws.receive_json()
            assert error["type"] == "error"
            ws.send_json({"type": "nonsense"})
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "end"})
        assert steward_module.sessions_of(app).sessions == {}


def test_a_dead_harness_is_reported_and_start_is_the_only_way_back(fake_path, monkeypatch):
    monkeypatch.setenv("PKC_FAKE_MODE", "fail")
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            frames = read_until(ws, "session_exited")
            assert frames[-1]["exit_code"] == 1

        # Reconnecting does NOT resurrect it: the same dead session is handed back.
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            snapshot = ws.receive_json()
            assert snapshot["live"] is False and snapshot["exited"] is True

            # Only the Owner's own "start again" makes a new process.
            monkeypatch.setenv("PKC_FAKE_MODE", "ok")
            ws.send_json({"type": "start"})
            fresh = read_until(ws, "snapshot")[-1]
            assert fresh["live"] is True and fresh["events"] == []
            ws.send_json({"type": "end"})
        assert steward_module.sessions_of(app).sessions == {}


# ── the answer arrives once ────────────────────────────────────────────────────────────────


def test_an_answer_is_rendered_once_even_though_codex_sends_it_twice(fake_path):
    """The fake speaks 0.154's real shape: deltas, then the whole text again on
    `item/completed`. What reaches the browser is the answer, once."""
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json({"type": "user", "text": "how many jobs?"})
            frames = read_until(ws, "turn_finished")
            said = "".join(f["text"] for f in frames if f["type"] == "text_delta")
            assert said == "two jobs"
            ws.send_json({"type": "end"})


# ── a turn that carries images ─────────────────────────────────────────────────────────────

PNG = "iVBORw0KGgo="  # eight real PNG magic bytes, base64


def data_url(mime: str = "image/png", payload: str = PNG) -> str:
    return f"data:{mime};base64,{payload}"


def image(name: str = "shot.png", mime: str = "image/png", payload: str = PNG) -> dict:
    return {"name": name, "mime": mime, "data_url": data_url(mime, payload)}


def first_error(ws) -> dict:  # noqa: ANN001
    """The next `error` frame, past whatever the session was already saying."""
    return read_until(ws, "error")[-1]


def turn_starts(log: Path) -> list[dict]:
    """What the bridge asked the harness to do, as the fake wrote it down."""
    return [
        json.loads(line)["turn_start"]
        for line in log.read_text(encoding="utf-8").splitlines()
        if "turn_start" in json.loads(line)
    ]


def test_a_pasted_screenshot_reaches_the_harness_as_a_local_image(fake_path):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json(
                {"type": "user", "text": "what is this?", "images": [image()]}
            )
            read_until(ws, "turn_finished")

            session = steward_module.sessions_of(app).get(USER)
            params = turn_starts(fake_path / "invocations.jsonl")[-1]
            assert [i["type"] for i in params["input"]] == ["localImage", "text"]
            path = Path(params["input"][0]["path"])
            # Written into the session's OWN directory, under a name this framework chose.
            assert path.parent == session.attachments_dir()
            assert path.name == "image-0.png"
            assert path.read_bytes() == base64.b64decode(PNG)
            # And the turn reads back as the Owner's words, with the note beside them.
            assert app.state.ctx.steward_turns.turns[(USER, session.session_id)] == [
                "what is this?"
            ]

            ws.send_json({"type": "end"})
        # The session went, and its scratch files with it.
        assert not path.exists()


def test_an_image_only_turn_is_a_turn(fake_path):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json({"type": "user", "text": "", "images": [image()]})
            read_until(ws, "turn_finished")
            params = turn_starts(fake_path / "invocations.jsonl")[-1]
            assert [i["type"] for i in params["input"]] == ["localImage"]
            ws.send_json({"type": "end"})


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"images": [image()] * 5}, "at most 4"),
        ({"images": [image(mime="image/tiff")]}, "unsupported image type"),
        ({"images": [{"name": "x", "mime": "image/png", "data_url": "not-a-data-url"}]},
         "data:<mime>;base64,"),
        ({"images": [{"name": "x", "mime": "image/png",
                      "data_url": "data:image/jpeg;base64," + PNG}]}, "but the image says"),
        ({"images": [{"name": "x", "mime": "image/png",
                      "data_url": "data:image/png,hello"}]}, "base64-encoded"),
        ({"images": [image(payload="!!!not base64!!!")]}, "not valid base64"),
        ({"images": "one image"}, "images must be a list"),
    ],
)
def test_a_refused_attachment_says_why_and_never_drops_the_socket(fake_path, payload, reason):
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json({"type": "user", "text": "look at this", **payload})
            error = first_error(ws)
            assert reason in error["detail"]

            # The socket is alive, and nothing was recorded for the refused turn.
            session = steward_module.sessions_of(app).get(USER)
            assert app.state.ctx.steward_turns.turns.get((USER, session.session_id)) is None
            ws.send_json({"type": "end"})


@pytest.mark.parametrize("over", [1, MAX_IMAGE_BYTES])
def test_an_oversized_image_is_refused_by_its_decoded_size(fake_path, over):
    """One byte over is refused after decoding; grossly over is refused BEFORE, so a payload
    far past the limit is never materialised at all."""
    big = base64.b64encode(b"\x00" * (MAX_IMAGE_BYTES + over)).decode("ascii")
    app = agent_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/users/{USER}/steward") as ws:
            ws.receive_json()
            ws.send_json(
                {"type": "user", "text": "big", "images": [image(payload=big)]}
            )
            error = first_error(ws)
            assert str(MAX_IMAGE_BYTES) in error["detail"]
            ws.send_json({"type": "end"})
