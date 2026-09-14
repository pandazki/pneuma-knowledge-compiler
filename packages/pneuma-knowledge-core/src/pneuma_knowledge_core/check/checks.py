"""Every check predicate (docs/design/structure-lens.md §3.1), stated once.

Each one is mechanical and model-free: a predicate over paths, titles, links, claim text and
counts, producing a finding with the page it is about, verbatim evidence, what it costs and
what repairs it. A threshold is a module-level named constant, so the number a finding rests
on is readable in one place and is never repeated in a console, a route or a prompt.

Two kinds, and the split is the design's ruling that a finding belongs to the lowest tier
that can see it. A JUDGEMENT item is the contract's expectation that no write can decide: the
page in front of the writer looks right, and only the whole library shows the link that is
owed. A LEGACY item is an instance of a tier-one fault on a page written before the hook
existed — the write face refuses new ones, so what the check lists is a closed backlog, and
every one of them names the verb that repairs it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from ..compile.anchor_ops import (
    MAX_ESCAPED_NEWLINES,
    MAX_LINE_CHARS,
    unanchored_blocks,
)
from ..compile.documents import OVERVIEW_SLOTS, parse_overview, strip_overview
from ..domain.archive import normalize_title
from ..domain.canonical import CANONICAL_CITATION_MARKER_RE
from ..prompts import prompt
from ..shape import (
    ROLE_CHILD,
    ROLE_CHRONOLOGY,
    ROLE_HUB,
    is_degenerate_title,
    project_dir,
    role_of,
    shares_hub_title,
    subject_of,
    template_of,
)
from ..shape.phrase import Phrase, clip_evidence
from ..shape.text import (
    bare_prose,
    citation_sources,
    claim_blocks,
    claim_words,
    dated_sections,
    escaped_newline_count,
    longest_line,
    stray_headings,
)
from ..shape.view import LibraryView
from .model import (
    CHECK_KIND,
    CORR_SINGLE_SOURCE,
    FORM_COLLAPSED_BODY,
    FORM_DEFINITION_EMPTY,
    FORM_LEGACY_SECTIONS,
    FORM_OVERVIEW_RESTATES,
    FORM_STRAY_HEADING,
    FORM_UNANCHORED_CITATION,
    FORM_REPEATED_DATES,
    FORM_UNORDERED_CHRONOLOGY,
    ID_TITLE_CHILD_COLLISION,
    ID_TITLE_DEGENERATE,
    ID_TITLE_DUPLICATE,
    ID_TITLE_SHARED_WITH_HUB,
    ID_TITLE_SIBLING_COLLISION,
    NAV_CHRONOLOGY_UNLINKED,
    NAV_DEAD_LINK,
    NAV_DECISION_UNLINKED,
    NAV_HUB_INCOMPLETE,
    NAV_MENTION_UNLINKED,
    Finding,
)

# ─────────────────────────────────────────────────────────────────────── thresholds

#: `nav.chronology_unlinked`: how many dated sections make a page a chronology in fact.
CHRONOLOGY_MIN_DATED_SECTIONS = 3
#: `nav.mention_unlinked`: a title shorter than this is too common a string to be a mention.
MENTION_MIN_TITLE_CHARS = 4
#: …and how many times it has to be named before the missing link is a finding.
MENTION_MIN_COUNT = 3
#: `form.collapsed_body`: the two numbers the WRITE FACE refuses at, read from it rather than
#: restated — the check lists the instances a library already holds of exactly the fault the
#: write face now refuses, so a second spelling of either number would make the two disagree.
LONG_LINE_CHARS = MAX_LINE_CHARS
ESCAPED_NEWLINE_MIN = MAX_ESCAPED_NEWLINES
#: `corr.single_source`: how many claims a subject carries before resting all of them on one
#: source is a finding.
SINGLE_SOURCE_MIN_CLAIMS = 8

#: The four slot names a page may still carry as `## ` sections below an overview head — the
#: pre-region spelling of the same four things.
LEGACY_SECTION_NAMES: tuple[str, ...] = OVERVIEW_SLOTS


# ─────────────────────────────────────────────────────────────── building one finding


def evidence_hash(
    evidence: Sequence[str],
    targets: Sequence[str],
    fields: Mapping[str, object] | None = None,
) -> str:
    """The evidence half of a finding key: sha256 over what the finding SHOWS and COUNTS.

    The key has to be STABLE for the same observation and DIFFERENT once the observation
    changes — a repaired page is not the page the finding was about. `evidence` alone cannot
    carry that: §5.1 admits only verbatim strings there, so the numbers that distinguish one
    instance from the next live in the `impact`/`action` fields and are hashed here for
    exactly that reason.

    The separator is a byte no value can contain, and the field pairs are sorted, so the hash
    is a function of the observation and not of dict ordering.
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
    item: str,
    scope: str,
    evidence: Sequence[str],
    targets: Sequence[str],
    fields: Mapping[str, object] | None = None,
) -> str:
    """`"<id>:<path or scope>:<evidence hash>"` — §5.1's stable id."""
    return f"{item}:{scope}:{evidence_hash(evidence, targets, fields)}"


