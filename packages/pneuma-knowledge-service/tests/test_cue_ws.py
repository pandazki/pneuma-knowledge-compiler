"""`WS /v1/users/{id}/context_stream/cue/ws` — the long-lived listening connection.

A thin layer on purpose: every policy decision (window, quiet period, coalescing, dedup)
is asserted with an injected clock in `test_cue_session.py`, so what is left to check here
is the transport contract — the frames in each direction, and the rule that a listening
feature degrades rather than disconnects.

Starlette's `TestClient.websocket_connect` runs the app in-process over an anyio portal,
so this needs no new dependency and no server. It does run the app on its own event loop
in a separate thread, which is why these tests are synchronous.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.cue import ResolvedCue
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.cue import CueResult
from pneuma_knowledge_service.api.routes import context_stream as cue_module
from fastapi import FastAPI
from fastapi.testclient import TestClient

SRC = "11111111-1111-1111-1111-111111111111"


def resolved(title: str, kind: str = "concept") -> ResolvedCue:
    return ResolvedCue(
        kind=kind,
        title=title,
        body="解释",
        trigger="触发",
        confidence=9,
        citations=[Citation(source_id=SourceId(SRC), block_start=1, block_end=2)],
    )


def result(*cues: ResolvedCue) -> CueResult:
    return CueResult(cues=tuple(cues), token_usage={"total_tokens": 3})


async def _no_profile(ctx, user):  # noqa: ANN001
    return None


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """A bare app carrying only the cue routers — no lifespan, so no middleware is needed.

    `app.state.ctx` is a stub because every route that would touch it is patched per test;
    the subject here is the socket, not the ports behind it."""
    monkeypatch.setattr(cue_module, "_render_profile", _no_profile)
    app = FastAPI()
    app.include_router(cue_module.router)
    app.include_router(cue_module.root_router)
    app.state.ctx = object()
    return TestClient(app)


PATH = "/v1/users/u-ws/context_stream/cue/ws"


def turn(text: str) -> dict:
    return {"type": "turn", "speaker": "me", "text": text, "role": "owner"}


def test_connect_config_turn_cue_want_more_disconnect(client, monkeypatch):
    """The whole intended round trip in one connection."""
    seen: dict = {}

    async def fake_eval(_ctx, user, plan, **kwargs):  # noqa: ANN001
        seen["user"] = user
        seen["focus"] = plan.focus
        seen["turns"] = [t.text for t in plan.turns]
        # The connection-lifetime label map must be handed down, or 参与者N renumbers as
        # the window rolls and refers to a different person between evaluations.
        seen["label_map_passed"] = isinstance(kwargs.get("label_map"), dict)
        return result(resolved("RAG"))

    async def fake_expand(_ctx, _user, cue):  # noqa: ANN001
        return {"title": cue["title"], "detail": "展开正文", "citations": [], "token_usage": {}}

    monkeypatch.setattr(cue_module, "run_evaluation", fake_eval)
    monkeypatch.setattr(cue_module, "expand_cue", fake_expand)

    with client.websocket_connect(PATH) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["focus"] == "general"

        # config echoes the EFFECTIVE policy back, so a client never has to assume.
        ws.send_json({"type": "config", "focus": "other", "quiet_period": 0})
        echoed = ws.receive_json()
        assert echoed["type"] == "ready"
        assert echoed["focus"] == "other"
        assert echoed["quiet_period"] == 0

        ws.send_json(turn("我们在聊 RAG"))
        frame = ws.receive_json()
        assert frame["type"] == "cue"
        assert frame["cue"]["title"] == "RAG"
        # Structured citations with real source ids — the client never sees an sNN handle.
        assert frame["cue"]["citations"] == [
            {"source_id": SRC, "block_start": 1, "block_end": 2}
        ]

        ws.send_json({"type": "want_more", "cue": frame["cue"]})
        detail = ws.receive_json()
        assert detail["type"] == "cue_detail"
        assert detail["title"] == "RAG"
        assert detail["detail"] == "展开正文"

    assert seen["user"] == "u-ws"
    assert seen["focus"] == "other"
    assert seen["turns"] == ["我们在聊 RAG"]
    assert seen["label_map_passed"] is True


def test_a_card_already_shown_this_connection_is_not_sent_again(client, monkeypatch):
    """Server-side dedup over the socket. The second evaluation re-emits RAG and adds
    HNSW; only HNSW may reach the lens."""
    rounds = [result(resolved("RAG")), result(resolved("RAG"), resolved("HNSW"))]

    async def fake_eval(*_args, **_kwargs):
        return rounds.pop(0)

    monkeypatch.setattr(cue_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        assert ws.receive_json()["cue"]["title"] == "RAG"

        ws.send_json(turn("第二轮"))
        second = ws.receive_json()
        assert second["type"] == "cue"
        assert second["cue"]["title"] == "HNSW"  # RAG was dropped, not re-sent


def test_a_reconnecting_client_restores_its_own_already_shown(client, monkeypatch):
    """The client is the dedup authority: after a deploy drops every connection, the card
    list it replays in `config` is the only thing that stops the owner re-reading cards."""

    async def fake_eval(*_args, **_kwargs):
        return result(resolved("RAG"), resolved("HNSW"))

    monkeypatch.setattr(cue_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "config",
                "quiet_period": 0,
                "already_shown": [{"kind": "concept", "title": "RAG"}],
                "turns": [{"speaker": "me", "text": "重连前说过的话", "role": "owner"}],
            }
        )
        ws.receive_json()
        frame = ws.receive_json()  # the restored window is dirty, so this evaluates
        assert frame["cue"]["title"] == "HNSW"


def test_an_evaluation_failure_is_an_error_frame_not_a_dropped_socket(client, monkeypatch):
    """A background listener degrades to silence; it never 500s onto a pair of context clients and
    it never takes the connection down with it."""
    calls = {"n": 0}

    async def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("qdrant unreachable")
        return result(resolved("RAG"))

    monkeypatch.setattr(cue_module, "run_evaluation", flaky)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "qdrant unreachable" in err["detail"]

        ws.send_json(turn("第二轮"))  # the same connection still works
        assert ws.receive_json()["cue"]["title"] == "RAG"


def test_a_malformed_frame_errors_without_dropping_the_connection(client, monkeypatch):
    async def fake_eval(*_args, **_kwargs):
        return result(resolved("RAG"))

    monkeypatch.setattr(cue_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_text("not json at all")
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "teleport"})
        unknown = ws.receive_json()
        assert unknown["type"] == "error"
        assert "unknown message type" in unknown["detail"]

        ws.send_json({"type": "want_more"})  # no cue payload
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "config", "focus": "everyone"})
        bad_focus = ws.receive_json()
        assert bad_focus["type"] == "error"
        assert "unknown cue focus" in bad_focus["detail"]

        ws.send_json(turn("仍然可用"))  # still alive after four bad frames
        assert ws.receive_json()["type"] == "cue"


def test_flush_evaluates_inside_the_quiet_period(client, monkeypatch):
    """`flush` is the client's override for "ask now" — the quiet period exists to
    coalesce transcript chatter, not to overrule an explicit request."""

    async def counting(*args, **kwargs):
        counting.n += 1
        return result(resolved(f"round-{counting.n}"))

    counting.n = 0
    monkeypatch.setattr(cue_module, "run_evaluation", counting)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 3600})  # effectively never again
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        assert ws.receive_json()["cue"]["title"] == "round-1"

        ws.send_json(turn("第二轮"))  # would wait an hour on its own
        ws.send_json({"type": "flush"})
        assert ws.receive_json()["cue"]["title"] == "round-2"


def test_silence_produces_no_frames(client, monkeypatch):
    """Zero cues must send nothing at all — an "I have nothing" frame arriving every few
    seconds is the opposite of what a lens wants."""

    async def silent(*_args, **_kwargs):
        return result()

    async def fake_expand(_ctx, _user, cue):  # noqa: ANN001
        return {"title": "x", "detail": "d", "citations": [], "token_usage": {}}

    monkeypatch.setattr(cue_module, "run_evaluation", silent)
    monkeypatch.setattr(cue_module, "expand_cue", fake_expand)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()
        ws.send_json(turn("闲聊，没有值得提示的东西"))
        # Nothing is emitted for the evaluation; the next frame is the answer to a LATER
        # request, which can only arrive if no cue/done/idle frame was queued ahead of it.
        ws.send_json({"type": "want_more", "cue": {"title": "x"}})
        assert ws.receive_json()["type"] == "cue_detail"


def test_ping_from_the_client_is_accepted_silently(client):
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})
        ws.send_json({"type": "config", "min_confidence": 8})
        echoed = ws.receive_json()
        assert echoed["type"] == "ready"  # not an error for the ping
        assert echoed["min_confidence"] == 8


def test_stats_are_off_by_default_and_opt_in_per_connection(client, monkeypatch):
    """The gate counters must be available, without making a quiet socket chatty.

    `dropped` is the single most useful tuning signal, and it was SSE-only — unavailable
    on the transport the context clients actually use. But emitting telemetry every evaluation
    would break the property `test_silence_produces_no_frames` guards, so it is opt-in and
    the lens never pays for it."""

    async def silent(*_args, **_kwargs):
        r = result()
        object.__setattr__(r, "dropped", {"uncited": 2, "low_confidence": 1})
        return r

    monkeypatch.setattr(cue_module, "run_evaluation", silent)

    with client.websocket_connect(PATH) as ws:
        assert ws.receive_json()["stats"] is False  # default, echoed in `ready`

        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        assert ws.receive_json()["stats"] is True

        ws.send_json(turn("闲聊，没有值得提示的东西"))
        frame = ws.receive_json()

    # Fires even though the evaluation produced nothing — that is the case you most need
    # it for, and the one a field on the `cue` frame could never cover.
    assert frame["type"] == "stats"
    assert frame["delivered"] == 0
    assert frame["dropped"] == {"uncited": 2, "low_confidence": 1}


def test_want_more_echoes_the_clients_ref_on_both_outcomes(client, monkeypatch):
    """Without a correlation id a failed expansion names no request, so a client cannot
    tell WHICH card failed — it has to reset every pending expansion at once. Matching on
    `title` is the other trap: it works only because title doubles as the dedup key."""
    calls: list[dict] = []

    async def expand(_ctx, _user, cue):  # noqa: ANN001
        calls.append(cue)
        if cue.get("title") == "boom":
            raise ValueError("nope")
        return {"title": cue.get("title"), "detail": "d", "citations": [], "token_usage": {}}

    monkeypatch.setattr(cue_module, "expand_cue", expand)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()

        ws.send_json({"type": "want_more", "cue": {"title": "ok"}, "ref": "card-7"})
        good = ws.receive_json()
        assert good["type"] == "cue_detail"
        assert good["ref"] == "card-7"

        ws.send_json({"type": "want_more", "cue": {"title": "boom"}, "ref": "card-9"})
        bad = ws.receive_json()
        assert bad["type"] == "error"
        assert bad["ref"] == "card-9"  # the failure names its own request

    assert [c["title"] for c in calls] == ["ok", "boom"]
