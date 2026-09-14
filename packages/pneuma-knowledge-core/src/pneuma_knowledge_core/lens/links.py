"""Edges and claims, counted the way the rest of the framework counts them.

There is exactly one link grammar in this repository (`compile/links.py`) and exactly one
claim count (`canonical_glance.claim_count`), and the lens uses both rather than restating
either. That is not tidiness: the eval suite's reachability group and the lens are supposed
to agree on dead ends by construction (docs/design/structure-lens.md §8), and two parsers
of one grammar agree only by luck.

What this module adds is the SUBJECT fold. A closed volume's links and claims belong to the
page it was cut out of, so an edge is between subjects rather than between files, and a
page's link to its own volume is not an edge at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..canonical_glance import claim_count
from ..compile.anchor_ops import anchored_blocks
from ..compile.documents import overview_region, strip_overview
from ..compile.links import _MD_LINK_RE, _resolve_relative
from .families import subject_of


@dataclass(frozen=True)
class Edge:
    """One link, as the lens reads it: from a subject, to a target path, by an href.

    `target` is the repository path the href resolves to — which may be a path no document
    has, and that is the `nav.dead_link` finding. `source_path` is the FILE the href was
    written in (a volume keeps its own name here), so a finding can point at the line.
    """

    subject: str
    target: str
    href: str
    source_path: str


def _link_regions(body: str) -> list[str]:
    """The text an edge may be written in: the overview region, and each anchored claim.

    §2's rule, applied literally. A heading, an unanchored paragraph or a stray note is not
    a claim, so a link there is not knowledge pointing anywhere — it is text nobody cited.
    """
    ledger = strip_overview(body)
    regions = [region for region in (overview_region(body),) if region]
    regions.extend(anchored_blocks(ledger))
    return regions


def document_edges(path: str, body: str) -> list[tuple[str, str]]:
    """`(target path, href)` for every canonical link in `body`'s claims and overview.

    Only `.md` hrefs, only relative ones: an external URL is not an edge in this library,
    and the resolver is the gate's, so a target here is a target there. Fragments are
    dropped by the resolver itself.
    """
    out: list[tuple[str, str]] = []
    for region in _link_regions(body):
        for match in _MD_LINK_RE.finditer(region):
            href = match.group(1)
            if not href.endswith(".md") or "://" in href:
                continue
            out.append((_resolve_relative(path, href), href))
    return out


def subject_edges(
    documents: Mapping[str, object] | Sequence[object],
) -> list[Edge]:
    """Every edge in the library, folded onto subjects and de-duplicated.

    A volume's edges are re-attributed to its open page, and a subject's link to its own
    volume — or to itself — is dropped: neither is a hop a reader could take to somewhere
    else, which is the only thing an edge is being counted for.
    """
    by_path = _by_path(documents)
    present = set(by_path)
    seen: set[tuple[str, str]] = set()
    edges: list[Edge] = []
    for path in sorted(by_path):
        doc = by_path[path]
        subject = subject_of(path, present)
        for target, href in document_edges(path, str(getattr(doc, "body", "") or "")):
            target_subject = subject_of(target, present) if target in present else target
            if target_subject == subject:
                continue
            key = (subject, target_subject)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                Edge(subject=subject, target=target_subject, href=href, source_path=path)
            )
    return edges


def subject_claims(documents: Mapping[str, object] | Sequence[object]) -> dict[str, int]:
    """subject → how many claims it holds, volumes folded in.

    `canonical_glance.claim_count` is what counts them, so the overview's blocks are not
    claims here either — the lens and core agree on how developed a subject is.
    """
    by_path = _by_path(documents)
    present = set(by_path)
    counts: dict[str, int] = {}
    for path, doc in by_path.items():
        subject = subject_of(path, present)
        counts[subject] = counts.get(subject, 0) + claim_count(doc)
    return counts


def _by_path(documents: Mapping[str, object] | Sequence[object]) -> dict[str, object]:
    if isinstance(documents, Mapping):
        return {str(path): doc for path, doc in documents.items()}
    return {str(getattr(doc, "path", "")): doc for doc in documents}


def in_degree(edges: Iterable[Edge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.target] = counts.get(edge.target, 0) + 1
    return counts


def out_degree(edges: Iterable[Edge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.subject] = counts.get(edge.subject, 0) + 1
    return counts


__all__ = [
    "Edge",
    "document_edges",
    "in_degree",
    "out_degree",
    "subject_claims",
    "subject_edges",
]
