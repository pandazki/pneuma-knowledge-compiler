"""One voice call, driven against a scripted provider channel and a fake librarian.

Keyless and middleware-free: the provider is a list of dicts the test feeds, the library is
an object that returns what the test tells it to. What is pinned here is the set of rules the
session file states it holds — a delegation is claimed once, the voice follows the LATEST ask
while the screen keeps every answer, a failure ends as a sentence rather than as silence, and
the browser's data channel may carry exactly three commands and no instruction.

All content is invented: the Ferry Scheduling Rebuild and the Harbour Quay are synthetic.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

import pytest
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.call import Ask, Exchange, Ledger
from pneuma_knowledge_service.call import session as session_module
from pneuma_knowledge_service.call.librarian import LibraryAnswer
from pneuma_knowledge_service.call.session import (
    BROWSER_COMMANDS,
    SPOKEN_BUDGET_CHARS,
    CallSession,
    CallSessions,
    call_status,
    session_config,
)
from pneuma_knowledge_service.settings import Settings

USER = "u-call-session"
#: Short and obviously invented: what matters is that a deployment HAS one.
KEY = "ck-not-a-real-key-000111"


def keyed(**over) -> Settings:
    """Settings with a provider key. `openai_api_key` is read by its own env name, so it is
    the alias an init kwarg has to use."""
    return Settings(**{"OPENAI_API_KEY": KEY}, **over)


# ── the provider, scripted ─────────────────────────────────────────────────────────────────


class ScriptedChannel:
    """A `LiveChannel` the test writes the provider's half of.

    Events are polled off a list so a test can feed more of them mid-call, and a
    `session.close` command is answered with the `session.closed` event a real provider
    sends — which is what makes the close REASON observable."""

    def __init__(self, events=(), *, answers_close: bool = True) -> None:
        self.sent: list[dict] = []
        self.answers_close = answers_close
        self._pending: list[dict] = [dict(event) for event in events]
        self._ended = False

    def feed(self, *events) -> None:
        self._pending.extend(dict(event) for event in events)

    def stop(self) -> None:
        """The sideband goes away — the provider's end of `async for` running out."""
        self._ended = True

    async def send(self, event) -> None:
        self.sent.append(dict(event))
        if self.answers_close and event.get("type") == "session.close":
            self.feed({"type": "session.closed", "reason": "close_requested", "usage": {"seconds": 7.0}})

    async def __aiter__(self):
        while True:
            while self._pending:
                yield self._pending.pop(0)
            if self._ended:
                return
            await asyncio.sleep(0.005)

    # readers the assertions use
    def commentary(self, delegation_id: str | None = None) -> list[dict]:
        return [
            event
            for event in self.sent
            if event.get("type") == "session.commentary.append"
            and (delegation_id is None or event.get("delegation_id") == delegation_id)
        ]

    def spoken(self, delegation_id: str | None = None) -> list[str]:
        return [event["content"] for event in self.commentary(delegation_id)]


