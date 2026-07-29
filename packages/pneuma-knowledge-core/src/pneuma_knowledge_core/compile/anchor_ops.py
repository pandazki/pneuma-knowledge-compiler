"""Claim-level write mechanism: anchor preflight + surgical edit primitives.

Ported from Pneuma Compiler's `skill-refactor/tools/anchor_tools.py` (11-test regression suite).
Design stance (architecture.md §0 discipline 1 — mechanism, not persuasion):

- The disease = graph-level data model (a claim anchor IS its node id) crossed with a
  file-level write API (whole-file replace). The model kept dropping anchors.
- The cure = drop the write unit to the claim block and turn anchor-loss from a
  round-level gate penalty into an immediate write-time refusal. The model no longer
  needs to "remember to copy anchors" — a write that drops one cannot land.

All functions here are pure. Anchor syntax is shared with the library
(`domain.ids.ANCHOR_MARK_RE`).

Deviations from the Pneuma Compiler source (see M3a report):
- import ANCHOR_MARK_RE / extract_anchors from `..domain.ids`;
- dropped `anchor_preflight_error` (write_file refusal message — v1 exposes no
  whole-file write tool) and `allowed_removals_from_sidecar` (sidecar transition
  parsing — v1 declares no transition sidecar; deletion has no authorized channel and
  is rejected wholesale by the gate). This also drops the `yaml` import, keeping core's
  dependency surface at pydantic + langchain-core.
- added `assign_document_anchors` (new, not ported): whole-document anchoring for the
  `create_document` path, built on the ported block primitives.
"""

from __future__ import annotations

import hashlib
import re

from ..domain.canonical import normalize_canonical_citation_markers
from ..domain.ids import ANCHOR_MARK_RE, extract_anchors
from ..prompts import prompt


class AnchorToolError(ValueError):
    """Model-readable operation refusal. The message is returned verbatim to the
    agent, written as an actionable instruction."""


_REPEATED_HEADING_MARKER_RE = re.compile(
    r"^(?P<prefix>[ \t]*#{1,6})[ \t]+(?:#{1,6}[ \t]+)+"
)
_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")


def normalize_repeated_heading_markers(document: str) -> tuple[str, int]:
    """Repair compounded Markdown syntax without touching claims or anchors.

    ``## ## Action items`` is the historical result of treating a model-supplied
    ``"## Action items"`` section argument as plain title text. Keep the actual leading
    heading level and remove only the repeated marker runs after it. Returns the
    rewritten document and replacement count for migration reporting.
    """
    output: list[str] = []
    changes = 0
    fence_character: str | None = None
    fence_length = 0
    for line in document.splitlines(keepends=True):
        fence = _FENCE_RE.match(line)
        if fence is not None:
            marker = fence.group("fence")
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            output.append(line)
            continue
        if fence_character is None:
            line, count = _REPEATED_HEADING_MARKER_RE.subn(
                r"\g<prefix> ", line, count=1
            )
            changes += count
        output.append(line)
    return "".join(output), changes


# ---------------------------------------------------------------- preflight


def missing_anchors(
    old_text: str, new_text: str, *, allowed_removals: set[str] | None = None
) -> list[str]:
    """Anchors present in old, absent from new, and not authorized for removal
    (write-time check; empty list = allow)."""
    allowed = allowed_removals or set()
    new_set = set(extract_anchors(new_text))
    seen: set[str] = set()
    result: list[str] = []
    for anchor in extract_anchors(old_text):
        if anchor in new_set or anchor in allowed or anchor in seen:
            continue
        seen.add(anchor)
        result.append(anchor)
    return result


# ---------------------------------------------------------------- edit_claim


_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _block_span(lines: list[str], anchor_line: int) -> tuple[int, int]:
    """The natural block [start, end) that the anchor at `anchor_line` belongs to.

    Aligned with the patch-format claim-block rule: list items are each independent
    (adjacent bullets are not one block); the anchor sits on the block's last line so
    the block runs up to the anchor line; a paragraph block extends upward to a
    blank/heading/list boundary; a multi-line list item's continuation lines fold up to
    their bullet line.
    """
    end = anchor_line + 1
    if _LIST_ITEM_RE.match(lines[anchor_line]):
        return anchor_line, end
    start = anchor_line
    while start > 0:
        prev = lines[start - 1]
        if not prev.strip() or _HEADING_RE.match(prev):
            break
        start -= 1
        if _LIST_ITEM_RE.match(prev):
            break
    return start, end