def make_finding(
    item: str,
    *,
    scope: str,
    paths: Sequence[str] = (),
    targets: Sequence[str] = (),
    evidence: Sequence[object] = (),
    fields: Mapping[str, object] | None = None,
) -> Finding:
    """One finding, with its key, its kind and its two catalog sentences.

    `fields` is ONE dict feeding both the impact and the action template: two dicts for one
    observation would be two places for the same number to be wrong, and `prompt()`
    substitutes only the placeholders a template names, so each sentence takes the subset it
    declares and ignores the rest.

    `evidence` is verbatim library text and nothing else (§5.1): a path, a title, a heading, a
    date, an href, a source id. A count or a share is not evidence — it is a thing the finding
    SAYS — so it belongs in `fields` and is spoken by the sentence. An item with nothing
    verbatim to show hands in no evidence at all, which is an honest empty list rather than a
    row of bare numbers nobody can check against the library.
    """
    clipped = clip_evidence(evidence)
    ordered_targets = tuple(targets)
    values = dict(fields or {})
    return Finding(
        key=finding_key(item, scope, clipped, ordered_targets, values),
        id=item,
        kind=CHECK_KIND[item],  # type: ignore[arg-type]
        paths=tuple(paths),
        targets=ordered_targets,
        evidence=clipped,
        impact=Phrase(f"check.{item}.impact", values),
        action=Phrase(f"check.{item}.action", values),
    )


def _outgoing(view: LibraryView) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for edge in view.edges:
        out.setdefault(edge.subject, set()).add(edge.target)
    return out


# ───────────────────────────────────────────────── judgement items: what is not linked


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


def check_hub_incomplete(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    outgoing = _outgoing(view)
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
            )
        )
    return findings


def check_chronology_unlinked(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    outgoing = _outgoing(view)
    for subject in view.subjects:
        if role_of(subject, view.path_templates) != ROLE_CHRONOLOGY:
            continue
        if len(dated_sections(view.body(subject))) < CHRONOLOGY_MIN_DATED_SECTIONS:
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
            )
        )
    return findings


def check_decision_unlinked(view: LibraryView) -> list[Finding]:
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
            )
        )
    return findings


def check_mention_unlinked(view: LibraryView) -> list[Finding]:
    """A subject named over and over in another page's claims, never linked.

    Counted under `normalize_title` on both sides: the title and the claim text are reduced to
    the letters, digits and CJK they are made of, so a name written with different spacing or
    punctuation is still the same name. It is an equality rule over a normalized string and
    deliberately not a similarity measure — the same limit `domain.archive` states for the
    shadowing rule it shares the function with.
    """
    findings: list[Finding] = []
    outgoing = _outgoing(view)
    named = [
        (
            subject,
            view.titles.get(subject, ""),
            normalize_title(view.titles.get(subject, "")),
        )
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
                )
            )
    return findings


def check_dead_link(view: LibraryView) -> list[Finding]:
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
            )
        )
    return findings


# ─────────────────────────────────────────────────── judgement items: identity, evidence


def check_title_duplicate(view: LibraryView) -> list[Finding]:
    """Two live subjects under one name, in DIFFERENT directories.

    Across directories no write can see the collision at all, which is exactly what makes it
    the check's (§3.1). The same name INSIDE one directory is a different observation with a
    different reader's problem — two files side by side under one name — and it has its own
    item, `id.title_sibling_collision`. A name standing in three places, twice in one
    directory, is honestly both: the sibling item is about that pair, this one about the name
    reaching across the library.
    """
    child = {frozenset(pair) for pair in _child_collisions(view)}
    by_title: dict[str, list[str]] = {}
    for subject in view.subjects:
        key = normalize_title(view.titles.get(subject, ""))
        if key:
            by_title.setdefault(key, []).append(subject)
    findings: list[Finding] = []
    for key in sorted(by_title):
        members = sorted(by_title[key])
        directories = {
            member.rsplit("/", 1)[0] if "/" in member else "" for member in members
        }
        if len(members) < 2 or len(directories) < 2:
            continue
        if len(members) == 2 and frozenset(members) in child:
            continue
        title = view.titles.get(members[0], "")
        findings.append(
            make_finding(
                ID_TITLE_DUPLICATE,
                scope=members[0],
                paths=tuple(members),
                evidence=(title,),
                fields={
                    "title": title,
                    "paths": ", ".join(members),
                    "count": len(members),
                },
            )
        )
    return findings


