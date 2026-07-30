"""Group D — navigability: canonical's two jobs, quantified.

Canonical exists to do two things no index does:

1. FOLLOW THE THREAD — from one entry point you can walk to the related subject without
   already knowing its name. That walk runs on inter-document markdown links, which the
   projection turns into graph edges. Measured as: what fraction of documents is reachable
   from the hub family within k hops, how many documents are isolated, and how many claims
   sit in unreachable documents.
2. BIRD'S EYE — the whole structure stays smaller than the material it summarizes, and keeps
   getting relatively smaller as material accumulates. Measured as the growth exponent of
   canonical size in L0 size: sublinear (< 1) is the claim, linear (≈ 1) means the layer is
   just a compressed mirror.

Plus the fragmentation signals that decide whether either job survives contact with a year
of material: does a subject get ONE document that grows, or a new dated document every
round; and is the family space actually used, or has everything collapsed into one family.

The link grammar and resolution are the gate's, so a link that counts as an edge here is
exactly a link the gate validated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pneuma_knowledge_core.compile.gate import _MD_LINK_RE, _resolve_relative

from ..artifacts import Checkpoint, Trajectory, family_of
from .common import log_log_slope, rate, shannon_entropy, unavailable

#: A slug carrying a date or a bare year — the fragmentation tell. A subject that gets
#: `orion-pilot-2026-07-24.md` instead of growing `orion-pilot.md` has been sliced by time,
#: which is precisely what makes follow-the-thread stop working.
_DATED_SLUG_RE = re.compile(r"(?:^|-)(?:19|20)\d{2}(?:-\d{1,2})?(?:-\d{1,2})?(?:$|-)")

#: Default hop budget for the follow-the-thread walk. Two hops is the browse depth a reader
#: tolerates before giving up and going back to search.
DEFAULT_MAX_HOPS = 2


def hub_paths(trajectory: Trajectory) -> tuple[str, ...]:
    """The hub family: the fixed-path documents a skill declares (no `{slug}` in template).

    For the packaged skill that is `memory/profile.md` — the one document guaranteed to
    exist, hence the only entry point a reader can be assumed to know.
    """
    return tuple(
        template for template in trajectory.path_templates if "{slug}" not in template
    )


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
    """Follow-the-thread: document and claim coverage reachable from the hub family.

    Reported directed (what a reader following links actually gets) and undirected (what a
    graph view would show), because a structure whose edges all point AT the hub is navigable
    in a graph UI and useless when read from the hub.
    """
    hubs = hub_paths(trajectory)
    series: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        edges = _edges(checkpoint)
        seeds = [path for path in hubs if path in edges]
        documents = len(checkpoint.files)
        directed = _reachable(edges, seeds, max_hops=max_hops, undirected=False)
        undirected = _reachable(edges, seeds, max_hops=max_hops, undirected=True)
        isolated = sorted(
            path
            for path, targets in edges.items()
            if not targets and not any(path in others for others in edges.values())
        )
        unreachable = set(checkpoint.files) - directed
        orphan_claims = [
            claim for claim in checkpoint.claims if claim.document_path in unreachable
        ]
        series.append(
            {
                "checkpoint": checkpoint.label,
                "documents": documents,
                "hub_documents_present": len(seeds),
                "edges": sum(len(targets) for targets in edges.values()),
                "reachable_documents": len(directed),
                "reachable_document_rate": rate(len(directed), documents),
                "reachable_documents_undirected": len(undirected),
                "isolated_documents": len(isolated),
                "isolated_document_rate": rate(len(isolated), documents),
                "orphan_claims": len(orphan_claims),
                "orphan_claim_rate": rate(len(orphan_claims), len(checkpoint.claims)),
            }
        )
    head = series[-1]
    return {
        "status": "ok",
        "max_hops": max_hops,
        "hub_templates": list(hubs),
        "series": series,
        "head": head,
        "invariants": {
            "hub_present_at_head": head["hub_documents_present"] > 0,
            "graph_has_edges_at_head": head["edges"] > 0,
            "every_document_reachable_at_head": head["reachable_document_rate"] == 1.0,
        },
    }


def growth(trajectory: Trajectory) -> dict[str, Any]:
    """Bird's eye: is canonical growth sublinear in material growth?

    The exponent is fitted over checkpoints, so it is a property of the trajectory and not of
    HEAD. It needs at least two checkpoints with known consumed L0; otherwise it says so.
    """
    if not trajectory.has_l0:
        return unavailable("trajectory carries no L0 sources: growth has no independent axis")
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


def navigability_metrics(
    trajectory: Trajectory, *, max_hops: int = DEFAULT_MAX_HOPS
) -> dict[str, Any]:
    """Group D entry point: reachability, growth, structure health."""
    return {
        "group": "D_navigability",
        "reachability": reachability(trajectory, max_hops=max_hops),
        "growth": growth(trajectory),
        "structure": structure_health(trajectory),
    }


__all__ = [
    "DEFAULT_MAX_HOPS",
    "growth",
    "hub_paths",
    "navigability_metrics",
    "reachability",
    "structure_health",
]
