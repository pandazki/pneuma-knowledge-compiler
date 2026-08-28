"""Claim supersession: the mechanical form of "the world changed".

WHY THIS EXISTS
---------------
The two daily write tools express two things and conflate a third. `append_block` adds a
claim; `edit_claim` rewrites one in place. Neither says that a NEW claim replaces an OLD
one as the current state of the same fact — a promotion, a change of employer, a moved
deadline. Written with `edit_claim`, the old state vanishes from the readable page (it
survives only in git); written with `append_block`, two states sit side by side with no
relation, and "which one holds now" becomes a reading exercise. The compile contract used
to ask the model to "keep the old state, the time of change and the source" — prompt copy,
which the project's own discipline forbids as the only enforcement.

`supersede_claim` is the third verb. The old claim stays byte-for-byte; the new claim gets
a system-assigned anchor and carries a second HTML-comment marker naming what it replaces:

    - X 是恒印印刷对接人 [cite: s01 ¶8-9] <!-- c:a1f3 -->
    - X 自 2026-05 起任新华印务采购总监 [cite: s02 ¶3] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->

The anchor grammar (`domain.ids.ANCHOR_MARK_RE`) is untouched — the supersedes marker is a
separate comment that the anchor regex does not match, so every existing reader of anchors
keeps working and invariant I4 keeps its one parser per syntax.

WHAT IS DERIVED FROM THE MARKER
-------------------------------
- the CURRENT view of a document: its claims with no successor;
- the HISTORY of one fact: the chain root → … → head;
- an as-of answer: walk the chain by each claim's cited-source date (no new field);
- a `claim_superseded` compile event (transitions.py), so the brief narrates a state
  change rather than "one claim added".

WHAT THE GATE ENFORCES (compile.gate.check_supersession)
--------------------------------------------------------
target exists; no self-supersession; at most one successor per claim (chains are linear);
no cycles; a superseded claim is frozen (its text may not change afterwards); the
superseding claim carries new evidence (a `[cite:]` marker of its own). "Only new evidence
may supersede an old state" is thereby a write-time rejection, not a reminder.

Everything here is pure and sync.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from ..domain.ids import ANCHOR_MARK_RE, extract_anchors
from .anchor_ops import anchored_blocks

#: The supersedes marker. Deliberately NOT a variant of the anchor comment: `<!-- c:… -->`
#: stays the one and only anchor syntax; this comment names a predecessor.
SUPERSEDES_MARK_RE = re.compile(r"<!--\s*supersedes:\s*c:([0-9a-f]{4,})\s*-->")


def supersedes_marker(old_anchor: str) -> str:
    """The marker text a superseding claim carries (single spelling, written here only)."""
    return f"<!-- supersedes: c:{old_anchor} -->"


def block_anchor(block: str) -> str | None:
    """The anchor a claim block carries as its own identity: the LAST anchor mark in the
    block (the write tools put a block's anchor on its final line)."""
    marks = ANCHOR_MARK_RE.findall(block)
    return marks[-1] if marks else None


def block_supersedes(block: str) -> list[str]:
    """Every predecessor anchor a block names (the gate requires exactly one)."""
    return SUPERSEDES_MARK_RE.findall(block)


def supersessions(body: str) -> dict[str, str]:
    """new anchor → old anchor, for every superseding claim in `body`.

    A block naming several predecessors is reported under its first one here; the gate
    rejects such a block, so committed canonical never contains one.
    """
    out: dict[str, str] = {}
    for block in anchored_blocks(body):
        olds = block_supersedes(block)
        if not olds:
            continue
        new = block_anchor(block)
        if new is not None:
            out[new] = olds[0]
    return out


def superseded_index(bodies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """old anchor → (path of the successor, successor anchor), repository-wide."""
    out: dict[str, tuple[str, str]] = {}
    for path, body in bodies.items():
        for new, old in supersessions(body).items():
            out[old] = (path, new)
    return out


def current_blocks(body: str, superseded: Iterable[str]) -> list[str]:
    """The claims of `body` that hold NOW: anchored blocks with no successor anywhere.

    `superseded` is the repository-wide set of replaced anchors (`superseded_index` keys):
    a successor may live in another document (e.g. the active page superseding a claim
    archived in a frozen volume), so the current view of one page is a repo-level fact.
    """
    dead = set(superseded)
    return [b for b in anchored_blocks(body) if block_anchor(b) not in dead]


def chains(bodies: Mapping[str, str]) -> list[list[str]]:
    """Every supersession chain as an ordered anchor list, root first, head last.

    A chain root is a claim that supersedes nothing; the walk follows old → new. Cycles
    cannot occur in committed canonical (gate), but the walk still refuses to loop so a
    hand-edited repository cannot hang a reader.
    """
    successor: dict[str, str] = {}
    predecessor_of: set[str] = set()
    for body in bodies.values():
        for new, old in supersessions(body).items():
            successor[old] = new
            predecessor_of.add(new)
    result: list[list[str]] = []
    for root in sorted(a for a in successor if a not in predecessor_of):
        chain = [root]
        seen = {root}
        cursor = root
        while cursor in successor and successor[cursor] not in seen:
            cursor = successor[cursor]
            chain.append(cursor)
            seen.add(cursor)
        result.append(chain)
    return result


def block_by_anchor(bodies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """anchor → (path, block text), repository-wide — the lookup chains resolve through."""
    out: dict[str, tuple[str, str]] = {}
    for path, body in bodies.items():
        for block in anchored_blocks(body):
            anchor = block_anchor(block)
            if anchor is not None:
                out[anchor] = (path, block)
    return out


__all__ = [
    "SUPERSEDES_MARK_RE",
    "block_anchor",
    "block_by_anchor",
    "block_supersedes",
    "chains",
    "current_blocks",
    "superseded_index",
    "supersedes_marker",
    "supersessions",
]
