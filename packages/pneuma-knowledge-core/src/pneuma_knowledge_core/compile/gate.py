"""Mechanical compile gate (architecture.md §8): all checks hard-reject.

Five machine checks, each returning structured violations (fed back verbatim for one
repair round by the runner):

1. anchor continuity — a base anchor must not vanish. v1 has no authorized deletion
   channel; the model may only add or revise, never remove. The ONE exemption is the
   overview region's own anchors: that region is rewritten whole and its blocks carry no
   permanent identity, so a rewrite retires them by design (check 4c holds the line that
   nothing was actually lost). Ledger anchors stay strict.
2. anchor uniqueness — every anchor is unique across the whole repo.
3. citation legality — every citation INTRODUCED this round names a source in this
   compile's supplied set, with a block interval inside that source's bounds. A citation
   carried over verbatim from the base body is grandfathered (it was validated when first
   committed); a later forward-only compile that does not supply that old source must not
   retroactively reject it (M5 Path B: new source compiled while old canonical stands).
3b. citation SHAPE — anything spelled `[cite: …]` must parse completely as a locator. See
   `check_citation_shape`: the legality check above can only judge markers it can read, so
   an unreadable one used to pass as provenance by looking like some.
4. frontmatter completeness — doc_id / type / slug present.
4b. anchor coverage — every content block carries an anchor (else it is browse-visible
   canonical text that never enters the L3 claim index — an orphaned claim).
4e. claim TEXT carries no machinery — no HTML comment, no invented `__AUTO__` / `__NEW__`
   anchor placeholder, anywhere before a block's trailing system markers. Judged for the
   pages this round CHANGED: a legacy page nobody touched keeps its bytes (the only channel
   that could repair it is a compile that is writing it anyway).
4c. the OVERVIEW region — bounded in size, grounded in the ledger, four slots and no others
   (compile/overview.py). The one region a compile may rewrite whole, and the checks are
   what make that safe: it may hold nothing the ledger does not already carry. Judged for
   the regions this round WROTE, like the citation checks above.
4d. the overview a document OWES — a page this round touched whose ledger has passed the
   threshold must carry one (`definition` at least). 4c bounds the head from above; this
   bounds the ledger from below. Judged for the pages this round CHANGED, never for the
   library at large.
5. path ownership — every document path matches a skill path template, or is one of an owned
   page's closed volumes (`<owned document>/aNN.md`; see patch.history_volume_owner).
5b. closed volume — a closed volume may not be modified by a compile (`volume_closed`).
5c. the ARCHIVE (`archive/`, docs/design/archive.md) — a different rule and a different word:
   nothing under `archive/` changes in a compile, and a new document may take neither a live
   path an archived document shadows nor an archived document's TITLE. All three are
   `archived_path`.
6. supersession — a `supersedes` marker names an existing anchor, never itself; chains are
   linear and acyclic; a superseded claim is frozen; the superseding claim carries new
   evidence (compile/supersession.py).
7. component checks — every enabled index component judges the documents of its family
   (components/__init__.py); the framework runs them, it does not know what they test.

The gate is the mechanism; there is no prompt asking the model to "please remember".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.archive import (
    ARCHIVE_OF_KEY,
    archived_path,
    is_archive_record,
    is_archived_path,
    normalize_title,
    shadowed_paths,
)
from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, iter_canonical_citations
from ..domain.ids import extract_anchors
from ..domain.source import NormalizedSource
from ..prompts import prompt
from ..components import registered_components
from .anchor_ops import (
    anchored_blocks,
    missing_anchors,
    text_machinery_problems,
    unanchored_blocks,
)
from .documents import DOC_ID_KEY, LEGACY_DOC_ID_KEYS
# Re-exported: the link grammar and its two coordinate functions now live in
# `compile.links` — three write paths need them (the gate, rollover's re-rendering, and
# the overview's connection links) and they cannot all import the gate. Every existing
# importer keeps reading them from here.
from .links import _MD_LINK_RE, _render_relative, _resolve_relative  # noqa: F401
from .overview import (
    OVERVIEW_BUDGET_CHARS,
    OVERVIEW_REQUIRED_AFTER_CLAIMS,
    check_overview_required,
    check_overviews,
    overview_anchors,
)
from .patch import (
    PatchDraft,
    archived_titles,
    document_title,
    history_volume_owner,
    path_allowed,
    touched_this_round,
)
from .supersession import block_anchor, block_by_anchor, block_supersedes

REQUIRED_FRONTMATTER = (DOC_ID_KEY, "type", "slug")

# Accepted-on-read spellings per required key. A document committed before the id key was
# renamed carries `pneuma_id`; loads normalize it (compile.documents.normalize_frontmatter),
# but the gate accepts the legacy spelling directly too, so an un-normalized legacy
# document is never hard-rejected for "missing" an id it does have. Writes emit `doc_id`
# only — this is a read-side alias, not a second supported field name.
_FRONTMATTER_READ_ALIASES: dict[str, tuple[str, ...]] = {DOC_ID_KEY: LEGACY_DOC_ID_KEYS}

# Anything a reader would take for a citation: the `[cite:` opener through the next `]`.
# Deliberately looser than `CANONICAL_CITATION_MARKER_RE` — its whole job is to catch the
# strings that regex does NOT match, which is why it cannot be that regex.
_CITE_BRACKET_RE = re.compile(r"\[cite:(?P<inner>[^\]]*)\]")

# An anchor reference (`c:<id>`) written where a source locator belongs. It is a legal
# provenance form in the wrong container, so it gets its own violation text: telling an
# author "this does not parse" when the fix is "move it outside the brackets" is a riddle.
_ANCHOR_IN_MARKER_RE = re.compile(r"^\s*c:(?P<anchor>[0-9a-zA-Z_-]+)\s*$")


@dataclass(frozen=True)
class Violation:
    kind: str  # anchor_continuity | anchor_uniqueness | citation | claim_text | link | frontmatter | path | volume_closed | archived_path
    path: str
    detail: str

    def render(self) -> str:
        return f"[{self.kind}] {self.path}: {self.detail}"


def check_anchor_uniqueness(docs: Mapping[str, object]) -> list[Violation]:
    """Every anchor is unique across the whole repo (shared by compile + evolve gates)."""
    violations: list[Violation] = []
    seen: dict[str, str] = {}
    for path, doc in docs.items():
        for anchor in extract_anchors(doc.body):
            if anchor in seen:
                violations.append(
                    Violation(
                        "anchor_uniqueness",
                        path,
                        prompt(
                            "gate.anchor_uniqueness",
                            anchor=anchor,
                            other_path=seen[anchor],
                        ),
                    )
                )
            else:
                seen[anchor] = path
    return violations


def check_frontmatter(docs: Mapping[str, object]) -> list[Violation]:
    """doc_id / type / slug present on every document (shared by compile + evolve gates)."""
    violations: list[Violation] = []
    for path, doc in docs.items():
        for key in REQUIRED_FRONTMATTER:
            spellings = (key, *_FRONTMATTER_READ_ALIASES.get(key, ()))
            if not any(
                str(doc.frontmatter.get(spelling, "")).strip() for spelling in spellings
            ):
                violations.append(
                    Violation(
                        "frontmatter",
                        path,
                        prompt("gate.frontmatter_missing", key=key),
                    )
                )
    return violations


def check_archive_records(
    docs: Mapping[str, object], base_docs: Mapping[str, object]
) -> list[Violation]:
    """No round writes on an ARCHIVE RECORD. Shared by the compile + evolve gates.

    The record is a live document in every other respect — it is in the outline,
    `read_document` answers with it, the projection indexes its claims and a lane answers
    with them — so nothing else in either gate refuses a diff on it. What refuses one is
    this: it states a decision the owner made, in a page whose every byte a mechanical
    channel derived, and the owner unmakes it by unarchiving.

    Shared rather than written twice because the rule is about CANONICAL and not about one
    writing channel: a daily compile and a whole-library reorganization are equally unable
    to move a claim out of a record, rename its family, or edit the reason it carries. Both
    write faces refuse the write up front (`PatchDraft._refuse_archive_record`); this is the
    final arbiter over the produced draft, and it is silent on a record nobody touched —
    which is exactly what a reorganization does to one.
    """
    violations: list[Violation] = []
    for path, doc in docs.items():
        base_doc = base_docs.get(path)
        if not is_archive_record(doc) and not (
            base_doc is not None and is_archive_record(base_doc)
        ):
            continue
        if not touched_this_round(doc, base_doc):
            continue
        frontmatter = (base_doc or doc).frontmatter or {}
        violations.append(
            Violation(
                "archived_path",
                path,
                prompt(
                    "gate.archive_record",
                    archived=str(frontmatter.get(ARCHIVE_OF_KEY) or archived_path(path)),
                ),
            )
        )
    return violations


def check_anchor_coverage(docs: Mapping[str, object]) -> list[Violation]:
    """Every content block carries an anchor, or it is browse-visible canonical text that
    never enters the L3 claim index (an orphaned claim). Shared by compile + evolve gates."""
    violations: list[Violation] = []
    for path, doc in docs.items():
        for orphan in unanchored_blocks(doc.body):
            preview = orphan.strip().splitlines()[0][:40] if orphan.strip() else ""
            violations.append(
                Violation(
                    "anchor_coverage",
                    path,
                    prompt("gate.anchor_coverage", preview=preview),
                )
            )
    return violations


def check_claim_text_machinery(
    docs: Mapping[str, object],
    base_bodies: Mapping[str, str],
    *,
    path_templates: Sequence[str] = (),
) -> list[Violation]:
    """No claim's TEXT carries the system's own machinery — the final arbiter behind the
    write faces' `refuse_text_machinery`.

    A claim says things in words. Anchors and supersedes markers are the system's, written at
    the END of a block; an HTML comment anywhere before them is either a model minting
    identity by hand or — the case this was written for — a model gluing two claims together
    with an invented `<!-- c:__AUTO__ -->` separator. That placeholder is not an anchor
    (`ANCHOR_MARK_RE` wants hex), so every anchor guard looked through it and the anchoring
    pass simply appended a real anchor after it, committing two statements as one claim with a
    dead marker in the middle.

    Judged for the pages this round CHANGED, never for the library at large. A legacy page
    nobody wrote keeps its bytes: the only channel that can repair a claim is a compile that
    is already writing that page, and a repository-wide floor would abort compiles that have
    nothing to do with the defect. A page this round DID write answers for what it carries —
    the model has `edit_claim` in hand and the refusal names the corrective action.

    Rollover volumes are exempt for the reason 4d exempts them: the corrective action does not
    exist there (`edit_claim` refuses a closed volume), and a changed volume is already gate
    5b's violation.
    """
    violations: list[Violation] = []
    for path, doc in docs.items():
        base = base_bodies.get(path)
        if base is not None and doc.body == base:
            continue
        if history_volume_owner(path, list(path_templates)) is not None:
            continue
        for found, preview in text_machinery_problems(doc.body):
            violations.append(
                Violation(
                    "claim_text",
                    path,
                    prompt("gate.claim_text_machinery", found=found, preview=preview),
                )
            )
    return violations


def check_citation_shape(docs: Mapping[str, object]) -> list[Violation]:
    """Every `[cite: …]` in the repo parses COMPLETELY as a locator, or it is a violation.

    The legality check judges the citations it can read. That is a silent selection: a marker
    the grammar does not match is not an illegal citation, it is not a citation at all — so
    it was never judged, and the provenance check three steps down accepted the claim
    carrying it because a `[cite:` had been typed. A marker with the LOOK of provenance and
    no readable locator is worse than a missing one: it survives review by resembling an
    answer, and it resolves to nothing for every reader downstream.

    Judged over the whole repository, with no grandfathering. The malformed markers this was
    written for are already committed, and exempting them would preserve exactly the state
    the check exists to end; the next compile that touches such a document is asked to fix
    it, which is the only channel that can.
    """
    violations: list[Violation] = []
    for path, doc in docs.items():
        for bracket in _CITE_BRACKET_RE.finditer(doc.body):
            marker = bracket.group(0)
            # Full-match, not search: a parse that leaves bytes over inside the brackets read
            # a locator the author did not write.
            if CANONICAL_CITATION_MARKER_RE.fullmatch(marker) is not None:
                continue
            anchor = _ANCHOR_IN_MARKER_RE.match(bracket.group("inner"))
            if anchor is not None:
                violations.append(
                    Violation(
                        "citation",
                        path,
                        prompt(
                            "gate.citation_anchor_in_marker",
                            marker=marker,
                            anchor=anchor.group("anchor"),
                        ),
                    )
                )
                continue
            violations.append(
                Violation(
                    "citation",
                    path,
                    prompt("gate.citation_unparsable_marker", marker=marker),
                )
            )
    return violations


def check_supersession(
    docs: Mapping[str, object], base_bodies: Mapping[str, str]
) -> list[Violation]:
    """Every `supersedes` marker in the repository is a legal, linear, evidenced link.

    Judged repository-wide (like anchor uniqueness): a chain may cross documents — the
    open volume supersedes a claim that closed into an earlier one — so a per-document view
    would miss exactly the links that matter. Seven rejections:

    - `supersession_target_missing`: the named anchor exists nowhere;
    - `supersession_self`: a claim naming itself;
    - `supersession_multiple`: one block naming several predecessors (one claim
      supersedes one claim);
    - `supersession_not_linear`: two claims naming the same predecessor;
    - `supersession_cycle`: a → b → … → a;
    - `supersession_frozen`: a claim that was ALREADY superseded in the base changed its
      text — superseded history is immutable, like a rollover volume;
    - `supersession_without_evidence`: the superseding block carries no `[cite:]` of its
      own. "Only new evidence may supersede an old state" is enforced here, not asked.
    """
    violations: list[Violation] = []
    bodies = {path: doc.body for path, doc in docs.items()}
    by_anchor = block_by_anchor(bodies)
    successors: dict[str, list[tuple[str, str]]] = {}  # old → [(path, new)]
    links: dict[str, str] = {}  # old → new (first seen), for the cycle walk

    for path, doc in docs.items():
        for block in anchored_blocks(doc.body):
            olds = block_supersedes(block)
            if not olds:
                continue
            new = block_anchor(block) or "?"
            if len(olds) > 1:
                violations.append(
                    Violation(
                        "supersession",
                        path,
                        prompt("gate.supersession_multiple", anchor=new, targets=", ".join(olds)),
                    )
                )
            old = olds[0]
            if old == new:
                violations.append(
                    Violation("supersession", path, prompt("gate.supersession_self", anchor=new))
                )
                continue
            if old not in by_anchor:
                violations.append(
                    Violation(
                        "supersession",
                        path,
                        prompt("gate.supersession_target_missing", anchor=new, target=old),
                    )
                )
                continue
            if CANONICAL_CITATION_MARKER_RE.search(block) is None:
                violations.append(
                    Violation(
                        "supersession",
                        path,
                        prompt("gate.supersession_without_evidence", anchor=new, target=old),
                    )
                )
            successors.setdefault(old, []).append((path, new))
            links.setdefault(old, new)

    for old, heads in successors.items():
        if len(heads) > 1:
            violations.append(
                Violation(
                    "supersession",
                    heads[0][0],
                    prompt(
                        "gate.supersession_not_linear",
                        target=old,
                        anchors=", ".join(new for _, new in heads),
                    ),
                )
            )

    for start in links:
        seen = {start}
        cursor = start
        while cursor in links:
            cursor = links[cursor]
            if cursor in seen:
                violations.append(
                    Violation(
                        "supersession",
                        by_anchor[start][0],
                        prompt("gate.supersession_cycle", anchor=start),
                    )
                )
                break
            seen.add(cursor)

    # Frozen: a claim that already HAD a successor in the base keeps its bytes.
    base_by_anchor = block_by_anchor(base_bodies)
    already_superseded = {
        old
        for body in base_bodies.values()
        for block in anchored_blocks(body)
        for old in block_supersedes(block)
    }
    for old in already_superseded:
        before = base_by_anchor.get(old)
        after = by_anchor.get(old)
        if before is None or after is None:
            continue  # continuity is judged by check 1
        if before[1] != after[1]:
            violations.append(
                Violation(
                    "supersession",
                    after[0],
                    prompt("gate.supersession_frozen", anchor=old, successor=links.get(old, "?")),
                )
            )
    return violations


def overview_required_violations(
    draft: PatchDraft,
    *,
    threshold: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
) -> list[Violation]:
    """The pages this round touched that owe an overview — the WHOLE judgement, once.

    The pure half (what counts as touched, what counts as a ledger claim, what counts as
    having a head) lives in `compile/overview.py`; this is where it meets the two things
    only the draft knows: the Violation type, and which paths are frozen rollover volumes.

    A volume is exempt because the corrective action does not exist for it: `rewrite_overview`
    refuses a closed volume, so asking one for a head would name an action the mechanism
    itself forbids — and a volume is never legitimately changed by a compile anyway (gate 5b
    refuses that on its own terms, which is the violation that should be read).

    Called from BOTH faces — `finish_compile` in the runner's tool loop, and the gate below —
    so the early refusal and the final arbiter cannot come to different conclusions.
    """
    documents = {
        path: doc
        for path, doc in draft.documents().items()
        if history_volume_owner(path, draft.path_templates) is None
    }
    return [
        Violation("overview", path, detail)
        for path, detail in check_overview_required(
            documents, draft.base_documents(), threshold=threshold
        )
    ]


def run_gate(
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    *,
    alias_map: dict[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
    overview_budget_chars: int = OVERVIEW_BUDGET_CHARS,
    overview_required_after_claims: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
) -> list[Violation]:
    docs = draft.documents()
    base_bodies = draft.base_bodies()
    violations: list[Violation] = []

    # 1. anchor continuity (base anchors may not disappear; deleted docs lose all).
    new_bodies = draft.new_bodies()
    for path, base_body in base_bodies.items():
        current = new_bodies.get(path, "")
        # The overview region's base anchors are the one authorized removal: `rewrite_overview`
        # replaces the whole region and mints fresh ids for it. Computed from the BASE body, so
        # a ledger anchor can never be laundered into the exemption by moving it into a region
        # this round wrote.
        for anchor in missing_anchors(
            base_body, current, allowed_removals=overview_anchors(base_body)
        ):
            violations.append(
                Violation(
                    "anchor_continuity",
                    path,
                    prompt("gate.anchor_continuity", anchor=anchor),
                )
            )

    # 2. anchor uniqueness across the whole repo.
    violations.extend(check_anchor_uniqueness(docs))

    # 3. citation legality — judge only citations introduced this round (a verbatim
    # carry-over from the base body was already validated at its own commit).
    current_bounds = {str(s.raw.source_id): len(s.blocks) for s in sources}
    bounds = dict(known_source_bounds or {})
    bounds.update(current_bounds)
    # At the compile boundary the model cites short per-job handles (`sNN`); resolve each
    # to its real source id before validating (a real id is passed through). Both forms
    # are accepted — a scripted/real model may cite either.
    alias_map = alias_map or {}
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        for marker in CANONICAL_CITATION_MARKER_RE.finditer(doc.body):
            # Preserve the existing single-span grandfather rule: only a byte-identical
            # marker already present in this document's base body is exempt.
            grandfathered = known_source_bounds is None and marker.group(0) in base_body
            for citation in iter_canonical_citations(marker.group(0)):
                if grandfathered:
                    continue
                sid = alias_map.get(str(citation.source_id), str(citation.source_id))
                start = citation.block_start
                end = citation.block_end
                if sid not in bounds:
                    violations.append(
                        Violation(
                            "citation",
                            path,
                            prompt("gate.citation_unknown_source", source_id=sid),
                        )
                    )
                    continue
                n = bounds[sid]
                if start > end or start < 0 or end >= n:
                    violations.append(
                        Violation(
                            "citation",
                            path,
                            prompt(
                                "gate.citation_out_of_range",
                                source_id=sid,
                                start=start,
                                end=end,
                                count=n,
                                last=n - 1,
                            ),
                        )
                    )

    # 3b. citation SHAPE — before provenance, because provenance counts markers it cannot
    # read as evidence, and this is what tells the two apart.
    violations.extend(check_citation_shape(docs))

    # 3c. PROVENANCE on newly introduced claims. The one invariant the gate never actually
    # enforced: it validated the citations that existed but never required a claim to have
    # one, so an uncited assertion committed cleanly into the only non-rebuildable layer.
    # Judged per NEW anchor (present now, absent from the base body) — claims carried over
    # from base keep whatever provenance they were committed with.
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        base_anchors = set(extract_anchors(base_body))
        # An overview block's provenance is judged by 4c instead, and judged harder: it must
        # reference a LEDGER anchor from anywhere in the repository, where this check only
        # knows the anchors this one document had before the round. Running both would reject
        # the legitimate case the overview exists for — a head resting on a claim filed under
        # another subject.
        region_anchors = overview_anchors(doc.body)
        for block in anchored_blocks(doc.body):
            if set(extract_anchors(block)) & region_anchors:
                continue
            anchors = [a for a in extract_anchors(block) if a not in base_anchors]
            if not anchors:
                continue  # pre-existing claim, or no anchor of its own
            if CANONICAL_CITATION_MARKER_RE.search(block):
                continue
            # The skill allows a second legitimate provenance: a claim derived from EXISTING
            # canonical rather than from this round's material (§8 "link back to this round's
            # source or to existing canonical"). There is no `[cite:]` form for that, so
            # referencing the existing
            # anchor it derives from satisfies the requirement. Without this the rule would
            # be stricter than the invariant it enforces.
            if any(f"c:{a}" in block for a in base_anchors):
                continue
            preview = " ".join(block.split())[:48]
            violations.append(
                Violation(
                    "citation",
                    path,
                    prompt(
                        "gate.claim_without_provenance",
                        preview=preview,
                        anchor=anchors[0],
                    ),
                )
            )

    # 3d. INTER-DOCUMENT LINK targets must exist. Markdown links are what the projection
    # layer turns into knowledge-graph edges, i.e. the hops available when direct retrieval
    # fails. A link to a path that does not exist is a dead end in that graph — and the model
    # does produce them (it links to a subject it believes ought to exist without creating
    # it). Judged only for links introduced this round; only `.md` targets are treated as
    # canonical links, so external URLs are untouched.
    known_paths = set(docs)
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        for m in _MD_LINK_RE.finditer(doc.body):
            href = m.group(1)
            if m.group(0) in base_body or not href.endswith(".md") or "://" in href:
                continue
            target = _resolve_relative(path, href)
            if target == path:
                violations.append(
                    Violation(
                        "link",
                        path,
                        prompt("gate.link_self_reference", href=href),
                    )
                )
                continue
            if target not in known_paths:
                violations.append(
                    Violation(
                        "link",
                        path,
                        prompt("gate.link_dead", href=href, target=target),
                    )
                )

    # 4. frontmatter completeness.
    violations.extend(check_frontmatter(docs))

    # 4b. anchor coverage — every content block must carry an anchor, or it is
    # browse-visible canonical text that never enters the L3 claim index (orphaned). The
    # write tools auto-anchor every block, so this is the backstop that keeps any future
    # path from committing unindexed claims.
    violations.extend(check_anchor_coverage(docs))

    # 4e. a claim's TEXT is words, never markers. The write faces refuse it first
    # (`anchor_ops.refuse_text_machinery`); this is the arbiter over the produced draft, and
    # it is what makes a page this round wrote answer for machinery it carried in from before.
    violations.extend(
        check_claim_text_machinery(
            docs, base_bodies, path_templates=draft.path_templates
        )
    )

    # 4c. the OVERVIEW region: bounded, grounded in the ledger, four slots. The pure judgement
    # lives in compile/overview.py; the gate owns the Violation type, so it wraps the findings
    # rather than importing itself into the module it calls.
    violations.extend(
        Violation(kind, path, detail)
        for kind, path, detail in check_overviews(
            new_bodies, base_bodies, budget=overview_budget_chars
        )
    )

    # 4d. and the same region judged from the other end: a document this round TOUCHED whose
    # ledger has passed the threshold must HAVE an overview. The budget above stops a head
    # from growing into a ledger; this stops a ledger from growing without a head — the
    # failure a real library actually showed (41 of 85 pages never got one, some at 20–31
    # claims, while the ones that had a head were maintained over and over). Untouched pages
    # are never judged: they converge on their next touch, and a repository-wide floor would
    # abort compiles that have nothing to do with the page.
    violations.extend(
        overview_required_violations(draft, threshold=overview_required_after_claims)
    )

    # 5. path ownership. A document's ROLLOVER VOLUMES (`<owned document>/aNN.md`) count as
    # owned here even though they are outside the write templates: a volume is a real canonical
    # document, so it is read off git into every later compile's draft, and judging it unowned
    # would make every compile after the first rollover abort on a path it is not even
    # touching. The write face is unchanged — `create_document` still calls `path_allowed`
    # alone, so no compile tool can create a volume (only the groom channel writes there).
    for path in docs:
        if path_allowed(path, draft.path_templates):
            continue
        if history_volume_owner(path, draft.path_templates) is not None:
            continue
        # A document in the ARCHIVE is owned by the archive, not by a write template: the
        # move under `archive/` deliberately puts it outside every path pattern (which is
        # what makes `create_document` there impossible), and it sits in the draft like
        # every other document. Judging it unowned would abort every compile after the
        # owner's first archive, on a path the round never touched. 5c below is the rule
        # that actually holds for it.
        if is_archived_path(path):
            continue
        violations.append(
            Violation(
                "path",
                path,
                prompt(
                    "gate.path_not_owned",
                    templates=", ".join(draft.path_templates),
                ),
            )
        )

    # 5b. a closed volume is CLOSED. Compile cannot create one, but every volume does sit in
    # the draft as an ordinary document. The claim-mutation tools now refuse a volume path
    # up front (PatchDraft._refuse_closed_volume, same ownership derivation), so in the tool
    # loop this check should never be the FIRST thing to say "closed" — but it stays as the
    # final arbiter over the produced draft: nothing in a daily compile has any business
    # writing there — the open volume is where new claims belong — so any change to a
    # closed volume, however it got into the draft, is refused.
    for path, doc in docs.items():
        if history_volume_owner(path, draft.path_templates) is None:
            continue
        if doc.body != base_bodies.get(path):
            violations.append(
                Violation(
                    "volume_closed",
                    path,
                    prompt("gate.volume_closed", owner=history_volume_owner(
                        path, draft.path_templates
                    )),
                )
            )

    # 5c. the ARCHIVE. Not the closed-volume rule above and deliberately a separate kind:
    # `archive/` is where the OWNER moved a subject that is no longer worth an answer slot,
    # and the move in and out is the owner's alone (docs/design/archive.md §2.1). Two
    # mechanical rules, both judged over the produced draft: nothing under `archive/` changes,
    # and no new document may take a live path an archived document shadows — a document's id
    # derives from its path, and two documents with one id is the one thing a move must never
    # produce. The tool face refuses both up front; this is the final arbiter.
    base_documents = draft.base_documents()
    for path, doc in docs.items():
        if not is_archived_path(path):
            continue
        if touched_this_round(doc, base_documents.get(path)):
            violations.append(
                Violation("archived_path", path, prompt("gate.archived_path"))
            )
    # …and the ARCHIVE RECORD, which is the same rule read at the live path — stated once,
    # above, because the evolve gate holds the identical line over its own draft.
    violations.extend(check_archive_records(docs, base_documents))

    shadowed = shadowed_paths(base_documents.values())
    # The title map is derived once for the whole check, off the BASE tree: no round can add
    # or rename an archived document, so the archived names are the names this round started
    # with.
    archived_by_title = archived_titles(base_documents.values())
    for path, doc in docs.items():
        if path in base_bodies:
            continue
        if path in shadowed:
            violations.append(
                Violation(
                    "archived_path",
                    path,
                    prompt("gate.archived_path_shadowed", archived=archived_path(path)),
                )
            )
            continue
        # …and the same rule read off the NAME. Shadowing the path alone held "one path, one
        # doc_id" while a retired subject came back at the next free slug under a title that
        # matched the archived page word for word (docs/design/archive.md §2.1, finding O3).
        # A paraphrased title still escapes — see `PatchDraft._refuse_shadowed_title` for why
        # that limit is stated rather than papered over.
        title = document_title(doc)
        archived_twin = archived_by_title.get(normalize_title(title))
        if archived_twin is None:
            continue
        violations.append(
            Violation(
                "archived_path",
                path,
                prompt(
                    "gate.archived_title_shadowed",
                    title=title,
                    archived=archived_twin,
                ),
            )
        )

    # 6. supersession links (compile/supersession.py) — legal, linear, evidenced, frozen.
    violations.extend(check_supersession(docs, base_bodies))

    # 7. enabled index components judge the documents of their families. The framework
    # runs the checks and feeds the violations back like its own; what a component tests
    # (an identity unique across the repository, an alias list that only grows) is the
    # component's declaration, never a rule core knows.
    for component in registered_components():
        violations.extend(component.gate_checks(docs, base_documents))

    return violations


def archive_refusals(
    violations: Sequence[Violation], draft: PatchDraft
) -> list[dict]:
    """Every archive refusal this compile made, tool face and gate together, deduplicated.

    A refusal is not a write, so it produces no compile event — events are derived from the
    file diff, and nothing here changed a file. It is still the one moment the framework
    learns something the OWNER needs: new material came in about a subject they retired.
    So it travels as its own small record on `CompileResult` and into the job's completion
    detail, and the owner reads it beside the compile that hit it
    (docs/design/archive.md §2.1, finding O3).

    Shape, per item: `{"kind": "path" | "title" | "record", "path", "archived", "title",
    "attempted"}` — `record` being a write attempted on the archive record a retired subject
    left at its live path, which is a reach for the subject exactly as the other two are —
    `path` is what the round tried to write, `archived` the archived document standing in its
    way, `title` THAT document's name (the retired subject, which is the fact the owner
    needs), and `attempted` the name the round tried to give the new page — `None` for a path
    refusal, where nothing was attempted by name.

    Deduplicated on `(kind, path, archived)`: two attempts at one archived subject that
    differ only in punctuation normalize to the same subject and are one fact, so the first
    is kept and its `attempted` spelling is the one that travels.
    """
    records = draft.archive_refusals
    docs, base = draft.documents(), draft.base_documents()
    shadowed = shadowed_paths(base.values())
    by_title = archived_titles(base.values())
    seen = {(r["kind"], r["path"], r["archived"]) for r in records}

    def add(record: dict) -> None:
        key = (record["kind"], record["path"], record["archived"])
        if key not in seen:
            seen.add(key)
            records.append(record)

    for violation in violations:
        if violation.kind != "archived_path":
            continue
        path = violation.path
        if is_archived_path(path):
            # A change UNDER the archive: the path is its own archived form.
            doc = docs.get(path) or base.get(path)
            add(
                {
                    "kind": "path",
                    "path": path,
                    "archived": path,
                    "title": document_title(doc) if doc else "",
                    "attempted": None,
                }
            )
            continue
        record = base.get(path)
        if record is not None and is_archive_record(record):
            # The live path is held by the RECORD, so the reach is a write on the record and
            # not a create on a shadowed path. Checked before the shadow branch below, which
            # would otherwise match the same path (the archived twin shadows it too) and
            # report the same fact under a second code — the tool face already spells it
            # `record`, and one reach is one record.
            twin = str(
                (record.frontmatter or {}).get(ARCHIVE_OF_KEY) or archived_path(path)
            )
            add(
                {
                    "kind": "record",
                    "path": path,
                    "archived": twin,
                    "title": document_title(record),
                    "attempted": None,
                }
            )
            continue
        if path in shadowed:
            twin = archived_path(path)
            doc = base.get(twin)
            add(
                {
                    "kind": "path",
                    "path": path,
                    "archived": twin,
                    "title": document_title(doc) if doc else "",
                    "attempted": None,
                }
            )
            continue
        doc = docs.get(path)
        attempted = document_title(doc) if doc else ""
        twin = by_title.get(normalize_title(attempted), "")
        archived_doc = base.get(twin)
        add(
            {
                "kind": "title",
                "path": path,
                "archived": twin,
                # The archived page's own name, not the one the round reached for: same rule
                # as the tool face, so a refusal reads the same whichever face caught it.
                "title": document_title(archived_doc) if archived_doc else "",
                "attempted": attempted,
            }
        )
    return records
