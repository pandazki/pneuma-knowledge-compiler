"""Evolve gate profile — independent of the daily compile gate (schema-evolve §2.4).

Same three structural checks as compile (anchor uniqueness / frontmatter / anchor coverage,
reused verbatim from `compile.gate`), but three checks change shape because a whole-KB
reorganization is not a forward-only single compile:

- **anchor continuity is repo-level, and never hard-rejects.** A base anchor must exist
  *somewhere* in the new repo, not at its old path (a moved claim keeps its anchor at a new
  home). An anchor that truly vanished — a merged/deleted claim — is not a violation; it is
  surfaced as a `DroppedAnchor` (with its original text) for the review page.
- **citations validate against the store for real.** Every citation newly introduced this
  reorganization is checked with `source_bounds(sid)` (block count, or None if the source
  is gone). A citation that appears VERBATIM anywhere in the base repo is grandfathered at
  the repo level — a moved claim carries its citation byte-for-byte, so it is exempt and
  never hits the store (evolve must not re-audit the whole KB on every run).
- **path ownership is against the NEW skill's templates**, passed in explicitly.

This profile shares compile's pure structural, citation-shape, claim-provenance and overview
checks. New/changed claims and newly broken dependants must reach provenance. Byte-identical
historical defects may move but never ground new claims. It also shares the rule that
an ARCHIVE RECORD is read-only (`check_archive_records`). A reorganization moves claims
between pages and renames families, and a record is neither material nor shape: it stays
byte-for-byte where the archive job left it, and the Owner unmakes that by unarchiving.

What it does NOT change shape for is the enabled components' own checks. A component's
gate check is a canonical FIELD invariant — an identity bound by one page only, two
speakers of one conversation never merged into one person — and canonical does not know
which channel wrote it. Evolve authors canonical exactly as a daily compile does, so the
same fan-out runs here (`component_gate_checks`), over evolve's changed documents against
the base it evolved from, and again at adopt over the reconciled tree against current main
(`evolve_service.adopt_evolve_job`). Without it a page evolve created could bind two
co-speakers, land through review, and then be grandfathered by every later compile.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from ..compile.documents import DOC_ID_KEY, parse_document
from ..compile.gate import (
    check_supersession,
    Violation,
    check_anchor_coverage,
    check_anchor_uniqueness,
    check_archive_records,
    check_citation_shape,
    check_claim_provenance,
    check_frontmatter,
)
from ..compile.patch import DraftDoc, PatchDraft, path_allowed
from ..compile.overview import check_overviews
from ..compile.transitions import _anchor_blocks
from ..components import registered_components
from ..domain.canonical import (
    CANONICAL_CITATION_MARKER_RE,
    CanonicalDocument,
    iter_canonical_citations,
)
from ..domain.ids import DocumentId, extract_anchors
from ..prompts import prompt

SourceBounds = Callable[[str], Awaitable[int | None]]


@dataclass(frozen=True)
class DroppedAnchor:
    """A base anchor that vanished from the new repo — a claim merged/deleted away. Carries
    its original text so the review page can show what was dropped."""

    anchor: str
    old_path: str
    text: str


def _base_anchor_texts(base_bodies: dict[str, str]) -> dict[str, tuple[str, str]]:
    """anchor id → (old_path, block_text) across the whole base repo."""
    out: dict[str, tuple[str, str]] = {}
    for path, body in base_bodies.items():
        for anchor, text in _anchor_blocks(body).items():
            out.setdefault(anchor, (path, text))
    return out


def _base_citation_markers(base_bodies: dict[str, str]) -> set[str]:
    """Every citation marker in the base repo — the verbatim grandfather set."""
    markers: set[str] = set()
    for body in base_bodies.values():
        markers.update(m.group(0) for m in CANONICAL_CITATION_MARKER_RE.finditer(body))
    return markers


def component_gate_checks(
    docs: Mapping[str, DraftDoc], base_docs: Mapping[str, DraftDoc]
) -> list["Violation"]:
    """Every enabled component's write-time judgement over one authoring channel's tree.

    The same fan-out `compile/gate.py` runs, called the same way — the whole file table on
    both sides, the component deciding for itself which of its family's pages this round
    touched (`compile/patch.py:touched_this_round`). Shared rather than re-derived, so a
    component's rules cannot hold on one canonical authoring channel and not another: an
    identity another page already binds is refused whether a daily compile, a whole-KB
    reorganization or an adopt merge is the thing writing it.

    A component that cannot judge the round says so (a readiness violation); the framework
    runs the checks and never knows what they test.
    """
    violations: list["Violation"] = []
    for component in registered_components():
        violations.extend(component.gate_checks(docs, base_docs))
    return violations


def _draft_doc(path: str, frontmatter: dict, body: str) -> DraftDoc:
    return DraftDoc(
        path=path,
        doc_id=DocumentId(str(frontmatter.get(DOC_ID_KEY, ""))),
        frontmatter=dict(frontmatter),
        body=body,
    )


def docs_from_files(files: Mapping[str, str]) -> dict[str, DraftDoc]:
    """A serialized file table as the document table the component seams are handed.

    The adopt merge produces FILES (it renders its result before it commits it), and a
    component gate check reads frontmatter and body. Parsing them back is that one
    conversion, and it is the same parser every canonical read uses.
    """
    out: dict[str, DraftDoc] = {}
    for path, text in files.items():
        frontmatter, body = parse_document(text)
        out[path] = _draft_doc(path, frontmatter, body)
    return out


def docs_from_canonical(documents: Sequence[CanonicalDocument]) -> dict[str, DraftDoc]:
    """A canonical document list as the same document table — the BASE side of an adopt
    check, where "base" is current main rather than a round's own starting draft."""
    return {
        doc.path: _draft_doc(doc.path, doc.frontmatter, doc.body) for doc in documents
    }


