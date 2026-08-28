"""The third fast-lane evidence strategy: `all`.

`ranked` keeps fixed heads. `select` spends one structured call choosing between wide
candidates. `all` removes the choice instead of making it: the pool `select` would have been
offered is handed to ONE answer call whole — no selection turn, no score truncation — so a
missing fact can no longer be blamed on a selector that did not pick it.

What is pinned here is exactly what makes that safe rather than reckless:

* every candidate reaches the answer, and the counts say so;
* no selection model is called — the selector-role model is a fake that fails the test if
  anything touches it, and the `select` stage comes back `skipped`, not `ran`;
* the one bound (`all_context_chars`) drops in a FIXED order — windows, then episode
  summaries, then the lowest-ranked claims — and never silently: the result carries
  `evidence_selection_degraded="all:truncated"` and the `assemble` preview carries the counts;
* `ranked` and `select` are untouched, including the byte-stable System contract.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.recall.fast import (
    DELIBERATION_CHARS,
    DeliberatedRecallAnswer,
    EpisodeSummary,
    RetrievedClaim,
    StructuredRecallAnswer,
    apply_context_ceiling,
    fast_recall,
    structured_answer_contract,
)
from pneuma_knowledge_core.recall.rag import RecallHit


class AnsweringModel(BaseChatModel):
    """One structured answer, with the schema it was asked for recorded."""

    parsed: object
    schemas: list = []
    contracts: list = []

    @property
    def _llm_type(self) -> str:
        return "evidence-strategy-all-test"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self
        outer.schemas.append(schema)

        class Bound:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.contracts.append(messages[0].content)
                return {
                    "raw": AIMessage(
                        content="",
                        usage_metadata={
                            "input_tokens": 20,
                            "output_tokens": 4,
                            "total_tokens": 24,
                        },
                    ),
                    "parsed": outer.parsed,
                    "parsing_error": None,
                }

        return Bound()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="unused"))])


class ForbiddenModel(BaseChatModel):
    """The selector-role model. Touching it at all is the failure this lane exists to avoid."""

    @property
    def _llm_type(self) -> str:
        return "must-never-be-called"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        raise AssertionError("the `all` strategy made a selection call")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        raise AssertionError("the `all` strategy made a selection call")


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


def _wire(monkeypatch, claims, summaries, windows, seen):
    from pneuma_knowledge_core.recall import fast as fast_module

    async def retrieve_claims(*args, **kwargs):  # noqa: ANN002, ANN003
        return list(claims)

    async def retrieve_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        return list(windows)

    async def build_summaries(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["summary_cap"] = kwargs["cap"]
        # The real builder caps what it produces; a fake that ignored the cap would hide
        # exactly the truncation the ranked path is supposed to keep doing.
        return list(summaries)[: kwargs["cap"]]

    async def forbidden_selection(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("select_evidence ran under the `all` strategy")

    monkeypatch.setattr(fast_module, "retrieve_claims", retrieve_claims)
    monkeypatch.setattr(fast_module, "retrieve_windows", retrieve_windows)
    monkeypatch.setattr(fast_module, "build_episode_summaries", build_summaries)
    monkeypatch.setattr(fast_module, "select_evidence", forbidden_selection)


def _stage(result, name: str):
    return next(stage for stage in result.stages if stage.name == name)


async def test_all_hands_the_whole_candidate_pool_to_one_answer_call(monkeypatch):
    """The pool the selector would have judged IS the context, and nothing judged it."""
    claims, summaries, windows = _claims(9), _summaries(5), _windows(5)
    seen: dict = {}
    _wire(monkeypatch, claims, summaries, windows, seen)

    model = AnsweringModel(
        parsed=DeliberatedRecallAnswer(
            deliberation="claim 0 and window 2 bear on it; the rest is noise.",
            answer_kind="fact",
            answer="August 14, 2026.",
            citations=[],
        ),
        schemas=[],
        contracts=[],
    )
    result = await fast_recall(
        UserId("u-all"),
        "what happened",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=model,
        glance_model=ForbiddenModel(),
        evidence_strategy="all",
        answer_format="structured",
        # The final caps `select` would have truncated to. `all` must ignore all three.
        cap=1,
        episode_summary_cap=1,
        window_cap=1,
        claim_candidate_cap=9,
        window_candidate_cap=5,
    )

    # Candidate breadth, unbroken: the episode face is built over candidate depth, and every
    # face reaches the answer at its full size rather than at its final cap.
    assert seen["summary_cap"] == 5
    assert len(result.used_claims) == 9
    assert len(result.used_episode_summaries) == 5
    assert len(result.used_windows) == 5
    assert result.claim_candidates == 9
    assert result.episode_summary_candidates == 5
    assert result.window_candidates == 5

    # Nothing was selected, because nothing selected.
    assert result.model_selected_claims == 0
    assert result.model_selected_episode_summaries == 0
    assert result.model_selected_windows == 0
    assert result.model_selected_component_items == 0
    assert result.evidence_selection_degraded is None
    assert _stage(result, "select").status == "skipped"
    assert _stage(result, "select").ms == 0

    # ONE answer call, and its structured output parsed.
    assert len(model.contracts) == 1
    assert result.answer_text == "August 14, 2026."
    assert result.answer_kind == "fact"
    assert result.evidence_strategy == "all"
    assert result.answer_format == "structured"
    assert result.token_usage["total_tokens"] == 24


async def test_all_asks_the_answer_call_for_its_own_evidence_review(monkeypatch):
    """No selection call means no evidence review — unless the answering call makes one."""
    claims, summaries, windows = _claims(3), _summaries(2), _windows(2)
    _wire(monkeypatch, claims, summaries, windows, {})

    long_review = "x" * (DELIBERATION_CHARS + 200)
    model = AnsweringModel(
        parsed=DeliberatedRecallAnswer(
            deliberation=long_review,
            answer_kind="fact",
            answer="the answer",
            citations=[],
        ),
        schemas=[],
        contracts=[],
    )
    result = await fast_recall(
        UserId("u-all"),
        "what happened",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=model,
        evidence_strategy="all",
        answer_format="structured",
    )

    assert model.schemas == [DeliberatedRecallAnswer]
    assert model.contracts[0] == structured_answer_contract(deliberate=True)
    # Bounded on the way OUT, never by the schema: an overlong review costs a trim, not a
    # parse failure and a second turn.
    assert result.deliberation == "x" * DELIBERATION_CHARS
    assert result.answer_format_degraded is None


async def test_the_review_can_be_turned_off_without_leaving_the_all_strategy(monkeypatch):
    """`deliberate` is stateable, because a measurement has to be able to isolate it."""
    _wire(monkeypatch, _claims(3), _summaries(2), _windows(2), {})

    model = AnsweringModel(
        parsed=StructuredRecallAnswer(
            answer_kind="fact", answer="the answer", citations=[]
        ),
        schemas=[],
        contracts=[],
    )
    result = await fast_recall(
        UserId("u-all"),
        "what happened",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=model,
        evidence_strategy="all",
        answer_format="structured",
        deliberate=False,
    )

    assert model.schemas == [StructuredRecallAnswer]
    assert model.contracts[0] == structured_answer_contract()
    assert result.deliberation is None


async def test_the_context_ceiling_drops_windows_then_episodes_then_claims(monkeypatch):
    """The one bound, in one fixed mechanical order, stated in full."""
    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    _wire(monkeypatch, claims, summaries, windows, {})
    # 3 × "claim N" (7) + 3 × "episode summary N" (17) + 3 × "verbatim window N" (17) = 123.
    assert (
        sum(len(c.text) for c in claims)
        + sum(len(s.text) for s in summaries)
        + sum(len(w.text) for w in windows)
    ) == 123

    async def run(ceiling: int):
        model = AnsweringModel(
            parsed=DeliberatedRecallAnswer(
                deliberation="", answer_kind="fact", answer="a", citations=[]
            ),
            schemas=[],
            contracts=[],
        )
        return await fast_recall(
            UserId("u-all"),
            "what happened",
            as_of=datetime(2026, 8, 14),
            claim_lexical=object(),
            claim_vectors=object(),
            lexical=object(),
            vectors=object(),
            embeddings=object(),
            model=model,
            evidence_strategy="all",
            answer_format="structured",
            all_context_chars=ceiling,
        )

    # 40 chars: every window goes first, then episode summaries until it fits. The claim
    # face — the precise, citable one — is not touched at all.
    tight = await run(40)
    assert len(tight.used_windows) == 0
    assert len(tight.used_episode_summaries) == 1
    assert len(tight.used_claims) == 3
    assert tight.evidence_selection_degraded == "all:truncated"
    preview = _stage(tight, "assemble").preview
    assert preview["dropped_windows"] == 3
    assert preview["dropped_episode_summaries"] == 2
    assert preview["dropped_claims"] == 0
    assert preview["context_ceiling"] == 40

    # 15 chars: only now does the claim face give ground, from its lowest-ranked end.
    brutal = await run(15)
    assert len(brutal.used_windows) == 0
    assert len(brutal.used_episode_summaries) == 0
    assert [c.text for c in brutal.used_claims] == ["claim 0", "claim 1"]
    assert brutal.evidence_selection_degraded == "all:truncated"
    assert _stage(brutal, "assemble").preview["dropped_claims"] == 1

    # Under the ceiling nothing is cut and nothing is claimed to have been.
    roomy = await run(10_000)
    assert len(roomy.used_windows) == 3
    assert len(roomy.used_episode_summaries) == 3
    assert len(roomy.used_claims) == 3
    assert roomy.evidence_selection_degraded is None
    assert "dropped" not in (_stage(roomy, "assemble").preview or {})


def test_the_ceiling_is_off_at_zero_and_never_drops_a_whole_context():
    """A ceiling of 0 is "no ceiling", not "keep nothing" — the difference is a silent
    empty answer."""
    kept = apply_context_ceiling(_claims(2), _summaries(2), _windows(2), ceiling=0)
    assert [len(face) for face in kept[:3]] == [2, 2, 2]
    assert kept[3] == {}


async def test_ranked_and_select_are_untouched_by_the_third_strategy(monkeypatch):
    """The historical lanes: fixed heads, the selection call still made, no review field."""
    claims, summaries, windows = _claims(9), _summaries(5), _windows(5)
    seen: dict = {}
    _wire(monkeypatch, claims, summaries, windows, seen)

    model = AnsweringModel(
        parsed=StructuredRecallAnswer(
            answer_kind="fact", answer="the answer", citations=[]
        ),
        schemas=[],
        contracts=[],
    )
    ranked = await fast_recall(
        UserId("u-all"),
        "what happened",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=model,
        evidence_strategy="ranked",
        answer_format="structured",
        cap=2,
        episode_summary_cap=2,
        window_cap=1,
    )
    assert len(ranked.used_claims) == 2
    assert len(ranked.used_episode_summaries) == 2
    assert len(ranked.used_windows) == 1
    assert ranked.deliberation is None
    assert model.schemas == [StructuredRecallAnswer]
    assert model.contracts[0] == structured_answer_contract()
    assert _stage(ranked, "select").status == "skipped"

    # `select` still calls the selector — the fake wired above raises when it does, which is
    # exactly how this test knows the branch was taken.
    with pytest.raises(AssertionError, match="select_evidence ran"):
        await fast_recall(
            UserId("u-all"),
            "what happened",
            as_of=datetime(2026, 8, 14),
            claim_lexical=object(),
            claim_vectors=object(),
            lexical=object(),
            vectors=object(),
            embeddings=object(),
            model=model,
            evidence_strategy="select",
            answer_format="structured",
        )


def test_an_unknown_strategy_is_refused_by_name():
    assert "'ranked', 'select' or 'all'" in _refusal()


def _refusal() -> str:
    import asyncio

    try:
        asyncio.run(
            fast_recall(
                UserId("u-all"),
                "q",
                as_of=datetime(2026, 8, 14),
                claim_lexical=object(),
                claim_vectors=object(),
                embeddings=object(),
                model=object(),
                evidence_strategy="everything",  # type: ignore[arg-type]
            )
        )
    except ValueError as error:
        return str(error)
    raise AssertionError("an unknown strategy was accepted")
