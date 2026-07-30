"""Scorecard assembly: the six groups over one trajectory, plus a readable rendering.

TWO DELIBERATE ABSENCES
-----------------------
There is no overall score. A weighted sum over six groups would invent a trade-off nobody
decided (is one dead link worth two percent of recall?) and would hide exactly the pattern
this package exists to expose — a structure that is impeccably grounded and completely
unnavigable. The reader gets the six groups.

There is no pass/fail gate either. The scorecard emits `findings`: mechanically derived,
each naming the metric, the observed value and why it matters. A finding is an argument with
evidence attached, which survives a corpus change; a threshold is a number that quietly stops
meaning anything the moment the corpus changes.

The markdown rendering is mechanical too — tables and flagged findings, no interpretation.
Interpretation belongs in a signed evaluation report, where a human can be held to it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .artifacts import Trajectory
from .metrics import (
    admission_metrics,
    evolution_metrics,
    grounded_metrics,
    layering_metrics,
    navigability_metrics,
)
from .metrics.common import L0_ABSENT, Matcher, char_similarity
from .qa import TruthJudge, qa_metrics
from .truth import TruthSet

#: Bumped to v2 when group D's reachability was re-based from the designated hub family to
#: retrieval-hit seeding and gained the glance check (see metrics/navigability.py). The field
#: names under `D_navigability.reachability` changed with the definition, deliberately: a
#: renamed metric makes an old and a new scorecard refuse to be compared, where a silently
#: redefined one would invite exactly that comparison. Artifacts already written under v1 keep
#: their schema string and their old meaning.
SCORECARD_SCHEMA = "pneuma.eval.scorecard/v2"


def build_scorecard(
    trajectory: Trajectory,
    *,
    mode: str = "mechanical",
    truth: TruthSet | None = None,
    matcher: Matcher | None = None,
    generated_at: datetime | None = None,
    qa: dict[str, Any] | None = None,
    declared_language: str | None = None,
    truth_judge: TruthJudge | None = None,
) -> dict[str, Any]:
    """Run all six groups over `trajectory` and assemble a JSON-serializable scorecard.

    `qa` is group F pre-computed by an async caller (`qa.qa_metrics_async`), because asking
    a live recall path a question is the one group that cannot run inside a pure sync
    function. Omitted, F falls back to the synchronous shell — which is a real result for
    mechanical mode and an explicit `unavailable`/raise otherwise, never a fabricated number.

    `declared_language` is the evaluated subject's own language setting (their profile's
    `locale.language`). Group C holds the claims to it; omitted, English — the framework's
    documented default for a subject who declared none.

    `truth_judge` is group B's full-mode entailment arm (`qa.build_truth_judge`). Omitted,
    group B reports its similarity arm and marks the judged arm `unavailable` with its reason;
    it is never silently reported as the same number.
    """
    if mode not in ("mechanical", "full"):
        raise ValueError(f"unknown evaluation mode: {mode!r}")
    matcher = matcher or char_similarity
    groups = {
        "A_grounded": grounded_metrics(trajectory),
        "B_admission": admission_metrics(trajectory, truth, matcher=matcher, judge=truth_judge),
        "C_layering": layering_metrics(
            trajectory, truth, matcher=matcher, declared_language=declared_language
        ),
        "D_navigability": navigability_metrics(trajectory),
        "E_evolution": evolution_metrics(trajectory, matcher=matcher),
        "F_usability_qa": qa if qa is not None else qa_metrics(truth, mode=mode),
    }
    scorecard: dict[str, Any] = {
        "schema": SCORECARD_SCHEMA,
        "mode": mode,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "bundle": {
            "id": trajectory.bundle_id,
            "checkpoints": len(trajectory.checkpoints),
            "documents_at_head": len(trajectory.head.files),
            "claims_at_head": len(trajectory.head.claims),
            "sources": len(trajectory.sources),
            "l0_blocks": sum(record.block_count for record in trajectory.sources.values()),
            "path_templates": list(trajectory.path_templates),
            "origin": dict(trajectory.origin),
        },
        "checkpoints": [
            {
                "label": cp.label,
                "ref": cp.ref[:12],
                "committed_at": cp.committed_at.isoformat() if cp.committed_at else None,
                "job_id": cp.job_id,
                "consumed_sources": list(cp.consumed_source_ids),
                "documents": len(cp.files),
                "claims": len(cp.claims),
                "canonical_chars": cp.canonical_chars,
            }
            for cp in trajectory.checkpoints
        ],
        "groups": groups,
    }
    scorecard["findings"] = findings(scorecard)
    scorecard["unavailable"] = _unavailable(groups)
    return scorecard


def _unavailable(groups: dict[str, Any]) -> list[dict[str, str]]:
    """Every metric that did NOT produce a number, by name, with its reason and its cause.

    This list is the package's answer to silent shortfall: a metric that could not run has to
    say so somewhere a reader and a caller both look, or a scorecard missing five metrics is
    indistinguishable from one that computed them. `cause` is the machine-readable half —
    `l0_absent` on every metric a missing L0 half cost, which is what lets the CLI account for
    them in one line and name the flag that supplies them.
    """
    out: list[dict[str, str]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            status = node.get("status")
            if status in {"unavailable", "skipped", "no_evolution_events", "no_moves_observed"}:
                out.append(
                    {
                        "metric": prefix,
                        "status": str(status),
                        "reason": str(node.get("reason") or ""),
                        "cause": str(node.get("cause") or ""),
                    }
                )
            for key, value in node.items():
                if key in {"series", "cases", "details", "samples"}:
                    continue
                walk(f"{prefix}.{key}" if prefix else str(key), value)

    walk("", groups)
    return out


def unavailable_because(scorecard: dict[str, Any], cause: str) -> list[dict[str, str]]:
    """The `unavailable` entries a single missing input is responsible for.

    The CLI's closing account is built from this: one missing half of the evidence usually
    costs several metrics across several groups, and listing them by name beats leaving the
    reader to notice five nulls in three different sections.
    """
    return [row for row in scorecard.get("unavailable", ()) if row.get("cause") == cause]


# ──────────────────────────────────────────────────────────────────────────── findings


def _finding(metric: str, severity: str, observed: Any, why: str) -> dict[str, Any]:
    return {"metric": metric, "severity": severity, "observed": observed, "why": why}


def findings(scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    """Mechanically derived weaknesses. Each names its metric, its value, and why it matters.

    Only invariants that the system itself asserts are flagged — provenance completeness, the
    monotone floors, subject uniqueness, the navigability claim. Nothing here is a tuned
    threshold masquerading as a standard.
    """
    out: list[dict[str, Any]] = []
    groups = scorecard["groups"]

    citations = groups["A_grounded"]["citations"]
    head = citations["head"]
    if head["claims_total"] and head["claims_with_citations"] < head["claims_total"]:
        out.append(
            _finding(
                "A.citations.claim_coverage",
                "high",
                f"{head['claims_with_citations']}/{head['claims_total']}",
                "an uncited claim is an assertion in the only non-rebuildable layer",
            )
        )
    if head.get("unparsable_marker_residue"):
        out.append(
            _finding(
                "A.citations.unparsable_marker_residue",
                "high",
                head["unparsable_marker_residue"],
                "text that looks like a citation but resolves to nothing is worse than none",
            )
        )
    if citations["l0_available"] and head.get("citations_resolvable") != head["citations_total"]:
        out.append(
            _finding(
                "A.citations.resolvable_rate",
                "high",
                head.get("resolvable_rate"),
                "a locator that cannot be replayed breaks the audit path back to evidence",
            )
        )
    anchors = groups["A_grounded"]["anchors"]
    if not anchors["invariants"]["no_repo_wide_anchor_loss"]:
        out.append(
            _finding(
                "A.anchors.repo_wide_vanished",
                "high",
                sum(row["repo_wide_vanished"] for row in anchors["series"]),
                "a claim identity that disappears takes its history and its citations with it",
            )
        )
    links = groups["A_grounded"]["links"]
    if links["head"]["dead"] or links["head"]["self"]:
        out.append(
            _finding(
                "A.links.dead",
                "medium",
                f"dead={links['head']['dead']} self={links['head']['self']}",
                "a dead edge is a dead end in the graph retrieval falls back on",
            )
        )

    layering = groups["C_layering"]
    duplication = layering["duplication"]
    if duplication["head"]["cross_document_groups"]:
        out.append(
            _finding(
                "C.duplication.cross_document_groups",
                "medium",
                duplication["head"]["cross_document_groups"],
                "two documents claiming the same fact means neither owns the subject",
            )
        )
    verbatim = layering["verbatim_reproduction"]
    if verbatim.get("status") == "ok" and (verbatim["head"]["transcription_rate"] or 0) > 0:
        out.append(
            _finding(
                "C.verbatim_reproduction.transcription_rate",
                "medium",
                verbatim["head"]["transcription_rate"],
                "canonical is the thread layer; a transcript duplicates L0 without adding a thread",
            )
        )
    compression = layering["compression"]
    if compression.get("status") == "ok" and (compression.get("trend") or 0) > 0:
        out.append(
            _finding(
                "C.compression.trend",
                "low",
                compression["trend"],
                "a rising ratio means the compiler transcribes at a fixed rate instead of threading",
            )
        )
    language = layering.get("language_consistency") or {}
    head_language = language.get("head") or {}
    if language.get("status") == "ok" and (head_language.get("diverged_from_declared") or 0) > 0:
        out.append(
            _finding(
                "C.language_consistency.diverged_from_declared",
                "medium",
                f"{head_language['diverged_from_declared']}/{head_language['claims_total']}",
                "a claim written outside the subject's declared language "
                f"({language['declared_language']}) is unreadable to the only reader the layer "
                "exists for, and no character-level metric can match it against its own corpus",
            )
        )

    reach = groups["D_navigability"]["reachability"]
    if not reach["invariants"]["graph_has_edges_at_head"]:
        out.append(
            _finding(
                "D.reachability.edges",
                "high",
                0,
                "with no inter-document links the follow-the-thread job does not exist at all",
            )
        )
    if reach["head"]["dead_end_documents"]:
        out.append(
            _finding(
                "D.reachability.dead_end_documents",
                "medium",
                f"{reach['head']['dead_end_documents']}/{reach['head']['documents']}",
                "landing on one of these by retrieval leaves nowhere to walk: the thread ends "
                "at the hit",
            )
        )
    if reach["head"]["arrival_blind_documents"]:
        out.append(
            _finding(
                "D.reachability.arrival_blind_documents",
                "medium",
                f"{reach['head']['arrival_blind_documents']}/{reach['head']['documents']}",
                "a document nothing links to can only be found by already knowing its name",
            )
        )
    if reach["head"]["isolated_documents"]:
        out.append(
            _finding(
                "D.reachability.isolated_documents",
                "medium",
                reach["head"]["isolated_documents"],
                "an isolated document is retrievable but not browsable",
            )
        )
    glance = groups["D_navigability"].get("glance") or {}
    if glance.get("status") == "ok" and not glance.get("present"):
        out.append(
            _finding(
                "D.glance.present",
                "high",
                f"{glance.get('documents_listed')}/{glance.get('documents_at_head')} documents, "
                f"{glance.get('families_rendered')}/{glance.get('families_declared')} families",
                "the answering side carries the base's layout into every prompt; a layout that "
                "renders nothing claims to show the shape of the library while showing none of it",
            )
        )
    elif glance.get("status") == "ok" and not glance.get("within_budget"):
        out.append(
            _finding(
                "D.glance.within_budget",
                "medium",
                f"{glance.get('chars')}/{glance.get('budget')} chars",
                "a glance past its budget is truncated in every recall prompt, so the tail of "
                "the base is invisible to the answerer",
            )
        )
    growth = groups["D_navigability"]["growth"]
    if growth.get("sublinear") is False:
        out.append(
            _finding(
                "D.growth.canonical_growth_exponent",
                "medium",
                growth["canonical_growth_exponent"],
                "canonical growing at or above the material's own rate means the bird's-eye "
                "view stops improving as material accumulates",
            )
        )
    structure = groups["D_navigability"]["structure"]
    if structure["dated_slug_documents"]:
        out.append(
            _finding(
                "D.structure.dated_slug_rate",
                "medium",
                structure["dated_slug_rate"],
                "a dated slug slices a subject by time, which is what breaks the thread",
            )
        )
    if (structure["aggregation_rate"] or 0) == 0 and structure["documents_at_head"] > 1:
        out.append(
            _finding(
                "D.structure.aggregation_rate",
                "medium",
                structure["aggregation_rate"],
                "no document grew across rounds: every round wrote new files instead of threading",
            )
        )

    evolution = groups["E_evolution"]
    response = evolution["response"]
    if response.get("verdict") == "missed_pressure":
        out.append(
            _finding(
                "E.response.verdict",
                "high",
                "missed_pressure",
                "sustained catch-all pressure with no schema response means the schema stopped fitting",
            )
        )
    if response.get("verdict") == "churn":
        out.append(
            _finding(
                "E.response.verdict",
                "medium",
                "churn",
                "a schema change without misfit pressure reorganizes for its own sake",
            )
        )
    stability = evolution["schema_stability"]
    if not stability["invariants"]["family_floor_is_monotone"]:
        out.append(
            _finding(
                "E.schema_stability.family_floor",
                "high",
                stability["family_churn_events"],
                "a removed family orphans every document filed under it",
            )
        )
    fidelity = evolution["move_fidelity"]
    if fidelity.get("rewritten_while_moving"):
        out.append(
            _finding(
                "E.move_fidelity.rewritten_while_moving",
                "high",
                len(fidelity["rewritten_while_moving"]),
                "a claim rewritten while moving keeps an identity it no longer says the same thing under",
            )
        )

    admission = groups["B_admission"]
    if admission.get("status") == "unavailable":
        out.append(
            _finding(
                "B.admission",
                "coverage",
                "unavailable",
                admission.get("reason", "no truth set bound"),
            )
        )
    else:
        recall = admission["recall"]
        if (recall.get("degraded_from_peak") or 0) > 0:
            out.append(
                _finding(
                    "B.recall.degraded_from_peak",
                    "high",
                    recall["degraded_from_peak"],
                    "the structure once expressed a fact recognizably and later stopped",
                )
            )
        if not admission["noise_exclusion"]["invariants"]["no_unguarded_leak_at_head"]:
            out.append(
                _finding(
                    "B.noise_exclusion.unguarded_leaks",
                    "high",
                    admission["noise_exclusion"]["head"]["unguarded_leaks"],
                    "labelled exhaust standing as current fact is the admission failure that matters",
                )
            )
        support = admission.get("noise_support") or {}
        if support.get("status") == "ok" and support["head"]["claims_noise_only"]:
            out.append(
                _finding(
                    "B.noise_support.claims_noise_only",
                    "medium",
                    f"{support['head']['claims_noise_only']}/{support['head']['claims_judged']}",
                    "a claim whose entire evidence base was labelled exhaust is over-admission "
                    "that the negative-control list cannot see",
                )
            )
    if groups["F_usability_qa"].get("status") != "ok":
        out.append(
            _finding(
                "F.usability_qa",
                "coverage",
                groups["F_usability_qa"].get("status"),
                groups["F_usability_qa"].get("reason", ""),
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────── rendering


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _render_admission(admission: dict[str, Any]) -> list[str]:
    """The group B series, when a truth set was actually bound.

    Rendered because a bound truth set is the whole point of pairing artifacts with a
    labelled corpus: leaving it at a one-line status made the recall trajectory readable
    only by opening `scorecard.json`.
    """
    if admission.get("status") == "unavailable":
        return []
    out: list[str] = []
    truth_set = admission.get("truth_set") or {}
    out.append(
        f"- truth set: `{truth_set.get('corpus_key')}` — {truth_set.get('entries')} entries "
        f"({truth_set.get('current_entries')} current), {truth_set.get('negatives')} negative "
        f"controls, {truth_set.get('supersessions')} supersessions, "
        f"{truth_set.get('batches')} declared intake batches"
    )
    out.append("")
    recall = admission.get("recall") or {}
    if recall.get("status") == "ok":
        judged = recall.get("recall_judged") or {}
        judged_ran = judged.get("status") == "ok"
        headers = ["round", "claims", "matched", "labelled", "recall"]
        if judged_ran:
            headers += ["matched (judged)", "recall (judged)"]
        out.append(
            _table(
                headers,
                [
                    [
                        row["checkpoint"],
                        row["claims_total"],
                        row["matched"],
                        row["total"],
                        row["recall"],
                        *(
                            [row["matched_judged"], row["recall_judged"]]
                            if judged_ran
                            else []
                        ),
                    ]
                    for row in recall["series"]
                ],
            )
        )
        out += [
            "",
            f"- recall_similarity (character overlap ≥ {recall.get('threshold')}): head "
            f"{recall.get('head_recall')} · peak {recall.get('peak_recall')} · degraded from "
            f"peak {recall.get('degraded_from_peak')}",
        ]
        if judged_ran:
            out.append(
                f"- recall_judged (threshold passes + judge-confirmed rejections, top-"
                f"{judged.get('top_k')}): head {judged.get('head')} · peak "
                f"{judged.get('peak_recall')} · degraded from peak "
                f"{judged.get('degraded_from_peak')}; {judged.get('judge_decisions')} "
                f"fact-round decision(s) over {judged.get('judge_calls')} model call(s), "
                f"{judged.get('judge_no_candidate')} of them with no candidate claim to judge"
            )
        else:
            out.append(f"- recall_judged: `{judged.get('status')}` — {judged.get('reason')}")
        out.append("")
    noise = admission.get("noise_exclusion") or {}
    if noise.get("status") == "ok":
        head = noise["head"]
        out.append(
            f"- negative controls at head: {head['unguarded_leaks']} unguarded leak(s), "
            f"{head['guarded_mentions']} guarded mention(s) of {head['total']} labelled; "
            f"leak rate {head['leak_rate']}"
        )
    support = admission.get("noise_support") or {}
    if support.get("status") == "ok":
        head = support["head"]
        out.append(
            f"- over-inclusion against {support['labelled_texts']} pre-compilation content-class "
            f"labels: {head['claims_noise_only']} of {head['claims_judged']} judged claims rest "
            f"ONLY on noise-labelled evidence (rate {head['noise_only_rate']}); "
            f"{head['claims_citing_any_noise']} cite any noise block; cited block classes "
            f"{head['cited_block_classes']}"
        )
        if support["documents_at_head"]:
            out.append(f"  - noise-only claims by document: {support['documents_at_head']}")
    else:
        out.append(f"- over-inclusion: `{support.get('status')}` — {support.get('reason')}")
    latency = admission.get("latency") or {}
    if latency.get("status") == "ok":
        out.append(
            f"- admission latency: measured on {latency['measured']}/{latency['total']} "
            f"entries (round axis aligned: {latency['round_axis_aligned']}); mean lag "
            f"{latency['lag_rounds_mean']} rounds, max {latency['lag_rounds_max']}, "
            f"{latency['same_round_admissions']} same-round, "
            f"{latency['never_admitted']} never admitted"
        )
    else:
        out.append(f"- admission latency: `{latency.get('status')}` — {latency.get('reason')}")
    supersessions = admission.get("supersessions") or {}
    if supersessions.get("status") == "ok":
        out.append(
            f"- supersessions at head: {supersessions['head']['correct']}"
            f"/{supersessions['head']['total']} correct"
        )
    else:
        out.append(
            f"- supersessions: `{supersessions.get('status')}` — {supersessions.get('reason')}"
        )
    return out


def _render_qa(qa: dict[str, Any]) -> list[str]:
    """The group F accuracy tables, when the suite actually ran."""
    if qa.get("status") != "ok":
        return []
    out = [
        f"- cases: {qa['cases_correct']}/{qa['cases_total']} correct "
        f"(accuracy {qa['accuracy']}), threshold {qa['threshold']}",
        f"- judge arm: {'on' if qa.get('judge_used') else 'off'}; "
        f"{qa.get('judge_decided_checks', 0)} check(s) reached the judge",
        "",
        _table(
            ["category", "correct", "total", "accuracy"],
            [
                [category, row["correct"], row["total"], row["accuracy"]]
                for category, row in sorted(qa.get("by_category", {}).items())
            ],
        ),
        "",
        _table(
            ["case", "category", "correct", "checks passed"],
            [
                [
                    row["case_id"],
                    row["category"],
                    "yes" if row["correct"] else "no",
                    f"{sum(check['correct'] for check in row['checks'])}/{len(row['checks'])}",
                ]
                for row in qa.get("cases", [])
            ],
        ),
    ]
    return out


def render_report(scorecard: dict[str, Any]) -> str:
    """Render the scorecard as markdown: the series tables plus the findings list."""
    groups = scorecard["groups"]
    bundle = scorecard["bundle"]
    out: list[str] = [
        f"# Evaluation scorecard — {bundle['id']}",
        "",
        f"- mode: `{scorecard['mode']}`",
        f"- generated: {scorecard['generated_at']}",
        f"- checkpoints: {bundle['checkpoints']}",
        f"- documents at head: {bundle['documents_at_head']}",
        f"- claims at head: {bundle['claims_at_head']}",
        f"- L0 sources: {bundle['sources']} ({bundle['l0_blocks']} blocks)",
        "",
        "## Trajectory",
        "",
        _table(
            ["round", "ref", "committed", "docs", "claims", "canonical chars"],
            [
                [
                    row["label"],
                    row["ref"],
                    (row["committed_at"] or "—")[:19],
                    row["documents"],
                    row["claims"],
                    row["canonical_chars"],
                ]
                for row in scorecard["checkpoints"]
            ],
        ),
        "",
        "## A · grounded",
        "",
        _table(
            ["round", "claims", "cited", "coverage", "citations", "resolvable", "residue"],
            [
                [
                    row["checkpoint"],
                    row["claims_total"],
                    row["claims_with_citations"],
                    row["claim_coverage"],
                    row["citations_total"],
                    row.get("citations_resolvable"),
                    row["unparsable_marker_residue"],
                ]
                for row in groups["A_grounded"]["citations"]["series"]
            ],
        ),
        "",
        _table(
            ["transition", "anchors before", "anchors after", "added", "vanished (repo-wide)"],
            [
                [
                    f"{row['from']}→{row['to']}",
                    row["anchors_before"],
                    row["anchors_after"],
                    row["anchors_added"],
                    row["repo_wide_vanished"],
                ]
                for row in groups["A_grounded"]["anchors"]["series"]
            ],
        ),
        "",
        "## C · layering",
        "",
    ]
    compression = groups["C_layering"]["compression"]
    if compression.get("status") == "ok":
        out.append(
            _table(
                ["round", "prose chars", "markup chars", "L0 chars", "ratio", "chars/claim"],
                [
                    [
                        row["checkpoint"],
                        row["prose_chars"],
                        row["markup_chars"],
                        row["l0_chars"],
                        row["compression_ratio"],
                        row["chars_per_claim"],
                    ]
                    for row in compression["series"]
                ],
            )
        )
    else:
        out.append(f"_compression unavailable: {compression.get('reason')}_")
    out += [
        "",
        _table(
            ["round", "claims", "near-dup groups", "cross-doc groups", "dup row rate"],
            [
                [
                    row["checkpoint"],
                    row["claims_total"],
                    row["near_duplicate_groups"],
                    row["cross_document_groups"],
                    row["duplicate_row_rate"],
                ]
                for row in groups["C_layering"]["duplication"]["series"]
            ],
        ),
        "",
    ]
    language = groups["C_layering"].get("language_consistency") or {}
    if language.get("status") == "ok":
        out += [
            f"- declared language: `{language['declared_language']}` "
            f"(script `{language['declared_script']}`, from {language['declared_language_source']})",
            f"- material script, for reference only: `{language['material_script']}` "
            f"(L0 block scripts {language['material_block_scripts']})",
            "",
            _table(
                [
                    "round",
                    "claims",
                    "in declared language",
                    "diverged",
                    "mixed",
                    "declared-language rate",
                ],
                [
                    [
                        row["checkpoint"],
                        row["claims_total"],
                        row["in_declared_language"],
                        row["diverged_from_declared"],
                        row["mixed"],
                        row["declared_language_rate"],
                    ]
                    for row in language["series"]
                ],
            ),
        ]
        if language["documents_at_head"]:
            out.append(
                f"- diverged claims by document at head: {language['documents_at_head']}"
            )
    else:
        out.append(
            f"_language consistency unavailable: {language.get('reason')}_"
        )
    out += [
        "",
        "## D · navigability",
        "",
        f"- reachability basis: `{groups['D_navigability']['reachability'].get('basis')}` "
        f"(k={groups['D_navigability']['reachability'].get('max_hops')} hops from every "
        "document in turn, each standing for a retrieval hit)",
        "",
        _table(
            [
                "round",
                "docs",
                "edges",
                "mean reach",
                "median reach",
                "dead ends",
                "arrival-blind",
                "orphan claims",
            ],
            [
                [
                    row["checkpoint"],
                    row["documents"],
                    row["edges"],
                    row["mean_reach_rate"],
                    row["median_reach_rate"],
                    row["dead_end_documents"],
                    row["arrival_blind_documents"],
                    row["orphan_claims"],
                ]
                for row in groups["D_navigability"]["reachability"]["series"]
            ],
        ),
        "",
    ]
    glance = groups["D_navigability"].get("glance") or {}
    if glance.get("status") == "ok":
        out.append(
            f"- glance at head: {glance['chars']}/{glance['budget']} chars, "
            f"{glance['documents_listed']}/{glance['documents_at_head']} documents listed, "
            f"{glance['families_rendered']}/{glance['families_declared']} declared families "
            f"rendered ({glance['families_with_documents']} in use); present: "
            f"{'yes' if glance['present'] else 'no'}"
        )
    out += [
        "",
        "## E · evolution",
        "",
    ]
    pressure = groups["E_evolution"]["response"]["pressure"]
    out.append(
        _table(
            ["round", "new claims", "catch-all", "share", "under pressure"],
            [
                [
                    row["checkpoint"],
                    row["new_claims"],
                    row["catchall_claims"],
                    row["catchall_share"],
                    "yes" if row["under_pressure"] else "no",
                ]
                for row in pressure["series"]
            ],
        )
    )
    out += [
        "",
        f"- response status: `{groups['E_evolution']['response']['status']}`",
        f"- response verdict: `{groups['E_evolution']['response'].get('verdict')}`",
        "",
        "## B · admission",
        "",
        f"- B status: `{groups['B_admission'].get('status', 'ok')}`"
        + (
            f" — {groups['B_admission'].get('reason')}"
            if groups["B_admission"].get("reason")
            else ""
        ),
        "",
    ]
    out += _render_admission(groups["B_admission"])
    out += [
        "",
        "## F · usability QA",
        "",
        f"- F status: `{groups['F_usability_qa'].get('status')}`"
        + (
            f" — {groups['F_usability_qa'].get('reason')}"
            if groups["F_usability_qa"].get("reason")
            else ""
        ),
        "",
    ]
    out += _render_qa(groups["F_usability_qa"])
    out += [
        "",
        "## Findings",
        "",
    ]
    if scorecard["findings"]:
        out.append(
            _table(
                ["severity", "metric", "observed", "why it matters"],
                [
                    [row["severity"], f"`{row['metric']}`", row["observed"], row["why"]]
                    for row in scorecard["findings"]
                ],
            )
        )
    else:
        out.append("_no findings._")
    # Rendered because a metric that did not run is a hole in the reading, and a report that
    # shows only what WAS computed reads as complete coverage of everything it does not mention.
    out += [
        "",
        "## Not computed",
        "",
    ]
    if scorecard.get("unavailable"):
        out.append(
            _table(
                ["metric", "status", "cause", "reason"],
                [
                    [
                        f"`{row['metric']}`",
                        row["status"],
                        f"`{row['cause']}`" if row.get("cause") else "—",
                        row["reason"],
                    ]
                    for row in scorecard["unavailable"]
                ],
            )
        )
    else:
        out.append("_every metric produced a number._")
    out.append("")
    return "\n".join(out)


def write_outputs(scorecard: dict[str, Any], out_dir: Any) -> tuple[Any, Any]:
    """Write `scorecard.json` + `report.md` into `out_dir`; return both paths."""
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "scorecard.json"
    report_path = out_dir / "report.md"
    json_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_path.write_text(render_report(scorecard), encoding="utf-8")
    return json_path, report_path


__all__ = [
    "L0_ABSENT",
    "SCORECARD_SCHEMA",
    "build_scorecard",
    "findings",
    "render_report",
    "unavailable_because",
    "write_outputs",
]