def heard(text: str, *, start_ms: int = 0, end_ms: int = 2000) -> dict:
    return {
        "type": "session.input_transcript.delta",
        "delta": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def said(text: str, *, start_ms: int = 0, end_ms: int = 2000) -> dict:
    return {
        "type": "session.output_transcript.delta",
        "delta": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def delegated(provider_id: str, *, target: str = "client", offset_ms: int = 2100) -> dict:
    return {
        "type": "session.delegation.created",
        "delegation": {"id": provider_id, "target": target},
        "offset_ms": offset_ms,
    }


# ── the library, faked ─────────────────────────────────────────────────────────────────────


@dataclass
class Reply:
    """What the fake library does for one question."""

    tokens: tuple[str, ...] = ("The ramp was widened last week [cite: s3 ¶4-9].",)
    text: str = ""
    delay: float = 0.0
    raises: BaseException | None = None
    #: Held here until the test sets it — the answering call still in flight.
    gate: asyncio.Event | None = None
    retrieved: bool = True

    @property
    def answer_text(self) -> str:
        return self.text or "".join(self.tokens)


class FakeLibrarian:
    """A `Librarian` the test drives: one ask per script entry, one reply per question."""

    def __init__(
        self,
        *,
        asks: list[Ask] | None = None,
        reply: Reply | None = None,
        replies: dict[str, Reply] | None = None,
        vocabulary_text: str = "- Ferry Scheduling Rebuild",
    ) -> None:
        self._asks = list(asks or [Ask(question="How far did the ferry scheduling rebuild get?")])
        self._reply = reply or Reply()
        self._replies = dict(replies or {})
        self._vocabulary = vocabulary_text
        self.warmed = 0
        self.vocabulary_calls: list[str] = []
        self.ask_calls: list[dict] = []
        self.questions: list[str] = []
        self.started: list[str] = []
        self.cancelled: list[str] = []

    async def warm(self) -> None:
        self.warmed += 1

    async def vocabulary(self, heard: str) -> str:  # noqa: A002
        self.vocabulary_calls.append(heard)
        return self._vocabulary

    async def form_ask(self, ledger: Ledger, *, earlier, vocabulary) -> Ask:
        self.ask_calls.append(
            {"tail": ledger.tail(), "earlier": list(earlier), "vocabulary": vocabulary}
        )
        # Formation is a model call and therefore yields; a fake that returns without ever
        # reaching the event loop would hide the speculative attempt it runs beside.
        await asyncio.sleep(0)
        return self._asks.pop(0) if len(self._asks) > 1 else self._asks[0]

    async def answer(self, question: str, *, on_token, on_retrieved) -> LibraryAnswer:
        reply = self._replies.get(question, self._reply)
        self.questions.append(question)
        self.started.append(question)
        try:
            if reply.gate is not None:
                await reply.gate.wait()
            if reply.delay:
                await asyncio.sleep(reply.delay)
            if reply.raises is not None:
                raise reply.raises
            if reply.retrieved:
                on_retrieved()
            for token in reply.tokens:
                on_token(token)
                await asyncio.sleep(0)
            return LibraryAnswer(
                payload={"answer": reply.answer_text, "question": question},
                answer_text=reply.answer_text,
            )
        except asyncio.CancelledError:
            self.cancelled.append(question)
            raise


# ── harness ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def settle_at_once(monkeypatch):
    """The transcript-settling wait is real time nobody's assertion is about; one test below
    turns it back on to pin what it is for."""
    monkeypatch.setattr(session_module, "SETTLE_QUIET_SECONDS", 0.0)
    monkeypatch.setattr(session_module, "SETTLE_MAX_SECONDS", 0.0)


async def until(predicate, *, timeout: float = 3.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what or 'the condition'}")


def drain(queue: asyncio.Queue) -> list[dict]:
    frames: list[dict] = []
    while True:
        try:
            frames.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return frames


def card(session: CallSession, delegation_id: str = "d1"):
    """The card, or None — a predicate that raises cannot be polled on."""
    return session.delegations.get(delegation_id)


def card_state(session: CallSession, delegation_id: str = "d1") -> str:
    found = card(session, delegation_id)
    return found.state if found is not None else ""


def states(frames, delegation_id: str = "d1") -> list[str]:
    out = []
    for frame in frames:
        if frame.get("type") == "delegation" and frame["delegation"]["id"] == delegation_id:
            if not out or out[-1] != frame["delegation"]["state"]:
                out.append(frame["delegation"]["state"])
    return out


@contextlib.asynccontextmanager
async def running(librarian, *, events=(), **kwargs):
    """A call on a scripted channel, torn down however the test leaves it."""
    channel = ScriptedChannel(events)
    session = CallSession(
        user_id=USER,
        librarian=librarian,
        idle_seconds=kwargs.pop("idle_seconds", 0),
        max_seconds=kwargs.pop("max_seconds", 0),
        **kwargs,
    )
    queue = session.attach()
    runner = asyncio.create_task(session.run(channel))
    try:
        yield session, channel, queue
    finally:
        channel.stop()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(runner, 2.0)
        runner.cancel()
        with contextlib.suppress(BaseException):
            await runner


# ── a delegation is claimed once, and only the client's ────────────────────────────────────


async def test_a_delegation_addressed_somewhere_other_than_the_client_is_ignored():
    """The provider routes delegations; one that is not ours is not ours to answer."""
    librarian = FakeLibrarian()
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1", target="server")]) as (
        session,
        _channel,
        _queue,
    ):
        await asyncio.sleep(0.05)
        assert session.delegations == {}
        assert librarian.ask_calls == [] and librarian.questions == []


async def test_a_delegation_delivered_twice_runs_the_lookup_once():
    """The id is claimed before any work starts, so a redelivered event costs nothing —
    a duplicate lookup would also hand the voice the same words twice."""
    gate = asyncio.Event()
    librarian = FakeLibrarian(reply=Reply(gate=gate))
    async with running(
        librarian, events=[heard("第二点呢"), delegated("dg-1"), delegated("dg-1")]
    ) as (session, _channel, _queue):
        await until(lambda: librarian.started, what="the first lookup")
        await asyncio.sleep(0.05)
        assert list(session.delegations) == ["d1"]
        assert len(librarian.questions) == 1
        gate.set()
        await until(lambda: card_state(session) == "done", what="the card to finish")


# ── the happy path ─────────────────────────────────────────────────────────────────────────


async def test_a_delegation_walks_the_card_from_hearing_to_done_and_speaks_the_answer():
    gate = asyncio.Event()
    librarian = FakeLibrarian(
        asks=[Ask(question="How far did the ferry scheduling rebuild get?")],
        reply=Reply(tokens=("The ramp was widened last week [cite: s3 ¶4-9]. ",), gate=gate),
    )
    events = [
        said("Three things landed this week.", start_ms=0, end_ms=1500),
        heard("第二点呢", start_ms=1700, end_ms=2600),
        delegated("dg-1"),
    ]
    async with running(librarian, events=events) as (session, channel, queue):
        await until(lambda: card_state(session) == "searching", what="searching")
        gate.set()
        await until(lambda: card_state(session) == "done", what="the card to finish")
        frames = drain(queue)
        delegation = session.delegations["d1"]

    assert frames[0] == {"type": "attached"}
    assert states(frames) == ["hearing", "searching", "answering", "done"]
    assert librarian.questions == ["How far did the ferry scheduling rebuild get?"]
    assert delegation.ask == "How far did the ferry scheduling rebuild get?"
    # Ask formation read both sides of the call, and the library's own vocabulary with it.
    tail = librarian.ask_calls[0]["tail"]
    assert "Three things landed this week." in tail and "第二点呢" in tail
    assert librarian.ask_calls[0]["vocabulary"] == "- Ferry Scheduling Rebuild"
    assert channel.spoken("dg-1") == ["The ramp was widened last week."]
    assert delegation.answer == {
        "answer": "The ramp was widened last week [cite: s3 ¶4-9]. ",
        "question": "How far did the ferry scheduling rebuild get?",
    }
    assert delegation.spoken is True and delegation.elapsed_ms is not None


async def test_the_canonical_tree_is_read_while_the_owner_is_still_saying_hello():
    """Warming is why the first ask does not wait for a git read it could have done during
    the greeting."""
    librarian = FakeLibrarian()
    async with running(librarian) as (_session, _channel, _queue):
        await until(lambda: librarian.warmed == 1, what="the warm read")


async def test_the_words_that_land_after_the_delegation_event_are_still_in_the_question(
    monkeypatch,
):
    """The delegation event routinely arrives BEFORE the last words of the sentence it is
    about, so the transcript is given a moment to go quiet before it is read."""
    monkeypatch.setattr(session_module, "SETTLE_QUIET_SECONDS", 0.08)
    monkeypatch.setattr(session_module, "SETTLE_MAX_SECONDS", 1.0)
    librarian = FakeLibrarian()
    async with running(librarian, events=[heard("ferry scheduling ", end_ms=1800)]) as (
        _session,
        channel,
        _queue,
    ):
        await asyncio.sleep(0.02)
        channel.feed(delegated("dg-1"))
        await asyncio.sleep(0.02)
        channel.feed(heard("rebuild, how far did it get?", start_ms=1800, end_ms=2600))
        await until(lambda: librarian.ask_calls, what="ask formation")
        assert "rebuild, how far did it get?" in librarian.ask_calls[0]["tail"]


# ── the barge-in rule ──────────────────────────────────────────────────────────────────────


async def test_a_second_ask_silences_the_first_while_its_card_still_finishes():
    """THE rule of this file. A spoken interruption cancels nothing at the provider — the
    decision is ours and it is mechanical: the overtaken delegation finishes its lookup and
    completes its card, and the voice hears nothing more about it. The screen keeps every
    answer; the voice follows the latest ask."""
    first_gate, second_gate = asyncio.Event(), asyncio.Event()
    librarian = FakeLibrarian(
        asks=[Ask(question="first question"), Ask(question="second question")],
        replies={
            "first question": Reply(tokens=("The FIRST answer, about the ramp. ",), gate=first_gate),
            "second question": Reply(tokens=("The SECOND answer, about the roster. ",), gate=second_gate),
        },
    )
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: librarian.started == ["first question"], what="the first lookup")

        channel.feed(delegated("dg-2"))
        await until(lambda: getattr(card(session), "spoken", True) is False, what="the first to go quiet")
        await until(lambda: librarian.started == ["first question", "second question"], what="the second lookup")

        first_gate.set()
        await until(lambda: card_state(session) == "done", what="the first card")
        second_gate.set()
        await until(lambda: card_state(session, "d2") == "done", what="the second card")

        first, second = session.delegations["d1"], session.delegations["d2"]

    # The overtaken ask completed in full, on screen.
    assert first.state == "done" and first.answer["answer"] == "The FIRST answer, about the ramp. "
    assert first.spoken is False and first.said == ""
    # And the voice was handed nothing for it, ever.
    assert channel.spoken("dg-1") == []
    assert channel.spoken("dg-2") == ["The SECOND answer, about the roster."]
    assert second.spoken is True


