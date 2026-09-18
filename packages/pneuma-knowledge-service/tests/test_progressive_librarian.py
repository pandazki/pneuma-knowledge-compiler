"""The two lookups share scope, overlap, and clean up together; no middleware needed."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim
from pneuma_knowledge_core.recall.progressive import FirstChoice, RefinementDecision
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
                parsed = FirstChoice(index=0) if schema is FirstChoice else RefinementDecision(
                    relation="extend", answer="The flood inspection is tomorrow.",  citations=["[cite: s01 ¶0-0]"])
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
    assert speech and answer.payload["progressive"]["relation"] == "extend"
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

    async def retrieve(user, question, **kw):
        if kw["model"] is None:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append("quick")
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
