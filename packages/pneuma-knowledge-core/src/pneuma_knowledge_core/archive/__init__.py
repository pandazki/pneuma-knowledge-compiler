"""The archive: planning what a move actually moves.

`domain/archive.py` states the MARKS (a path under `archive/`, a source's `archived_at`).
This package holds the two pieces of judgement-free reasoning above them: given the Owner's
seeds, what else follows mechanically from the citations already in the library
(`proposal.py`), and what the RECORD a moved subject leaves behind at its live path says
(`record.py`) — the short page that keeps the subject answerable, as archived, instead of
letting it vanish out of a library that still mentions it.

Pure and synchronous — a tree of canonical documents in, a proposal out. Nothing here
reads a port, and nothing here executes anything: the proposal is shown to the Owner, who
confirms an exact set against an exact library state (docs/design/archive.md §5).
"""

from .proposal import (
    ArchiveAction,
    ArchiveProposal,
    NOTE_ALREADY_ARCHIVED,
    NOTE_ALREADY_LIVE,
    NOTE_FULLY_DEPENDENT,
    NOTE_ORPHANED,
    NOTE_PARTIALLY_DEPENDENT,
    NOTE_RESTORED_WITH_PAGE,
    NOTE_SEED,
    NOTE_STILL_CITED,
    NOTE_UNKNOWN,
    ProposalItem,
    ProposalReason,
    plan_archive,
)
from .record import (
    GROUNDING_EXEMPT,
    RecordFacts,
    RecordViolation,
    compute_record_facts,
    note_machinery,
    record_anchors,
    record_reason,
    statement_quote,
    record_doc_id,
    record_facts_in_move,
    render_record,
    run_archive_record_gate,
    sanitize_note,
    unit_facts,
)

__all__ = [
    "NOTE_ALREADY_ARCHIVED",
    "NOTE_ALREADY_LIVE",
    "NOTE_FULLY_DEPENDENT",
    "NOTE_ORPHANED",
    "NOTE_PARTIALLY_DEPENDENT",
    "NOTE_RESTORED_WITH_PAGE",
    "NOTE_SEED",
    "NOTE_STILL_CITED",
    "NOTE_UNKNOWN",
    "ArchiveAction",
    "ArchiveProposal",
    "GROUNDING_EXEMPT",
    "ProposalItem",
    "ProposalReason",
    "RecordFacts",
    "RecordViolation",
    "compute_record_facts",
    "note_machinery",
    "plan_archive",
    "record_anchors",
    "record_doc_id",
    "record_reason",
    "record_facts_in_move",
    "render_record",
    "run_archive_record_gate",
    "sanitize_note",
    "statement_quote",
    "unit_facts",
]
