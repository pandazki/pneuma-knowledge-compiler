"""The six dimensions (docs/design/structure-lens.md §4.2) — every metric and every band.

What only the WHOLE shows: whether the library is walkable as a body, where knowledge piles
up, how much of it is a log of sessions rather than knowledge about subjects, whether it ever
corrects itself, whether the structure its accumulating knowledge implies exists yet, and
whether what it holds is what people ask it. No page shows any of this, which is why none of
it is a check item and none of it names a page to repair.

Every threshold is a named module constant, declared once here: the console does not repeat
them, a route does not restate them, and the number a band rests on is readable in one place.
Everything is mechanical and model-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ..compile.documents import parse_overview
from ..compile.overview import OVERVIEW_REQUIRED_AFTER_CLAIMS
from ..compile.rollover import VOLUME_COUNT_KEY
from ..compile.supersession import SUPERSEDES_MARK_RE
from ..shape import (
    ROLE_CHRONOLOGY,
    VOLUME_FILE_RE,
    project_dir,
    role_of,
    subject_of,
    template_of,
)
from ..shape.phrase import clip_evidence
from ..shape.text import (
    SESSION_DATE_PREFIX_RE,
    citation_sources,
    claim_blocks,
    claim_words,
    section_headings,
)
from ..shape.view import LibraryView

# ─────────────────────────────────────────────────────────────────────── thresholds

#: `walkability` (§4.2): the share of subjects that may be dead ends or arrival-blind before
#: the library stops being a body a reader can walk. Both shares are judged against the same
#: two numbers, because a hop that cannot be taken and a page nobody arrives at are the two
#: halves of one failure.
WALKABILITY_OPEN_SHARE = 0.15
WALKABILITY_THIN_SHARE = 0.40

#: `shape`: how large one subject's share of the claims may be, and how far a family's claim
#: share may run ahead of its page share before the weight is sitting in one kind of subject.
SHAPE_EVEN_LEAD_SHARE = 0.10
SHAPE_LEANING_LEAD_SHARE = 0.20
SHAPE_FAMILY_RATIO = 2.0
#: …and the guard that makes a SHARE mean concentration: how many times an even share the
#: lead subject must hold (`lead_over_even`, not `lead_ratio` — the first is the lead against
#: what every subject would hold if the claims were spread flat, the second is the lead
#: against the subject behind it, which is what §4.2 calls the lead ratio). A share alone says
#: nothing in a small library — a sixth subject holding a quarter of thirteen claims is a page
#: with one extra paragraph, not a catch-all — and past ten subjects the share threshold
#: implies this multiple anyway, so the guard only ever speaks where the share does not.
SHAPE_LEAD_OVER_EVEN = 2.0

#: `knowledge_vs_log`: the share of claims carrying the session signature, and what makes one
#: SUBJECT a log rather than a subject.
NARRATION_KNOWLEDGE_SHARE = 0.20
NARRATION_MIXED_SHARE = 0.50
LOG_SUBJECT_SHARE = 0.60
#: …with a floor under how many claims a subject needs to have a shape at all: a page holding
#: two dated claims is a page that was started on a Tuesday, not a log of sessions.
LOG_SUBJECT_MIN_CLAIMS = 5

#: `liveness`: supersessions per 100 claims, and the share of subjects nothing has touched in
#: `LIVENESS_UNTOUCHED_DAYS`. The second is read only when a caller supplies write dates.
LIVENESS_LIVING_PER_HUNDRED = 1.0
LIVENESS_STILL_PER_HUNDRED = 0.5
LIVENESS_LIVING_UNTOUCHED_SHARE = 0.50
LIVENESS_STILL_UNTOUCHED_SHARE = 0.80
LIVENESS_UNTOUCHED_DAYS = 180

#: `type_structure`: how large each misfiling proxy may be, as a share of its own base.
TYPE_ALIGNED_SHARE = 0.05
TYPE_STRAINED_SHARE = 0.20

#: `demand_supply`: the share of answers that cited nothing, and how far the most-asked
#: family's share of the asking may run ahead of its share of the claims.
DEMAND_GAP_SHARE = 0.10
DEMAND_FAMILY_RATIO = 2.0

#: The section headings a DECISION is written under. A page carrying these outside the
#: decisions family is decision knowledge filed as something else — the `type_structure`
#: proxy, and deliberately a small closed table in both shipped languages rather than a
#: similarity measure.
DECISION_SECTION_WORDS: frozenset[str] = frozenset(
    {
        "decision",
        "rationale",
        "scope",
        "implementation",
        "决策",
        "理由",
        "依据",
        "范围",
        "实施",
        "实现",
    }
)


@dataclass(frozen=True)
class Consultation:
    """One answering call, as the lens reads it (§4.2's `demand_supply`).

    The framework's own record of a consultation carries far more (the question, the lane, the
    visitor class, the ref it sampled); what a reading of the library's shape needs is three
    facts — which subjects were answered from, whether the answer cited anything at all, and
    when. The service maps its kept records onto this, so the lens stays pure core and never
    learns what a `ConsultationRecord` is.
    """

    paths: tuple[str, ...] = ()
    cited: bool = True
    at: str = ""


@dataclass(frozen=True)
class Observation:
    """One dimension, read: its band, its metrics, what it can show verbatim, and the fields
    its two sentences substitute."""

    id: str
    band: str
    metrics: dict[str, float | int | None] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    fields: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────── small arithmetic


def _share(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


def _pct(value: float | None) -> str:
    """A share as a percentage string — the one rendering, so a console and a terminal cannot
    disagree about what 0.2137 is called."""
    return f"{round((value or 0.0) * 100)}%"


def _rounded(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _by_weight(counts: Mapping[str, int]) -> list[str]:
    """The paths a proxy caught, the one carrying most of it first, ties by path.

    Evidence is bounded (five items), so which five it is has to be the five worth opening
    rather than the five that sorted first alphabetically.
    """
    return [path for path, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _components(view: LibraryView) -> list[set[str]]:
    """The connected components of the subject graph, read UNDIRECTED.

    A reader walks a link in the direction it points; a body of knowledge is connected when
    some path of links joins two subjects at all, whichever way each one runs. Both readings
    are useful and only one is the question "is this one library or several", which is what a
    component counts here.
    """
    neighbours: dict[str, set[str]] = {subject: set() for subject in view.subjects}
    for edge in view.edges:
        if edge.subject in neighbours and edge.target in neighbours:
            neighbours[edge.subject].add(edge.target)
            neighbours[edge.target].add(edge.subject)
    seen: set[str] = set()
    out: list[set[str]] = []
    for subject in view.subjects:
        if subject in seen:
            continue
        stack = [subject]
        group: set[str] = set()
        while stack:
            current = stack.pop()
            if current in group:
                continue
            group.add(current)
            stack.extend(neighbours.get(current, set()) - group)
        seen |= group
        out.append(group)
    return out


def _islands(view: LibraryView) -> list[str]:
    """Project directories no page outside reaches and that reach no page outside."""
    projects: dict[str, set[str]] = {}
    for subject in view.subjects:
        directory = project_dir(subject, view.path_templates)
        if directory:
            projects.setdefault(directory, set()).add(subject)
    out: list[str] = []
    for directory in sorted(projects):
        members = projects[directory]
        if len(members) == len(view.subjects):
            # A library that is one project is not an island; it is the library.
            continue
        crosses = any(
            (edge.subject in members) != (edge.target in members) for edge in view.edges
        )
        if not crosses:
            out.append(directory)
    return out


def _family_rows(view: LibraryView) -> list[tuple[str, int, int, float, float]]:
    """`(template, pages, claims, claim share, page share)` per declared family."""
    total = view.total_claims
    subjects = len(view.subjects)
    rows: list[tuple[str, int, int, float, float]] = []
    for template in view.path_templates:
        members = [
            subject
            for subject in view.subjects
            if template_of(subject, view.path_templates) == template
        ]
        claims = sum(view.claims.get(member, 0) for member in members)
        rows.append(
            (
                template,
                len(members),
                claims,
                _share(claims, total),
                _share(len(members), subjects),
            )
        )
    return rows


def _subject_blocks(view: LibraryView, subject: str) -> list[str]:
    blocks: list[str] = []
    for path in view.files_of(subject):
        blocks.extend(claim_blocks(view.body(path)))
    return blocks


def _is_narration(block: str) -> bool:
    """One claim carrying the session signature: a single source, and a dated opening."""
    return (
        len(citation_sources(block)) == 1
        and SESSION_DATE_PREFIX_RE.match(claim_words(block)) is not None
    )


# ────────────────────────────────────────────────────────────────────── 1. walkability


def read_walkability(view: LibraryView) -> Observation:
    subjects = len(view.subjects)
    dead_ends = [s for s in view.subjects if not view.out_degree.get(s, 0)]
    blind = [s for s in view.subjects if not view.in_degree.get(s, 0)]
    dead_share = _share(len(dead_ends), subjects)
    blind_share = _share(len(blind), subjects)
    components = _components(view)
    largest = max((len(group) for group in components), default=0)
    islands = _islands(view)
    if dead_share <= WALKABILITY_OPEN_SHARE and blind_share <= WALKABILITY_OPEN_SHARE:
        band = "open"
    elif dead_share <= WALKABILITY_THIN_SHARE and blind_share <= WALKABILITY_THIN_SHARE:
        band = "thin"
    else:
        band = "broken"
    return Observation(
        id="walkability",
        band=band,
        metrics={
            "edges_per_subject": _rounded(_share(len(view.edges), subjects), 2),
            "dead_end_share": _rounded(dead_share),
            "arrival_blind_share": _rounded(blind_share),
            "largest_component_share": _rounded(_share(largest, subjects)),
            "islands": len(islands),
        },
        evidence=clip_evidence((*islands, *dead_ends)),
        fields={
            "subjects": subjects,
            "dead_ends": len(dead_ends),
            "dead_end_share": _pct(dead_share),
            "arrival_blind": len(blind),
            "arrival_blind_share": _pct(blind_share),
            "component_share": _pct(_share(largest, subjects)),
            "islands": len(islands),
            "edges": len(view.edges),
        },
    )


# ─────────────────────────────────────────────────────────────────────────── 2. shape


def read_shape(view: LibraryView) -> Observation:
    subjects = len(view.subjects)
    total = view.total_claims
    ranked = sorted(view.subjects, key=lambda s: (-view.claims.get(s, 0), s))
    lead = ranked[0] if ranked else ""
    lead_claims = view.claims.get(lead, 0) if lead else 0
    lead_share = _share(lead_claims, total)
    even = _share(total, subjects)
    #: Two different numbers, and the console showed what happens when one wears the other's
    #: name: a real library's lead held 159 claims against a second subject's 54 — 2.9× the
    #: next subject — and the reading said "23.41× an even share" under the name `lead_ratio`.
    #: `lead_ratio` is the lead against the subject BEHIND it (§4.2); `lead_over_even` is the
    #: lead against a flat spread, which is what the band guard needs.
    lead_over_even = _share(lead_claims, even)
    second_claims = view.claims.get(ranked[1], 0) if len(ranked) > 1 else 0
    lead_ratio = _share(lead_claims, second_claims) if second_claims else 0.0
    rows = _family_rows(view)
    heaviest = max(
        (row for row in rows if row[1] and row[4]),
        key=lambda row: row[3] / row[4],
        default=None,
    )
    heaviest_ratio = (heaviest[3] / heaviest[4]) if heaviest else 0.0
    empty = [row[0] for row in rows if not row[1]]
    clusters = len(_components(view))
    concentrated = lead_over_even >= SHAPE_LEAD_OVER_EVEN
    if (
        lead_share <= SHAPE_EVEN_LEAD_SHARE or not concentrated
    ) and heaviest_ratio < SHAPE_FAMILY_RATIO:
        band = "even"
    elif lead_share > SHAPE_LEANING_LEAD_SHARE and concentrated:
        band = "collapsing"
    else:
        band = "leaning"
    return Observation(
        id="shape",
        band=band,
        metrics={
            "lead_share": _rounded(lead_share),
            "lead_ratio": _rounded(lead_ratio, 2),
            "lead_over_even": _rounded(lead_over_even, 2),
            "heaviest_family_ratio": _rounded(heaviest_ratio, 2),
            "empty_families": len(empty),
            "clusters": clusters,
        },
        evidence=clip_evidence(
            item for item in (lead, heaviest[0] if heaviest else "", *empty) if item
        ),
        fields={
            "subjects": subjects,
            "claims": total,
            "path": lead,
            "title": view.titles.get(lead, ""),
            "lead_share": _pct(lead_share),
            "lead_ratio": _rounded(lead_ratio, 2),
            "lead_over_even": _rounded(lead_over_even, 2),
            "count": lead_claims,
            "family": heaviest[0] if heaviest else "",
            "family_share": _pct(heaviest[3] if heaviest else 0.0),
            "family_pages": _pct(heaviest[4] if heaviest else 0.0),
            "empty_families": len(empty),
            "clusters": clusters,
        },
    )


# ─────────────────────────────────────────────────────────────── 3. knowledge vs. log


def read_knowledge_vs_log(view: LibraryView) -> Observation:
    narration_count = 0
    total_blocks = 0
    log_subjects: list[tuple[float, str]] = []
    for subject in view.subjects:
        blocks = _subject_blocks(view, subject)
        total_blocks += len(blocks)
        shaped = sum(1 for block in blocks if _is_narration(block))
        narration_count += shaped
        share = _share(shaped, len(blocks))
        if len(blocks) >= LOG_SUBJECT_MIN_CLAIMS and share >= LOG_SUBJECT_SHARE:
            log_subjects.append((share, subject))
    narration_share = _share(narration_count, total_blocks)
    rows = _family_rows(view)
    lead_family = max(rows, key=lambda row: row[3], default=None)
    if narration_share <= NARRATION_KNOWLEDGE_SHARE:
        band = "knowledge"
    elif narration_share <= NARRATION_MIXED_SHARE:
        band = "mixed"
    else:
        band = "log"
    # Evidence is what a reader can OPEN. The date prefix is the MECHANISM — a console that
    # showed `2026-08-12,` three times told the Owner nothing they could act on — so what
    # travels is the subjects that are made of those claims, the most log-shaped first.
    # Most log-shaped first, ties by path — the same ordering rule `_by_weight` uses, so
    # which five of them travel is a function of the library and not of sort luck.
    worst = [
        subject
        for _share_of, subject in sorted(
            log_subjects, key=lambda item: (-item[0], item[1])
        )
    ]
    return Observation(
        id="knowledge_vs_log",
        band=band,
        metrics={
            "narration_share": _rounded(narration_share),
            "log_subject_share": _rounded(_share(len(log_subjects), len(view.subjects))),
            "lead_family_claim_share": _rounded(lead_family[3] if lead_family else 0.0),
        },
        evidence=clip_evidence(worst),
        fields={
            "claims": total_blocks,
            "count": narration_count,
            "narration_share": _pct(narration_share),
            "log_subjects": len(log_subjects),
            "log_subject_share": _pct(_share(len(log_subjects), len(view.subjects))),
            "family": lead_family[0] if lead_family else "",
            "family_share": _pct(lead_family[3] if lead_family else 0.0),
        },
    )


# ──────────────────────────────────────────────────────────────────────── 4. liveness


def _as_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def read_liveness(
    view: LibraryView,
    *,
    written_on: Mapping[str, str] | None = None,
    read_at: str = "",
) -> Observation:
    """Does the library ever correct itself?

    Three of the metrics come out of canonical alone: a supersession is a marker in the bytes,
    a rollover is a closed volume, an overview is a region a developed page either has or does
    not. The two that need HISTORY — how long a subject has stood untouched, and the median
    age of a write — are read only when a caller supplies `written_on` (the service reads it
    off git). Without it they are null and the band is chosen from the supersession rate
    alone, which is the honest reading: a library whose write history was not read is not a
    library that was never written.
    """
    claims = view.total_claims
    supersessions = sum(
        len(SUPERSEDES_MARK_RE.findall(view.body(path))) for path in view.documents
    )
    per_hundred = 100 * _share(supersessions, claims)
    volumes = [
        path
        for path in view.documents
        if VOLUME_FILE_RE.match(path.rsplit("/", 1)[-1]) is not None
    ]
    rollovers = len(volumes) or sum(
        int(view.frontmatter(path).get(VOLUME_COUNT_KEY) or 0)
        for path in view.documents
    )
    developed = [
        subject
        for subject in view.subjects
        if view.claims.get(subject, 0) >= OVERVIEW_REQUIRED_AFTER_CLAIMS
    ]
    with_overview = [
        subject
        for subject in developed
        if parse_overview(view.body(subject))[0] is not None
    ]
    coverage = _share(len(with_overview), len(developed)) if developed else None

    untouched_share: float | None = None
    median_days: float | None = None
    dates = {
        subject: written
        for subject in view.subjects
        if (written := _as_date(str((written_on or {}).get(subject, ""))))
    }
    if written_on and dates:
        today = _as_date(read_at) or max(dates.values())
        ages = sorted((today - written).days for written in dates.values())
        median_days = float(ages[len(ages) // 2])
        stale = [age for age in ages if age > LIVENESS_UNTOUCHED_DAYS]
        untouched_share = _rounded(_share(len(stale), len(view.subjects)))

    living = per_hundred >= LIVENESS_LIVING_PER_HUNDRED and (
        untouched_share is None or untouched_share <= LIVENESS_LIVING_UNTOUCHED_SHARE
    )
    still = per_hundred < LIVENESS_STILL_PER_HUNDRED or (
        untouched_share is not None
        and untouched_share >= LIVENESS_STILL_UNTOUCHED_SHARE
    )
    band = "living" if living else ("still" if still else "settling")
    return Observation(
        id="liveness",
        band=band,
        metrics={
            "supersessions_per_100_claims": _rounded(per_hundred, 2),
            "rollovers": rollovers,
            "overview_coverage": None if coverage is None else _rounded(coverage),
            "untouched_subject_share": untouched_share,
            "median_days_since_write": median_days,
        },
        evidence=clip_evidence(sorted(volumes)[:3]),
        fields={
            "subjects": len(view.subjects),
            "claims": claims,
            "count": supersessions,
            "per_hundred": _rounded(per_hundred, 2),
            "rollovers": rollovers,
            "overview_share": _pct(coverage),
            "developed": len(developed),
        },
    )


# ─────────────────────────────────────────────────────────────────── 5. type structure


def read_type_structure(view: LibraryView) -> Observation:
    """What kind of knowledge is accumulating, and does the structure it implies exist?

    Three proxies, each a share of its own base: dated claims written outside any chronology
    page, decision-shaped sections outside the decisions family, and declared families nothing
    was ever filed under. None of them is a fault on the page it sits on — a dated claim is a
    perfectly good claim — which is exactly why this is a reading of the whole and not a check
    item: what it measures is the distance between the knowledge arriving and the structure
    declared for it.
    """
    claims = 0
    sections = 0
    dated_outside = 0
    decision_outside = 0
    #: The PAGES each proxy caught, with how much of it each one carries: the evidence is
    #: something the Owner can open, never the matched fragment. A console that showed
    #: `rationale` and `2026-08-12,` gave a reader three words and nowhere to go.
    dated_pages: dict[str, int] = {}
    decision_pages: dict[str, int] = {}
    for subject in view.subjects:
        chronology = role_of(subject, view.path_templates) == ROLE_CHRONOLOGY
        template = template_of(subject, view.path_templates) or ""
        decisions_family = "decisions" in template.split("/")
        for path in view.files_of(subject):
            body = view.body(path)
            blocks = claim_blocks(body)
            claims += len(blocks)
            if not chronology:
                dated = sum(
                    1
                    for block in blocks
                    if SESSION_DATE_PREFIX_RE.match(claim_words(block))
                )
                dated_outside += dated
                if dated:
                    dated_pages[subject] = dated_pages.get(subject, 0) + dated
            for _line, heading in section_headings(body):
                sections += 1
                if not decisions_family and heading.strip().casefold() in DECISION_SECTION_WORDS:
                    decision_outside += 1
                    decision_pages[subject] = decision_pages.get(subject, 0) + 1
    rows = _family_rows(view)
    empty = [row[0] for row in rows if not row[1]]
    dated_share = _share(dated_outside, claims)
    decision_share = _share(decision_outside, sections)
    empty_share = _share(len(empty), len(rows))
    worst = max(dated_share, decision_share, empty_share)
    if worst <= TYPE_ALIGNED_SHARE:
        band = "aligned"
    elif worst <= TYPE_STRAINED_SHARE:
        band = "strained"
    else:
        band = "misfiled"
    return Observation(
        id="type_structure",
        band=band,
        metrics={
            "dated_outside_chronology_share": _rounded(dated_share),
            "decision_shaped_outside_share": _rounded(decision_share),
            "empty_family_share": _rounded(empty_share),
        },
        evidence=clip_evidence(
            (*_by_weight(decision_pages), *_by_weight(dated_pages), *empty)
        ),
        fields={
            "claims": claims,
            "dated": dated_outside,
            "dated_share": _pct(dated_share),
            "decision_shaped": decision_outside,
            "decision_share": _pct(decision_share),
            "empty_families": len(empty),
            "families": len(rows),
            "worst_share": _pct(worst),
        },
    )


# ──────────────────────────────────────────────────────────────────── 6. demand/supply


def read_demand_supply(
    view: LibraryView, consultations: Sequence[Consultation] | None = None
) -> Observation:
    """Is what the library holds what people ask it?

    The one dimension read from something other than canonical: the kept consultation records,
    which are stored observations a rebuild replays and never rewrites. With none of them the
    band is `unread` — not `matched`, and not a zero: a library nobody has asked anything has
    no demand to compare its holdings against, and saying otherwise would invent a reading.
    """
    records = list(consultations or ())
    subjects = len(view.subjects)
    if not records:
        return Observation(
            id="demand_supply",
            band="unread",
            metrics={
                "consultations": 0,
                "uncited_share": None,
                "consulted_subject_share": None,
                "lead_family_demand_ratio": None,
            },
            fields={"subjects": subjects, "claims": view.total_claims},
        )
    present = set(view.documents)
    gaps = [record for record in records if not record.cited]
    consulted: set[str] = set()
    demand: dict[str, int] = {}
    hits = 0
    for record in records:
        families: set[str] = set()
        for path in record.paths:
            subject = subject_of(str(path), present)
            if subject in view.claims:
                consulted.add(subject)
            template = template_of(subject, view.path_templates)
            if template:
                families.add(template)
        for template in families:
            demand[template] = demand.get(template, 0) + 1
            hits += 1
    rows = {row[0]: row for row in _family_rows(view)}
    lead_family = max(demand, key=lambda name: (demand[name], name), default="")
    demand_share = _share(demand.get(lead_family, 0), hits)
    claim_share = rows[lead_family][3] if lead_family in rows else 0.0
    ratio = _share(demand_share, claim_share) if claim_share else 0.0
    gap_share = _share(len(gaps), len(records))
    matched = gap_share <= DEMAND_GAP_SHARE and (
        not lead_family or ratio <= DEMAND_FAMILY_RATIO
    )
    return Observation(
        id="demand_supply",
        band="matched" if matched else "skewed",
        metrics={
            "consultations": len(records),
            "uncited_share": _rounded(gap_share),
            "consulted_subject_share": _rounded(_share(len(consulted), subjects)),
            "lead_family_demand_ratio": _rounded(ratio, 2),
        },
        evidence=clip_evidence(item for item in (lead_family,) if item),
        fields={
            "consultations": len(records),
            "count": len(gaps),
            "gap_share": _pct(gap_share),
            "consulted": len(consulted),
            "never_consulted": subjects - len(consulted),
            "subjects": subjects,
            "family": lead_family,
            "demand_share": _pct(demand_share),
            "claim_share": _pct(claim_share),
            "ratio": _rounded(ratio, 2),
        },
    )


def read_dimensions(
    view: LibraryView,
    *,
    consultations: Sequence[Consultation] | None = None,
    written_on: Mapping[str, str] | None = None,
    read_at: str = "",
) -> list[Observation]:
    """All six, in §4.2's order."""
    return [
        read_walkability(view),
        read_shape(view),
        read_knowledge_vs_log(view),
        read_liveness(view, written_on=written_on, read_at=read_at),
        read_type_structure(view),
        read_demand_supply(view, consultations),
    ]


