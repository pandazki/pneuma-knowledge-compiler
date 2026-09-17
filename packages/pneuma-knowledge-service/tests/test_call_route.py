"""`GET`/`POST /v1/users/{id}/call` and the socket beside them — the voice call's three doors.

Thin on purpose, like the steward route's tests: the session's behaviour is pinned in
`test_call_session.py`, so what is left here is the transport contract — what the browser is
handed, what it is NEVER handed (the project key is used in this process and nowhere else),
what an unconfigured or refusing deployment answers, and who may join a call's socket.

Keyless: the provider is a stub gateway, the library is the same fake librarian the session
tests drive.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pneuma_knowledge_service.api.routes import call as call_module
from pneuma_knowledge_service.call.gateway import CreatedSession, LiveUnavailable
from pneuma_knowledge_service.settings import Settings

from test_call_session import KEY, FakeLibrarian, ScriptedChannel, delegated, heard  # noqa: E402

USER = "u-call-route"
OFFER = "v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
ANSWER = "v=0\r\no=- 7000000000000000000 2 IN IP4 127.0.0.1\r\n"


# ── the provider, stubbed ──────────────────────────────────────────────────────────────────


class StubGateway:
    def __init__(self, *, refuses: BaseException | None = None) -> None:
        self.refuses = refuses
        self.created: list[dict] = []
        self.channels: list[ScriptedChannel] = []

    async def create(self, *, session, offer_sdp: str) -> CreatedSession:
        self.created.append({"session": dict(session), "offer_sdp": offer_sdp})
        if self.refuses is not None:
            raise self.refuses
        return CreatedSession(session_id=f"sess-{len(self.created)}", sdp=ANSWER)

    @asynccontextmanager
    async def attach(self, session_id: str):
        channel = ScriptedChannel()
        channel.session_id = session_id
        self.channels.append(channel)
        try:
            yield channel
        finally:
            channel.stop()


def configured(**over) -> Settings:
    return Settings(
        **{"OPENAI_API_KEY": KEY},
        llm_model_call="scripted:call",
        call_model="voice-model-x",
        call_voice="marin",
        **over,
    )


def app_for(settings: Settings, gateway: StubGateway | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await call_module.close_calls(app)

    app = FastAPI(lifespan=lifespan)
    app.include_router(call_module.router)
    app.state.ctx = SimpleNamespace(settings=settings)
    if gateway is not None:
        app.state.call_gateway = gateway
    app.state.call_librarian = lambda ctx, user_id: FakeLibrarian()
    return app


def wait_for(predicate, *, timeout: float = 5.0, what: str = "") -> None:
    """Poll from the test thread; the app's loop lives in the portal thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what or 'the condition'}")


def place(client: TestClient, user: str = USER) -> dict:
    response = client.post(f"/v1/users/{user}/call", json={"sdp": OFFER})
    assert response.status_code == 201, response.text
    return response.json()


# ── whether a call can be placed here ──────────────────────────────────────────────────────


def test_the_status_route_says_what_the_console_draws_its_button_from():
    with TestClient(app_for(configured(), StubGateway())) as client:
        body = client.get(f"/v1/users/{USER}/call").json()
    assert body == {
        "configured": True,
        "reason": "",
        "detail": "",
        "model": "voice-model-x",
        "voice": "marin",
        "live": False,
    }


def test_the_status_route_reports_a_live_call_as_live():
    gateway = StubGateway()
    with TestClient(app_for(configured(), gateway)) as client:
        place(client)
        assert client.get(f"/v1/users/{USER}/call").json()["live"] is True
        # …and one owner's call is not another owner's.
        assert client.get("/v1/users/u-somebody-else/call").json()["live"] is False


# ── placing one ────────────────────────────────────────────────────────────────────────────


def test_placing_a_call_returns_the_providers_answer_and_never_the_project_key():
    """THE property of this route: the documented browser path has no ephemeral credential,
    so the exchange runs HERE with the project key and the browser receives an SDP answer and
    two ids. A key in this response body would be a key in a page."""
    gateway = StubGateway()
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        response = client.post(f"/v1/users/{USER}/call", json={"sdp": OFFER})

    assert response.status_code == 201
    body = response.json()
    assert body["sdp"] == ANSWER
    assert body["session_id"] == "sess-1"
    assert body["call_id"] and body["expires_at"] is None
    assert KEY not in response.text

    # The offer went to the provider as the browser wrote it, inside our session config.
    assert gateway.created[0]["offer_sdp"] == OFFER
    assert gateway.created[0]["session"]["model"] == "voice-model-x"
    assert gateway.created[0]["session"]["delegation"] == {"type": "client"}


