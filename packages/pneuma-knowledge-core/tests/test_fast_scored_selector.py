"""The `select` strategy's other selector: a scorer, and a floor in code.

What these pin is the claim that makes the two selectors comparable at all — AFTER the
judgement, nothing differs. The scored path validates with `_selected_indexes`, unions the
same ranked safety anchors and enforces the same per-face caps, so a test that compares it
against that function on the same inputs is comparing the two paths' mechanics, not
re-implementing them here.

The rest is the fail-soft contract: a pass that times out, fails, or comes back with no
score at all selects NOTHING and says so, and the lane answers out of its exact ranked
heads. A partial failure is the interesting one: unscored candidates are neither kept nor
dropped, and the anchors go on protecting the head exactly as they do when the whole pass
fails.

Synthetic throughout (Mei LIN, 阿宝, example.com); the scorer is a dict.
"""

from __future__ import annotations

from dataclasses import replace

import asyncio
from datetime import datetime

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScores
from pneuma_knowledge_core.recall.fast import (
    DEFAULT_SELECTION_CLAIM_ANCHORS,
    DEFAULT_SELECTION_EPISODE_ANCHORS,
    DEFAULT_SELECTION_WINDOW_ANCHORS,
    DEFAULT_SELECT_SCORE_FLOOR,
    SCORER_CANDIDATE_MAX_CHARS,
    SCORER_CLIP_MARKER,
    EpisodeSummary,
    RetrievedClaim,
    SelectedEvidence,
    _selected_indexes,
    fast_recall,
    select_evidence_scored,
    selection_candidate_texts,
)
from pneuma_knowledge_core.recall.rag import RecallHit

UID = UserId("u-scored-selector")


# ------------------------------------------------------------------ fakes and fixtures


