"""The full mode's embedding matcher: semantic recognition on top of character matching.

WHY IT IS A SEPARATE ARM
------------------------
Character similarity cannot tell "the pilot ends on the 24th" from "the pilot ends next
Friday", so a purely mechanical matcher UNDER-counts recall — it reports the compiler as
having lost a fact it actually recorded in different words. The embedding arm exists to
recover those.

The combination rule is the existing evaluator's, unchanged: `score = max(char, cosine)`.
Taking the max means the semantic arm can only ever recognize MORE true matches, never fewer,
so turning it on cannot make a bad artifact look good by hiding a character-level match.

WHY IT PRE-EMBEDS
-----------------
A `Matcher` is a pure synchronous function — the metric modules must stay pure and offline by
construction. So the vectors are computed ONCE, up front, over an explicit text list, and the
matcher is a lookup. A text that was not in that list scores on characters alone, which is
recorded in `coverage` rather than silently assumed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .artifacts import Trajectory
from .errors import EvalDependencyError
from .matching import char_similarity, cosine
from .metrics.common import Matcher
from .truth import TruthSet

DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"


def collect_texts(trajectory: Trajectory, truth: TruthSet | None) -> list[str]:
    """Every text the matcher will ever be asked about, deduplicated in a stable order."""
    seen: dict[str, None] = {}
    for checkpoint in trajectory.checkpoints:
        for claim in checkpoint.claims:
            seen.setdefault(claim.text, None)
    if truth is not None:
        for entry in truth.entries:
            seen.setdefault(entry.value, None)
        for negative in truth.negatives:
            seen.setdefault(negative.value, None)
    return [text for text in seen if text.strip()]


@dataclass(frozen=True)
class EmbeddingMatcher:
    """`max(char_similarity, cosine)` over pre-computed vectors."""

    vectors: dict[str, list[float]]

    def __call__(self, expected: str, candidate: str) -> float:
        char = char_similarity(expected, candidate)
        semantic = cosine(self.vectors.get(expected), self.vectors.get(candidate))
        return max(char, semantic)

    @property
    def coverage(self) -> int:
        return len(self.vectors)


def build_embedding_matcher(
    texts: Sequence[str],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    batch_size: int = 64,
) -> Matcher:
    """Embed `texts` and return the combined matcher. Raises when credentials are missing.

    Deliberately loud: an evaluation asked for in full mode that quietly ran on characters
    alone would publish a lower recall under a label promising the higher-fidelity arm.
    """
    import os

    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EvalDependencyError(
            "the embedding matcher needs OPENROUTER_API_KEY or OPENAI_API_KEY; --mode "
            "mechanical needs neither"
        )
    try:
        from langchain_openai import OpenAIEmbeddings
    except ModuleNotFoundError as exc:  # pragma: no cover - service dependency
        raise EvalDependencyError("the embedding matcher needs langchain-openai") from exc

    embeddings: Any = OpenAIEmbeddings(
        model=model or os.environ.get("EVAL_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        api_key=key,
        base_url=base_url or os.environ.get("OPENROUTER_BASE_URL") or None,
        check_embedding_ctx_length=False,
    )
    unique = [text for text in dict.fromkeys(texts) if text.strip()]
    vectors: dict[str, list[float]] = {}
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        vectors.update(zip(batch, embeddings.embed_documents(batch)))
    return EmbeddingMatcher(vectors=vectors)


def matcher_from_vectors(vectors: dict[str, list[float]]) -> Matcher:
    """Wrap already-computed vectors (a caller that owns an async embeddings port)."""
    return EmbeddingMatcher(vectors=dict(vectors))


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingMatcher",
    "build_embedding_matcher",
    "collect_texts",
    "matcher_from_vectors",
]