# ── the spoken budget ──────────────────────────────────────────────────────────────────────


def sentence(index: int) -> str:
    return f"第{index}句" + "报" * 55 + "。"


async def test_hand_overs_stop_at_the_spoken_budget_while_the_card_keeps_the_whole_answer():
    """About twenty-five seconds of speech is the whole budget for one ask: an answering model
    asked for seventy characters writes a hundred and fifty often enough, and the owner can
    ask for the rest. The card is not budgeted — the screen has room."""
    sentences = [sentence(index) for index in range(1, 6)]
    librarian = FakeLibrarian(reply=Reply(tokens=tuple(sentences)))
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the card to finish")
        delegation = session.delegations["d1"]

    assert channel.spoken("dg-1") == sentences[:3]
    assert len(delegation.said) >= SPOKEN_BUDGET_CHARS
    assert sentences[3] not in delegation.said and sentences[4] not in delegation.said
    assert delegation.answer["answer"] == "".join(sentences)


# ── every failure ends as a sentence ───────────────────────────────────────────────────────


async def test_a_library_that_raises_ends_as_a_failed_card_and_a_spoken_sentence():
    """A voice told not to guess and handed nothing has nothing to say, and the owner hears
    silence on a live phone call."""
    librarian = FakeLibrarian(reply=Reply(raises=RuntimeError("the index is unreachable")))
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "failed", what="the failed card")
        delegation = session.delegations["d1"]

    assert delegation.detail == "RuntimeError"
    assert channel.spoken("dg-1") == [prompt("call.say.failed")]


