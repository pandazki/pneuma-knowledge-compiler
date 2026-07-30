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
- LANGUAGE CONSISTENCY: are the claims written in the language the knowledge base is DECLARED
  to be in — the subject's own language setting, defaulting to English when nothing is set?
  This used to be measured against the language of the material, which was the wrong target:
  the material of one knowledge base is routinely multilingual, so "consistent with the
  material" has no single answer, and a base whose subject reads Chinese is not improved by
  claims that follow whichever language each source happened to arrive in. The declared
  language is a setting, so it is a target a compile can be held to. The material's own script
  is still reported beside it, as context for reading the number.
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
#: "is the thread layer written in the writing system the subject reads", which is exactly the
#: failure a script test catches and a finer language ID would only blur.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿　-〿＀-￯]")
_LATIN_RE = re.compile(r"[A-Za-z]")

#: The language a knowledge base is assumed to be written in when no declaration reaches the
#: evaluator. It mirrors the framework's own default (prompts `compile.owner_env.language_unknown`):
#: a subject with no language setting gets English, so English is what the compile is held to.
DEFAULT_DECLARED_LANGUAGE = "en"

#: BCP-47 primary subtags whose writing system is CJK. Coarse on purpose, exactly like `_script_of`:
#: the check distinguishes writing systems, not languages, so only the split it can actually
#: measure is encoded here.
_CJK_LANGUAGE_TAGS = frozenset({"zh", "ja", "ko", "yue", "cmn", "wuu", "nan", "hak"})


def script_of_language(tag: str | None) -> str:
    """A BCP-47 tag → the script this check measures in (`cjk` / `latin`).

    Unknown or empty tags fall back to the default declared language rather than to "anything
    goes": a missing declaration is a known state with a known consequence (English), and
    treating it as unmeasurable would quietly drop the metric on exactly the bases that need it.
    """
    primary = str(tag or DEFAULT_DECLARED_LANGUAGE).strip().lower().replace("_", "-")
    primary = primary.split("-", 1)[0]
    return "cjk" if primary in _CJK_LANGUAGE_TAGS else "latin"


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


def _material_script(trajectory: Trajectory) -> tuple[str | None, dict[str, int]]:
    """The dominant script of the L0 blocks, as REFERENCE only (never the target).

    Kept because it is what makes a divergence readable — "claims in Latin over Chinese
    material" is a different diagnosis from "claims in Latin over Latin material that the
    subject cannot read" — but it no longer decides anything.
    """
    counts = Counter(
        _script_of(block)
        for record in trajectory.sources.values()
        for block in record.blocks
        if block.strip()
    )
    ranked = [
        script
        for script, _ in counts.most_common()
        if script not in {"neither", "mixed"}
    ]
    return (ranked[0] if ranked else None), dict(counts)


def language_consistency(
    trajectory: Trajectory, *, declared_language: str | None = None
) -> dict[str, Any]:
    """Are canonical's claims written in the language the base is DECLARED to be in?

    A layering question, not a cosmetic one. The knowledge base belongs to one subject who
    reads one language, declared in their profile (`locale.language`, defaulting to English
    when unset), and the compile contract now states that language and requires every claim to
    be written in it. A claim in another language is unreadable to the only person the layer
    exists for, and it silently breaks every character-level measurement downstream: a truth
    label or a duplicate in one script can never match a claim in the other, so admission
    recall and duplication both under-report on exactly the claims that drifted.

    The target is the DECLARATION, not the material. Measuring against the material was the
    earlier reading and it does not survive contact with a real corpus: one base's sources are
    routinely in several languages, so "the corpus language" is an artifact of whichever
    language happened to dominate, and a compile cannot be held to it. The material's own
    script is still reported (`material_script`) as context.

    Available with or without L0 — the declared language is known either way, which is the
    point of declaring it.
    """
    declared = (declared_language or "").strip() or DEFAULT_DECLARED_LANGUAGE
    declared_script = script_of_language(declared)
    material_script, material_counts = _material_script(trajectory)
    series: list[dict[str, Any]] = []
    head_samples: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        counts: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        for claim in checkpoint.claims:
            script = _script_of(claim.text)
            counts[script] += 1
            if script not in {declared_script, "mixed", "neither"}:
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
                # Field names carry the new basis: an old scorecard's `consistent` was
                # measured against the material and must not be compared with this.
                "in_declared_language": counts[declared_script],
                "diverged_from_declared": total
                - counts[declared_script]
                - counts["mixed"],
                "mixed": counts["mixed"],
                "declared_language_rate": rate(counts[declared_script], total),
                "by_script": dict(counts),
            }
        )
        head_samples = samples
    return {
        "status": "ok",
        "declared_language": declared,
        "declared_script": declared_script,
        "declared_language_source": "argument" if declared_language else "default",
        # Reference only — what the material happened to be written in.
        "material_script": material_script,
        "material_block_scripts": material_counts,
        "series": series,
        "head": series[-1] if series else None,
        "diverged_claims_at_head": head_samples[:30],
        "documents_at_head": dict(
            Counter(row["document_path"] for row in head_samples)
        ),
        "invariants": {
            "head_fully_in_declared_language": bool(series)
            and series[-1]["declared_language_rate"] in (None, 1.0)
        },
    }


def layering_metrics(
    trajectory: Trajectory,
    truth: TruthSet | None = None,
    *,
    matcher: Matcher = char_similarity,
    declared_language: str | None = None,
) -> dict[str, Any]:
    """Group C entry point: compression, duplication, verbatim, detail leakage, language.

    `declared_language` is the subject's own language setting (`UserProfile.locale.language`)
    threaded from the evaluation entry point; omitted, the framework default (English) is what
    the compile is held to — same rule the compile contract states to the model.
    """
    return {
        "group": "C_layering",
        "compression": compression(trajectory),
        "duplication": duplication(trajectory, matcher=matcher),
        "verbatim_reproduction": verbatim_reproduction(trajectory),
        "detail_leakage": detail_leakage(trajectory, truth, matcher=matcher),
        "language_consistency": language_consistency(
            trajectory, declared_language=declared_language
        ),
    }


__all__ = [
    "DEFAULT_DECLARED_LANGUAGE",
    "VERBATIM_RUN_CHARS",
    "compression",
    "detail_leakage",
    "duplication",
    "language_consistency",
    "layering_metrics",
    "script_of_language",
    "verbatim_reproduction",
]
