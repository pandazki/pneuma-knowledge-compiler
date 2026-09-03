"""Document rollover: the `groom` channel's pure mechanics + its own hard gate.

WHY THIS EXISTS
---------------
A canonical document that keeps accruing claims for one long-lived subject eventually stops
being usable as canonical. Observed in a full replay: one product document reached 435 KB /
894 claims — 42% of the whole knowledge base in a single file. Reading it whole blows a
recall window, and the bird's-eye view it was supposed to serve degrades into a wall.

A LONG-LIVED PAGE IS A WORK IN SEVERAL VOLUMES. That is the whole metaphor, and it is not
the ARCHIVE (docs/design/archive.md): a closed volume is live knowledge — indexed, retrieved
and listed like any other page — while `archive/` is where the Owner moves a subject that is
no longer worth an answer slot. One says "this book got long"; the other says "this subject
is no longer ours". Only the second is called archiving anywhere in this codebase.

Rollover is MECHANICAL MAINTENANCE, the way log rotation is: size-triggered, subject
unchanged, earlier volumes closed. It is orthogonal to `evolve`, which is SEMANTIC
reorganization (split a subject into sub-subjects). Both can coexist; neither replaces the
other.

Compile still has no move channel (a claim anchor never migrates on the daily path, so
anchor identity stays trivially safe). Rollover is a separate NARROW write channel with its
own gate — `run_groom_gate` below — and it never runs inside a compile.

THE SHAPE IT PRODUCES
---------------------
Given an open volume over the size threshold:

- the OLDEST claim blocks move, byte for byte, into a fresh CLOSED VOLUME inside the
  page's own VOLUME DIRECTORY — `work/products/aurora-planner.md` closes into
  `work/products/aurora-planner/a01.md`, `a02.md`, … — whose frontmatter records the page it
  is a volume of, its volume number, and the date span its entries cover. A volume is CLOSED
  once written: the next rollover opens the next volume, never rewrites an older one.

  The layout is one file plus one same-name directory, so the earlier volumes travel with the
  page they belong to and need no slug of their own. It also lands OUTSIDE the skill's write
  templates on purpose: `create_document` refuses those paths, so a volume can only be written
  through this channel, and the compile gate additionally refuses any change to one
  (`gate.run_gate` 5b). Closing is a mechanism, not a convention;
- the OPEN VOLUME — the page itself — keeps its path (so every inbound link and its doc_id
  survive), its frontmatter, and the most recent tail of claims verbatim. Between the title
  and that tail it gains the two GROOM-MANAGED sections that make up the VOLUME CARD: a
  digest of the earlier volumes (the only thing an LLM writes here) and a VOLUME CATALOG of
  markdown links — links being exactly the form the projection layer turns into graph edges,
  so the earlier volumes stay reachable for free.

WHY THE MANAGED BLOCKS CARRY ANCHORS
-----------------------------------
Every content block in canonical must carry an anchor (compile gate 4b): an unanchored
block is browse-visible text that never enters the L3 claim index. A groom that committed
unanchored prose would therefore HARD-FAIL every subsequent compile on that user — the
knowledge base would be bricked by its own gate. So the overview points and the catalog
entries are anchored blocks like any other claim, with machine-assigned ids that are
DETERMINISTIC per (document, slot) so a later rewrite of the card reuses the same ids
instead of churning the projection.

Their ids are recorded in the active document's frontmatter
(`rollover_overview_anchors` / `rollover_catalog_anchors`) rather than inferred from a
heading, because the heading is overridable prose and the ledger must not depend on prose.
That ledger is what lets the conservation check below be exact: real CLAIM anchors are
conserved to the letter, and the only anchors that may appear or disappear are the
groom-managed ones.

PROVENANCE OF AN OVERVIEW POINT
-------------------------------
An overview point is derived from EXISTING canonical, not from this round's material, so it
has no `[cite:]` form available. The write contract's second legitimate provenance applies:
it names the closed-volume anchors it rests on (`c:<id>`, as plain text — never as an anchor
comment, which would duplicate an id and break repo-wide uniqueness). A point that cannot
name one is not written, and the gate refuses the whole groom if one slips through.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..domain.canonical import CanonicalDocument
from ..domain.ids import ANCHOR_MARK_RE, extract_anchors
from ..prompts import prompt
from .anchor_ops import _HEADING_RE, _LIST_ITEM_RE, anchored_blocks, assign_anchor
from .documents import (
    overview_region,
    render_document,
    strip_overview,
    with_derived_title,
)
from .gate import (
    _MD_LINK_RE,
    _render_relative,
    _resolve_relative,
    Violation,
    check_anchor_coverage,
    check_anchor_uniqueness,
    check_frontmatter,
    path_allowed,
)
from .patch import (
    _VOLUME_FILE_RE,
    assign_document_id,
    history_dir,
    history_volume_owner,
)

# --- frontmatter ledger keys ------------------------------------------------------------
#: On a CLOSED VOLUME: which page it was cut out of, its volume number, and the date span its
#: entries cover (derived from dates present in the closed text; absent when none are).
#:
#: The literal `archived_from` is the volume's owning-page stamp in LEGACY SPELLING and stays
#: exactly as it is: it is written into every user's git library, so renaming the key on disk
#: would orphan every volume already written. Only the constant carries the current word.
VOLUME_OF_KEY = "archived_from"
VOLUME_NUMBER_KEY = "rollover_volume"
VOLUME_SPAN_KEY = "rollover_span"
#: On the ACTIVE document: how many volumes exist, and the ids of the groom-managed blocks.
VOLUME_COUNT_KEY = "rollover_volumes"
OVERVIEW_ANCHORS_KEY = "rollover_overview_anchors"
CATALOG_ANCHORS_KEY = "rollover_catalog_anchors"

#: A volume's filename inside the volume directory: `a01.md`, `a02.md`, … The grammar itself is
#: shared with path ownership (`patch._VOLUME_FILE_RE`), which is what makes "a volume" one fact
#: rather than two spellings.
_VOLUME_FILENAME = "a{number:02d}.md"

#: Any ISO-8601 calendar day appearing in a closed volume's text. Its span is the min..max of
#: these — a derived fact, never an invented one: a volume whose entries carry no dates simply
#: has no span, and the catalog says so by falling back to the volume's name.
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# --- when a claim says it HAPPENED -------------------------------------------------------
#
# WHY THE MIN..MAX OF EVERY DATE IN THE TEXT IS THE WRONG SPAN
# ------------------------------------------------------------
# A volume's catalog entry is the only thing a reader has when choosing which volume to open,
# so its date range is a claim about that volume — and "any ISO day anywhere in the bytes"
# makes that claim out of dates the entries merely MENTION. Measured on a real library: a
# volume of seven months of material advertised ten, because one entry recounted something
# from before the corpus began and another named a FUTURE launch date. Both dates are real
# text; neither is when anything in the volume happened.
#
# The entries themselves state the right answer. A claim that is about a day opens with that
# day, in one of two shapes the write contract produces, and a date appearing anywhere else
# in the sentence is context rather than occurrence. So the span prefers occurrence days and
# only falls back to the loose reading when not one entry states one.

#: A claim's leading furniture before its first word: list bullet, blockquote marker, and an
#: optional bracketed label (the strength-tier prefix mechanism renders one). All punctuation
#: and labels, never content — stripped so the two shapes below can anchor at `^`.
_CLAIM_LEAD_RE = re.compile(r"^[\s>*+-]*(?:【[^】\n]{1,16}】)?\s*")
#: Shape 1 — the day parenthesized at the head of the claim: `- (2026-03-04) …`.
_LEAD_PAREN_DAY_RE = re.compile(r"^\((\d{4}-\d{2}-\d{2})\)")
#: Shape 2 — the day as the claim's opening clause, closed by a comma: `2026-03-04, …`.
#: Both the ASCII and the full-width comma, because the clause break is the signal and its
#: glyph is whatever the deployment's language writes it with.
_LEAD_CLAUSE_DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[,，]")

#: How much of the closing material the volume-card call may see. Deliberately large: the
#: point of the call is to summarize what is being closed, so the default is "effectively
#: everything". The bound exists because the pathological input this feature was built for
#: is itself 435 KB, and an unbounded prompt is a hang rather than an answer. Truncation is
#: STATED in the rendered input (never silent), and it keeps the most recent closing
#: claims — the ones a volume card is most likely to still be about.
OVERVIEW_INPUT_BUDGET_CHARS = 200_000


# ============================================================ relative links travel along
#
# WHY A "VERBATIM" MOVE STILL REWRITES LINKS
# ------------------------------------------
# A volume sits one level DEEPER than the document it was cut out of
# (`work/products/aurora-planner.md` → `work/products/aurora-planner/a01.md`). A claim's markdown
# links are relative, so moving one byte for byte silently repoints every link it carries:
# `../../memory/collaborators/x.md` resolved from the volume lands at `work/memory/...`,
# which is nowhere. Measured on a real replay: ONE groom of two documents produced 556 dead
# links, and the earlier volumes' reachability collapsed with them.
#
# So "verbatim" was too literal a reading of the conservation invariant. A link is a
# SEMANTIC POINTER; its relative spelling is only how that pointer renders from the position
# the text currently occupies. The invariant this channel actually owes is therefore two
# clauses, and the gate below asserts both:
#
#   NON-LINK BYTES are conserved literally — a rollover may not reword or reflow a claim;
#   LINK TARGETS are conserved semantically — every link resolves, from the volume, to the
#   very document it resolved to from the active page. Which means the href bytes MUST
#   change whenever the depth does; leaving them alone is the corruption, not the fidelity.

#: What this channel re-renders: a link whose path part names a canonical `.md` document and
#: is not an external URL. The `#fragment` suffix is carried through untouched — it addresses
#: a place inside the target, not the target, so it is not the move's business. Anchor
#: comments (`<!-- c:… -->`) and `[cite: …]` markers carry no `](…)` and are never matched.
def _rewritable(href: str) -> bool:
    return href.split("#")[0].endswith(".md") and "://" not in href


def _link_hrefs(text: str) -> tuple[str, ...]:
    """Every re-renderable link href in `text`, in document order."""
    return tuple(
        m.group(1) for m in _MD_LINK_RE.finditer(text) if _rewritable(m.group(1))
    )


def link_targets(text: str, from_path: str) -> tuple[str, ...]:
    """What `text`'s links point at when it is read at `from_path`, in document order.

    This tuple — count, order and targets together — is the half of the conservation
    invariant a move is allowed to re-render rather than preserve byte for byte.
    """
    return tuple(_resolve_relative(from_path, href) for href in _link_hrefs(text))


def link_elided(text: str) -> str:
    """`text` with every re-renderable href emptied — the bytes a move may NOT touch.

    The `](` and `)` delimiters stay, and a non-canonical href (an external URL, a non-`.md`
    file) stays verbatim, so eliding cannot hide a change to anything but a target's spelling.
    """
    return _MD_LINK_RE.sub(
        lambda m: "]()" if _rewritable(m.group(1)) else m.group(0), text
    )


def relink(text: str, *, from_path: str, to_path: str) -> str:
    """`text` re-rendered for a reader at `to_path`, every link still pointing where it did.

    Deterministic and total: no path table is consulted, so a link that was already dead
    stays dead at the same target rather than being quietly "fixed" — repairing a target the
    author got wrong is a judgement, and this channel makes none.
    """
    if from_path == to_path:
        return text

    def _rewrite(match: re.Match[str]) -> str:
        href = match.group(1)
        if not _rewritable(href):
            return match.group(0)
        path_part, sep, fragment = href.partition("#")
        target = _resolve_relative(from_path, path_part)
        return f"]({_render_relative(to_path, target)}{sep}{fragment})"

    return _MD_LINK_RE.sub(_rewrite, text)


def dead_links(bodies: Mapping[str, str]) -> int:
    """How many links in `path → body` resolve to a document that is not in `bodies`.

    Counted with the gate's own machinery (`gate._MD_LINK_RE` + `gate._resolve_relative`) over
    the same links this module re-renders, so the number a groom promises not to raise is the
    number of edges the graph projection would fail to build. A dead link is not a style
    complaint: it is a hop a reader cannot take.
    """
    known = set(bodies)
    return sum(
        1
        for path, body in bodies.items()
        for href in _link_hrefs(body)
        if _resolve_relative(path, href) not in known
    )


# =============================================================== volume paths / numbering


def volume_path_for(active_path: str, number: int) -> str:
    """The path of volume `number`, inside `active_path`'s own volume directory."""
    return f"{history_dir(active_path)}/{_VOLUME_FILENAME.format(number=number)}"


