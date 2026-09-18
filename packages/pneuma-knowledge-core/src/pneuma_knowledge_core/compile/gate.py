"""Mechanical compile gate (architecture.md §8): all checks hard-reject.

The checks return structured violations (fed back verbatim for one
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
3c. authored claim provenance — new/revised blocks and newly broken dependants must reach
   a source or previously admitted mechanical record. Unchanged historical defects may
   remain but cannot ground new claims. This checks provenance, not semantic entailment.
4. frontmatter completeness — doc_id / type / slug present.
4b. anchor coverage — every content block carries an anchor (else it is browse-visible
   canonical text that never enters the L3 claim index — an orphaned claim).
4e. claim TEXT carries no machinery — no HTML comment, no invented `__AUTO__` / `__NEW__`
   anchor placeholder, anywhere before a block's trailing system markers. Judged for the
   pages this round CHANGED: a legacy page nobody touched keeps its bytes (the only channel
   that could repair it is a compile that is writing it anyway).
4f. a `# ` heading NAMES the page and therefore stands at the top of its body or nowhere;
   a heading further down used to rename the page silently (docs/design/structure-lens.md
   §6). Judged for the pages this round changed, volumes exempt, like 4e.
4g. two LIVE pages in one directory may not answer to one name (`retitle` is what can now
   produce that). Judged for the pages whose NAME this round wrote.
4h. …and a page's name judged on its own: a title that is empty, that is its family's ROLE
   word (`overview`, `演进`), or that is the project slug on a page that is not the hub
   (`title_degenerate`); and a chronology carrying its hub's name (`title_shared_with_hub`).
   Roles come from the contract's path templates through `shape/families.py`. Judged — like
   4g — only for the pages whose NAME this round wrote, volumes excluded.
4i. the overview head against the ledger below it: a slot whose words ARE one of the page's
   claims (`overview_restates`), and a `definition` made of references with no prose
   (`definition_empty`). Judged only for the pages whose overview REGION this round wrote.

   4g–4i all take one rule: A HOOK JUDGES WHAT THE ROUND CHANGED, NEVER WHAT IT INHERITED,
   and "changed" is the narrowest true statement of it — the title for a title rule, the
   region for a region rule. Judged per PAGE instead, a page carrying one legacy fault
   becomes unrepairable: every write on it, the very `retitle` that would fix it included,
   comes back refused for a line the round never wrote (a real review round hit exactly
   that). What those pages are for is the CHECK (docs/design/structure-lens.md §3.1), which
   lists each of them with the verb that repairs it.
4c. the OVERVIEW region — bounded in size, grounded in the ledger, four slots and no others
   (compile/overview.py). Every declared reference must resolve to a ledger anchor.
   Rewritten regions are fully checked; unchanged regions must retain every reference
   that resolved in the base. These checks do not prove semantic fidelity.
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
from ..domain.authorship import owner_authored_blocks
from ..prompts import prompt
from ..components import registered_components
from ..shape.families import ROLE_CHRONOLOGY, role_of
from ..shape.text import bare_prose, claim_blocks, claim_words
from ..shape.titles import is_degenerate_title, shares_hub_title
from .anchor_ops import (
    anchored_blocks,
    heading_lines,
    missing_anchors,
    text_machinery_problems,
    unanchored_blocks,
)
from .documents import (
    DOC_ID_KEY,
    LEGACY_DOC_ID_KEYS,
    OVERVIEW_SLOTS,
    overview_region,
    parse_overview,
)
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
    grounding_references,
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
from .transitions import _anchor_blocks

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


#: Every violation kind this gate can emit, in the order the checks are documented in the
#: module docstring, paired with the prompt-catalog keys whose templates ARE the gate's own
#: descriptions of it. Enumerable on purpose: a generated reference for a coding-agent
#: Steward (`pkc skill install`) renders one entry per kind out of this table and out of the
#: catalog, so the door's description of a refusal and the refusal itself are one text
#: (docs/design/coding-agent-mode.md ruling 4). Nothing here paraphrases a check — the tuple
#: names keys, and `violation_catalog()` resolves them through the ordinary prompt seam so a
#: deployment's overlay and its language pack reach the reference too.
#:
#: `compile.overview.refuse_missing` is the one non-`gate.` key: the overview a page OWES is
#: refused by the write verb first and by the gate second, from that single text.
VIOLATION_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anchor_continuity", ("gate.anchor_continuity",)),
    ("anchor_uniqueness", ("gate.anchor_uniqueness",)),
    (
        "citation",
        (
            "gate.citation_unknown_source",
            "gate.citation_out_of_range",
            "gate.citation_unparsable_marker",
            "gate.citation_anchor_in_marker",
            "gate.claim_without_provenance",
        ),
    ),
    ("frontmatter", ("gate.frontmatter_missing",)),
    ("owner_voice", ("gate.owner_voice", "gate.owner_voice_unresolved")),
    ("anchor_coverage", ("gate.anchor_coverage",)),
    ("claim_text", ("gate.claim_text_machinery",)),
    # A page is named by the heading at the TOP of its body. A `# ` line anywhere else used
    # to rename it silently, in every outline, glance and card
    # (docs/design/structure-lens.md §2).
    ("heading_in_block", ("gate.heading_in_block",)),
    # …and the other half of the same concern: two live pages in one directory answering to
    # one name, which `retitle` can now produce and nothing else could.
    ("title_sibling_collision", ("gate.title_sibling_collision",)),
    # …and the two ways a name can be wrong on its own page rather than against a neighbour:
    # a name that says where the page SITS instead of what it is about, and a chronology
    # wearing the name of the hub it runs beside (docs/design/structure-lens.md §2).
    ("title_degenerate", ("gate.title_degenerate",)),
    ("title_shared_with_hub", ("gate.title_shared_with_hub",)),
    # The overview head, judged against the ledger under it: a slot that repeats a claim word
    # for word says nothing the ledger had not, and a definition made of references says
    # nothing at all.
    ("overview_restates", ("gate.overview_restates",)),
    ("definition_empty", ("gate.definition_empty",)),
    (
        "overview",
        (
            "gate.overview_budget",
            "gate.overview_ungrounded",
            "gate.overview_invalid_references",
            "gate.overview_unknown_slot",
            "gate.overview_definition_blocks",
            "gate.overview_definition_length",
            "compile.overview.refuse_missing",
        ),
    ),
    ("path", ("gate.path_not_owned",)),
    ("volume_closed", ("gate.volume_closed",)),
    (
        # The ARCHIVE, which is not the closed-volume rule above: `archive/` is where the
        # OWNER moved a subject out of the answering set, and the four texts are the four
        # ways a round can reach back for it — the archived path itself, the live path it
        # shadows, the name it shadows, and the record it left standing.
        "archived_path",
        (
            "gate.archived_path",
            "gate.archived_path_shadowed",
            "gate.archived_title_shadowed",
            "gate.archive_record",
        ),
    ),
    (
        "supersession",
        (
            "gate.supersession_target_missing",
            "gate.supersession_self",
            "gate.supersession_multiple",
            "gate.supersession_not_linear",
            "gate.supersession_cycle",
            "gate.supersession_frozen",
            "gate.supersession_without_evidence",
        ),
    ),
    ("link", ("gate.link_self_reference", "gate.link_dead")),
)


def violation_catalog() -> list[tuple[str, list[str]]]:
    """`VIOLATION_KINDS` with every key resolved to the text the gate would render.

    Templates, not filled sentences: the placeholders (`{anchor}`, `{source_id}`) are the
    part a violation supplies at the moment it is raised, and a reference that invented
    values for them would be describing a different failure than the one that happens. The
    resolution goes through `prompt`, so an overridden clause and the active language pack
    are what a reader of the reference sees.
    """
    return [(kind, [prompt(key) for key in keys]) for kind, keys in VIOLATION_KINDS]


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


def check_heading_in_block(
    docs: Mapping[str, object],
    base_bodies: Mapping[str, str],
    *,
    path_templates: Sequence[str] = (),
) -> list[Violation]:
    """A `# ` heading stands at the TOP of a body or nowhere — the final arbiter behind the
    write faces' `refuse_heading_in_block`.

    A page's name is derived from its leading heading (`compile.documents.derived_title`), so
    a `# ` line further down is a second name written into the middle of the page. Before the
    derivation was narrowed, that line WAS the name: an append could rename a subject with
    nothing in the diff saying so.

    Judged for the pages this round CHANGED, and only for the headings this round
    INTRODUCED — a heading the base body already carried is grandfathered, exactly as a
    citation carried over verbatim is. That limit is not leniency, it is the absence of a
    corrective action: a `# ` line is a HEADING to the block walker, so it belongs to no
    claim, no `edit_claim` can reach it and no write verb can delete it. Refusing a page for
    a line nothing can remove would be a deadlock, and what the existing instances are for is
    the lens's `form.stray_heading`, which lists them for a repair the Owner decides on.

    Closed volumes are exempt for the reason they are exempt from 4e: no write verb reaches
    one at all.
    """
    violations: list[Violation] = []
    for path, doc in docs.items():
        base = base_bodies.get(path)
        if base is not None and doc.body == base:
            continue
        if history_volume_owner(path, list(path_templates)) is not None:
            continue
        carried = {heading for _, heading in heading_lines(base or "")}
        lines = doc.body.split("\n")
        first = next((n for n, line in enumerate(lines, start=1) if line.strip()), 0)
        for line_number, heading in heading_lines(doc.body):
            if line_number == first or heading in carried:
                continue
            violations.append(
                Violation(
                    "heading_in_block",
                    path,
                    prompt("gate.heading_in_block", heading=heading),
                )
            )
    return violations


def title_changed(doc: object, base: object | None) -> bool:
    """Did THIS round give the page the name it now carries?

    A hook judges what the round CHANGED, never what it inherited — the discipline the three
    title checks below and the region checks further down all take. A page whose name is the
    name it arrived with is not this round's business even when that name is wrong: the CHECK
    lists it (docs/design/structure-lens.md §3.1) and `retitle` repairs it in a round of its
    own. Refusing the page instead would mean a page with one legacy fault could not be
    repaired at all — every write on it, including the retitle that would fix it, would come
    back refused for a line the round never wrote. A real review round hit exactly that.

    A page this round CREATED has no inherited anything, so its name is always its own.
    """
    if base is None:
        return True
    return document_title(doc) != document_title(base)


def check_title_siblings(
    docs: Mapping[str, object], base_docs: Mapping[str, object]
) -> list[Violation]:
    """No two LIVE pages in one directory answer to one name.

    The companion rule to the archive's title shadowing, over the live tree: `retitle` can
    give a page any name, and the name that would be worst is the one its neighbour already
    has — a reader and a citation then have no way to tell the two apart, which is exactly
    the `id.title_duplicate` finding the lens reports about libraries that already did it.

    "Sibling" is the immediate directory and nothing cleverer: it is the one grouping every
    path has, it needs no contract to state it, and it is the grouping a person reading a
    file tree sees. Judged for the pages whose NAME this round wrote (`title_changed`), so a
    collision two legacy pages have carried for months does not abort a compile that appends
    one claim to either — that pair is the check's `id.title_sibling_collision`, and the
    repair is a retitle this rule must not stand in the way of.
    """
    violations: list[Violation] = []
    live = {
        path: doc
        for path, doc in docs.items()
        if not is_archived_path(path) and not is_archive_record(doc)
    }
    by_directory: dict[str, list[str]] = {}
    for path in live:
        by_directory.setdefault(path.rsplit("/", 1)[0] if "/" in path else "", []).append(path)
    for path, doc in sorted(live.items()):
        if not title_changed(doc, base_docs.get(path)):
            continue
        title = document_title(doc)
        key = normalize_title(title)
        if not key:
            continue
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        for other in sorted(by_directory.get(directory, [])):
            if other == path:
                continue
            if normalize_title(document_title(live[other])) != key:
                continue
            violations.append(
                Violation(
                    "title_sibling_collision",
                    path,
                    prompt("gate.title_sibling_collision", title=title, other=other),
                )
            )
            break
    return violations


def _live_titles(docs: Mapping[str, object]) -> dict[str, str]:
    """path → name, over the LIVE pages only. Archived documents and archive records are not
    pages a round may name, and a name is judged against the pages a reader can reach."""
    return {
        path: document_title(doc)
        for path, doc in docs.items()
        if not is_archived_path(path) and not is_archive_record(doc)
    }


def _judged_titles(
    docs: Mapping[str, object],
    base_docs: Mapping[str, object],
    path_templates: Sequence[str],
) -> list[tuple[str, str]]:
    """`(path, title)` for every live page whose NAME this round wrote, volumes excluded.

    A closed volume is excluded because it has no name of its own — it is labelled from the
    page it was cut out of — and no write verb reaches one anyway.
    """
    return [
        (path, title)
        for path, title in sorted(_live_titles(docs).items())
        if title_changed(docs[path], base_docs.get(path))
        and history_volume_owner(path, list(path_templates)) is None
    ]


def check_title_degenerate(
    docs: Mapping[str, object],
    base_docs: Mapping[str, object],
    *,
    path_templates: Sequence[str] = (),
) -> list[Violation]:
    """A page's name says what it is ABOUT, never where it sits.

    `Overview`, `演进`, `Decisions` — and the project's own slug on a page that is not its
    hub — name a place in the layout, so every page of that family would answer to them and
    none of them tells a reader or a retrieval which page this is. The predicate is
    `shape.titles.is_degenerate_title`, shared with the check, so a title the gate accepts is
    never one the check then reports. Judged only for the pages whose NAME this round wrote
    (`title_changed`): a page that arrived carrying a role word keeps it until somebody
    retitles it, and that retitle must not be refused by the fault it is repairing.

    An EMPTY name is the same fault at its limit, and the gate does NOT refuse it here. A
    page whose body opens with no `# ` line has no name at all — `is_degenerate_title` says so,
    and the check lists every one of them with `retitle` as the repair — but refusing the write
    would abort every round whose model creates a page opening on a `## ` section, which is how
    pages have been created for as long as the tool face has existed. Turning that into a hard
    refusal is a contract change with an announcement and a migration in front of it, not a
    line in a gate; until then it is the check's `id.title_degenerate`.
    """
    violations: list[Violation] = []
    for path, title in _judged_titles(docs, base_docs, path_templates):
        if not is_degenerate_title(path, title, path_templates):
            continue
        if not normalize_title(title):
            continue
        violations.append(
            Violation(
                "title_degenerate",
                path,
                prompt("gate.title_degenerate", title=title, path=path),
            )
        )
    return violations


def check_title_shared_with_hub(
    docs: Mapping[str, object],
    base_docs: Mapping[str, object],
    *,
    path_templates: Sequence[str] = (),
) -> list[Violation]:
    """A project's chronology may not wear its hub's name.

    The hub says what the project IS; the chronology says what happened to it. One name over
    the two leaves a reader — and a citation, and a retrieval card — with no way to tell which
    page it is holding, and it is the collision a real library produced over and over, because
    the project's name is the obvious thing to call the page about the project. Judged, like
    every title rule here, only for the pages whose name this round wrote.
    """
    violations: list[Violation] = []
    titles = _live_titles(docs)
    for path, title in _judged_titles(docs, base_docs, path_templates):
        hub = shares_hub_title(path, titles, path_templates)
        if not hub:
            continue
        violations.append(
            Violation(
                "title_shared_with_hub",
                path,
                prompt("gate.title_shared_with_hub", title=title, other=hub),
            )
        )
    return violations


def _overview_region_changed(body: str, base_body: str | None) -> bool:
    """Did this round write the page's overview REGION?

    The narrowest true statement of "what the round changed" for a head-level rule: a byte
    compare of the region itself, not of the page. A retitle rewrites one heading line, an
    append adds a claim to the ledger, `reorder_chronology` moves whole sections — none of
    them touches the head, so none of them answers for a head written before the rule existed.
    That distinction is not a nicety: judged per PAGE, these two checks turned a legacy
    overview into a page nothing could repair, because the retitle that would have fixed its
    name came back refused for the head it had not touched.
    """
    if base_body is None:
        return True
    return overview_region(body) != overview_region(base_body)


def check_overview_restates(
    docs: Mapping[str, object], base_bodies: Mapping[str, str]
) -> list[Violation]:
    """An overview block may not be a ledger claim said again.

    The head is a READING of the ledger — what this subject is, what it comes to, how it
    connects — and the gate already requires every block of it to rest on a claim or a span.
    A block whose words ARE one of those claims passes that rule and says nothing: the head
    has spent its budget repeating the page below it. Cite the claim instead.

    Compared with citations, anchor references and whitespace runs removed, so the same
    sentence carrying a reference is still the same sentence. `connections` is exempt: a
    connection line is a link plus the relation it stands for, and repeating a claim's words
    there is how a relation is named.
    """
    violations: list[Violation] = []
    for path, doc in sorted(docs.items()):
        if not _overview_region_changed(doc.body, base_bodies.get(path)):
            continue
        overview, _ = parse_overview(doc.body)
        if overview is None:
            continue
        ledger = {bare_prose(claim_words(block)) for block in claim_blocks(doc.body)}
        ledger.discard("")
        for slot in OVERVIEW_SLOTS:
            if slot == "connections":
                continue
            text = bare_prose(str(getattr(overview, slot, "") or ""))
            if not text or text not in ledger:
                continue
            violations.append(
                Violation(
                    "overview_restates",
                    path,
                    prompt("gate.overview_restates", slot=slot),
                )
            )
    return violations


def check_definition_empty(
    docs: Mapping[str, object], base_bodies: Mapping[str, str]
) -> list[Violation]:
    """The one line that says what a subject IS has to be made of words.

    A `definition` holding only anchor references and citations is a slot that was filled to
    satisfy the rule that a developed page owes an overview, and it answers no question: a
    reader asking what this subject is receives a list of pointers to claims.
    """
    violations: list[Violation] = []
    for path, doc in sorted(docs.items()):
        if not _overview_region_changed(doc.body, base_bodies.get(path)):
            continue
        overview, _ = parse_overview(doc.body)
        if overview is None:
            continue
        raw = str(overview.definition or "").strip()
        if not raw or bare_prose(raw):
            continue
        violations.append(
            Violation("definition_empty", path, prompt("gate.definition_empty"))
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


def check_claim_provenance(
    docs: Mapping[str, object], base_documents: Mapping[str, object], *, audit: bool = False
) -> list[Violation]:
    """Reject new provenance defects; an explicit audit also reports historical defects.

    A byte-identical claim may retain an existing defect, even across a move. It is NOT a
    grounding root for new claims. Previously grounded dependants that lose their source
    chain are rejected even when their text did not change. This keeps an unrelated write
    from being held hostage by history, especially history the writer cannot edit.

    Archive records and volume catalogs have their own mechanical admission channels.
    Their exact, previously admitted blocks are valid bases. Read BASE metadata, never a
    model's newly declared exemption. Citation shape and bounds are separate checks;
    reaching a source does not establish semantic entailment.
    """
    current_blocks, grounded = _provenance_graph(docs, base_documents)
    base_blocks, base_grounded = _provenance_graph(base_documents, base_documents)
    previous = {anchor: block for blocks in base_blocks.values() for anchor, block in blocks.items()}
    violations = []
    for path, blocks in current_blocks.items():
        for anchor, block in blocks.items():
            if anchor in grounded:
                continue
            if not audit and previous.get(anchor) == block and anchor not in base_grounded:
                continue
            violations.append(Violation(
                "citation", path, prompt(
                    "gate.claim_without_provenance",
                    preview=" ".join(block.split())[:48], anchor=anchor,
                ),
            ))
    return violations


def _provenance_graph(
    docs: Mapping[str, object], admitted: Mapping[str, object]
) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Find source-reachable claims without treating legacy admission as evidence."""
    from .rollover import catalog_anchors

    current_blocks = {
        path: _anchor_blocks(doc.body) for path, doc in docs.items()
    }
    grounded: set[str] = set()
    dependants: dict[str, set[str]] = {}
    for path, blocks in current_blocks.items():
        base = admitted.get(path)
        if base is None:
            continue
        base_blocks = _anchor_blocks(base.body)
        mechanical = (set(base_blocks) if is_archive_record(base)
                      else set(catalog_anchors(base.frontmatter)))
        grounded.update(anchor for anchor in mechanical
                        if anchor in blocks and blocks[anchor] == base_blocks.get(anchor))
    for blocks in current_blocks.values():
        for anchor, block in blocks.items():
            if CANONICAL_CITATION_MARKER_RE.search(block):
                grounded.add(anchor)
            for reference in grounding_references(block) - set(extract_anchors(block)):
                dependants.setdefault(reference, set()).add(anchor)
    pending = list(grounded)
    while pending:
        for anchor in dependants.get(pending.pop(), ()):
            if anchor not in grounded:
                grounded.add(anchor)
                pending.append(anchor)
    return current_blocks, grounded


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


