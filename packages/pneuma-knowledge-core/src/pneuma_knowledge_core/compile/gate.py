"""Mechanical compile gate (architecture.md §8): all checks hard-reject.

Five machine checks, each returning structured violations (fed back verbatim for one
repair round by the runner):

1. anchor continuity — a base anchor must not vanish. v1 has no authorized deletion
   channel; the model may only add or revise, never remove.
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
5. path ownership — every document path matches a skill path template, or is one of an owned
   document's rollover volumes (`<owned document>/aNN.md`; see patch.history_volume_owner).
5b. frozen archive — a rollover volume may not be modified by a compile.

The gate is the mechanism; there is no prompt asking the model to "please remember".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, iter_canonical_citations
from ..domain.ids import extract_anchors
from ..domain.source import NormalizedSource
from ..prompts import prompt
from .anchor_ops import anchored_blocks, missing_anchors, unanchored_blocks
from .documents import DOC_ID_KEY, LEGACY_DOC_ID_KEYS
from .patch import PatchDraft, history_volume_owner, path_allowed

REQUIRED_FRONTMATTER = (DOC_ID_KEY, "type", "slug")

# Accepted-on-read spellings per required key. A document committed before the id key was
# renamed carries `pneuma_id`; loads normalize it (compile.documents.normalize_frontmatter),
# but the gate accepts the legacy spelling directly too, so an un-normalized legacy
# document is never hard-rejected for "missing" an id it does have. Writes emit `doc_id`
# only — this is a read-side alias, not a second supported field name.
_FRONTMATTER_READ_ALIASES: dict[str, tuple[str, ...]] = {DOC_ID_KEY: LEGACY_DOC_ID_KEYS}

# Inter-document markdown links — the form the projection layer reads to build graph edges
# (service dataset._MD_LINK_RE). Kept identical here so the gate validates exactly what the
# graph will later try to resolve.
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")

# Anything a reader would take for a citation: the `[cite:` opener through the next `]`.
# Deliberately looser than `CANONICAL_CITATION_MARKER_RE` — its whole job is to catch the
# strings that regex does NOT match, which is why it cannot be that regex.
_CITE_BRACKET_RE = re.compile(r"\[cite:(?P<inner>[^\]]*)\]")

# An anchor reference (`c:<id>`) written where a source locator belongs. It is a legal
# provenance form in the wrong container, so it gets its own violation text: telling an
# author "this does not parse" when the fix is "move it outside the brackets" is a riddle.
_ANCHOR_IN_MARKER_RE = re.compile(r"^\s*c:(?P<anchor>[0-9a-zA-Z_-]+)\s*$")


def _resolve_relative(from_path: str, href: str) -> str:
    """Resolve `href` against the linking document's directory (mirrors dataset._resolve_link)."""
    stack = from_path.split("/")[:-1]
    for part in href.split("#")[0].split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
        else:
            stack.append(part)
    return "/".join(stack)


def _render_relative(from_path: str, target: str) -> str:
    """The href that renders `target` from a document at `from_path` — the inverse above.

    Its law is the round trip: `_resolve_relative(from_path, _render_relative(from_path, t))
    == t` for every repo-relative `t`. That is what makes a relative link MOVABLE: the href
    is only a rendering of a target from one position, so a document that changes position
    keeps its links by re-rendering them (compile.rollover), never by leaving the bytes alone.

    It lives next to the resolver because an inverse stated somewhere else is a second
    spelling of the same fact, and the two would drift.
    """
    from_dir = from_path.split("/")[:-1]
    parts = target.split("/")
    common = 0
    while (
        common < len(from_dir)
        and common < len(parts) - 1
        and from_dir[common] == parts[common]
    ):
        common += 1
    return "/".join([".."] * (len(from_dir) - common) + parts[common:])


@dataclass(frozen=True)
class Violation:
    kind: str  # anchor_continuity | anchor_uniqueness | citation | link | frontmatter | path
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


def run_gate(
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    *,
    alias_map: dict[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
) -> list[Violation]:
    docs = draft.documents()
    base_bodies = draft.base_bodies()
    violations: list[Violation] = []

    # 1. anchor continuity (base anchors may not disappear; deleted docs lose all).
    new_bodies = draft.new_bodies()
    for path, base_body in base_bodies.items():
        current = new_bodies.get(path, "")
        for anchor in missing_anchors(base_body, current):
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
        for block in anchored_blocks(doc.body):
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

    # 5b. a rollover volume is FROZEN. Compile cannot create one, but every volume does sit in
    # the draft as an ordinary document. The claim-mutation tools now refuse a volume path
    # up front (PatchDraft._refuse_frozen_volume, same ownership derivation), so in the tool
    # loop this check should never be the FIRST thing to say "frozen" — but it stays as the
    # final arbiter over the produced draft: nothing in a daily compile has any business
    # writing there — the active document is where new claims belong — so any change to a
    # volume, however it got into the draft, is refused.
    for path, doc in docs.items():
        if history_volume_owner(path, draft.path_templates) is None:
            continue
        if doc.body != base_bodies.get(path):
            violations.append(
                Violation(
                    "archive_frozen",
                    path,
                    prompt("gate.archive_frozen", owner=history_volume_owner(
                        path, draft.path_templates
                    )),
                )
            )

    return violations
