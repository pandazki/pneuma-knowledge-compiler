"""Mechanical compile gate (architecture.md §8): all checks hard-reject.

Five machine checks, each returning structured violations (fed back verbatim for one
repair round by the runner):

1. anchor continuity — a base anchor must not vanish. v1 has no authorized deletion
   channel; the model may only add or revise, never remove.
2. anchor uniqueness — every anchor is unique across the whole repo.
3. citation legality — every citation INTRODUCED this round names a source in this
   compile's supplied set, with a block interval inside that source's bounds. A citation
   carried over verbatim from the base body is grandfathered (it was validated when first
   committed); a later forward-only compile that does not supply that old source must not
   retroactively reject it (M5 Path B: new source compiled while old canonical stands).
4. frontmatter completeness — pneuma_id / type / slug present.
4b. anchor coverage — every content block carries an anchor (else it is browse-visible
   canonical text that never enters the L3 claim index — an orphaned claim).
5. path ownership — every document path matches a skill path template.

The gate is the mechanism; there is no prompt asking the model to "please remember".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.canonical import CANONICAL_CITATION_RE
from ..domain.ids import extract_anchors
from ..domain.source import NormalizedSource
from .anchor_ops import missing_anchors, unanchored_blocks
from .patch import PatchDraft, path_allowed

REQUIRED_FRONTMATTER = ("pneuma_id", "type", "slug")


@dataclass(frozen=True)
class Violation:
    kind: str  # anchor_continuity | anchor_uniqueness | citation | frontmatter | path
    path: str
    detail: str

    def render(self) -> str:
        return f"[{self.kind}] {self.path}: {self.detail}"


def check_anchor_uniqueness(docs: Mapping[str, object]) -> list[Violation]:
    """Every anchor is unique across the whole repo (shared by compile + evolve gates)."""
    violations: list[Violation] = []
    seen: dict[str, str] = {}
    for path, doc in docs.items():
        for anchor in extract_anchors(doc.body):
            if anchor in seen:
                violations.append(
                    Violation(
                        "anchor_uniqueness",
                        path,
                        f"锚 c:{anchor} 重复（另见 {seen[anchor]}）；锚是全 repo 唯一身份。",
                    )
                )
            else:
                seen[anchor] = path
    return violations


def check_frontmatter(docs: Mapping[str, object]) -> list[Violation]:
    """pneuma_id / type / slug present on every document (shared by compile + evolve gates)."""
    violations: list[Violation] = []
    for path, doc in docs.items():
        for key in REQUIRED_FRONTMATTER:
            if not str(doc.frontmatter.get(key, "")).strip():
                violations.append(
                    Violation("frontmatter", path, f"frontmatter 缺少必填字段 {key}。")
                )
    return violations


def check_anchor_coverage(docs: Mapping[str, object]) -> list[Violation]:
    """Every content block carries an anchor, or it is browse-visible canonical text that
    never enters the L3 claim index (an orphaned claim). Shared by compile + evolve gates."""
    violations: list[Violation] = []
    for path, doc in docs.items():
        for orphan in unanchored_blocks(doc.body):
            preview = orphan.strip().splitlines()[0][:40] if orphan.strip() else ""
            violations.append(
                Violation(
                    "anchor_coverage",
                    path,
                    f"内容块无锚，不会进入 claim 索引：「{preview}…」。每个 claim 块都需系统锚。",
                )
            )
    return violations


def run_gate(
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    *,
    alias_map: dict[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
) -> list[Violation]:
    docs = draft.documents()
    base_bodies = draft.base_bodies()
    violations: list[Violation] = []

    # 1. anchor continuity (base anchors may not disappear; deleted docs lose all).
    new_bodies = draft.new_bodies()
    for path, base_body in base_bodies.items():
        current = new_bodies.get(path, "")
        for anchor in missing_anchors(base_body, current):
            violations.append(
                Violation(
                    "anchor_continuity",
                    path,
                    f"既有锚 c:{anchor} 在本次编译后消失（v1 无删除通道，claim 只增改不删）。",
                )
            )

    # 2. anchor uniqueness across the whole repo.
    violations.extend(check_anchor_uniqueness(docs))

    # 3. citation legality — judge only citations introduced this round (a verbatim
    # carry-over from the base body was already validated at its own commit).
    current_bounds = {str(s.raw.source_id): len(s.blocks) for s in sources}
    bounds = dict(known_source_bounds or {})
    bounds.update(current_bounds)
    # At the compile boundary the model cites short per-job handles (`sNN`); resolve each
    # to its real source id before validating (a real id is passed through). Both forms
    # are accepted — a scripted/real model may cite either.
    alias_map = alias_map or {}
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        for m in CANONICAL_CITATION_RE.finditer(doc.body):
            if known_source_bounds is None and m.group(0) in base_body:
                continue  # grandfathered: unchanged, previously-validated citation
            sid = alias_map.get(m.group("sid"), m.group("sid"))
            start = int(m.group("start"))
            end = int(m.group("end")) if m.group("end") is not None else start
            if sid not in bounds:
                violations.append(
                    Violation(
                        "citation",
                        path,
                        f"citation 引用了本次未供给的 source_id={sid}。",
                    )
                )
                continue
            n = bounds[sid]
            if start > end or start < 0 or end >= n:
                violations.append(
                    Violation(
                        "citation",
                        path,
                        f"citation [{sid} ¶{start}-{end}] 越界（该 source 有 {n} 个 block，"
                        f"合法区间 0..{n - 1}）。",
                    )
                )

    # 4. frontmatter completeness.
    violations.extend(check_frontmatter(docs))

    # 4b. anchor coverage — every content block must carry an anchor, or it is
    # browse-visible canonical text that never enters the L3 claim index (orphaned). The
    # write tools auto-anchor every block, so this is the backstop that keeps any future
    # path from committing unindexed claims.
    violations.extend(check_anchor_coverage(docs))

    # 5. path ownership.
    for path in docs:
        if not path_allowed(path, draft.path_templates):
            violations.append(
                Violation(
                    "path",
                    path,
                    f"路径不在 skill 允许的 ownership 模板内：{', '.join(draft.path_templates)}。",
                )
            )

    return violations
