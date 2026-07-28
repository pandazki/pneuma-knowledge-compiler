"""Live Context — two client-facing transports plus the vocabulary endpoint.

**Shape A, `POST /live-context/stream`** — one-shot SSE. The client posts a whole
transcript window, the server emits one `event: suggestion` per surviving card and then
`event: done`. No session, no dedup, no throttling: that is the point of it. Built for
evals, for debugging, and for any client that is not a pair of context clients.

**Shape B, `WS /live-context/ws`** — the long-lived connection used by passive clients. The
client pushes turns; the server holds the sliding window, the quiet period and the
in-connection dedup. All of that policy lives in `live_context/session.py` as a pure
clock-injected state machine — this module is the transport that feeds it.

Wire protocol (JSON text frames both directions):

    client → server
      {"type": "config", "focus": "general"|"owner"|"other", "min_confidence": 1-10,
       "max_suggestions": int, "turn_window": int, "quiet_period": float,
       "briefing_id": str|"", "turns": [Turn], "already_shown": [{kind, title}],
       "stats": bool}
          Every field optional; absent means unchanged. `turns` + `already_shown` are
          the RECONNECT path — the client is the dedup authority and restores both.
      {"type": "turn", "speaker": str, "text": str,
       "role": "owner"|"other"|"unknown", "speaker_id": str|null, "at": iso8601|null}
      {"type": "flush"}                     — evaluate now, skipping the quiet period
      {"type": "want_more", "suggestion": ContextSuggestion, "ref": str|null}
          The client hands a card it received back. `ref` is the client's own
          correlation id, echoed on both `suggestion_detail` and `error` — without it a
          failed expansion names no request and the client cannot tell which card
          it belonged to.
      {"type": "ping"}                      — ignored; a client-side keepalive

    server → client
      {"type": "ready", "focus": ..., "min_confidence": ..., "max_suggestions": ...,
       "turn_window": ..., "quiet_period": ..., "briefing_id": ..., "stats": bool}
          On accept, and again after every `config`, echoing the EFFECTIVE policy.
      {"type": "stats", "seq": int, "focus": str, "delivered": int,
       "dropped": {...}, "token_usage": {...}}
          OFF unless the client sets `stats: true` in `config`. When on: one per
          evaluation, INCLUDING the ones that produced nothing — an evaluation with
          zero survivors emits no `suggestion` frame at all, and that is exactly when the
          gate counters are worth having. Off by default because a quiet connection
          has to stay actually quiet: that is the property the context clients rely on.
      {"type": "suggestion", "seq": int, "suggestion": {kind, title, body, trigger, confidence,
       citations: [{source_id, block_start, block_end}]}}
      {"type": "suggestion_detail", "ref": ..., "title": ..., "detail": ..., "citations": [...],
       "token_usage": {...}}
      {"type": "error", "detail": str, "ref": str|null}
          Never fatal; the connection stays open. `ref` is present when the failure
          belongs to a specific `want_more`.
      {"type": "ping"}                      — ~30s server keepalive

The server pings because SILENCE IS THIS FEATURE'S STEADY STATE: a connection with no
relevant context is working correctly, and Cloudflare would drop it at ~100s idle.
Sending is its own task behind a bounded drop-oldest queue — a slow client must never be
able to stall an evaluation, and a suggestion that has aged out before delivery is worth
less than the one behind it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.suggestion import (
    CONTEXT_FOCUSES,
    SUGGESTION_KINDS,
    ContextFocusOption,
    SuggestionKindOption,
    focus_option,
)
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.suggestion import (
    DEFAULT_MAX_SUGGESTIONS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_TURN_WINDOW,
)
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...live_context.engine import expand_suggestion, load_briefing_pack, run_evaluation
from ...live_context.session import LiveContextSession, EvaluationPlan
from .v1 import _render_profile

# Own routers, mounted alongside v1's in `create_app`. Same prefixes, so the owner-scoped
# paths land under /v1/users/{user_id}/... exactly as docker/nginx.conf's WebSocket
# location expects.
router = APIRouter(prefix="/v1/users/{user_id}")
root_router = APIRouter(prefix="/v1")

# Server keepalive interval. Well under Cloudflare's ~100s idle timeout.
PING_INTERVAL = 30.0

# Outbound frames held for a slow client before the oldest is dropped.
OUTBOUND_LIMIT = 32


def put_drop_oldest(queue: asyncio.Queue, item: Any) -> bool:
    """Enqueue `item`, evicting the oldest frames if the queue is full. True if any went.

    Synchronous and non-blocking on purpose: this is called from the evaluation path, and
    an `await queue.put()` there would let a client that has stopped reading apply
    backpressure all the way up into the LLM call. Dropping is the correct failure: an
    stale suggestion after the workstream moved on is worse than no suggestion."""
    dropped = False
    while queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - only under concurrent drain
            break
        dropped = True
    queue.put_nowait(item)
    return dropped


# ---------------------------------------------------------------------- wire models


class TurnIn(BaseModel):
    speaker: str = ""
    text: str
    role: str = "unknown"
    speaker_id: str | None = None
    at: datetime | None = None

    def to_turn(self) -> ConversationTurn:
        return ConversationTurn(
            speaker=self.speaker,
            text=self.text,
            role=self.role,  # type: ignore[arg-type]
            speaker_id=self.speaker_id,
            at=self.at,
        )


class LiveContextStreamIn(BaseModel):
    turns: list[TurnIn] = []
    focus: str = "general"
    min_confidence: int = DEFAULT_MIN_CONFIDENCE
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS
    turn_window: int = DEFAULT_TURN_WINDOW
    # Briefing scope: evaluate against this stored briefing's frozen pack (zero retrieval).
    briefing_id: str | None = None
    already_shown: list[dict[str, Any]] = []
    as_of: str | None = None


def _suggestion_out(suggestion: Any) -> dict[str, Any]:
    """One card on the wire. `sNN` handles are already gone — core resolved and stripped
    them before this point, and a handle is only meaningful inside its own evaluation."""
    return {
        "kind": suggestion.kind,
        "title": suggestion.title,
        "body": suggestion.body,
        "trigger": suggestion.trigger,
        "confidence": suggestion.confidence,
        "citations": [
            {
                "source_id": str(c.source_id),
                "block_start": c.block_start,
                "block_end": c.block_end,
            }
            for c in suggestion.citations
        ],
    }


# ------------------------------------------------------------------- the vocabularies


@root_router.get("/live-context/focuses", response_model=list[ContextFocusOption])
async def list_context_focuses() -> list[ContextFocusOption]:
    """The suggestion focus registry — core is the single source of truth and the UI fetches it
    rather than inlining a copy (same discipline as `GET /v1/intake/archetypes`)."""
    return CONTEXT_FOCUSES


@root_router.get("/live-context/kinds", response_model=list[SuggestionKindOption])
async def list_suggestion_kinds() -> list[SuggestionKindOption]:
    """The suggestion kind registry. Served for the same reason as the focuses: the client
    renders `concept` and `fact` differently, so it needs the closed set, and a private
    copy in the frontend is a third place for it to drift."""
    return SUGGESTION_KINDS


# ------------------------------------------------------------------ shape A: one-shot


def _plan_from(body: LiveContextStreamIn) -> EvaluationPlan:
    return EvaluationPlan(
        seq=0,
        turns=tuple(t.to_turn() for t in body.turns),
        focus=body.focus,  # type: ignore[arg-type]
        min_confidence=body.min_confidence,
        max_suggestions=body.max_suggestions,
        turn_window=body.turn_window,
        briefing_id=body.briefing_id,
        already_shown=tuple(body.already_shown),
        started_at=0.0,
    )


@router.post("/live-context/stream")
async def live_context_stream(
    user_id: str, body: LiveContextStreamIn, request: Request
) -> StreamingResponse:
    """One evaluation over a posted transcript window, streamed as SSE.

    Same machinery as `/recall/stream`: a sibling `asyncio.Task` produces into an
    unbounded `asyncio.Queue` while the response generator drains it, and the generator's
    `finally` cancels the producer so an abandoned stream cannot leave an evaluation
    burning LLM calls with nobody left to read them.

    Unbounded queue here (unlike the WS path): this producer runs exactly one evaluation
    and puts at most a handful of frames, and the consumer is the response itself."""
    ctx = request.app.state.ctx
    try:
        focus_option(body.focus)  # closed vocabulary — an unknown focus is a 400, not a guess
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = _plan_from(body)
    as_of = datetime.fromisoformat(body.as_of) if body.as_of else datetime.now(timezone.utc)
    events: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            pack = None
            if body.briefing_id:
                pack = await load_briefing_pack(ctx, user_id, body.briefing_id)
            result = await run_evaluation(
                ctx,
                user_id,
                plan,
                profile=await _render_profile(ctx, UserId(user_id)),
                pack=pack,
                as_of=as_of,
            )
            for suggestion in result.suggestions:
                events.put_nowait(("suggestion", _suggestion_out(suggestion)))
            events.put_nowait(
                (
                    "done",
                    {
                        "focus": plan.focus,
                        "count": len(result.suggestions),
                        "dropped": result.dropped,
                        "token_usage": result.token_usage,
                        "as_of": as_of.isoformat(),
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 — a live stream surfaces failure in-band
            events.put_nowait(("error", {"detail": str(exc)}))

    task = asyncio.create_task(produce())

    async def stream():
        try:
            while True:
                kind, payload = await events.get()
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if kind in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------- shape B: the socket


@router.websocket("/live-context/ws")
async def live_context_ws(websocket: WebSocket, user_id: str) -> None:
    """The long-lived listening connection. See the module docstring for the protocol."""
    await websocket.accept()
    ctx = websocket.app.state.ctx
    loop = asyncio.get_running_loop()
    session = LiveContextSession()
    outbound: asyncio.Queue = asyncio.Queue(maxsize=OUTBOUND_LIMIT)
    # Set whenever something might have made an evaluation due. The runner waits on this
    # instead of polling, so an idle connection costs one suspended task and no wakeups.
    wake = asyncio.Event()
    side_tasks: set[asyncio.Task] = set()
    # The owner profile does not change mid-conversation, so it is resolved once per
    # connection rather than once per evaluation — this feature is latency-shaped and a PG
    # round trip on every round buys nothing. A one-slot list, so the closure can fill it.
    profile: list[str | None] = []
    # Telemetry opt-in, transport-level rather than session policy: it changes what the
    # socket says about an evaluation, not how the evaluation is decided. Kept off the
    # pure state machine on purpose.
    send_stats = [False]

    def emit(frame: dict[str, Any]) -> None:
        put_drop_oldest(outbound, frame)

    def ready_frame() -> dict[str, Any]:
        p = session.policy
        return {
            "type": "ready",
            "focus": p.focus,
            "min_confidence": p.min_confidence,
            "max_suggestions": p.max_suggestions,
            "turn_window": p.turn_window,
            "quiet_period": p.quiet_period,
            "briefing_id": p.briefing_id,
            "stats": send_stats[0],
        }

    async def send_loop() -> None:
        while True:
            frame = await outbound.get()
            await websocket.send_json(frame)

    async def ping_loop() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            emit({"type": "ping"})

    async def evaluate(plan: EvaluationPlan) -> None:
        pack = None
        if plan.briefing_id:
            pack = await load_briefing_pack(ctx, user_id, plan.briefing_id)
        if not profile:
            profile.append(await _render_profile(ctx, UserId(user_id)))
        result = await run_evaluation(
            ctx,
            user_id,
            plan,
            label_map=session.label_map,
            profile=profile[0],
            pack=pack,
        )
        # The session dedup runs on the RESULT, layered over core's within-evaluation one.
        delivered = session.complete(plan.seq, result.suggestions, now=loop.time())
        for suggestion in delivered:
            emit({"type": "suggestion", "seq": plan.seq, "suggestion": _suggestion_out(suggestion)})
        # Its own frame rather than a field on `suggestion`: the evaluation that produced ZERO
        # cards emits no `suggestion` frame at all, and that is precisely the one you need the
        # gate counters for — "why did nothing fire" is the question this socket gets
        # asked most, because silence is the steady state.
        #
        # OFF by default, and that default is load-bearing. Emitting telemetry every
        # evaluation would mean a quiet connection is never actually quiet, which breaks
        # the property the context clients rely on (and which `test_silence_produces_no_frames`
        # guards). Debug surfaces opt in; passive clients need not pay for them.
        if send_stats[0]:
            emit(
                {
                    "type": "stats",
                    "seq": plan.seq,
                    "focus": plan.focus,
                    "delivered": len(delivered),
                    "dropped": dict(result.dropped),
                    "token_usage": dict(result.token_usage),
                }
            )

    async def run_loop() -> None:
        while True:
            due = session.due_in(now=loop.time())
            if due is None:
                await wake.wait()
                wake.clear()
                continue
            if due > 0.0:
                try:
                    await asyncio.wait_for(wake.wait(), due)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
                wake.clear()
                continue
            plan = session.begin(now=loop.time())
            if plan is None:  # pragma: no cover - due==0 implies a plan
                continue
            try:
                await evaluate(plan)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a listener degrades, never dies
                session.abandon(plan.seq, now=loop.time())
                emit({"type": "error", "detail": str(exc)})
            # Turns that landed mid-evaluation set `dirty`; re-check now that we are idle.
            wake.set()

    async def want_more(suggestion: dict[str, Any], ref: str | None) -> None:
        """`ref` is the client's own correlation id, echoed back on BOTH outcomes.

        Without it a client has no way to tell which expansion failed — the error frame
        names no request — so one failure forces it to either guess or reset every pending
        expansion at once. Matching on `title` instead is the other trap: it happens to
        work because title is also the dedup key, which makes it fragile by coincidence
        rather than by design."""
        try:
            detail = await expand_suggestion(ctx, user_id, suggestion)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            emit({"type": "error", "detail": str(exc), "ref": ref})
            return
        emit({"type": "suggestion_detail", "ref": ref, **detail})

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        side_tasks.add(task)
        task.add_done_callback(side_tasks.discard)

    workers = [asyncio.create_task(c) for c in (send_loop(), ping_loop(), run_loop())]
    emit(ready_frame())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError("frame must be a JSON object")
            except ValueError as exc:
                emit({"type": "error", "detail": f"bad frame: {exc}"})
                continue

            kind = msg.get("type")
            try:
                if kind == "config":
                    session.configure(
                        focus=msg.get("focus"),
                        min_confidence=msg.get("min_confidence"),
                        max_suggestions=msg.get("max_suggestions"),
                        turn_window=msg.get("turn_window"),
                        quiet_period=msg.get("quiet_period"),
                        briefing_id=msg.get("briefing_id"),
                        turns=(
                            [TurnIn(**t).to_turn() for t in msg["turns"]]
                            if msg.get("turns") is not None
                            else None
                        ),
                        already_shown=msg.get("already_shown"),
                    )
                    if msg.get("stats") is not None:
                        send_stats[0] = bool(msg["stats"])
                    emit(ready_frame())
                    wake.set()
                elif kind == "turn":
                    fields = {k: v for k, v in msg.items() if k != "type"}
                    session.add_turn(TurnIn(**fields).to_turn())
                    wake.set()
                elif kind == "flush":
                    session.flush()
                    wake.set()
                elif kind == "want_more":
                    suggestion = msg.get("suggestion")
                    if not isinstance(suggestion, dict):
                        raise ValueError("want_more requires a `suggestion` object")
                    ref = msg.get("ref")
                    spawn(want_more(suggestion, str(ref) if ref is not None else None))
                elif kind in ("ping", "pong"):
                    pass
                else:
                    raise ValueError(f"unknown message type: {kind!r}")
            except Exception as exc:  # noqa: BLE001 — one bad frame never drops the socket
                emit({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        for task in [*workers, *side_tasks]:
            task.cancel()