def check_owner_voice(
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    *,
    alias_map: Mapping[str, str] | None = None,
) -> list[Violation]:
    """New or edited claims on opted-in paths must resolve entirely to Owner blocks.

    Canonical anchor references follow their provenance too, including overview references.
    A carried-over citation marker does not exempt a new assertion using that marker.
    """
    if not draft.owner_voice_templates:
        return []
    aliases = alias_map or {}
    owners = {sid: set(indices) for sid, indices in draft.owner_authored_blocks.items()}
    for source in sources:
        sid = str(source.raw.source_id)
        owners[aliases.get(sid, sid)] = set(owner_authored_blocks(source.raw)) & {
            block.index for block in source.blocks
        }
    docs = draft.documents()
    claims = {
        block_anchor(block): block
        for doc in docs.values()
        for block in anchored_blocks(doc.body)
    }

    evidence_cache: dict[str, tuple[list, bool]] = {}

    def evidence(block: str, visited: frozenset[str]) -> tuple[list, bool]:
        anchor = block_anchor(block)
        if anchor in evidence_cache:
            return evidence_cache[anchor]
        citations = list(iter_canonical_citations(block))
        prose = re.sub(r"<!--.*?-->", "", block, flags=re.DOTALL)
        refs = set(re.findall(r"\bc:([0-9a-zA-Z_-]+)", prose))
        resolved = bool(citations or refs)
        for ref in sorted(refs):
            if ref in visited or ref not in claims:
                resolved = False
                continue
            more, valid = evidence(claims[ref], visited | {ref})
            citations.extend(more)
            resolved = resolved and valid
        evidence_cache[anchor] = citations, resolved
        return citations, resolved

    violations = []
    base_bodies = draft.base_bodies()
    for path, doc in docs.items():
        if not path_allowed(path, draft.owner_voice_templates):
            continue
        base = {
            block_anchor(block): block
            for block in anchored_blocks(base_bodies.get(path, ""))
        }
        for block in anchored_blocks(doc.body):
            anchor = block_anchor(block)
            if base.get(anchor) == block:
                continue
            citations, resolved = evidence(block, frozenset({anchor}))
            if not resolved:
                violations.append(
                    Violation(
                        "owner_voice",
                        path,
                        prompt("gate.owner_voice_unresolved", anchor=anchor),
                    )
                )
            for citation in citations:
                sid = aliases.get(str(citation.source_id), str(citation.source_id))
                start, end = citation.block_start, citation.block_end
                owner_indices = owners.get(sid, set())
                # Bound the work by the available indices, even for an enormous bad span.
                if (
                    start < 0
                    or start > end
                    or end - start + 1 > len(owner_indices)
                    or any(
                        index not in owner_indices for index in range(start, end + 1)
                    )
                ):
                    violations.append(
                        Violation(
                            "owner_voice",
                            path,
                            prompt(
                                "gate.owner_voice",
                                anchor=anchor,
                                source_id=sid,
                                start=start,
                                end=end,
                            ),
                        )
                    )
    return violations


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
    violations.extend(check_owner_voice(draft, sources, alias_map=alias_map))

    # 3c. New/changed claims and newly broken dependants must reach provenance.
    violations.extend(check_claim_provenance(docs, draft.base_documents()))

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
    from ..recall.speech_lexicon import validate_metadata
    for path, doc in docs.items():
        base = draft.base_documents().get(path)
        if "speech_terms" not in doc.frontmatter:
            continue
        if base and base.body == doc.body and base.frontmatter.get("speech_terms") == doc.frontmatter["speech_terms"]:
            continue
        try:
            validate_metadata(doc.frontmatter["speech_terms"], doc.body)
        except ValueError as exc:
            violations.append(Violation("frontmatter", path, str(exc)))

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

    # 4f. a `# ` heading names the page and stands at the top of it, or it is a second name
    # written into the middle of one. The write faces refuse a new one; this is the arbiter
    # over the produced draft, on the same changed-pages terms as 4e.
    violations.extend(
        check_heading_in_block(docs, base_bodies, path_templates=draft.path_templates)
    )

    # 4g. …and the same concern between pages: two live siblings under one name.
    violations.extend(check_title_siblings(docs, draft.base_documents()))

    # 4h. …and the two ways one page's own name is wrong: a name that is its family's role
    # rather than its subject, and a chronology wearing its hub's name. Both read the role
    # table in `shape/families.py` off this draft's path templates, so a contract that
    # declares none of those names is judged by neither.
    violations.extend(
        check_title_degenerate(
            docs, draft.base_documents(), path_templates=draft.path_templates
        )
    )
    violations.extend(
        check_title_shared_with_hub(
            docs, draft.base_documents(), path_templates=draft.path_templates
        )
    )

    # 4i. the overview head judged against the ledger under it: a slot that repeats a claim,
    # and a definition made of references alone. 4c bounds the head and grounds it; these two
    # are what "grounded" does not catch — a block that rests on a claim by BEING it.
    violations.extend(check_overview_restates(docs, base_bodies))
    violations.extend(check_definition_empty(docs, base_bodies))

    # 4c. the OVERVIEW region: bounded, grounded in the ledger, four slots. The pure judgement
    # lives in compile/overview.py; the gate owns the Violation type, so it wraps the findings
    # rather than importing itself into the module it calls.
    violations.extend(
        Violation(kind, path, detail)
        for kind, path, detail in check_overviews(
            new_bodies, base_bodies=base_bodies, budget=overview_budget_chars
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


def owed_now_lines(
    draft: PatchDraft,
    *,
    threshold: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
) -> list[str]:
    """What the round already OWES, by the very predicates the gate will run.

    Two of them, and no more: the overview a touched page owes
    (`overview_required_violations` — the same call `finish_compile` makes) and every enabled
    component's `gate_checks` over the current draft. Re-deriving this from a second set of
    rules would let the notice name work the gate does not want; asking the whole gate would
    need the sources and the alias map for a message whose only job is to point the last few
    calls at what is outstanding.

    Both executors read it: the langchain loop puts it in the low-water HumanMessage, the CLI
    appends it to the write that crossed the mark and repeats it in `pkc draft status`. One
    derivation, so the two renderings cannot name different work.
    """
    owed = [
        v.render()
        for v in overview_required_violations(draft, threshold=threshold)
    ]
    documents, base = draft.documents(), draft.base_documents()
    for component in registered_components():
        owed.extend(v.render() for v in component.gate_checks(documents, base))
    return owed


def post_write_violations(
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    path: str,
    *,
    baseline: Sequence[Violation] = (),
    alias_map: dict[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
    overview_budget_chars: int = OVERVIEW_BUDGET_CHARS,
    overview_required_after_claims: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
) -> list[Violation]:
    """What one write just broke on the page it touched (ruling 10 of the coding-agent design).

    A write that passed its argument checks is APPLIED and then judged: the gate's own
    predicates run over the draft, and this returns the findings that name `path` and were
    not already standing before the write (`baseline`, the same call over the draft as it
    stood). Two properties come out of that shape, and both are why it is not a second set of
    predicates:

    - **the gate's rules, once.** `run_gate` is the arbiter, here and at `finish`; there is no
      per-command rulebook that could hold a rule the final gate does not, or miss one it
      does.
    - **the write answers for itself and nothing else.** A page that arrived with a problem —
      a legacy document, or a page an earlier command in this round left owing an overview —
      does not make the next unrelated write refusable, and a round is never wedged by a
      finding no single command can repair.

    The whole gate runs rather than a per-document slice of it, because several of its checks
    are repository-wide by nature (anchor uniqueness, link targets, the overview's grounding
    in a ledger that may live on another page) and a scoped re-implementation of those would
    be exactly the second rulebook this function exists to avoid. The findings are then
    filtered to the touched page, which is the scope the ruling asks for.
    """
    after = run_gate(
        draft,
        sources,
        alias_map=alias_map,
        known_source_bounds=known_source_bounds,
        overview_budget_chars=overview_budget_chars,
        overview_required_after_claims=overview_required_after_claims,
    )
    standing = set(baseline)
    return [v for v in after if v.path == path and v not in standing]
