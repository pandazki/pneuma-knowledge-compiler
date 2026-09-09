"""Agent citations: parse real addresses, then validate against tenant-scoped authority.

The service supplies block counts and canonical anchor paths from this user's stores.
These pure helpers share the canonical citation grammar (I4) and the lane's manifest
containment rule; a direct read changes admission, never the evidence handed by the lane.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, iter_canonical_citations
from ..domain.consultation import EvidenceRef, dedup_evidence, parse_span_ref, span_ref
from .citation_alias import resolve_handles
from .consultation import _admitted

_BRACKET_RE = re.compile(r"\[cite:\s*([^\]]*)\]")
_ANCHOR_RE = re.compile(r"(?<![\w:])c:([0-9a-zA-Z_-]+)")
# Free-text answers may group several sources in one bracket. Split only at a NEW source;
# the shared canonical parser still owns every span, including same-source grouped spans.
_NEXT_SOURCE_RE = re.compile(r"[,;]\s*(?=[^\s,;¶]+\s+¶)")


class UnresolvedCitation(ValueError):
    """The named marker cannot become a consultation address; nothing is recorded."""


def answer_addresses(answer: str, handles: dict[str, str]) -> tuple[EvidenceRef, ...]:
    """Resolve handles and parse every citation, refusing malformed or spanless markers."""
    resolved = resolve_handles(answer, handles)
    refs: list[EvidenceRef] = []
    cursor = 0
    for bracket in _BRACKET_RE.finditer(resolved):
        refs.extend(_bare_anchors(resolved[cursor:bracket.start()]))
        cursor = bracket.end()
        body = bracket.group(1).strip()
        if _ANCHOR_RE.fullmatch(body):
            refs.append(EvidenceRef(kind="claim", ref=body))
            continue
        for part in _NEXT_SOURCE_RE.split(body):
            marker = f"[cite: {part.strip()}]"
            if CANONICAL_CITATION_MARKER_RE.fullmatch(marker) is None:
                raise UnresolvedCitation(f"unresolved citation: {bracket.group(0)}")
            refs.extend(
                span_ref(str(c.source_id), c.block_start, c.block_end)
                for c in iter_canonical_citations(marker)
            )
    refs.extend(_bare_anchors(resolved[cursor:]))
    return dedup_evidence(refs)


def _bare_anchors(text: str) -> list[EvidenceRef]:
    if "[cite:" in text:
        raise UnresolvedCitation(f"unresolved citation: {text[text.index('[cite:'):]}")
    return [
        EvidenceRef(kind="claim", ref=f"c:{match.group(1)}")
        for match in _ANCHOR_RE.finditer(text)
    ]


def admit_resolving_citations(
    refs: tuple[EvidenceRef, ...],
    manifest: tuple[EvidenceRef, ...],
    *,
    block_counts: Mapping[str, int],
    anchor_paths: Mapping[str, str],
) -> tuple[EvidenceRef, ...]:
    """Every address must resolve; manifest membership determines origin, not admission.

    Counts and paths are observations of this tenant's stores, never supplied by the agent.
    Anchors use bare ids as keys. A bad marker refuses the whole answer, so its pending
    hand-over remains available for correction instead of producing a partial record.
    """
    anchors, spans = _admitted(manifest)
    admitted: list[EvidenceRef] = []
    for ref in refs:
        if ref.kind == "claim":
            path = anchor_paths.get(ref.ref.removeprefix("c:"))
            if path is None:
                raise UnresolvedCitation(f"unresolved citation: {ref.ref} — no canonical anchor")
            handed = ref.ref in anchors
            admitted.append(replace(
                ref, path=path, kind=anchors.get(ref.ref, "claim"),
                origin="handed" if handed else "direct",
            ))
            continue
        parsed = parse_span_ref(ref.ref)
        if parsed is None:
            raise UnresolvedCitation(f"unresolved citation: {ref.ref}")
        sid, start, end = parsed
        count = block_counts.get(sid)
        if count is None or not 1 <= start <= end <= count:
            raise UnresolvedCitation(
                f"unresolved citation: {ref.ref} — source missing or interval outside its block range"
            )
        kind = next((kind for a, b, kind in spans.get(sid, ()) if a <= start <= end <= b), None)
        admitted.append(replace(
            ref, kind=kind or "window", origin="handed" if kind is not None else "direct",
        ))
    return dedup_evidence(admitted)
