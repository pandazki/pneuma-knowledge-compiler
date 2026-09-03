"""Consultation records over the real stack — who leaves a trace, and who is seen.

Two halves. The adapter half asks whether a record is isolated and whether the replay face
returns what a rebuild can replay; the route half asks what each visitor class actually
costs, which is the whole point of having three of them: `silent` writes nothing at all,
`audit` writes and steers nothing, `business` writes and QUEUES — the components hear about
it when the worker drains that job, not while the owner is waiting for an answer.

Skips (only) when the middleware is unreachable — the sanctioned reason.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pneuma_knowledge_core.components import (
    BaseComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.access_stats import RECALL_PROJECTION_JOB_KIND
from pneuma_knowledge_service.api.routes.v1 import drain_recording_tasks
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs, drain_user

from test_api_e2e import _client, _open  # noqa: E402

DAY = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_registry():
    """No component is registered by default (`PNEUMA_KNOWLEDGE_COMPONENTS` is empty), so a
    test that registers one must leave the registry as it found it."""
    yield
    reset_components()


class _Recorder(BaseComponent):
    """A component whose only face is the use-side one: it remembers what it was told."""

    name = "consultation-recorder"

    def __init__(self) -> None:
        self.seen: list[ConsultationRecord] = []

    async def on_recall(self, user_id, record):
        self.seen.append(record)


def _record(user: UserId, consultation_id: str, *, minute: int, visitor_class: str):
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id=str(user),
        created_at=DAY + timedelta(minutes=minute),
        lane="fast",
        visitor_class=visitor_class,
        question=f"阿宝在第 {minute} 分钟问的问题",
        as_of=DAY,
        library_ref="a1b2c3d4",
        evidence_handed=(EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),),
        answer_kind="fact",
        answer="他在三月接手。",
        citations=(EvidenceRef("window", "src-01 ¶2-4", ""),),
        miss=False,
        degraded=(("glance_degraded", "timeout"),),
    )


# --------------------------------------------------------------------- the adapter


async def test_a_record_written_for_one_tenant_is_invisible_to_another(pg_store):
    """I1 on the use-side table: `user_id` is the first key, and there is no read path
    that omits it — a consultation is as isolated as the library it was asked of."""
    mei = UserId(f"u-it-{uuid.uuid4().hex[:10]}")
    bao = UserId(f"u-it-{uuid.uuid4().hex[:10]}")

    await pg_store.create_consultation(mei, _record(mei, "k-1", minute=0, visitor_class="audit"))

    assert [r.consultation_id for r in await pg_store.list_consultations(mei)] == ["k-1"]
    assert await pg_store.list_consultations(bao) == []


async def test_a_tenant_that_has_only_ever_asked_is_still_enumerable(pg_store):
    """What `rebuild_derived --all` needs and `list_users` cannot give it: a tenant can make
    business consultations before importing anything, and the projection derived from those
    records is exactly the layer an operator would need to repair."""
    mei = UserId(f"u-it-{uuid.uuid4().hex[:10]}")
    await pg_store.create_consultation(mei, _record(mei, "k-1", minute=0, visitor_class="business"))

    assert str(mei) in await pg_store.list_consultation_users()
    # ...and it owns no source, so the L0 listing does not know about it.
    assert str(mei) not in await pg_store.list_users()


async def test_the_replay_face_returns_records_in_the_order_they_were_recorded(pg_store):
    """The rebuild face: oldest first, bounded, and keyset-continued on
    `(created_at, consultation_id)` so the order is total rather than mostly-determined."""
    mei = UserId(f"u-it-{uuid.uuid4().hex[:10]}")
    for minute, cid, klass in [
        (2, "k-b", "business"),
        (0, "k-a", "audit"),
        (4, "k-c", "business"),
    ]:
        await pg_store.create_consultation(
            mei, _record(mei, cid, minute=minute, visitor_class=klass)
        )

    walked = await pg_store.list_consultations(mei)
    assert [r.consultation_id for r in walked] == ["k-a", "k-b", "k-c"]

    # Every field survives the round trip, addresses included.
    first = walked[0]
    assert first.evidence_handed == (EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),)
    assert first.citations == (EvidenceRef("window", "src-01 ¶2-4", ""),)
    assert first.degraded == (("glance_degraded", "timeout"),)
    assert first.miss is False and first.answer_kind == "fact"

    page = await pg_store.list_consultations(mei, limit=1)
    assert [r.consultation_id for r in page] == ["k-a"]
    rest = await pg_store.list_consultations(
        mei, after=(page[-1].created_at, page[-1].consultation_id)
    )
    assert [r.consultation_id for r in rest] == ["k-b", "k-c"]

    assert [
        r.consultation_id
        for r in await pg_store.list_consultations(mei, visitor_class="business")
    ] == ["k-b", "k-c"]
    assert [
        r.consultation_id
        for r in await pg_store.list_consultations(mei, since=DAY + timedelta(minutes=3))
    ] == ["k-c"]


# ----------------------------------------------------------------------- the routes


@pytest.fixture
async def answering_client(tmp_path):
    """The app with a scripted (keyless) answering model — enough for the fast lane to
    produce a real answer over real retrieval without a provider key."""
    script = tmp_path / "recall.json"
    script.write_text(
        json.dumps({"turns": [{"content": "交期从两周缩短到五天。"}] * 6}),
        encoding="utf-8",
    )
    s = Settings(
        canonical_root=str(tmp_path / "canonical"),
        llm_model=f"scripted:{script}",
    )
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    async with _client(create_app(s)) as c:
        yield c


async def _seeded_user(client) -> str:
    """One synthetic source, ingested and indexed, so the fast lane has something to hand
    to the model (an empty library would make every consultation a miss for the wrong
    reason)."""
    uid = f"u-it-{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        f"/v1/users/{uid}/sources/conversation",
        json={
            "title": "交付评审",
            "turns": [
                {
                    "speaker": "Mei LIN",
                    "text": "供应商把交期从两周缩短到五天。",
                    "at": "2026-08-20T09:00:00Z",
                },
                {
                    "speaker": "阿宝",
                    "text": "验收标准写进了 momo@example.com 发的那份附件。",
                    "at": "2026-08-20T09:05:00Z",
                },
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    await drain_index_jobs(client.app.state.ctx, UserId(uid))
    return uid


async def _consultations(client, uid: str) -> list[ConsultationRecord]:
    """The rows, after the detached recording tasks have had their moment.

    The route emits and returns, so a test that read the table the instant the response
    landed would be racing the write it is about — which is the property, not a flake."""
    await drain_recording_tasks(5.0)
    return await client.app.state.ctx.store.list_consultations(UserId(uid))


async def _jobs(client, uid: str, kind: str) -> list[dict]:
    await drain_recording_tasks(5.0)
    return [
        j
        for j in await client.app.state.ctx.store.list_jobs(UserId(uid))
        if j["kind"] == kind
    ]


async def _deliver(client, uid: str) -> None:
    """Drain this user's whole queue the way the worker does.

    The whole queue, not the projection jobs alone, and that is the delivery model showing
    through: the queue is per-user FIFO, so a projection enqueued behind this tenant's
    ingest compile is delivered after it. What that costs in wall-clock is the queue's, not
    the answer's — the answer was returned before any of this.
    """
    await drain_recording_tasks(5.0)
    await drain_user(client.app.state.ctx, None, None, UserId(uid))


async def test_a_silent_visitor_leaves_no_trace_at_all(answering_client):
    """The default. An evaluation harness, a benchmark, an auditor who must not disturb
    what they measure — none of them is recorded, and none of them has to say so."""
    uid = await _seeded_user(answering_client)
    recorder = _Recorder()
    register_component(recorder)

    resp = await answering_client.post(
        f"/v1/users/{uid}/recall", json={"query": "交期缩短了多少？", "mode": "fast"}
    )
    assert resp.status_code == 200, resp.text

    assert await _consultations(answering_client, uid) == []
    assert await _jobs(answering_client, uid, RECALL_PROJECTION_JOB_KIND) == []
    assert recorder.seen == []


async def test_an_audit_visitor_is_recorded_and_steers_nothing(answering_client):
    """Recording and influence are two axes, and `audit` is the point that separates them:
    the consultation is reconstructible, and no component ever hears about it."""
    uid = await _seeded_user(answering_client)
    recorder = _Recorder()
    register_component(recorder)

    resp = await answering_client.post(
        f"/v1/users/{uid}/recall",
        json={"query": "交期缩短了多少？", "mode": "fast", "visitor_class": "audit"},
    )
    assert resp.status_code == 200, resp.text

    records = await _consultations(answering_client, uid)
    assert len(records) == 1
    record = records[0]
    assert record.lane == "fast" and record.visitor_class == "audit"
    assert record.question == "交期缩短了多少？"
    assert record.evidence_handed  # real retrieval reached the model
    assert record.user_id == uid
    assert await _jobs(answering_client, uid, RECALL_PROJECTION_JOB_KIND) == []
    await _deliver(answering_client, uid)
    assert recorder.seen == []


async def test_a_business_visitor_is_recorded_and_queued_then_delivered(answering_client):
    """The delivery model, end to end. The response comes back with the job merely QUEUED
    and no component having heard anything; the worker's drain is what fans it out, and the
    built-in access statistics land in the same pass."""
    uid = await _seeded_user(answering_client)
    recorder = _Recorder()
    register_component(recorder)

    resp = await answering_client.post(
        f"/v1/users/{uid}/recall",
        json={"query": "交期缩短了多少？", "mode": "fast", "visitor_class": "business"},
    )
    assert resp.status_code == 200, resp.text

    records = await _consultations(answering_client, uid)
    assert len(records) == 1
    queued = await _jobs(answering_client, uid, RECALL_PROJECTION_JOB_KIND)
    assert [(j["status"], j["payload"]) for j in queued] == [
        ("queued", {"consultation_id": records[0].consultation_id})
    ]
    assert recorder.seen == []  # nothing was processed in the request path

    await _deliver(answering_client, uid)

    assert [r.consultation_id for r in recorder.seen] == [records[0].consultation_id]
    assert recorder.seen[0].visitor_class == "business"
    store = answering_client.app.state.ctx.store
    hits = await store.access_hits_since(UserId(uid), records[0].created_at.date())
    assert hits, "the built-in consumer wrote nothing"


async def test_the_rag_lane_records_nothing_under_any_class(answering_client):
    """`rag` returns a hit list. It reaches no model, so there is no "what was handed to
    one" for a record to be about — and a row saying otherwise would be a fiction."""
    uid = await _seeded_user(answering_client)
    recorder = _Recorder()
    register_component(recorder)

    for visitor_class in ("silent", "audit", "business"):
        resp = await answering_client.post(
            f"/v1/users/{uid}/recall",
            json={"query": "交期", "mode": "rag", "visitor_class": visitor_class},
        )
        assert resp.status_code == 200, resp.text

    assert await _consultations(answering_client, uid) == []
    assert await _jobs(answering_client, uid, RECALL_PROJECTION_JOB_KIND) == []
    assert recorder.seen == []


async def test_a_record_that_cannot_be_made_never_costs_the_answer(
    answering_client, monkeypatch
):
    """Fail-soft over the whole recording path, building included. The answer has already
    been produced by the time any of this runs; failing the request now would trade the
    thing the owner asked for against the note that they asked it."""
    from pneuma_knowledge_service.api.routes import v1 as v1_module

    uid = await _seeded_user(answering_client)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(v1_module, "consultation_from_fast", _explode)

    resp = await answering_client.post(
        f"/v1/users/{uid}/recall",
        json={"query": "交期缩短了多少？", "mode": "fast", "visitor_class": "business"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"]
    assert await _consultations(answering_client, uid) == []