def _render_span(days: Sequence[str]) -> str:
    """`min — max` over already-sorted days, collapsed to one day when they coincide."""
    if not days:
        return ""
    return days[0] if days[0] == days[-1] else f"{days[0]} — {days[-1]}"


def date_span(text: str) -> str:
    """The calendar-day span the given canonical text covers, or "" when it states no date.

    Mechanical: the min and max ISO-8601 day appearing anywhere in the text. A span is never
    inferred from anything else (an ingest timestamp, a commit time) — a made-up period reads as
    evidence about the volume and is worse than saying nothing.

    This is the LOOSE reading: it counts every day the text mentions, including ones the
    entries only refer to. `volume_date_span` is what a volume advertises; see the comment
    above `_CLAIM_LEAD_RE` for why the difference matters.
    """
    return _render_span(sorted(set(_ISO_DATE_RE.findall(text))))


def claim_occurrence_date(block: str) -> str:
    """The day a claim states it HAPPENED, or "" when it does not open with one.

    Only the two leading shapes count (see `_LEAD_PAREN_DAY_RE` / `_LEAD_CLAUSE_DAY_RE`). A
    date further into the sentence is something the claim talks about — a deadline, a prior
    event, a planned release — and reading it as the claim's own day is how a volume ends up
    advertising a period nothing in it covers.
    """
    first = next((line for line in block.split("\n") if line.strip()), "")
    rest = _CLAIM_LEAD_RE.sub("", first, count=1)
    for pattern in (_LEAD_PAREN_DAY_RE, _LEAD_CLAUSE_DAY_RE):
        match = pattern.match(rest)
        if match is not None:
            return match.group(1)
    return ""


