"""Group C — layering: is canonical the thread layer, or a second copy of the raw material?

The write contract is explicit that canonical is "the layer of threads and indexes, not a
full-text store": no detail is lost by leaving it out, because L0 is never rewritten and
L1/L2 index it. That makes over-inclusion a real defect and not a harmless surplus — a
canonical that reproduces the material is a bigger, slower, redundant L0 with a citation
attached, and it destroys the bird's-eye job that justifies the layer existing.

Three mechanical signals, none of which needs a label:

- COMPRESSION: canonical body characters over consumed L0 characters. Should be low, and
  should stay flat or fall as the corpus grows (a constant ratio means the compiler is
  transcribing at a fixed rate rather than threading).
- DUPLICATION: the same statement written twice, especially across documents — a direct
  violation of subject uniqueness, and the thing that makes a KB feel like it is arguing
  with itself.
- VERBATIM REPRODUCTION: the longest literal run shared between a claim and the source
  blocks it cites. A thread paraphrases and attributes; a transcript copies. This is the
  label-free half of "detail leakage" — the labelled half needs negative controls and is
  reported separately when a truth set is bound.
- LANGUAGE CONSISTENCY: do the claims stay in the language of the material they compile? A
  claim written in another language is a translation presented as a thread, so the reader can
  no longer tell which words were the speaker's — and it silently breaks every character-level
  measurement downstream, because a label or a duplicate in one script cannot match a claim in
  the other.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from ..artifacts import Trajectory
from ..truth import TruthSet
from .common import (
    NEAR_DUPLICATE_THRESHOLD,
    Matcher,
    best_match,
    char_similarity,
    cluster,
    memoized,
    near_duplicate_pairs,
    normalize_text,
    rate,
    unavailable,
)

#: A literal run this long, shared between a claim and its cited blocks, is transcription
#: rather than paraphrase. Chosen well above incidental overlap (names, dates, boilerplate
#: openings) and well below whole-sentence length in the corpora at hand.
VERBATIM_RUN_CHARS = 40


def compression(trajectory: Trajectory) -> dict[str, Any]:
    """Canonical body characters against the L0 characters actually consumed, per checkpoint."""
    if not trajectory.has_l0:
        return unavailable("trajectory carries no L0 sources: compression has no denominator")
    series: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(trajectory.checkpoints):
        l0_chars = trajectory.l0_chars_through(index)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "canonical_chars": checkpoint.canonical_chars,
                "prose_chars": checkpoint.prose_chars,
                "l0_chars": l0_chars,
                # The headline ratio excludes citation/anchor markup: that overhead is the
                # provenance backbone, not verbosity. The raw ratio is kept beside it.
                "compression_ratio": rate(checkpoint.prose_chars, l0_chars or 0),
                "raw_compression_ratio": rate(checkpoint.canonical_chars, l0_chars or 0),
                "markup_chars": checkpoint.canonical_chars - checkpoint.prose_chars,
                "claims_total": len(checkpoint.claims),
                "chars_per_claim": rate(checkpoint.prose_chars, len(checkpoint.claims)),
            }
        )
    ratios = [row["compression_ratio"] for row in series if row["compression_ratio"] is not None]
    if not ratios:
        return unavailable(
            "no checkpoint declares which sources it consumed: compression has no denominator",
            series=series,
        )
    return {
        "status": "ok",
        "series": series,
        "head_ratio": ratios[-1],
        "min_ratio": min(ratios),
        "max_ratio": max(ratios),
        "trend": round(ratios[-1] - ratios[0], 6),
    }


def _claim_key(claim: Any) -> str:
    return f"{claim.document_path}#{claim.anchor}"


def duplication(
    trajectory: Trajectory,
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    matcher: Matcher = char_similarity,
) -> dict[str, Any]:
    """Repeated statements per checkpoint, split by whether the repetition crosses documents.

    Within one document a near-duplicate is usually a revision artifact; ACROSS documents it
    is a subject-uniqueness violation — two documents both claiming to own the same fact —
    which is the failure that makes a reader distrust the structure.
    """
    scored = memoized(matcher)
    series: list[dict[str, Any]] = []
    head_clusters: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        claims = checkpoint.claims
        texts = {_claim_key(claim): claim.text for claim in claims}
        exact: dict[str, list[str]] = {}
        for claim in claims:
            normalized = normalize_text(claim.text)
            if normalized:
                exact.setdefault(normalized, []).append(_claim_key(claim))
        exact_groups = [keys for keys in exact.values() if len(keys) > 1]
        pairs = near_duplicate_pairs(texts, threshold=threshold, matcher=scored)
        groups = cluster(pairs)
        cross_document = [
            members
            for members in groups
            if len({member.split("#", 1)[0] for member in members}) > 1
        ]
        excess = sum(len(members) - 1 for members in groups)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "claims_total": len(claims),
                "exact_duplicate_groups": len(exact_groups),
                "exact_duplicate_excess": sum(len(keys) - 1 for keys in exact_groups),
                "near_duplicate_groups": len(groups),
                "near_duplicate_excess": excess,
                "cross_document_groups": len(cross_document),
                "duplicate_row_rate": rate(excess, len(claims)),
            }
        )
        head_clusters = [
            {"members": members, "text": texts[members[0]]} for members in groups[:20]
        ]
    return {
        "status": "ok",
        "threshold": threshold,
        "series": series,
        "head": series[-1],
        "head_clusters": head_clusters,
        "invariants": {
            "no_exact_duplicates_at_head": series[-1]["exact_duplicate_groups"] == 0,
            "no_cross_document_duplicates_at_head": series[-1]["cross_document_groups"] == 0,
        },
    }


def _longest_shared_run(left: str, right: str) -> int:
    if not left or not right:
        return 0
    return SequenceMatcher(a=left, b=right, autojunk=False).find_longest_match(
        0, len(left), 0, len(right)
    ).size


def verbatim_reproduction(
    trajectory: Trajectory, *, min_run: int = VERBATIM_RUN_CHARS
) -> dict[str, Any]:
    """Longest literal run shared between each claim and the source blocks it cites.

    Compared on NORMALIZED text (punctuation and case folded away) so that reformatting
    cannot hide a copy. Only claims with a resolvable citation can be judged; the count of
    judgeable claims is reported alongside, because a rate over an unstated subset is not a
    measurement.
    """
    if not trajectory.has_l0:
        return unavailable("trajectory carries no L0 sources: nothing to compare claims against")
    series: list[dict[str, Any]] = []
    head_samples: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        judged = 0
        transcribed = 0
        runs: list[int] = []
        samples: list[dict[str, Any]] = []
        for claim in checkpoint.claims:
            support: list[str] = []
            for citation in claim.citations:
                record = trajectory.sources.get(str(citation.source_id))
                if record is None:
                    continue
                start = max(citation.block_start, 0)
                end = min(citation.block_end, record.block_count - 1)
                if start > end:
                    continue
                support.extend(record.blocks[start : end + 1])
            if not support:
                continue
            judged += 1
            claim_text = normalize_text(claim.text)
            run = max(
                (_longest_shared_run(claim_text, normalize_text(block)) for block in support),
                default=0,
            )
            runs.append(run)
            if run >= min_run:
                transcribed += 1
                if len(samples) < 10:
                    samples.append(
                        {
                            "document_path": claim.document_path,
                            "anchor": str(claim.anchor),
                            "longest_run": run,
                            "claim_chars": len(claim.text),
                        }
                    )
        series.append(
            {
                "checkpoint": checkpoint.label,
                "claims_judged": judged,
                "claims_total": len(checkpoint.claims),
                "transcribed": transcribed,
                "transcription_rate": rate(transcribed, judged),
                "longest_run_max": max(runs) if runs else None,
                "longest_run_mean": round(sum(runs) / len(runs), 3) if runs else None,
            }
        )
        head_samples = samples
    return {
        "status": "ok",
        "min_run_chars": min_run,
        "series": series,
        "head": series[-1],
        "head_samples": head_samples,
    }


def detail_leakage(
    trajectory: Trajectory,
    truth: TruthSet | None,
    *,
    matcher: Matcher = char_similarity,
    threshold: float = 0.78,
) -> dict[str, Any]:
    """The labelled half of detail leakage: negative controls surfacing in canonical.

    Shares the corpus's negative controls with group B but asks a different question: group B
    asks whether exhaust was ADMITTED as fact, this asks how much labelled detail reached the
    thread layer at all. Unavailable without a bound truth set.
    """
    if truth is None or not truth.negatives:
        return unavailable("no labelled detail negatives are bound to this trajectory")
    scored = memoized(matcher)
    series: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        texts = [claim.text for claim in checkpoint.claims]
        present = 0
        for negative in truth.negatives:
            score, _ = best_match(negative.value, texts, matcher=scored)
            present += int(score >= threshold)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "present": present,
                "total": len(truth.negatives),
                "leak_rate": rate(present, len(truth.negatives)),
            }
        )
    return {"status": "ok", "threshold": threshold, "series": series, "head": series[-1]}


#: Scripts distinguished for the language-consistency check. Deliberately coarse: the question is
#: "did the thread layer switch writing system away from its evidence", which is exactly the
#: failure a script test catches and a finer language ID would only blur.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿　-〿＀-￯]")
_LATIN_RE = re.compile(r"[A-Za-z]")

#: A claim needs this many letters of the minority script before it counts as genuinely mixed
#: rather than as a stray loan word, product name or date fragment.
_MIXED_FLOOR_LATIN = 12
_MIXED_FLOOR_CJK = 8


def _script_of(text: str) -> str:
    """`cjk` / `latin` / `mixed` / `neither` for one stretch of prose."""
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if not cjk and not latin:
        return "neither"
    if cjk >= _MIXED_FLOOR_CJK and latin >= _MIXED_FLOOR_LATIN:
        return "mixed"
    # One CJK character carries roughly a Latin word, so compare on a deliberately generous
    # ratio rather than raw counts.
    return "cjk" if cjk >= latin / 3 else "latin"


def language_consistency(trajectory: Trajectory) -> dict[str, Any]:
    """Do canonical's claims stay in the language of the material they compile?

    A layering question, not a cosmetic one. Canonical is the thread layer over evidence that is
    never rewritten, and the contract requires exact wording to be kept apart from
    interpretation — so a claim written in a different language from its source is a translation
    presented as a thread, and the reader cannot tell which words were the speaker's. It also
    silently breaks every character-level measurement downstream: a truth label or a duplicate
    in one script can never match a claim in the other, so admission recall and duplication both
    under-report on exactly the claims that drifted.

    The corpus language is taken from the L0 blocks rather than assumed, and the metric reports
    the share of claims that match it per checkpoint. Unavailable without L0, because "consistent
    with what?" has no answer then.
    """
    if not trajectory.has_l0:
        return unavailable(
            "trajectory carries no L0 sources: there is no corpus language to be consistent with"
        )
    corpus_counts = Counter(
        _script_of(block)
        for record in trajectory.sources.values()
        for block in record.blocks
        if block.strip()
    )
    ranked = [
        (script, count)
        for script, count in corpus_counts.most_common()
        if script not in {"neither", "mixed"}
    ]
    if not ranked:
        return unavailable("L0 carries no script this check can identify")
    corpus_script = ranked[0][0]
    series: list[dict[str, Any]] = []
    head_samples: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        counts: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        for claim in checkpoint.claims:
            script = _script_of(claim.text)
            counts[script] += 1
            if script not in {corpus_script, "mixed", "neither"}:
                samples.append(
                    {
                        "anchor": str(claim.anchor),
                        "document_path": claim.document_path,
                        "script": script,
                        "text": claim.text[:120],
                    }
                )
        total = sum(counts.values())
        series.append(
            {
                "checkpoint": checkpoint.label,
                "claims_total": total,
                "consistent": counts[corpus_script],
                "diverged": total - counts[corpus_script] - counts["mixed"],
                "mixed": counts["mixed"],
                "consistency_rate": rate(counts[corpus_script], total),
                "by_script": dict(counts),
            }
        )
        head_samples = samples
    return {
        "status": "ok",
        "corpus_script": corpus_script,
        "corpus_block_scripts": dict(corpus_counts),
        "series": series,
        "head": series[-1] if series else None,
        "diverged_claims_at_head": head_samples[:30],
        "documents_at_head": dict(
            Counter(row["document_path"] for row in head_samples)
        ),
        "invariants": {
            "head_fully_consistent": bool(series)
            and series[-1]["consistency_rate"] in (None, 1.0)
        },
    }


def layering_metrics(
    trajectory: Trajectory,
    truth: TruthSet | None = None,
    *,
    matcher: Matcher = char_similarity,
) -> dict[str, Any]:
    """Group C entry point: compression, duplication, verbatim, detail leakage, language."""
    return {
        "group": "C_layering",
        "compression": compression(trajectory),
        "duplication": duplication(trajectory, matcher=matcher),
        "verbatim_reproduction": verbatim_reproduction(trajectory),
        "detail_leakage": detail_leakage(trajectory, truth, matcher=matcher),
        "language_consistency": language_consistency(trajectory),
    }


__all__ = [
    "VERBATIM_RUN_CHARS",
    "compression",
    "detail_leakage",
    "duplication",
    "language_consistency",
    "layering_metrics",
    "verbatim_reproduction",
]
