"""SkillVersion: an immutable vertical-skill asset.

The built-in OPC developer strategy is an immutable, versioned asset. A SkillVersion is
instructions + path templates + contract rules; the content hash is system-computed for
identity/versioning.

Multiple built-in versions coexist (milestone M5): `load_builtin_skill(version=...)`
returns whichever packaged asset is asked for. A skill upgrade is forward-only — new
compiles use the new version; existing canonical is never re-written (invariant I2).
Each version's `content_hash` is independent and byte-stable, so the version used to
compile a snapshot can be stamped into the commit trailer as a free git audit trace.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_ASSETS = Path(__file__).resolve().parent / "assets"

# Canonical path layout for the built-in OPC developer strategy. The path ownership is
# stable across versions so an upgrade never orphans earlier anchors.
_OPC_DEVELOPER_TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "work/products/{slug}.md",
    "work/experiments/{slug}.md",
    "work/operations/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]

_SKILL_ID = "opc-developer-knowledge"

# Per-version extra write-contract clauses folded into render_system_contract. These are
# mechanism refinements (受控词表/呈现约定), not persuasion (§0 discipline 1). v1 carries
# none; v2 adds a citation-presentation rule that shapes how future compiles cite. The
# rules ride the byte-stable SystemMessage, so they are part of the version's identity.
_CITATION_GRANULARITY_RULE = (
    "每条 claim 只回链其直接依据的 source ¶ 区间；有多段独立支撑时按 ¶ 升序分别列出 "
    "`[cite: <sid> ¶a-b]`，不要合并成一个跨越无关段落的大区间。"
)
_STRENGTH_LABEL_RULE = (
    "承诺与关系类 claim 用 skill 约定的强度前缀标签（【强】/【中】/【弱】）起头，"
    "投影层据此分层呈现；标签只用这三档。"
)
# One citation marker holds exactly ONE source and ONE ¶ range. Stated because the gate
# parses citations with a fixed grammar and rejects anything it cannot fully parse: a model
# that packs several sources or several ranges into one marker (`¶1,3`, `¶0-2; s07 ¶4`)
# writes a citation the projection cannot resolve, which is how a claim ends up committed
# with no recoverable provenance at all.
_CITATION_SHAPE_RULE = (
    "一个 `[cite: …]` 标记里只能有一个 source_id 和一个 ¶ 区间。"
    "多段支撑就并列多个标记（`[cite: <sid> ¶0-2] [cite: <sid> ¶7]`），"
    "不要在同一个标记里用逗号堆多段、也不要用分号并列多个 source。"
)

_CONTRACT_RULES: dict[str, tuple[str, ...]] = {
    "v1": (),
    "v2": (_CITATION_GRANULARITY_RULE, _STRENGTH_LABEL_RULE),
    # v3 previously had NO entry, so `.get(version, ())` silently gave it zero rules — and
    # v3 is the configured default base (settings.user_schema_base_version). The citation
    # rules therefore never reached the model on the default path, while v3's body restates
    # only the strength-label convention. Carried forward explicitly, plus the shape rule.
    "v3": (_CITATION_GRANULARITY_RULE, _CITATION_SHAPE_RULE, _STRENGTH_LABEL_RULE),
}


class SkillVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str
    version: str
    instructions: str
    path_templates: list[str] = Field(default_factory=list)
    contract_rules: tuple[str, ...] = ()
    content_hash: str

    @staticmethod
    def compute_hash(
        skill_id: str,
        version: str,
        instructions: str,
        path_templates: list[str],
        contract_rules: tuple[str, ...] = (),
    ) -> str:
        h = hashlib.sha256()
        h.update(skill_id.encode("utf-8"))
        h.update(b"\x00")
        h.update(version.encode("utf-8"))
        h.update(b"\x00")
        h.update(instructions.encode("utf-8"))
        h.update(b"\x00")
        h.update("\n".join(path_templates).encode("utf-8"))
        h.update(b"\x00")
        h.update("\n".join(contract_rules).encode("utf-8"))
        return h.hexdigest()


def load_builtin_skill(version: str = "v1") -> SkillVersion:
    """Load a built-in OPC developer strategy from its packaged asset.

    `version` selects the asset (`opc_developer_<version>.md`). Versions coexist so
    forward-only upgrades can rebuild derived data without rewriting canonical history."""
    asset = _ASSETS / f"opc_developer_{version}.md"
    if not asset.is_file():
        raise ValueError(f"unknown built-in skill version: {version!r}")
    instructions = asset.read_text(encoding="utf-8")
    rules = _CONTRACT_RULES.get(version, ())
    return SkillVersion(
        skill_id=_SKILL_ID,
        version=version,
        instructions=instructions,
        path_templates=list(_OPC_DEVELOPER_TEMPLATES),
        contract_rules=rules,
        content_hash=SkillVersion.compute_hash(
            _SKILL_ID, version, instructions, _OPC_DEVELOPER_TEMPLATES, rules
        ),
    )
