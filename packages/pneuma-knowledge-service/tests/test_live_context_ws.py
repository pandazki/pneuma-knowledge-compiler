"""`WS /v1/users/{id}/live-context/ws` — the long-lived Live Context connection.

A thin layer on purpose: every policy decision (window, quiet period, coalescing, dedup)
is asserted with an injected clock in `test_suggestion_session.py`, so what is left to check here
is the transport contract — the frames in each direction, and the rule that a listening
feature degrades rather than disconnects.

Starlette's `TestClient.websocket_connect` runs the app in-process over an anyio portal,
so this needs no new dependency and no server. It does run the app on its own event loop
in a separate thread, which is why these tests are synchronous.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.suggestion import ResolvedSuggestion
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.live_pipeline import PipelineResult
from pneuma_knowledge_core.recall.stage_timing import StageTiming
from pneuma_knowledge_service.api.routes import live_context as suggestion_module
from fastapi import FastAPI
from fastapi.testclient import TestClient

SRC = "11111111-1111-1111-1111-111111111111"


def resolved(title: str, kind: str = "concept") -> ResolvedSuggestion:
    return ResolvedSuggestion(
        kind=kind,
        title=title,
        body="解释",
        trigger="触发",
        confidence=9,
        citations=[Citation(source_id=SourceId(SRC), block_start=1, block_end=2)],
    )


def result(*suggestions: ResolvedSuggestion, **fields) -> PipelineResult:
    return PipelineResult(
        suggestions=tuple(suggestions), token_usage={"total_tokens": 3}, **fields
    )


async def _no_profile(ctx, user):  # noqa: ANN001
    return None


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """A bare app carrying only the suggestion routers — no lifespan, so no middleware is needed.

    `app.state.ctx` is a stub because every route that would touch it is patched per test;
    the subject here is the socket, not the ports behind it."""
    monkeypatch.setattr(suggestion_module, "_render_profile", _no_profile)
    app = FastAPI()
    app.include_router(suggestion_module.router)
    app.include_router(suggestion_module.root_router)
    app.state.ctx = object()
    return TestClient(app)


PATH = "/v1/users/u-ws/live-context/ws"


def turn(text: str) -> dict:
    return {"type": "turn", "speaker": "me", "text": text, "role": "owner"}


def test_connect_config_turn_suggestion_want_more_disconnect(client, monkeypatch):
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

    async def fake_expand(_ctx, _user, suggestion):  # noqa: ANN001
        return {"title": suggestion["title"], "detail": "展开正文", "citations": [], "token_usage": {}}

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    monkeypatch.setattr(suggestion_module, "expand_suggestion", fake_expand)

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
        assert frame["type"] == "suggestion"
        assert frame["suggestion"]["title"] == "RAG"
        # Structured citations with real source ids — the client never sees an sNN handle.
        assert frame["suggestion"]["citations"] == [
            {"source_id": SRC, "block_start": 1, "block_end": 2}
        ]

        ws.send_json({"type": "want_more", "suggestion": frame["suggestion"]})
        detail = ws.receive_json()
        assert detail["type"] == "suggestion_detail"
        assert detail["title"] == "RAG"
        assert detail["detail"] == "展开正文"

    assert seen["user"] == "u-ws"
    assert seen["focus"] == "other"
    assert seen["turns"] == ["我们在聊 RAG"]
    assert seen["label_map_passed"] is True


def test_a_card_already_shown_this_connection_is_not_sent_again(client, monkeypatch):
    """Server-side dedup over the socket. The second evaluation re-emits RAG and adds
    HNSW; only HNSW may reach the client."""
    rounds = [result(resolved("RAG")), result(resolved("RAG"), resolved("HNSW"))]

    async def fake_eval(*_args, **_kwargs):
        return rounds.pop(0)

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        assert ws.receive_json()["suggestion"]["title"] == "RAG"

        ws.send_json(turn("第二轮"))
        second = ws.receive_json()
        assert second["type"] == "suggestion"
        assert second["suggestion"]["title"] == "HNSW"  # RAG was dropped, not re-sent


def test_a_reconnecting_client_restores_its_own_already_shown(client, monkeypatch):
    """The client is the dedup authority: after a deploy drops every connection, the card
    list it replays in `config` is the only thing that stops the owner re-reading cards."""

    async def fake_eval(*_args, **_kwargs):
        return result(resolved("RAG"), resolved("HNSW"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)

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
        assert frame["suggestion"]["title"] == "HNSW"


def test_an_evaluation_failure_is_an_error_frame_not_a_dropped_socket(client, monkeypatch):
    """A background listener degrades to silence; it never 500s onto a pair of context clients and
    it never takes the connection down with it."""
    calls = {"n": 0}

    async def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("qdrant unreachable")
        return result(resolved("RAG"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", flaky)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "qdrant unreachable" in err["detail"]

        ws.send_json(turn("第二轮"))  # the same connection still works
        assert ws.receive_json()["suggestion"]["title"] == "RAG"


def test_a_malformed_frame_errors_without_dropping_the_connection(client, monkeypatch):
    async def fake_eval(*_args, **_kwargs):
        return result(resolved("RAG"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_text("not json at all")
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "teleport"})
        unknown = ws.receive_json()
        assert unknown["type"] == "error"
        assert "unknown message type" in unknown["detail"]

        ws.send_json({"type": "want_more"})  # no suggestion payload
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "config", "focus": "everyone"})
        bad_focus = ws.receive_json()
        assert bad_focus["type"] == "error"
        assert "unknown suggestion focus" in bad_focus["detail"]

        ws.send_json(turn("仍然可用"))  # still alive after four bad frames
        assert ws.receive_json()["type"] == "suggestion"


def test_flush_evaluates_inside_the_quiet_period(client, monkeypatch):
    """`flush` is the client's override for "ask now" — the quiet period exists to
    coalesce transcript chatter, not to overrule an explicit request."""

    async def counting(*args, **kwargs):
        counting.n += 1
        return result(resolved(f"round-{counting.n}"))

    counting.n = 0
    monkeypatch.setattr(suggestion_module, "run_evaluation", counting)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 3600})  # effectively never again
        ws.receive_json()

        ws.send_json(turn("第一轮"))
        assert ws.receive_json()["suggestion"]["title"] == "round-1"

        ws.send_json(turn("第二轮"))  # would wait an hour on its own
        ws.send_json({"type": "flush"})
        assert ws.receive_json()["suggestion"]["title"] == "round-2"


def test_silence_produces_no_frames(client, monkeypatch):
    """Zero suggestions must send nothing at all — an "I have nothing" frame arriving every few
    seconds is the opposite of a passive context feature."""

    async def silent(*_args, **_kwargs):
        return result()

    async def fake_expand(_ctx, _user, suggestion):  # noqa: ANN001
        return {"title": "x", "detail": "d", "citations": [], "token_usage": {}}

    monkeypatch.setattr(suggestion_module, "run_evaluation", silent)
    monkeypatch.setattr(suggestion_module, "expand_suggestion", fake_expand)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()
        ws.send_json(turn("闲聊，没有值得提示的东西"))
        # Nothing is emitted for the evaluation; the next frame is the answer to a LATER
        # request, which can only arrive if no suggestion/done/idle frame was queued ahead of it.
        ws.send_json({"type": "want_more", "suggestion": {"title": "x"}})
        assert ws.receive_json()["type"] == "suggestion_detail"


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
    passive clients never pay for it."""

    async def silent(*_args, **_kwargs):
        r = result()
        object.__setattr__(r, "dropped", {"uncited": 2, "low_confidence": 1})
        return r

    monkeypatch.setattr(suggestion_module, "run_evaluation", silent)

    with client.websocket_connect(PATH) as ws:
        assert ws.receive_json()["stats"] is False  # default, echoed in `ready`

        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        assert ws.receive_json()["stats"] is True

        ws.send_json(turn("闲聊，没有值得提示的东西"))
        frame = ws.receive_json()

    # Fires even though the evaluation produced nothing — that is the case you most need
    # it for, and the one a field on the `suggestion` frame could never cover.
    assert frame["type"] == "stats"
    assert frame["delivered"] == 0
    assert frame["dropped"] == {"uncited": 2, "low_confidence": 1}