async def run_evolve_gate(
    draft: PatchDraft,
    *,
    source_bounds: SourceBounds,
    path_templates: list[str],
) -> tuple[list[Violation], list[DroppedAnchor]]:
    """Run the evolve gate over a reorganized draft.

    Returns `(violations, dropped)`: violations are hard (still-failing → the runner aborts),
    dropped anchors are informational (merged claims surfaced for review)."""
    docs = draft.documents()
    base_bodies = draft.base_bodies()
    violations: list[Violation] = []

    # 0. supersession links stay legal through a reorganization (compile/supersession.py):
    # a merged-away predecessor would leave its successor dangling for every later compile.
    violations.extend(check_supersession(docs, base_bodies))

    # 1. repo-level anchor continuity — a base anchor absent from the WHOLE new repo is a
    # dropped anchor (informational), never a violation.
    new_anchors: set[str] = set()
    for doc in docs.values():
        new_anchors.update(extract_anchors(doc.body))
    dropped: list[DroppedAnchor] = []
    for anchor, (old_path, text) in _base_anchor_texts(base_bodies).items():
        if anchor not in new_anchors:
            dropped.append(DroppedAnchor(anchor=anchor, old_path=old_path, text=text))

    # 2. citation legality against the store — only for citations NOT grandfathered at the
    # repo level (a verbatim base marker carried unchanged never touches `source_bounds`).
    grandfathered = _base_citation_markers(base_bodies)
    for path, doc in docs.items():
        for marker in CANONICAL_CITATION_MARKER_RE.finditer(doc.body):
            if marker.group(0) in grandfathered:
                continue  # moved/unchanged citation — exempt, no store call
            for citation in iter_canonical_citations(marker.group(0)):
                sid = str(citation.source_id)
                start = citation.block_start
                end = citation.block_end
                n = await source_bounds(sid)
                if n is None:
                    violations.append(
                        Violation(
                            "citation",
                            path,
                            prompt(
                                "gate.evolve.citation_unknown_source", source_id=sid
                            ),
                        )
                    )
                    continue
                if start > end or start < 0 or end >= n:
                    violations.append(
                        Violation(
                            "citation",
                            path,
                            prompt(
                                "gate.evolve.citation_out_of_range",
                                source_id=sid,
                                start=start,
                                end=end,
                                count=n,
                                last=n - 1,
                            ),
                        )
                    )

    # 3. anchor uniqueness / frontmatter / anchor coverage — reused verbatim from compile.
    violations.extend(check_anchor_uniqueness(docs))
    violations.extend(check_frontmatter(docs))
    violations.extend(check_anchor_coverage(docs))

    # 3b. Provenance belongs to canonical, regardless of the writing channel.
    violations.extend(check_citation_shape(docs))
    violations.extend(check_claim_provenance(docs, draft.base_documents()))
    violations.extend(
        Violation(kind, path, detail) for kind, path, detail in check_overviews(
            {path: doc.body for path, doc in docs.items()},
            base_bodies=base_bodies,
            budget=draft.overview_budget_chars,
        )
    )
    # The enabled components also judge their own families, as in a daily compile.
    violations.extend(component_gate_checks(docs, draft.base_documents()))

    # 3c. an ARCHIVE RECORD is left where it stands, byte-for-byte — the same rule the daily
    # compile gate holds, over the one draft that can move claims between documents. A
    # reorganization has nothing to say about a retired subject: the record is not material
    # it may re-file, and the owner unmakes the decision it states by unarchiving. Silent on
    # the untouched record every run carries through, which is what a reorganization leaves.
    violations.extend(check_archive_records(docs, draft.base_documents()))

    # 4. path ownership — against the NEW skill's templates.
    for path in docs:
        if not path_allowed(path, path_templates):
            violations.append(
                Violation(
                    "path",
                    path,
                    prompt(
                        "gate.evolve.path_not_owned",
                        templates=", ".join(path_templates),
                    ),
                )
            )

    return violations, dropped
