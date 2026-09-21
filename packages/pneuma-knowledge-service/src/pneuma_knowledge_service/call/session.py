"""One voice call, as this process sees it.

THE RULES THIS FILE HOLDS (docs/design/voice-call.md §5)
------------------------------------------------------
* **One owner per action.** The browser draws captions and may close or mute; everything
  else — reading the transcript, answering a delegation, handing words to the voice — is
  done here, once. A delegation id is claimed before any work starts, so a redelivered
  event cannot run the same lookup twice.
* **The voice follows the latest ask; the screen keeps every answer.** A spoken interruption
  is reviewed while results are pending. Cancellation, changed intent or a newer delegation
  suppresses further old-result sends; accepted provider context cannot be retracted.
  Superseded work can finish its on-screen card.
* **An acknowledgement is not speech.** The provider acks a hand-over when it estimates the
  text reached the model's context, not when anybody heard it. What is recorded from an ack
  is its estimated interval on the session timeline. The console can link nearby speech
  for navigation, but timing does not prove which answer supports a spoken sentence.
* **Silence is billed.** A session costs by the minute whether or not anyone speaks, so a
  call that has heard nothing from the owner for `call_idle_seconds`, or has run for
  `call_max_seconds`, is closed from here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.call import (
    OWNER,
    VOICE,
    Exchange,
    Ledger,
    SpokenChunker,
    voice_context,
    voice_instructions,
)

from .gateway import LiveChannel
from .librarian import Librarian

logger = logging.getLogger(__name__)

#: After a delegation event, wait for the owner's transcript to go quiet before reading it:
#: the event routinely arrives BEFORE the last words of the sentence it is about (measured:
#: the final fragment landed with the event, or up to half a second after it).
SETTLE_QUIET_SECONDS = 0.35
SETTLE_MAX_SECONDS = 1.2

#: A lookup that has said nothing by here gets one quiet progress update. The voice covers the
#: first seconds on its own ("let me check"), so this is not for the ordinary wait — it is for
#: the one that has gone wrong enough to be worth mentioning and not yet wrong enough to have
#: failed. Once per delegation: a voice that keeps announcing that it is still looking is
#: worse than a voice that is quiet.
PROGRESS_AFTER_SECONDS = 9.0

#: One lookup, end to end. Past it the voice is told the lookup failed — a delegate that never
#: answers leaves a voice that was told not to guess with nothing to say.
ANSWER_TIMEOUT_SECONDS = 30.0

#: The only commands the browser's data channel may send. The session is created with this
#: list, so a page cannot append an instruction, a quiet context or a spoken line: that is
#: not a rule the page is asked to follow, it is a command the provider refuses.
BROWSER_COMMANDS = ("session.close", "session.input_audio.mute", "session.input_audio.unmute")

#: How many earlier asks of this call ask formation is shown.
EARLIER_ASKS = 3

#: Safety ceiling for anomalously long output, not a routine conversational length limit.
#: The answer style sets the normal length and allows detail when requested. A fixed 130
#: characters cut ordinary English answers and repeatedly cut requests to explain more.
SPOKEN_BUDGET_CHARS = 4000  # Six bounded facts plus a preliminary; never drop final qualifiers.


def session_config(settings: Any, *, zone: str, now: datetime | None = None, speech_vocabulary: str = "") -> dict[str, Any]:
    """The provider session a call is created with.

    WebRTC negotiates its own audio format, so none is stated. The standing prompt carries
    no per-call fields; the date rides in as the first developer message.
    """
    try:
        local = (now or datetime.now().astimezone()).astimezone(ZoneInfo(zone))
    except Exception:  # noqa: BLE001 — an unknown zone is not a reason to refuse a call
        local, zone = (now or datetime.now().astimezone()), "UTC"
    weekdays = prompt("call.voice.weekdays").split(",")
    context = voice_context(
        today=local.date().isoformat(), weekday=weekdays[local.weekday()].strip(), zone=zone
    )
    if speech_vocabulary:
        context += "\n\n<speech_vocabulary>\n" + speech_vocabulary + "\n</speech_vocabulary>"
    return {
        "model": settings.call_model,
        "instructions": voice_instructions(),
        "audio": {"output": {"voice": settings.call_voice}},
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": context}],
            }
        ],
        "delegation": {"type": "client"},
        "client": {"data_channel": {"allowed_client_events": list(BROWSER_COMMANDS)}},
    }


def call_status(settings: Any, *, live: bool) -> dict[str, Any]:
    """Whether this deployment can place a call, and if not, the one thing missing."""
    from ..wiring import usable_model_name

    reason = detail = ""
    if not str(getattr(settings, "openai_api_key", "") or "").strip():
        reason = "no_openai_key"
        detail = "A voice call needs OPENAI_API_KEY; none is configured."
    elif not usable_model_name(settings, "call"):
        reason = "no_recall_model"
        detail = "A voice call answers from the fast lane, and this deployment has no usable model for it."
    return {
        "configured": not reason,
        "reason": reason,
        "detail": detail,
        "model": settings.call_model,
        "voice": settings.call_voice,
        "live": live,
    }


@dataclass
class Delegation:
    """One ask of the library, from the provider's event to the completed card."""

    id: str
    provider_id: str
    revision: int
    offset_ms: int
    began: float
    state: str = "hearing"
    spoken: bool = True
    ask: str = ""
    said: str = ""
    preliminary: str = ""
    answer_phase: str = "searching"
    answer: dict[str, Any] | None = None
    detail: str = ""
    deliveries: list[dict[str, int]] = field(default_factory=list)
    elapsed_ms: int | None = None
    #: Where the wait went, in milliseconds since the delegation event: the transcript
    #: settled, the question was written, retrieval finished, the first words were handed
    #: over. Measured here rather than reconstructed by a reader from arrival gaps.
    timings: dict[str, int] = field(default_factory=dict)
    updates: list[dict[str, Any]] = field(default_factory=list)
    observed_speech: list[dict[str, Any]] = field(default_factory=list)
    owner_changes: list[dict[str, Any]] = field(default_factory=list)
    review_ready: asyncio.Event = field(default_factory=asyncio.Event)

    def mark(self, name: str) -> None:
        self.timings.setdefault(name, int((time.monotonic() - self.began) * 1000))

    def frame(self) -> dict[str, Any]:
        return {
            "type": "delegation",
            "delegation": {
                "id": self.id,
                "state": self.state,
                "spoken": self.spoken,
                "ask": self.ask,
                "said": self.said,
                "preliminary": self.preliminary,
                "answer_phase": self.answer_phase,
                "answer": self.answer,
                "detail": self.detail,
                "offset_ms": self.offset_ms,
                "deliveries": list(self.deliveries),
                "elapsed_ms": self.elapsed_ms,
                "timings": dict(self.timings),
                "provider_id": self.provider_id,
                "updates": [dict(update) for update in self.updates],
                "observed_speech": list(self.observed_speech),
                "owner_changes": list(self.owner_changes),
            },
        }


