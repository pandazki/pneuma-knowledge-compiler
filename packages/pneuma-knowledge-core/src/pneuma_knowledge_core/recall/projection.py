"""Canonical → claim projection (architecture.md §3 L3, §7; milestone M4).

Everything here is derived (invariant I2): a full pass over a snapshot's canonical
documents that re-materializes one record per anchored claim. The projection is
rebuilt in full after every compile commit — never mutated incrementally — so it is
always reconstructable from canonical alone.

Provenance (I4): each ProjectedClaim keeps its anchor and its `[cite: <sid> ¶a-b]`
citations parsed into the same `source_id + block span` addressing used everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.canonical import (
    CANONICAL_CITATION_MARKER_RE,
    CanonicalDocument,
    Citation,
    iter_canonical_citations,
)
from ..domain.ids import ANCHOR_MARK_RE, AnchorId, SourceId

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


@dataclass(frozen=True)
class ProjectionStrategy:
    """A derived-layer projection strategy (invariant I2, milestone M5).

    The projection is derived: how a canonical claim is materialized into the L3
    retrieval face is a strategy decision that can be upgraded and full-rebuilt WITHOUT
    touching canonical. This holds the knobs; a new strategy + `rebuild_projection`
    re-materializes every row from the same frozen canonical.

    - `version`: identity tag stamped onto each rebuild (audit/observability).
    - `fold_section_context`: v2 enriches the indexed/rendered claim text with its
      section breadcrumb so a claim is self-contained for lexical + semantic retrieval
      (a claim like "end-to-end tests pass" gains its "Delivery › Acceptance" context). The
      canonical body
      is unchanged; only the derived `text` differs.
    """

    version: str = "v1"
    fold_section_context: bool = False


PROJECTION_V1 = ProjectionStrategy(version="v1", fold_section_context=False)
PROJECTION_V2 = ProjectionStrategy(version="v2", fold_section_context=True)


@dataclass(frozen=True)
class ProjectedClaim:
    """One anchored claim materialized from a canonical document body (L3 face)."""

    anchor: AnchorId
    document_path: str
    section_path: tuple[str, ...]
    text: str
    citations: tuple[Citation, ...] = field(default_factory=tuple)


def _anchor_block(lines: list[str], anchor_line: int) -> tuple[int, int]:
    """The natural block [start, end) holding the anchor (mirrors anchor_ops._block_span
    and dataset._anchor_block: list items stand alone, a paragraph extends upward to a
    blank/heading/list boundary, and any line carrying another anchor is a hard stop —
    an anchor sits on its block's last line, so an anchored line above the target is
    another claim's end and must not fold into this claim's text)."""
    end = anchor_line + 1
    if _LIST_ITEM_RE.match(lines[anchor_line]):
        return anchor_line, end
    start = anchor_line
    while start > 0:
        prev = lines[start - 1]
        if not prev.strip() or _HEADING_RE.match(prev) or ANCHOR_MARK_RE.search(prev):
            break
        start -= 1
        if _LIST_ITEM_RE.match(prev):
            break
    return start, end


def _clean_and_cite(block: str) -> tuple[str, list[Citation]]:
    """Split a claim block into clean display text + parsed citations.

    The anchor comment and the inline `[cite:…]` markers are stripped from the text;
    citations are parsed into structured `Citation` records (I4 addressing)."""
    citations = list(iter_canonical_citations(block))
    text = CANONICAL_CITATION_MARKER_RE.sub("", block)
    text = ANCHOR_MARK_RE.sub("", text)
    # Drop a leading list bullet for a cleaner claim string; collapse trailing space.
    text = _LIST_ITEM_RE.sub("", text, count=1) if _LIST_ITEM_RE.match(text) else text
    return text.strip(), citations


def _render_text(text: str, section_path: tuple[str, ...], strategy: ProjectionStrategy) -> str:
    """Apply the strategy's text rendering to a claim's clean display text."""
    if strategy.fold_section_context and section_path:
        return f"[{' › '.join(section_path)}] {text}"
    return text


def project_document_claims(
    doc: CanonicalDocument, strategy: ProjectionStrategy = PROJECTION_V1
) -> list[ProjectedClaim]:
    """Parse every anchored claim in one canonical document, in document order.

    section_path is the heading stack above the claim; duplicate anchors (a re-cited
    anchor) are emitted once (first occurrence). `strategy` governs derived rendering
    only (e.g. folding the section breadcrumb into the indexed text) — the canonical
    body is read, never written."""
    lines = doc.body.split("\n")
    claims: list[ProjectedClaim] = []
    seen: set[str] = set()
    section_stack: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))
            continue
        for anchor in ANCHOR_MARK_RE.findall(line):
            if anchor in seen:
                continue
            seen.add(anchor)
            start, end = _anchor_block(lines, i)
            block = "\n".join(lines[start:end])
            text, citations = _clean_and_cite(block)
            section_path = tuple(t for _, t in section_stack)
            claims.append(
                ProjectedClaim(
                    anchor=AnchorId(anchor),
                    document_path=doc.path,
                    section_path=section_path,
                    text=_render_text(text, section_path, strategy),
                    citations=tuple(citations),
                )
            )
    return claims


def project_snapshot_claims(
    docs: list[CanonicalDocument],
    strategy: ProjectionStrategy = PROJECTION_V1,
) -> list[ProjectedClaim]:
    """Project a whole snapshot's documents into a claim list under `strategy`.

    Deterministic order: documents by path, then claims in document order — no set
    iteration (the briefing byte-stability discipline)."""
    out: list[ProjectedClaim] = []
    for doc in sorted(docs, key=lambda d: d.path):
        out.extend(project_document_claims(doc, strategy))
    return out


def claims_citing(
    claims: list[ProjectedClaim], source_id: SourceId
) -> list[ProjectedClaim]:
    """Reverse lookup: the claims whose citations reference `source_id`, in the input
    order (already deterministic when fed project_snapshot_claims output)."""
    sid = str(source_id)
    return [
        c for c in claims if any(str(cit.source_id) == sid for cit in c.citations)
    ]
