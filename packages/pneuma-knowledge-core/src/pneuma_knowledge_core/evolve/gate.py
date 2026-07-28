"""Evolve gate profile — independent of the daily compile gate (schema-evolve §2.4).

Same three structural checks as compile (anchor uniqueness / frontmatter / anchor coverage,
reused verbatim from `compile.gate`), but three checks change shape because a whole-KB
reorganization is not a forward-only single compile:

- **anchor continuity is repo-level, and never hard-rejects.** A base anchor must exist
  *somewhere* in the new repo, not at its old path (a moved claim keeps its anchor at a new
  home). An anchor that truly vanished — a merged/deleted claim — is not a violation; it is
  surfaced as a `DroppedAnchor` (with its original text) for the review page.
- **citations validate against the store for real.** Every citation newly introduced this
  reorganization is checked with `source_bounds(sid)` (block count, or None if the source
  is gone). A citation that appears VERBATIM anywhere in the base repo is grandfathered at
  the repo level — a moved claim carries its citation byte-for-byte, so it is exempt and
  never hits the store (evolve must not re-audit the whole KB on every run).
- **path ownership is against the NEW skill's templates**, passed in explicitly.

The daily compile gate is untouched; this is a separate profile that shares only the pure
structural checks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..compile.gate import (
    Violation,
    check_anchor_coverage,
    check_anchor_uniqueness,
    check_frontmatter,
)
from ..compile.patch import PatchDraft, path_allowed
from ..compile.transitions import _anchor_blocks
from ..domain.canonical import CANONICAL_CITATION_RE
from ..domain.ids import extract_anchors

SourceBounds = Callable[[str], Awaitable[int | None]]


@dataclass(frozen=True)
class DroppedAnchor:
    """A base anchor that vanished from the new repo — a claim merged/deleted away. Carries
    its original text so the review page can show what was dropped."""

    anchor: str
    old_path: str
    text: str


def _base_anchor_texts(base_bodies: dict[str, str]) -> dict[str, tuple[str, str]]:
    """anchor id → (old_path, block_text) across the whole base repo."""
    out: dict[str, tuple[str, str]] = {}
    for path, body in base_bodies.items():
        for anchor, text in _anchor_blocks(body).items():
            out.setdefault(anchor, (path, text))
    return out


def _base_citation_markers(base_bodies: dict[str, str]) -> set[str]:
    """Every citation marker string present anywhere in the base repo — the repo-level
    grandfather set (a verbatim carry-over is exempt from the store re-check)."""
    markers: set[str] = set()
    for body in base_bodies.values():
        for m in CANONICAL_CITATION_RE.finditer(body):
            markers.add(m.group(0))
    return markers


async def run_evolve_gate(
    draft: PatchDraft,
    *,
    source_bounds: SourceBounds,
    path_templates: list[str],
) -> tuple[list[Violation], list[DroppedAnchor]]:
    """Run the evolve gate over a reorganized draft.

    Returns `(violations, dropped)`: violations are hard (still-failing → the runner aborts),
    dropped anchors are informational (merged claims surfaced for review)."""
    docs = draft.documents()
    base_bodies = draft.base_bodies()
    violations: list[Violation] = []

    # 1. repo-level anchor continuity — a base anchor absent from the WHOLE new repo is a
    # dropped anchor (informational), never a violation.
    new_anchors: set[str] = set()
    for doc in docs.values():
        new_anchors.update(extract_anchors(doc.body))
    dropped: list[DroppedAnchor] = []
    for anchor, (old_path, text) in _base_anchor_texts(base_bodies).items():
        if anchor not in new_anchors:
            dropped.append(DroppedAnchor(anchor=anchor, old_path=old_path, text=text))

    # 2. citation legality against the store — only for citations NOT grandfathered at the
    # repo level (a verbatim base carry-over never touches `source_bounds`).
    grandfathered = _base_citation_markers(base_bodies)
    for path, doc in docs.items():
        for m in CANONICAL_CITATION_RE.finditer(doc.body):
            if m.group(0) in grandfathered:
                continue  # moved/unchanged citation — exempt, no store call
            sid = m.group("sid")
            start = int(m.group("start"))
            end = int(m.group("end")) if m.group("end") is not None else start
            n = await source_bounds(sid)
            if n is None:
                violations.append(
                    Violation(
                        "citation",
                        path,
                        f"citation 引用了 store 中不存在的 source_id={sid}。",
                    )
                )
                continue
            if start > end or start < 0 or end >= n:
                violations.append(
                    Violation(
                        "citation",
                        path,
                        f"citation [{sid} ¶{start}-{end}] 越界（该 source 有 {n} 个 block，"
                        f"合法区间 0..{n - 1}）。",
                    )
                )

    # 3. anchor uniqueness / frontmatter / anchor coverage — reused verbatim from compile.
    violations.extend(check_anchor_uniqueness(docs))
    violations.extend(check_frontmatter(docs))
    violations.extend(check_anchor_coverage(docs))

    # 4. path ownership — against the NEW skill's templates.
    for path in docs:
        if not path_allowed(path, path_templates):
            violations.append(
                Violation(
                    "path",
                    path,
                    f"路径不在新 skill 允许的 ownership 模板内：{', '.join(path_templates)}。",
                )
            )

    return violations, dropped