def volume_date_span(text: str) -> str:
    """The span a volume advertises for the claims it closes over — narrowest honest reading.

    Three tiers, each used only when the one above it is silent:

      1. the min..max of the days the closed CLAIMS say they happened;
      2. the min..max of every day mentioned anywhere in the volume's text (`date_span`) —
         weaker, but a volume of undated-but-date-mentioning entries still tells a reader
         roughly what era it holds;
      3. "" — and the catalog names the volume instead of guessing a period.
    """
    days = sorted(
        {
            day
            for block in anchored_blocks(text)
            if (day := claim_occurrence_date(block))
        }
    )
    return _render_span(days) if days else date_span(text)


def is_closed_volume(doc: CanonicalDocument) -> bool:
    """True for a closed volume — read off frontmatter, never guessed from the path.

    A document that merely SITS where a volume would (something hand-filed at `notes/a01.md`)
    is not one: only the owning-page stamp a groom writes makes a volume a volume. The
    glance's collapse deliberately accepts the weaker path signal too, because a MISSING stamp
    there would resurface a closed volume as a peer document; here, where the question is "is
    this document a closed volume", the stamp is the only honest answer.
    """
    return bool(str((doc.frontmatter or {}).get(VOLUME_OF_KEY) or "").strip())


def volume_of(doc: CanonicalDocument) -> str:
    """The open volume (the page) this closed volume was cut out of, or "" when it is not one."""
    return str((doc.frontmatter or {}).get(VOLUME_OF_KEY) or "").strip()


def volume_number(doc: CanonicalDocument) -> int:
    """A volume's number, from frontmatter, falling back to its filename."""
    raw = str((doc.frontmatter or {}).get(VOLUME_NUMBER_KEY) or "").strip()
    if raw.isdigit():
        return int(raw)
    match = _VOLUME_FILE_RE.match(doc.path.rsplit("/", 1)[-1])
    return int(match.group(1)) if match else 0


def volume_span(doc: CanonicalDocument) -> str:
    """A volume's recorded date span, or "" — read off frontmatter, never recomputed."""
    return str((doc.frontmatter or {}).get(VOLUME_SPAN_KEY) or "").strip()


def volumes_of(
    active_path: str, docs: Sequence[CanonicalDocument]
) -> list[CanonicalDocument]:
    """Every existing closed volume of `active_path`, oldest volume first."""
    return sorted(
        (d for d in docs if volume_of(d) == active_path), key=volume_number
    )


# ================================================================ frontmatter anchor ledger


