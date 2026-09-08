"""Resolve canonical claim references to source locators in one caller-scoped snapshot.

This is navigation, not a provenance admission gate or an entailment check. In particular,
an admitted mechanical record may have no L0 locator. The supplied documents are the whole
resolution scope: no store is read, no archived page is added, and no supersession is
followed. Query callers pass their pinned, archive-scoped documents.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from ..compile.anchor_ops import anchored_blocks
from ..compile.overview import grounding_references, overview_anchors
from ..domain.canonical import CanonicalDocument, Citation, iter_canonical_citations
from ..domain.ids import extract_anchors

ClaimKey = tuple[str, str]
_ClaimT = TypeVar("_ClaimT")


@dataclass(frozen=True)
class ProvenanceResolution:
    citations: tuple[Citation, ...] = ()
    missing_anchors: tuple[str, ...] = ()
    ambiguous_anchors: tuple[str, ...] = ()
    root_found: bool = True
    # Set only by query-row hydration; locator resolution itself has no index text to judge.
    text_matches: bool | None = None

    @property
    def source_backed(self) -> bool:
        """At least one source was reached; other branches may still be unresolved."""
        return bool(self.citations)


class CanonicalProvenance:
    """A pure, reusable locator resolver over exactly one supplied document set.

    References name ledger anchors repository-wide, using the write gate's grammar and
    self-reference exclusion. Overview blocks can be roots but never reference targets.
    Duplicate identities are ambiguous even if their blocks happen to be byte-identical.
    Missing/ambiguous branches contribute no locator and remain visible in the result.

    A per-root iterative walk visits each reachable identity once. Source-free cycles
    resolve to no citations; cycles with a path to a source retain that source. Completed
    root results alone are cached, so a cycle cannot leave a partially resolved node cached.
    """

    def __init__(self, documents: Iterable[CanonicalDocument]) -> None:
        docs = sorted(documents, key=lambda doc: doc.path)
        counts = Counter(anchor for doc in docs for anchor in extract_anchors(doc.body))
        self._ambiguous = {anchor for anchor, count in counts.items() if count > 1}
        self._blocks: dict[ClaimKey, str] = {}
        self._ledger: dict[str, ClaimKey] = {}
        self._cache: dict[ClaimKey, ProvenanceResolution] = {}
        for doc in docs:
            overview = overview_anchors(doc.body)
            for block in anchored_blocks(doc.body):
                for anchor in extract_anchors(block):
                    key = (doc.path, anchor)
                    self._blocks[key] = block
                    if anchor not in overview and anchor not in self._ambiguous:
                        self._ledger[anchor] = key

    def has_claim(self, document_path: str, anchor: str) -> bool:
        """Whether this exact root is present, independently of ambiguous dependencies."""
        return (str(document_path), str(anchor)) in self._blocks

    def resolve(self, document_path: str, anchor: str) -> ProvenanceResolution:
        root = (str(document_path), str(anchor))
        if root in self._cache:
            return self._cache[root]
        if root not in self._blocks:
            return ProvenanceResolution(missing_anchors=(root[1],), root_found=False)
        if root[1] in self._ambiguous:
            return ProvenanceResolution(ambiguous_anchors=(root[1],))

        citations: dict[tuple[str, int, int], Citation] = {}
        missing: set[str] = set()
        ambiguous: set[str] = set()
        visited: set[ClaimKey] = set()
        pending = [root]
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            block = self._blocks[key]
            for citation in iter_canonical_citations(block):
                locator = (str(citation.source_id), citation.block_start, citation.block_end)
                citations.setdefault(locator, citation)
            references = grounding_references(block) - set(extract_anchors(block))
            # The parser returns a set. Reverse push gives stable lexical traversal while
            # preserving each block's direct citation order and the root's citations first.
            for reference in sorted(references, reverse=True):
                if reference in self._ambiguous:
                    ambiguous.add(reference)
                elif reference not in self._ledger:
                    missing.add(reference)
                else:
                    pending.append(self._ledger[reference])
        result = ProvenanceResolution(
            citations=tuple(citations.values()),
            missing_anchors=tuple(sorted(missing)),
            ambiguous_anchors=tuple(sorted(ambiguous)),
        )
        self._cache[root] = result
        return result


def hydrate_claim_citations(
    claims: Sequence[_ClaimT],
    documents: Iterable[CanonicalDocument] | None,
) -> tuple[list[_ClaimT], dict[ClaimKey, ProvenanceResolution]]:
    """Replace dataclass rows' locators from canonical; return every resolution for audit.

    All other row fields, including text, are preserved. A known root is hydrated only if
    its index text equals its current V1 or V2 projected display text. A stale text or
    missing root keeps its existing row and reports the mismatch; optional enrichment does
    not replace the lane's canonical scoping policy. None means no canonical snapshot was
    supplied and leaves rows untouched. Even a text match establishes navigation, not
    semantic entailment of the authored claim by its source.
    """
    if documents is None:
        return list(claims), {}
    # Local import: projection uses this helper after its own module is initialized. The
    # projector remains the sole definition of both supported display forms.
    from .projection import PROJECTION_V1, PROJECTION_V2, project_document_claims

    docs = list(documents)
    resolver = CanonicalProvenance(docs)
    display_texts: dict[ClaimKey, set[str]] = {}
    for doc in docs:
        for strategy in (PROJECTION_V1, PROJECTION_V2):
            for projected in project_document_claims(doc, strategy):
                key = (projected.document_path, str(projected.anchor))
                display_texts.setdefault(key, set()).add(projected.text)
    resolutions: dict[ClaimKey, ProvenanceResolution] = {}
    hydrated: list[_ClaimT] = []
    for claim in claims:
        key = (str(claim.document_path), str(claim.anchor))
        result = resolver.resolve(*key)
        if result.root_found:
            result = replace(result, text_matches=claim.text in display_texts.get(key, ()))
        resolutions[key] = result
        hydrated.append(
            replace(claim, citations=result.citations)
            if result.root_found and result.text_matches else claim
        )
    return hydrated, resolutions
