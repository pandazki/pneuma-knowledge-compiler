"""The pending recall hand-over's home in Postgres (coding-agent-mode §5.1).

The keyless suite proves `pkc recall --evidence` and `pkc consult answer` against the
in-memory stand-in; this is the same set of claims against real SQL — the row round-trips, it
is per-tenant, it is deleted when the answer arrives, and one nobody came back to is swept by
the same startup self-heal that reclaims abandoned drafts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.postgres import PostgresRecallHandoffStore
from pneuma_knowledge_service.workers.compile_worker import sweep_recall_handoffs

STATE = {
    "question": "what do seats cost?",
    "as_of": "2026-09-01T00:00:00+00:00",
    "library_ref": "abc123",
    "visitor_class": "business",
    "handles": {"s01": "src-1"},
    "manifest": [{"kind": "window", "ref": "src-1 ¶1-2", "path": ""}],
}


async def _age(pg_store, user, handoff_id: str, *, seconds: int) -> None:
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE recall_handoffs SET created_at = now() - make_interval(secs => %s) "
            "WHERE user_id = %s AND handoff_id = %s",
            (float(seconds), str(user), handoff_id),
        )


async def test_a_handoff_round_trips_and_is_gone_once_it_is_answered(pg_store, user):
    handoffs = PostgresRecallHandoffStore(pg_store)

    assert await handoffs.get(user, "h-1") is None
    assert await handoffs.list_pending(user) == []

    await handoffs.create(user, "h-1", STATE)
    assert await handoffs.get(user, "h-1") == STATE
    assert [h for h, _ in await handoffs.list_pending(user)] == ["h-1"]

    # Another tenant's store answers about its own rows and nothing else (I1).
    other = UserId(f"{user}-other")
    assert await handoffs.get(other, "h-1") is None
    assert await handoffs.list_pending(other) == []

    await handoffs.delete(user, "h-1")
    assert await handoffs.get(user, "h-1") is None
    await handoffs.delete(user, "h-1")  # idempotent: an answered hand-over is not an error


async def test_the_self_heal_sweeps_the_handoff_nobody_came_back_to(pg_store, user):
    handoffs = PostgresRecallHandoffStore(pg_store)
    await handoffs.create(user, "h-fresh", STATE)
    await handoffs.create(user, "h-stale", STATE)
    await _age(pg_store, user, "h-stale", seconds=48 * 60 * 60)

    ctx = SimpleNamespace(
        store=pg_store, settings=SimpleNamespace(recall_handoff_ttl=24 * 60 * 60)
    )
    swept = await sweep_recall_handoffs(ctx, label="test")
    assert swept >= 1

    assert await handoffs.get(user, "h-stale") is None
    # A round still being worked on is left alone.
    assert await handoffs.get(user, "h-fresh") == STATE

    # A TTL of 0 disables the sweep entirely.
    await _age(pg_store, user, "h-fresh", seconds=48 * 60 * 60)
    ctx.settings.recall_handoff_ttl = 0
    assert await sweep_recall_handoffs(ctx, label="test") == 0
    assert await handoffs.get(user, "h-fresh") == STATE

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await handoffs.sweep(cutoff) >= 1


async def test_keyless_reading_and_consultation_round_trip_on_postgres(
    pg_store, user, settings, tmp_path, monkeypatch
):
    """Real startup, L0, handoff, consultation and access ledger; no model construction.

    Search hits and canonical pages are synthetic fixtures, so this test requires only
    Postgres. No provider or vector service participates in a semantic-off reading.
    """
    from pneuma_knowledge_service import wiring
    from pneuma_knowledge_service.access_stats import access_stats, run_recall_projection_job
    from pneuma_knowledge_service.cli import consult, read
    from pneuma_knowledge_service.settings import Settings
    from test_recall_handoff_cli import PAGE, QUESTION, _lib
    from _cli_library import source

    lib = _lib()
    lib.ctx.lexical.aclose = AsyncMock()
    monkeypatch.setattr(wiring, "MeiliLexicalIndex", Mock(return_value=lib.ctx.lexical))
    monkeypatch.setattr(wiring, "GitCanonicalStore", Mock(return_value=lib.canonical))
    monkeypatch.setattr(wiring, "S3MediaStore", Mock(return_value=SimpleNamespace(aclose=AsyncMock())))
    build_chat = Mock(side_effect=AssertionError("reading constructed a chat model"))
    build_embeddings = Mock(side_effect=AssertionError("reading constructed embeddings"))
    build_vectors = Mock(side_effect=AssertionError("reading constructed a vector index"))
    monkeypatch.setattr(wiring.AppContext, "get_chat_model", build_chat)
    monkeypatch.setattr(wiring, "build_embeddings", build_embeddings)
    monkeypatch.setattr(wiring, "QdrantVectorIndex", build_vectors)
    ctx = await wiring.build_context(
        Settings(
            _env_file=None, pg_dsn=settings.pg_dsn, canonical_root=str(tmp_path / "canonical"),
            engine_dir="", components="", semantic_retrieval="off", user_schema_packs=True,
            embedding_model="openrouter:synthetic/embedding", openrouter_api_key="",
            recall_plan_queries=3, recall_evidence_strategy="select",
        ),
        probe_agent=False,
    )
    try:
        assert ctx.embeddings is None and ctx.vectors is None
        material = source("s-01", blocks=["intro", "20 a seat", "renewal terms"])
        material = material.model_copy(update={"raw": material.raw.model_copy(update={"user_id": user})})
        await ctx.store.add(user, material)
        handoffs = PostgresRecallHandoffStore(ctx.store)
        rt = read.ReadRuntime(user_id=user, ctx=ctx, as_json=True, out=io.StringIO(), err=io.StringIO())
        assert await read.cmd_glance(rt) == 0
        assert "glance" in json.loads(rt.out.getvalue())
        rt.out = io.StringIO()
        assert await read.cmd_recall_evidence(rt, QUESTION, handoffs=handoffs) == 0
        evidence = json.loads(rt.out.getvalue())
        hid = evidence["handoff_id"]
        assert evidence["evidence_manifest"]
        assert await handoffs.get(user, hid) is not None
        opening = await ctx.store.get_consultation(user, hid)
        assert opening.state == "unanswered" and opening.miss is None
        assert opening.consultation_id == hid
        other = UserId(f"{user}-other")
        assert await handoffs.get(other, hid) is None
        assert await consult.cmd_consult_answer(
            ctx, other, hid, handoffs=handoffs, text="No cross-user answer", err=io.StringIO()
        ) == consult.EXIT_NOTHING

        handle = next(h for h, sid in evidence["handles"].items() if sid == "s-01")
        assert await consult.cmd_consult_answer(
            ctx, user, hid, handoffs=handoffs,
            text=f"20 a seat. [cite: {handle} ¶1]",
            out=io.StringIO(), err=io.StringIO(),
        ) == 0
        assert await handoffs.get(user, hid) is None
        records = await ctx.store.list_consultations(user)
        assert len(records) == 1
        record = records[0]
        assert record.question == QUESTION and record.visitor_class == "business"
        assert record.consultation_id == hid and record.opening() == opening
        assert record.answer_kind == "answer" and not record.miss
        assert record.library_ref == "c0"
        assert [item.ref for item in record.citations] == ["s-01 ¶1"]
        assert await ctx.store.list_consultations(other) == []
        jobs = await ctx.store.list_jobs(user)
        assert len(jobs) == 2 and all(j["kind"] == "recall_projection" for j in jobs)
        for _ in range(2):
            job = await ctx.store.claim_next(user)
            assert job is not None
            await run_recall_projection_job(ctx, user, job)
        stats = await access_stats(ctx.store, user, [("document", PAGE), ("source", "s-01")])
        assert stats[("document", PAGE)]["hits_7d"] > 0
        assert stats[("source", "s-01")]["hits_7d"] > 0
        assert await ctx.canonical.read_meta(user, "skill/manifest.json") is None
        assert (await ctx.canonical.snapshots(user))[0].ref == "c0"
        build_chat.assert_not_called()
        build_embeddings.assert_not_called()
        build_vectors.assert_not_called()
    finally:
        await ctx.aclose()


async def test_direct_record_round_trips_counts_and_attention_on_postgres(pg_store, user, settings):
    from _cli_library import source
    from test_recall_handoff_cli import PAGE, QUESTION, _lib
    from pneuma_knowledge_service.api.routes.v1 import _consultation_out
    from pneuma_knowledge_service.access_stats import access_stats, run_recall_projection_job
    from pneuma_knowledge_service.cli import build_parser, dispatch, read

    lib = _lib()
    lib.ctx.store = pg_store
    material = source("direct-source", blocks=["Seats cost 20.", "Renewals cost 25."])
    material = material.model_copy(update={
        "raw": material.raw.model_copy(update={"user_id": user}),
        "blocks": [b.model_copy(update={"index": b.index + 1}) for b in material.blocks],
    })
    await pg_store.add(user, material)
    # Direct reading, with no recall or pending hand-over anywhere in this session.
    assert await pg_store.fetch(user, material.raw.source_id, {"blocks": [1, 2]}) == (
        "Seats cost 20.\nRenewals cost 25."
    )
    from pneuma_knowledge_service.cli import consult

    out, err = io.StringIO(), io.StringIO()
    assert await consult.cmd_consult_record(
        lib.ctx, user, question=QUESTION,
        text="20, renewal 25. [cite: direct-source ¶1-2] c:aaa1",
        as_json=True, out=out, err=err,
    ) == 0, err.getvalue()
    result = json.loads(out.getvalue())
    records = await pg_store.list_consultations(user)
    assert len(records) == 1
    record = records[0]
    assert record.lane == "direct" and not record.miss
    assert record.evidence_handed == () and record.citations_direct == 2
    assert all(c.origin == "direct" for c in record.citations)
    assert record.citations[-1].path == PAGE
    assert record.library_ref == "c0" and record.as_of is None
    assert [event.event for event in await pg_store.list_consultation_events(user)] == ["opening", "answer"]
    detail = _consultation_out(record, settings).model_dump()
    assert detail["citations_direct"] == 2
    assert all(c["origin"] == "direct" for c in detail["citations"])
    assert result["consultation_id"] == record.consultation_id
    args = build_parser().parse_args(["--user", str(user), "consultations", "--json"])
    out = io.StringIO()
    assert await dispatch(lib.ctx, args, out=out, err=err) == 0
    listing = json.loads(out.getvalue())["consultations"][0]
    assert listing["evidence_handed"] == 0
    assert listing["citations"] == listing["citations_direct"] == 2
    rt = read.ReadRuntime(user_id=user, ctx=lib.ctx, out=io.StringIO(), err=err)
    assert await read.cmd_consultations(rt) == 0
    assert "evidence handed: 0" in rt.out.getvalue() and "direct: 2" in rt.out.getvalue()
    assert await PostgresRecallHandoffStore(pg_store).list_pending(user) == []
    jobs = await pg_store.list_jobs(user)
    assert len(jobs) == 1 and jobs[0]["kind"] == "recall_projection"
    assert jobs[0]["payload"]["consultation_id"] == record.consultation_id
    job = await pg_store.claim_next(user)
    await run_recall_projection_job(lib.ctx, user, job)
    stats = await access_stats(pg_store, user, [("source", "direct-source"), ("document", PAGE)])
    assert all(stat["hits_7d"] > 0 for stat in stats.values())

    # A real id owned by another user is still not evidence for this tenant.
    other = UserId(f"{user}-other")
    for uid, marker in ((other, "[cite: direct-source ¶1]"), (user, "[cite: direct-source ¶3]")):
        err = io.StringIO()
        assert await consult.cmd_consult_record(
            lib.ctx, uid, question=QUESTION, text=marker, out=io.StringIO(), err=err,
        ) == 4
        assert marker.removeprefix("[cite: ").removesuffix("]") in err.getvalue()
    assert await pg_store.list_consultations(other) == []
    assert await pg_store.list_jobs(other) == []
    assert len(await pg_store.list_consultations(user)) == 1


async def test_old_consultation_origins_default_to_handed_without_rewriting(pg_store, user):
    from pneuma_knowledge_core.domain.consultation import ConsultationRecord, span_ref

    record = ConsultationRecord(
        consultation_id="legacy", user_id=str(user), created_at=datetime.now(timezone.utc),
        lane="fast", visitor_class="audit", question="Synthetic question", as_of=None,
        library_ref="", citations=(span_ref("legacy-source", 1, 2),),
    )
    await pg_store.create_consultation(user, record)
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE consultations SET citations = '[{\"kind\":\"window\",\"ref\":\"legacy-source ¶1-2\"}]'::jsonb "
            "WHERE user_id = %s AND consultation_id = 'legacy'", (str(user),),
        )
    restored = (await pg_store.list_consultations(user))[0]
    assert restored.citations[0].origin == "handed" and restored.citations_direct == 0
    rows, _total, _more = await pg_store.list_consultations_page(user, limit=10)
    assert rows[0]["citations_direct"] == 0 and rows[0]["citation_count"] == 1


async def test_opening_survives_expiry_and_schema_reapplication(pg_store, user):
    from pneuma_knowledge_core.domain.consultation import ConsultationRecord, claim_ref

    opening = ConsultationRecord(
        consultation_id="kept-opening", user_id=str(user), created_at=datetime.now(timezone.utc),
        lane="fast", visitor_class="business", question="Synthetic unanswered question",
        as_of=None, library_ref="synthetic-head", evidence_handed=(claim_ref("aa11", "topics/seats.md"),),
        event="opening", miss=None,
    )
    handoffs = PostgresRecallHandoffStore(pg_store)
    await pg_store.create_consultation(user, opening)
    await handoffs.create(user, opening.consultation_id, STATE)
    await _age(pg_store, user, opening.consultation_id, seconds=48 * 60 * 60)
    await handoffs.sweep(datetime.now(timezone.utc) - timedelta(hours=24))
    assert await handoffs.get(user, opening.consultation_id) is None
    # apply_schema runs at every process start; it must migrate legacy answers only ONCE.
    await pg_store.apply_schema()
    assert await pg_store.get_consultation(user, opening.consultation_id) == opening
    rows, total, _ = await pg_store.list_consultations_page(user, limit=10)
    assert total == 1 and rows[0]["state"] == "unanswered" and rows[0]["miss"] is None
    assert rows[0]["evidence_count"] == 1
    async with pg_store._pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT answer_kind, answer, citations, miss, degraded, token_usage, answered_at "
            "FROM consultations WHERE user_id = %s AND consultation_id = %s",
            (str(user), opening.consultation_id),
        )).fetchone()
    assert row == (None,) * 7


async def test_concurrent_answers_append_only_once_and_replay_each_event(pg_store, user):
    import asyncio
    from dataclasses import replace
    from pneuma_knowledge_core.domain.consultation import ConsultationRecord, claim_ref
    from pneuma_knowledge_service.access_stats import (
        apply_record, rebuild_access_stats, run_recall_projection_job,
    )

    now = datetime.now(timezone.utc)
    ref = claim_ref("aa11", "topics/seats.md")
    opening = ConsultationRecord(
        consultation_id="concurrent", user_id=str(user), created_at=now - timedelta(days=1),
        lane="fast", visitor_class="business", question="Synthetic seat question", as_of=None,
        library_ref="synthetic-head", evidence_handed=(ref,), event="opening", miss=None,
    )
    await pg_store.create_consultation(user, opening)
    assert await apply_record(pg_store, user, opening)
    assert not await apply_record(pg_store, user, opening)
    answer = replace(opening, event="answer", answered_at=now, answer="20 seats", citations=(ref,), miss=False)
    other_answer = replace(answer, answer="21 seats")
    results = await asyncio.gather(
        pg_store.answer_consultation(user, answer), pg_store.answer_consultation(user, other_answer),
        return_exceptions=True,
    )
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert "already answered" in str(next(r for r in results if isinstance(r, ValueError)))
    stored = await pg_store.get_consultation(user, opening.consultation_id)
    assert stored.opening() == opening and stored.answer in {"20 seats", "21 seats"}
    # The unprojected answer is not borrowed by a rebuild of its already-applied opening.
    assert await rebuild_access_stats(pg_store, user) == 1
    assert await apply_record(pg_store, user, replace(stored, event="answer"))
    assert not await apply_record(pg_store, user, replace(stored, event="answer"))
    assert await rebuild_access_stats(pg_store, user) == 2
    rows = await pg_store.access_rows_for(user, [("document", "topics/seats.md")])
    assert sum(row["hits"] for row in rows) == 2
    assert {row["day"] for row in rows} == {opening.created_at.date(), now.date()}
    events = await pg_store.list_consultation_events(user, limit=1)
    assert events == [opening]
    events = await pg_store.list_consultation_events(user, after=(opening.created_at, opening.consultation_id, 0))
    assert [e.event for e in events] == ["answer"]
    assert await pg_store.get_consultation(UserId(f"{user}-other"), opening.consultation_id) is None
    assert await pg_store.list_consultation_events(UserId(f"{user}-other")) == []
    # Pending original queue deliveries are harmless after replay: both stamps survive.
    jobs = await pg_store.list_jobs(user)
    assert len(jobs) == 2
    while job := await pg_store.claim_next(user):
        await run_recall_projection_job(SimpleNamespace(store=pg_store), user, job)
    assert sum(row["hits"] for row in await pg_store.access_rows_for(user, [("document", "topics/seats.md")])) == 2
    assert await pg_store.get_consultation(user, opening.consultation_id) == stored


async def test_attention_counts_events_by_time_and_excludes_audit(pg_store, user):
    from dataclasses import replace
    from pneuma_knowledge_core.domain.consultation import ConsultationRecord, span_ref

    now = datetime.now(timezone.utc)
    opening = ConsultationRecord(
        consultation_id="activity", user_id=str(user), created_at=now, lane="fast",
        visitor_class="business", question="Synthetic question", as_of=None, library_ref="",
        evidence_handed=(span_ref("synthetic-source", 1, 2),), event="opening", miss=None,
    )
    await pg_store.create_consultation(user, opening)
    await pg_store.create_consultation(user, replace(opening, consultation_id="audit", visitor_class="audit"))
    kwargs = dict(since=now - timedelta(seconds=1), until=now + timedelta(seconds=1))
    counts = await pg_store.consultation_activity(user, **kwargs)
    assert counts == dict(openings=1, evidence_handed=1, answers=0, citations=0, misses=0, unanswered=1)
    await pg_store.answer_consultation(user, replace(
        opening, event="answer", answered_at=now, answer_kind="no_record", miss=True,
    ))
    assert await pg_store.consultation_activity(user, **kwargs) == dict(
        openings=1, evidence_handed=1, answers=1, citations=0, misses=1, unanswered=0,
    )