def _anchor_list(frontmatter: Mapping, key: str) -> tuple[str, ...]:
    raw = str((frontmatter or {}).get(key) or "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def overview_anchors(frontmatter: Mapping) -> tuple[str, ...]:
    """The ids of the active document's current overview points (frontmatter ledger)."""
    return _anchor_list(frontmatter, OVERVIEW_ANCHORS_KEY)


def catalog_anchors(frontmatter: Mapping) -> tuple[str, ...]:
    """The ids of the open volume's current volume-catalog entries."""
    return _anchor_list(frontmatter, CATALOG_ANCHORS_KEY)


def managed_anchors(frontmatter: Mapping) -> set[str]:
    """Every groom-authored anchor in the open volume (digest ∪ catalog).

    These are the ONLY anchors a groom may add or drop; everything else is a real claim and
    is conserved to the letter (`run_groom_gate`).
    """
    return set(overview_anchors(frontmatter)) | set(catalog_anchors(frontmatter))


# ======================================================================= body segmentation


@dataclass(frozen=True)
class _Unit:
    """One line-run of a body: a heading, a blank line, or a claim block."""

    kind: Literal["heading", "blank", "block"]
    lines: tuple[str, ...]
    level: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _units(body: str) -> list[_Unit]:
    """Segment a body into headings / blanks / claim blocks.

    Block segmentation is byte-identical to `anchor_ops._iter_content_blocks` (a list item is
    one block; a paragraph runs until a blank, heading, list item or its own anchor line),
    because the whole point of this module is that the blocks it moves are the same blocks the
    gate and the projection see.
    """
    lines = body.split("\n")
    units: list[_Unit] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            units.append(_Unit("blank", ("",)))
            i += 1
            continue
        heading = _HEADING_RE.match(line)
        if heading is not None:
            units.append(_Unit("heading", (line,), len(heading.group(1))))
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        if not _LIST_ITEM_RE.match(line) and not ANCHOR_MARK_RE.search(line):
            while j < n:
                nxt = lines[j]
                if not nxt.strip() or _HEADING_RE.match(nxt) or _LIST_ITEM_RE.match(nxt):
                    break
                block_lines.append(nxt)
                j += 1
                if ANCHOR_MARK_RE.search(nxt):
                    break
        units.append(_Unit("block", tuple(block_lines)))
        i = j
    return units


def _assemble(units: Sequence[_Unit], keep: set[int]) -> str:
    """Re-emit `units`, keeping only the block units whose index is in `keep`.

    Two mechanical rules make the result safe:

    - a DROPPED block becomes a blank line rather than nothing. Without it, removing a list
      item that sat between two paragraphs would leave those paragraphs adjacent — and
      adjacent paragraphs are ONE block, so two claims would fuse into one and the
      byte-equality gate would (correctly) refuse the whole groom;
    - a heading whose subtree holds no surviving block is dropped, so neither side of the cut
      carries empty sections. The document's `# ` title survives as long as anything does.

    Blank runs are then collapsed to one, which cannot change block segmentation (any blank
    count is one boundary) and cannot change a single block's bytes.
    """
    emitted: list[_Unit] = []
    for index, unit in enumerate(units):
        if unit.kind != "block":
            emitted.append(unit)
        elif index in keep:
            emitted.append(unit)
        else:
            emitted.append(_Unit("blank", ("",)))

    keep_heading = [True] * len(emitted)
    for i, unit in enumerate(emitted):
        if unit.kind != "heading":
            continue
        has_block = False
        for j in range(i + 1, len(emitted)):
            other = emitted[j]
            if other.kind == "heading" and other.level <= unit.level:
                break
            if other.kind == "block":
                has_block = True
                break
        keep_heading[i] = has_block

    lines: list[str] = []
    for i, unit in enumerate(emitted):
        if unit.kind == "heading" and not keep_heading[i]:
            continue
        lines.extend(unit.lines)

    out: list[str] = []
    for line in lines:
        if not line.strip():
            if not out or not out[-1].strip():
                continue
            out.append("")
        else:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def strip_blocks(body: str, anchors: set[str]) -> str:
    """The body with every block carrying one of `anchors` removed (headings pruned)."""
    if not anchors:
        return body
    units = _units(body)
    keep = {
        index
        for index, unit in enumerate(units)
        if unit.kind == "block"
        and not (set(extract_anchors(unit.text)) & anchors)
    }
    return _assemble(units, keep)


def select_blocks(body: str, anchors: set[str]) -> list[str]:
    """The blocks of `body` carrying one of `anchors`, in document order, verbatim."""
    return [
        block
        for block in anchored_blocks(body)
        if set(extract_anchors(block)) & anchors
    ]


# ================================================================================= the plan


@dataclass(frozen=True)
class RolloverPlan:
    """Everything a rollover needs that does NOT require a model, decided mechanically."""

    active_path: str
    active_frontmatter: dict
    volume_path: str
    volume_number: int
    #: The closing claim blocks with their headings — the new volume's body. Verbatim in every
    #: byte except the relative links, which are re-rendered for the volume's depth so they keep
    #: pointing at the documents they pointed at (see "relative links travel along" above).
    closed_body: str
    #: Verbatim retained tail — the open volume's claims after the cut.
    kept_body: str
    closed_claims: int
    kept_claims: int
    #: The previous volume card's digest, rendered as plain lines (input for the rewrite).
    previous_overview: str
    #: The document's OVERVIEW REGION, verbatim (compile/documents.py), or `""`.
    #:
    #: The region is the compile channel's wholesale-rewritable head and this channel's
    #: business is the ledger, so a rollover carries it across untouched: it is lifted out
    #: before the cut is planned (so its blocks can never be rolled into a volume, which
    #: would tear the region in half across two documents) and re-emitted under the title of
    #: the rewritten open volume. The two heads then sit one above the other and stay
    #: disjoint by construction — the groom's volume card is written into the ledger area
    #: below, and the `rollover_overview_anchors` ledger never names a region anchor.
    overview_region: str
    #: Every closed volume of this subject after the rollover, oldest first: (path, claims, span).
    volumes: tuple[tuple[str, int, str], ...]
    #: Anchors this groom may legitimately drop (the volume card it is replacing).
    replaced_anchors: frozenset[str]
    #: Every anchor in the repo that is NOT being replaced — the collision seed for new ids.
    reserved_anchors: frozenset[str]


def needs_rollover(text: str, threshold_chars: int) -> bool:
    """The trigger predicate: a written document over the configured size. 0 disables it."""
    return threshold_chars > 0 and len(text) > threshold_chars


def _cut_ordinal(units: Sequence[_Unit], keep_recent_chars: int) -> int:
    """How many of the leading claim blocks close into the new volume.

    Walks the blocks from the END, keeping whole blocks while the retained tail fits in
    `keep_recent_chars` — a claim block is never split, which is the whole reason the budget
    is approximate. The LAST block is always retained, so a rollover can never empty the
    open volume.
    """
    blocks = [i for i, unit in enumerate(units) if unit.kind == "block"]
    if not blocks:
        return 0
    used = 0
    cut = len(blocks) - 1
    for ordinal in range(len(blocks) - 1, -1, -1):
        size = len(units[blocks[ordinal]].text) + 1
        if ordinal != len(blocks) - 1 and used + size > keep_recent_chars:
            break
        used += size
        cut = ordinal
    return cut


def plan_rollover(
    active: CanonicalDocument,
    docs: Sequence[CanonicalDocument],
    *,
    path_templates: Sequence[str],
    keep_recent_chars: int,
) -> RolloverPlan | None:
    """Decide the cut, or return None when this document cannot/need not be rolled over.

    None means: this document is not one the skill owns (so it has no volume directory of its
    own — including a closed volume, which is never rolled over again), or the retained tail
    already accounts for every claim (nothing to close — one oversized claim block, or a
    threshold set below the keep-recent budget).
    """
    volume_no = len(volumes_of(active.path, docs)) + 1
    volume = volume_path_for(active.path, volume_no)
    if history_volume_owner(volume, list(path_templates)) != active.path:
        return None
    if any(d.path == volume for d in docs):
        return None

    managed = managed_anchors(active.frontmatter)
    previous_overview = "\n".join(
        select_blocks(active.body, set(overview_anchors(active.frontmatter)))
    )
    region = overview_region(active.body)
    claims_body = strip_blocks(strip_overview(active.body), managed)

    units = _units(claims_body)
    blocks = [i for i, unit in enumerate(units) if unit.kind == "block"]
    cut = _cut_ordinal(units, keep_recent_chars)
    if cut <= 0:
        return None

    # The volume lives one level deeper than the page, so the closing text is re-rendered for
    # its new position: same targets, different relative spelling. The retained tail does not
    # move, so it is not touched at all.
    closed_body = relink(
        _assemble(units, set(blocks[:cut])), from_path=active.path, to_path=volume
    )
    kept_body = _assemble(units, set(blocks[cut:]))

    volumes = tuple(
        (d.path, len(anchored_blocks(d.body)), volume_span(d))
        for d in volumes_of(active.path, docs)
    ) + ((volume, len(anchored_blocks(closed_body)), volume_date_span(closed_body)),)

    reserved = {
        anchor for d in docs for anchor in extract_anchors(d.body)
    } - managed
    return RolloverPlan(
        active_path=active.path,
        active_frontmatter=dict(active.frontmatter),
        volume_path=volume,
        volume_number=volume_no,
        closed_body=closed_body,
        kept_body=kept_body,
        closed_claims=len(anchored_blocks(closed_body)),
        kept_claims=len(anchored_blocks(kept_body)),
        previous_overview=previous_overview,
        overview_region=region,
        volumes=volumes,
        replaced_anchors=frozenset(managed),
        reserved_anchors=frozenset(reserved),
    )


# ============================================================== the overview (the LLM step)


@dataclass(frozen=True)
class OverviewPoint:
    """One line of the volume card: a statement plus the closed-volume anchors it rests on."""

    text: str
    anchors: tuple[str, ...]


class _OverviewPointDraft(BaseModel):
    """One proposed digest point. `anchors` is the point's whole provenance."""

    text: str = ""
    anchors: list[str] = Field(default_factory=list)


class _OverviewDraft(BaseModel):
    """The model's answer: the whole replacement digest, points in reading order."""

    points: list[_OverviewPointDraft] = Field(default_factory=list)


OverviewReason = Literal["written", "call_failed", "parse_error", "empty"]


def render_overview_input(
    plan: RolloverPlan, *, budget: int = OVERVIEW_INPUT_BUDGET_CHARS
) -> str:
    """The HumanMessage for the digest call: what is being closed + the card to replace.

    The closing body is passed with its anchor comments intact — that is how the model can
    name the evidence for each point at all.
    """
    closing = plan.closed_body
    omitted = 0
    if len(closing) > budget:
        lines = closing.split("\n")
        kept: list[str] = []
        used = 0
        for line in reversed(lines):
            if used + len(line) + 1 > budget:
                omitted += 1
                continue
            kept.append(line)
            used += len(line) + 1
        closing = "\n".join(reversed(kept))

    parts = [
        prompt(
            "compile.groom.task_header",
            path=plan.active_path,
            volume=plan.volume_path,
            claims=plan.closed_claims,
        ),
        "",
        prompt("compile.groom.previous_header"),
        plan.previous_overview.strip() or prompt("compile.groom.previous_empty"),
        "",
        prompt("compile.groom.closing_header"),
    ]
    if omitted:
        parts.append(prompt("compile.groom.closing_truncated", count=omitted))
    parts.append(closing)
    return "\n".join(parts)


async def write_overview(
    *,
    model: BaseChatModel,
    plan: RolloverPlan,
    known_anchors: set[str],
    budget: int = OVERVIEW_INPUT_BUDGET_CHARS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[list[OverviewPoint], OverviewReason]:
    """Run the ONE model call a rollover makes → `(points, reason)`.

    The model's only job is the volume card. Everything else about a rollover is mechanical,
    so there is nothing else here for it to get wrong — and its output is filtered before it
    is trusted: a point with no text, or whose named anchors are not actually closed-volume
    anchors of this subject, is DROPPED rather than repaired. A call that fails, fails to
    parse, or yields no usable point returns a reason and no points; the caller abandons the
    groom and the document is left exactly as it was.
    """
    structured = model.with_structured_output(_OverviewDraft, include_raw=True)
    config = {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": "compile.groom.overview",
    }
    try:
        raw = await structured.ainvoke(
            [
                SystemMessage(content=prompt("compile.groom.contract")),
                HumanMessage(content=render_overview_input(plan, budget=budget)),
            ],
            config=config,
        )
    except Exception:  # noqa: BLE001 — a groom failure is abandoned, never raised at a worker
        return [], "call_failed"

    parsed = raw.get("parsed") if isinstance(raw, Mapping) else raw
    if not isinstance(parsed, _OverviewDraft):
        return [], "parse_error"

    points: list[OverviewPoint] = []
    for draft in parsed.points:
        text = " ".join(str(draft.text or "").split())
        anchors = tuple(
            dict.fromkeys(
                a
                for a in (str(x).strip().removeprefix("c:") for x in draft.anchors)
                if a in known_anchors
            )
        )
        if not text or not anchors:
            continue
        points.append(OverviewPoint(text=text, anchors=anchors))
    if not points:
        return [], "empty"
    return points, "written"


# ================================================================================ rendering


def _anchored(block: str, anchor: str) -> str:
    return f"{block.rstrip()} <!-- c:{anchor} -->"


# A trailing parenthetical (either bracket family) whose contents carry anchors.
_EVIDENCE_TAIL_RE = re.compile(r"[（(][^（()）]*[)）]\s*$")


def _without_duplicate_evidence_tail(text: str, anchors: Sequence[str]) -> str:
    """Drop a trailing evidence parenthetical the renderer is about to write anyway.

    A second rollover of the same document shows the model the card it is replacing, whose
    lines already END in the rendered evidence tail. The model merges those lines and carries
    the tail into its `text`, so the renderer appended a second one and the line came out
    reading `…（依据 c:a, c:b）（依据 c:b, c:c）` (observed on a real library).

    Only a tail whose anchors are all anchors of THIS point is removed: that makes it a
    verbatim duplicate of what gets appended. A tail naming anything else is left alone —
    prose may legitimately cite an anchor, and the gate is what judges those."""
    if not anchors:
        return text
    match = _EVIDENCE_TAIL_RE.search(text)
    if match is None:
        return text
    tail = match.group(0)
    cited = set(re.findall(r"c:([0-9a-f]+)", tail))
    if not cited or not cited <= set(anchors):
        return text
    return text[: match.start()].rstrip()


def render_overview_blocks(
    plan: RolloverPlan, points: Sequence[OverviewPoint]
) -> tuple[list[str], list[str]]:
    """`(blocks, anchors)` for the volume card's digest.

    Anchors are deterministic per (document, slot index) and seeded with every anchor the
    repo holds MINUS the card being replaced — so rewriting the card in place reuses the same
    ids and the projection sees an edit, not a churn of deletes and inserts.
    """
    taken = set(plan.reserved_anchors)
    blocks: list[str] = []
    anchors: list[str] = []
    for index, point in enumerate(points):
        anchor = assign_anchor(plan.active_path, f"rollover-overview-{index}", taken)
        taken.add(anchor)
        line = prompt(
            "compile.groom.overview_point",
            text=_without_duplicate_evidence_tail(point.text, point.anchors),
            anchors=", ".join(f"c:{a}" for a in point.anchors),
        )
        blocks.append(_anchored(line, anchor))
        anchors.append(anchor)
    return blocks, anchors


def render_catalog_blocks(plan: RolloverPlan) -> tuple[list[str], list[str]]:
    """`(blocks, anchors)` for the volume catalog — one markdown link per closed volume.

    The link is what matters: markdown links are the form the projection layer turns into
    knowledge-graph edges, so listing the volumes this way makes the earlier volumes reachable
    by the same hop mechanism as every other inter-document relation. The href is relative to
    the open volume (`<stem>/aNN.md`), which is what the gate's and the dataset's shared
    resolver expects, and the LINK TEXT is the volume's date span — the one thing that lets a
    reader pick which volume to open. A volume whose entries state no date falls back to its
    own name rather than to a guessed period.
    """
    taken = set(plan.reserved_anchors)
    stem = history_dir(plan.active_path).rsplit("/", 1)[-1]
    blocks: list[str] = []
    anchors: list[str] = []
    for path, claims, span in plan.volumes:
        filename = path.rsplit("/", 1)[-1]
        number = int(_VOLUME_FILE_RE.match(filename).group(1))
        anchor = assign_anchor(plan.active_path, f"rollover-volume-{number:02d}", taken)
        taken.add(anchor)
        line = prompt(
            "compile.groom.volume_entry",
            number=f"{number:02d}",
            title=span or filename.removesuffix(".md"),
            href=f"{stem}/{filename}",
            claims=claims,
        )
        blocks.append(_anchored(line, anchor))
        anchors.append(anchor)
    return blocks, anchors


def _split_title(body: str) -> tuple[str, str]:
    """`(title_line, rest)` — the document's `# ` title stays first in the rewritten body."""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = _HEADING_RE.match(line)
        if match is not None and len(match.group(1)) == 1:
            rest = "\n".join(lines[index + 1 :]).strip("\n")
            return line, rest
        break
    return "", body.strip("\n")


def render_active_body(
    plan: RolloverPlan, overview_blocks: Sequence[str], catalog_blocks: Sequence[str]
) -> str:
    """The rewritten open volume: title → overview region → volume card → catalog → tail.

    The overview REGION (the compile channel's head, `compile/documents.py`) is re-emitted
    verbatim directly under the title — the position it holds in every other document — while
    the volume card this channel writes goes below it. Two heads, one above the other, and a
    rollover neither reads nor rewrites the upper one.
    """
    title, tail = _split_title(plan.kept_body)
    parts: list[str] = []
    if title:
        parts.extend([title, ""])
    if plan.overview_region:
        parts.extend([plan.overview_region, ""])
    if overview_blocks:
        parts.append(prompt("compile.groom.overview_heading"))
        parts.append("")
        for block in overview_blocks:
            parts.append(block)
        parts.append("")
    if catalog_blocks:
        parts.append(prompt("compile.groom.volumes_heading"))
        parts.append("")
        for block in catalog_blocks:
            parts.append(block)
        parts.append("")
    if tail:
        parts.append(tail)
    return "\n".join(parts).strip("\n") + "\n"


def volume_frontmatter(plan: RolloverPlan) -> dict:
    """A closed volume's frontmatter: a complete document in its own right, stamped as one.

    Complete on purpose — a volume is read off git like any other canonical document, so it has
    to satisfy the same frontmatter check. `slug` is its filename inside the volume directory
    (`a01`); the volume needs no slug of its own because its identity is "the Nth volume of
    that page", which the owning-page stamp states outright.
    """
    active_type = str(plan.active_frontmatter.get("type") or "").strip()
    frontmatter = {
        "doc_id": str(assign_document_id(plan.volume_path)),
        # Legacy spelling, kept on disk for the same reason `VOLUME_OF_KEY` is: this value is
        # written into every user's git library, so changing it would make two spellings of one
        # fact. It is only the fallback for a page that declares no `type` of its own.
        "type": active_type or "archive",
        "slug": plan.volume_path.rsplit("/", 1)[-1].removesuffix(".md"),
        VOLUME_OF_KEY: plan.active_path,
        VOLUME_NUMBER_KEY: f"{plan.volume_number:02d}",
    }
    span = plan.volumes[-1][2] if plan.volumes else ""
    if span:
        frontmatter[VOLUME_SPAN_KEY] = span
    return frontmatter


# ===================================================================== the groom-only gate


@dataclass(frozen=True)
class _DocView:
    """The minimal shape `gate.check_*` reads, so the shared checks are reused verbatim."""

    frontmatter: dict
    body: str


def run_groom_gate(
    *,
    plan: RolloverPlan,
    active_frontmatter: dict,
    active_body: str,
    volume_frontmatter_: dict,
    volume_body: str,
    base_docs: Sequence[CanonicalDocument],
    path_templates: Sequence[str],
    overview_blocks: Sequence[str],
    overview_anchor_ids: Sequence[str],
    catalog_anchor_ids: Sequence[str],
) -> list[Violation]:
    """The groom channel's own gate. Every check hard-rejects; ANY violation abandons the
    whole rollover and leaves the document byte-identical to what it was.

    1. `groom_bytes` — the move is VERBATIM OUTSIDE LINKS: with every canonical link href
       elided, the multiset of claim blocks in (new active ∪ new volume) equals the multiset
       in the old active document. Not "the same claims" — the same BYTES, so a rollover can
       neither reword nor reflow a claim.
    1b. `groom_links` — and SEMANTICALLY EXACT INSIDE them: read from wherever it now lives,
       each moved claim carries the same number of links, in the same order, resolving to the
       same documents as before. The href bytes may change (they must, when the depth does);
       what they point at may not. Together, 1 and 1b are the conservation invariant — a
       relative link is a rendering of a target, so preserving its bytes across a move is
       exactly how a groom used to break 556 of them.
    1c. `groom_links` — repo-wide, the rollover does not raise the count of unresolvable
       links. 1b is per-claim and local; this one catches any way a move could cost the graph
       an edge that per-claim bookkeeping missed.
    2. `groom_conservation` — repo-wide CLAIM anchors are conserved exactly: none lost, none
       invented. The only anchors allowed to appear or disappear are the groom-managed card
       ids, which the frontmatter ledger declares.
    3. `anchor_uniqueness` — repo-wide, over the post-rollover tree (shared with compile).
    4. `groom_overview` — every digest point names at least one `c:` anchor, and every
       anchor it names actually lives in a closed volume of THIS subject. A point that cites
       nothing, or cites something outside the earlier volumes, is not a summary — it is a
       new uncited assertion in the one non-rebuildable layer.
    5. `anchor_coverage` — both written documents carry an anchor on every content block
       (shared with compile). Without this a groom could brick every later compile.
    6. `frontmatter` / `path` — both written documents are complete and inside the skill's
       declared families (shared with compile).
    """
    violations: list[Violation] = []

    base_by_path = {d.path: d for d in base_docs}
    old_active = base_by_path.get(plan.active_path)
    old_body = old_active.body if old_active is not None else ""

    managed_before = managed_anchors(
        old_active.frontmatter if old_active is not None else {}
    )
    managed_after = set(overview_anchor_ids) | set(catalog_anchor_ids)

    after_docs: dict[str, _DocView] = {
        d.path: _DocView(dict(d.frontmatter), d.body)
        for d in base_docs
        if d.path != plan.active_path
    }
    after_docs[plan.active_path] = _DocView(dict(active_frontmatter), active_body)
    after_docs[plan.volume_path] = _DocView(dict(volume_frontmatter_), volume_body)

    # The claim blocks on each side of the move, tagged with the position they are read from —
    # which is the whole point: a block's link targets are a function of where it lives.
    before_claims = [
        (block, plan.active_path)
        for block in select_blocks(old_body, set(extract_anchors(old_body)) - managed_before)
    ]
    after_claims = [
        (block, plan.active_path)
        for block in select_blocks(
            active_body, set(extract_anchors(active_body)) - managed_after
        )
    ] + [(block, plan.volume_path) for block in anchored_blocks(volume_body)]

    # 1. byte-equal move over CLAIM blocks, links elided (the card is excluded on both sides).
    before_literals = sorted(link_elided(block) for block, _ in before_claims)
    after_literals = sorted(link_elided(block) for block, _ in after_claims)
    if before_literals != after_literals:
        violations.append(
            Violation(
                "groom_bytes",
                plan.active_path,
                prompt(
                    "gate.groom.claims_not_byte_equal",
                    before=len(before_claims),
                    after=len(after_claims),
                ),
            )
        )

    # 1b. per-claim link-target conservation. Claims are paired by their anchors — the one
    # identity that survives a move — rather than by text, so a re-rendered href cannot make
    # two claims look like each other's counterpart.
    def _by_anchor(
        claims: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, ...], tuple[str, ...]]:
        return {
            tuple(sorted(extract_anchors(block))): link_targets(block, path)
            for block, path in claims
        }

    targets_before = _by_anchor(before_claims)
    targets_after = _by_anchor(after_claims)
    for key in sorted(targets_before):
        was, now = targets_before[key], targets_after.get(key)
        if now is None or was == now:
            continue  # a claim that vanished entirely is check 2's business, not this one
        anchor = key[0] if key else ""
        if len(was) != len(now):
            violations.append(
                Violation(
                    "groom_links",
                    plan.active_path,
                    prompt(
                        "gate.groom.link_count_changed",
                        anchor=anchor,
                        before=len(was),
                        after=len(now),
                    ),
                )
            )
            continue
        for old_target, new_target in zip(was, now):
            if old_target != new_target:
                violations.append(
                    Violation(
                        "groom_links",
                        plan.active_path,
                        prompt(
                            "gate.groom.link_target_changed",
                            anchor=anchor,
                            before=old_target,
                            after=new_target,
                        ),
                    )
                )

    # 1c. repo-wide: the rollover may not leave the graph with more dead ends than it found.
    dead_before = dead_links({d.path: d.body for d in base_docs})
    dead_after = dead_links({path: view.body for path, view in after_docs.items()})
    if dead_after > dead_before:
        violations.append(
            Violation(
                "groom_links",
                plan.active_path,
                prompt(
                    "gate.groom.dead_links_increased",
                    before=dead_before,
                    after=dead_after,
                ),
            )
        )

    # 2. repo-wide claim-anchor conservation.
    before_anchors = {a for d in base_docs for a in extract_anchors(d.body)} - managed_before
    after_anchors = {
        a for view in after_docs.values() for a in extract_anchors(view.body)
    } - managed_after
    for anchor in sorted(before_anchors - after_anchors):
        violations.append(
            Violation(
                "groom_conservation",
                plan.active_path,
                prompt("gate.groom.anchor_lost", anchor=anchor),
            )
        )
    for anchor in sorted(after_anchors - before_anchors):
        violations.append(
            Violation(
                "groom_conservation",
                plan.active_path,
                prompt("gate.groom.anchor_added", anchor=anchor),
            )
        )

    # 3. repo-wide anchor uniqueness (shared check).
    violations.extend(check_anchor_uniqueness(after_docs))

    # 4. digest provenance: every point cites an anchor living in one of this subject's volumes.
    closed_anchors: set[str] = set(extract_anchors(volume_body))
    for doc in base_docs:
        if volume_of(doc) == plan.active_path:
            closed_anchors |= set(extract_anchors(doc.body))
    for block in overview_blocks:
        cited = {m.group(1) for m in re.finditer(r"\bc:([0-9a-f]{4,})\b", block)}
        own = set(extract_anchors(block))
        cited -= own
        preview = " ".join(block.split())[:48]
        if not cited:
            violations.append(
                Violation(
                    "groom_overview",
                    plan.active_path,
                    prompt("gate.groom.overview_without_reference", preview=preview),
                )
            )
            continue
        for anchor in sorted(cited - closed_anchors):
            violations.append(
                Violation(
                    "groom_overview",
                    plan.active_path,
                    prompt(
                        "gate.groom.overview_unknown_reference",
                        preview=preview,
                        anchor=anchor,
                    ),
                )
            )

    # 5 + 6. shared coverage / frontmatter / path ownership over what this groom writes.
    written = {
        plan.active_path: after_docs[plan.active_path],
        plan.volume_path: after_docs[plan.volume_path],
    }
    violations.extend(check_anchor_coverage(written))
    violations.extend(check_frontmatter(written))
    # Path ownership, groom's own reading of it: the active document must be one the skill owns,
    # and the volume must be one of THAT document's history-directory volumes. The second half
    # is the mechanical derivation the write templates deliberately do not cover — which is
    # exactly what keeps this the only channel that can put a file there.
    if not path_allowed(plan.active_path, list(path_templates)):
        violations.append(
            Violation(
                "path",
                plan.active_path,
                prompt("gate.path_not_owned", templates=", ".join(path_templates)),
            )
        )
    if history_volume_owner(plan.volume_path, list(path_templates)) != plan.active_path:
        violations.append(
            Violation(
                "path",
                plan.volume_path,
                prompt("gate.path_not_owned", templates=", ".join(path_templates)),
            )
        )
    return violations


# ================================================================================ assembly


@dataclass(frozen=True)
class RolloverResult:
    """The outcome of one rollover: files to commit, or violations and nothing to commit."""

    status: Literal["ready", "rejected"]
    files: dict[str, str] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    closed_claims: int = 0
    volume_path: str = ""
    overview_points: int = 0


def build_rollover(
    plan: RolloverPlan,
    points: Sequence[OverviewPoint],
    base_docs: Sequence[CanonicalDocument],
    *,
    path_templates: Sequence[str],
) -> RolloverResult:
    """Assemble the two files and run the groom gate. Nothing here touches a store.

    `status="rejected"` means the caller commits NOTHING: a rollover is all-or-nothing by
    construction, because a half-applied one would have moved claims out of the open volume
    without recording where they went.
    """
    overview_blocks, overview_ids = render_overview_blocks(plan, points)
    catalog_blocks, catalog_ids = render_catalog_blocks(plan)

    active_body = render_active_body(plan, overview_blocks, catalog_blocks)
    active_frontmatter = dict(plan.active_frontmatter)
    active_frontmatter[VOLUME_COUNT_KEY] = str(len(plan.volumes))
    active_frontmatter[OVERVIEW_ANCHORS_KEY] = ",".join(overview_ids)
    active_frontmatter[CATALOG_ANCHORS_KEY] = ",".join(catalog_ids)

    volume_fm = volume_frontmatter(plan)
    volume_body = plan.closed_body

    # Both files this channel writes get the same derived `title` every compile write gets:
    # the page's own `# ` heading, and a volume's own — a closed volume is a canonical document
    # in its own right, so it is named by what stands at the top of it, not by what the page it
    # was cut out of happens to be called. Derived BEFORE the gate, so the groom gate judges
    # the frontmatter that will actually be committed.
    active_frontmatter = with_derived_title(active_frontmatter, active_body)
    volume_fm = with_derived_title(volume_fm, volume_body)

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=active_frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=volume_body,
        base_docs=base_docs,
        path_templates=path_templates,
        overview_blocks=overview_blocks,
        overview_anchor_ids=overview_ids,
        catalog_anchor_ids=catalog_ids,
    )
    if violations:
        return RolloverResult(status="rejected", violations=violations)

    return RolloverResult(
        status="ready",
        files={
            plan.active_path: render_document(active_frontmatter, active_body),
            plan.volume_path: render_document(volume_fm, volume_body),
        },
        closed_claims=plan.closed_claims,
        volume_path=plan.volume_path,
        overview_points=len(points),
    )


