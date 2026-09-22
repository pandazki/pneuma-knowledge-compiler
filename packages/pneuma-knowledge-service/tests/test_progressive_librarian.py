"""The two lookups share scope, overlap, and clean up together; no middleware needed."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim
from pneuma_knowledge_core.recall.progressive import FirstDecision, KnowledgeDecision, KnowledgeFact
from pneuma_knowledge_service.call import librarian as module
from pneuma_knowledge_service.call.librarian import LibraryLibrarian


def evidence():
    return FastEvidence(question="What blocks the ferry ramp?", as_of=datetime(2026, 9, 18, tzinfo=timezone.utc),
        system="Use records only.", content="The flood inspection blocks the ramp. [cite: s01 ¶0-0]",
        handles={"s01": "ferry-source"}, token_usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        used_claims=(RetrievedClaim(AnchorId("c:1234"), "projects/ferry.md", (),
            "The ramp needs a flood inspection.", (Citation(source_id=SourceId("ferry-source"), block_start=0, block_end=0),)),))


class Model:
    def with_structured_output(self, schema, **kwargs):
        class Bound:
            async def ainvoke(self, messages, config=None):
                parsed = FirstDecision(disposition="ready", index=0, subject="unambiguous",
                    support="direct", record_kind="subject_fact", quote=(
                        "Lyrra Framework builds applications." if "Lyrra" in str(messages)
                        else "The ramp needs a flood inspection.")) if schema is FirstDecision else KnowledgeDecision(
                    status="answered", facts=[KnowledgeFact(text="The flood inspection is tomorrow.", citations=["[cite: s01 ¶0-0]"])], scope="Ramp record.", limitations=[])
                return {"parsed": parsed, "raw": AIMessage(content="", usage_metadata={
                    "input_tokens": 9, "output_tokens": 2, "total_tokens": 11})}
        return Bound()


@pytest.fixture
def librarian(monkeypatch):
    from pneuma_knowledge_service.api.routes import v1

    async def plane(*args):
        return SimpleNamespace(retrieval_user=UserId("scoped-owner"))

    async def kwargs(*args, **kw):
        return {"as_of": kw["as_of"], "documents": (), "archive_active": True,
                "include_archived": False, "callbacks": [], "trace_metadata": {"user": kw["user_id"]}}

    async def inputs(*args):
        return {}

    def out(answer, **kwargs):
        return SimpleNamespace(model_dump=lambda **kw: {"answer": answer.answer,
            "token_usage": answer.token_usage, "stages": [s.name for s in answer.stages]})

    monkeypatch.setattr(v1, "_resolve_plane", plane)
    monkeypatch.setattr(v1, "_fast_recall_kwargs", kwargs)
    monkeypatch.setattr(v1, "_fast_answer_out", out)
    monkeypatch.setattr(LibraryLibrarian, "_inputs", inputs)
    return LibraryLibrarian(SimpleNamespace(get_chat_model=lambda role: Model(), settings=SimpleNamespace()), "owner")


async def test_first_result_reaches_the_caller_while_broader_retrieval_is_still_running(librarian, monkeypatch):
    broad_started, release_broad, first_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen, speech, first = [], [], []

    async def retrieve(user, question, **kw):
        seen.append((user, kw))
        if kw["model"] is not None:
            broad_started.set()
            await release_broad.wait()
        else:
            await broad_started.wait()
        return evidence()

    def preliminary(text):
        first.append(text)
        first_ready.set()

    monkeypatch.setattr(module, "fast_recall", retrieve)
    task = asyncio.create_task(librarian.answer("What blocks the ferry ramp?", on_preliminary=preliminary,
        on_token=speech.append, on_retrieved=lambda: None))
    await asyncio.wait_for(first_ready.wait(), 1)
    assert first and not speech and not task.done()
    release_broad.set()
    answer = await task
    assert speech and answer.payload["lookup_result"]["status"] == "answered"
    assert answer.payload["token_usage"]["total_tokens"] == 25  # first pick + refinement + broad selection
    quick, broad = [kw for _, kw in seen]
    assert all(user == UserId("scoped-owner") for user, _ in seen)
    assert quick["as_of"] == broad["as_of"]
    assert quick["documents"] is broad["documents"]
    assert quick["archive_active"] is broad["archive_active"] is True
    assert quick["include_archived"] is broad["include_archived"] is False
    assert quick["fast_paths"] == () and quick["embeddings"] is None
    assert quick["cap"] < broad["cap"]


async def test_a_first_lookup_timeout_never_cancels_the_broader_answer(librarian, monkeypatch):
    monkeypatch.setattr(module, "FIRST_LOOK_SECONDS", 0.01)
    cancelled = []
    quick_cancelled = asyncio.Event()

    async def retrieve(user, question, **kw):
        if kw["model"] is None:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append("quick")
                quick_cancelled.set()
        await quick_cancelled.wait()
        return evidence()

    monkeypatch.setattr(module, "fast_recall", retrieve)
    first, speech = [], []
    answer = await librarian.answer("question", on_preliminary=first.append, on_token=speech.append, on_retrieved=lambda: None)
    assert first == [] and speech == ["The flood inspection is tomorrow."]
    assert cancelled == ["quick"]
    assert answer.payload["progressive"]["first_degraded"] == "timeout"


async def test_cancellation_joins_both_lookups(librarian, monkeypatch):
    started, cancelled = [], []
    both = asyncio.Event()

    async def retrieve(user, question, **kw):
        role = "quick" if kw["model"] is None else "broad"
        started.append(role)
        if len(started) == 2:
            both.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(role)

    monkeypatch.setattr(module, "fast_recall", retrieve)
    task = asyncio.create_task(librarian.answer("question", on_preliminary=lambda text: None,
        on_token=lambda text: None, on_retrieved=lambda: None))
    await asyncio.wait_for(both.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(cancelled) == ["broad", "quick"]


async def test_exact_subject_overview_bypasses_lexical_first_look(librarian, monkeypatch):
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_service.api.routes import v1
    doc = CanonicalDocument(doc_id='synthetic', path='projects/lyrra/overview.md',
        frontmatter={'title': 'Lyrra Framework', 'slug': 'lyrra-framework'},
        body='# Lyrra Framework\n\n<!-- overview -->\n<!-- overview:definition -->\n\n'
             'Lyrra Framework builds applications. [cite: synthetic-source ¶0] <!-- c:aa11 -->\n\n<!-- /overview -->')
    async def kwargs(*args, **kw):
        return {'as_of': kw['as_of'], 'documents': [doc]}
    first_ready = asyncio.Event()
    async def retrieve(user, question, **kw):
        assert kw['model'] is not None, 'exact canonical identity must not use lexical first look'
        await first_ready.wait()
        return evidence()
    monkeypatch.setattr(v1, '_fast_recall_kwargs', kwargs)
    monkeypatch.setattr(module, 'fast_recall', retrieve)
    first = []
    def preliminary(text):
        first.append(text)
        first_ready.set()
    answer = await librarian.answer('介绍 Lyrra Framework', on_preliminary=preliminary,
        on_token=lambda text: None, on_retrieved=lambda: None)
    assert first and 'builds applications' in first[0]
    assert answer.payload['progressive']['locator'] == 'projects/lyrra/overview.md#aa11'


async def test_early_canonical_lookup_shares_the_policy_and_withholds_undated_facts(librarian, monkeypatch):
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.ports.evidence_scorer import SourceClockDecision
    from pneuma_knowledge_core.recall.temporal import resolve_source_time_scope, temporal_notice
    from pneuma_knowledge_service.api.routes import v1

    doc = CanonicalDocument(doc_id="synthetic", path="projects/lyrra.md",
        frontmatter={"title": "Lyrra Framework"},
        body="<!-- overview -->\n<!-- overview:definition -->\n"
             "Lyrra Framework builds applications. [cite: synthetic-source ¶0] <!-- c:aa11 -->\n"
             "<!-- /overview -->")
    calls, received, first, facts = [], [], [], []
    release_broad = asyncio.Event()

    class Policy:
        async def source_clock_policy(self, question):
            calls.append(question)
            return SourceClockDecision(True, 0.98, 13, "synthetic", "today", 0.95)

    async def kwargs(*args, **kw):
        return {"as_of": kw["as_of"], "documents": [doc], "evidence_scorer": Policy()}

    async def retrieve(user, question, **kw):
        assert kw["model"] is not None
        clock = await asyncio.shield(kw["source_clock_decision"])
        received.append(clock)
        await release_broad.wait()
        scope = resolve_source_time_scope(clock, question=question, as_of=kw["as_of"])
        return FastEvidence(question=question, as_of=kw["as_of"], system="", content="", handles={},
            source_time_scope=scope, temporal_notice=temporal_notice(scope, has_evidence=False),
            scorer_input_tokens=clock.input_tokens)

    monkeypatch.setattr(v1, "_fast_recall_kwargs", kwargs)
    monkeypatch.setattr(module, "fast_recall", retrieve)
    answer = await asyncio.wait_for(librarian.answer("今天关于 Lyrra Framework 的记录是什么？",
        on_preliminary=first.append, on_token=facts.append, on_retrieved=lambda: None,
        on_progress=lambda text: release_broad.set()), 1)
    assert len(calls) == len(received) == 1
    assert first == [] and len(facts) == 1
    assert "builds applications" not in facts[0]
    assert answer.payload["lookup_result"]["status"] == "unresolved"
    assert answer.payload["lookup_result"]["facts"] == []


async def test_librarian_cancellation_joins_the_shared_policy(librarian, monkeypatch):
    from pneuma_knowledge_service.api.routes import v1

    started, cancelled = asyncio.Event(), asyncio.Event()

    class Policy:
        async def source_clock_policy(self, question):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def kwargs(*args, **kw):
        return {"as_of": kw["as_of"], "documents": (), "evidence_scorer": Policy()}

    async def retrieve(user, question, **kw):
        await asyncio.shield(kw["source_clock_decision"])
        raise AssertionError("cancelled lookup must not continue")

    monkeypatch.setattr(v1, "_fast_recall_kwargs", kwargs)
    monkeypatch.setattr(module, "fast_recall", retrieve)
    task = asyncio.create_task(librarian.answer("question", on_preliminary=lambda text: None,
        on_token=lambda text: None, on_retrieved=lambda: None))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


async def test_broad_evidence_does_not_wait_for_a_slow_first_finding(librarian, monkeypatch):
    quick_started, quick_cancelled = asyncio.Event(), asyncio.Event()
    first, speech = [], []

    async def retrieve(user, question, **kw):
        if kw["model"] is None:
            quick_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                quick_cancelled.set()
        await quick_started.wait()
        return evidence()

    monkeypatch.setattr(module, "fast_recall", retrieve)
    answer = await asyncio.wait_for(librarian.answer(
        "question", on_preliminary=first.append, on_token=speech.append,
        on_retrieved=lambda: None), 1)
    assert quick_cancelled.is_set()
    assert first == [] and speech == ["The flood inspection is tomorrow."]
    assert answer.payload["progressive"]["first_skipped"] == "broader_ready"
    assert answer.payload["progressive"]["first_degraded"] is None


async def test_a_failed_broad_lookup_cancels_and_joins_the_first(librarian, monkeypatch):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def retrieve(user, question, **kw):
        if kw["model"] is None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        await started.wait()
        raise RuntimeError("synthetic retrieval failure")

    monkeypatch.setattr(module, "fast_recall", retrieve)
    with pytest.raises(RuntimeError, match="synthetic retrieval failure"):
        await asyncio.wait_for(librarian.answer("question", on_preliminary=lambda _: None,
            on_token=lambda _: None, on_retrieved=lambda: None), 1)
    assert cancelled.is_set()


async def test_only_broad_retrieval_inherits_the_configured_scorer(librarian, monkeypatch):
    from pneuma_knowledge_service.api.routes import v1
    from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScores

    calls, seen = [], []

    class Scorer:
        async def score(self, question, candidates):
            calls.append(question)
            return EvidenceScores(scores=(1.0,))

    scorer = Scorer()
    original = v1._fast_recall_kwargs

    async def kwargs(*args, **kw):
        return {**await original(*args, **kw), "evidence_scorer": scorer,
                "select_score_floor": 0.65, "claim_candidate_cap": 80}

    async def retrieve(user, question, **kw):
        seen.append(kw)
        if kw["evidence_scorer"] is not None:
            await kw["evidence_scorer"].score(question, ["synthetic evidence"])
        return evidence()

    monkeypatch.setattr(v1, "_fast_recall_kwargs", kwargs)
    monkeypatch.setattr(module, "fast_recall", retrieve)
    await librarian.answer("question", on_preliminary=lambda _: None,
        on_token=lambda _: None, on_retrieved=lambda: None)
    quick, broad = seen
    assert calls == ["question"]
    assert quick["evidence_scorer"] is None and broad["evidence_scorer"] is scorer
    assert broad["claim_candidate_cap"] == 80 and broad["select_score_floor"] == 0.65
    assert broad["evidence_selection_timeout"] == 5.0


async def test_uncertain_first_result_emits_only_task_state_while_broad_lookup_continues(librarian, monkeypatch):
    from pneuma_knowledge_core.recall.progressive import FirstFinding
    broad_gate, progress_ready = asyncio.Event(), asyncio.Event()
    first, progress, final = [], [], []

    async def retrieve(user, question, **kw):
        if kw["model"] is not None:
            await broad_gate.wait()
        return evidence()

    async def uncertain(*args, **kwargs):
        return FirstFinding(disposition="needs_review", reason="admission_failed")

    def report(text):
        progress.append(text)
        progress_ready.set()

    monkeypatch.setattr(module, "fast_recall", retrieve)
    monkeypatch.setattr(module, "first_finding", uncertain)
    task = asyncio.create_task(librarian.answer("Which subject?", on_preliminary=first.append,
        on_progress=report, on_token=final.append, on_retrieved=lambda: None))
    await asyncio.wait_for(progress_ready.wait(), 1)
    assert not first and not final and not task.done()
    assert progress == [module.prompt("call.progressive.checking")]
    assert "flood" not in progress[0]
    broad_gate.set()
    result = await task
    assert final and result.payload["progressive"]["first_disposition"] == "needs_review"