def test_a_tick_reports_which_door_closed_and_what_each_stage_spent(client, monkeypatch):
    """Silence is the steady state, so "why did nothing fire" is what this socket is asked
    most — and after the redesign the answer is a skip REASON and a per-stage breakdown, not
    a set of gate counters that a tick which never retrieved would leave all zero."""

    async def skipped(*_args, **_kwargs):
        return result(
            skipped="small_talk",
            intent="",
            worth=1,
            stages=(
                StageTiming(name="discover", ms=1711),
                StageTiming(name="retrieve", ms=0, status="skipped"),
                StageTiming(name="pick", ms=0, status="skipped"),
                StageTiming(name="total", ms=1711),
            ),
        )

    monkeypatch.setattr(suggestion_module, "run_evaluation", skipped)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json(turn("中午吃什么"))
        frame = ws.receive_json()

    assert frame["type"] == "stats"
    assert frame["skipped"] == "small_talk"
    assert frame["delivered"] == 0
    by_name = {s["name"]: s for s in frame["stages"]}
    assert by_name["discover"]["ms"] == 1711
    assert by_name["retrieve"]["status"] == "skipped", "a skip touched no index"
    assert by_name["pick"]["status"] == "skipped", "and spent no second call"


def test_an_older_clients_policy_field_names_are_tolerated(client, monkeypatch):
    """`turn_window` was renamed and `max_suggestions` stopped meaning anything. A client
    built against the old wire must keep working: the rename still lands where it meant to,
    the dead field is ignored, and neither produces an error frame."""

    async def silent(*_args, **_kwargs):
        return result()

    monkeypatch.setattr(suggestion_module, "run_evaluation", silent)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "turn_window": 5, "max_suggestions": 3})
        ready = ws.receive_json()

    assert ready["type"] == "ready", "not an error frame"
    assert ready["max_pending_turns"] == 5, "the old name still lands where it meant to"
    assert "max_suggestions" not in ready