def commit_message(plan: RolloverPlan) -> str:
    """The one-line git subject for a rollover commit."""
    return prompt(
        "compile.groom.commit_message",
        path=plan.active_path,
        claims=plan.closed_claims,
        volume=plan.volume_path,
    )


# ======================================================= healing what an old groom broke
#
# Every volume written before the depth compensation above carries links that resolve one
# level SHORT. That damage is mechanically identifiable — and only that damage: a link that
# fails from the volume but succeeds when resolved from the PARENT page is, by construction,
# a link the move mis-rendered, because the parent page is exactly the position the text was
# written at. Anything else that does not resolve was already broken when the model wrote it,
# and this pass leaves it alone: repairing an author's wrong target is a judgement about what
# they meant, and this channel makes no judgements.


@dataclass(frozen=True)
class HealResult:
    """The outcome of one heal pass: files to commit, nothing to do, or violations."""

    status: Literal["ready", "clean", "rejected"]
    files: dict[str, str] = field(default_factory=dict)
    healed_links: int = 0
    dead_before: int = 0
    dead_after: int = 0
    violations: list[Violation] = field(default_factory=list)


def _heal_body(
    body: str, *, volume_path: str, parent_path: str, known: set[str]
) -> tuple[str, int, tuple[str, ...]]:
    """`(healed body, links repaired, the target each link is meant to end up at)`.

    A link is repaired only when it fails from the volume AND succeeds from the parent page —
    the signature of a move that did not re-render it. Every other link is left byte-identical
    and its current target is what it is meant to keep.
    """
    repaired = 0
    intended: list[str] = []

    def _rewrite(match: re.Match[str]) -> str:
        nonlocal repaired
        href = match.group(1)
        if not _rewritable(href):
            return match.group(0)
        path_part, sep, fragment = href.partition("#")
        here = _resolve_relative(volume_path, path_part)
        there = _resolve_relative(parent_path, path_part)
        if here in known or there not in known or there == here:
            intended.append(here)
            return match.group(0)
        repaired += 1
        intended.append(there)
        return f"]({_render_relative(volume_path, there)}{sep}{fragment})"

    healed = _MD_LINK_RE.sub(_rewrite, body)
    return healed, repaired, tuple(intended)


