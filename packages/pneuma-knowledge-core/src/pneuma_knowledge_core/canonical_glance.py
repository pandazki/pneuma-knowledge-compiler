"""Canonical's SHAPE as a rendered surface — the map the compiler and the answerer share.

WHY THIS MODULE EXISTS
----------------------
The compile side already rendered canonical as an outline (one line per document: path,
type, claim count, section headings) so a job could see what subjects exist and where they
live without paying for their bodies. The recall side had nothing: fast and briefing saw a
flat list of retrieved claims and body windows, deep saw the same plus three search tools.
Both of canonical's own jobs were therefore missing from the answering face — you could not
FOLLOW THE THREAD (no way to open a document and walk its links) and you could not take the
BIRD'S EYE view (no way to see the library's layout at all).

A glance is that layout, always present: the filing families a skill declares, the documents
filed under each, and how developed each document is. It is deliberately not "the relevant
document pasted in" — it is the shape of the library, so any question at all can be located
in it.

ONE MODULE, TWO FACES
---------------------
`render_outline` is the compile face and `render_canonical_glance` is the recall face, and
they live here together on purpose: the mechanical derivations (which paths exist, how many
claims a document carries, what its title is, which family owns it, how a family is
truncated) are stated once, so "the library the compiler sees" and "the library the answerer
sees" cannot drift into two different maps of the same repo.

They are not the same bytes, because they answer different questions. Compile is deciding
WHERE TO WRITE, so its line carries the document type and its section headings. Recall is
deciding WHAT TO READ, so its line carries the title and how recently the document moved.
`render_outline` keeps the compile task's original line grammar (its prompt keys are
unchanged) with one deliberate exception: a frozen rollover volume's line says so — see the
function's own docstring.

WHERE THE ONE-LINE BLURBS COME FROM
-----------------------------------
Nothing new has to be written or maintained:

- **Family level** — a `SchemaPack` already states, in prose the business controls, what its
  filing slots collect. The blurb is its first line, read off the pack STRUCTURE
  (`extra_instructions` keyed by `extra_path_templates`), never parsed out of the skill body.
  A base family declared by the skill itself has no such structured text, so it renders as
  the bare template — which is still the fact that matters (the family exists, this is its
  path shape).
- **Document level** — mechanically derived: title (first `# ` heading, else a frontmatter
  `title`, else the filename stem), claim count (anchors), and the last-updated date when a
  caller can supply one (git, or a frontmatter `updated` field).
- **One level below the title** — the document's overview `definition`, when it has one. This
  is the single line here that a model wrote, and it is the exception that proves the rule
  above: a free-standing summary FIELD would rot silently, but the definition lives inside
  the overview region, which is grounded in the ledger and rewritten whenever the document's
  picture changes. It is maintained by the same act that changes what it describes.
- **The same level, when there is no definition** — the head of the page's own CURRENT ledger,
  rendered as plain text (`ledger:` rather than `definition:`, so the two are never mistaken
  for each other). A page holding little needs no summary written for it: those few claims
  ARE the summary, and you take them in at a glance. Nothing is generated — machinery
  (`[cite:]` spans, anchors, supersedes markers) and markdown are removed and the words are
  the ledger's own, superseded predecessors skipped, stopping on a whole claim under the
  definition's own ceiling — and if not even the first claim fits under it, there is no line
  at all, because a claim cut in half is a different claim.

BUDGET
------
Bounded the way the outline is: documents are sorted, each family keeps its first `top_k`
and states how many it dropped, and the whole render stops at `budget` characters on a line
boundary with an explicit truncation notice. The cost is O(documents) and every line it
emits is bounded — a body is walked for its anchors, its headings and (for a page with no
definition) the head of its claims, never carried into the render whole.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .compile.documents import derived_title, parse_overview, strip_overview
from .compile.overview import ANCHOR_REFERENCE_RE, DEFINITION_MAX_CHARS
from .compile.patch import _VOLUME_FILE_RE, path_allowed
from .compile.rollover import archived_from
from .compile.supersession import SUPERSEDES_MARK_RE, current_blocks, superseded_index
from .components import registered_components
from .domain.canonical import CANONICAL_CITATION_MARKER_RE, CanonicalDocument
from .domain.ids import ANCHOR_MARK_RE, extract_anchors
from .prompts import prompt

#: Whole-glance character budget — the same order of magnitude as the compile outline it is
#: modelled on, so adding the glance to a recall prompt costs a bounded, known amount.
GLANCE_BUDGET_CHARS = 5_000

#: Documents listed per family before the "…and N more" line. A family that has grown past
#: this is better represented by its head plus an honest count than by a wall of paths.
FAMILY_TOP_K = 8

#: A family blurb is one line; a pack paragraph that opens with a long sentence is cut here.
BLURB_CHARS = 180


# ------------------------------------------------------------- mechanical derivations


def claim_count(doc: CanonicalDocument) -> int:
    """How many anchored claims the document's LEDGER carries — its development level.

    The overview region's blocks are not counted. They are a reading of the ledger, replaced
    whole on every rewrite, so counting them would both inflate "how developed is this
    subject" and make the number move when nothing was learned.
    """
    return len(extract_anchors(strip_overview(doc.body)))


def section_headings(doc: CanonicalDocument) -> list[str]:
    """The document's `## ` section headings, in order (the compile face's "what's inside")."""
    return [
        line[3:].strip()
        for line in doc.body.splitlines()
        if line.startswith("## ") and line[3:].strip()
    ]


def document_title(doc: CanonicalDocument) -> str:
    """The document's subject line: first `# ` heading → frontmatter `title` → filename stem.

    Derived rather than stored, so it cannot disagree with the document it names — and read
    through the very function the STORED field is derived with (`compile.documents.
    derived_title`), so the displayed name and the written one cannot disagree with each
    other either. That matters on an annotated heading: `# Mei <!-- c:1a2b3c4d -->` is a page
    named `Mei`, and a second reading of the same line that kept the anchor would put
    machinery in an outline, a glance, and in the name a component reserves for the subject.

    A heading that says nothing once its annotations are removed is not a title, so the
    frontmatter/filename fallback stands behind it exactly as it does for a page with no
    heading at all.
    """
    heading = derived_title(doc.body)
    if heading:
        return heading
    frontmatter = doc.frontmatter or {}
    for key in ("title", "slug"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            return value
    return doc.path.rsplit("/", 1)[-1].removesuffix(".md")


#: How much of a document's definition an outline / glance line carries. One line each, and
#: a definition is one sentence by gate rule, so this only ever fires on a run-on.
DEFINITION_LINE_CHARS = 160


def document_definition(doc: CanonicalDocument) -> str | None:
    """The document's overview `definition` — its one-sentence "what this is" — or None.

    This is the level of detail directly below the title, and it is the ONE thing in these
    two renders that a model wrote rather than the system derived. That is deliberate and it
    is safe: the definition is grounded in the ledger and rewritten whenever the picture
    changes (compile/overview.py), so unlike a stored summary field it cannot rot while the
    document moves on without it. A document with no overview simply has no line.
    """
    overview, _ = parse_overview(doc.body)
    if overview is None:
        return None
    # Display text: the grounding the gate insists on (`c:` references, `[cite:]` spans) is
    # machinery, and these two lines are read by someone deciding what to open.
    text = CANONICAL_CITATION_MARKER_RE.sub("", overview.definition)
    text = " ".join(ANCHOR_REFERENCE_RE.sub("", text).split())
    if not text:
        return None
    return (
        text
        if len(text) <= DEFINITION_LINE_CHARS
        else text[:DEFINITION_LINE_CHARS].rstrip() + "…"
    )


#: Markdown scaffolding canonical text carries for the PAGE's sake — its list bullet, a
#: heading marker on a block that opens a section, a blockquote marker. Structure, never a
#: word, and a display line is one line of plain text, so all of it is dropped.
_MD_BULLET_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
_MD_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+")
_MD_QUOTE_RE = re.compile(r"^[ \t]*(?:>[ \t]?)+")

#: An HTML comment — an anchor mark, a supersedes marker, an editorial note. All machinery,
#: and the visible text on either side of it is not: `a <!-- x --> b` is `a b`.
_MD_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: An image, then a link — in that order, because `![alt](src)` contains link syntax and the
#: alt text is what a reader of one line can use. A link keeps its LABEL and drops its
#: destination: the label is what the writer wrote, the href is an address.
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_LABEL_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

#: Paired emphasis / strikethrough / inline code, keeping what they wrap. The underscore form
#: is matched only at word boundaries so `snake_case_names` survives intact; whatever markers
#: are left unpaired are swept afterwards, because a stray `**` is typography either way.
_MD_PAIRED_RE = re.compile(r"(\*\*|__|~~)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_MD_EM_STAR_RE = re.compile(r"(?<!\*)\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)")
_MD_EM_UNDER_RE = re.compile(r"(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])")
_MD_CODE_RE = re.compile(r"`+([^`]*)`+")
_MD_LEFTOVER_MARKS_RE = re.compile(r"\*\*|__|~~")


def markdown_display_text(text: str) -> str:
    """Markdown as one line of plain display text — the words, none of the typography.

    The one place this repository turns canonical markdown into a line a PERSON reads (the
    glance / outline ledger line). It is one function rather than a strip per caller because
    "plain text" was the claim being made and half of it was true: a line that still carries
    `[Delta](../delta.md)`, `*paused*` or `` `P0` `` is a line that says the file layout and
    the emphasis markers out loud, and an href is longer than most of the sentence it sits in.

    What it removes is form: HTML comments (without eating the visible text around them),
    image and link syntax (keeping the alt text and the label), emphasis, strikethrough,
    inline code, list bullets, heading markers, blockquote markers, and every line break —
    the words themselves are never touched, and nothing is generated.
    """
    text = _MD_COMMENT_RE.sub("", text)
    text = _MD_IMAGE_RE.sub(r"\1", text)
    text = _MD_LINK_LABEL_RE.sub(r"\1", text)
    lines = [
        _MD_HEADING_RE.sub("", _MD_BULLET_RE.sub("", _MD_QUOTE_RE.sub("", line)))
        for line in text.split("\n")
    ]
    text = " ".join(lines)
    text = _MD_PAIRED_RE.sub(r"\2", text)
    text = _MD_EM_STAR_RE.sub(r"\1", text)
    text = _MD_EM_UNDER_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    return " ".join(_MD_LEFTOVER_MARKS_RE.sub("", text).split())


#: What separates two claims on the fallback line. A claim is a whole statement, so the join
#: has to read as "and another one" rather than as punctuation inside a sentence.
LEDGER_LINE_JOINER = " · "


def claim_display_text(block: str) -> str:
    """One claim as plain display text: machinery and markdown removed, one line.

    Everything stripped here is addressing or typography — `[cite:]` spans, the anchor
    comment, the supersedes comment, and then (via `markdown_display_text`) the markdown the
    claim wears — never a word the claim actually says.

    Public because a claim reaches a PERSON in more than one place now: the ledger line under
    a title, and the bounded head a stage preview carries (`recall/stage_timing.py`). Both are
    the same operation on the same text, so they are the same function — a second strip written
    beside this one would drift, and the drift would show up as machinery on a screen.
    """
    text = CANONICAL_CITATION_MARKER_RE.sub("", block)
    text = ANCHOR_MARK_RE.sub("", text)
    text = SUPERSEDES_MARK_RE.sub("", text)
    return markdown_display_text(text)


def document_ledger_line(
    doc: CanonicalDocument, superseded: Iterable[str] = ()
) -> str | None:
    """The head of the document's CURRENT ledger as one plain line, or None when it has none.

    This is the fallback for the line below the title on a page with no overview definition,
    and the reason it is honest is the reason the owner gave for wanting it: when a page holds
    little, its claims ARE its overview — you take them in at a glance, and a rendered
    "no summary yet" would be less informative than the two sentences it is standing in front
    of. Nothing is generated: this is the ledger's own words with its machinery removed.

    Superseded predecessors are skipped (`superseded` is the repository-wide dead set, so a
    successor living in another document still retires its predecessor here), the overview
    region is not read at all, and the line stops at `DEFINITION_MAX_CHARS` — the same ceiling
    the definition it stands in for is written under, so the slot below a title costs the same
    whichever of the two fills it.

    It stops on a whole claim ALWAYS, never on a character: half a claim reads as a fact, and
    a fact cut in half is a different fact. The claim whose negation, qualifier or outcome
    lands past the ceiling ("…, but the board did not approve it") would be shown here as its
    own opposite, and it would be shown in the one slot a reader takes at face value because
    everything else in it is derived. So when the first current claim does not fit, this page
    simply has no ledger line — the title, the path and the claim count still say the page is
    there and how developed it is, and the page itself is one hop away.
    """
    kept: list[str] = []
    used = 0
    for block in current_blocks(strip_overview(doc.body), superseded):
        text = claim_display_text(block)
        if not text:
            continue
        if not kept:
            if len(text) > DEFINITION_MAX_CHARS:
                return None
            kept.append(text)
            used = len(text)
            continue
        if used + len(LEDGER_LINE_JOINER) + len(text) > DEFINITION_MAX_CHARS:
            break
        kept.append(text)
        used += len(LEDGER_LINE_JOINER) + len(text)
    return LEDGER_LINE_JOINER.join(kept) if kept else None


def repository_superseded(docs: Sequence[CanonicalDocument]) -> set[str]:
    """Every anchor that has a successor ANYWHERE in `docs` — the ledger line's dead set."""
    return set(superseded_index({doc.path: doc.body for doc in docs}))