def edit_claim_text(doc_text: str, anchor_id: str, new_block: str) -> str:
    """Replace the natural block holding `anchor_id` with `new_block`, mechanically
    guaranteeing the anchor is preserved.

    - a `new_block` without an anchor gets the original one restored (no transcription);
    - a `new_block` carrying a different anchor (moving/minting identity) → refused;
    - an unknown anchor → refused, listing the document's existing anchors.
    """
    anchor_id = anchor_id.removeprefix("c-")
    lines = doc_text.split("\n")
    anchor_lines = [
        i
        for i, line in enumerate(lines)
        if any(m == anchor_id for m in ANCHOR_MARK_RE.findall(line))
    ]
    if not anchor_lines:
        existing = ", ".join(extract_anchors(doc_text)) or prompt("compile.anchor.none")
        raise AnchorToolError(
            prompt(
                "compile.anchor.edit_unknown_anchor",
                anchor_id=anchor_id,
                existing=existing,
            )
        )
    if len(anchor_lines) > 1:
        raise AnchorToolError(
            prompt("compile.anchor.edit_duplicate_anchor", anchor_id=anchor_id)
        )

    block = normalize_canonical_citation_markers(new_block.strip("\n"))[0]
    block_anchors = extract_anchors(block)
    if any(a != anchor_id for a in block_anchors):
        raise AnchorToolError(
            prompt("compile.anchor.edit_extra_anchor")
        )
    if not block_anchors:
        block_lines = block.split("\n")
        block_lines[-1] = f"{block_lines[-1].rstrip()} <!-- c:{anchor_id} -->"
        block = "\n".join(block_lines)

    start, end = _block_span(lines, anchor_lines[0])
    return "\n".join(lines[:start] + block.split("\n") + lines[end:])


# ---------------------------------------------------------------- append_block


def assign_anchor(document_path: str, block: str, existing: set[str]) -> str:
    """Content-addressed anchor assignment: deterministic, machine-generated; the
    model never mints an id."""
    seed = 0
    while True:
        digest = hashlib.sha256(
            f"{document_path}\n{block.strip()}\n{seed}".encode("utf-8")
        ).hexdigest()[:8]
        if digest not in existing:
            return digest
        seed += 1


def _heading_title(heading: str) -> str:
    """Normalize a model-supplied section name to plain heading text.

    The tool owns Markdown syntax and always creates a level-two section. Models
    nevertheless sometimes pass ``"## Action items"`` after reading a rendered document;
    treating those hashes as title text produces ``"## ## Action items"`` and compounds on
    every incremental compile. Strip any repeated leading Markdown heading markers at
    the write boundary instead.
    """
    title = heading.strip()
    while True:
        marker = re.match(r"^#{1,6}(?:\s+|$)", title)
        if marker is None:
            break
        title = title[marker.end() :].strip()
    if not title:
        raise AnchorToolError(prompt("compile.anchor.append_empty_heading"))
    return title


def _append_to_section(doc_text: str, heading: str, block: str) -> str:
    """Insert an already-finalized `block` string at the end of the named section, creating
    the section at end-of-file when absent.

    The block is placed verbatim (no anchoring): callers finalize the block first —
    `append_block_text` anchors a new claim, `insert_block_verbatim` carries a moved claim's
    existing anchor. Shared by both so the section-placement rule is written once."""
    lines = doc_text.split("\n")
    target = _heading_title(heading)
    heading_line = -1
    heading_level = 0
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and match.group(2) == target:
            heading_line = i
            heading_level = len(match.group(1))
            break

    if heading_line < 0:
        suffix = [""] if lines and lines[-1].strip() else []
        return "\n".join(lines + suffix + [f"## {target}", "", block, ""])

    insert_at = len(lines)
    for i in range(heading_line + 1, len(lines)):
        match = _HEADING_RE.match(lines[i])
        if match and len(match.group(1)) <= heading_level:
            insert_at = i
            break
    while insert_at > heading_line + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    return "\n".join(lines[:insert_at] + ["", block] + lines[insert_at:])


def append_block_text(
    doc_text: str, heading: str, block: str, *, document_path: str = ""
) -> str:
    """Append a new claim block at the end of the named section; create the section at
    end-of-file if absent.

    - `block` must not carry an anchor: the new claim's anchor is assigned by
      `assign_anchor`;
    - the assigned anchor is guaranteed not to collide with the document's existing ones.
    """
    block = block.strip("\n")
    if extract_anchors(block):
        raise AnchorToolError(
            prompt("compile.anchor.append_anchor_present")
        )
    # Anchor EVERY block in the appended text (it may be several paragraphs / list items),
    # not just the last line — otherwise the earlier ones are orphaned: visible in the doc
    # but never indexed as claims. Seed with the doc's anchors to avoid collisions.
    block = assign_document_anchors(
        block, document_path, existing=set(extract_anchors(doc_text))
    )
    return _append_to_section(doc_text, heading, block)


# ------------------------------------------------------- move / delete (evolve only)


