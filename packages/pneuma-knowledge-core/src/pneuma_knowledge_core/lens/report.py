"""The report: one reading of a canonical library at one ref (design §3).

`build_report` is pure and sync — documents and templates in, a `Report` out. It calls no
port, reads no clock of its own beyond the `read_at` a caller hands it, and runs no model.
That is what makes the number the Owner sees the number the Steward was shown: the same
inputs produce the same report, byte for byte, in a route, in a CLI and in a test.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from ..domain.archive import is_archive_record, is_archived_path
from ..prompts import prompt
from .families import subject_of
from .lenses import LENS_IDS, build_view, family_rows, run_lenses
from .model import LEVEL_ORDER, Decision, FamilyRow, Finding, Report


def _by_path(documents: Sequence[object] | Mapping[str, object]) -> dict[str, object]:
    """`{path: document}` from either shape. A document is anything carrying `.path`,
    `.frontmatter` and `.body` — `CanonicalDocument` and the gate's `DraftDoc` both do, and
    the lens has no business knowing which of the two it was handed."""
    if isinstance(documents, Mapping):
        return {str(path): doc for path, doc in documents.items()}
    return {str(getattr(doc, "path", "")): doc for doc in documents if getattr(doc, "path", "")}


def judged_documents(
    documents: Sequence[object] | Mapping[str, object],
) -> tuple[dict[str, object], frozenset[str]]:
    """`(what the lens judges, every path it resolves a link against)`.

    Two sets, deliberately different (§2). What is JUDGED is the live library minus the
    archive records: an archived document is out of every count, and a record is a page a
    mechanical channel wrote and no compile may touch, so a finding about one would name an
    action nobody can take. What links RESOLVE against is every path handed in — the archive
    included — so a link to a subject the Owner retired is not reported as a dead link. The
    archive leaves the counts; it does not leave the map.
    """
    by_path = _by_path(documents)
    judged = {
        path: doc
        for path, doc in by_path.items()
        if not is_archived_path(path) and not is_archive_record(doc)
    }
    return judged, frozenset(by_path)


def build_report(
    documents: Sequence[object] | Mapping[str, object],
    path_templates: Sequence[str],
    *,
    ref: str = "",
    read_at: str = "",
    decisions: Mapping[str, Decision] | None = None,
) -> Report:
    """The whole reading: base counts, every §4 lens, the score, the order, the balance table.

    `decisions` maps a finding key to a standing decline; a finding whose key is in it
    carries it and stops counting against the score. The map is empty in this version — the
    channel that fills it is design §9 — and the parameter is here because the key it is
    addressed by is computed here and nowhere else.
    """
    judged, known = judged_documents(documents)
    view = build_view(judged, path_templates, known_paths=known)
    findings = _decided(run_lenses(view), decisions or {})
    return Report(
        ref=ref,
        read_at=read_at,
        subjects=len(view.subjects),
        files=len(judged),
        claims=view.total_claims,
        edges=len(view.edges),
        score=score_of(findings, view.subjects),
        findings=tuple(order_findings(findings)),
        families=tuple(
            FamilyRow(name=name, pages=pages, claims=claims, share=share)
            for name, pages, claims, share in family_rows(view)
        ),
    )


def _decided(
    findings: Sequence[Finding], decisions: Mapping[str, Decision]
) -> list[Finding]:
    """Attach a standing decline to every finding whose key it was made about.

    The key hashes the evidence, so a decline stops applying the moment the evidence changes
    — which is the point: the question was answered about what stood then.
    """
    if not decisions:
        return list(findings)
    out: list[Finding] = []
    for finding in findings:
        decision = decisions.get(finding.key)
        out.append(
            Finding(
                key=finding.key,
                lens=finding.lens,
                level=finding.level,
                actor=finding.actor,
                paths=finding.paths,
                targets=finding.targets,
                evidence=finding.evidence,
                impact=finding.impact,
                action=finding.action,
                weight=finding.weight,
                decision=decision,
            )
            if decision is not None
            else finding
        )
    return out


def score_of(findings: Sequence[Finding], subjects: Collection[str]) -> int:
    """The share of subjects that no open finding NAMES, as a whole number 0–100 (§3.3).

    A subject is named when it appears in any finding's `paths`, whichever the level — a
    principle finding names every page it is about. A declined finding names nothing: the
    question it asked has been answered, so its pages are clean again.

    Deliberately not a weighted sum. A weighted sum was the first shape and a real 250-page
    library showed what it is worth: 508 findings put it at zero, where it stayed however
    many pages were repaired, because the cap had been reached long before. "How much of the
    base has nothing to fix" moves by one page each time one page is fixed, which is the
    only property a number watched between snapshots has to have.
    """
    total = set(subjects)
    if not total:
        return 100
    named = {
        path
        for finding in findings
        if finding.decision is None
        for path in finding.paths
    }
    return int(round(100 * len(total - named) / len(total)))


def order_findings(findings: Sequence[Finding]) -> list[Finding]:
    """§3.4: principle before drift before shape; within a level by weight descending; then
    by lens id; then by path."""
    return sorted(
        findings,
        key=lambda f: (
            LEVEL_ORDER.get(f.level, len(LEVEL_ORDER)),
            -f.weight,
            f.lens,
            f.paths[0] if f.paths else "",
            f.key,
        ),
    )


def page_findings(report: Report, path: str) -> list[Finding]:
    """The findings one page answers for, in report order.

    A closed volume is answered for by its page: the lens names subjects, so asking about
    `<doc>/a01.md` returns what `<doc>.md` holds. The fold uses the paths the report was
    built over, which is the same fold the counts used.
    """
    wanted = str(path or "")
    if not wanted:
        return []
    subjects = {p for finding in report.findings for p in finding.paths}
    wanted = subject_of(wanted, subjects) if wanted not in subjects else wanted
    return [finding for finding in report.findings if wanted in finding.paths]


def render_impact(finding: Finding) -> str:
    """What the finding costs, as the reader's language renders it."""
    return prompt(finding.impact.key, **finding.impact.fields)


def render_action(finding: Finding) -> str:
    """What to do about it, addressed to the finding's actor."""
    return prompt(finding.action.key, **finding.action.fields)


__all__ = [
    "LENS_IDS",
    "build_report",
    "judged_documents",
    "order_findings",
    "page_findings",
    "render_action",
    "render_impact",
    "score_of",
]
