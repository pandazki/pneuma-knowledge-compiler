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

from pydantic import BaseModel, Field

from .ids import AnchorId, DocumentId, SourceId


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