def document_updated(
    doc: CanonicalDocument, updated: Mapping[str, str] | None = None
) -> str | None:
    """The last-updated date for one document, or None when nothing knows it.

    `updated` is the caller's path→date map (a git adapter has this for free); a frontmatter
    `updated` field is the fallback. Absent → the field is simply not rendered. A date is
    never inferred: a made-up recency reads as evidence and is worse than silence.
    """
    if updated is not None:
        value = str(updated.get(doc.path) or "").strip()
        if value:
            return value
    value = str((doc.frontmatter or {}).get("updated") or "").strip()
    return value or None


def family_blurbs(packs: Sequence[object]) -> dict[str, str]:
    """{path_template: one-line blurb} read off pack STRUCTURE, not skill prose.

    A pack declares its filing slots (`extra_path_templates`) next to the paragraph that
    says what they collect (`extra_instructions`); the blurb is that paragraph's first
    non-empty line with markdown heading markers stripped, capped at `BLURB_CHARS`. A pack
    with several slots lends the same blurb to each — it is one statement about one addition
    to the schema.
    """
    blurbs: dict[str, str] = {}
    for pack in packs:
        templates = list(getattr(pack, "extra_path_templates", ()) or ())
        if not templates:
            continue
        blurb = _first_line(str(getattr(pack, "extra_instructions", "") or ""))
        if not blurb:
            continue
        for template in templates:
            blurbs.setdefault(template, blurb)
    return blurbs