def _subject_claim_blocks(view: LibraryView, subject: str) -> list[str]:
    """Every claim block of a subject, its closed volumes folded in."""
    blocks: list[str] = []
    for path in view.files_of(subject):
        blocks.extend(claim_blocks(view.body(path)))
    return blocks


def check_single_source(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        blocks = _subject_claim_blocks(view, subject)
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


def check_legacy_sections(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    names = _legacy_section_names()
    for subject in view.subjects:
        overview, ledger = parse_overview(view.body(subject))
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
            )
        )
    return findings


# ───────────────────────────────────────── legacy items: the tier-one faults, as they stand


def _file_findings(view: LibraryView, per_file) -> list[Finding]:
    """Run a per-FILE predicate over every document, attributing each finding to its subject.

    A closed volume is a file the Owner cannot repair and a subject cannot disown: the finding
    names the subject (§5.1's `paths`) and the file it is really in (the `path` field), so a
    reader is sent to the right line without the volume becoming a subject of its own.
    """
    findings: list[Finding] = []
    present = set(view.documents)
    for path in sorted(view.documents):
        findings.extend(per_file(path, subject_of(path, present), view.body(path)))
    return findings


def check_stray_heading(view: LibraryView) -> list[Finding]:
    def per_file(path: str, subject: str, body: str) -> list[Finding]:
        return [
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
            )
            for line, heading in stray_headings(body)
        ]

    return _file_findings(view, per_file)


def check_collapsed_body(view: LibraryView) -> list[Finding]:
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
            )
        ]

    return _file_findings(view, per_file)