async def test_a_lookup_that_runs_past_its_ceiling_ends_as_a_failed_card_and_a_spoken_sentence(
    monkeypatch,
):
    monkeypatch.setattr(session_module, "ANSWER_TIMEOUT_SECONDS", 0.05)
    librarian = FakeLibrarian(reply=Reply(delay=5.0))
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "failed", what="the failed card")
        delegation = session.delegations["d1"]

    assert delegation.detail == "timed out"
    assert channel.spoken("dg-1") == [prompt("call.say.failed")]


async def test_a_lookup_slow_enough_to_notice_gets_one_holding_line_and_only_one(monkeypatch):
    """The voice covers the first seconds on its own, so this is not for the ordinary wait —
    it is for the one that has gone wrong enough to be worth mentioning and not yet wrong
    enough to have failed. A voice that keeps announcing that it is still looking is worse
    than a voice that is quiet, so it is said once."""
    monkeypatch.setattr(session_module, "PROGRESS_AFTER_SECONDS", 0.05)
    gate = asyncio.Event()
    librarian = FakeLibrarian(reply=Reply(tokens=("The ramp was widened last week. ",), gate=gate))
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: channel.spoken("dg-1"), what="the holding line")
        assert channel.spoken("dg-1") == [prompt("call.say.working")]
        await asyncio.sleep(0.15)
        gate.set()
        await until(lambda: card_state(session) == "done", what="the card to finish")

    assert channel.spoken("dg-1") == [
        prompt("call.say.working"),
        "The ramp was widened last week.",
    ]


