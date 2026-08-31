"""Live Context — two client-facing transports plus the vocabulary endpoints.

**Shape A, `POST /live-context/stream`** — one-shot SSE. The client posts a whole
transcript window, the server emits one `event: suggestion` per surviving card and then
`event: done`. No session, no dedup, no throttling: that is the point of it. Built for
evals, for debugging, and for any client that is not a pair of context clients.

**Shape B, `WS /live-context/ws`** — the long-lived connection used by passive clients. The
client pushes turns; the server holds the PENDING run, the quiet period, the in-connection
dedup and the subject ledger. All of that policy lives in `live_context/session.py` as a
pure clock-injected state machine — this module is the transport that feeds it.

Wire protocol (JSON text frames both directions):

    client → server
      {"type": "config", "focus": "general"|"owner"|"other",
       "density": "eager"|"balanced"|"quiet",   # absent/unknown => "balanced"
       "min_confidence": 1-10,
       "max_pending_turns": int, "quiet_period": float, "web_search": bool,
       "briefing_id": str|"", "turns": [Turn],
       "already_shown": [{kind, title, body?, subject?, subject_label?}],
       "stats": bool}
          Every field optional; absent means unchanged. `turns` + `already_shown` are
          the RECONNECT path — the client is the dedup authority and restores both, and a
          replayed `subject` also restores the ledger so a reconnect does not re-introduce
          a subject the reader has met. `turn_window` is accepted as the old name of
          `max_pending_turns`; `max_suggestions` is accepted and ignored (the lane delivers
          exactly one card per tick).
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
      {"type": "ready", "focus": ..., "density": ..., "min_confidence": ...,
       "max_pending_turns": ..., "quiet_period": ..., "web_search": bool,
       "briefing_id": ..., "stats": bool}
          On accept, and again after every `config`, echoing the EFFECTIVE policy.
          `web_search` in particular is the EFFECTIVE value and not the request: a client
          may ask for the supplementary internet path, and it is granted only where the
          deployment enabled one (`PNEUMA_KNOWLEDGE_LIVE_WEB_SEARCH`). A client that asked
          and reads `false` back has been told no, mechanically, rather than left to
          discover it from the absence of web cards.
      {"type": "stats", "seq": int, "focus": str, "delivered": int, "turns": int,
       "token_usage": {...}, "skipped": str, "intent": str, "worth": int,
       "plan": [str], "rejected": [str], "chosen": int,
       "candidates": [{index, kind, title, subject, origin, provenance, citations}],
       "web": {"tier": "off"|"planned"|"fallback", "searches": int, "cost": float,
                "pages": int},
       "stages": [{name, ms, status, detail}]}
          OFF unless the client sets `stats: true` in `config`. When on: one per
          evaluation, INCLUDING the ones that produced nothing — an evaluation with
          zero survivors emits no `suggestion` frame at all, and that is exactly when
          `skipped` is worth having. `skipped` is "" on a delivery and otherwise names
          which door closed: a discover reason (`small_talk` / `already_mined` /
          `nothing_new`), `low_worth`, `no_plan`, `no_candidates`, `no_coverage`,
          `none_chosen`, `low_confidence`, `uncited`, `duplicate`, `unparsed`,
          `pick_failed`. `no_coverage` is the pick's own `choice: 0` — the library holds
          nothing that answers the intent — and is kept apart from `low_confidence` (a weak
          answer held back) and from `none_chosen` (a malformed index) because the three
          look identical on a silent tick and mean different things. Off by default because a
          quiet connection has to stay actually quiet: that is the property the context
          clients rely on.
      {"type": "suggestion", "seq": int, "suggestion": {kind, title, body, evidence,
       subject, trigger, confidence, citations: [{source_id, block_start, block_end}],
       web_citations: [{title, url}]}}
          `body` is the lede — one or two sentences guessing what the reader needs.
          `evidence` is the verbatim material underneath it, rendered mechanically and
          shown collapsed. Two fields because they have two different authors.
          TWO CITATION SHAPES, and which one a card carries is stated by `kind` rather
          than guessed at: `concept` / `fact` carry `citations` (the one addressing scheme
          over the owner's own material — source id + block span, I4) and `web` carries
          `web_citations` (page title + URL). A card never carries both. The evidence
          surface is otherwise identical across the two: same numbered rows, same collapsed
          section, and the pick's citation subset selects into either list by the same
          index rule. Only the affordance differs — a source span opens in-app, a URL
          opens a new tab.
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
import logging
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.suggestion import (
    CONTEXT_FOCUSES,
    SUGGESTION_KINDS,
    ContextFocusOption,
    SuggestionKindOption,
    DEFAULT_DENSITY,
    coerce_density,
    focus_option,
)
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.live_pipeline import DEFAULT_MAX_PENDING_TURNS
from pneuma_knowledge_core.recall.suggestion import DEFAULT_MIN_CONFIDENCE
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pneuma_knowledge_core.recall.live_pipeline import SubjectLedger

from ...live_context.engine import expand_suggestion, load_briefing_pack, run_evaluation
from ...live_context.session import LiveContextSession, EvaluationPlan
from ...settings import get_settings
from .v1 import _render_profile

logger = logging.getLogger(__name__)

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
    #: `eager` | `balanced` | `quiet`. Absent or unknown ⇒ `balanced`.
    density: str = DEFAULT_DENSITY
    min_confidence: int = DEFAULT_MIN_CONFIDENCE
    max_pending_turns: int = DEFAULT_MAX_PENDING_TURNS
    # Allow the supplementary internet search on this request. Clamped against the
    # deployment's own knob below — asking is not granting.
    web_search: bool = False
    # Briefing scope: evaluate against this stored briefing's frozen pack (zero retrieval).
    briefing_id: str | None = None
    already_shown: list[dict[str, Any]] = []
    as_of: str | None = None
    # Accepted and ignored: an older client still sends them. `max_suggestions` stopped
    # meaning anything when the lane began delivering exactly one card per tick, and
    # `turn_window` was renamed to `max_pending_turns` when the window stopped being a
    # sliding tail. Tolerated rather than rejected — a 422 on a field nobody reads any more
    # would break a client for no gain.
    max_suggestions: int | None = None
    turn_window: int | None = None


def _suggestion_out(suggestion: Any) -> dict[str, Any]:
    """One card on the wire. `sNN` handles are already gone — core resolved and stripped
    them before this point, and a handle is only meaningful inside its own evaluation.

    `body` is the lede (the guessed need); `evidence` is the mechanically rendered verbatim
    material underneath it, which the client shows collapsed. They are two fields rather
    than one string because they have two different authors — a model wrote the first, and
    nothing wrote the second."""
    return {
        "kind": suggestion.kind,
        "title": suggestion.title,
        "body": suggestion.body,
        "evidence": getattr(suggestion, "evidence", "") or "",
        "subject": getattr(suggestion, "subject", "") or "",
        # The short human name for that subject. It travels because a reconnecting client
        # replays it, and without it the ledger digest would name a document PATH at the
        # discover stage instead of the thing a person calls it.
        "subject_label": getattr(suggestion, "subject_label", "") or "",
        "trigger": suggestion.trigger,
        "confidence": suggestion.confidence,
        # True only on a `glance` card that has not settled yet: a true sentence shown
        # early, with the tick still running behind it. The `upgrade` frame clears it.
        "provisional": bool(getattr(suggestion, "provisional", False)),
        "citations": [
            {
                "source_id": str(c.source_id),
                "block_start": c.block_start,
                "block_end": c.block_end,
            }
            for c in suggestion.citations
        ],
        # The second citation shape, always present as a list so a client tests a field
        # rather than sniffing for one. A `web` card fills this and leaves `citations`
        # empty; every other card does the reverse. See the module docstring.
        "web_citations": [
            {"title": c.title, "url": c.url}
            for c in getattr(suggestion, "web_citations", None) or []
        ],
    }


def _processing_out(result: Any) -> dict[str, Any]:
    """What one tick DID, for the debug stream and the web Processing tab.

    Silence is this feature's steady state, so "why did nothing fire" is the question this
    surface gets asked most — and after the redesign it has a real answer at three different
    depths: the stage never ran (`skipped` names which door closed), it ran and found
    nothing, or it ran, built candidates and the pick declined. All three are here, with
    per-stage milliseconds, so nobody has to infer any of it from a token count."""
    return {
        "skipped": result.skipped,
        # The glance short-circuit: whether the plan named a subject the library could show
        # instantly (`hit`/`miss`), how it ended once the pipeline settled, and — separately
        # from `total` — WHEN the provisional card left. The last one is the whole claim of
        # the mechanism, and a millisecond count folded into the total would not state it.
        "glance": {
            "state": result.glance_state,
            "outcome": result.glance_outcome,
            "ms": result.glance_ms,
        },
        # The posture this tick ran under. Reported beside the skip because the same turn is
        # a skip under `quiet` and a lookup under `eager` — a record showing only the skip
        # would make the difference look like model noise.
        "density": result.density,
        "dropped": dict(result.dropped),
        "intent": result.intent,
        "worth": result.worth,
        "plan": list(result.plan),
        "rejected": list(result.rejected),
        "candidates": [
            {
                "index": c.index,
                "kind": c.kind,
                "title": c.title,
                "subject": c.subject,
                "origin": c.origin,
                # Which POOL — `library` or `web` — as the pick stage was shown it. The
                # fine-grained `origin` above is the face; this is the two words the
                # contract's source-blind rule is about.
                "provenance": c.provenance,
                "citations": len(c.citations) or len(c.web_citations),
            }
            for c in result.candidates
        ],
        "chosen": result.chosen,
        # What the supplementary face did and what it cost. `tier` distinguishes the two
        # ways it can be reached — `planned` (discover asked, ran concurrently) from
        # `fallback` (discover did not ask, the library came back empty, so it ran after) —
        # because "the web answered" and "the web answered because nothing else did" are
        # different facts about the tick.
        "web": {
            "tier": result.web_tier,
            "searches": result.web_searches,
            "cost": result.web_cost,
            # Pages the searches named. Zero beside a non-zero cost is the one outcome that
            # would otherwise be invisible: a search that ran, was billed, and cited nothing,
            # so its answer was refused at construction and never became a candidate.
            "pages": result.web_pages,
        },
        "stages": [
            {"name": st.name, "ms": st.ms, "status": st.status, "detail": st.detail}
            for st in result.stages
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


def allow_web_search(ctx: Any, requested: Any) -> bool:
    """The client asked; the deployment answers. ONE place, both transports.

    Asking is not granting, and the clamp lives here rather than in the session because the
    session is a pure state machine that knows nothing about settings — so what it holds is
    already the effective value, and the `ready` echo is therefore the truth rather than a
    repetition of the request."""
    return bool(requested) and bool(getattr(ctx.settings, "live_web_search", False))


def _plan_from(body: LiveContextStreamIn, ctx: Any) -> EvaluationPlan:
    return EvaluationPlan(
        seq=0,
        turns=tuple(t.to_turn() for t in body.turns),
        focus=body.focus,  # type: ignore[arg-type]
        density=coerce_density(body.density),
        min_confidence=body.min_confidence,
        web_search=allow_web_search(ctx, body.web_search),
        # An older client's `turn_window` still lands where it meant to: the bound on how
        # much of the submitted window one evaluation reads.
        max_pending_turns=body.turn_window or body.max_pending_turns,
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

    plan = _plan_from(body, ctx)
    as_of = datetime.fromisoformat(body.as_of) if body.as_of else datetime.now(timezone.utc)
    events: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            pack = None
            if body.briefing_id:
                pack = await load_briefing_pack(ctx, user_id, body.briefing_id)
            # One-shot: no session, so the ledger is whatever the submitted `already_shown`
            # implies. That is the honest bound of a stateless evaluation — the caller is
            # the only thing that remembers this conversation.
            ledger = SubjectLedger()
            for shown in body.already_shown:
                subject = str(shown.get("subject") or "")
                if subject:
                    ledger.deliver(
                        subject,
                        str(shown.get("kind") or ""),
                        str(shown.get("subject_label") or subject),
                    )
            # SSE has one event stream and no seq to upgrade into, so the provisional card
            # is put on it the moment it exists — which is the whole point, since it lands a
            # retrieval before anything else can. What settles it here is the `done` event
            # the stream always ends with: `glance.outcome` says which ending happened.
            glanced: list[Any] = []

            async def send_glance(card: Any) -> None:
                glanced.append(card)
                events.put_nowait(("suggestion", _suggestion_out(card)))

            result = await run_evaluation(
                ctx,
                user_id,
                plan,
                profile=await _render_profile(ctx, UserId(user_id)),
                pack=pack,
                as_of=as_of,
                ledger=ledger,
                on_glance=send_glance,
            )
            for suggestion in result.suggestions:
                events.put_nowait(("suggestion", _suggestion_out(suggestion)))
            events.put_nowait(
                (
                    "done",
                    {
                        "focus": plan.focus,
                        "count": len(result.suggestions),
                        "token_usage": result.token_usage,
                        "as_of": as_of.isoformat(),
                        **_processing_out(result),
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
            "density": p.density,
            "min_confidence": p.min_confidence,
            "max_pending_turns": p.max_pending_turns,
            "quiet_period": p.quiet_period,
            # EFFECTIVE, not requested — see `allow_web_search`.
            "web_search": p.web_search,
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

        # The glance short-circuit's transport half. The card goes out on THIS tick's seq —
        # the same slot the full card will land in — so an upgrade is a replacement in place
        # rather than a second bubble, and the queue does not grow.
        glanced: list[Any] = []

        async def send_glance(card: Any) -> None:
            # Recorded in the ledger AT DELIVERY, like any other card: the reader has been
            # introduced to this subject whatever the rest of the tick does. An upgrade is
            # the same subject, so `deliver` is idempotent over it and nothing double-counts.
            glanced.append(card)
            session.glance_delivered(plan.seq, card)
            emit(
                {
                    "type": "suggestion",
                    "seq": plan.seq,
                    "provisional": True,
                    "suggestion": _suggestion_out(card),
                }
            )

        result = await run_evaluation(
            ctx,
            user_id,
            plan,
            label_map=session.label_map,
            profile=profile[0],
            pack=pack,
            ledger=session.ledger,
            on_glance=send_glance,
        )
        # The session dedup runs on the RESULT, layered over core's within-evaluation one.
        # The ledger is written here too, and only here: a result that outlived its own
        # evaluation must not be able to teach the session anything.
        delivered = session.complete(
            plan.seq,
            result.suggestions,
            now=loop.time(),
            touched=result.touched,
            asked=result.asked,
        )
        # A provisional card always gets its settling frame, whichever ending happened —
        # the shimmer is the client's word for "this tick has not finished", and a tick that
        # finished without saying so would leave it shimmering forever.
        queued = list(delivered)
        if glanced:
            upgrade = next(
                (s for s in delivered if s.subject == glanced[0].subject), None
            )
            emit(
                {
                    "type": "upgrade",
                    "seq": plan.seq,
                    # None ⇒ settle in place: the same card, no longer provisional.
                    "suggestion": _suggestion_out(upgrade) if upgrade is not None else None,
                }
            )
            # Removed from what is EMITTED, never from what was delivered: the card reached
            # the reader, in the provisional card's own slot. A stats frame that counted it
            # as zero would say a tick delivered nothing when the reader is looking at it.
            queued = [s for s in queued if s is not upgrade]
        for suggestion in queued:
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
                    "token_usage": dict(result.token_usage),
                    "turns": len(plan.turns),
                    **_processing_out(result),
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
                # A failure processed nothing: the turns it consumed go back on the pending
                # run rather than being silently lost to a provider hiccup.
                session.abandon(plan.seq, now=loop.time(), turns=plan.turns)
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
                        density=msg.get("density"),
                        min_confidence=msg.get("min_confidence"),
                        # `turn_window` is the old name for the same bound; `max_suggestions`
                        # is simply dropped. An older client is tolerated, never 400ed.
                        max_pending_turns=msg.get("max_pending_turns")
                        or msg.get("turn_window"),
                        quiet_period=msg.get("quiet_period"),
                        web_search=(
                            allow_web_search(ctx, msg["web_search"])
                            if msg.get("web_search") is not None
                            else None
                        ),
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
