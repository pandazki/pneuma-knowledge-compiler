"""One voice call, as this process sees it.

THE RULES THIS FILE HOLDS (docs/design/voice-call.md §5)
------------------------------------------------------
* **One owner per action.** The browser draws captions and may close or mute; everything
  else — reading the transcript, answering a delegation, handing words to the voice — is
  done here, once. A delegation id is claimed before any work starts, so a redelivered
  event cannot run the same lookup twice.
* **The voice follows the latest ask; the screen keeps every answer.** A spoken interruption
  cancels nothing at the provider — it is this application's decision — and the decision is
  mechanical: a delegation that a newer one has overtaken finishes its lookup and completes
  its card, and hands the voice nothing.
* **An acknowledgement is not speech.** The provider acks a hand-over when it estimates the
  text reached the model's context, not when anybody heard it. What is recorded from an ack
  is its interval on the session timeline, which is what lets the console tell which spoken
  lines stand on which answer — and mark the ones that stand on none.
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

#: A lookup that has said nothing by here gets one spoken holding line. The voice covers the
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

#: How much of one answer the voice is handed, in characters. Measured: about five Chinese
#: characters are spoken per second, so this is some twenty-five seconds of speech, and an
#: answering model asked for seventy characters writes a hundred and fifty often enough. The
#: style clause asks; this stops. Hand-overs end at the sentence that crosses the line — the
#: card on screen keeps the whole answer, and the owner can ask for the rest.
SPOKEN_BUDGET_CHARS = 130


def session_config(settings: Any, *, zone: str, now: datetime | None = None) -> dict[str, Any]:
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
    answer: dict[str, Any] | None = None
    detail: str = ""
    deliveries: list[dict[str, int]] = field(default_factory=list)
    elapsed_ms: int | None = None
    #: Where the wait went, in milliseconds since the delegation event: the transcript
    #: settled, the question was written, retrieval finished, the first words were handed
    #: over. Measured here rather than reconstructed by a reader from arrival gaps.
    timings: dict[str, int] = field(default_factory=dict)

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
                "answer": self.answer,
                "detail": self.detail,
                "offset_ms": self.offset_ms,
                "deliveries": list(self.deliveries),
                "elapsed_ms": self.elapsed_ms,
                "timings": dict(self.timings),
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
        self._handovers: dict[str, Delegation] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._tasks: set[asyncio.Task] = set()
        self._channel: LiveChannel | None = None
        self._owner_heard_at = time.monotonic()
        self._owner_fragment_at = 0.0
        self._started_at = time.monotonic()
        self._closing = False
        self._sent = 0

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
        elif kind == "session.output_transcript.delta":
            self.ledger.add(VOICE, str(event.get("delta") or ""), event.get("start_ms") or 0, event.get("end_ms") or 0)
        elif kind == "session.delegation.created":
            self._begin(event)
        elif kind in ("session.commentary.appended", "session.instructions.appended"):
            delegation = self._handovers.pop(str(event.get("client_event_id") or ""), None)
            if delegation is not None:
                delegation.deliveries.append(
                    {"start_ms": int(event.get("start_ms") or 0), "end_ms": int(event.get("end_ms") or 0)}
                )
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
            delegation = self._handovers.pop(str(event.get("client_event_id") or error.get("client_event_id") or ""), None)
            self._publish({"type": "error", "code": str(error.get("code") or "error"), "detail": str(error.get("message") or "")})
            if delegation is not None:
                logger.warning("call %s: hand-over refused: %s", self.call_id, error.get("code"))

    # ── delegations ─────────────────────────────────────────────────────────────────────

    def _begin(self, event: Mapping[str, Any]) -> None:
        meta = event.get("delegation") or {}
        provider_id = str(meta.get("id") or "")
        if not provider_id or meta.get("target") != "client" or provider_id in self._claimed:
            return
        self._claimed.add(provider_id)
        self._revision += 1
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
        self.delegations[delegation.id] = delegation
        self._publish(delegation.frame())
        task = asyncio.create_task(self._answer(delegation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _current(self, delegation: Delegation) -> bool:
        return delegation.revision == self._revision and not self._closing

    async def _settle(self, delegation: Delegation) -> None:
        deadline = delegation.began + SETTLE_MAX_SECONDS
        while time.monotonic() < deadline:
            if time.monotonic() - self._owner_fragment_at >= SETTLE_QUIET_SECONDS:
                return
            await asyncio.sleep(0.05)

    async def _hand_over(self, delegation: Delegation, text: str) -> None:
        """Give the voice something to say for this delegation — if it is still the latest."""
        if not text or self._channel is None:
            return
        if not self._current(delegation):
            if delegation.spoken:
                delegation.spoken = False
                self._publish(delegation.frame())
            return
        if len(delegation.said) >= SPOKEN_BUDGET_CHARS:
            return
        self._sent += 1
        event_id = f"{self.call_id}-{delegation.id}-{self._sent}"
        self._handovers[event_id] = delegation
        if delegation.elapsed_ms is None:
            delegation.elapsed_ms = int((time.monotonic() - delegation.began) * 1000)
            delegation.mark("first_words")
        delegation.said = f"{delegation.said} {text}".strip()
        await self._channel.send(
            {
                "type": "session.commentary.append",
                "event_id": event_id,
                "delegation_id": delegation.provider_id,
                "content": text,
            }
        )
        self._publish(delegation.frame())

    async def _holding_line(self, delegation: Delegation) -> None:
        """Say "still looking" once, if the lookup is slow enough to need it."""
        await asyncio.sleep(PROGRESS_AFTER_SECONDS)
        if not delegation.said and self._current(delegation):
            with contextlib.suppress(Exception):
                await self._hand_over(delegation, prompt("call.say.working"))

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
                await self._hand_over(delegation, prompt("call.say.failed"))
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

        # SPECULATE. Writing the question out of the transcript costs a model call — measured
        # at over two seconds, the largest single wait in a lookup — and for a first question
        # asked in a whole sentence it returns the owner's own words with a question mark. So
        # those words go to the library at once, beside the call that may replace them, and
        # whatever they bring back is HELD: nothing is handed to the voice until the formed
        # question turns out to be the same one. If it is not (a follow-up, a correction, a
        # repaired name), the attempt is dropped unheard and the lookup starts over on the
        # real question. The unused attempt is a cost, and it is this design's to own.
        heard = self.ledger.owner_last_words()
        try:
            vocabulary = await self.librarian.vocabulary(heard)
        except Exception:  # noqa: BLE001 — the vocabulary repairs names; its absence only repairs fewer
            vocabulary = ""
        attempt = self._attempt(delegation, heard) if len(_bare(heard)) >= SPECULATE_MIN_CHARS else None
        try:
            ask = await self.librarian.form_ask(self.ledger, earlier=earlier, vocabulary=vocabulary)
        except BaseException:
            if attempt is not None:
                await attempt.drop()
            raise
        delegation.mark("asked")
        if not ask.ready:
            if attempt is not None:
                await attempt.drop()
            delegation.state = "unclear"
            delegation.detail = ask.clarify
            await self._hand_over(delegation, ask.clarify or prompt("call.say.unclear"))
            self._publish(delegation.frame())
            return

        delegation.ask = ask.question
        if attempt is not None and _bare(ask.question) != _bare(heard):
            await attempt.drop()
            attempt = None
        delegation.timings["speculated"] = int(attempt is not None)
        if attempt is None:
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
        delegation.state = "done"
        self._publish(delegation.frame())

    def _attempt(self, delegation: Delegation, question: str) -> "_Attempt":
        return _Attempt(self, delegation, question)


def _bare(text: str) -> str:
    """A question with everything but its words removed — what two askings are compared by."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


