"""Spec: docs/guides/recall-strategies.md.

The quality path is an opt-in composition layer over existing evidence. These tests pin
its two mechanical boundaries before implementation: model output can only select real
candidates, and structured answers can only cite exact spans shown to the model.
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.recall.assembly import Passage
from pneuma_knowledge_core.recall.fast import (
    EpisodeSummary,
    EvidenceSelection,
    SelectedEvidence,
    RetrievedClaim,
    StructuredRecallAnswer,
    answer_with_structured,
    expand_claim_provenance,
    expand_episode_provenance,
    fast_recall,
    select_evidence,
)
from pneuma_knowledge_core.recall.rag import RecallHit


class StructuredModel(BaseChatModel):
    """One structured response with observable messages and provider usage."""

    parsed: object
    error: Exception | None = None
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "quality-selection-test"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self

        class Bound:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.seen.append(list(messages))
                if outer.error is not None:
                    raise outer.error
                return {
                    "raw": AIMessage(
                        content="",
                        usage_metadata={
                            "input_tokens": 11,
                            "output_tokens": 3,
                            "total_tokens": 14,
                        },
                    ),
                    "parsed": outer.parsed,
                    "parsing_error": None,
                }

        return Bound()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="unused"))])


def _claims(count: int) -> list[RetrievedClaim]:
    return [
        RetrievedClaim(
            anchor=AnchorId(f"a{index:03d}"),
            document_path=f"people/p{index}.md",
            section_path=("facts",),
            text=f"claim {index}",
            citations=(
                Citation(
                    source_id=SourceId(f"source-{index}"),
                    block_start=index,
                    block_end=index,
                ),
            ),
            score=1 / (index + 1),
        )
        for index in range(count)
    ]


def _summaries(count: int) -> list[EpisodeSummary]:
    return [
        EpisodeSummary(
            source_id=SourceId(f"episode-{index}"),
            block_start=index,
            block_end=index + 1,
            text=f"episode summary {index}",
            score=1 / (index + 1),
            source_title=f"Session {index}",
            source_occurred_on="2026-08-14",
        )
        for index in range(count)
    ]


def _windows(count: int) -> list[RecallHit]:
    return [
        RecallHit(
            source_id=SourceId(f"window-{index}"),
            block_start=index,
            block_end=index,
            text=f"verbatim window {index}",
            paths=("lexical",),
            score=1 / (index + 1),
        )
        for index in range(count)
    ]


async def test_cross_face_selection_validates_indexes_unions_safety_head_and_caps():
    model = StructuredModel(
        parsed=EvidenceSelection(
            claims=[11, 11, -1, 999],
            episode_summaries=[5, 999],
            raw_windows=[5, -1],
            document_paths=["people/p11.md", "invented.md", "people/p11.md"],
        ),
        seen=[],
    )

    selected, usage, degraded = await select_evidence(
        model,
        "Which facts jointly answer this?",
        claims=_claims(12),
        episode_summaries=_summaries(6),
        windows=_windows(6),
        glance="# Knowledge base\n- `people/p11.md`",
        known_paths=("people/p11.md",),
        claim_cap=10,
        episode_summary_cap=5,
        window_cap=5,
        timeout=None,
    )

    assert degraded is None
    assert usage["total_tokens"] == 14
    # Model choices lead; deterministic ranked anchors preserve the strongest evidence.
    assert selected.claim_indexes == (11, 0, 1, 2, 3, 4, 5, 6, 7)
    assert selected.episode_indexes == (5, 0, 1, 2, 3)
    assert selected.model_claim_count == 1
    assert selected.model_episode_count == 1
    assert selected.model_window_count == 1
    assert selected.window_indexes == (5, 0, 1, 2, 3)
    assert selected.document_paths == ("people/p11.md",)
    human = model.seen[0][1].content
    assert "C11:" in human and "E5:" in human and "W5:" in human
    assert human.rstrip().endswith("Which facts jointly answer this?")


async def test_cross_face_selection_failure_is_explicit_and_has_no_fake_selection():
    model = StructuredModel(
        parsed=EvidenceSelection(), error=RuntimeError("provider down"), seen=[]
    )
    selected, usage, degraded = await select_evidence(
        model,
        "q",
        claims=_claims(2),
        episode_summaries=_summaries(2),
        windows=_windows(2),
        timeout=None,
    )
    assert selected is None
    assert usage["total_tokens"] == 0
    assert degraded == "error"


async def test_structured_answer_admits_only_exact_presented_citations():
    claim = _claims(1)[0]
    window = Passage(
        source_id=SourceId("raw-source"),
        block_start=3,
        block_end=5,
        text="the exact source text",
        paths=("vector",),
        score=1.0,
    )
    model = StructuredModel(
        parsed=StructuredRecallAnswer(
            answer_kind="time",
            answer="August 14, 2026.",
            citations=[
                "[cite: s01 ¶0-0]",
                "[cite: s02 ¶3-5]",
                "[cite: s02 ¶3-99]",  # widened beyond the shown evidence
                "[cite: s99 ¶1-1]",  # unknown handle
            ],
        ),
        seen=[],
    )

    (
        answer_text,
        answer,
        usage,
        handles,
        kind,
        degraded,
        deliberation,
    ) = await answer_with_structured(
        model,
        "When was it?",
        [claim],
        as_of=datetime(2026, 8, 14),
        windows=[window],
        timeout=None,
        answer_style="concise",
    )

    assert degraded == "invalid_citations"
    assert deliberation is None  # no deliberation was asked for, so the field stays absent
    assert kind == "time"
    assert usage["total_tokens"] == 14
    assert answer_text == "August 14, 2026."
    assert answer == "August 14, 2026. [cite: s01 ¶0-0] [cite: s02 ¶3-5]"
    assert handles == {"s01": "source-0", "s02": "raw-source"}
    assert "[cite: s01 ¶0-0]" in model.seen[0][1].content
    assert model.seen[0][0].content != ""


async def test_selected_provenance_follows_claims_and_episodes_to_authoritative_l0():
    from pneuma_knowledge_core.domain.source import NormalizedSource

    def source(source_id: str, texts: list[str]) -> NormalizedSource:
        return NormalizedSource.model_validate(
            {
                "raw": {
                    "source_id": source_id,
                    "user_id": "u-quality",
                    "kind": "im",
                    "origin": "mock",
                    "title": f"Title {source_id}",
                    "mime": "application/json",
                    "checksum": f"checksum-{source_id}",
                    "created_at": "2026-08-14T00:00:00Z",
                    "meta": {"occurred_on": "2026-08-13"},
                },
                "blocks": [
                    {"index": index, "text": text, "section_path": ["session"]}
                    for index, text in enumerate(texts)
                ],
                "structure": {"sections": []},
            }
        )

    sources = {
        "source-0": source("source-0", ["claim evidence"]),
        "episode-0": source("episode-0", ["episode line one", "episode line two"]),
    }

    class Content:
        async def get(self, user_id, source_id):  # noqa: ANN001
            return sources[str(source_id)]

    existing = [
        Passage(
            source_id=SourceId("source-0"),
            block_start=0,
            block_end=0,
            text="claim evidence",
            paths=("lexical",),
            score=1,
        )
    ]
    claims = await expand_claim_provenance(
        UserId("u-quality"),
        _claims(1),
        content=Content(),
        existing=existing,
        claim_cap=1,
        passage_cap=12,
    )
    episodes = await expand_episode_provenance(
        UserId("u-quality"),
        _summaries(1),
        content=Content(),
        existing=existing,
        episode_cap=4,
    )

    assert claims == []  # independently retrieved verbatim evidence is not duplicated
    assert len(episodes) == 1
    assert episodes[0].text == "episode line one\nepisode line two"
    assert episodes[0].paths == ("episode-provenance",)
    assert episodes[0].source_title == "Title episode-0"


async def test_fast_select_and_structured_answer_are_one_observable_quality_path(monkeypatch):
    from pneuma_knowledge_core.recall import fast as fast_module

    claims = _claims(3)
    summaries = _summaries(3)
    windows = _windows(3)
    seen = {}

    async def retrieve_claims(*args, **kwargs):  # noqa: ANN002, ANN003
        return claims

    async def retrieve_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        return windows

    async def build_summaries(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["summary_cap"] = kwargs["cap"]
        return summaries

    async def choose(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["selector_claims"] = list(kwargs["claims"])
        seen["selector_summaries"] = list(kwargs["episode_summaries"])
        seen["selector_windows"] = list(kwargs["windows"])
        return SelectedEvidence(
            (2,),
            (2,),
            (2,),
            (),
            model_claim_count=1,
            model_episode_count=1,
            model_window_count=1,
        ), {
            "input_tokens": 5,
            "output_tokens": 2,
            "total_tokens": 7,
            "cache_read": 0,
            "cache_creation": 0,
        }, None

    async def structured(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["answer_claims"] = list(args[2])
        seen["answer_summaries"] = list(kwargs["episode_summaries"])
        seen["answer_windows"] = list(kwargs["windows"])
        return "the answer", "the answer [cite: s01 ¶0-0]", {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
            "cache_read": 0,
            "cache_creation": 0,
        }, {}, "fact", None, None

    monkeypatch.setattr(fast_module, "retrieve_claims", retrieve_claims)
    monkeypatch.setattr(fast_module, "retrieve_windows", retrieve_windows)
    monkeypatch.setattr(fast_module, "build_episode_summaries", build_summaries)
    monkeypatch.setattr(fast_module, "select_evidence", choose)
    monkeypatch.setattr(fast_module, "answer_with_structured", structured)

    model = StructuredModel(parsed=EvidenceSelection(), seen=[])
    result = await fast_recall(
        UserId("u-quality"),
        "join the evidence",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=model,
        evidence_strategy="select",
        answer_format="structured",
        cap=1,
        episode_summary_cap=1,
        window_cap=1,
        window_candidate_cap=3,
    )

    # Selection sees candidate breadth, while the answer sees only selected coordinates.
    assert seen["summary_cap"] == 3
    assert len(seen["selector_claims"]) == 3
    assert len(seen["selector_summaries"]) == 3
    assert len(seen["selector_windows"]) == 3
    assert seen["answer_claims"] == [claims[2]]
    assert seen["answer_summaries"] == [summaries[2]]
    assert seen["answer_windows"] == [windows[2]]
    assert result.answer_text == "the answer"
    assert result.answer == "the answer [cite: s01 ¶0-0]"
    assert result.answer_kind == "fact"
    assert result.evidence_strategy == "select"
    assert result.answer_format == "structured"
    assert result.claim_candidates == 3
    assert result.episode_summary_candidates == 3
    assert result.window_candidates == 3
    assert result.model_selected_claims == 1
    assert result.model_selected_episode_summaries == 1
    assert result.model_selected_windows == 1
    assert result.token_usage["total_tokens"] == 12


async def test_fast_select_failure_falls_back_to_ranked_heads_and_reports_it(monkeypatch):
    from pneuma_knowledge_core.recall import fast as fast_module

    claims = _claims(3)
    summaries = _summaries(3)
    windows = _windows(3)
    seen = {}

    async def retrieve_claims(*args, **kwargs):  # noqa: ANN002, ANN003
        return claims

    async def retrieve_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        return windows

    async def build_summaries(*args, **kwargs):  # noqa: ANN002, ANN003
        return summaries

    async def fail_selection(*args, **kwargs):  # noqa: ANN002, ANN003
        return None, {
            "input_tokens": 2,
            "output_tokens": 0,
            "total_tokens": 2,
            "cache_read": 0,
            "cache_creation": 0,
        }, "timeout"

    async def answer(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["claims"] = list(args[2])
        seen["summaries"] = list(kwargs["episode_summaries"])
        seen["windows"] = list(kwargs["windows"])
        return "fallback [cite: s01 ¶0-0]", {
            "input_tokens": 3,
            "output_tokens": 1,
            "total_tokens": 4,
            "cache_read": 0,
            "cache_creation": 0,
        }, {}

    monkeypatch.setattr(fast_module, "retrieve_claims", retrieve_claims)
    monkeypatch.setattr(fast_module, "retrieve_windows", retrieve_windows)
    monkeypatch.setattr(fast_module, "build_episode_summaries", build_summaries)
    monkeypatch.setattr(fast_module, "select_evidence", fail_selection)
    monkeypatch.setattr(fast_module, "answer_with_selector", answer)

    result = await fast_recall(
        UserId("u-quality"),
        "q",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=StructuredModel(parsed=EvidenceSelection(), seen=[]),
        evidence_strategy="select",
        cap=2,
        episode_summary_cap=2,
        window_cap=2,
        window_candidate_cap=3,
    )

    assert seen == {
        "claims": claims[:2],
        "summaries": summaries[:2],
        "windows": windows[:2],
    }
    assert result.evidence_selection_degraded == "timeout"
    assert result.answer == "fallback [cite: s01 ¶0-0]"
    assert result.answer_text == "fallback"
    assert result.model_selected_claims == 0
    assert result.model_selected_episode_summaries == 0
    assert result.model_selected_windows == 0
    assert result.token_usage["total_tokens"] == 6


async def test_default_fast_path_never_invokes_quality_selector_or_structured_answer(monkeypatch):
    from pneuma_knowledge_core.recall import fast as fast_module

    async def no_claims(*args, **kwargs):  # noqa: ANN002, ANN003
        return []

    async def no_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        return []

    async def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("opt-in quality pass ran on the default path")

    async def answer(*args, **kwargs):  # noqa: ANN002, ANN003
        return "historical [cite: s01 ¶0-0]", {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "cache_read": 0,
            "cache_creation": 0,
        }, {}

    monkeypatch.setattr(fast_module, "retrieve_claims", no_claims)
    monkeypatch.setattr(fast_module, "retrieve_windows", no_windows)
    monkeypatch.setattr(fast_module, "select_evidence", forbidden)
    monkeypatch.setattr(fast_module, "answer_with_structured", forbidden)
    monkeypatch.setattr(fast_module, "answer_with_selector", answer)

    result = await fast_recall(
        UserId("u-quality"),
        "q",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        embeddings=object(),
        model=StructuredModel(parsed=EvidenceSelection(), seen=[]),
    )

    assert result.answer == "historical [cite: s01 ¶0-0]"
    assert result.evidence_strategy == "ranked"
    assert result.answer_format == "text"
    assert result.answer_text == "historical"
