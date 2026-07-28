"""PatchDraft: in-memory compile staging area.

A base snapshot file table + accumulated edit ops → a produced files dict, committed
atomically by the runner. Every edit op is claim-level (architecture.md §8): there is
NO whole-file rewrite operation — the model cannot replace a document body wholesale,
so it cannot drop a claim anchor by transcription. Anchors and document ids are all
system-assigned (discipline 1: mechanism over persuasion).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..domain.canonical import CanonicalDocument
from ..domain.ids import DocumentId
from .anchor_ops import (
    AnchorToolError,
    append_block_text,
    assign_document_anchors,
    edit_claim_text,
    insert_block_verbatim,
    remove_claim_block,
)
from .documents import render_document

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"


def _template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{slug\})", template)
    body = "".join(_SLUG if p == "{slug}" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def path_allowed(path: str, path_templates: list[str]) -> bool:
    """True iff `path` matches one of the skill's path templates (path ownership)."""
    return any(_template_regex(t).match(path) for t in path_templates)


def _assign_document_id(path: str) -> DocumentId:
    return DocumentId(hashlib.sha256(f"doc:{path}".encode("utf-8")).hexdigest()[:12])


@dataclass
class DraftDoc:
    path: str
    pneuma_id: DocumentId
    frontmatter: dict
    body: str


@dataclass
class PatchDraft:
    """Working copy of the canonical file table plus claim-level mutations."""

    path_templates: list[str]
    _base: dict[str, DraftDoc] = field(default_factory=dict)
    _working: dict[str, DraftDoc] = field(default_factory=dict)

    @classmethod
    def from_canonical(
        cls, docs: list[CanonicalDocument], path_templates: list[str]
    ) -> "PatchDraft":
        base = {
            d.path: DraftDoc(
                path=d.path,
                pneuma_id=d.pneuma_id,
                frontmatter=dict(d.frontmatter),
                body=d.body,
            )
            for d in docs
        }
        working = {
            p: DraftDoc(d.path, d.pneuma_id, dict(d.frontmatter), d.body)
            for p, d in base.items()
        }
        return cls(path_templates=list(path_templates), _base=base, _working=working)

    # --- read -----------------------------------------------------------------

    def list_paths(self) -> list[str]:
        return sorted(self._working)

    def read(self, path: str) -> DraftDoc:
        doc = self._working.get(path)
        if doc is None:
            raise AnchorToolError(f"read_document 被拒绝：文档 {path} 不存在。")
        return doc

    # --- claim-level mutations ------------------------------------------------

    def create_document(self, path: str, frontmatter: dict, body: str) -> DraftDoc:
        if not path_allowed(path, self.path_templates):
            raise AnchorToolError(
                f"create_document 被拒绝：路径 {path} 不在 skill 允许的 ownership 模板内。"
                f"允许模板：{', '.join(self.path_templates)}。"
            )
        if path in self._working:
            raise AnchorToolError(
                f"create_document 被拒绝：文档 {path} 已存在，改写既有 claim 用 edit_claim，"
                "新增 claim 用 append_block。"
            )
        pneuma_id = _assign_document_id(path)
        anchored = assign_document_anchors(body, path)
        fm = dict(frontmatter)
        fm["pneuma_id"] = str(pneuma_id)
        doc = DraftDoc(path=path, pneuma_id=pneuma_id, frontmatter=fm, body=anchored)
        self._working[path] = doc
        return doc

    def edit_claim(self, path: str, anchor_id: str, new_text: str) -> DraftDoc:
        doc = self.read(path)
        doc.body = edit_claim_text(doc.body, anchor_id, new_text)
        return doc

    def append_block(self, path: str, heading: str, text: str) -> DraftDoc:
        doc = self.read(path)
        doc.body = append_block_text(doc.body, heading, text, document_path=path)
        return doc

    # --- evolve-only merge channel (move / delete) ----------------------------
    # Only the evolve tool face registers these; the daily compile `_build_tools` never
    # exposes them, so compile keeps its zero-deletion discipline byte-for-byte.

    def move_claim(
        self, from_path: str, anchor_id: str, to_path: str, heading: str
    ) -> DraftDoc:
        """Move a whole anchored claim block from `from_path` to the end of `to_path`'s
        `heading` section — VERBATIM, anchor unchanged. The block is removed from the source
        (a re-section within the same document is allowed). The target must already exist;
        the model must `create_document` it first."""
        src = self.read(from_path)  # refuses if source missing / anchor missing
        if to_path not in self._working:
            raise AnchorToolError(
                f"move_claim 被拒绝：目标文档 {to_path} 不存在，请先 create_document 再搬移。"
            )
        block, remaining = remove_claim_block(src.body, anchor_id)
        if from_path == to_path:
            # Same-document re-section: remove then re-insert on the one working body.
            src.body = insert_block_verbatim(remaining, heading, block)
            return src
        src.body = remaining
        dst = self._working[to_path]
        dst.body = insert_block_verbatim(dst.body, heading, block)
        return dst

    def delete_claim(self, path: str, anchor_id: str) -> DraftDoc:
        """Remove a whole anchored claim block (the evolve-only merge outcome). The anchor
        disappears — `run_evolve_gate` surfaces it in the dropped-anchors list rather than
        rejecting it (a redundant claim merged away)."""
        doc = self.read(path)
        _, doc.body = remove_claim_block(doc.body, anchor_id)
        return doc

    # --- outputs --------------------------------------------------------------

    def base_bodies(self) -> dict[str, str]:
        return {p: d.body for p, d in self._base.items()}

    def new_bodies(self) -> dict[str, str]:
        return {p: d.body for p, d in self._working.items()}

    def documents(self) -> dict[str, DraftDoc]:
        return dict(self._working)

    def to_files(self) -> dict[str, str]:
        """path → serialized markdown file (frontmatter fence + body)."""
        return {
            p: render_document(d.frontmatter, d.body) for p, d in self._working.items()
        }

    def is_dirty(self) -> bool:
        return self.new_bodies() != self.base_bodies() or set(self._working) != set(
            self._base
        )