def check_title_degenerate(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        title = view.titles.get(subject, "")
        if not is_degenerate_title(subject, title, view.path_templates):
            continue
        findings.append(
            make_finding(
                ID_TITLE_DEGENERATE,
                scope=subject,
                paths=(subject,),
                evidence=(title or subject,),
                fields={"path": subject, "title": title},
            )
        )
    return findings


def _hub_shared_pairs(view: LibraryView) -> set[frozenset[str]]:
    """`{chronology, its hub}` for every project whose two pages answer to one name."""
    return {
        frozenset((subject, hub))
        for subject in view.subjects
        if (hub := shares_hub_title(subject, view.titles, view.path_templates))
    }


def check_title_shared_with_hub(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        hub = shares_hub_title(subject, view.titles, view.path_templates)
        if not hub:
            continue
        title = view.titles.get(subject, "")
        findings.append(
            make_finding(
                ID_TITLE_SHARED_WITH_HUB,
                scope=subject,
                paths=(subject,),
                targets=(hub,),
                evidence=(title,),
                fields={"path": subject, "title": title, "target": hub},
            )
        )
    return findings


def _child_collisions(view: LibraryView) -> list[tuple[str, str]]:
    """`(page, deeper page)` pairs whose titles are one name, within one subtree.

    "Its own subtree" is the directory the page sits in: a page at `projects/x/evolution.md`
    has `projects/x/features/*` and `projects/x/decisions/*` below it, which is exactly the
    shape §3.1 names — the evolution page that took a decision's name.
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


def check_title_child_collision(view: LibraryView) -> list[Finding]:
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
            )
        )
    return findings


def check_title_sibling_collision(view: LibraryView) -> list[Finding]:
    """Two live pages in ONE directory under one name — the legacy half of the gate's
    `title_sibling_collision`.

    The hook refuses a new one from now on, and it judges only the pages a round touched, so a
    collision two pages have carried since before the rule cannot reach a reader through the
    gate at all. A real 250-subject library held exactly that: two feature pages of one
    project, both called 『屏幕内容地形』, reported by nothing — `id.title_duplicate` is the
    cross-directory case and a child collision needs one page to sit below the other.

    One observation, one finding, across the four title items: a pair that is a project's
    chronology and its hub is `id.title_shared_with_hub`, which says which of the two keeps
    the name, so it is not repeated here.
    """
    hub_shared = _hub_shared_pairs(view)
    groups: dict[tuple[str, str], list[str]] = {}
    for subject in view.subjects:
        key = normalize_title(view.titles.get(subject, ""))
        if not key:
            continue
        directory = subject.rsplit("/", 1)[0] if "/" in subject else ""
        groups.setdefault((directory, key), []).append(subject)
    findings: list[Finding] = []
    for (_directory, _key), members in sorted(groups.items()):
        members = sorted(members)
        if len(members) < 2:
            continue
        if len(members) == 2 and frozenset(members) in hub_shared:
            continue
        title = view.titles.get(members[0], "")
        findings.append(
            make_finding(
                ID_TITLE_SIBLING_COLLISION,
                scope=members[0],
                paths=tuple(members),
                targets=tuple(members[1:]),
                evidence=(title,),
                fields={
                    "title": title,
                    "paths": ", ".join(members),
                    "count": len(members),
                },
            )
        )
    return findings


def check_unordered_chronology(view: LibraryView) -> list[Finding]:
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
        # TWO findings and not one, because they have two different repairs. An inversion is
        # what `reorder_chronology` exists for: whole sections move into ascending order and
        # no claim is touched. A repeated date is not — a page whose sections all run forward
        # and merely share a date is ALREADY sorted, so that verb changes nothing, and a
        # report that named it was telling a round to run a command that could not do what
        # the report asked. It did: three pages, three reported repairs, an empty commit.
        if inversion:
            findings.append(
                make_finding(
                    FORM_UNORDERED_CHRONOLOGY,
                    scope=subject,
                    paths=(subject,),
                    evidence=tuple(inverted_pair),
                    fields={
                        "path": subject,
                        "title": view.titles.get(subject, ""),
                        "first": inversion,
                        "count": len(sections),
                    },
                )
            )
        if repeats:
            findings.append(
                make_finding(
                    FORM_REPEATED_DATES,
                    scope=subject,
                    paths=(subject,),
                    evidence=tuple(repeats),
                    fields={
                        "path": subject,
                        "title": view.titles.get(subject, ""),
                        "repeats": ", ".join(repeats),
                        "count": len(repeats),
                    },
                )
            )
    return findings


def check_overview_restates(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        body = view.body(subject)
        overview, _ = parse_overview(body)
        if overview is None:
            continue
        ledger = {bare_prose(claim_words(block)) for block in claim_blocks(body)}
        ledger.discard("")
        for slot in OVERVIEW_SLOTS:
            if slot == "connections":
                continue
            text = bare_prose(str(getattr(overview, slot, "") or ""))
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
                )
            )
    return findings


def check_definition_empty(view: LibraryView) -> list[Finding]:
    findings: list[Finding] = []
    for subject in view.subjects:
        overview, _ = parse_overview(view.body(subject))
        if overview is None:
            continue
        raw = str(overview.definition or "").strip()
        if not raw or bare_prose(raw):
            continue
        findings.append(
            make_finding(
                FORM_DEFINITION_EMPTY,
                scope=subject,
                paths=(subject,),
                evidence=(raw,),
                fields={"path": subject, "title": view.titles.get(subject, "")},
            )
        )
    return findings


def check_unanchored_citation(view: LibraryView) -> list[Finding]:
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
            )
        ]

    return _file_findings(view, per_file)


#: Every check, in the order the module runs them (the report then orders §5.1). Adding an
#: item is adding a row here plus its two catalog sentences.
CHECKS: tuple = (
    check_stray_heading,
    check_collapsed_body,
    check_title_degenerate,
    check_title_shared_with_hub,
    check_title_child_collision,
    check_title_sibling_collision,
    check_unordered_chronology,
    check_overview_restates,
    check_definition_empty,
    check_unanchored_citation,
    check_hub_incomplete,
    check_chronology_unlinked,
    check_decision_unlinked,
    check_mention_unlinked,
    check_dead_link,
    check_title_duplicate,
    check_single_source,
    check_legacy_sections,
)


def run_checks(view: LibraryView) -> list[Finding]:
    """Every check over one view, concatenated in table order."""
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(view))
    return findings


__all__ = [
    "CHECKS",
    "CHRONOLOGY_MIN_DATED_SECTIONS",
    "ESCAPED_NEWLINE_MIN",
    "LEGACY_SECTION_NAMES",
    "LONG_LINE_CHARS",
    "MENTION_MIN_COUNT",
    "MENTION_MIN_TITLE_CHARS",
    "SINGLE_SOURCE_MIN_CLAIMS",
    "evidence_hash",
    "finding_key",
    "make_finding",
    "run_checks",
]
