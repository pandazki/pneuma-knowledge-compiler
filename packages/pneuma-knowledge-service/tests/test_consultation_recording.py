"""Emitting a consultation: what the request path does, and what it refuses to wait for.

The record is bookkeeping ABOUT an answer that has already been produced, and the delivery
model says so out loud: the route EMITS the event and returns. It writes the row and — for a
`business` visitor — enqueues one `recall_projection` job in the same transaction; consuming
that job is the worker's, on the same per-user queue the ingest side already drains. Nothing
in the answering path processes anything, and nothing in it waits.

The routes are driven directly and their `body_iterator` drained, for the same reason
`test_recall_stream.py` does it: the property under test is ORDERING inside the streaming
machinery, and an ASGI client that buffers the whole body cannot see it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.components import register_component, reset_components

from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import (
    RecallIn,
    drain_recording_tasks,
    recall,
    recall_stream,
)

_TIMEOUT = 5.0


@dataclass
class _FakeDeepAnswer:
    answer: str = "答案。[cite: src-01 ¶1-2]"
    used_claims: tuple = ()
    used_windows: tuple = ()
    trail: list = field(default_factory=list)
    glance_chars: int = 0
    read_documents: tuple = ()
    image_count: int = 0
    image_mode: str = "caption"
    stages: tuple = ()
    evidence_manifest: tuple = ()
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 7})


class _RecordingStore:
    """The store's half of the emit: one row, and one job for a `business` visitor.

    It yields to the loop before it lands, and the yielding is the whole point. A stub that
    completed without ever awaiting would be written even by a caller that never gave the
    task a chance to run, so it could not tell "detached and scheduled" from "awaited".
    """

    def __init__(self, *, yields: int = 50) -> None:
        self.rows: list = []
        self.jobs: list = []
        self._yields = yields

    async def create_consultation(self, user, record) -> str | None:  # noqa: ANN001
        for _ in range(self._yields):
            await asyncio.sleep(0)
        self.rows.append((str(user), record))
        if record.visitor_class != "business":
            return None
        job_id = f"j-{len(self.jobs) + 1}"
        self.jobs.append((str(user), "recall_projection", record.consultation_id))
        return job_id


class _CountingComponent:
    name = "test-recall-counter"

    def __init__(self) -> None:
        self.seen: list = []

    async def on_recall(self, user_id: str, record) -> None:  # noqa: ANN001
        self.seen.append((user_id, record))


@pytest.fixture
def component():
    reset_components()
    counter = _CountingComponent()
    register_component(counter)
    try:
        yield counter
    finally:
        reset_components()


async def _no_snapshots(user):  # noqa: ANN001
    return []


async def _no_profile(user):  # noqa: ANN001
    raise RuntimeError("no profile provider in this test")


def _request(store) -> SimpleNamespace:  # noqa: ANN001
    ctx = SimpleNamespace(
        canonical=SimpleNamespace(snapshots=_no_snapshots),
        user_info=SimpleNamespace(get_profile=_no_profile),
        langfuse_handler=lambda: None,
        lexical=None,
        vectors=None,
        embeddings=None,
        media=object(),
        store=store,
        get_chat_model=lambda role="default": None,
        settings=SimpleNamespace(
            recall_answer_style="conversational",
            llm_model="scripted:record-test",
            openrouter_api_key="",
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


def _frame(raw: str) -> tuple[str, dict]:
    lines = raw.strip().splitlines()
    return lines[0][7:], json.loads(lines[1][6:])


def _body(**kwargs) -> RecallIn:
    return RecallIn(query="阿宝在盯哪条线？", mode="deep", visitor_class="business", **kwargs)


async def _fake_deep(*_args, **_kwargs):
    return _FakeDeepAnswer()


async def _drain(iterator) -> list[tuple[str, dict]]:
    return [_frame(chunk) async for chunk in iterator]


# ------------------------------------------------ what a business consultation produces


async def test_a_business_consultation_is_one_row_and_one_queued_job(
    monkeypatch, component
):
    """Row and job, and nothing consumed in the request path: the component hears about
    this consultation from the WORKER, when the job is drained, not from the route."""
    store = _RecordingStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    await recall("u-mei", _body(), _request(store))
    await drain_recording_tasks(_TIMEOUT)

    assert len(store.rows) == 1
    user, record = store.rows[0]
    assert user == "u-mei" and record.lane == "deep" and record.visitor_class == "business"
    assert store.jobs == [("u-mei", "recall_projection", record.consultation_id)]
    assert component.seen == []


async def test_an_audit_consultation_is_a_row_and_no_job(monkeypatch, component):
    """Recording and influence are two axes: a consultation reconstructible after the fact,
    steering nothing — so there is nothing for a consumer to be handed."""
    store = _RecordingStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    await recall(
        "u-mei",
        RecallIn(query="q", mode="deep", visitor_class="audit"),
        _request(store),
    )
    await drain_recording_tasks(_TIMEOUT)

    assert len(store.rows) == 1 and store.jobs == [] and component.seen == []


async def test_a_silent_visitor_leaves_no_row_on_either_route(monkeypatch, component):
    """`silent` is the default, and it returns before anything is built — the read-side face
    of I6: a harness cannot steer the steward it is judging. Not a row, not a job, and not
    even a task."""
    store = _RecordingStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    await recall("u-mei", RecallIn(query="q", mode="deep"), _request(store))
    response = await recall_stream("u-mei", RecallIn(query="q", mode="deep"), _request(store))
    _ = [chunk async for chunk in response.body_iterator]
    await drain_recording_tasks(_TIMEOUT)

    assert store.rows == [] and store.jobs == [] and component.seen == []
    assert not [t for t in v1_module._RECORDING_TASKS if not t.done()]


# --------------------------------------------- what the answer is never made to wait for


class _BlockedStore(_RecordingStore):
    """A store whose write does not land until the test says so."""

    def __init__(self) -> None:
        super().__init__(yields=0)
        self.released = asyncio.Event()

    async def create_consultation(self, user, record) -> str | None:  # noqa: ANN001
        await self.released.wait()
        return await super().create_consultation(user, record)


async def test_the_terminal_frame_is_emitted_without_waiting_on_the_recording(
    monkeypatch, component
):
    """The property the delivery ruling is about. The store's write never completes until
    this test releases it, and `done` arrives anyway — so nothing between the answer and the
    reader is holding a place for bookkeeping. Under the previous shape this test hung for
    the whole recording budget and then passed for the wrong reason."""
    store = _BlockedStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    response = await recall_stream("u-mei", _body(), _request(store))
    frames = await asyncio.wait_for(_drain(response.body_iterator), _TIMEOUT)

    assert [kind for kind, _ in frames][-1] == "done"
    assert store.rows == []  # still blocked

    store.released.set()
    await drain_recording_tasks(_TIMEOUT)
    assert len(store.rows) == 1 and len(store.jobs) == 1


async def test_a_client_that_stops_reading_at_done_still_leaves_one_row(
    monkeypatch, component
):
    """The reader takes the terminal frame and walks away, which cancels the producer
    immediately. The recording is a SIBLING task with a strong reference of its own, so it
    outlives that cancellation — which is what makes "emit and return" safe rather than
    lossy in the one case the old ordering comment was written for."""
    store = _RecordingStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    response = await recall_stream("u-mei", _body(), _request(store))
    frames = response.body_iterator
    kind, _payload = _frame(await asyncio.wait_for(frames.__anext__(), _TIMEOUT))
    assert kind == "done"
    await frames.aclose()
    await drain_recording_tasks(_TIMEOUT)

    assert len(store.rows) == 1 and len(store.jobs) == 1


async def test_a_store_that_raises_costs_the_record_and_never_the_answer(
    monkeypatch, component
):
    """Fail-soft, in the one place it still applies: the answer has already been produced
    and is already on its way out, and the emit is best-effort by construction."""

    class _RaisingStore:
        async def create_consultation(self, user, record):  # noqa: ANN001
            raise RuntimeError("the database is having a day")

    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    out = await asyncio.wait_for(
        recall("u-mei", _body(), _request(_RaisingStore())), _TIMEOUT
    )
    await drain_recording_tasks(_TIMEOUT)

    assert out.answer.startswith("答案")


async def test_the_plain_route_returns_without_waiting_on_the_recording(
    monkeypatch, component
):
    """The same property on the route that has no streaming machinery around it. The
    streaming case is the one with an ordering question, but the acceptance is the ROUTE's
    shape — and a plain `await` reintroduced here would be invisible to every stream test."""
    store = _BlockedStore()
    monkeypatch.setattr(v1_module, "deep_recall", _fake_deep)

    out = await asyncio.wait_for(recall("u-mei", _body(), _request(store)), _TIMEOUT)

    assert out.answer.startswith("答案")
    assert store.rows == []  # still blocked when the answer was handed back

    store.released.set()
    await drain_recording_tasks(_TIMEOUT)
    assert len(store.rows) == 1 and len(store.jobs) == 1


async def test_the_briefing_ask_route_emits_on_the_same_terms(monkeypatch, component):
    """The fourth call site. It shares `_spawn_recording` with the other three, and this
    pins that it actually calls it rather than awaiting a write of its own."""
    store = _BlockedStore()
    record_holder: list = []

    async def _row(ctx, user, briefing_id):  # noqa: ANN001
        return {"briefing_id": briefing_id, "snapshot_ref": "deadbeef"}

    async def _answered(ctx, user, briefing_id, row, question, **kwargs):  # noqa: ANN001
        out = v1_module.AskOut(
            answer="交期从两周缩短到五天。",
            citations=[],
            verbatim_fetches=[],
            token_usage={"total_tokens": 3},
        )
        record = v1_module._consultation(
            lambda answer, **kw: SimpleNamespace(
                lane=kw["lane"],
                visitor_class=kw["visitor_class"],
                consultation_id=kw["consultation_id"],
            ),
            out,
            user=user,
            lane="briefing_ask",
            visitor_class=kwargs["visitor_class"],
            question=question,
            as_of=None,
            library_ref="deadbeef",
        )
        record_holder.append(record)
        return out, record

    monkeypatch.setattr(v1_module, "_briefing_row", _row)
    monkeypatch.setattr(v1_module, "_ask_over_briefing", _answered)

    out = await asyncio.wait_for(
        v1_module.ask_briefing(
            "u-mei",
            "b-1",
            v1_module.AskIn(question="交期缩短了多少？", visitor_class="business"),
            _request(store),
        ),
        _TIMEOUT,
    )

    assert out.answer.startswith("交期")
    assert store.rows == []  # the ask returned while the write was still blocked

    store.released.set()
    await drain_recording_tasks(_TIMEOUT)
    assert [r.lane for _u, r in store.rows] == ["briefing_ask"]
    assert len(store.jobs) == 1


def test_the_answering_routes_cannot_call_a_component_at_all():
    """"No component call in the request path" is a fact about the MODULE, not about what a
    stub store happened not to do: the fan-out moved to the worker, so the name the route
    used to reach it by is not there to be called back into by accident."""
    assert not hasattr(v1_module, "notify_recall")