__all__ = [
    "DECISION_SECTION_WORDS",
    "DEMAND_FAMILY_RATIO",
    "DEMAND_GAP_SHARE",
    "LIVENESS_LIVING_PER_HUNDRED",
    "LIVENESS_LIVING_UNTOUCHED_SHARE",
    "LIVENESS_STILL_PER_HUNDRED",
    "LIVENESS_STILL_UNTOUCHED_SHARE",
    "LIVENESS_UNTOUCHED_DAYS",
    "LOG_SUBJECT_MIN_CLAIMS",
    "LOG_SUBJECT_SHARE",
    "NARRATION_KNOWLEDGE_SHARE",
    "NARRATION_MIXED_SHARE",
    "SHAPE_EVEN_LEAD_SHARE",
    "SHAPE_FAMILY_RATIO",
    "SHAPE_LEAD_OVER_EVEN",
    "SHAPE_LEANING_LEAD_SHARE",
    "TYPE_ALIGNED_SHARE",
    "TYPE_STRAINED_SHARE",
    "WALKABILITY_OPEN_SHARE",
    "WALKABILITY_THIN_SHARE",
    "Consultation",
    "Observation",
    "read_demand_supply",
    "read_dimensions",
    "read_knowledge_vs_log",
    "read_liveness",
    "read_shape",
    "read_type_structure",
    "read_walkability",
]
