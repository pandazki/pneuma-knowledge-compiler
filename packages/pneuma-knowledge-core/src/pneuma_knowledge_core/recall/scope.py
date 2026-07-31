"""SnapshotScope — the answering face of a knowledge-base snapshot (architecture.md §7).

WHY THIS IS SO SMALL
--------------------
A knowledge base is a moving object, so "what did it say in March?" is a real question. The
mechanism that answers it lives entirely OUTSIDE core: a snapshot is a frozen TENANT (see the
service's `kb_snapshots`), and every storage layer here already isolates by `user_id`. So
answering over a snapshot is the ordinary recall stack called with the snapshot tenant's id
and the canonical document set read at its pinned git ref. No retrieval function needs a new
filter, no index needs a new field, and nothing has to be re-embedded.

What is left for core is the part that is genuinely about the ANSWER rather than the storage:
the model has to be told, in words, that it is reading a frozen past state and that a gap is
the honest state of that state rather than a retrieval failure to work around. That is this
module — an identity, a moment, and the two prose surfaces built from them.

WHY IT IS NOT JUST A STRING
---------------------------
Because two different surfaces need the same facts stated the same way: the opening
declaration, and the stated absence a `fetch_verbatim` miss returns under a snapshot. Passing
a label around as a bare string is how those two drift apart.

RELATION TO `as_of`
-------------------
Orthogonal, and both are rendered. `as_of` is what time it is NOW, so "last Tuesday" resolves;
this is which VERSION of the base is open. A snapshot answer legitimately says "as of today,
the newest thing this snapshot knows is …".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..prompts import prompt


@dataclass(frozen=True)
class SnapshotScope:
    """The snapshot a recall is pinned to, as the answering side needs to describe it.

    Deliberately NOT the snapshot record: no tenant id, no canonical ref, no counts. Core
    never routes storage, so carrying the routing fields here would only invite a core
    function to start using them."""

    #: The user-facing name of the snapshot ("before the Q3 reorg", "week-02").
    label: str
    #: When the snapshot was frozen (UTC). None when the caller does not know it.
    created_at: datetime | None = None

    def moment(self) -> str:
        """The snapshot named for the model: label plus its freeze time when known."""
        if self.created_at is None:
            return prompt("recall.snapshot.moment_undated", label=self.label)
        return prompt(
            "recall.snapshot.moment",
            label=self.label,
            at=self.created_at.isoformat(),
        )

    def declaration(self) -> str:
        """The time anchor rendered into the answering prompt (see module docstring)."""
        return prompt("recall.snapshot.declaration", snapshot=self.moment())


def scope_declaration(scope: SnapshotScope | None) -> str | None:
    """`scope.declaration()`, or None for the HEAD case (no snapshot section is rendered)."""
    return None if scope is None else scope.declaration()


def out_of_scope_source(scope: SnapshotScope, source_id: object) -> str:
    """The stated absence an L0 fetch returns for a source the snapshot does not hold.

    Stated, never an empty string: "this source is not in the snapshot you are reading" is a
    fact the model must be able to report, and silence would read as "the source is there and
    says nothing"."""
    return prompt(
        "recall.snapshot.source_absent",
        source_id=str(source_id),
        snapshot=scope.moment(),
    )


__all__ = [
    "SnapshotScope",
    "out_of_scope_source",
    "scope_declaration",
]