async def test_a_second_ask_is_formed_knowing_what_was_already_asked_and_answered():
    """A follow-up needs the answer it follows up on: "and the second one?" resolves against
    what the voice was handed, not against what the library happens to hold."""
    librarian = FakeLibrarian(
        asks=[Ask(question="first question"), Ask(question="second question")],
        replies={
            "first question": Reply(tokens=("Three things landed. ",)),
            "second question": Reply(tokens=("The ramp was widened. ",)),
        },
    )
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the first card")
        channel.feed(delegated("dg-2"))
        await until(lambda: card_state(session, "d2") == "done", what="the second card")

    assert librarian.ask_calls[0]["earlier"] == []
    assert librarian.ask_calls[1]["earlier"] == [
        Exchange(question="first question", said="Three things landed.")
    ]


async def test_a_transcript_that_establishes_no_question_asks_the_owner_instead():
    """`ready=False` is a judgement, not a failure: retrieval is never run on a question
    nobody established, and the voice puts the clarifying question."""
    librarian = FakeLibrarian(asks=[Ask(question="", clarify="Which of the three do you mean?")])
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "unclear", what="the unclear card")
        delegation = session.delegations["d1"]

    assert delegation.detail == "Which of the three do you mean?"
    assert channel.spoken("dg-1") == ["Which of the three do you mean?"]
    assert librarian.questions == []


# ── speculation ────────────────────────────────────────────────────────────────────────────


HEARD_ENOUGH = "渡口排班重写进度怎么样"