#: The owner's own words are tried speculatively only when there are enough of them to be a
#: question: "第二点呢" is a reference, and a lookup on it is wasted by construction.
SPECULATE_MIN_CHARS = 8


class _Attempt:
    """One run of the library on one wording of the question, its words held until released."""

    def __init__(self, session: CallSession, delegation: Delegation, question: str) -> None:
        self._session = session
        self._delegation = delegation
        self._chunker = SpokenChunker()
        self._chunks: asyncio.Queue[str | None] = asyncio.Queue()
        self.retrieved = False
        self._released = False
        self._task = asyncio.create_task(
            session.librarian.answer(question, on_token=self._on_token, on_retrieved=self._on_retrieved)
        )

    # `on_token` runs inside the answering call's streaming loop and must not block, so it
    # only queues; `release` does the sending.
    def _on_token(self, delta: str) -> None:
        for chunk in self._chunker.feed(delta):
            self._chunks.put_nowait(chunk)

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
        """From here on what the library says reaches the voice, as it is written."""
        self._released = True
        if self.retrieved:
            self._delegation.mark("retrieved")

        async def finish() -> None:
            try:
                await self._task
            finally:
                for chunk in self._chunker.flush():
                    self._chunks.put_nowait(chunk)
                self._chunks.put_nowait(None)

        finisher = asyncio.create_task(finish())
        try:
            while (chunk := await self._chunks.get()) is not None:
                await self._session._hand_over(self._delegation, chunk)
            await finisher
        except BaseException:
            finisher.cancel()
            await self.drop()
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