def heal_volume_links(docs: Sequence[CanonicalDocument]) -> HealResult:
    """Re-render the links a pre-compensation groom left resolving one level short.

    Idempotent by construction: once every volume link resolves, nothing matches the "fails
    here, succeeds from the parent" test and the pass returns `clean` with no files — so it is
    safe to run on every repo, including ones that never had the defect.

    The same two-clause invariant the rollover gate asserts holds here, read for this move:
    non-link bytes are untouched, each rewritten link resolves to the target the parent page
    resolved it to, and the repo-wide dead-link count strictly DROPS (a heal that repaired
    nothing has no business writing a commit).

    ONE DELIBERATE EXCEPTION to "non-link bytes are untouched": a file this pass rewrites is
    serialized with its DERIVED title (`with_derived_title`), so its frontmatter `title` may
    change or appear. `title` is not stored content — it is read off the document's own `# `
    heading at every write path that serializes a changed document, and a repair channel that
    opted out of that rule would be a way for a wrong or missing title to survive a write
    forever. The exception is bounded from both ends: the delta is system-derived from bytes
    this pass did not touch (the heading is not a link), and it only ever rides a file the
    heal was already writing — a volume with a stale title and no repairable link is not
    written at all. Clause 1 is asserted on the BODY for exactly that reason.
    """
    known = {d.path for d in docs}
    files: dict[str, str] = {}
    violations: list[Violation] = []
    healed = 0

    before_bodies = {d.path: d.body for d in docs}
    after_bodies = dict(before_bodies)

    for doc in sorted(docs, key=lambda d: d.path):
        parent = volume_of(doc)
        if not parent or parent not in known:
            continue  # not a volume, or an orphan whose original position is unknowable

        healed_body, repaired, intended = _heal_body(
            doc.body, volume_path=doc.path, parent_path=parent, known=known
        )
        if not repaired:
            continue
        healed += repaired
        after_bodies[doc.path] = healed_body
        files[doc.path] = render_document(
            with_derived_title(dict(doc.frontmatter), healed_body), healed_body
        )

        # the same clause 1, read on the BODY: nothing but link spellings moved there. The
        # frontmatter title is the docstring's one exception — derived, not content.
        if link_elided(healed_body) != link_elided(doc.body):
            violations.append(
                Violation(
                    "groom_bytes",
                    doc.path,
                    prompt("gate.groom.heal_not_byte_equal"),
                )
            )
        # the same clause 1b, read for THIS move: a repaired link resolves to what the PARENT
        # page resolved it to, and an untouched one still resolves where it did.
        landed = link_targets(healed_body, doc.path)
        if landed != intended:
            for want, got in zip(intended, landed):
                if want == got:
                    continue
                violations.append(
                    Violation(
                        "groom_links",
                        doc.path,
                        prompt(
                            "gate.groom.link_target_changed",
                            anchor=doc.path,
                            before=want,
                            after=got,
                        ),
                    )
                )
            if len(landed) != len(intended):
                violations.append(
                    Violation(
                        "groom_links",
                        doc.path,
                        prompt(
                            "gate.groom.link_count_changed",
                            anchor=doc.path,
                            before=len(intended),
                            after=len(landed),
                        ),
                    )
                )

    dead_before = dead_links(before_bodies)
    dead_after = dead_links(after_bodies)
    if not files:
        return HealResult(
            status="clean", dead_before=dead_before, dead_after=dead_after
        )
    if dead_after >= dead_before:
        violations.append(
            Violation(
                "groom_links",
                "",
                prompt(
                    "gate.groom.heal_repaired_nothing",
                    before=dead_before,
                    after=dead_after,
                ),
            )
        )
    if violations:
        return HealResult(status="rejected", violations=violations)
    return HealResult(
        status="ready",
        files=files,
        healed_links=healed,
        dead_before=dead_before,
        dead_after=dead_after,
    )