async def test_the_owners_own_words_go_to_the_library_before_the_question_is_written():
    """Writing the question out of the transcript is the largest single wait in a lookup, and
    for a first question asked in a whole sentence it returns the owner's own words back. So
    those words are tried at once, beside the call that may replace them."""
    gate = asyncio.Event()
    librarian = FakeLibrarian(
        asks=[Ask(question=HEARD_ENOUGH + "？")],
        reply=Reply(tokens=("排班重写上周做完了。",), gate=gate),
    )
    async with running(librarian, events=[heard(HEARD_ENOUGH), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: librarian.started == [HEARD_ENOUGH], what="the speculative lookup")
        gate.set()
        await until(lambda: card_state(session) == "done", what="the card to finish")
        delegation = session.delegations["d1"]

    # The formed question differed only in punctuation, so the attempt already running stood
    # and exactly one lookup was spent.
    assert librarian.questions == [HEARD_ENOUGH]
    assert delegation.timings["speculated"] == 1
    assert channel.spoken("dg-1") == ["排班重写上周做完了。"]


async def test_a_speculative_attempt_the_formed_question_disagrees_with_is_never_spoken():
    """The unused attempt is a cost this design owns; a WRONG answer spoken over the owner is
    not one it may pay."""
    librarian = FakeLibrarian(
        asks=[Ask(question="上周渡口排班重写的结论是什么")],
        replies={
            HEARD_ENOUGH: Reply(tokens=("SPECULATIVE。",), delay=5.0),
            "上周渡口排班重写的结论是什么": Reply(tokens=("FORMED。",)),
        },
    )
    async with running(librarian, events=[heard(HEARD_ENOUGH), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the card to finish")
        delegation = session.delegations["d1"]

    assert librarian.questions == [HEARD_ENOUGH, "上周渡口排班重写的结论是什么"]
    assert librarian.cancelled == [HEARD_ENOUGH]
    assert channel.spoken("dg-1") == ["FORMED。"]
    assert delegation.timings["speculated"] == 0
    assert delegation.ask == "上周渡口排班重写的结论是什么"


async def test_words_too_few_to_be_a_question_are_not_speculated_on():
    """A bare reference ("第二点呢" — "the second point?") is not a question, and a lookup on
    it is wasted by construction."""
    librarian = FakeLibrarian(asks=[Ask(question="上周渡口排班重写的结论是什么")])
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        _channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the card to finish")
        delegation = session.delegations["d1"]

    assert librarian.questions == ["上周渡口排班重写的结论是什么"]
    assert delegation.timings["speculated"] == 0


# ── acknowledgements, usage, the close ─────────────────────────────────────────────────────


async def test_an_acknowledgement_records_its_interval_on_the_card_it_belongs_to():
    """An ack is not speech: the provider sends it when it estimates the text reached the
    model's context. What is kept is its interval, which is what lets a reader tell which
    spoken lines stand on which answer — and mark the ones that stand on none."""
    librarian = FakeLibrarian(reply=Reply(tokens=("The ramp was widened last week. ",)))
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: channel.commentary("dg-1"), what="a hand-over")
        event_id = channel.commentary("dg-1")[0]["event_id"]
        channel.feed(
            {
                "type": "session.commentary.appended",
                "client_event_id": event_id,
                "start_ms": 4100,
                "end_ms": 6200,
            }
        )
        await until(lambda: getattr(card(session), "deliveries", None), what="the ack")
        delegation = session.delegations["d1"]

    assert delegation.deliveries == [{"start_ms": 4100, "end_ms": 6200}]


async def test_an_acknowledgement_for_nothing_this_process_sent_changes_no_card():
    librarian = FakeLibrarian()
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the card")
        channel.feed(
            {
                "type": "session.commentary.appended",
                "client_event_id": "somebody-elses-event",
                "start_ms": 1,
                "end_ms": 2,
            }
        )
        await asyncio.sleep(0.05)
        assert session.delegations["d1"].deliveries == []


async def test_usage_updates_are_published_and_the_closing_figure_is_the_authoritative_one():
    """Silence is billed: what the call cost is the provider's own number at the close, not
    the last mid-call estimate."""
    async with running(FakeLibrarian()) as (session, channel, queue):
        channel.feed(
            {
                "type": "session.usage.updated",
                "usage": {"seconds": 12.5},
                "context_window": {"usage_ratio": 0.31},
            }
        )
        await until(lambda: session.seconds == 12.5, what="the usage frame")
        channel.feed(
            {"type": "session.closed", "reason": "client_closed", "usage": {"seconds": 31.0}}
        )
        await until(lambda: session.closed.is_set(), what="the close")
        frames = drain(queue)

    assert {"type": "usage", "seconds": 12.5, "context_ratio": 0.31} in frames
    assert frames[-1] == {"type": "closed", "reason": "client_closed", "seconds": 31.0}
    assert session.seconds == 31.0


async def test_a_sideband_that_simply_stops_still_closes_the_call():
    async with running(FakeLibrarian()) as (session, channel, _queue):
        channel.stop()
        await until(lambda: session.closed.is_set(), what="the close")
        assert session.close_reason == "connection_lost"


# ── the two clocks that end a call ─────────────────────────────────────────────────────────


async def test_a_call_that_has_heard_nothing_for_too_long_is_closed_from_here():
    """A session bills by the minute whether or not anybody speaks."""
    async with running(FakeLibrarian(), idle_seconds=0.01, max_seconds=0) as (
        session,
        _channel,
        _queue,
    ):
        await until(lambda: session.closed.is_set(), timeout=5.0, what="the idle close")
        assert session.close_reason == "idle"


async def test_a_call_that_has_run_past_its_ceiling_is_closed_from_here():
    async with running(FakeLibrarian(), idle_seconds=0, max_seconds=0.01) as (
        session,
        _channel,
        _queue,
    ):
        await until(lambda: session.closed.is_set(), timeout=5.0, what="the duration close")
        assert session.close_reason == "max_duration"


async def test_this_processs_own_reason_survives_the_providers_acknowledging_close():
    """The provider says only that somebody asked; this process knows WHY it asked."""
    async with running(FakeLibrarian(), idle_seconds=0.01, max_seconds=0) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: session.closed.is_set(), timeout=5.0, what="the idle close")
        assert [event["type"] for event in channel.sent] == ["session.close"]
        assert session.close_reason == "idle"


# ── who is watching ────────────────────────────────────────────────────────────────────────


async def test_a_late_subscriber_is_repainted_from_state_and_then_follows_live():
    """A tab that reconnects mid-call, or after it ended, must see the same call the first
    tab saw — the cards are state here, not a replay of a stream it missed."""
    librarian = FakeLibrarian()
    async with running(librarian, events=[heard("第二点呢"), delegated("dg-1")]) as (
        session,
        channel,
        _queue,
    ):
        await until(lambda: card_state(session) == "done", what="the card")
        late = session.attach()
        repaint = drain(late)
        assert repaint[0] == {"type": "attached"}
        assert [frame["delegation"]["state"] for frame in repaint[1:]] == ["done"]

        channel.feed(delegated("dg-2"))
        await until(lambda: "d2" in session.delegations, what="the second card")
        assert any(
            frame.get("type") == "delegation" and frame["delegation"]["id"] == "d2"
            for frame in drain(late)
        )

        session.detach(late)
        channel.feed({"type": "session.usage.updated", "usage": {"seconds": 3.0}})
        await until(lambda: session.seconds == 3.0, what="the usage frame")
        assert drain(late) == []


async def test_a_subscriber_that_joins_after_the_close_is_told_the_call_ended():
    async with running(FakeLibrarian()) as (session, channel, _queue):
        channel.feed({"type": "session.closed", "reason": "client_closed", "usage": {"seconds": 9.0}})
        await until(lambda: session.closed.is_set(), what="the close")
        frames = drain(session.attach())

    assert frames == [{"type": "attached"}, {"type": "closed", "reason": "client_closed", "seconds": 9.0}]


# ── the registry ───────────────────────────────────────────────────────────────────────────


def a_session(user: str = USER, call_id: str | None = None) -> CallSession:
    return CallSession(user_id=user, librarian=FakeLibrarian(), call_id=call_id)


async def test_a_new_call_ends_the_one_the_same_owner_already_had():
    """The usual reason an owner has two is a tab that died mid-call, and that session is
    still billing."""
    registry = CallSessions()
    first = a_session(call_id="call-one")
    registry.start(first, asyncio.create_task(asyncio.sleep(0)))
    assert registry.live(USER) is True

    await registry.replace(USER)
    assert first.close_reason == "replaced" and first.closed.is_set()
    assert registry.live(USER) is False

    second = a_session(call_id="call-two")
    registry.start(second, asyncio.create_task(asyncio.sleep(0)))
    assert registry.live(USER) is True
    assert registry.get("call-two") is second
    assert registry.get("call-one") is first
    assert registry.get("no-such-call") is None
    await asyncio.sleep(0)


async def test_one_owners_call_is_not_another_owners_live_call():
    """I1: a call is a per-user thing like everything else."""
    registry = CallSessions()
    registry.start(a_session("u-one", "c1"), asyncio.create_task(asyncio.sleep(0)))
    assert registry.live("u-one") is True
    assert registry.live("u-two") is False
    await asyncio.sleep(0)


async def test_closing_the_registry_ends_every_call_it_holds():
    registry = CallSessions()
    one, two = a_session("u-one", "c1"), a_session("u-two", "c2")
    registry.start(one, asyncio.create_task(asyncio.sleep(0)))
    registry.start(two, asyncio.create_task(asyncio.sleep(0)))
    await registry.aclose()
    assert (one.close_reason, two.close_reason) == ("shutdown", "shutdown")
    await asyncio.sleep(0)


# ── the session the provider is given ──────────────────────────────────────────────────────


def test_the_browsers_data_channel_may_carry_exactly_three_commands():
    """THE security property of this design: the page cannot append an instruction, a quiet
    context or a spoken line to the voice — not as a rule it is asked to follow, but as a
    command the provider refuses. Adding a fourth command here turns this red on purpose."""
    config = session_config(Settings(call_model="voice-model-x"), zone="Europe/Lisbon")
    assert config["client"]["data_channel"]["allowed_client_events"] == [
        "session.close",
        "session.input_audio.mute",
        "session.input_audio.unmute",
    ]
    assert tuple(config["client"]["data_channel"]["allowed_client_events"]) == BROWSER_COMMANDS


def test_the_session_carries_the_standing_prompt_and_delegates_to_the_client():
    config = session_config(Settings(call_model="voice-model-x", call_voice="marin"), zone="UTC")
    assert config["model"] == "voice-model-x"
    assert config["audio"]["output"]["voice"] == "marin"
    assert config["delegation"] == {"type": "client"}
    assert "Delegation policy:" in config["instructions"]


def test_what_day_it_is_rides_in_as_context_and_never_in_the_standing_prompt():
    """I5 in the shape this surface takes it: the instructions are one byte-string per
    language, so what changes per call is seeded as conversation context instead."""
    from datetime import datetime, timezone

    now = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)
    config = session_config(Settings(), zone="Asia/Tokyo", now=now)
    context = config["input"][0]["content"][0]["text"]
    assert config["input"][0]["role"] == "developer"
    assert "2026-09-17" in context and "Asia/Tokyo" in context
    assert "Thursday" in context
    assert "2026-09-17" not in config["instructions"]


