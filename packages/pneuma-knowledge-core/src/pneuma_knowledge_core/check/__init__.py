"""The CHECK — tier two of docs/design/structure-lens.md: the library's own reflection.

What the insider can find by checking needs a checklist, not a vantage point. A page that
names another subject twenty times and never links it, an evolution page whose turning points
cite no decision, a hub that leaves three of its own pages unreachable: a Steward standing at
the page can see each of these against the contract and can repair it in a round of its own.

This package is that checklist. It reads canonical documents and the contract's path
templates, writes nothing, and produces a `CheckReport` — findings, each with the page it is
about, verbatim evidence, what it costs and the verb that repairs it. Two kinds: JUDGEMENT
items, the contract's expectations no write can decide, and LEGACY items, the instances a
library already holds of the faults the write face now refuses.

A finding belongs to the lowest tier that can see it, so nothing here is a lens reading and
nothing here is a fault the gate refuses at the write. Everything is pure and sync: same
documents, same templates, same report.
"""

from __future__ import annotations

from .checks import (
    CHECKS,
    CHRONOLOGY_MIN_DATED_SECTIONS,
    MENTION_MIN_COUNT,
    MENTION_MIN_TITLE_CHARS,
    SINGLE_SOURCE_MIN_CLAIMS,
    evidence_hash,
    finding_key,
    make_finding,
    run_checks,
)
from .model import (
    CHECK_IDS,
    CHECK_KIND,
    JUDGEMENT_IDS,
    LEGACY_IDS,
    CheckReport,
    Finding,
)
from .report import (
    build_check,
    order_findings,
    page_findings,
    render_action,
    render_impact,
)

__all__ = [
    "CHECKS",
    "CHECK_IDS",
    "CHECK_KIND",
    "CHRONOLOGY_MIN_DATED_SECTIONS",
    "JUDGEMENT_IDS",
    "LEGACY_IDS",
    "MENTION_MIN_COUNT",
    "MENTION_MIN_TITLE_CHARS",
    "SINGLE_SOURCE_MIN_CLAIMS",
    "CheckReport",
    "Finding",
    "build_check",
    "evidence_hash",
    "finding_key",
    "make_finding",
    "order_findings",
    "page_findings",
    "render_action",
    "render_impact",
    "run_checks",
]
