"""A query's source-time window is enforced independently of relevance and ranked anchors."""

import asyncio
from dataclasses import replace
from datetime import datetime

import pytest

from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScores, SourceClockDecision
from pneuma_knowledge_core.recall.evidence_context import EvidenceTime, enrich_evidence
from pneuma_knowledge_core.recall import fast
from pneuma_knowledge_core.recall.progressive import first_finding, refine
from test_evidence_context import USER, WHEN, Content, claim, source, window


def decision(period="last_two_days"):
    return SourceClockDecision(True, 0.98, 17, "synthetic", period=period, period_confidence=0.99)


def scope(period="last_two_days", *, as_of=WHEN, zone="Asia/Shanghai", question="these two days"):
    from pneuma_knowledge_core.recall.temporal import resolve_source_time_scope
    return resolve_source_time_scope(decision(period), question=question, as_of=as_of, zone=zone)


def test_period_arithmetic_uses_the_subject_calendar_and_dst():
    resolved = scope()
    assert resolved.start_day == "2026-09-20" and resolved.end_day == "2026-09-21"
    assert resolved.start.isoformat() == "2026-09-19T16:00:00+00:00"
    assert resolved.end.isoformat() == "2026-09-21T16:00:00+00:00"
    dst = scope("today", as_of=datetime.fromisoformat("2026-11-01T14:00:00+00:00"), zone="America/New_York")
    assert (dst.end - dst.start).total_seconds() == 25 * 3600


def test_event_dates_and_unresolved_recency_never_invent_a_source_window():
    from pneuma_knowledge_core.recall.temporal import resolve_source_time_scope
    assert resolve_source_time_scope(SourceClockDecision(False, 0.1), question="release date?", as_of=WHEN) is None
    assert scope("unresolved").status == "unresolved"
    assert scope("explicit_dates", question="records from 2026-09-20 to 2026-09-21").start_day == "2026-09-20"
    assert scope("explicit_dates", question="records from February 30").status == "unresolved"
    assert resolve_source_time_scope(SourceClockDecision(policy_id="unavailable"), question="q", as_of=WHEN).status == "unavailable"


def test_unknown_source_day_and_partial_clocks_do_not_prove_a_whole_claim_is_in_range():
    from pneuma_knowledge_core.recall.temporal import temporal_status
    item = claim("a001", "synthetic")
    only_day = EvidenceTime(SourceId("synthetic"), 0, 0, occurred_on="2026-09-21")
    assert temporal_status(replace(item, source_times=(only_day,)), scope()) == "unknown"
    dated = replace(only_day, first="2026-09-20T17:00:00Z", last="2026-09-20T17:00:00Z", timed_blocks=1)
    assert temporal_status(replace(item, source_times=(dated,)), scope()) == "within"
    partial = replace(dated, block_end=1)
    assert temporal_status(replace(item, source_times=(partial,)), scope()) == "unknown"


async def test_multiday_windows_are_split_at_real_block_clocks_without_rewriting_l0():
    from pneuma_knowledge_core.recall.temporal import temporal_windows
    raw = source("mixed", "2026-09-17", ["old", "today A", "undated", "today B"], clocks=[
        "2026-09-17T01:00:00Z", "2026-09-20T17:00:00Z", None, "2026-09-21T00:00:00Z",
    ])
    rows, counts = await temporal_windows([window("mixed", 0, 3, "old\ntoday A\nundated\ntoday B")],
                                         scope(), user_id=USER, content=Content(raw))
    assert [(w.block_start, w.block_end, w.text) for w in rows] == [(1, 1, "today A"), (3, 3, "today B")]
    assert all(any(o.bounded for o in w.retrieval_origins) for w in rows)
    assert [b.text for b in raw.blocks] == ["old", "today A", "undated", "today B"]


async def test_temporal_reread_rejects_a_different_tenant_and_duplicate_blocks():
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_core.recall.temporal import temporal_windows

    raw = source("synthetic", "2026-09-21", ["A", "B"], clocks=[
        "2026-09-21T00:00:00Z", "2026-09-21T00:01:00Z",
    ])
    other = raw.model_copy(update={"raw": raw.raw.model_copy(update={"user_id": UserId("other")})})
    hit = window("synthetic", 0, 1, "A\nB")
    with pytest.raises(ValueError, match="tenant/source"):
        await temporal_windows([hit], scope(), user_id=USER, content=Content(other))
    duplicate = raw.model_copy(update={"blocks": [raw.blocks[0], raw.blocks[0]]})
    with pytest.raises(ValueError, match="duplicate block"):
        await temporal_windows([hit], scope(), user_id=USER, content=Content(duplicate))


class Scorer:
    def __init__(self, *, fail=False):
        self.seen = []
        self.fail = fail

    async def score(self, question, candidates):
        self.seen.extend(candidates)
        if self.fail:
            raise RuntimeError("synthetic scoring failure")
        return EvidenceScores(tuple(0.0 for _ in candidates))