def heal_commit_message(healed_links: int) -> str:
    """The one-line git subject for a heal commit."""
    return prompt("compile.groom.heal_commit_message", links=healed_links)


__all__ = [
    "CATALOG_ANCHORS_KEY",
    "HealResult",
    "OVERVIEW_ANCHORS_KEY",
    "OVERVIEW_INPUT_BUDGET_CHARS",
    "OverviewPoint",
    "OverviewReason",
    "RolloverPlan",
    "RolloverResult",
    "VOLUME_COUNT_KEY",
    "VOLUME_NUMBER_KEY",
    "VOLUME_OF_KEY",
    "VOLUME_SPAN_KEY",
    "build_rollover",
    "catalog_anchors",
    "claim_occurrence_date",
    "commit_message",
    "date_span",
    "dead_links",
    "heal_commit_message",
    "heal_volume_links",
    "history_dir",
    "is_closed_volume",
    "link_elided",
    "link_targets",
    "managed_anchors",
    "needs_rollover",
    "overview_anchors",
    "plan_rollover",
    "relink",
    "render_active_body",
    "render_overview_input",
    "run_groom_gate",
    "volume_date_span",
    "volume_frontmatter",
    "volume_number",
    "volume_of",
    "volume_path_for",
    "volume_span",
    "volumes_of",
    "write_overview",
]
