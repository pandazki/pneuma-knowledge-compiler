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

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.canonical import CANONICAL_CITATION_MARKER_RE, iter_canonical_citations
from ..domain.ids import extract_anchors
from ..domain.source import NormalizedSource
from .anchor_ops import anchored_blocks, missing_anchors, unanchored_blocks
from .patch import PatchDraft, path_allowed

REQUIRED_FRONTMATTER = ("pneuma_id", "type", "slug")

# Inter-document markdown links — the form the projection layer reads to build graph edges
# (service dataset._MD_LINK_RE). Kept identical here so the gate validates exactly what the
# graph will later try to resolve.
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _resolve_relative(from_path: str, href: str) -> str:
    """Resolve `href` against the linking document's directory (mirrors dataset._resolve_link)."""
    stack = from_path.split("/")[:-1]
    for part in href.split("#")[0].split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
        else:
            stack.append(part)
    return "/".join(stack)


@dataclass(frozen=True)
class Violation:
    kind: str  # anchor_continuity | anchor_uniqueness | citation | link | frontmatter | path
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
        for marker in CANONICAL_CITATION_MARKER_RE.finditer(doc.body):
            # Preserve the existing single-span grandfather rule: only a byte-identical
            # marker already present in this document's base body is exempt.
            grandfathered = known_source_bounds is None and marker.group(0) in base_body
            for citation in iter_canonical_citations(marker.group(0)):
                if grandfathered:
                    continue
                sid = alias_map.get(str(citation.source_id), str(citation.source_id))
                start = citation.block_start
                end = citation.block_end
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

    # 3c. PROVENANCE on newly introduced claims. The one invariant the gate never actually
    # enforced: it validated the citations that existed but never required a claim to have
    # one, so an uncited assertion committed cleanly into the only non-rebuildable layer.
    # Judged per NEW anchor (present now, absent from the base body) — claims carried over
    # from base keep whatever provenance they were committed with.
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        base_anchors = set(extract_anchors(base_body))
        for block in anchored_blocks(doc.body):
            anchors = [a for a in extract_anchors(block) if a not in base_anchors]
            if not anchors:
                continue  # pre-existing claim, or no anchor of its own
            if CANONICAL_CITATION_MARKER_RE.search(block):
                continue
            # The skill allows a second legitimate provenance: a claim derived from EXISTING
            # canonical rather than from this round's material (§8 "回链到本轮来源或既有
            # canonical"). There is no `[cite:]` form for that, so referencing the existing
            # anchor it derives from satisfies the requirement. Without this the rule would
            # be stricter than the invariant it enforces.
            if any(f"c:{a}" in block for a in base_anchors):
                continue
            preview = " ".join(block.split())[:48]
            violations.append(
                Violation(
                    "citation",
                    path,
                    f"新建的 claim 没有任何来源：「{preview}…」（锚 c:{anchors[0]}）。"
                    "本轮新增的每条 claim 都必须回链依据——要么用 `[cite: <source_id> ¶a-b]` "
                    "指向本轮素材，要么在文中引用其所依据的既有锚 `c:<id>`；"
                    "若它只是小节标签或结构行，就不要把它写成独立 claim 块。",
                )
            )

    # 3d. INTER-DOCUMENT LINK targets must exist. Markdown links are what the projection
    # layer turns into knowledge-graph edges, i.e. the hops available when direct retrieval
    # fails. A link to a path that does not exist is a dead end in that graph — and the model
    # does produce them (it links to a subject it believes ought to exist without creating
    # it). Judged only for links introduced this round; only `.md` targets are treated as
    # canonical links, so external URLs are untouched.
    known_paths = set(docs)
    for path, doc in docs.items():
        base_body = base_bodies.get(path, "")
        for m in _MD_LINK_RE.finditer(doc.body):
            href = m.group(1)
            if m.group(0) in base_body or not href.endswith(".md") or "://" in href:
                continue
            target = _resolve_relative(path, href)
            if target == path:
                violations.append(
                    Violation(
                        "link",
                        path,
                        f"链接指向了当前文档自己：`{href}`。链接只用于指向别的主体，"
                        "自指是噪声，投影层也会丢弃它。",
                    )
                )
                continue
            if target not in known_paths:
                violations.append(
                    Violation(
                        "link",
                        path,
                        f"链接目标不存在：`{href}`（解析为 `{target}`）。"
                        "要么先用 create_document 建立该主体文档，要么不要写这个链接——"
                        "死链在知识图谱里是断头路。",
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