async def run_lane(monkeypatch, *, with_new=False, fail=False, evidence_only=True):
    old = source("old", "2026-09-17", ["Old project work."], clocks=["2026-09-17T01:00:00Z"])
    new = source("new", "2026-09-20", ["New project work."], clocks=["2026-09-20T17:00:00Z"])
    claims = [claim("a001", "old", text="Old project work.")]
    windows = [window("old", 0, 0, "Old project work.")]
    if with_new:
        claims.append(claim("a002", "new", text="New project work."))
        windows.append(window("new", 0, 0, "New project work."))

    async def claim_lookup(*args, **kwargs):
        return claims

    async def window_lookup(*args, **kwargs):
        return windows

    monkeypatch.setattr(fast, "retrieve_claims", claim_lookup)
    monkeypatch.setattr(fast, "retrieve_windows", window_lookup)
    scorer = Scorer(fail=fail)
    result = await fast.fast_recall(USER, "What did I work on these two days?", as_of=WHEN,
        claim_lexical=object(), claim_vectors=None, lexical=object(), vectors=None, embeddings=None,
        content=Content(old, new), model=None, documents=(), fast_paths=(),
        evidence_strategy="select", evidence_scorer=scorer, source_clock_decision=decision(),
        evidence_only=evidence_only, zone="Asia/Shanghai")
    return result, scorer


@pytest.mark.parametrize("fail", [False, True])
async def test_ranked_anchors_and_failure_fallback_cannot_reintroduce_old_evidence(monkeypatch, fail):
    evidence, scorer = await run_lane(monkeypatch, with_new=True, fail=fail)
    assert "Old project work" not in evidence.content
    assert "New project work" in evidence.content
    assert all("Old project work" not in text for text in scorer.seen)
    assert not evidence.temporal_notice


async def test_empty_temporal_evidence_blocks_both_voice_phases_without_asking_a_model(monkeypatch):
    evidence, _ = await run_lane(monkeypatch)
    assert not evidence.used_claims and not evidence.used_windows
    assert evidence.temporal_notice
    assert (await first_finding(object(), evidence.question, evidence)).text == ""
    result = await refine(object(), evidence)
    assert result.status == "unresolved" and not result.facts
    assert "2026-09-20" in result.result_text and "2026-09-21" in result.result_text


async def test_text_answer_also_refuses_to_summarize_out_of_period_material(monkeypatch):
    result, _ = await run_lane(monkeypatch, evidence_only=False)
    assert result.answer_kind == "no_record"
    assert "Old project work" not in result.answer
    assert "2026-09-20" in result.answer


async def test_unavailable_validation_returns_a_failure_result_without_requesting_dates():
    from pneuma_knowledge_core.recall.temporal import resolve_source_time_scope, temporal_notice

    unavailable = resolve_source_time_scope(SourceClockDecision(policy_id="unavailable"),
        question="What is Heron?", as_of=WHEN)
    notice = temporal_notice(unavailable, has_evidence=True)
    evidence = fast.FastEvidence(question="What is Heron?", as_of=WHEN, system="", content="",
        handles={}, source_time_scope=unavailable, temporal_notice=notice)
    result = await refine(object(), evidence)
    assert result.status == "unresolved" and result.facts == ()
    assert "unavailable" in result.result_text
    assert "specify" not in result.result_text and "Please" not in result.result_text


async def test_clock_policy_and_retrieval_overlap_and_the_policy_runs_only_once(monkeypatch):
    clock_started, retrieval_started = asyncio.Event(), asyncio.Event()
    calls = []

    class ConcurrentScorer(Scorer):
        async def source_clock_policy(self, question):
            calls.append(question)
            clock_started.set()
            await retrieval_started.wait()
            return SourceClockDecision(False, 0.05, 11, "synthetic")

    async def claims(*args, **kwargs):
        retrieval_started.set()
        await clock_started.wait()
        return []

    monkeypatch.setattr(fast, "retrieve_claims", claims)
    result = await asyncio.wait_for(fast.fast_recall(USER, "What is Heron?", as_of=WHEN,
        claim_lexical=object(), claim_vectors=None, lexical=None, vectors=None, embeddings=None,
        model=None, fast_paths=(), evidence_only=True, evidence_strategy="select",
        evidence_scorer=ConcurrentScorer()), 0.5)
    assert calls == ["What is Heron?"]
    assert result.scorer_input_tokens == 11


async def test_cancellation_joins_the_owned_policy_and_retrieval_tasks(monkeypatch):
    started, cancelled = set(), set()
    both_started = asyncio.Event()

    async def wait(name):
        started.add(name)
        if len(started) == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(name)

    class SlowScorer(Scorer):
        async def source_clock_policy(self, question):
            await wait("policy")

    async def claims(*args, **kwargs):
        await wait("retrieval")

    monkeypatch.setattr(fast, "retrieve_claims", claims)
    task = asyncio.create_task(fast.fast_recall(USER, "q", as_of=WHEN, claim_lexical=object(),
        claim_vectors=None, lexical=None, vectors=None, embeddings=None, model=None, fast_paths=(),
        evidence_only=True, evidence_scorer=SlowScorer()))
    await asyncio.wait_for(both_started.wait(), 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == started
