"""Canonical knowledge model.

Invariant I2 (canonical vs derived): a CanonicalDocument lives in the per-user
git authority layer and, together with raw content, is the ONLY non-rebuildable
object. Projections, indexes, annotations are all derived and declared fully
rebuildable. Strategy/rendering upgrades trigger derived rebuilds and NEVER
rewrite canonical. These types are the canonical (authority) side of that split;
derived artifacts are modeled elsewhere (projection/index adapters).

Invariant I4 (provenance): every Claim addresses back to source via
`source_id + block span` through its Citation list — the same addressing used by
semantic chunks, lexical hits, and the structure map.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from .ids import AnchorId, DocumentId, SourceId

# Canonical syntax is rendered as `¶a-b`. A model may emit several spans for the same
# source in one bracket, e.g. `¶1-2,6` or `¶1,3,5-7`; that form expands into the same
# one-Citation-per-span addressing used elsewhere. Accept an optional repeated paragraph
# marker (`¶a-¶b`) and surrounding whitespace as lossless output variants. The
# compile/evolve gates, projection, briefing and dataset share this grammar.
CANONICAL_CITATION_RE = re.compile(
    r"\[cite:\s*(?P<sid>[^\s\]]+)\s*"
    r"¶\s*(?P<start>\d+)"
    r"(?:\s*-\s*¶?\s*(?P<end>\d+))?\s*\]"
)
CANONICAL_CITATION_MARKER_RE = re.compile(
    r"\[cite:\s*(?P<sid>[^\s\]]+)\s*"
    r"(?P<spans>¶\s*\d+(?:\s*-\s*¶?\s*\d+)?"
    r"(?:\s*,\s*¶?\s*\d+(?:\s*-\s*¶?\s*\d+)?)*)\s*\]"
)
_CANONICAL_CITATION_SPAN_RE = re.compile(
    r"¶?\s*(?P<start>\d+)(?:\s*-\s*¶?\s*(?P<end>\d+))?"
)


class Citation(BaseModel):
    source_id: SourceId
    block_start: int
    block_end: int


def _citation_spans(spans: str) -> tuple[tuple[int, int], ...]:
    """Parse the already grammar-checked span list inside one canonical marker."""
    parsed: list[tuple[int, int]] = []
    for raw_span in spans.split(","):
        match = _CANONICAL_CITATION_SPAN_RE.fullmatch(raw_span.strip())
        if match is None:  # Defensive: callers only pass MARKER_RE's `spans` group.
            continue
        start = int(match.group("start"))
        end = int(match.group("end")) if match.group("end") is not None else start
        parsed.append((start, end))
    return tuple(parsed)


def iter_canonical_citations(text: str) -> Iterable[Citation]:
    """Yield structured canonical citations, expanding same-source grouped spans.

    A grouped marker remains one markdown marker at rest, but becomes one Citation per
    span for projection, provenance checks, and consumer views. Single-span markers keep
    their existing result exactly.
    """
    for marker in CANONICAL_CITATION_MARKER_RE.finditer(text):
        source_id = SourceId(marker.group("sid"))
        for start, end in _citation_spans(marker.group("spans")):
            yield Citation(source_id=source_id, block_start=start, block_end=end)


def normalize_canonical_citation_markers(text: str) -> tuple[str, int]:
    """Render accepted citations with one stable spelling and expand grouped spans."""
    changes = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changes
        rendered_spans: list[str] = []
        for start, end in _citation_spans(match.group("spans")):
            rendered = f"[cite: {match.group('sid')} ¶{start}"
            if end != start:
                rendered += f"-{end}"
            rendered_spans.append(rendered + "]")
        rendered = " ".join(rendered_spans)
        changes += int(rendered != match.group(0))
        return rendered

    return CANONICAL_CITATION_MARKER_RE.sub(replace, text), changes


def resolve_canonical_citation_source_prefixes(
    text: str, valid_source_ids: Iterable[str]
) -> tuple[str, int, set[str]]:
    """Repair a truncated citation id only when it identifies one real source.

    This is deliberately a migration primitive, not fuzzy matching: an exact id is left
    alone; an invalid id is expanded only when it is a prefix of exactly one valid id.
    Ambiguous and unrelated ids remain byte-for-byte unchanged and are reported so the
    caller can fail closed instead of guessing provenance.
    """

    valid = set(valid_source_ids)
    changes = 0
    unresolved: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        nonlocal changes
        source_id = match.group("sid")
        if source_id in valid:
            return match.group(0)
        candidates = [candidate for candidate in valid if candidate.startswith(source_id)]
        if len(candidates) != 1:
            unresolved.add(source_id)
            return match.group(0)
        changes += 1
        return match.group(0).replace(source_id, candidates[0], 1)

    return CANONICAL_CITATION_MARKER_RE.sub(replace, text), changes, unresolved


class Claim(BaseModel):
    anchor: AnchorId
    text: str
    citations: list[Citation] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    doc_id: DocumentId
    path: str
    frontmatter: dict = Field(default_factory=dict)
    body: str
