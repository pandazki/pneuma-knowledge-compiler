"""Group A — grounded: the provenance honesty audit.

The compile gate already hard-rejects an illegal citation, a vanished anchor and a dead
link, so this group is NOT here to re-test the gate. It is here because a gate is a claim
about what will be admitted next, while an artifact is evidence about what was admitted
before — and canonical is forward-only, so history predates every rule added after it. A
snapshot committed before a rule existed can legitimately violate it.

So: replay the provenance against the artifacts, report per checkpoint, and never repair.
A non-zero count in an early checkpoint with a zero at HEAD is the healthy shape (the
mechanism closed a hole); a non-zero count at HEAD is a real finding.

Every locator check uses the gate's own grammar and resolution helpers, so "resolvable"
here means exactly what "legal" means at write time.
"""

from __future__ import annotations

from typing import Any

from pneuma_knowledge_core.compile.anchor_ops import missing_anchors
from pneuma_knowledge_core.compile.gate import _MD_LINK_RE, _resolve_relative
from pneuma_knowledge_core.domain.canonical import CANONICAL_CITATION_MARKER_RE

from ..artifacts import Checkpoint, Trajectory
from .common import rate

# A `[cite:` opening that the accepted grammar does not match — malformed provenance that
# reads as a citation to a human but resolves to nothing.
_MARKER_OPENING = "[cite:"


def citation_integrity(trajectory: Trajectory) -> dict[str, Any]:
    """Per checkpoint: can every citation be replayed to a real source ¶ interval?

    Three independent failure modes are kept apart because they mean different things:
    `unknown_source` is a fabricated or renamed provenance, `out_of_range` is a real source
    with an interval past its block table, and `unparsable` is prose that looks like a
    citation but is not one.
    """
    bounds = trajectory.source_bounds()
    series: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        claims = checkpoint.claims
        citations_total = 0
        unknown_source = 0
        out_of_range = 0
        resolvable = 0
        unparsable = 0
        for doc in checkpoint.documents:
            unparsable += doc.body.count(_MARKER_OPENING) - len(
                CANONICAL_CITATION_MARKER_RE.findall(doc.body)
            )
        for claim in claims:
            for citation in claim.citations:
                citations_total += 1
                sid = str(citation.source_id)
                if sid not in bounds:
                    unknown_source += 1
                elif (
                    citation.block_start < 0
                    or citation.block_end < citation.block_start
                    or citation.block_end >= bounds[sid]
                ):
                    out_of_range += 1
                else:
                    resolvable += 1
        with_citations = sum(1 for claim in claims if claim.citations)
        row: dict[str, Any] = {
            "checkpoint": checkpoint.label,
            "claims_total": len(claims),
            "claims_with_citations": with_citations,
            "claim_coverage": rate(with_citations, len(claims)),
            "citations_total": citations_total,
            "unparsable_marker_residue": unparsable,
        }
        if trajectory.has_l0:
            row.update(
                {
                    "citations_resolvable": resolvable,
                    "resolvable_rate": rate(resolvable, citations_total),
                    "unknown_source": unknown_source,
                    "out_of_range": out_of_range,
                }
            )
        else:
            row["citations_resolvable"] = None
            row["resolvable_rate"] = None
            row["locator_replay"] = "unavailable: trajectory carries no L0 sources"
        series.append(row)
    head = series[-1]
    return {
        "status": "ok",
        "l0_available": trajectory.has_l0,
        "series": series,
        "head": head,
        "invariants": {
            "head_claim_coverage_is_total": head["claims_with_citations"] == head["claims_total"],
            "head_all_citations_resolvable": (
                head["citations_resolvable"] == head["citations_total"]
                if trajectory.has_l0
                else None
            ),
            "no_unparsable_residue_at_head": head["unparsable_marker_residue"] == 0,
        },
    }


def _vanished_repo_wide(previous: Checkpoint, current: Checkpoint) -> list[str]:
    """Anchors that left the repository entirely — a claim identity that stopped existing.

    Distinct from the gate's per-document rule on purpose: a claim MOVED between documents
    (the evolve channel) keeps its anchor, so it is not a loss. Only disappearing from every
    document is.
    """
    return sorted(previous.anchor_set - current.anchor_set)