def test_a_call_with_no_offer_in_it_is_refused_before_the_provider_is_paid():
    gateway = StubGateway()
    with TestClient(app_for(configured(), gateway)) as client:
        response = client.post(f"/v1/users/{USER}/call", json={"sdp": ""})
    assert response.status_code == 422
    assert gateway.created == []


def test_a_provider_that_refuses_is_reported_in_its_own_words_with_the_key_taken_out():
    """The provider's sentence is what tells the owner what to do ("unsupported usage tier"),
    and its message routinely quotes the key it rejected."""
    gateway = StubGateway(
        refuses=LiveUnavailable(f"Incorrect API key provided: {KEY}. Check your project.", status=401)
    )
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        response = client.post(f"/v1/users/{USER}/call", json={"sdp": OFFER})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "live_unavailable"
    assert "Check your project." in detail["message"]
    assert KEY not in response.text
    # A refused call is not a call: nothing is left billing or listed.
    assert call_module.calls_of(app).live(USER) is False


def test_an_unconfigured_deployment_says_which_half_is_missing_and_creates_nothing():
    """Creating a session is billed, so a deployment that cannot answer from the library must
    not reach the provider at all."""
    gateway = StubGateway()
    app = app_for(Settings(), gateway)
    with TestClient(app) as client:
        response = client.post(f"/v1/users/{USER}/call", json={"sdp": OFFER})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "call_not_configured" and detail["reason"] == "no_openai_key"
    assert gateway.created == []
    assert getattr(app.state, "call_sessions", None) is None


def test_a_second_call_ends_the_one_the_same_owner_already_had():
    """The usual reason a first one is still open is a tab that died mid-call, and that
    session is still billing."""
    gateway = StubGateway()
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        first = place(client)
        wait_for(lambda: gateway.channels, what="the first sideband")
        second = place(client)
        registry = call_module.calls_of(app)
        wait_for(
            lambda: registry.get(first["call_id"]).closed.is_set(), what="the first call to end"
        )
        assert registry.get(first["call_id"]).close_reason == "replaced"
        assert registry.live(USER) is True
        assert second["call_id"] != first["call_id"]


# ── the socket beside it ───────────────────────────────────────────────────────────────────


def read_until(ws, kind: str, limit: int = 40) -> list[dict]:
    frames: list[dict] = []
    for _ in range(limit):
        frame = ws.receive_json()
        if frame["type"] == "ping":
            continue
        frames.append(frame)
        if frame["type"] == kind:
            return frames
    raise AssertionError(f"never saw a {kind!r} frame; got {[frame['type'] for frame in frames]}")


def test_the_socket_carries_the_cards_the_browsers_own_data_channel_cannot_see():
    gateway = StubGateway()
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        call = place(client)
        wait_for(lambda: gateway.channels, what="the sideband")
        channel = gateway.channels[0]
        channel.feed(heard("第二点呢"), delegated("dg-1"))

        with client.websocket_connect(f"/v1/users/{USER}/call/{call['call_id']}") as ws:
            assert ws.receive_json() == {"type": "attached"}
            frames = read_until(ws, "delegation")
            while frames[-1]["delegation"]["state"] != "done":
                frames.append(ws.receive_json())
            card = frames[-1]["delegation"]

            ws.send_json({"type": "end"})
            closed = read_until(ws, "closed")[-1]

    assert card["ask"] == "How far did the ferry scheduling rebuild get?"
    assert card["answer"]["answer"] == "The ramp was widened last week [cite: s3 ¶4-9]."
    assert closed["reason"] == "close_requested"
    assert any(event["type"] == "session.close" for event in channel.sent)


@pytest.mark.parametrize(
    ("user", "call_id"),
    [(USER, "no-such-call"), ("u-somebody-else", None)],
    ids=["unknown call", "another owner's call"],
)
def test_a_socket_for_a_call_that_is_not_yours_is_refused_rather_than_joined(user, call_id):
    """I1 at the socket: there is no cross-user read path, and an unknown id is not one
    either — joining would show one owner another owner's transcript."""
    gateway = StubGateway()
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        call = place(client)
        target = call_id or call["call_id"]
        with client.websocket_connect(f"/v1/users/{user}/call/{target}") as ws:
            frame = ws.receive_json()
        session = call_module.calls_of(app).get(call["call_id"])
        # The refusal is the socket's alone: the owner's own call is neither joined nor ended.
        assert session.watched is False
        assert session.closed.is_set() is False

    assert frame == {"type": "error", "code": "unknown_call", "detail": "no such call"}


def test_shutting_the_api_down_ends_every_call_it_is_paying_for():
    """No session outlives the process that pays for it."""
    gateway = StubGateway()
    app = app_for(configured(), gateway)
    with TestClient(app) as client:
        call = place(client)
        session = call_module.calls_of(app).get(call["call_id"])
    assert session.closed.is_set() and session.close_reason == "shutdown"
