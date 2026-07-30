"""Group B — admission: was the right material let in, and did that judgement hold?

This is the one group that needs a labelled corpus, because "should this have been
admitted?" is not decidable from the artifact alone. The scoring machinery — normalized
character matching, the truth/negative thresholds, the guarded-statement vocabulary, the
supersession rule — is IMPORTED from `experiments.opc_84d_evaluation`, the evaluator that
already reports these numbers on a live stack. Re-implementing it would produce a second
definition of recall that drifts from the first.

What this module adds is the TRAJECTORY axis. The existing evaluator reports admission at
HEAD; that cannot distinguish a knowledge base that has been right since round 3 from one
that only became right on round 12, nor can it see judgement DEGRADING as the KB grows
(the interesting failure: a fact admitted in round 4 that later rounds bury or rewrite past
recognition). So recall, noise exclusion and supersession correctness are all reported per
checkpoint, plus admission latency in rounds.

Two complementary admission questions are asked about noise, because they fail differently.
`noise_exclusion` asks whether the corpus's hand-written negative-control STATEMENTS were
admitted — precise, but only as broad as the list someone thought to write. `noise_support`
goes the other way: for every claim actually in canonical, what was its evidence labelled as
before compilation? A corpus that classes each authored block signal / noise / ambiguous has
orders of magnitude more admission signal there, and it catches over-admission of material
nobody thought to forbid.

Group B is `unavailable` — never zero — when no truth set is bound to the trajectory. A
truth set from a different corpus would score ~0 and read as a catastrophic quality
finding when it is really a mismatched input.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pneuma_knowledge_service.experiments.opc_84d_evaluation import (
    NEGATIVE_THRESHOLD,
    TRUTH_THRESHOLD,
    guarded_statement,
    normalize_text,
)

from ..artifacts import Trajectory
from ..truth import TRUTH_CATEGORIES, TruthSet
from .common import Matcher, best_match, char_similarity, memoized, rate, unavailable


def _claim_texts(trajectory: Trajectory) -> list[list[str]]:
    return [[claim.text for claim in cp.claims] for cp in trajectory.checkpoints]


def _by_category(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for category in TRUTH_CATEGORIES:
        subset = [row for row in rows if row["category"] == category]
        matched = sum(row["matched"] for row in subset)
        out[category] = {
            "matched": matched,
            "total": len(subset),
            "recall": rate(matched, len(subset)),
        }
    return out


def truth_recall_series(
    trajectory: Trajectory,
    truth: TruthSet,
    *,
    matcher: Matcher = char_similarity,
    threshold: float = TRUTH_THRESHOLD,
) -> dict[str, Any]:
    """Recall of the currently-true statements, per checkpoint.

    `peak_recall` vs `head_recall` is the degradation signal: a peak above the head value
    means the structure once expressed a fact and later stopped expressing it recognizably —
    exactly the failure a HEAD-only evaluation cannot see.
    """
    scored = memoized(matcher)
    entries = truth.current_entries()
    texts = _claim_texts(trajectory)
    series: list[dict[str, Any]] = []
    per_entry_first_match: dict[str, int | None] = {entry.truth_id: None for entry in entries}
    head_rows: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(trajectory.checkpoints):
        rows: list[dict[str, Any]] = []
        for entry in entries:
            score, text = best_match(entry.value, texts[index], matcher=scored)
            matched = score >= threshold
            if matched and per_entry_first_match[entry.truth_id] is None:
                per_entry_first_match[entry.truth_id] = index
            rows.append(
                {
                    "truth_id": entry.truth_id,
                    "category": entry.category,
                    "matched": matched,
                    "score": score,
                    "best_text": text,
                }
            )
        matched_total = sum(row["matched"] for row in rows)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "claims_total": len(texts[index]),
                "matched": matched_total,
                "total": len(rows),
                "recall": rate(matched_total, len(rows)),
                "by_category": _by_category(rows),
            }
        )
        head_rows = rows
    recalls = [row["recall"] for row in series if row["recall"] is not None]
    return {
        "status": "ok",
        "threshold": threshold,
        "series": series,
        "head_recall": series[-1]["recall"],
        "peak_recall": max(recalls) if recalls else None,
        "degraded_from_peak": (
            round(max(recalls) - series[-1]["recall"], 6)
            if recalls and series[-1]["recall"] is not None
            else None
        ),
        "first_match_round": {
            truth_id: (None if index is None else trajectory.checkpoints[index].label)
            for truth_id, index in sorted(per_entry_first_match.items())
        },
        "misses_at_head": [row for row in head_rows if not row["matched"]][:30],
    }


def noise_exclusion(
    trajectory: Trajectory,
    truth: TruthSet,
    *,
    matcher: Matcher = char_similarity,
    threshold: float = NEGATIVE_THRESHOLD,
) -> dict[str, Any]:
    """Labelled exhaust must not enter canonical — or must enter explicitly guarded.

    A guarded mention ("the rejected idea was X") is a legitimate compile output: canonical
    is allowed to record that something was considered and dropped. An UNGUARDED match is
    the leak, so the two are counted separately rather than lumped into one error rate.
    """
    scored = memoized(matcher)
    texts = _claim_texts(trajectory)
    series: list[dict[str, Any]] = []
    head_rows: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(trajectory.checkpoints):
        rows: list[dict[str, Any]] = []
        for negative in truth.negatives:
            score, text = best_match(negative.value, texts[index], matcher=scored)
            found = score >= threshold
            guarded = found and guarded_statement(str(text or ""))
            rows.append(
                {
                    "truth_id": negative.truth_id,
                    "found": found,
                    "guarded": guarded,
                    "unguarded_leak": found and not guarded,
                    "score": score,
                    "best_text": text,
                }
            )
        leaks = sum(row["unguarded_leak"] for row in rows)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "unguarded_leaks": leaks,
                "guarded_mentions": sum(row["guarded"] for row in rows),
                "total": len(rows),
                "leak_rate": rate(leaks, len(rows)),
            }
        )
        head_rows = rows
    return {
        "status": "ok",
        "threshold": threshold,
        "series": series,
        "head": series[-1],
        "leaks_at_head": [row for row in head_rows if row["unguarded_leak"]],
        "invariants": {
            "no_unguarded_leak_at_head": series[-1]["unguarded_leaks"] == 0,
            "no_unguarded_leak_ever": all(row["unguarded_leaks"] == 0 for row in series),
        },
    }


def admission_latency(
    trajectory: Trajectory,
    truth: TruthSet,
    *,
    matcher: Matcher = char_similarity,
    threshold: float = TRUTH_THRESHOLD,
) -> dict[str, Any]:
    """How many compile rounds a fact takes to become expressible in canonical.

    Measured in rounds, not wall clock: the corpus intake batch a fact becomes effective in
    is the earliest round that COULD have admitted it, so `lag = first_matching_round -
    effective_batch`. A lag of 0 means the round that saw the material admitted it.

    Requires the corpus to declare intake windows AND those windows to line up 1:1 with the
    checkpoints. When they do not, the raw first-match round is still reported and the lag is
    explicitly `unmeasurable` — a lag against a mismatched round axis would be a made-up
    number.
    """
    if not truth.batches:
        return unavailable(
            "corpus declares no intake batch windows: latency has no round axis",
            first_match_round=None,
        )
    aligned = len(truth.batches) == len(trajectory.checkpoints)
    scored = memoized(matcher)
    texts = _claim_texts(trajectory)
    rows: list[dict[str, Any]] = []
    for entry in truth.current_entries():
        effective_batch = truth.batch_index_for(entry.effective_at)
        first_match: int | None = None
        for index in range(len(trajectory.checkpoints)):
            score, _ = best_match(entry.value, texts[index], matcher=scored)
            if score >= threshold:
                first_match = index
                break
        lag = (
            first_match - effective_batch
            if aligned and first_match is not None and effective_batch is not None
            else None
        )
        rows.append(
            {
                "truth_id": entry.truth_id,
                "category": entry.category,
                "effective_batch": (
                    truth.batches[effective_batch].batch_id
                    if effective_batch is not None
                    else None
                ),
                "first_match_round": (
                    trajectory.checkpoints[first_match].label if first_match is not None else None
                ),
                "lag_rounds": lag,
            }
        )
    lags = [row["lag_rounds"] for row in rows if row["lag_rounds"] is not None]
    return {
        "status": "ok",
        "round_axis_aligned": aligned,
        "measured": len(lags),
        "total": len(rows),
        # A label category may carry no admissibility date at all (a commitment's manifest
        # row records when it is DUE, which is not when it became compilable). Those are
        # excluded from the lag statistics and counted here rather than dated by proxy.
        "effective_date_unknown": sum(1 for row in rows if row["effective_batch"] is None),
        "never_admitted": sum(1 for row in rows if row["first_match_round"] is None),
        "lag_rounds_mean": round(sum(lags) / len(lags), 6) if lags else None,
        "lag_rounds_max": max(lags) if lags else None,
        "same_round_admissions": sum(1 for lag in lags if lag == 0),
        "details": rows,
    }


def supersession_correctness(
    trajectory: Trajectory,
    truth: TruthSet,
    *,
    matcher: Matcher = char_similarity,
    threshold: float = TRUTH_THRESHOLD,
) -> dict[str, Any]:
    """Did a replacement land, and did the replaced statement stop standing as current?

    The rule is the existing evaluator's, unchanged: correct iff the AFTER statement is
    present and the BEFORE statement is either absent or explicitly guarded. Reported per
    checkpoint so a late correction is visible as a late correction.
    """
    if not truth.supersessions:
        return unavailable("corpus declares no supersessions")
    scored = memoized(matcher)
    by_id = truth.by_id()
    texts = _claim_texts(trajectory)
    series: list[dict[str, Any]] = []
    head_rows: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(trajectory.checkpoints):
        rows: list[dict[str, Any]] = []
        for supersession in truth.supersessions:
            before = by_id[supersession.before_truth_id]
            after = by_id[supersession.after_truth_id]
            before_score, before_text = best_match(before.value, texts[index], matcher=scored)
            after_score, _ = best_match(after.value, texts[index], matcher=scored)
            before_found = before_score >= threshold
            before_guarded = before_found and guarded_statement(str(before_text or ""))
            after_found = after_score >= threshold
            rows.append(
                {
                    "supersession_id": supersession.supersession_id,
                    "before_found": before_found,
                    "before_guarded": before_guarded,
                    "after_found": after_found,
                    "correct": after_found and (not before_found or before_guarded),
                }
            )
        correct = sum(row["correct"] for row in rows)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "correct": correct,
                "total": len(rows),
                "accuracy": rate(correct, len(rows)),
            }
        )
        head_rows = rows
    return {
        "status": "ok",
        "series": series,
        "head": series[-1],
        "incorrect_at_head": [row for row in head_rows if not row["correct"]],
    }


def noise_support(trajectory: Trajectory, truth: TruthSet | None) -> dict[str, Any]:
    """How much of canonical rests entirely on material the corpus labelled as exhaust.

    The complement of `noise_exclusion`, and a far larger measurement. `noise_exclusion` asks
    whether a handful of hand-written negative-control STATEMENTS were admitted; this asks, of
    every claim actually in canonical, what its evidence was labelled as before compilation. A
    corpus that labels every authored block signal / noise / ambiguous has orders of magnitude
    more admission signal in those labels than in its negative-control list, and it catches the
    failure the negative controls structurally cannot see: material that is genuinely low-value
    and that nobody thought to write down as a forbidden statement.

    Resolution runs claim → citations → ¶ blocks → label, so it inherits the citation layer's own
    addressing; a claim whose citations do not resolve is excluded from the denominator rather
    than assumed clean. A ¶ block whose text matches no authored label is counted as `unmatched`
    and likewise never treated as signal — the reformatting gap between authoring and ingest is
    reported, not silently resolved in the compiler's favour.

    `noise_only` is the headline: at least one noise-labelled cited block, and every other cited
    block also noise-labelled. A claim that threads a noise block together with real evidence is
    doing its job; a claim whose entire basis is exhaust is an admission error. An `unmatched`
    block disqualifies a claim from `noise_only` rather than counting toward it — "we could not
    find this block's label" is not evidence that the block was exhaust, and letting it stand in
    for one would inflate the very number this metric exists to report. Those claims are counted
    separately as `claims_with_unknown_support`.
    """
    if truth is None or not truth.content_classes:
        return unavailable(
            "corpus declares no authorship.content_class labels: admission over-inclusion is "
            "only measurable against material labelled before compilation"
        )
    if not trajectory.has_l0:
        return unavailable(
            "trajectory carries no L0 sources: cited ¶ blocks cannot be resolved to labels"
        )
    labels = dict(truth.content_classes)
    # Longest-first so a containment fallback prefers the most specific authored text. Ingest may
    # wrap an authored block in surrounding structure, which defeats an exact match.
    ordered = sorted(labels, key=len, reverse=True)

    block_class: dict[tuple[str, int], str] = {}

    def classify(source_id: str, index: int, text: str) -> str:
        key = (source_id, index)
        cached = block_class.get(key)
        if cached is not None:
            return cached
        normalized = normalize_text(text)
        found = labels.get(normalized)
        if found is None:
            for candidate in ordered:
                if candidate and candidate in normalized:
                    found = labels[candidate]
                    break
        block_class[key] = found or "unmatched"
        return block_class[key]

    series: list[dict[str, Any]] = []
    head_offenders: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        judged = 0
        noise_only = 0
        any_noise = 0
        unknown_support = 0
        totals: Counter[str] = Counter()
        offenders: list[dict[str, Any]] = []
        for claim in checkpoint.claims:
            seen: Counter[str] = Counter()
            for citation in claim.citations:
                record = trajectory.sources.get(str(citation.source_id))
                if record is None:
                    continue
                start = max(citation.block_start, 0)
                end = min(citation.block_end, record.block_count - 1)
                for index in range(start, end + 1):
                    seen[classify(str(citation.source_id), index, record.blocks[index])] += 1
            if not seen:
                continue
            judged += 1
            totals.update(seen)
            if seen["unmatched"]:
                unknown_support += 1
            if seen["noise"]:
                any_noise += 1
                if not (seen["signal"] or seen["ambiguous"] or seen["unmatched"]):
                    noise_only += 1
                    offenders.append(
                        {
                            "anchor": str(claim.anchor),
                            "document_path": claim.document_path,
                            "cited_block_classes": dict(seen),
                        }
                    )
        series.append(
            {
                "checkpoint": checkpoint.label,
                "claims_judged": judged,
                "claims_total": len(checkpoint.claims),
                "claims_citing_any_noise": any_noise,
                "claims_noise_only": noise_only,
                "claims_with_unknown_support": unknown_support,
                "noise_only_rate": rate(noise_only, judged),
                "cited_block_classes": dict(totals),
            }
        )
        head_offenders = offenders
    return {
        "status": "ok",
        "labelled_texts": len(labels),
        "series": series,
        "head": series[-1] if series else None,
        "noise_only_claims_at_head": head_offenders[:30],
        "documents_at_head": dict(
            Counter(row["document_path"] for row in head_offenders)
        ),
        "invariants": {
            "no_noise_only_claim_at_head": bool(series) and series[-1]["claims_noise_only"] == 0
        },
    }


def admission_metrics(
    trajectory: Trajectory,
    truth: TruthSet | None,
    *,
    matcher: Matcher = char_similarity,
) -> dict[str, Any]:
    """Group B entry point. `unavailable` when no truth set is bound to this trajectory."""
    if truth is None:
        return {
            "group": "B_admission",
            **unavailable(
                "no truth set is bound to this trajectory: admission judgement is only "
                "measurable against a corpus whose facts, exhaust and supersessions were "
                "labelled before compilation"
            ),
        }
    return {
        "group": "B_admission",
        "truth_set": {
            "experiment_id": truth.experiment_id,
            "corpus_key": truth.corpus_key,
            "entries": len(truth.entries),
            "current_entries": len(truth.current_entries()),
            "negatives": len(truth.negatives),
            "supersessions": len(truth.supersessions),
            "batches": len(truth.batches),
            "origin": dict(truth.origin),
        },
        "recall": truth_recall_series(trajectory, truth, matcher=matcher),
        "noise_exclusion": noise_exclusion(trajectory, truth, matcher=matcher),
        "noise_support": noise_support(trajectory, truth),
        "latency": admission_latency(trajectory, truth, matcher=matcher),
        "supersessions": supersession_correctness(trajectory, truth, matcher=matcher),
    }


__all__ = [
    "admission_latency",
    "admission_metrics",
    "noise_exclusion",
    "noise_support",
    "supersession_correctness",
    "truth_recall_series",
]