def test_a_card_carries_its_evidence_and_subject_onto_the_wire(client, monkeypatch):
    """Two text fields with two different authors: the lede a model wrote, and the verbatim
    material nothing rewrote. A client that could not tell them apart would have to present
    a guess as if the library had said it."""

    async def one(*_args, **_kwargs):
        card = resolved("Lumenlab")
        object.__setattr__(card, "evidence", "- 逐字证据一行")
        object.__setattr__(card, "subject", "projects/lumenlab.md")
        return result(card)

    monkeypatch.setattr(suggestion_module, "run_evaluation", one)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()
        ws.send_json(turn("说到 Lumenlab"))
        frame = ws.receive_json()

    card = frame["suggestion"]
    assert card["body"] == "解释", "the lede"
    assert card["evidence"] == "- 逐字证据一行", "and the evidence, unmerged"
    assert card["subject"] == "projects/lumenlab.md"


def test_want_more_echoes_the_clients_ref_on_both_outcomes(client, monkeypatch):
    """Without a correlation id a failed expansion names no request, so a client cannot
    tell WHICH card failed — it has to reset every pending expansion at once. Matching on
    `title` is the other trap: it works only because title doubles as the dedup key."""
    calls: list[dict] = []

    async def expand(_ctx, _user, suggestion):  # noqa: ANN001
        calls.append(suggestion)
        if suggestion.get("title") == "boom":
            raise ValueError("nope")
        return {"title": suggestion.get("title"), "detail": "d", "citations": [], "token_usage": {}}

    monkeypatch.setattr(suggestion_module, "expand_suggestion", expand)

    with client.websocket_connect(PATH) as ws:
        ws.receive_json()

        ws.send_json({"type": "want_more", "suggestion": {"title": "ok"}, "ref": "card-7"})
        good = ws.receive_json()
        assert good["type"] == "suggestion_detail"
        assert good["ref"] == "card-7"

        ws.send_json({"type": "want_more", "suggestion": {"title": "boom"}, "ref": "card-9"})
        bad = ws.receive_json()
        assert bad["type"] == "error"
        assert bad["ref"] == "card-9"  # the failure names its own request

    assert [c["title"] for c in calls] == ["ok", "boom"]


