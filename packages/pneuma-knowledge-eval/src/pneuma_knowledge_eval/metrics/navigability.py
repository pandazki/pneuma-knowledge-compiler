"""Group D — navigability: canonical's two jobs, quantified.

Canonical exists to do two things no index does:

1. FOLLOW THE THREAD — from wherever you land you can walk to the related subject without
   already knowing its name. That walk runs on inter-document markdown links, which the
   projection turns into graph edges.
2. BIRD'S EYE — the whole structure stays smaller than the material it summarizes, and keeps
   getting relatively smaller as material accumulates. Measured as the growth exponent of
   canonical size in L0 size: sublinear (< 1) is the claim, linear (≈ 1) means the layer is
   just a compressed mirror.

Plus the fragmentation signals that decide whether either job survives contact with a year
of material: does a subject get ONE document that grows, or a new dated document every
round; and is the family space actually used, or has everything collapsed into one family.
Plus, since the answering side now carries the base's layout into every prompt, whether that
layout renders at all over this trajectory's head.

WHY REACHABILITY IS NO LONGER HUB-SEEDED (metric definition changed — see scorecard schema
version). The first cut of this group walked from the "hub family", the fixed-path documents
a skill declares (`memory/profile.md` for the packaged one), on the reasoning that the hub is
the only entry a reader can be assumed to know. That measured the wrong system. Nobody enters
this knowledge base at a designated root: a question arrives, retrieval lands on whatever
document holds the matching claim, and the walk starts THERE. Hub-seeding therefore scored a
structure by whether one particular document happened to be created and happened to link
outward — which is how the first evaluation reported reachability 0.0 for a base with a
perfectly usable link graph, purely because that one file was never written.

So the walk is now seeded from every document in turn, each standing for a retrieval hit,
and the metric is the DISTRIBUTION of how much of the base is reachable from an arbitrary
landing point within k hops. A dead-end document (a landing point from which nothing else is
reachable) is the concrete navigation failure; an arrival-blind document (one no other
document links to) is the concrete discovery failure. Both are reported as counts, not folded
into an average that hides them.

The link grammar and resolution are the gate's, so a link that counts as an edge here is
exactly a link the gate validated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from statistics import fmean, median
from typing import Any

from pneuma_knowledge_core.canonical_glance import (
    GLANCE_BUDGET_CHARS,
    family_of as glance_family_of,
    render_canonical_glance,
)
from pneuma_knowledge_core.compile.gate import _MD_LINK_RE, _resolve_relative

from ..artifacts import Checkpoint, Trajectory, family_of
from .common import L0_ABSENT, log_log_slope, rate, shannon_entropy, unavailable

#: A slug carrying a date or a bare year — the fragmentation tell. A subject that gets
#: `orion-pilot-2026-07-24.md` instead of growing `orion-pilot.md` has been sliced by time,
#: which is precisely what makes follow-the-thread stop working.
_DATED_SLUG_RE = re.compile(r"(?:^|-)(?:19|20)\d{2}(?:-\d{1,2})?(?:-\d{1,2})?(?:$|-)")

#: Default hop budget for the follow-the-thread walk. Two hops is the browse depth a reader
#: tolerates before giving up and going back to search.
DEFAULT_MAX_HOPS = 2


def _edges(checkpoint: Checkpoint) -> dict[str, set[str]]:
    """Directed link edges between existing documents (dead links are not edges)."""
    known = set(checkpoint.files)
    out: dict[str, set[str]] = {path: set() for path in known}
    for doc in checkpoint.documents:
        for match in _MD_LINK_RE.finditer(doc.body):
            href = match.group(1)
            if not href.endswith(".md") or "://" in href:
                continue
            target = _resolve_relative(doc.path, href)
            if target in known and target != doc.path:
                out[doc.path].add(target)
    return out


def _reachable(
    edges: dict[str, set[str]], seeds: Sequence[str], *, max_hops: int, undirected: bool
) -> set[str]:
    if undirected:
        symmetric: dict[str, set[str]] = {path: set(targets) for path, targets in edges.items()}
        for path, targets in edges.items():
            for target in targets:
                symmetric.setdefault(target, set()).add(path)
        edges = symmetric
    frontier = {seed for seed in seeds if seed in edges}
    seen = set(frontier)
    for _ in range(max_hops):
        nxt: set[str] = set()
        for path in frontier:
            nxt |= edges.get(path, set()) - seen
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    return seen


def reachability(
    trajectory: Trajectory, *, max_hops: int = DEFAULT_MAX_HOPS
) -> dict[str, Any]:
    """Follow-the-thread from a retrieval hit: how far can you walk from where you land?

    Every document is seeded in turn — each one standing for the landing point retrieval hands
    you — and the reported quantity is the distribution of k-hop coverage over those seeds:
    `mean_reach_rate` is the fraction of the base an arbitrary hit can walk to, and it is 1/N
    for a base with no links at all (you have only what you landed on).

    Two failure counts are kept out of the average because averaging hides exactly what a
    reader feels: `dead_end_documents` are landing points from which nothing else is
    reachable, and `arrival_blind_documents` are documents no other document links to, which
    can only be found by already knowing their name. `isolated_documents` are both at once.

    Reported directed (what a reader following links actually gets) and undirected (what a
    graph view would show), because a structure whose edges all point one way is navigable in
    a graph UI and a cul-de-sac when read.
    """
    series: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        edges = _edges(checkpoint)
        documents = len(checkpoint.files)
        paths = sorted(edges)
        incoming: dict[str, int] = {path: 0 for path in paths}
        for source, targets in edges.items():
            for target in targets:
                incoming[target] = incoming.get(target, 0) + 1

        directed_rates: list[float] = []
        undirected_rates: list[float] = []
        dead_ends: list[str] = []
        for seed in paths:
            reached = _reachable(edges, [seed], max_hops=max_hops, undirected=False)
            directed_rates.append(len(reached) / documents if documents else 0.0)
            undirected_rates.append(
                len(_reachable(edges, [seed], max_hops=max_hops, undirected=True)) / documents
                if documents
                else 0.0
            )
            if len(reached - {seed}) == 0:
                dead_ends.append(seed)

        arrival_blind = sorted(path for path in paths if incoming.get(path, 0) == 0)
        isolated = sorted(set(dead_ends) & set(arrival_blind))
        # A claim is orphaned when its document can be reached from nothing else: the claim
        # exists, retrieval can hit it directly, but no thread leads to it.
        orphan_claims = [
            claim
            for claim in checkpoint.claims
            if claim.document_path in set(arrival_blind)
        ]
        series.append(
            {
                "checkpoint": checkpoint.label,
                "documents": documents,
                "edges": sum(len(targets) for targets in edges.values()),
                "mean_reach_rate": round(fmean(directed_rates), 6) if directed_rates else None,
                "median_reach_rate": (
                    round(median(directed_rates), 6) if directed_rates else None
                ),
                "max_reach_rate": round(max(directed_rates), 6) if directed_rates else None,
                "mean_reach_rate_undirected": (
                    round(fmean(undirected_rates), 6) if undirected_rates else None
                ),
                "dead_end_documents": len(dead_ends),
                "dead_end_rate": rate(len(dead_ends), documents),
                "arrival_blind_documents": len(arrival_blind),
                "arrival_blind_rate": rate(len(arrival_blind), documents),
                "isolated_documents": len(isolated),
                "isolated_document_rate": rate(len(isolated), documents),
                "orphan_claims": len(orphan_claims),
                "orphan_claim_rate": rate(len(orphan_claims), len(checkpoint.claims)),
            }
        )
    head = series[-1]
    return {
        "status": "ok",
        # The seeding basis, stated in the artifact: a scorecard read years later must not have
        # to guess which definition of "reachable" produced its numbers.
        "basis": "retrieval_hit_seeded",
        "max_hops": max_hops,
        "series": series,
        "head": head,
        "invariants": {
            "graph_has_edges_at_head": head["edges"] > 0,
            "no_dead_end_at_head": head["dead_end_documents"] == 0,
            "every_document_arrivable_at_head": head["arrival_blind_documents"] == 0,
        },
    }


def growth(trajectory: Trajectory) -> dict[str, Any]:
    """Bird's eye: is canonical growth sublinear in material growth?

    The exponent is fitted over checkpoints, so it is a property of the trajectory and not of
    HEAD. It needs at least two checkpoints with known consumed L0; otherwise it says so.
    """
    if not trajectory.has_l0:
        return unavailable(
            "trajectory carries no L0 sources: growth has no independent axis",
            cause=L0_ABSENT,
        )
    xs: list[float] = []
    chars: list[float] = []
    claims: list[float] = []
    series: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(trajectory.checkpoints):
        l0 = trajectory.l0_chars_through(index)
        series.append(
            {
                "checkpoint": checkpoint.label,
                "l0_chars": l0,
                "canonical_chars": checkpoint.canonical_chars,
                "documents": len(checkpoint.files),
                "claims": len(checkpoint.claims),
            }
        )
        if l0:
            xs.append(float(l0))
            chars.append(float(checkpoint.canonical_chars))
            claims.append(float(len(checkpoint.claims)))
    exponent = log_log_slope(xs, chars)
    claims_exponent = log_log_slope(xs, claims)
    return {
        "status": "ok" if exponent is not None else "unavailable",
        "reason": None if exponent is not None else "fewer than two checkpoints with known L0",
        "series": series,
        "canonical_growth_exponent": exponent,
        "claim_growth_exponent": claims_exponent,
        "sublinear": None if exponent is None else exponent < 1.0,
    }


def _slug_of(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def structure_health(trajectory: Trajectory) -> dict[str, Any]:
    """Fragmentation and family utilization: does a subject aggregate, or multiply?

    `documents_growing_across_rounds` is the aggregation measure — a document that received
    claims in more than one round is a subject that got threaded rather than snapshotted.
    Family entropy is normalized against the families actually AVAILABLE, so collapsing
    everything into one family scores low even when that family is busy.
    """
    templates = list(trajectory.path_templates)
    claims_by_path_round: dict[str, set[str]] = {}
    for previous, current in zip((None, *trajectory.checkpoints), trajectory.checkpoints):
        before = previous.anchor_set if previous is not None else frozenset()
        for claim in current.claims:
            if str(claim.anchor) not in before:
                claims_by_path_round.setdefault(claim.document_path, set()).add(current.label)
    head = trajectory.head
    family_counts: dict[str, int] = {template: 0 for template in templates}
    unowned = 0
    for claim in head.claims:
        template = family_of(claim.document_path, templates)
        if template is None:
            unowned += 1
        else:
            family_counts[template] += 1
    dated = [path for path in head.files if _DATED_SLUG_RE.search(_slug_of(path))]
    multi_round = [
        path for path, rounds in claims_by_path_round.items() if len(rounds) > 1
    ]
    entropy = shannon_entropy(family_counts.values())
    families_in_use = sum(1 for count in family_counts.values() if count)
    max_entropy = shannon_entropy([1] * len(templates)) if templates else None
    return {
        "status": "ok",
        "documents_at_head": len(head.files),
        "documents_growing_across_rounds": len(multi_round),
        "aggregation_rate": rate(len(multi_round), len(head.files)),
        "dated_slug_documents": len(dated),
        "dated_slug_rate": rate(len(dated), len(head.files)),
        "dated_slug_samples": sorted(dated)[:10],
        "families_available": len(templates),
        "families_in_use": families_in_use,
        "family_utilization": rate(families_in_use, len(templates)),
        "family_claim_counts": dict(sorted(family_counts.items())),
        "family_entropy_bits": entropy,
        "family_entropy_normalized": (
            round(entropy / max_entropy, 6)
            if entropy is not None and max_entropy not in (None, 0)
            else None
        ),
        "claims_in_unowned_paths": unowned,
        "documents_per_round": [
            {"checkpoint": cp.label, "documents": len(cp.files), "claims": len(cp.claims)}
            for cp in trajectory.checkpoints
        ],
    }


def glance(trajectory: Trajectory) -> dict[str, Any]:
    """Bird's eye, as the answering side actually receives it: does the glance render?

    The recall lanes carry the knowledge base's layout into every prompt (core's
    `canonical_glance`). That is a capability, and a capability that silently produces an
    empty or over-budget surface is worse than an absent one — the prompt then claims to show
    the library's shape while showing nothing.

    This runs the SHIPPED renderer over the head snapshot's real documents and real path
    templates, so what is checked is the artifact the model would get: is it non-empty, does
    every declared family appear in it (a family missing from the layout is a filing slot the
    answerer cannot know exists), does every document appear or get honestly counted as
    omitted, and does it fit the budget.

    What it cannot check is that a live prompt included it — that is a property of an assembled
    message, tested where the lanes are assembled. Here the question is whether this
    trajectory's structure renders into a usable map at all.
    """
    head = trajectory.head
    templates = list(trajectory.path_templates)
    documents = list(head.documents)
    text = render_canonical_glance(documents, templates=templates)
    families_with_documents = sorted(
        {
            template
            for template in templates
            if any(glance_family_of(path, templates) == template for path in head.files)
        }
    )
    # Checked against the rendered text rather than against the renderer's internals, so a
    # deployment that rewrote the glance wording is still measured on what it actually emits.
    missing_families = [template for template in templates if template not in text]
    listed = sum(1 for path in head.files if path in text)
    return {
        "status": "ok",
        "chars": len(text),
        "budget": GLANCE_BUDGET_CHARS,
        "within_budget": len(text) <= GLANCE_BUDGET_CHARS,
        "families_declared": len(templates),
        "families_rendered": len(templates) - len(missing_families),
        "families_with_documents": len(families_with_documents),
        "families_missing_from_glance": missing_families,
        "documents_at_head": len(head.files),
        "documents_listed": listed,
        "documents_omitted_by_truncation": len(head.files) - listed,
        # A glance that renders nothing but its own header is not a bird's-eye view.
        "present": bool(documents) and listed > 0 and not missing_families,
    }


def navigability_metrics(
    trajectory: Trajectory, *, max_hops: int = DEFAULT_MAX_HOPS
) -> dict[str, Any]:
    """Group D entry point: reachability, growth, structure health, glance."""
    return {
        "group": "D_navigability",
        "reachability": reachability(trajectory, max_hops=max_hops),
        "growth": growth(trajectory),
        "structure": structure_health(trajectory),
        "glance": glance(trajectory),
    }


__all__ = [
    "DEFAULT_MAX_HOPS",
    "glance",
    "growth",
    "navigability_metrics",
    "reachability",
    "structure_health",
]
