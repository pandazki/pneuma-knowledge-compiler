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
from typing import Protocol, Sequence


@dataclass(frozen=True)
class EvidenceScores:
    """One scorer pass over one candidate list."""

    #: Index-aligned with the submitted candidates; None = unscored.
    scores: tuple[float | None, ...]
    #: What the scorer consumed, for the stage preview (not the LLM ledger): a decision
    #: model's tokens are a different currency from the answering call's and are never
    #: summed into `token_usage`.
    input_tokens: int = 0


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
