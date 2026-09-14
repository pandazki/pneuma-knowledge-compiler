"""The structure lens — a derived, model-free reading of the library's SHAPE.

The Steward works inside the library, one source at a time, and every compile can be right
while the sum drifts: a page filling with session narration, a chronology arriving in ingest
order rather than in time, a subject existing twice under two spellings, a family nothing
links to. None of that is a fabrication and none of it is visible from where a compile
stands. It is visible from outside, to a reader that takes the whole library at once.

This package is that reader. It reads canonical documents and the contract's path templates,
writes nothing, and produces a `Report` — findings, each with its evidence, what it costs and
one recommended action addressed to the Steward, the Owner or the mechanism itself.

Design authority: docs/design/structure-lens.md. Everything here is pure and sync: same
documents, same templates, same report.
"""

from __future__ import annotations

from .families import family_role, project_dir, role_of, roles, subject_of
from .lenses import LENS_IDS, LENS_LEVEL, LibraryView, build_view, run_lenses
from .links import Edge, subject_claims, subject_edges
from .model import Decision, FamilyRow, Finding, Phrase, Report
from .report import (
    build_report,
    judged_documents,
    order_findings,
    page_findings,
    render_action,
    render_impact,
    score_of,
)

__all__ = [
    "LENS_IDS",
    "LENS_LEVEL",
    "Decision",
    "Edge",
    "FamilyRow",
    "Finding",
    "LibraryView",
    "Phrase",
    "Report",
    "build_report",
    "build_view",
    "family_role",
    "judged_documents",
    "order_findings",
    "page_findings",
    "project_dir",
    "render_action",
    "render_impact",
    "role_of",
    "roles",
    "run_lenses",
    "score_of",
    "subject_claims",
    "subject_edges",
    "subject_of",
]