def test_a_zone_nobody_can_resolve_is_not_a_reason_to_refuse_a_call():
    config = session_config(Settings(), zone="Middle/Earth")
    assert "UTC" in config["input"][0]["content"][0]["text"]


# ── can this deployment place a call at all ────────────────────────────────────────────────


def test_without_a_provider_key_the_console_is_told_which_key_is_missing():
    status = call_status(Settings(openai_api_key=""), live=False)
    assert status["configured"] is False and status["reason"] == "no_openai_key"
    assert "OPENAI_API_KEY" in status["detail"]


def test_with_a_key_but_no_model_the_lane_behind_the_voice_is_what_is_missing():
    """A call answers from the fast lane, so a deployment that can reach the voice and not the
    library cannot place one — and the button says which half is missing."""
    status = call_status(keyed(llm_model="openrouter:some/model"), live=False)
    assert status["configured"] is False and status["reason"] == "no_recall_model"


def test_with_both_the_call_is_configured_and_the_status_names_model_and_voice():
    settings = keyed(
        llm_model_call="scripted:call", call_model="voice-model-x", call_voice="marin"
    )
    status = call_status(settings, live=True)
    assert status == {
        "configured": True,
        "reason": "",
        "detail": "",
        "model": "voice-model-x",
        "voice": "marin",
        "live": True,
    }
