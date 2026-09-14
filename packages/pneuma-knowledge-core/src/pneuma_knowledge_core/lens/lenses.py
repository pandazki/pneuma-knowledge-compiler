"""The lenses (docs/design/structure-lens.md §4) — every predicate, stated once.

Every lens here is mechanical and model-free: a predicate over paths, titles, links, claim
text and counts. A threshold is a module-level named constant, so the number a finding rests
on is readable in one place and is never repeated in a console, a route or a prompt.

The three levels and their actors come from `model.ACTOR_OF_LEVEL`: a `shape` fault is the
mechanism's (the write face now refuses it and the existing instance wants a repair), a
`drift` finding is the Steward's (one ordinary round on that page fixes it), a `principle`
finding is the Owner's (no single page fixes a layout).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..canonical_glance import document_title
from ..compile.anchor_ops import (
    MAX_ESCAPED_NEWLINES,
    MAX_LINE_CHARS,
    anchored_blocks,
    block_text,
    unanchored_blocks,
)
from ..compile.documents import OVERVIEW_SLOTS, parse_overview, strip_overview
from ..compile.overview import ANCHOR_REFERENCE_RE
from ..domain.archive import normalize_title
from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, HTML_COMMENT_RE
from ..prompts import prompt
from .families import (
    ROLE_CHILD,
    ROLE_CHRONOLOGY,
    ROLE_HUB,
    project_dir,
    role_of,
    subject_of,
    template_of,
)
from .links import Edge, in_degree, out_degree, subject_claims, subject_edges
from .model import ACTOR_OF_LEVEL, MAX_EVIDENCE, MAX_EVIDENCE_CHARS, Finding, Phrase

# ───────────────────────────────────────────────────────────────────── the lens ids

NAV_DEAD_END = "nav.dead_end"
NAV_ARRIVAL_BLIND = "nav.arrival_blind"
NAV_DEAD_LINK = "nav.dead_link"
NAV_HUB_INCOMPLETE = "nav.hub_incomplete"
NAV_CHRONOLOGY_UNLINKED = "nav.chronology_unlinked"
NAV_DECISION_UNLINKED = "nav.decision_unlinked"
NAV_MENTION_UNLINKED = "nav.mention_unlinked"
NAV_ISLAND = "nav.island"
ID_TITLE_DUPLICATE = "id.title_duplicate"
ID_TITLE_CHILD_COLLISION = "id.title_child_collision"
ID_TITLE_DEGENERATE = "id.title_degenerate"
ID_TITLE_SHARED_WITH_HUB = "id.title_shared_with_hub"
FORM_COLLAPSED_BODY = "form.collapsed_body"
FORM_STRAY_HEADING = "form.stray_heading"
FORM_UNANCHORED_CITATION = "form.unanchored_citation"
FORM_OVERVIEW_RESTATES = "form.overview_restates"
FORM_LEGACY_SECTIONS = "form.legacy_sections"
FORM_DEFINITION_EMPTY = "form.definition_empty"
FORM_UNORDERED_CHRONOLOGY = "form.unordered_chronology"
CONC_CATCH_ALL = "conc.catch_all"
BAL_FAMILY_HEAVY = "bal.family_heavy"
BAL_FAMILY_EMPTY = "bal.family_empty"
BAL_SESSION_SHAPED = "bal.session_shaped"
CORR_SINGLE_SOURCE = "corr.single_source"

#: Every lens, in the order the module runs them. Enumerable so a test can assert that the
#: prompt catalog carries an `impact` and an `action` for each — a lens with no sentence is
#: a number with no consequence, which §1 rules is not a finding.
LENS_IDS: tuple[str, ...] = (
    NAV_DEAD_END,
    NAV_ARRIVAL_BLIND,
    NAV_DEAD_LINK,
    NAV_HUB_INCOMPLETE,
    NAV_CHRONOLOGY_UNLINKED,
    NAV_DECISION_UNLINKED,
    NAV_MENTION_UNLINKED,
    NAV_ISLAND,
    ID_TITLE_DUPLICATE,
    ID_TITLE_CHILD_COLLISION,
    ID_TITLE_DEGENERATE,
    ID_TITLE_SHARED_WITH_HUB,
    FORM_COLLAPSED_BODY,
    FORM_STRAY_HEADING,
    FORM_UNANCHORED_CITATION,
    FORM_OVERVIEW_RESTATES,
    FORM_LEGACY_SECTIONS,
    FORM_DEFINITION_EMPTY,
    FORM_UNORDERED_CHRONOLOGY,
    CONC_CATCH_ALL,
    BAL_FAMILY_HEAVY,
    BAL_FAMILY_EMPTY,
    BAL_SESSION_SHAPED,
    CORR_SINGLE_SOURCE,
)

#: The level each lens reports at (§4's tables).
LENS_LEVEL: dict[str, str] = {
    NAV_DEAD_END: "drift",
    NAV_ARRIVAL_BLIND: "drift",
    NAV_DEAD_LINK: "shape",
    NAV_HUB_INCOMPLETE: "drift",
    NAV_CHRONOLOGY_UNLINKED: "drift",
    NAV_DECISION_UNLINKED: "drift",
    NAV_MENTION_UNLINKED: "drift",
    NAV_ISLAND: "principle",
    ID_TITLE_DUPLICATE: "principle",
    ID_TITLE_CHILD_COLLISION: "shape",
    ID_TITLE_DEGENERATE: "drift",
    ID_TITLE_SHARED_WITH_HUB: "drift",
    FORM_COLLAPSED_BODY: "shape",
    FORM_STRAY_HEADING: "shape",
    FORM_UNANCHORED_CITATION: "shape",
    FORM_OVERVIEW_RESTATES: "drift",
    FORM_LEGACY_SECTIONS: "drift",
    FORM_DEFINITION_EMPTY: "shape",
    FORM_UNORDERED_CHRONOLOGY: "drift",
    CONC_CATCH_ALL: "principle",
    BAL_FAMILY_HEAVY: "principle",
    BAL_FAMILY_EMPTY: "principle",
    BAL_SESSION_SHAPED: "drift",
    CORR_SINGLE_SOURCE: "drift",
}

#: The two lenses §4.1 keeps for the counts and the compare tab, and which say nothing about
#: WHICH link is owed. Each is ONE finding over the whole library rather than one per page
#: (`_reachability_finding`), and the set is declared here so a later face that puts findings
#: in front of a writer has one table to consult rather than a rule repeated in its own module.
COUNTED_NOT_ADVISED: frozenset[str] = frozenset({NAV_DEAD_END, NAV_ARRIVAL_BLIND})

# ─────────────────────────────────────────────────────────────────────── thresholds

#: `nav.chronology_unlinked`: how many dated sections make a page a chronology in fact.
CHRONOLOGY_MIN_DATED_SECTIONS = 3
#: `nav.mention_unlinked`: a title shorter than this is too common a string to be a mention.
MENTION_MIN_TITLE_CHARS = 4
#: …and how many times it has to be named before the missing link is a finding.
MENTION_MIN_COUNT = 3
#: `form.collapsed_body`: the two numbers the WRITE FACE refuses at, read from it rather than
#: restated — the lens lists the instances a library already holds of exactly the fault the
#: gate now refuses, so a second spelling of either number would make the two disagree.
LONG_LINE_CHARS = MAX_LINE_CHARS
ESCAPED_NEWLINE_MIN = MAX_ESCAPED_NEWLINES
#: `conc.catch_all`: the two ways one subject swallows a library.
CATCH_ALL_SHARE = 0.20
CATCH_ALL_EVEN_MULTIPLE = 3.0
CATCH_ALL_LEAD_MULTIPLE = 4.0
CATCH_ALL_MIN_SUBJECTS = 5
#: `bal.family_heavy`: claim share ÷ page share, and the floor under the claim share.
FAMILY_HEAVY_RATIO = 2.0
FAMILY_HEAVY_SHARE = 0.20
#: `bal.session_shaped`: the share of a subject's claims that have to look like session
#: narration, and the floor under how many claims it takes to have a shape at all. The floor
#: is the lens's own (§4.4 states the share): a page holding two dated claims is a page that
#: was started on a Tuesday, not a log of sessions.
SESSION_SHAPED_SHARE = 0.60
SESSION_SHAPED_MIN_CLAIMS = 5
#: `corr.single_source`: how many claims a subject carries before resting all of them on one
#: source is a finding.
SINGLE_SOURCE_MIN_CLAIMS = 8

#: The signature `bal.session_shaped` counts: an optional bracketed label, then a date, then
#: the comma that starts the narration. Given verbatim by the design.
SESSION_DATE_PREFIX_RE = re.compile(r"^\s*(【[^】]*】)?\s*\d{4}-\d{2}-\d{2}[，,]")

#: A dated chronology section: `## 2026-01-02 …`.
DATED_SECTION_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")

#: Titles that name a family role instead of a subject. Compared under `normalize_title`,
#: so case, spacing and punctuation cannot dodge the table.
DEGENERATE_TITLE_WORDS: tuple[str, ...] = (
    "overview",
    "evolution",
    "features",
    "feature",
    "decisions",
    "decision",
    "people",
    "topics",
    "概览",
    "总览",
    "综述",
    "演进",
    "项目演进",
    "演进历程",
    "演化",
    "特性",
    "功能",
    "决策",
    "决定",
    "人物",
    "主题",
)

#: The four slot names a page may still carry as `## ` sections below an overview head —
#: the pre-region spelling of the same four things.
LEGACY_SECTION_NAMES: tuple[str, ...] = OVERVIEW_SLOTS


# ───────────────────────────────────────────────────────────── the view every lens reads


@dataclass(frozen=True)
class LibraryView:
    """One reading of the library, computed once and handed to every lens.

    `documents` is what the lens JUDGES — live, record-free, volumes included. `known_paths`
    is what it RESOLVES links against and is deliberately wider: it holds the archived
    documents and the archive records too, so a link to a subject the Owner retired is not
    reported as a dead link. The archive is out of the counts, not out of the map.
    """

    documents: Mapping[str, object]
    known_paths: frozenset[str]
    path_templates: tuple[str, ...]
    subjects: tuple[str, ...]
    claims: Mapping[str, int]
    titles: Mapping[str, str]
    edges: tuple[Edge, ...]
    in_degree: Mapping[str, int] = field(default_factory=dict)
    out_degree: Mapping[str, int] = field(default_factory=dict)

    @property
    def total_claims(self) -> int:
        return sum(self.claims.values())

    def body(self, path: str) -> str:
        doc = self.documents.get(path)
        return str(getattr(doc, "body", "") or "") if doc is not None else ""


def build_view(
    documents: Mapping[str, object],
    path_templates: Sequence[str],
    *,
    known_paths: frozenset[str] | None = None,
) -> LibraryView:
    """Derive the shared view from the documents the lens judges."""
    present = set(documents)
    edges = tuple(subject_edges(documents))
    claims = subject_claims(documents)
    subjects = tuple(
        sorted(path for path in present if subject_of(path, present) == path)
    )
    titles = {
        subject: document_title(documents[subject])
        for subject in subjects
        if subject in documents
    }
    return LibraryView(
        documents=dict(documents),
        known_paths=frozenset(known_paths if known_paths is not None else present),
        path_templates=tuple(str(t) for t in path_templates),
        subjects=subjects,
        claims=claims,
        titles=titles,
        edges=edges,
        in_degree=in_degree(edges),
        out_degree=out_degree(edges),
    )


# ─────────────────────────────────────────────────────────────── building one finding


def evidence_hash(
    evidence: Sequence[str],
    targets: Sequence[str],
    fields: Mapping[str, object] | None = None,
) -> str:
    """The evidence half of a finding key: sha256 over what the finding SHOWS and what it
    COUNTS.

    The key has to be STABLE for the same observation and DIFFERENT once the observation
    changes — that is what makes a decision about this finding and not about whatever the
    page became later (§9's kept record). `evidence` alone cannot carry that any more: §3
    now admits only verbatim strings there, so the numbers that distinguish one instance of
    a lens from the next — 36 arrival-blind subjects rather than 12, a body line of 813
    characters rather than 4 000 — live in the `impact`/`action` fields. They are hashed
    here for exactly that reason: a changed count is a changed observation, whichever half
    of the finding it is spoken in.

    The separator is a byte no value can contain, and the field pairs are sorted, so the
    hash is a function of the observation and not of dict ordering.
    """
    digest = hashlib.sha256()
    parts = [*evidence, "\x00targets\x00", *targets, "\x00fields\x00"]
    for name in sorted(fields or {}):
        parts.extend((name, (fields or {})[name]))
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:8]


def finding_key(
    lens: str,
    scope: str,
    evidence: Sequence[str],
    targets: Sequence[str],
    fields: Mapping[str, object] | None = None,
) -> str:
    """`"<lens>:<path or family>:<evidence hash>"` — §3's stable id."""
    return f"{lens}:{scope}:{evidence_hash(evidence, targets, fields)}"


def _clip(value: object) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= MAX_EVIDENCE_CHARS else text[:MAX_EVIDENCE_CHARS]


def make_finding(
    lens: str,
    *,
    scope: str,
    paths: Sequence[str] = (),
    targets: Sequence[str] = (),
    evidence: Sequence[object] = (),
    fields: Mapping[str, object] | None = None,
    weight: float = 0.0,
) -> Finding:
    """One finding, with its key, its level, its actor and its two catalog sentences.

    `fields` is ONE dict feeding both the impact and the action template: two dicts for one
    observation would be two places for the same number to be wrong, and `prompt()`
    substitutes only the placeholders a template names, so each sentence takes the subset it
    declares and ignores the rest.

    `evidence` is verbatim library text and nothing else (§3): a path, a title, a heading, a
    date, an href, a source id. A count or a share is not evidence — it is a thing the
    finding SAYS, so it belongs in `fields` and is spoken by the sentence. A lens with
    nothing verbatim to show therefore hands in no evidence at all, which is an honest empty
    list rather than a row of bare numbers nobody can check against the library.
    """
    level = LENS_LEVEL[lens]
    clipped = tuple(_clip(item) for item in evidence)[:MAX_EVIDENCE]
    ordered_targets = tuple(targets)
    values = dict(fields or {})
    return Finding(
        key=finding_key(lens, scope, clipped, ordered_targets, values),
        lens=lens,
        level=level,  # type: ignore[arg-type]
        actor=ACTOR_OF_LEVEL[level],  # type: ignore[arg-type]
        paths=tuple(paths),
        targets=ordered_targets,
        evidence=clipped,
        impact=Phrase(f"lens.{lens}.impact", values),
        action=Phrase(f"lens.{lens}.action", values),
        weight=round(max(0.0, min(1.0, weight)), 4),
    )


def _share(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


def _pct(value: float) -> str:
    """A share as a percentage string — the one rendering, so a console and a terminal
    cannot disagree about what 0.2137 is called."""
    return f"{round(value * 100)}%"


# ─────────────────────────────────────────────────────────────── mechanical derivations


def claim_blocks(body: str) -> list[str]:
    """The anchored claim blocks of a body's LEDGER (the overview is not claims)."""
    return anchored_blocks(strip_overview(body))


def claim_words(block: str) -> str:
    """What a claim SAYS: its text with the system's markers and its citations removed."""
    text = block_text(block)
    text = CANONICAL_CITATION_MARKER_RE.sub("", text)
    return HTML_COMMENT_RE.sub("", text).strip()


def citation_sources(block: str) -> list[str]:
    """The distinct source ids one block cites, in first-seen order."""
    out: list[str] = []
    for match in CANONICAL_CITATION_MARKER_RE.finditer(block):
        sid = match.group("sid")
        if sid not in out:
            out.append(sid)
    return out


def dated_sections(body: str) -> list[tuple[int, str]]:
    """`(line number, date)` for every `## YYYY-MM-DD` section, in document order."""
    out: list[tuple[int, str]] = []
    for index, line in enumerate(body.split("\n"), start=1):
        match = DATED_SECTION_RE.match(line)
        if match is not None:
            out.append((index, match.group(1)))
    return out


def stray_headings(body: str) -> list[tuple[int, str]]:
    """`(line number, heading text)` for every `# ` line that is not the body's first
    non-empty line — the instances of the fault §6 now refuses at the write."""
    out: list[tuple[int, str]] = []
    first_seen = False
    for index, line in enumerate(body.split("\n"), start=1):
        if not line.strip():
            continue
        if line.startswith("# "):
            if first_seen:
                out.append((index, line[2:].strip()))
        first_seen = True
    return out


def escaped_newline_count(text: str) -> int:
    """How many literal two-character `\\n` sequences the text carries."""
    return text.count("\\n")


def longest_line(text: str) -> int:
    return max((len(line) for line in text.split("\n")), default=0)


# ───────────────────────────────────────────────────────────────────── 4.1 navigability


#: The scope a library-wide finding's key is built under, in place of a path. The two
#: reachability lenses are ONE finding each (§4.1): on their own they say nothing about which
#: link is owed, so a row per page is one number repeated a hundred times — a real library
#: produced 124 dead-end rows and 99 arrival-blind ones, and not one of them told a reader
#: anything the count had not.
LIBRARY_SCOPE = "library"


def _reachability_finding(view: LibraryView, lens: str, affected: list[str]) -> list[Finding]:
    """One finding naming every subject the reachability predicate caught, or none."""
    if not affected:
        return []
    count = len(affected)
    share = _share(count, len(view.subjects))
    return [
        make_finding(
            lens,
            scope=LIBRARY_SCOPE,
            paths=tuple(sorted(affected)),
            # No evidence: `paths` already names every subject verbatim, and the count and
            # the share are what the finding SAYS rather than what it shows (§3).
            fields={"count": count, "share": _pct(share)},
            weight=share,
        )
    ]


def lens_dead_end(view: LibraryView) -> list[Finding]:
    return _reachability_finding(
        view,
        NAV_DEAD_END,
        [s for s in view.subjects if not view.out_degree.get(s, 0)],
    )


def lens_arrival_blind(view: LibraryView) -> list[Finding]:
    return _reachability_finding(
        view,
        NAV_ARRIVAL_BLIND,
        [s for s in view.subjects if not view.in_degree.get(s, 0)],
    )


def lens_dead_link(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for edge in view.edges:
        if edge.target in view.known_paths:
            continue
        findings.append(
            make_finding(
                NAV_DEAD_LINK,
                scope=edge.subject,
                paths=(edge.subject,),
                targets=(edge.target,),
                evidence=(edge.href,),
                fields={
                    "path": edge.source_path,
                    "title": view.titles.get(edge.subject, ""),
                    "href": edge.href,
                    "target": edge.target,
                },
                weight=_share(1, max(len(view.edges), 1)),
            )
        )
    return findings


def _subtree_pages(view: LibraryView, hub: str) -> list[str]:
    """Every other subject under the hub's project directory."""
    directory = project_dir(hub, view.path_templates)
    if not directory:
        return []
    return [
        subject
        for subject in view.subjects
        if subject != hub and subject.startswith(directory + "/")
    ]


def lens_hub_incomplete(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    outgoing: dict[str, set[str]] = {}
    for edge in view.edges:
        outgoing.setdefault(edge.subject, set()).add(edge.target)
    for subject in view.subjects:
        if role_of(subject, view.path_templates) != ROLE_HUB:
            continue
        members = _subtree_pages(view, subject)
        if not members:
            continue
        missing = sorted(set(members) - outgoing.get(subject, set()))
        if not missing:
            continue
        findings.append(
            make_finding(
                NAV_HUB_INCOMPLETE,
                scope=subject,
                paths=(subject,),
                targets=tuple(missing),
                evidence=tuple(missing),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "targets": ", ".join(missing),
                    "count": len(missing),
                },
                weight=_share(len(missing), len(view.subjects)),
            )
        )
    return findings


def lens_chronology_unlinked(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    outgoing: dict[str, set[str]] = {}
    for edge in view.edges:
        outgoing.setdefault(edge.subject, set()).add(edge.target)
    for subject in view.subjects:
        if role_of(subject, view.path_templates) != ROLE_CHRONOLOGY:
            continue
        sections = dated_sections(view.body(subject))
        if len(sections) < CHRONOLOGY_MIN_DATED_SECTIONS:
            continue
        directory = project_dir(subject, view.path_templates)
        children = [
            other
            for other in view.subjects
            if other != subject
            and directory
            and other.startswith(directory + "/")
            and role_of(other, view.path_templates) == ROLE_CHILD
        ]
        if not children:
            continue
        if outgoing.get(subject, set()) & set(children):
            continue
        findings.append(
            make_finding(
                NAV_CHRONOLOGY_UNLINKED,
                scope=subject,
                paths=(subject,),
                targets=tuple(sorted(children)),
                evidence=tuple(sorted(children)),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "count": len(children),
                    "targets": ", ".join(sorted(children)),
                },
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def lens_decision_unlinked(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        template = template_of(subject, view.path_templates)
        if template is None or "decisions" not in template.split("/"):
            continue
        if view.out_degree.get(subject, 0):
            continue
        findings.append(
            make_finding(
                NAV_DECISION_UNLINKED,
                scope=subject,
                paths=(subject,),
                fields={"path": subject, "title": view.titles.get(subject, "")},
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def lens_mention_unlinked(view: LibraryView) -> list[Finding]:
    """A subject named over and over in another page's claims, never linked.

    Counted under `normalize_title` on both sides: the title and the claim text are reduced
    to the letters, digits and CJK they are made of, so a name written with different
    spacing or punctuation is still the same name. It is an equality rule over a normalized
    string and deliberately not a similarity measure — the same limit `domain.archive`
    states for the shadowing rule it shares the function with.
    """
    findings: list[Finding] = []
    outgoing: dict[str, set[str]] = {}
    for edge in view.edges:
        outgoing.setdefault(edge.subject, set()).add(edge.target)
    named = [
        (subject, view.titles.get(subject, ""), normalize_title(view.titles.get(subject, "")))
        for subject in view.subjects
    ]
    named = [item for item in named if len(item[2]) >= MENTION_MIN_TITLE_CHARS]
    for subject in view.subjects:
        text = normalize_title(
            " ".join(claim_words(block) for block in claim_blocks(view.body(subject)))
        )
        if not text:
            continue
        linked = outgoing.get(subject, set())
        for target, title, key in named:
            if target == subject or target in linked:
                continue
            count = text.count(key)
            if count < MENTION_MIN_COUNT:
                continue
            findings.append(
                make_finding(
                    NAV_MENTION_UNLINKED,
                    scope=subject,
                    paths=(subject,),
                    targets=(target,),
                    evidence=(title,),
                    fields={
                        "path": subject,
                        "title": view.titles.get(subject, ""),
                        "mention": title,
                        "target": target,
                        "count": count,
                    },
                    weight=_share(1, len(view.subjects)),
                )
            )
    return findings


def lens_island(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    projects: dict[str, list[str]] = {}
    for subject in view.subjects:
        directory = project_dir(subject, view.path_templates)
        if directory:
            projects.setdefault(directory, []).append(subject)
    for directory in sorted(projects):
        members = set(projects[directory])
        if len(members) == len(view.subjects):
            # A library that is one project is not an island; it is the library.
            continue
        reaches_out = any(
            (edge.subject in members) != (edge.target in members) for edge in view.edges
        )
        if reaches_out:
            continue
        claims = sum(view.claims.get(member, 0) for member in members)
        findings.append(
            make_finding(
                NAV_ISLAND,
                scope=directory,
                paths=tuple(sorted(members)),
                fields={
                    "project": directory,
                    "count": len(members),
                    "claims": claims,
                },
                weight=_share(len(members), len(view.subjects)),
            )
        )
    return findings


# ─────────────────────────────────────────────────────────────────────── 4.2 identity


def _child_collisions(view: LibraryView) -> list[tuple[str, str]]:
    """`(page, deeper page)` pairs whose titles are one name, within one directory.

    "Its own subtree" is the directory the page sits in: a page at `projects/x/evolution.md`
    has `projects/x/features/*` and `projects/x/decisions/*` below it, which is exactly the
    shape §4.2 names — the evolution page that took a decision's name.
    """
    pairs: list[tuple[str, str]] = []
    for subject in view.subjects:
        key = normalize_title(view.titles.get(subject, ""))
        if not key:
            continue
        directory = subject.rsplit("/", 1)[0] if "/" in subject else ""
        if not directory:
            continue
        depth = subject.count("/")
        for other in view.subjects:
            if other == subject or not other.startswith(directory + "/"):
                continue
            if other.count("/") <= depth:
                continue
            if normalize_title(view.titles.get(other, "")) == key:
                pairs.append((subject, other))
    return pairs


def lens_title_child_collision(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject, child in _child_collisions(view):
        title = view.titles.get(subject, "")
        findings.append(
            make_finding(
                ID_TITLE_CHILD_COLLISION,
                scope=subject,
                paths=(subject,),
                targets=(child,),
                evidence=(child,),
                fields={"path": subject, "title": title, "target": child},
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def lens_title_duplicate(view: LibraryView) -> list[Finding]:
    """Two live subjects under one name — anywhere in the library.

    A pair another identity lens already reports is not repeated here. `title_child_collision`
    is the same observation seen inside one directory, where the level is `shape` because the
    mechanism has a repair; `title_shared_with_hub` is the same observation seen between a
    project's chronology and its hub, where the action names which of the two keeps the name.
    One observation is one finding: a real library reported the same four projects twice,
    once as duplicates and once as hub-shared titles, and the Owner read each of them twice.
    """
    collisions = {
        frozenset(pair)
        for pair in (*_child_collisions(view), *_hub_shared_pairs(view))
    }
    by_title: dict[str, list[str]] = {}
    for subject in view.subjects:
        key = normalize_title(view.titles.get(subject, ""))
        if key:
            by_title.setdefault(key, []).append(subject)
    findings: list[Finding] = []
    for key in sorted(by_title):
        members = sorted(by_title[key])
        if len(members) < 2:
            continue
        if len(members) == 2 and frozenset(members) in collisions:
            continue
        title = view.titles.get(members[0], "")
        findings.append(
            make_finding(
                ID_TITLE_DUPLICATE,
                scope=members[0],
                paths=tuple(members),
                targets=tuple(members[1:]),
                evidence=tuple(members),
                fields={
                    "title": title,
                    "paths": ", ".join(members),
                    "count": len(members),
                },
                weight=_share(len(members), len(view.subjects)),
            )
        )
    return findings


def lens_title_degenerate(view: LibraryView) -> list[Finding]:
    """A title that names a family role, or nothing at all.

    The project slug counts as degenerate only for a page that is NOT its project's hub: the
    hub IS the project, so its carrying the project's name is the right outcome and calling
    it a finding would make every well-named project one.
    """
    findings: list[Finding] = []
    words = {normalize_title(word) for word in DEGENERATE_TITLE_WORDS}
    for subject in view.subjects:
        title = view.titles.get(subject, "")
        key = normalize_title(title)
        role = role_of(subject, view.path_templates)
        degenerate = not key or key in words
        if not degenerate and role in (ROLE_CHRONOLOGY, ROLE_CHILD):
            directory = project_dir(subject, view.path_templates)
            slug = directory.rsplit("/", 1)[-1] if directory else ""
            degenerate = bool(slug) and key == normalize_title(slug)
        if not degenerate:
            continue
        findings.append(
            make_finding(
                ID_TITLE_DEGENERATE,
                scope=subject,
                paths=(subject,),
                evidence=(title or subject,),
                fields={"path": subject, "title": title},
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def _hub_shared_pairs(view: LibraryView) -> list[tuple[str, str]]:
    """`(chronology, its hub)` pairs whose titles are one name."""
    pairs: list[tuple[str, str]] = []
    for subject in view.subjects:
        if role_of(subject, view.path_templates) != ROLE_CHRONOLOGY:
            continue
        directory = project_dir(subject, view.path_templates)
        if not directory:
            continue
        hub = next(
            (
                other
                for other in view.subjects
                if other.startswith(directory + "/")
                and role_of(other, view.path_templates) == ROLE_HUB
            ),
            None,
        )
        if hub is None:
            continue
        key = normalize_title(view.titles.get(subject, ""))
        if key and key == normalize_title(view.titles.get(hub, "")):
            pairs.append((subject, hub))
    return pairs


def lens_title_shared_with_hub(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject, hub in _hub_shared_pairs(view):
        title = view.titles.get(subject, "")
        findings.append(
            make_finding(
                ID_TITLE_SHARED_WITH_HUB,
                scope=subject,
                paths=(subject,),
                targets=(hub,),
                evidence=(title,),
                fields={"path": subject, "title": title, "target": hub},
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


# ─────────────────────────────────────────────────────────────────────────── 4.3 form


def _file_findings(view: LibraryView, per_file) -> list[Finding]:
    """Run a per-FILE predicate over every document, attributing each finding to its subject.

    A closed volume is a file the Owner cannot repair and a subject cannot disown: the
    finding names the subject (§3's `paths`) and the file it is really in (the `path` field),
    so a reader is sent to the right line without the volume becoming a subject of its own.
    """
    findings: list[Finding] = []
    for path in sorted(view.documents):
        subject = subject_of(path, set(view.documents))
        findings.extend(per_file(path, subject, view.body(path)))
    return findings


def lens_collapsed_body(view: LibraryView) -> list[Finding]:
    def per_file(path: str, subject: str, body: str) -> list[Finding]:
        longest = longest_line(body)
        escaped = escaped_newline_count(body)
        real = body.count("\n")
        collapsed = longest >= LONG_LINE_CHARS or (
            escaped > ESCAPED_NEWLINE_MIN and real < escaped
        )
        if not collapsed:
            return []
        return [
            make_finding(
                FORM_COLLAPSED_BODY,
                scope=path,
                paths=(subject,),
                fields={
                    "path": path,
                    "title": view.titles.get(subject, ""),
                    "chars": longest,
                    "count": escaped,
                },
                weight=_share(1, len(view.subjects)),
            )
        ]

    return _file_findings(view, per_file)


def lens_stray_heading(view: LibraryView) -> list[Finding]:
    def per_file(path: str, subject: str, body: str) -> list[Finding]:
        out: list[Finding] = []
        for line, heading in stray_headings(body):
            out.append(
                make_finding(
                    FORM_STRAY_HEADING,
                    scope=path,
                    paths=(subject,),
                    evidence=(heading,),
                    fields={
                        "path": path,
                        "title": view.titles.get(subject, ""),
                        "line": line,
                        "heading": heading,
                    },
                    weight=_share(1, len(view.subjects)),
                )
            )
        return out

    return _file_findings(view, per_file)


def lens_unanchored_citation(view: LibraryView) -> list[Finding]:
    def per_file(path: str, subject: str, body: str) -> list[Finding]:
        orphans = [
            block
            for block in unanchored_blocks(strip_overview(body))
            if CANONICAL_CITATION_MARKER_RE.search(block)
        ]
        if not orphans:
            return []
        return [
            make_finding(
                FORM_UNANCHORED_CITATION,
                scope=path,
                paths=(subject,),
                fields={
                    "path": path,
                    "title": view.titles.get(subject, ""),
                    "count": len(orphans),
                },
                weight=_share(len(orphans), max(view.total_claims, 1)),
            )
        ]

    return _file_findings(view, per_file)


def _bare(text: str) -> str:
    """Prose with its citations, its anchor references and its whitespace runs removed."""
    stripped = CANONICAL_CITATION_MARKER_RE.sub("", text)
    stripped = ANCHOR_REFERENCE_RE.sub("", stripped)
    stripped = HTML_COMMENT_RE.sub("", stripped)
    return " ".join(stripped.split())


def lens_overview_restates(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        body = view.body(subject)
        overview, _ = parse_overview(body)
        if overview is None:
            continue
        ledger = {_bare(claim_words(block)) for block in claim_blocks(body)}
        ledger.discard("")
        for slot in OVERVIEW_SLOTS:
            if slot == "connections":
                continue
            text = _bare(str(getattr(overview, slot, "") or ""))
            if not text or text not in ledger:
                continue
            findings.append(
                make_finding(
                    FORM_OVERVIEW_RESTATES,
                    scope=subject,
                    paths=(subject,),
                    evidence=(slot,),
                    fields={
                        "path": subject,
                        "title": view.titles.get(subject, ""),
                        "slot": slot,
                    },
                    weight=_share(1, len(view.subjects)),
                )
            )
    return findings


def _legacy_section_names() -> set[str]:
    """The four slot names, plus whatever the active language pack renders them as — so a
    Chinese library's `## 定义` section is the same finding an English one's `## Definition`
    is. Resolved through the catalog, which is where the rendered spelling lives."""
    names = {normalize_title(name) for name in LEGACY_SECTION_NAMES}
    for slot in LEGACY_SECTION_NAMES:
        names.add(normalize_title(prompt(f"overview.heading.{slot}")))
    names.discard("")
    return names


def lens_legacy_sections(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    names = _legacy_section_names()
    for subject in view.subjects:
        body = view.body(subject)
        overview, ledger = parse_overview(body)
        if overview is None:
            continue
        sections = [
            line[3:].strip()
            for line in ledger.split("\n")
            if line.startswith("## ") and normalize_title(line[3:]) in names
        ]
        if not sections:
            continue
        findings.append(
            make_finding(
                FORM_LEGACY_SECTIONS,
                scope=subject,
                paths=(subject,),
                evidence=tuple(sections),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "sections": ", ".join(sections),
                    "count": len(sections),
                },
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def lens_definition_empty(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        overview, _ = parse_overview(view.body(subject))
        if overview is None:
            continue
        raw = str(overview.definition or "").strip()
        if not raw or _bare(raw):
            continue
        findings.append(
            make_finding(
                FORM_DEFINITION_EMPTY,
                scope=subject,
                paths=(subject,),
                evidence=(raw,),
                fields={"path": subject, "title": view.titles.get(subject, "")},
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


def lens_unordered_chronology(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        if role_of(subject, view.path_templates) != ROLE_CHRONOLOGY:
            continue
        sections = dated_sections(view.body(subject))
        if len(sections) < 2:
            continue
        dates = [date for _, date in sections]
        inverted_pair = next(
            (
                (dates[index - 1], dates[index])
                for index in range(1, len(dates))
                if dates[index] < dates[index - 1]
            ),
            (),
        )
        inversion = " → ".join(inverted_pair)
        repeats = sorted({date for date in dates if dates.count(date) > 1})
        if not inversion and not repeats:
            continue
        findings.append(
            make_finding(
                FORM_UNORDERED_CHRONOLOGY,
                scope=subject,
                paths=(subject,),
                evidence=tuple(
                    item for item in (*inverted_pair, *repeats) if item
                ),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "first": inversion,
                    "repeats": ", ".join(repeats),
                    "count": len(sections),
                },
                weight=_share(1, len(view.subjects)),
            )
        )
    return findings


# ─────────────────────────────────────────────────────────── 4.4 concentration, balance


def lens_catch_all(view: LibraryView) -> list[Finding]:
    total = view.total_claims
    if not total or len(view.subjects) < 2:
        return []
    ranked = sorted(view.subjects, key=lambda s: (-view.claims.get(s, 0), s))
    even = total / len(view.subjects)
    findings: list[Finding] = []
    lead = ranked[0]
    lead_claims = view.claims.get(lead, 0)
    share = _share(lead_claims, total)
    second = view.claims.get(ranked[1], 0) if len(ranked) > 1 else 0
    swallows = share > CATCH_ALL_SHARE and lead_claims > CATCH_ALL_EVEN_MULTIPLE * even
    outruns = (
        len(view.subjects) >= CATCH_ALL_MIN_SUBJECTS
        and lead_claims > CATCH_ALL_LEAD_MULTIPLE * second
    )
    if not (swallows or outruns):
        return []
    ratio = round(lead_claims / even, 2) if even else 0.0
    findings.append(
        make_finding(
            CONC_CATCH_ALL,
            scope=lead,
            paths=(lead,),
            fields={
                "path": lead,
                "title": view.titles.get(lead, ""),
                "share": _pct(share),
                "ratio": ratio,
                "count": lead_claims,
            },
            weight=share,
        )
    )
    return findings


def family_rows(view: LibraryView) -> list[tuple[str, int, int, float]]:
    """`(template, pages, claims, claim share)` per declared family, in declaration order."""
    total = view.total_claims
    rows: list[tuple[str, int, int, float]] = []
    for template in view.path_templates:
        members = [
            subject
            for subject in view.subjects
            if template_of(subject, view.path_templates) == template
        ]
        claims = sum(view.claims.get(member, 0) for member in members)
        rows.append((template, len(members), claims, round(_share(claims, total), 4)))
    return rows


def lens_family_heavy(view: LibraryView) -> list[Finding]:
    total = view.total_claims
    subjects = len(view.subjects)
    if not total or not subjects:
        return []
    findings: list[Finding] = []
    for template, pages, claims, claim_share in family_rows(view):
        if not pages:
            continue
        page_share = _share(pages, subjects)
        if not page_share:
            continue
        ratio = claim_share / page_share
        if ratio < FAMILY_HEAVY_RATIO or claim_share <= FAMILY_HEAVY_SHARE:
            continue
        findings.append(
            make_finding(
                BAL_FAMILY_HEAVY,
                scope=template,
                paths=(),
                evidence=(template,),
                fields={
                    "family": template,
                    "share": _pct(claim_share),
                    "pages": _pct(page_share),
                    "count": pages,
                },
                weight=claim_share,
            )
        )
    return findings


def lens_family_empty(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    templates = view.path_templates
    if not templates:
        return []
    for template, pages, _claims, _claim_share in family_rows(view):
        if pages:
            continue
        findings.append(
            make_finding(
                BAL_FAMILY_EMPTY,
                scope=template,
                paths=(),
                evidence=(template,),
                fields={"family": template},
                weight=_share(1, len(templates)),
            )
        )
    return findings


def lens_session_shaped(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        blocks = claim_blocks(view.body(subject))
        for path in sorted(view.documents):
            if path != subject and subject_of(path, set(view.documents)) == subject:
                blocks.extend(claim_blocks(view.body(path)))
        if len(blocks) < SESSION_SHAPED_MIN_CLAIMS:
            continue
        shaped = [
            block
            for block in blocks
            if len(citation_sources(block)) == 1
            and SESSION_DATE_PREFIX_RE.match(claim_words(block))
        ]
        share = _share(len(shaped), len(blocks))
        if share < SESSION_SHAPED_SHARE:
            continue
        findings.append(
            make_finding(
                BAL_SESSION_SHAPED,
                scope=subject,
                paths=(subject,),
                evidence=tuple(
                    match.group(0).strip()
                    for match in (
                        SESSION_DATE_PREFIX_RE.match(claim_words(block)) for block in shaped
                    )
                    if match is not None
                ),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "share": _pct(share),
                    "count": len(shaped),
                },
                weight=_share(len(blocks), max(view.total_claims, 1)),
            )
        )
    return findings


# ──────────────────────────────────────────────────────────────────── 4.5 corroboration


def lens_single_source(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    present = set(view.documents)
    for subject in view.subjects:
        blocks = claim_blocks(view.body(subject))
        for path in sorted(view.documents):
            if path != subject and subject_of(path, present) == subject:
                blocks.extend(claim_blocks(view.body(path)))
        if len(blocks) < SINGLE_SOURCE_MIN_CLAIMS:
            continue
        sources: set[str] = set()
        for block in blocks:
            sources.update(citation_sources(block))
        if len(sources) != 1:
            continue
        source_id = next(iter(sources))
        findings.append(
            make_finding(
                CORR_SINGLE_SOURCE,
                scope=subject,
                paths=(subject,),
                evidence=(source_id,),
                fields={
                    "path": subject,
                    "title": view.titles.get(subject, ""),
                    "source_id": source_id,
                    "count": len(blocks),
                },
                weight=_share(len(blocks), max(view.total_claims, 1)),
            )
        )
    return findings


#: Every lens function, in `LENS_IDS` order. The report runs this table and nothing else, so
#: adding a lens is adding a row here plus its two catalog sentences.
LENSES: tuple = (
    lens_dead_end,
    lens_arrival_blind,
    lens_dead_link,
    lens_hub_incomplete,
    lens_chronology_unlinked,
    lens_decision_unlinked,
    lens_mention_unlinked,
    lens_island,
    lens_title_duplicate,
    lens_title_child_collision,
    lens_title_degenerate,
    lens_title_shared_with_hub,
    lens_collapsed_body,
    lens_stray_heading,
    lens_unanchored_citation,
    lens_overview_restates,
    lens_legacy_sections,
    lens_definition_empty,
    lens_unordered_chronology,
    lens_catch_all,
    lens_family_heavy,
    lens_family_empty,
    lens_session_shaped,
    lens_single_source,
)


def run_lenses(view: LibraryView) -> list[Finding]:
    """Every lens over one view, concatenated in table order (the report then orders §3.4)."""
    findings: list[Finding] = []
    for lens in LENSES:
        findings.extend(lens(view))
    return findings


__all__ = [
    "CATCH_ALL_EVEN_MULTIPLE",
    "CATCH_ALL_LEAD_MULTIPLE",
    "CATCH_ALL_MIN_SUBJECTS",
    "CATCH_ALL_SHARE",
    "CHRONOLOGY_MIN_DATED_SECTIONS",
    "COUNTED_NOT_ADVISED",
    "DEGENERATE_TITLE_WORDS",
    "ESCAPED_NEWLINE_MIN",
    "FAMILY_HEAVY_RATIO",
    "FAMILY_HEAVY_SHARE",
    "LENSES",
    "LENS_IDS",
    "LENS_LEVEL",
    "LIBRARY_SCOPE",
    "LONG_LINE_CHARS",
    "MENTION_MIN_COUNT",
    "MENTION_MIN_TITLE_CHARS",
    "SESSION_DATE_PREFIX_RE",
    "SESSION_SHAPED_MIN_CLAIMS",
    "SESSION_SHAPED_SHARE",
    "SINGLE_SOURCE_MIN_CLAIMS",
    "LibraryView",
    "build_view",
    "claim_blocks",
    "claim_words",
    "citation_sources",
    "dated_sections",
    "escaped_newline_count",
    "evidence_hash",
    "family_rows",
    "finding_key",
    "longest_line",
    "make_finding",
    "run_lenses",
    "stray_headings",
]
