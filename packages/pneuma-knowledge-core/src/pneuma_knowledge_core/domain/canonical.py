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

# Canonical syntax is rendered as `¶a-b`. Accept an optional repeated paragraph
# marker (`¶a-¶b`) and surrounding whitespace as a lossless model-output variant.
# The compile gate, projection and UI dataset must share this exact grammar.
CANONICAL_CITATION_RE = re.compile(
    r"\[cite:\s*(?P<sid>[^\s\]]+)\s*"
    r"¶\s*(?P<start>\d+)"
    r"(?:\s*-\s*¶?\s*(?P<end>\d+))?\s*\]"
)


def normalize_canonical_citation_markers(text: str) -> tuple[str, int]:
    """Render every accepted canonical citation variant with one stable spelling."""
    changes = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changes
        start = int(match.group("start"))
        end_raw = match.group("end")
        rendered = f"[cite: {match.group('sid')} ¶{start}"
        if end_raw is not None and int(end_raw) != start:
            rendered += f"-{int(end_raw)}"
        rendered += "]"
        changes += int(rendered != match.group(0))
        return rendered

    return CANONICAL_CITATION_RE.sub(replace, text), changes


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

    return CANONICAL_CITATION_RE.sub(replace, text), changes, unresolved


class Citation(BaseModel):
    source_id: SourceId
    block_start: int
    block_end: int


class Claim(BaseModel):
    anchor: AnchorId
    text: str
    citations: list[Citation] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    pneuma_id: DocumentId
    path: str
    frontmatter: dict = Field(default_factory=dict)
    body: str