class CallSession:
    """One call. `run(channel)` is its whole life; everything else is how it is watched."""

    def __init__(
        self,
        *,
        user_id: str,
        librarian: Librarian,
        idle_seconds: float = 180.0,
        max_seconds: float = 1800.0,
        call_id: str | None = None,
    ) -> None:
        self.call_id = call_id or uuid.uuid4().hex[:12]
        self.user_id = user_id
        self.session_id = ""
        self.librarian = librarian
        self.idle_seconds = idle_seconds
        self.max_seconds = max_seconds
        self.ledger = Ledger()
        self.delegations: dict[str, Delegation] = {}
        self.closed = asyncio.Event()
        self.attached = False
        self.close_reason = ""
        self.seconds: float | None = None
        self._claimed: set[str] = set()
        self._revision = 0
        self._handovers: dict[str, tuple[Delegation, dict[str, Any]]] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._tasks: set[asyncio.Task] = set()
        self._channel: LiveChannel | None = None
        self._owner_heard_at = time.monotonic()
        self._owner_fragment_at = 0.0
        self._started_at = time.monotonic()
        self._closing = False
        self._sent = 0
        self._review_task: asyncio.Task | None = None
        self._review_text = ""
        self._review_generation = 0

    # ── watching ────────────────────────────────────────────────────────────────────────

    def attach(self) -> asyncio.Queue:
        """A browser socket joins: it is repainted from state, then follows live."""
        queue: asyncio.Queue = asyncio.Queue()
        if self.attached:
            queue.put_nowait({"type": "attached"})
        for delegation in self.delegations.values():
            queue.put_nowait(delegation.frame())
        if self.closed.is_set():
            queue.put_nowait(self._closed_frame())
        self._subscribers.append(queue)
        return queue

    @property
    def watched(self) -> bool:
        return bool(self._subscribers)

    def detach(self, queue: asyncio.Queue) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(queue)

    def _publish(self, frame: Mapping[str, Any]) -> None:
        for queue in self._subscribers:
            queue.put_nowait(dict(frame))

    def _closed_frame(self) -> dict[str, Any]:
        return {"type": "closed", "reason": self.close_reason, "seconds": self.seconds}

    # ── the life of the call ────────────────────────────────────────────────────────────

    async def run(self, channel: LiveChannel) -> None:
        self._channel = channel
        self.attached = True
        self._publish({"type": "attached"})
        watchdog = asyncio.create_task(self._watch())
        # Everything the first ask would otherwise wait for — the canonical tree, the page
        # titles — is read while the owner is still saying hello.
        warm = asyncio.create_task(self._warm())
        self._tasks.add(warm)
        warm.add_done_callback(self._tasks.discard)
        try:
            async for event in channel:
                await self._on_event(event)
                if self.closed.is_set():
                    break
        except Exception as exc:  # noqa: BLE001 — a dropped sideband ends the call, not the API
            logger.warning("call %s: sideband ended: %s", self.call_id, type(exc).__name__)
            self._publish({"type": "error", "code": "sideband_lost", "detail": type(exc).__name__})
        finally:
            watchdog.cancel()
            for task in list(self._tasks):
                task.cancel()
            if not self.closed.is_set():
                self.close_reason = self.close_reason or "connection_lost"
                self.closed.set()
                self._publish(self._closed_frame())

    async def _warm(self) -> None:
        with contextlib.suppress(Exception):  # a cold first ask is slower, not wrong
            await self.librarian.warm()

    async def end(self, reason: str = "close_requested") -> None:
        """Ask the provider to close. The `session.closed` event is what finishes `run`."""
        if self._closing or self.closed.is_set():
            return
        self._closing = True
        self.close_reason = reason
        if self._channel is None:
            self.closed.set()
            return
        with contextlib.suppress(Exception):
            await self._channel.send({"type": "session.close", "event_id": f"close-{self.call_id}"})

    async def _watch(self) -> None:
        while not self.closed.is_set():
            await asyncio.sleep(1.0)
            now = time.monotonic()
            if self.max_seconds and now - self._started_at > self.max_seconds:
                await self.end("max_duration")
            elif self.idle_seconds and now - self._owner_heard_at > self.idle_seconds:
                await self.end("idle")

    async def _on_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if kind == "session.input_transcript.delta":
            self._owner_heard_at = self._owner_fragment_at = time.monotonic()
            self.ledger.add(OWNER, str(event.get("delta") or ""), event.get("start_ms") or 0, event.get("end_ms") or 0)
            self._queue_owner_review(str(event.get("delta") or ""))
        elif kind == "session.output_transcript.delta":
            self.ledger.add(VOICE, str(event.get("delta") or ""), event.get("start_ms") or 0, event.get("end_ms") or 0)
            if self.delegations:
                latest = next(reversed(self.delegations.values()))
                latest.observed_speech.append({"delta": str(event.get("delta") or ""),
                    "start_ms": event.get("start_ms"), "end_ms": event.get("end_ms"),
                    "received_ms": int((time.monotonic() - latest.began) * 1000)})
                self._publish(latest.frame())
        elif kind == "session.delegation.created":
            self._begin(event)
        elif kind in ("session.commentary.appended", "session.instructions.appended", "session.thinking.appended"):
            pending = self._handovers.pop(str(event.get("client_event_id") or ""), None)
            if pending is not None:
                delegation, update = pending
                interval = {"start_ms": int(event.get("start_ms") or 0), "end_ms": int(event.get("end_ms") or 0)}
                update.update(state="acknowledged", ack_ms=int((time.monotonic() - delegation.began) * 1000), **interval)
                if update["result"] and update["type"] == "session.commentary.append":
                    delegation.deliveries.append(interval)
                self._publish(delegation.frame())
        elif kind == "session.usage.updated":
            usage = event.get("usage") or {}
            window = event.get("context_window") or {}
            self.seconds = usage.get("seconds", self.seconds)
            self._publish({"type": "usage", "seconds": self.seconds, "context_ratio": window.get("usage_ratio")})
        elif kind == "session.started":
            self.session_id = str((event.get("session") or {}).get("id") or self.session_id)
        elif kind == "session.closed":
            self.seconds = (event.get("usage") or {}).get("seconds", self.seconds)
            # The provider's reason stands unless this process asked for the close itself
            # and has a better one ("idle", "max_duration").
            provider_reason = str(event.get("reason") or "")
            if not self.close_reason or provider_reason != "close_requested":
                self.close_reason = provider_reason or self.close_reason
            self.closed.set()
            self._publish(self._closed_frame())
        elif kind == "error":
            error = event.get("error") or {}
            pending = self._handovers.pop(str(event.get("client_event_id") or error.get("client_event_id") or ""), None)
            self._publish({"type": "error", "code": str(error.get("code") or "error"), "detail": str(error.get("message") or "")})
            if pending is not None:
                delegation, update = pending
                update.update(state="rejected", error=str(error.get("code") or "rejected"),
                              ack_ms=int((time.monotonic() - delegation.began) * 1000))
                self._publish(delegation.frame())
                logger.warning("call %s: hand-over refused: %s", self.call_id, error.get("code"))

    # ── delegations ─────────────────────────────────────────────────────────────────────

    def _begin(self, event: Mapping[str, Any]) -> None:
        meta = event.get("delegation") or {}
        provider_id = str(meta.get("id") or "")
        if not provider_id or meta.get("target") != "client" or provider_id in self._claimed:
            return
        self._claimed.add(provider_id)
        self._revision += 1
        self._review_generation += 1
        self._review_text = ""
        if self._review_task is not None:
            self._review_task.cancel()
        for old in self.delegations.values():
            old.review_ready.set()
        # The voice follows the latest ask: whatever is still running has been overtaken.
        for earlier in self.delegations.values():
            if earlier.state in ("hearing", "searching", "answering") and earlier.spoken:
                earlier.spoken = False
                self._publish(earlier.frame())
        delegation = Delegation(
            id=f"d{len(self.delegations) + 1}",
            provider_id=provider_id,
            revision=self._revision,
            offset_ms=int(event.get("offset_ms") or 0),
            began=time.monotonic(),
        )
        delegation.review_ready.set()
        self.delegations[delegation.id] = delegation
        self._publish(delegation.frame())
        task = asyncio.create_task(self._answer(delegation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _queue_owner_review(self, delta: str) -> None:
        if not delta or not callable(getattr(self.librarian, "classify_change", None)):
            return
        active = next((d for d in reversed(self.delegations.values())
                       if d.ask and d.state in ("searching", "answering") and self._current(d)), None)
        if active is None:
            return
        self._review_text += delta
        self._review_generation += 1
        generation = self._review_generation
        active.review_ready.clear()
        if self._review_task is not None:
            self._review_task.cancel()
        async def review() -> None:
            text = ""
            try:
                await asyncio.sleep(SETTLE_QUIET_SECONDS)
                text = self._review_text
                action = await asyncio.wait_for(self.librarian.classify_change(active.ask, text), 3.0)
                if generation != self._review_generation or not self._current(active):
                    return
                active.owner_changes.append({"text": text, "action": action,
                    "ms": int((time.monotonic() - active.began) * 1000)})
                if action in ("cancel", "replace"):
                    self._revision += 1
                    active.spoken = False
                    active.mark("superseded")
                self._review_text = ""
            except asyncio.CancelledError:
                raise
            except Exception:
                # Unclassified speech is not permission to deliver a potentially obsolete result.
                if generation == self._review_generation:
                    active.owner_changes.append({"text": text, "action": "unresolved",
                        "ms": int((time.monotonic() - active.began) * 1000)})
                    active.spoken = False
                    self._revision += 1
            finally:
                if generation == self._review_generation:
                    active.review_ready.set()
                    self._publish(active.frame())
        self._review_task = asyncio.create_task(review())
        self._tasks.add(self._review_task)
        self._review_task.add_done_callback(self._tasks.discard)

    def _current(self, delegation: Delegation) -> bool:
        return delegation.revision == self._revision and not self._closing

    async def _settle(self, delegation: Delegation) -> None:
        deadline = delegation.began + SETTLE_MAX_SECONDS
        while time.monotonic() < deadline:
            if time.monotonic() - self._owner_fragment_at >= SETTLE_QUIET_SECONDS:
                return
            await asyncio.sleep(0.05)

    async def _hand_over(self, delegation: Delegation, text: str, *, result: bool = True, phase: str = "refinement", quiet: bool = False) -> None:
        """Give Live factual results or task context for this delegation — if it is still the latest."""
        if not text or self._channel is None:
            return
        # Clarifications are model-generated too and do not pass through _Attempt's chunker.
        # Enforce the append bound at the shared send boundary for every kind of message.
        if len(text) > 420 or len(text.encode("utf-8")) > 480:
            chunker = SpokenChunker()
            for chunk in [*chunker.feed(text), *chunker.flush()]:
                await self._hand_over(delegation, chunk, result=result, phase=phase, quiet=quiet)
            return
        await delegation.review_ready.wait()
        if not self._current(delegation):
            if delegation.spoken:
                delegation.spoken = False
                self._publish(delegation.frame())
            return
        if result and len(delegation.said) >= SPOKEN_BUDGET_CHARS:
            return
        self._sent += 1
        event_id = f"{self.call_id}-{delegation.id}-{self._sent}"
        # Progress, clarification and failure are not evidence deliveries. In particular,
        # a holding line must not consume the answer budget or suppress invoke-only output.
        event_type = "session.thinking.append" if quiet else "session.commentary.append"
        update = {"event_id": event_id, "type": event_type, "phase": phase, "content": text,
                  "result": result, "state": "sending", "sent_ms": int((time.monotonic() - delegation.began) * 1000)}
        delegation.updates.append(update)
        self._handovers[event_id] = (delegation, update)
        try:
            await self._channel.send({"type": event_type, "event_id": event_id,
                "delegation_id": delegation.provider_id, "content": text})
        except Exception as exc:
            self._handovers.pop(event_id, None)
            update.update(state="send_failed", error=type(exc).__name__)
            self._publish(delegation.frame())
            raise
        if result and not quiet and delegation.elapsed_ms is None:
            delegation.elapsed_ms = int((time.monotonic() - delegation.began) * 1000)
            delegation.mark("first_words")
            delegation.mark("first_sent")
        if update["state"] == "sending":
            update["state"] = "sent"
        if result and not quiet:
            delegation.said = f"{delegation.said} {text}".strip()
        self._publish(delegation.frame())

    async def _holding_line(self, delegation: Delegation) -> None:
        """Report an unfinished task once when it takes longer than the normal wait."""
        await asyncio.sleep(PROGRESS_AFTER_SECONDS)
        if not delegation.said and self._current(delegation):
            with contextlib.suppress(Exception):
                await self._hand_over(delegation, prompt("call.say.working"), result=False, phase="progress", quiet=True)

    async def _answer(self, delegation: Delegation) -> None:
        holding = asyncio.create_task(self._holding_line(delegation))
        try:
            await asyncio.wait_for(self._lookup(delegation), ANSWER_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — every failure ends as a sentence, never as silence
            logger.warning("call %s %s: lookup failed: %r", self.call_id, delegation.id, exc)
            delegation.state = "failed"
            delegation.detail = "timed out" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
            with contextlib.suppress(Exception):
                await self._hand_over(delegation, prompt(
                    "call.progressive.incomplete" if delegation.preliminary else "call.say.failed"
                ), result=False, phase="failure")
            self._publish(delegation.frame())
        finally:
            holding.cancel()

    async def _lookup(self, delegation: Delegation) -> None:
        await self._settle(delegation)
        delegation.mark("settled")
        earlier = [
            Exchange(question=done.ask, said=done.said)
            for done in self.delegations.values()
            if done is not delegation and done.ask and done.said
        ][-EARLIER_ASKS:]

        # Freeze the input before any I/O. Vocabulary loading and ask formation may yield
        # while another request arrives; an older card must keep the question it began on.
        ledger = Ledger(fragments=list(self.ledger.fragments))
        heard = ledger.owner_last_words()
        try:
            vocabulary = await self.librarian.vocabulary(heard)
        except Exception:  # noqa: BLE001 — the vocabulary repairs names; its absence only repairs fewer
            vocabulary = ""
        ask = await self.librarian.form_ask(ledger, earlier=earlier, vocabulary=vocabulary)
        delegation.mark("asked")
        if not ask.ready:
            delegation.state = "unclear"
            delegation.detail = ask.clarify
            await self._hand_over(delegation, ask.clarify or prompt("call.say.unclear"), result=False, phase="clarification")
            self._publish(delegation.frame())
            return

        delegation.ask = ask.question
        # One formed question launches one paired lookup. Speculating two full progressive
        # workflows on competing wordings would duplicate both retrievals and model costs.
        attempt = self._attempt(delegation, ask.question)
        delegation.state = "answering" if attempt.retrieved else "searching"
        self._publish(delegation.frame())

        answer = await attempt.release()
        if not delegation.said and self._current(delegation):
            # A model that streamed nothing (a scripted one, a provider without streaming)
            # still answered: say the finished text.
            whole = SpokenChunker()
            for chunk in [*whole.feed(answer.answer_text), *whole.flush()]:
                await self._hand_over(delegation, chunk)
        delegation.answer = answer.payload
        delegation.mark("completed")
        delegation.state = "done"
        self._publish(delegation.frame())

    def _attempt(self, delegation: Delegation, question: str) -> "_Attempt":
        return _Attempt(self, delegation, question)



class _Attempt:
    """One paired lookup whose phase-labelled results are drained by the session."""

    def __init__(self, session: CallSession, delegation: Delegation, question: str) -> None:
        self._session = session
        self._delegation = delegation
        self._chunker = SpokenChunker()
        self._final_chunks: list[str] = []
        self._chunks: asyncio.Queue[tuple[str, str, bool] | None] = asyncio.Queue()
        self.retrieved = False
        self._released = False
        self._task = asyncio.create_task(
            session.librarian.answer(question, on_token=self._on_token, on_retrieved=self._on_retrieved,
                                     on_preliminary=self._on_preliminary)
        )

    # Result callbacks must not block the producer, so each callback
    # only queues; `release` does the sending.
    def _on_token(self, delta: str) -> None:
        for chunk in self._chunker.feed(delta):
            self._final_chunks.append(chunk)

    def _on_preliminary(self, text: str) -> None:
        if text:
            self._chunks.put_nowait(("scope", prompt("call.progressive.partial_scope"), True))
            self._chunks.put_nowait(("preliminary", text, False))

    def _on_retrieved(self) -> None:
        self.retrieved = True
        if self._released:
            self._delegation.mark("retrieved")
            self._delegation.state = "answering"
            self._session._publish(self._delegation.frame())

    async def drop(self) -> None:
        self._task.cancel()
        with contextlib.suppress(BaseException):
            await self._task

    async def release(self):  # noqa: ANN201 — LibraryAnswer
        """Deliver partial facts immediately and final facts only after successful admission."""
        self._released = True
        if self.retrieved:
            self._delegation.mark("retrieved")

        async def finish() -> None:
            try:
                answer = await self._task
                self._final_chunks.extend(self._chunker.flush())
                lookup = answer.payload.get("lookup_result")
                if lookup is not None:
                    context = prompt("call.progressive.result_scope", status=lookup["status"],
                        scope=lookup["scope"], limitations="; ".join(lookup["limitations"]))
                    self._chunks.put_nowait(("scope", context, True))
                for chunk in self._final_chunks:
                    self._chunks.put_nowait(("refinement", chunk, False))
            finally:
                # A failed stream's unfinished tail is not a result. Wake the consumer,
                # then propagate the failure so the caller can explain what happened.
                self._chunks.put_nowait(None)

        finisher = asyncio.create_task(finish())
        try:
            while (item := await self._chunks.get()) is not None:
                phase, chunk, quiet = item
                before = self._delegation.said
                await self._session._hand_over(self._delegation, chunk, phase=phase, quiet=quiet, result=not quiet)
                if self._delegation.said != before:
                    self._delegation.answer_phase = phase
                    self._delegation.mark(phase)
                    if phase == "preliminary":
                        self._delegation.preliminary = chunk
                    self._session._publish(self._delegation.frame())
            await finisher
        except BaseException:
            finisher.cancel()
            await self.drop()
            with contextlib.suppress(BaseException):
                await finisher
            raise
        return self._task.result()


class CallSessions:
    """This process's calls, one per owner. A new call ends the one before it: the usual
    reason there is one is a tab that died mid-call, and that session is still billing."""

    def __init__(self) -> None:
        self._by_user: dict[str, CallSession] = {}
        self._by_id: dict[str, CallSession] = {}
        self._runners: dict[str, asyncio.Task] = {}

    def live(self, user_id: str) -> bool:
        session = self._by_user.get(str(user_id))
        return bool(session is not None and not session.closed.is_set())

    def get(self, call_id: str) -> CallSession | None:
        return self._by_id.get(call_id)

    async def replace(self, user_id: str) -> None:
        previous = self._by_user.get(str(user_id))
        if previous is not None and not previous.closed.is_set():
            await previous.end("replaced")

    def start(self, session: CallSession, runner: asyncio.Task) -> None:
        self._by_user[str(session.user_id)] = session
        self._by_id[session.call_id] = session
        self._runners[session.call_id] = runner

        def forget(_task: asyncio.Task, call_id: str = session.call_id) -> None:
            self._runners.pop(call_id, None)

        runner.add_done_callback(forget)

    async def aclose(self) -> None:
        for session in list(self._by_id.values()):
            await session.end("shutdown")
        for runner in list(self._runners.values()):
            runner.cancel()