def _first_line(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip()
        if line:
            return line if len(line) <= BLURB_CHARS else line[:BLURB_CHARS].rstrip() + "…"
    return ""


def family_of(path: str, templates: Sequence[str]) -> str | None:
    """The template owning `path`, or None. Uses the gate's own matcher, so "which family"
    here means exactly what path ownership means at write time."""
    for template in templates:
        if path_allowed(path, [template]):
            return template
    return None


# ----------------------------------------------------------------------- compile face


def render_outline(docs: Sequence[CanonicalDocument]) -> list[str]:
    """Existing canonical as the compile task's OUTLINE — one line per document.

    Same render the compile task has always emitted (same prompt keys, same sort, same
    fields) — path, frontmatter type, claim count, and the section headings that tell a
    writer where a new claim belongs — with ONE deliberate exception: a rollover volume's
    line states that it is a frozen archive of its active document and read-only, instead of
    presenting it as an editable peer. The outline is the compiler's working-set map, and it
    used to be the surface that taught the trap: a rolled-over subject showed up twice, and
    nothing on the volume's line said which of the two takes writes. The volume stays listed
    (a compiler must see the history it may read), identified the way the recall glance
    identifies one (`volume_origin`: the `archived_from` stamp, path shape as fallback).

    Lives here so the outline and the glance derive "what a document is" from one place.
    """
    if not docs:
        return [prompt("compile.task.outline_empty")]
    present = {doc.path for doc in docs}
    superseded = repository_superseded(docs)
    lines: list[str] = []
    for doc in sorted(docs, key=lambda d: d.path):
        origin = volume_origin(doc, present)
        if origin is not None:
            lines.append(
                prompt(
                    "compile.task.outline_entry_volume",
                    path=doc.path,
                    owner=origin,
                    claims=claim_count(doc),
                )
            )
            continue
        headings = section_headings(doc)
        doc_type = str((doc.frontmatter or {}).get("type") or "?")
        tail = (
            prompt("compile.task.outline_entry_tail", headings=" / ".join(headings))
            if headings
            else ""
        )
        lines.append(
            prompt(
                "compile.task.outline_entry",
                path=doc.path,
                doc_type=doc_type,
                claims=claim_count(doc),
                tail=tail,
            )
        )
        # One level below the title: the document's own definition of its subject, when it
        # has an overview. A compiler deciding WHERE TO WRITE has to tell two similarly-named
        # pages apart, and the path plus a claim count cannot do it.
        definition = document_definition(doc)
        if definition:
            lines.append(
                prompt("compile.task.outline_entry_definition", definition=definition)
            )
        else:
            # No definition: the page's own ledger stands in for one. Labelled apart from a
            # definition, because "someone stated what this is" and "this is what the page
            # happens to hold" are different facts about the page.
            ledger = document_ledger_line(doc, superseded)
            if ledger:
                lines.append(prompt("compile.task.outline_entry_ledger", ledger=ledger))
        # An enabled component may add ONE line under a document of its family — what it
        # indexes about the subject (an identity, an alias) — so "does this subject already
        # exist" is answered by the outline rather than by the model's memory. With no
        # component registered the outline is byte-identical to before the seam existed.
        for component in registered_components():
            extra = component.outline_tail(doc)
            if extra:
                lines.append(prompt("compile.task.outline_entry_component", tail=extra))
    return lines


# ------------------------------------------------------------------------ recall face


def volume_origin(doc: CanonicalDocument, present: Sequence[str] | set[str]) -> str | None:
    """The active document `doc` is a rollover volume OF, or None.

    Two agreeing signals, because a volume is identified by both its layout and its stamp: the
    volume lives in its document's history directory (`<document>/aNN.md`) and carries an
    `archived_from` frontmatter naming it. The frontmatter is authoritative — it survives a
    move — and the directory is the fallback for a volume whose stamp is missing. Either way the
    origin must actually EXIST: an orphaned volume keeps being listed on its own rather than
    being folded into a document that is gone, which would make its claims unreachable here.
    """
    origin = archived_from(doc) or None
    if origin is None:
        directory, _, filename = doc.path.rpartition("/")
        if directory and _VOLUME_FILE_RE.match(filename) is not None:
            origin = f"{directory}.md"
    return origin if origin in set(present) else None


def archive_volume_counts(docs: Sequence[CanonicalDocument]) -> dict[str, int]:
    """{active document path: how many frozen archive volumes it has}."""
    present = {doc.path for doc in docs}
    counts: dict[str, int] = {}
    for doc in docs:
        origin = volume_origin(doc, present)
        if origin is not None:
            counts[origin] = counts.get(origin, 0) + 1
    return counts


def glance_entry(
    doc: CanonicalDocument,
    updated: Mapping[str, str] | None = None,
    *,
    archived_volumes: int = 0,
    superseded: Iterable[str] = (),
) -> str:
    """One document's glance line: path, title, claim count, updated-when, archive count —
    plus, on a second line, its overview definition when the document has one.

    `archived_volumes` is the ROLLOVER collapse: a document that has been rolled over states
    how much frozen history stands behind it instead of the glance listing each volume as a
    peer. Listing them would let one long-lived subject crowd out every other family — the
    exact degradation rollover exists to fix — while the count plus the active document's own
    volume links keep the archive one hop away.
    """
    when = document_updated(doc, updated)
    tail = prompt("recall.glance.entry_tail_updated", updated=when) if when else ""
    if archived_volumes:
        tail += prompt("recall.glance.entry_tail_archived", count=archived_volumes)
    line = prompt(
        "recall.glance.entry",
        path=doc.path,
        title=document_title(doc),
        claims=claim_count(doc),
        tail=tail,
    )
    # The same one level below the title the compile outline shows. An answerer deciding WHAT
    # TO READ needs it for the same reason the compiler does, and it costs one line.
    definition = document_definition(doc)
    if definition:
        line += "\n" + prompt("recall.glance.entry_definition", definition=definition)
    else:
        ledger = document_ledger_line(doc, superseded)
        if ledger:
            line += "\n" + prompt("recall.glance.entry_ledger", ledger=ledger)
    return line


def render_canonical_glance(
    docs: Sequence[CanonicalDocument],
    skill: object | None = None,
    *,
    packs: Sequence[object] = (),
    templates: Sequence[str] | None = None,
    updated: Mapping[str, str] | None = None,
    budget: int = GLANCE_BUDGET_CHARS,
    top_k: int = FAMILY_TOP_K,
) -> str:
    """The knowledge base at a glance: families, their blurbs, their documents.

    `skill` supplies the declared families (`path_templates`); `templates` overrides that for
    a caller holding the templates without a SkillVersion. `packs` supply the family blurbs.
    With no families declared at all the documents render as one flat list — the library still
    has a shape, it just has no declared layout to group by.

    Deterministic: families in declaration order, documents sorted by path, per-family
    truncation before whole-render truncation. The same (docs, skill, packs) renders the same
    bytes, which is what lets the glance sit in a byte-stable prompt segment.
    """
    if templates is None:
        templates = list(getattr(skill, "path_templates", ()) or ())
    else:
        templates = list(templates)
    blurbs = family_blurbs(packs)
    ordered = sorted(docs, key=lambda d: d.path)

    lines: list[str] = [prompt("recall.glance.header"), prompt("recall.glance.note")]
    if not ordered:
        lines.append(prompt("recall.glance.empty"))

    # Rollover collapse: frozen archive volumes are counted on their active document's line
    # instead of being listed as documents of their own (see `glance_entry`). They do not
    # consume the glance budget either — one long-lived subject's history must not be able to
    # crowd out another family's documents.
    present = {doc.path for doc in ordered}
    archived = archive_volume_counts(ordered)
    # Computed over EVERY document, volumes included, and before they are dropped: an active
    # page routinely supersedes a claim that now lives in a frozen volume, so "which claims
    # still hold" is a repository-level fact (compile/supersession.py).
    superseded = repository_superseded(ordered)
    ordered = [doc for doc in ordered if volume_origin(doc, present) is None]

    grouped: dict[str, list[CanonicalDocument]] = {t: [] for t in templates}
    unfiled: list[CanonicalDocument] = []
    for doc in ordered:
        owner = family_of(doc.path, templates)
        if owner is None:
            unfiled.append(doc)
        else:
            grouped[owner].append(doc)

    body: list[str] = []
    for template in templates:
        body.append("")
        body.append(prompt("recall.glance.family_heading", template=template))
        blurb = blurbs.get(template)
        if blurb:
            body.append(prompt("recall.glance.family_blurb", blurb=blurb))
        members = grouped[template]
        if not members:
            body.append(prompt("recall.glance.family_empty"))
            continue
        for doc in members[:top_k]:
            body.append(
                glance_entry(
                    doc,
                    updated,
                    archived_volumes=archived.get(doc.path, 0),
                    superseded=superseded,
                )
            )
        if len(members) > top_k:
            body.append(
                prompt("recall.glance.family_more", count=len(members) - top_k)
            )

    if unfiled:
        body.append("")
        body.append(
            prompt("recall.glance.unfiled_heading")
            if templates
            else prompt("recall.glance.flat_heading")
        )
        for doc in unfiled[:top_k]:
            body.append(
                glance_entry(
                    doc,
                    updated,
                    archived_volumes=archived.get(doc.path, 0),
                    superseded=superseded,
                )
            )
        if len(unfiled) > top_k:
            body.append(prompt("recall.glance.family_more", count=len(unfiled) - top_k))

    # Whole-render budget, enforced on line boundaries: a glance cut mid-path would name a
    # document the reader cannot open, which is worse than saying the list was cut short.
    kept: list[str] = []
    used = sum(len(line) + 1 for line in lines)
    dropped = 0
    for line in body:
        if used + len(line) + 1 > budget:
            dropped += 1
            continue
        kept.append(line)
        used += len(line) + 1
    lines.extend(kept)
    if dropped:
        lines.append(prompt("recall.glance.truncated", count=dropped))
    return "\n".join(lines)


__all__ = [
    "BLURB_CHARS",
    "DEFINITION_LINE_CHARS",
    "FAMILY_TOP_K",
    "GLANCE_BUDGET_CHARS",
    "LEDGER_LINE_JOINER",
    "archive_volume_counts",
    "claim_count",
    "claim_display_text",
    "document_definition",
    "document_ledger_line",
    "document_title",
    "document_updated",
    "family_blurbs",
    "family_of",
    "glance_entry",
    "markdown_display_text",
    "render_canonical_glance",
    "render_outline",
    "repository_superseded",
    "section_headings",
    "volume_origin",
]
