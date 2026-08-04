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
  caller can supply one (git, or a frontmatter `updated` field). A model-maintained summary
  field is deliberately NOT introduced: it would rot silently, while a derived line is
  always as fresh as the document.

BUDGET
------
Bounded the way the outline is: documents are sorted, each family keeps its first `top_k`
and states how many it dropped, and the whole render stops at `budget` characters on a line
boundary with an explicit truncation notice. The cost is O(documents) and independent of
body size — nothing here reads a body except to count its anchors and find its headings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .compile.patch import _VOLUME_FILE_RE, path_allowed
from .compile.rollover import archived_from
from .domain.canonical import CanonicalDocument
from .domain.ids import extract_anchors
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
    """How many anchored claims the document carries — its development level."""
    return len(extract_anchors(doc.body))


def section_headings(doc: CanonicalDocument) -> list[str]:
    """The document's `## ` section headings, in order (the compile face's "what's inside")."""
    return [
        line[3:].strip()
        for line in doc.body.splitlines()
        if line.startswith("## ") and line[3:].strip()
    ]


def document_title(doc: CanonicalDocument) -> str:
    """The document's subject line: first `# ` heading → frontmatter `title` → filename stem.

    Derived rather than stored, so it cannot disagree with the document it names."""
    for line in doc.body.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    frontmatter = doc.frontmatter or {}
    for key in ("title", "slug"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            return value
    return doc.path.rsplit("/", 1)[-1].removesuffix(".md")


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
) -> str:
    """One document's glance line: path, title, claim count, updated-when, archive count.

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
    return prompt(
        "recall.glance.entry",
        path=doc.path,
        title=document_title(doc),
        claims=claim_count(doc),
        tail=tail,
    )


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
                glance_entry(doc, updated, archived_volumes=archived.get(doc.path, 0))
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
                glance_entry(doc, updated, archived_volumes=archived.get(doc.path, 0))
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
    "FAMILY_TOP_K",
    "GLANCE_BUDGET_CHARS",
    "archive_volume_counts",
    "claim_count",
    "document_title",
    "document_updated",
    "family_blurbs",
    "family_of",
    "glance_entry",
    "render_canonical_glance",
    "render_outline",
    "section_headings",
    "volume_origin",
]
