"""Evidence scorer port: one usefulness score per candidate, no generation.

A calibrated decision model reads the question and each candidate independently and places
it on a FIXED scale — that is the judgement a generative selector makes implicitly, made
explicit and made cheap. The `select` strategy's model selector reads the whole candidate
pool in one prefill-heavy call and returns coordinates; a scorer returns numbers, and the
keep/drop decision moves out of the model and into a floor in code (`select_evidence_scored`
in `recall/fast.py`). Everything after the selection — range validation, ranked safety
anchors, per-face caps, provenance following — is the same mechanism either way.

Unlike the storage ports this one carries no ``user_id``, for the same reason ``Reranker``
carries none: a scorer holds no state and reads nothing — it is pure computation over the
texts the caller already retrieved under its own tenant (I1 guards read paths into stored
state; there is none here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class SourceClockDecision:
    """Question-only source-clock intent and optional supported calendar period.

    A missing probability with a policy_id reports unavailable validation. No policy_id
    and the defaults mean the optional capability was not configured.
    """

    use_source_clocks: bool = False
    probability: float | None = None
    input_tokens: int = 0
    policy_id: str | None = None
    period: str | None = None
    period_confidence: float | None = None


@runtime_checkable
class SourceClockPolicy(Protocol):
    """Optional question interpretation; core computes and enforces admitted periods."""

    async def source_clock_policy(self, question: str) -> SourceClockDecision: ...


@dataclass(frozen=True)
class EvidenceScoreDetail:
    """Optional uncertainty telemetry, never an automatic admission threshold.

    Probabilities follow the provider's ordered rubric levels; confidence describes their
    concentration, not factual correctness. The model is the reported response version,
    not a guess based on the requested alias. No source text belongs in these fields.
    """

    probabilities: tuple[float, ...] = ()
    confidence: float | None = None
    model: str | None = None


@dataclass(frozen=True)
class EvidenceScores:
    """One scorer pass over one candidate list."""

    #: Index-aligned with the submitted candidates; None = unscored.
    scores: tuple[float | None, ...]
    #: What the scorer consumed, for the stage preview (not the LLM ledger): a decision
    #: model's tokens are a different currency from the answering call's and are never
    #: summed into `token_usage`.
    input_tokens: int = 0
    #: Optional, index-aligned diagnostics. Empty for scorers that do not supply them.
    details: tuple[EvidenceScoreDetail | None, ...] = ()
    requested_model: str | None = None
    rubric_id: str | None = None
    source_clock_policy: SourceClockDecision | None = None


class EvidenceScorer(Protocol):
    async def score(self, question: str, candidates: Sequence[str]) -> EvidenceScores:
        """Score every candidate's usefulness as evidence for answering `question`.

        Scale is FIXED and documented: 0.0 = about a different subject, useless for
        answering; 1.0 = states the fact the question asks for. A calibrated scorer places
        every candidate on that scale independently, so a floor in code means the same
        thing across faces and across asks. `None` marks a candidate the scorer could not
        score (a failed shard) — it is neither kept nor dropped by the floor; the caller
        decides.

        Implementations raise on total failure (transport/provider); a partial failure
        returns `None` for the affected candidates."""
        ...
