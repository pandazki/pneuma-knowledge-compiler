"""Mechanical event derivation (architecture.md §8).

The model declares NO transitions — every Pneuma Compiler experiment that asked the model to book
transitions was falsified. Instead the system derives events from the diff:

- an anchor present in the new repo but not the base → `claim_added`;
- an anchor in both, whose block text changed → `claim_revised`;
- deletion is blocked by the gate, so there is no `claim_removed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..domain.ids import ANCHOR_MARK_RE
from .anchor_ops import _block_span

EventType = Literal["claim_added", "claim_revised"]


@dataclass(frozen=True)
class CompileEvent:
    type: EventType
    path: str
    anchor: str
    before: str | None  # None for claim_added
    after: str


def _anchor_blocks(body: str) -> dict[str, str]:
    """anchor id → its block text (the natural block the anchor sits in)."""
    lines = body.split("\n")
    result: dict[str, str] = {}
    for i, line in enumerate(lines):
        for anchor in ANCHOR_MARK_RE.findall(line):
            start, end = _block_span(lines, i)
            result[anchor] = "\n".join(lines[start:end]).strip()
    return result


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
    return events