def remove_claim_block(doc_text: str, anchor_id: str) -> tuple[str, str]:
    """Locate the natural block holding `anchor_id` and split it out.

    Returns `(block_text, remaining_doc)`: `block_text` is the block VERBATIM — its anchor
    comment included, byte-for-byte — so a caller can re-insert it elsewhere with identity
    intact; `remaining_doc` is the document with that block removed. Same guard as
    `edit_claim_text`: an absent or duplicated anchor is refused (the model must fix the
    duplicate first). Backs the evolve-only move/delete channel — no daily compile tool
    exposes it."""
    anchor_id = anchor_id.removeprefix("c-")
    lines = doc_text.split("\n")
    anchor_lines = [
        i
        for i, line in enumerate(lines)
        if any(m == anchor_id for m in ANCHOR_MARK_RE.findall(line))
    ]
    if not anchor_lines:
        existing = ", ".join(extract_anchors(doc_text)) or prompt("compile.anchor.none")
        raise AnchorToolError(
            prompt(
                "compile.anchor.move_unknown_anchor",
                anchor_id=anchor_id,
                existing=existing,
            )
        )
    if len(anchor_lines) > 1:
        raise AnchorToolError(
            prompt("compile.anchor.move_duplicate_anchor", anchor_id=anchor_id)
        )
    start, end = _block_span(lines, anchor_lines[0])
    block = "\n".join(lines[start:end])
    remaining = "\n".join(lines[:start] + lines[end:])
    return block, remaining


def insert_block_verbatim(doc_text: str, heading: str, block: str) -> str:
    """Insert a PRE-ANCHORED block (a moved claim) verbatim at the section end.

    Unlike `append_block_text` this mints no anchor — a moved claim keeps its own identity
    so L3 projection / events / git blame stay continuous. Refused if the block carries no
    anchor (it is not an existing claim)."""
    block = block.strip("\n")
    if not extract_anchors(block):
        raise AnchorToolError(
            prompt("compile.anchor.move_missing_anchor")
        )
    return _append_to_section(doc_text, heading, block)


# ---------------------------------------------------------- whole-doc anchoring


def _iter_content_blocks(lines: list[str]):
    """Yield (block_lines, start_index) for every claim block: a list item is one line, a
    paragraph runs until a blank line / heading / next list item. Headings and blanks are
    not blocks. One shared walker so anchoring and the gate's orphan check agree exactly."""
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or _HEADING_RE.match(line):
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        if not _LIST_ITEM_RE.match(line):
            while j < n:
                nxt = lines[j]
                if not nxt.strip() or _HEADING_RE.match(nxt) or _LIST_ITEM_RE.match(nxt):
                    break
                block_lines.append(nxt)
                j += 1
        yield block_lines, i
        i = j


def assign_document_anchors(
    body: str, document_path: str, *, existing: set[str] | None = None
) -> str:
    """Assign a system anchor to EVERY claim block in `body` that lacks one — so a
    multi-block write leaves no orphan (browse-visible but never indexed as a claim).

    Backs both `create_document` (whole model-supplied body) and `append_block` (the
    appended text, which may itself be several blocks). A claim block is a list item or a
    paragraph run; headings and blank lines are skipped. Already-anchored blocks are left
    untouched. `existing` seeds the anchor set with ids the surrounding document already
    holds, so appended-block anchors never collide with the doc's."""
    body = normalize_canonical_citation_markers(body)[0]
    lines = body.split("\n")
    seen = set(existing or ()) | set(extract_anchors(body))
    for block_lines, start in _iter_content_blocks(lines):
        if extract_anchors("\n".join(block_lines)):
            continue
        anchor = assign_anchor(document_path, "\n".join(block_lines), seen)
        seen.add(anchor)
        last = start + len(block_lines) - 1  # appending to a line never shifts indices
        lines[last] = f"{lines[last].rstrip()} <!-- c:{anchor} -->"
    return "\n".join(lines)


def unanchored_blocks(body: str) -> list[str]:
    """Content blocks in `body` carrying no anchor — the gate's orphan backstop. Empty
    when every claim block is anchored (the post-condition assign_document_anchors gives)."""
    lines = body.split("\n")
    return [
        text
        for block_lines, _ in _iter_content_blocks(lines)
        if not extract_anchors(text := "\n".join(block_lines))
    ]


def anchored_blocks(body: str) -> list[str]:
    """Content blocks in `body` that DO carry an anchor — i.e. the claims.

    Complement of `unanchored_blocks`, over the same block segmentation, so the gate can
    judge a claim as a whole (its text plus its anchor plus its citations) rather than
    line by line.
    """
    lines = body.split("\n")
    return [
        text
        for block_lines, _ in _iter_content_blocks(lines)
        if extract_anchors(text := "\n".join(block_lines))
    ]
