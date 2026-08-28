"""Mechanical event derivation (architecture.md §8).

The model declares NO transitions — every Pneuma Compiler experiment that asked the model to book
transitions was falsified. Instead the system derives events from the diff:

- an anchor present in the new repo but not the base → `claim_added`;
- an anchor in both, whose block text changed → `claim_revised`;
- a new anchor whose block carries a `supersedes` marker → `claim_superseded`, with
  `before` = the replaced claim's text and `supersedes` = its anchor (the state of one
  fact changed; see compile/supersession.py);
- deletion is blocked by the gate, so there is no `claim_removed`.

The OVERVIEW region is derived separately and deliberately NOT as claim events. Its blocks
are replaced whole on every rewrite, so an anchor diff over them would report a rewrite of
four sentences as four claims added and four vanished — a record that is arithmetically true
and materially false: nothing was added to the knowledge base and nothing was lost from it.
The region's anchors are therefore excluded from the anchor index on both sides, and a
document whose region changed emits ONE `overview_rewritten` event naming the document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..domain.ids import ANCHOR_MARK_RE, extract_anchors
from .anchor_ops import _block_span
from .documents import OVERVIEW_MARKER_RE, overview_region
from .supersession import block_supersedes

EventType = Literal[
    "claim_added", "claim_revised", "claim_superseded", "overview_rewritten"
]


@dataclass(frozen=True)
class CompileEvent:
    type: EventType
    path: str
    #: The claim's anchor — empty for `overview_rewritten`, whose unit is the document.
    anchor: str
    before: str | None  # None for claim_added; the replaced claim for claim_superseded
    after: str
    supersedes: str | None = None  # the replaced anchor, claim_superseded only


def _anchor_blocks(body: str) -> dict[str, str]:
    """anchor id → its block text (the natural block the anchor sits in).

    Overview-region anchors are excluded: the region has its own event (see the module
    docstring), and letting its throwaway ids into the diff would narrate a rewrite as a
    burst of added and vanished claims.
    """
    lines = body.split("\n")
    skip = set(extract_anchors(overview_region(body)))
    result: dict[str, str] = {}
    for i, line in enumerate(lines):
        for anchor in ANCHOR_MARK_RE.findall(line):
            if anchor in skip:
                continue
            start, end = _block_span(lines, i)
            result[anchor] = "\n".join(lines[start:end]).strip()
    return result


def _overview_display(body: str) -> str:
    """The overview region as display copy: the system's marker lines dropped.

    The markers are the machinery that makes the region addressable; the event is what the
    History timeline and the post-compile brief read. Canonical keeps the authoritative
    bytes — this is the same relationship a claim event's `after` has to its block.
    """
    lines = [
        line
        for line in overview_region(body).split("\n")
        if not OVERVIEW_MARKER_RE.match(line)
    ]
    out: list[str] = []
    for line in lines:
        if not line.strip():
            if not out or not out[-1].strip():
                continue
            out.append("")
        else:
            out.append(line)
    return "\n".join(out).strip()


def _index(files: dict[str, str]) -> dict[str, tuple[str, str]]:
    """anchor → (path, block_text) across all files."""
    out: dict[str, tuple[str, str]] = {}
    for path, body in files.items():
        for anchor, text in _anchor_blocks(body).items():
            out[anchor] = (path, text)
    return out


def derive_events(
    base_files: dict[str, str], new_files: dict[str, str]
) -> list[CompileEvent]:
    base = _index(base_files)
    new = _index(new_files)

    events: list[CompileEvent] = []
    for anchor, (path, text) in new.items():
        if anchor not in base:
            olds = block_supersedes(text)
            if olds:
                old = olds[0]
                replaced = base.get(old) or new.get(old)
                events.append(
                    CompileEvent(
                        "claim_superseded",
                        path,
                        anchor,
                        before=replaced[1] if replaced else None,
                        after=text,
                        supersedes=old,
                    )
                )
                continue
            events.append(
                CompileEvent("claim_added", path, anchor, before=None, after=text)
            )
        else:
            before_path, before_text = base[anchor]
            if before_text != text:
                events.append(
                    CompileEvent(
                        "claim_revised", path, anchor, before=before_text, after=text
                    )
                )

    # One event per document whose overview region changed — the unit is the document,
    # because the rewrite is.
    for path in sorted(set(base_files) | set(new_files)):
        was = overview_region(base_files.get(path, ""))
        now = overview_region(new_files.get(path, ""))
        if was == now:
            continue
        events.append(
            CompileEvent(
                "overview_rewritten",
                path,
                anchor="",
                before=_overview_display(base_files.get(path, "")) or None,
                after=_overview_display(new_files.get(path, "")),
            )
        )
    return events
