"""What a page's bytes SAY, derived the way the write faces write them.

Claims, their words, their sources, their dated sections, the headings nobody should have
typed: every derivation here reads a committed body and returns plain values. They are shared
by the check and the lens so that "a claim", "a citation" and "a dated section" mean one
thing across both tiers — and each of them is defined in terms of the module that WRITES that
shape (`compile.anchor_ops`, `compile.documents`, `domain.canonical`), never in terms of a
second regex that agrees with it today.
"""

from __future__ import annotations

import re

from ..compile.anchor_ops import (
    DATED_SECTION_RE,
    anchored_blocks,
    block_text,
    heading_lines,
)
from ..compile.documents import strip_overview
from ..compile.overview import ANCHOR_REFERENCE_RE
from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, HTML_COMMENT_RE

#: The session signature: an optional bracketed label, then a date, then the comma that
#: starts the narration. Given verbatim by docs/design/structure-lens.md §4.2 — what a claim
#: looks like when it is a line of a session log rather than a statement about a subject.
SESSION_DATE_PREFIX_RE = re.compile(r"^\s*(【[^】]*】)?\s*\d{4}-\d{2}-\d{2}[，,]")


def claim_blocks(body: str) -> list[str]:
    """The anchored claim blocks of a body's LEDGER (the overview is not claims)."""
    return anchored_blocks(strip_overview(body))


def claim_words(block: str) -> str:
    """What a claim SAYS: its text with the system's markers and its citations removed."""
    text = block_text(block)
    text = CANONICAL_CITATION_MARKER_RE.sub("", text)
    return HTML_COMMENT_RE.sub("", text).strip()


def bare_prose(text: str) -> str:
    """Prose with its citations, its anchor references and its whitespace runs removed."""
    stripped = CANONICAL_CITATION_MARKER_RE.sub("", text)
    stripped = ANCHOR_REFERENCE_RE.sub("", stripped)
    stripped = HTML_COMMENT_RE.sub("", stripped)
    return " ".join(stripped.split())


def citation_sources(block: str) -> list[str]:
    """The distinct source ids one block cites, in first-seen order."""
    out: list[str] = []
    for match in CANONICAL_CITATION_MARKER_RE.finditer(block):
        sid = match.group("sid")
        if sid not in out:
            out.append(sid)
    return out


def dated_sections(body: str) -> list[tuple[int, str]]:
    """`(line number, date)` for every `## YYYY-MM-DD` section, in document order."""
    out: list[tuple[int, str]] = []
    for index, line in enumerate(body.split("\n"), start=1):
        match = DATED_SECTION_RE.match(line)
        if match is not None:
            out.append((index, match.group(1)))
    return out


def section_headings(body: str) -> list[tuple[int, str]]:
    """`(line number, heading text)` for every `## ` section heading, in document order."""
    out: list[tuple[int, str]] = []
    for index, line in enumerate(body.split("\n"), start=1):
        if line.startswith("## "):
            out.append((index, line[3:].strip()))
    return out


def stray_headings(body: str) -> list[tuple[int, str]]:
    """`(line number, heading text)` for every `# ` line that is not the body's first
    non-empty line — the instances of the fault the write face now refuses."""
    lines = body.split("\n")
    first = next((n for n, line in enumerate(lines, start=1) if line.strip()), 0)
    return [item for item in heading_lines(body) if item[0] != first]


def escaped_newline_count(text: str) -> int:
    """How many literal two-character `\\n` sequences the text carries."""
    return text.count("\\n")


def longest_line(text: str) -> int:
    return max((len(line) for line in text.split("\n")), default=0)


__all__ = [
    "DATED_SECTION_RE",
    "SESSION_DATE_PREFIX_RE",
    "bare_prose",
    "citation_sources",
    "claim_blocks",
    "claim_words",
    "dated_sections",
    "escaped_newline_count",
    "longest_line",
    "section_headings",
    "stray_headings",
]