# ─────────────────────────────────── the glance short-circuit on the socket
#
# The provisional card goes out on THIS tick's seq — the same slot the full card lands in —
# so an upgrade is a replacement in place rather than a second bubble.


def glanced(title: str = "Lumenlab") -> ResolvedSuggestion:
    return ResolvedSuggestion(
        kind="glance",
        title=title,
        body="Lumenlab 是企业异构数据的记忆基础设施。",
        trigger="触发",
        confidence=10,
        citations=[Citation(source_id=SourceId(SRC), block_start=4, block_end=5)],
        subject="projects/lumenlab.md",
        subject_label="lumenlab",
        provisional=True,
    )


def test_the_provisional_card_reaches_the_client_before_the_tick_settles(client, monkeypatch):
    order: list[str] = []

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        await kwargs["on_glance"](glanced())
        order.append("glance sent")
        return result(glance=glanced(), glance_state="hit", glance_outcome="alone")

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()
        ws.send_json(turn("lumenlab 是什么"))
        early = ws.receive_json()
        assert early["type"] == "suggestion"
        assert early["provisional"] is True
        assert early["suggestion"]["kind"] == "glance"
        assert early["suggestion"]["provisional"] is True
        assert early["suggestion"]["citations"] == [
            {"source_id": SRC, "block_start": 4, "block_end": 5}
        ]
        # …and the settling frame, on the SAME seq.
        settle = ws.receive_json()
        assert settle["type"] == "upgrade"
        assert settle["seq"] == early["seq"]
        assert settle["suggestion"] is None, "nothing else came: settle in place"
    assert order == ["glance sent"]


def test_a_full_card_about_the_same_subject_arrives_as_an_upgrade_and_not_a_second_bubble(
    client, monkeypatch
):
    full = ResolvedSuggestion(
        kind="concept",
        title="Lumenlab",
        body="完整的卡片",
        trigger="触发",
        confidence=9,
        citations=[Citation(source_id=SourceId(SRC), block_start=1, block_end=2)],
        subject="projects/lumenlab.md",
        subject_label="lumenlab",
    )

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        await kwargs["on_glance"](glanced())
        return result(full, glance=glanced(), glance_state="hit", glance_outcome="upgraded")

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json(turn("lumenlab 是什么"))
        assert ws.receive_json()["provisional"] is True
        frame = ws.receive_json()
        assert frame["type"] == "upgrade"
        assert frame["suggestion"]["title"] == "Lumenlab"
        assert frame["suggestion"]["provisional"] is False
        # …and NO ordinary `suggestion` frame for the same card: the queue does not grow.
        # `stats` closes every tick, so the next frame being it IS that assertion.
        closing = ws.receive_json()
        assert closing["type"] == "stats" and closing["delivered"] == 1


def test_a_full_card_about_another_subject_settles_the_glance_and_queues_beside_it(
    client, monkeypatch
):
    other = resolved("HNSW")

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        await kwargs["on_glance"](glanced())
        return result(other, glance=glanced(), glance_state="hit", glance_outcome="settled")

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0})
        ws.receive_json()
        ws.send_json(turn("lumenlab 是什么"))
        assert ws.receive_json()["provisional"] is True
        settle = ws.receive_json()
        assert settle["type"] == "upgrade" and settle["suggestion"] is None
        queued = ws.receive_json()
        assert queued["type"] == "suggestion" and queued["suggestion"]["title"] == "HNSW"