def anchor_continuity(trajectory: Trajectory) -> dict[str, Any]:
    """Per adjacent checkpoint pair: did any claim identity disappear?

    Reported on two axes — per-document (what the gate enforces) and repo-wide (what claim
    identity actually means). A per-document loss with no repo-wide loss is a legitimate
    move; a repo-wide loss is a real deletion.
    """
    series: list[dict[str, Any]] = []
    for previous, current in zip(trajectory.checkpoints, trajectory.checkpoints[1:]):
        per_document: list[dict[str, str]] = []
        for path, body in previous.bodies.items():
            for anchor in missing_anchors(body, current.bodies.get(path, "")):
                per_document.append({"path": path, "anchor": anchor})
        repo_wide = _vanished_repo_wide(previous, current)
        series.append(
            {
                "from": previous.label,
                "to": current.label,
                "anchors_before": len(previous.anchor_set),
                "anchors_after": len(current.anchor_set),
                "anchors_added": len(current.anchor_set - previous.anchor_set),
                "per_document_vanished": len(per_document),
                "repo_wide_vanished": len(repo_wide),
                "moved_not_lost": max(len(per_document) - len(repo_wide), 0),
                "samples": per_document[:10],
            }
        )
    documents_dropped = [
        {
            "from": previous.label,
            "to": current.label,
            "paths": sorted(set(previous.files) - set(current.files)),
        }
        for previous, current in zip(trajectory.checkpoints, trajectory.checkpoints[1:])
        if set(previous.files) - set(current.files)
    ]
    return {
        "status": "ok",
        "transitions": len(series),
        "series": series,
        "documents_dropped": documents_dropped,
        "invariants": {
            "no_repo_wide_anchor_loss": all(row["repo_wide_vanished"] == 0 for row in series),
            "no_document_dropped": not documents_dropped,
            "anchor_floor_is_monotone": all(
                row["anchors_after"] >= row["anchors_before"] for row in series
            ),
        },
    }


def _links_of(checkpoint: Checkpoint) -> list[dict[str, str]]:
    """Every inter-document markdown link, classified with the gate's own resolution."""
    known = set(checkpoint.files)
    links: list[dict[str, str]] = []
    for doc in checkpoint.documents:
        for match in _MD_LINK_RE.finditer(doc.body):
            href = match.group(1)
            if not href.endswith(".md") or "://" in href:
                continue
            target = _resolve_relative(doc.path, href)
            if target == doc.path:
                kind = "self"
            elif target in known:
                kind = "resolved"
            else:
                kind = "dead"
            links.append({"path": doc.path, "href": href, "target": target, "kind": kind})
    return links


def link_integrity(trajectory: Trajectory) -> dict[str, Any]:
    """Per checkpoint: dead / self / resolved inter-document links.

    Markdown links are what the projection turns into knowledge-graph edges, i.e. the hops
    available when direct retrieval misses. A dead link is a dead end in that graph; ZERO
    links at all is a different and quieter failure, so the link count itself is reported
    rather than only the error rate.
    """
    series: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        links = _links_of(checkpoint)
        dead = [row for row in links if row["kind"] == "dead"]
        selfish = [row for row in links if row["kind"] == "self"]
        series.append(
            {
                "checkpoint": checkpoint.label,
                "documents": len(checkpoint.files),
                "links_total": len(links),
                "resolved": len(links) - len(dead) - len(selfish),
                "dead": len(dead),
                "self": len(selfish),
                "dead_rate": rate(len(dead), len(links)),
                "samples": (dead + selfish)[:10],
            }
        )
    head = series[-1]
    return {
        "status": "ok",
        "series": series,
        "head": head,
        "invariants": {
            "no_dead_links_at_head": head["dead"] == 0,
            "no_self_links_at_head": head["self"] == 0,
            "head_has_any_link": head["links_total"] > 0,
        },
    }


def grounded_metrics(trajectory: Trajectory) -> dict[str, Any]:
    """Group A entry point: citation replay, anchor continuity, link integrity."""
    return {
        "group": "A_grounded",
        "citations": citation_integrity(trajectory),
        "anchors": anchor_continuity(trajectory),
        "links": link_integrity(trajectory),
    }


__all__ = [
    "anchor_continuity",
    "citation_integrity",
    "grounded_metrics",
    "link_integrity",
]
