"""The check: one reading of a canonical library against the contract, at one ref (§3).

`build_check` is pure and sync — documents and templates in, a `CheckReport` out. It calls no
port, reads no clock of its own beyond the `read_at` a caller hands it, and runs no model.
That is what makes the list the Owner sees the list the Steward was shown: the same inputs
produce the same report, byte for byte, in a route, in a CLI and in a `review` round.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..prompts import prompt
from ..shape import subject_of
from ..shape.view import build_view, judged_documents
from .checks import run_checks
from .model import KIND_ORDER, CheckReport, Finding


def build_check(
    documents: Sequence[object] | Mapping[str, object],
    path_templates: Sequence[str],
    *,
    ref: str = "",
    read_at: str = "",
) -> CheckReport:
    """The whole check: the base counts and every §3.1 item, ordered."""
    judged, known = judged_documents(documents)
    view = build_view(judged, path_templates, known_paths=known)
    return CheckReport(
        ref=ref,
        read_at=read_at,
        subjects=len(view.subjects),
        files=len(judged),
        claims=view.total_claims,
        edges=len(view.edges),
        findings=tuple(order_findings(run_checks(view))),
    )


def order_findings(findings: Sequence[Finding]) -> list[Finding]:
    """§5.1: legacy first — a hook fault is unambiguous — then judgement; within a kind by id,
    then by path."""
    return sorted(
        findings,
        key=lambda f: (
            KIND_ORDER.get(f.kind, len(KIND_ORDER)),
            f.id,
            f.paths[0] if f.paths else "",
            f.key,
        ),
    )


def page_findings(report: CheckReport, path: str) -> list[Finding]:
    """The findings one page answers for, in report order.

    A closed volume is answered for by its page: the check names subjects, so asking about
    `<doc>/a01.md` returns what `<doc>.md` holds. The fold uses the paths the report was built
    over, which is the same fold the counts used.
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
    """What repairs it, in the same language."""
    return prompt(finding.action.key, **finding.action.fields)


__all__ = [
    "build_check",
    "order_findings",
    "page_findings",
    "render_action",
    "render_impact",
]
