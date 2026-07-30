"""Shared primitives for the metric groups: rates, matching, near-duplicate blocking.

Text normalization and similarity are IMPORTED from the existing evaluator
(`experiments.opc_84d_evaluation`) rather than re-defined, so "these two claims are the
same statement" means one thing across the whole repository.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from pneuma_knowledge_service.experiments.opc_84d_evaluation import (
    char_similarity,
    normalize_text,
)

#: A similarity function: `(expected, candidate) -> [0, 1]`. The mechanical mode uses
#: `char_similarity`; the full mode wraps it with an embedding score (`max` of the two,
#: matching the existing evaluator's `_best_match`).
Matcher = Callable[[str, str], float]

#: Default near-duplicate threshold for claim-level redundancy. Deliberately below the
#: truth-match threshold: "the same statement written twice" is a looser relation than
#: "this claim expresses that labelled fact".
NEAR_DUPLICATE_THRESHOLD = 0.86

#: Shingle width for near-duplicate blocking. Two claims that share no 8-character run of
#: normalized text cannot reach the threshold, so blocking is exact, not approximate.
_SHINGLE = 8


def rate(numerator: float, denominator: float, *, digits: int = 6) -> float | None:
    """A rate, or None when the denominator is zero — never a silent 0.0."""
    if not denominator:
        return None
    return round(numerator / denominator, digits)


def unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """The one shape every un-computable metric returns."""
    return {"status": "unavailable", "reason": reason, **extra}


def mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def shannon_entropy(counts: Iterable[int]) -> float | None:
    """Entropy in bits over a count distribution (None when nothing was counted)."""
    values = [count for count in counts if count > 0]
    total = sum(values)
    if not total:
        return None
    return round(
        -sum((count / total) * math.log2(count / total) for count in values), 6
    )


def log_log_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Least-squares slope of log(y) against log(x) — the growth exponent.

    < 1 means y grows sublinearly in x, which is the bird's-eye claim canonical makes about
    itself. None when fewer than two usable points exist (a slope through one point is not
    a measurement).
    """
    points = [
        (math.log(x), math.log(y))
        for x, y in zip(xs, ys)
        if x and y and x > 0 and y > 0
    ]
    if len(points) < 2:
        return None
    n = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    denominator = n * sum_xx - sum_x * sum_x
    if not denominator:
        return None
    return round((n * sum_xy - sum_x * sum_y) / denominator, 6)


def best_match(
    expected: str, candidates: Sequence[str], *, matcher: Matcher = char_similarity
) -> tuple[float, str | None]:
    """The highest-scoring candidate for `expected` (score, text). Deterministic on ties:
    the first candidate in input order wins."""
    best_score = 0.0
    best_text: str | None = None
    for candidate in candidates:
        score = matcher(expected, candidate)
        if score > best_score:
            best_score = score
            best_text = candidate
    return round(best_score, 6), best_text


def memoized(matcher: Matcher) -> Matcher:
    """Cache a matcher over `(expected, candidate)`.

    A trajectory re-scores the same claim text at every later checkpoint (canonical is
    forward-only, so most claims persist), which makes the same pair recur O(rounds) times.
    Caching is safe because a matcher is required to be pure — and it is what keeps a
    12-round × 120-truth evaluation from re-deriving the same similarity 12 times.
    """
    cache: dict[tuple[str, str], float] = {}

    def scored(expected: str, candidate: str) -> float:
        key = (expected, candidate)
        if key not in cache:
            cache[key] = matcher(expected, candidate)
        return cache[key]

    return scored


def _shingles(normalized: str) -> frozenset[str]:
    if len(normalized) <= _SHINGLE:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(
        normalized[i : i + _SHINGLE] for i in range(len(normalized) - _SHINGLE + 1)
    )


def near_duplicate_pairs(
    texts: Mapping[str, str],
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    matcher: Matcher = char_similarity,
) -> list[tuple[str, str, float]]:
    """Keyed texts that say the same thing twice, as sorted `(key_a, key_b, score)` triples.

    Candidate pairs are blocked by shared normalized shingles first. That is a correctness
    shortcut rather than an approximation: below the threshold two texts cannot share any
    8-character run, so no qualifying pair is skipped, and the comparison stays feasible on
    a KB with thousands of claims.

    NOTE on what "duplicate" means here. The shared matcher scores CONTAINMENT as 1.0 (a
    normalized string of six or more characters found inside another). That is deliberate in
    the matcher — "was this statement admitted" must not depend on surrounding prose — and it
    means a short claim lifted out of a longer one counts as a duplicate pair. It is a real
    redundancy signal, but reading a cluster always requires looking at the pair, so every
    reported cluster carries its members.
    """
    normalized = {key: normalize_text(text) for key, text in texts.items()}
    buckets: dict[str, list[str]] = {}
    for key, text in normalized.items():
        for shingle in _shingles(text):
            buckets.setdefault(shingle, []).append(key)
    candidates: set[tuple[str, str]] = set()
    for keys in buckets.values():
        if len(keys) < 2:
            continue
        ordered = sorted(keys)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                candidates.add((left, right))
    pairs: list[tuple[str, str, float]] = []
    for left, right in sorted(candidates):
        score = matcher(texts[left], texts[right])
        if score >= threshold:
            pairs.append((left, right, round(score, 6)))
    return pairs


def cluster(pairs: Sequence[tuple[str, str, float]]) -> list[list[str]]:
    """Connected components over duplicate pairs — one component = one repeated statement."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for left, right, _ in pairs:
        a, b = find(left), find(right)
        if a != b:
            parent[a] = b
    groups: dict[str, list[str]] = {}
    for key in sorted(parent):
        groups.setdefault(find(key), []).append(key)
    return [sorted(members) for _, members in sorted(groups.items())]


__all__ = [
    "Matcher",
    "NEAR_DUPLICATE_THRESHOLD",
    "best_match",
    "char_similarity",
    "cluster",
    "log_log_slope",
    "mean",
    "memoized",
    "near_duplicate_pairs",
    "normalize_text",
    "rate",
    "shannon_entropy",
    "unavailable",
]