class DictScorer:
    """Scores a candidate by the first keyed phrase its text contains.

    A dict keyed by candidate text, with substring lookup so a test can name the fact it
    cares about ("阿宝 signed") instead of re-rendering the whole card. Anything unnamed
    scores `default`; `None` in the dict is a candidate this scorer could not score.
    """

    def __init__(self, scores: dict[str, float | None], *, default: float | None = 0.0,
                 input_tokens: int = 0, delay: float = 0.0, raise_with: Exception | None = None):
        self.scores = scores
        self.default = default
        self.input_tokens = input_tokens
        self.delay = delay
        self.raise_with = raise_with
        self.seen: list[tuple[str, list[str]]] = []

    async def score(self, question: str, candidates):  # noqa: ANN001
        self.seen.append((question, list(candidates)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_with is not None:
            raise self.raise_with
        out: list[float | None] = []
        for text in candidates:
            hit = next((key for key in self.scores if key in text), None)
            out.append(self.scores[hit] if hit is not None else self.default)
        return EvidenceScores(scores=tuple(out), input_tokens=self.input_tokens)


def _without_context(rows):
    return [replace(row, retrieval_origins=(), source_times=()) for row in rows]


def _claims(count: int) -> list[RetrievedClaim]:
    return [
        RetrievedClaim(
            anchor=AnchorId(f"a{index:03d}"),
            document_path=f"people/mei-lin-{index}.md",
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


# ------------------------------------------------------------------ the selection itself


async def test_the_floor_keeps_best_first_then_the_same_anchors_and_caps_as_the_model_path():
    """(a) The scored path is the model path with a different judge in front of it."""
    scorer = DictScorer(
        {"claim 11": 0.9, "claim 3": 0.7, "episode summary 5": 0.8, "verbatim window 4": 0.6},
        default=0.1,
        input_tokens=4321,
    )
    selection, tokens, degraded = await select_evidence_scored(
        scorer,
        "which facts answer this?",
        claims=_claims(12),
        episode_summaries=_summaries(6),
        windows=_windows(6),
        claim_cap=10,
        episode_summary_cap=5,
        window_cap=5,
        timeout=None,
    )

    assert degraded is None
    assert tokens == 4321
    # Kept best first, ties in pool order — then EXACTLY `_selected_indexes`, which is what
    # the model path runs on its own coordinates.
    assert selection.claim_indexes == _selected_indexes(
        [11, 3], available=12, cap=10, anchors=DEFAULT_SELECTION_CLAIM_ANCHORS
    )
    assert selection.episode_indexes == _selected_indexes(
        [5], available=6, cap=5, anchors=DEFAULT_SELECTION_EPISODE_ANCHORS
    )
    assert selection.window_indexes == _selected_indexes(
        [4], available=6, cap=5, anchors=DEFAULT_SELECTION_WINDOW_ANCHORS
    )
    # What the floor kept, before the anchors widened it.
    assert selection.model_claim_count == 2
    assert selection.model_episode_count == 1
    assert selection.model_window_count == 1
    assert selection.unscored == 0


async def test_a_higher_score_outranks_pool_order_and_the_floor_is_inclusive():
    scorer = DictScorer({"claim 0": 0.5, "claim 1": 0.95, "claim 2": 0.49}, default=0.0)
    selection, _tokens, _degraded = await select_evidence_scored(
        scorer,
        "q",
        claims=_claims(3),
        episode_summaries=(),
        windows=(),
        claim_cap=3,
        timeout=None,
    )
    # 1 outranks 0 on score; 2 sits just under the floor and is dropped by the floor, then
    # returns only as an anchor — which is the anchors' job, not the scorer's.
    assert selection.claim_indexes == (1, 0, 2)
    assert selection.model_claim_count == 2


async def test_a_scorer_that_finds_nothing_useful_still_leaves_the_ranked_head_standing():
    """(b) The anchors are unconditional in BOTH paths — a floor cannot empty the context."""
    scorer = DictScorer({}, default=0.0)
    selection, _tokens, degraded = await select_evidence_scored(
        scorer,
        "nothing in this library is about that",
        claims=_claims(12),
        episode_summaries=_summaries(6),
        windows=_windows(6),
        claim_cap=10,
        episode_summary_cap=5,
        window_cap=5,
        timeout=None,
    )
    assert degraded is None
    assert selection.claim_indexes == tuple(range(DEFAULT_SELECTION_CLAIM_ANCHORS))
    assert selection.episode_indexes == tuple(range(DEFAULT_SELECTION_EPISODE_ANCHORS))
    assert selection.window_indexes == tuple(range(DEFAULT_SELECTION_WINDOW_ANCHORS))
    assert selection.model_claim_count == 0


async def test_an_unscored_candidate_is_neither_kept_nor_dropped():
    """(d) A failed shard is not a judgement, so the floor does not get to read it as one."""
    scorer = DictScorer(
        {"claim 0": None, "claim 1": 0.9, "claim 2": None}, default=0.0, input_tokens=12
    )
    selection, tokens, degraded = await select_evidence_scored(
        scorer,
        "q",
        claims=_claims(4),
        episode_summaries=(),
        windows=(),
        claim_cap=4,
        timeout=None,
    )
    assert degraded is None and tokens == 12
    assert selection.unscored == 2
    assert selection.model_claim_count == 1  # only the scored keeper counts as kept
    assert selection.claim_indexes[0] == 1  # and the anchors still hold the head
    assert set(selection.claim_indexes) == {0, 1, 2, 3}


async def test_a_pass_that_scored_nothing_at_all_selects_nothing_and_says_error():
    """(c) All-None is indistinguishable from a failed pass, and is reported as one."""
    scorer = DictScorer({}, default=None, input_tokens=99)
    selection, tokens, degraded = await select_evidence_scored(
        scorer, "q", claims=_claims(3), episode_summaries=(), windows=(), timeout=None
    )
    assert selection is None
    assert tokens == 99  # the pass was still paid for; the cost is not hidden
    assert degraded == "error"


async def test_a_scorer_that_raises_degrades_without_a_fabricated_selection():
    scorer = DictScorer({}, raise_with=RuntimeError("provider down"))
    selection, tokens, degraded = await select_evidence_scored(
        scorer, "q", claims=_claims(3), episode_summaries=(), windows=(), timeout=None
    )
    assert selection is None and tokens == 0 and degraded == "error"


async def test_a_scorer_that_does_not_come_back_in_time_degrades_as_timeout():
    """(e) The lane's ceiling is the outer bound; past it there is no selection to use."""
    scorer = DictScorer({}, default=1.0, delay=0.05)
    selection, tokens, degraded = await select_evidence_scored(
        scorer, "q", claims=_claims(3), episode_summaries=(), windows=(), timeout=0.01
    )
    assert selection is None and tokens == 0 and degraded == "timeout"


async def test_the_scored_selector_never_asks_for_a_whole_document():
    """(f) Reading a page whole is a judgement about the page, which this scorer is not
    asked — so the one thing it cannot return is a document path."""
    scorer = DictScorer({}, default=1.0)
    selection, _tokens, _degraded = await select_evidence_scored(
        scorer,
        "is people/mei-lin-0.md worth reading whole?",
        claims=_claims(2),
        episode_summaries=(),
        windows=(),
        timeout=None,
    )
    assert selection.document_paths == ()


async def test_an_empty_pool_is_an_empty_selection_and_no_scorer_call():
    scorer = DictScorer({}, default=1.0)
    selection, tokens, degraded = await select_evidence_scored(
        scorer, "q", claims=(), episode_summaries=(), windows=(), timeout=None
    )
    assert selection == SelectedEvidence((), (), (), (), ())
    assert tokens == 0 and degraded is None
    assert scorer.seen == []


# ------------------------------------------------------------------ what the scorer reads


async def test_each_face_renders_the_facts_that_face_is_judged_on_in_pool_order():
    """(g) Same facts as the selector's lines, minus the index label — and a long passage is
    spliced head+tail so a shard's size never follows whichever window was retrieved."""
    claim = RetrievedClaim(
        anchor=AnchorId("a001"),
        document_path="people/mei-lin.md",
        section_path=("背景", "合作"),
        text="Mei LIN and 阿宝 co-signed the example.com renewal.",
        citations=(),
    )
    long_tail = "TAIL-MARKER-KEPT"
    window = RecallHit(
        source_id=SourceId("chat-9"),
        block_start=4,
        block_end=7,
        text="A" * 5_000 + long_tail,
        paths=("lexical",),
        score=0.5,
    )
    cards = selection_candidate_texts(
        claims=[claim], episode_summaries=_summaries(1), windows=[window]
    )

    assert cards[0] == (
        "[note · document=people/mei-lin.md; section=背景 / 合作] "
        "source occurrence / cited block clocks: unknown (no resolved metadata)\n"
        "Mei LIN and 阿宝 co-signed the example.com renewal."
    )
    assert cards[1].startswith("[episode summary · occurred_on=2026-08-14; span=0-1] ")
    assert cards[2].startswith("[verbatim source passage · source=chat-9; span=4-7] ")
    assert SCORER_CLIP_MARKER in cards[2]
    assert cards[2].endswith(long_tail)  # the tail survives; the middle is what was cut
    assert len(cards[2]) < len(window.text)


async def test_a_candidate_inside_the_budget_is_handed_over_whole():
    window = _windows(1)[0]
    card = selection_candidate_texts(claims=(), episode_summaries=(), windows=[window])[0]
    assert card.endswith(window.text)
    assert SCORER_CLIP_MARKER not in card
    assert len(window.text) < SCORER_CANDIDATE_MAX_CHARS


# ------------------------------------------------------------------ inside the lane


def _lane_patches(monkeypatch, claims, summaries, windows, seen):
    from pneuma_knowledge_core.recall import fast as fast_module

    async def retrieve_claims(*args, **kwargs):  # noqa: ANN002, ANN003
        return claims

    async def retrieve_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        return windows

    async def build_summaries(*args, **kwargs):  # noqa: ANN002, ANN003
        return summaries

    async def answer(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["claims"] = list(args[2])
        seen["summaries"] = list(kwargs["episode_summaries"])
        seen["windows"] = list(kwargs["windows"])
        return "answered [cite: s01 ¶0-0]", {
            "input_tokens": 3,
            "output_tokens": 1,
            "total_tokens": 4,
            "cache_read": 0,
            "cache_creation": 0,
        }, {}

    async def no_model_selection(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["model_selector_ran"] = True
        raise AssertionError("the model selector ran while a scorer was wired")

    monkeypatch.setattr(fast_module, "retrieve_claims", retrieve_claims)
    monkeypatch.setattr(fast_module, "retrieve_windows", retrieve_windows)
    monkeypatch.setattr(fast_module, "build_episode_summaries", build_summaries)
    monkeypatch.setattr(fast_module, "answer_with_selector", answer)
    monkeypatch.setattr(fast_module, "select_evidence", no_model_selection)


async def _lane(scorer, *, claims, summaries, windows, seen, monkeypatch, **kwargs):
    _lane_patches(monkeypatch, claims, summaries, windows, seen)
    return await fast_recall(
        UID,
        "who renewed example.com?",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        # No chat model at all: the scored selector needs none, and the lane must still
        # compose a context rather than fall back to the ranked heads.
        model=None,
        evidence_strategy="select",
        evidence_scorer=scorer,
        cap=2,
        episode_summary_cap=2,
        window_cap=2,
        window_candidate_cap=3,
        **kwargs,
    )


async def test_the_lane_composes_its_context_with_the_scorer_and_prices_it_apart(monkeypatch):
    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    seen: dict = {}
    scorer = DictScorer(
        {"claim 2": 0.9, "episode summary 1": 0.8, "verbatim window 2": 0.7},
        default=0.0,
        input_tokens=2048,
    )
    result = await _lane(
        scorer, claims=claims, summaries=summaries, windows=windows, seen=seen,
        monkeypatch=monkeypatch,
    )

    assert "model_selector_ran" not in seen
    assert "as_of: 2026-08-14T00:00:00" in scorer.seen[0][0]
    assert "subject_timezone: UTC" in scorer.seen[0][0]
    # Score first, then the ranked anchor behind it — the model path's mechanics exactly.
    assert _without_context(seen["claims"]) == [claims[2], claims[0]]
    assert seen["summaries"] == [summaries[1], summaries[0]]
    assert _without_context(seen["windows"]) == [windows[2], windows[0]]
    assert result.evidence_selection_degraded is None
    assert result.model_selected_claims == 1
    # The scorer's tokens are their own currency: on the result, and never in the ledger.
    assert result.scorer_input_tokens == 2048
    assert result.token_usage["total_tokens"] == 4
    stage = {s.name: s for s in result.stages}["select"]
    assert stage.preview["selector"] == "scorer"
    assert stage.preview["scorer_input_tokens"] == 2048
    assert stage.preview["kept"] == {
        "claims": 1, "episodes": 1, "windows": 1, "components": 0
    }
    assert stage.preview["unscored"] == 0


async def test_a_failed_scoring_pass_leaves_the_lane_on_its_exact_ranked_heads(monkeypatch):
    """(c) in the lane: nothing judged means nothing selected, said out loud."""
    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    seen: dict = {}
    scorer = DictScorer({}, default=None, input_tokens=7)
    result = await _lane(
        scorer, claims=claims, summaries=summaries, windows=windows, seen=seen,
        monkeypatch=monkeypatch,
    )

    assert _without_context(seen["claims"]) == claims[:2]
    assert seen["summaries"] == summaries[:2]
    assert _without_context(seen["windows"]) == windows[:2]
    assert result.evidence_selection_degraded == "error"
    assert result.scorer_input_tokens == 7
    stage = {s.name: s for s in result.stages}["select"]
    assert stage.status == "degraded" and stage.detail == "error"
    assert stage.preview["chosen"] == "none"
    assert stage.preview["selector"] == "scorer"


async def test_the_lane_reports_what_the_pass_could_not_score(monkeypatch):
    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    seen: dict = {}
    scorer = DictScorer({"claim 0": None, "claim 2": 0.9}, default=0.0)
    result = await _lane(
        scorer, claims=claims, summaries=summaries, windows=windows, seen=seen,
        monkeypatch=monkeypatch,
    )
    stage = {s.name: s for s in result.stages}["select"]
    assert stage.preview["unscored"] == 1
    assert result.evidence_selection_degraded is None


async def test_the_floor_is_the_deployments_to_move(monkeypatch):
    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    seen: dict = {}
    scorer = DictScorer({"claim 1": 0.4}, default=0.0)
    result = await _lane(
        scorer, claims=claims, summaries=summaries, windows=windows, seen=seen,
        monkeypatch=monkeypatch, select_score_floor=0.3,
    )
    assert _without_context(seen["claims"])[0] == claims[1]
    assert result.model_selected_claims == 1
    assert DEFAULT_SELECT_SCORE_FLOOR > 0.3  # the default would have dropped it


async def test_with_no_scorer_the_select_strategy_is_the_model_call_it_has_always_been(
    monkeypatch,
):
    """(h) `evidence_scorer=None` is the historical lane: the model selector runs, its
    preview says nothing about a scorer, and the scorer field on the answer stays 0."""
    from pneuma_knowledge_core.recall import fast as fast_module

    claims, summaries, windows = _claims(3), _summaries(3), _windows(3)
    seen: dict = {}
    _lane_patches(monkeypatch, claims, summaries, windows, seen)

    async def choose(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["model_selector_ran"] = True
        return SelectedEvidence((2,), (2,), (2,), (), model_claim_count=1), {
            "input_tokens": 5,
            "output_tokens": 2,
            "total_tokens": 7,
            "cache_read": 0,
            "cache_creation": 0,
        }, None

    async def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the scored selector ran with no scorer wired")

    monkeypatch.setattr(fast_module, "select_evidence", choose)
    monkeypatch.setattr(fast_module, "select_evidence_scored", forbidden)

    class _Model:
        """Not called — the selector is patched — but not None either, so the lane takes
        the model branch it has always taken."""

    result = await fast_recall(
        UID,
        "who renewed example.com?",
        as_of=datetime(2026, 8, 14),
        claim_lexical=object(),
        claim_vectors=object(),
        lexical=object(),
        vectors=object(),
        embeddings=object(),
        model=_Model(),
        evidence_strategy="select",
        cap=2,
        episode_summary_cap=2,
        window_cap=2,
        window_candidate_cap=3,
    )

    assert seen["model_selector_ran"] is True
    assert _without_context(seen["claims"]) == [claims[2]]
    assert result.scorer_input_tokens == 0
    assert result.token_usage["total_tokens"] == 11
    stage = {s.name: s for s in result.stages}["select"]
    assert "selector" not in stage.preview and "scorer_input_tokens" not in stage.preview
