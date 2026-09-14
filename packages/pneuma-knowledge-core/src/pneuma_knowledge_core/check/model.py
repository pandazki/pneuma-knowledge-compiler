"""The check's report, as data — no rendering, no I/O, no model.

The types here are the whole contract between the check and everything that reads it: the
HTTP route, the CLI, the console, and the `review` round that repairs what it lists. The
field names are fixed by docs/design/structure-lens.md §5.1 — a reader keys on them, so they
are part of the design and not of this module's convenience.

Every value is derived. A `CheckReport` is a function of (documents, path templates) at one
ref; nothing in it is stored, and re-reading the same ref reproduces it byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..shape.phrase import Phrase

# ───────────────────────────────────────────────────────────── the ids (§3.1)
#
# JUDGEMENT items are the contract's expectations no hook can decide: they need the whole
# library, or they need a judgement about what a page is FOR. LEGACY items are instances of
# a tier-one fault on a page written before the hook existed — the hook keeps new ones out,
# so what the check lists is a finite backlog with a repairing verb each.

NAV_HUB_INCOMPLETE = "nav.hub_incomplete"
NAV_CHRONOLOGY_UNLINKED = "nav.chronology_unlinked"
NAV_DECISION_UNLINKED = "nav.decision_unlinked"
NAV_MENTION_UNLINKED = "nav.mention_unlinked"
NAV_DEAD_LINK = "nav.dead_link"
ID_TITLE_DUPLICATE = "id.title_duplicate"
CORR_SINGLE_SOURCE = "corr.single_source"
FORM_LEGACY_SECTIONS = "form.legacy_sections"

FORM_STRAY_HEADING = "form.stray_heading"
FORM_COLLAPSED_BODY = "form.collapsed_body"
ID_TITLE_DEGENERATE = "id.title_degenerate"
ID_TITLE_SHARED_WITH_HUB = "id.title_shared_with_hub"
ID_TITLE_CHILD_COLLISION = "id.title_child_collision"
FORM_UNORDERED_CHRONOLOGY = "form.unordered_chronology"
FORM_OVERVIEW_RESTATES = "form.overview_restates"
FORM_DEFINITION_EMPTY = "form.definition_empty"
FORM_UNANCHORED_CITATION = "form.unanchored_citation"

#: The judgement items, exactly §3.1's table.
JUDGEMENT_IDS: tuple[str, ...] = (
    NAV_HUB_INCOMPLETE,
    NAV_CHRONOLOGY_UNLINKED,
    NAV_DECISION_UNLINKED,
    NAV_MENTION_UNLINKED,
    NAV_DEAD_LINK,
    ID_TITLE_DUPLICATE,
    CORR_SINGLE_SOURCE,
    FORM_LEGACY_SECTIONS,
)

#: The legacy items: one per tier-one hook, listing what a library already holds of exactly
#: the fault the write face now refuses.
LEGACY_IDS: tuple[str, ...] = (
    FORM_STRAY_HEADING,
    FORM_COLLAPSED_BODY,
    ID_TITLE_DEGENERATE,
    ID_TITLE_SHARED_WITH_HUB,
    ID_TITLE_CHILD_COLLISION,
    FORM_UNORDERED_CHRONOLOGY,
    FORM_OVERVIEW_RESTATES,
    FORM_DEFINITION_EMPTY,
    FORM_UNANCHORED_CITATION,
)

#: Every check id. Enumerable so a test can assert that the prompt catalog carries an
#: `impact` and an `action` for each — an item with no sentence is a number with no
#: consequence, which §1 rules is not a finding.
CHECK_IDS: tuple[str, ...] = (*LEGACY_IDS, *JUDGEMENT_IDS)

#: id → kind. A table rather than a convention, so an item cannot quietly change tier.
CHECK_KIND: dict[str, str] = {
    **{item: "legacy" for item in LEGACY_IDS},
    **{item: "judgement" for item in JUDGEMENT_IDS},
}

#: The report's ordering key (§5.1): legacy first — a hook fault is unambiguous — then
#: judgement.
KIND_ORDER: dict[str, int] = {"legacy": 0, "judgement": 1}


@dataclass(frozen=True)
class Finding:
    """One thing the check saw on one page, with what it costs and what repairs it."""

    key: str
    id: str
    kind: Literal["judgement", "legacy"]
    paths: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    impact: Phrase = field(default_factory=lambda: Phrase(""))
    action: Phrase = field(default_factory=lambda: Phrase(""))

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "id": self.id,
            "kind": self.kind,
            "paths": list(self.paths),
            "targets": list(self.targets),
            "evidence": list(self.evidence),
            "impact": self.impact.to_dict(),
            "action": self.action.to_dict(),
        }


@dataclass(frozen=True)
class CheckReport:
    """The whole check, at one ref."""

    ref: str = ""
    read_at: str = ""
    subjects: int = 0
    files: int = 0
    claims: int = 0
    edges: int = 0
    findings: tuple[Finding, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "read_at": self.read_at,
            "subjects": self.subjects,
            "files": self.files,
            "claims": self.claims,
            "edges": self.edges,
            "findings": [finding.to_dict() for finding in self.findings],
        }


__all__ = [
    "CHECK_IDS",
    "CHECK_KIND",
    "CORR_SINGLE_SOURCE",
    "FORM_COLLAPSED_BODY",
    "FORM_DEFINITION_EMPTY",
    "FORM_LEGACY_SECTIONS",
    "FORM_OVERVIEW_RESTATES",
    "FORM_STRAY_HEADING",
    "FORM_UNANCHORED_CITATION",
    "FORM_UNORDERED_CHRONOLOGY",
    "ID_TITLE_CHILD_COLLISION",
    "ID_TITLE_DEGENERATE",
    "ID_TITLE_DUPLICATE",
    "ID_TITLE_SHARED_WITH_HUB",
    "JUDGEMENT_IDS",
    "KIND_ORDER",
    "LEGACY_IDS",
    "NAV_CHRONOLOGY_UNLINKED",
    "NAV_DEAD_LINK",
    "NAV_DECISION_UNLINKED",
    "NAV_HUB_INCOMPLETE",
    "NAV_MENTION_UNLINKED",
    "CheckReport",
    "Finding",
]