def test_the_glance_is_recorded_once_and_never_delivered_twice_for_one_subject(
    client, monkeypatch
):
    """Repetition protection applies to a glance like any other card — and an upgrade about
    the same subject does not count it a second time."""
    seen: list = []

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        seen.append(tuple(sorted(r.key for r in kwargs["ledger"].records())))
        if len(seen) == 1:
            await kwargs["on_glance"](glanced())
            return result(glance=glanced(), glance_state="hit", glance_outcome="alone")
        return result()

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json(turn("lumenlab 是什么"))
        ws.receive_json()  # the provisional card
        ws.receive_json()  # its settling frame
        assert ws.receive_json()["type"] == "stats"
        ws.send_json(turn("再说说 lumenlab"))
        assert ws.receive_json()["type"] == "stats", "the second tick ran and said nothing"
    assert seen[0] == (), "the first tick's ledger knew nothing"
    assert seen[1] == ("projects/lumenlab.md",), "delivery recorded it, once"


def test_a_tick_reports_whether_it_glanced_and_how_it_ended(client, monkeypatch):
    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        await kwargs["on_glance"](glanced())
        return result(
            glance=glanced(), glance_state="hit", glance_outcome="alone", glance_ms=41.5
        )

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json(turn("lumenlab 是什么"))
        ws.receive_json()  # provisional
        ws.receive_json()  # upgrade
        stats = ws.receive_json()
        assert stats["type"] == "stats"
        assert stats["glance"] == {"state": "hit", "outcome": "alone", "ms": 41.5}


def test_a_tick_that_did_not_glance_says_so(client, monkeypatch):
    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        return result(resolved("RAG"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "quiet_period": 0, "stats": True})
        ws.receive_json()
        ws.send_json(turn("我们在聊 RAG"))
        card = ws.receive_json()
        # The frame-level flag is set only on the early emission; an ordinary card carries
        # neither it nor a provisional mark of its own.
        assert card["type"] == "suggestion" and "provisional" not in card
        assert card["suggestion"]["provisional"] is False
        assert ws.receive_json()["glance"]["state"] == "miss"


def test_a_reset_frame_re_acks_ready_and_the_next_tick_carries_nothing_from_before(
    client, monkeypatch
):
    """The transport half of 「清空对话」.

    The client empties its own stores; this frame is how the SERVER'S half goes with them.
    Without it the connection keeps the ledger, the context tail and the mined list of a
    conversation the reader has thrown away, and the next tick is answered against them —
    which is how a subject raised again after a clear came back skipped `already_mined`.

    What is asserted here is the transport contract only: the frame is acked with a fresh
    `ready`, and the plan the next tick receives carries no turn, no context and no mined
    card from before the clear. What that emptiness MEANS to the session is pinned with an
    injected clock in `test_live_context_session.py`."""
    plans: list = []

    async def fake_eval(_ctx, _user, plan, **kwargs):  # noqa: ANN001
        plans.append(plan)
        return result(resolved("Lumenlab"))

    monkeypatch.setattr(suggestion_module, "run_evaluation", fake_eval)

    with client.websocket_connect(PATH) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "config", "quiet_period": 0})
        assert ws.receive_json()["type"] == "ready"

        ws.send_json(turn("Lumenlab 是什么"))
        assert ws.receive_json()["type"] == "suggestion"

        ws.send_json({"type": "reset"})
        acked = ws.receive_json()
        assert acked["type"] == "ready", "the clear is acknowledged, not answered with silence"
        assert acked["quiet_period"] == 0, "the policy survives; only the conversation goes"

        ws.send_json(turn("Lumenlab 是什么"))
        assert ws.receive_json()["type"] == "suggestion"

    first, second = plans
    assert [t.text for t in first.turns] == ["Lumenlab 是什么"]
    assert first.already_shown == () and first.context == ()
    assert [t.text for t in second.turns] == ["Lumenlab 是什么"]
    assert second.context == (), "the cleared turn is not read as context for the new one"
    assert second.already_shown == (), "nor is the card it produced still a mined subject"
    assert second.seq == 1, "the conversation's own numbering starts over"
