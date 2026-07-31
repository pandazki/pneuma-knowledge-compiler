"""SkillVersion: an immutable vertical-skill asset.

The built-in personal-knowledge strategy is an immutable, versioned fallback. A SkillVersion is
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

# Canonical path layout for the built-in personal-knowledge strategy. Path ownership is
# stable across versions so an upgrade never orphans earlier anchors.
_PERSONAL_KNOWLEDGE_TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "work/products/{slug}.md",
    "work/experiments/{slug}.md",
    "work/operations/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]

_SKILL_ID = "personal-knowledge"

# Per-version extra write-contract clauses folded into render_system_contract. These are
# mechanism refinements (a controlled vocabulary, a presentation convention), not
# persuasion (§0 discipline 1). v1 carries none; v2 adds a citation-presentation rule that
# shapes how future compiles cite. The rules ride the byte-stable SystemMessage, so they
# are part of the version's identity.
#
# The values are prompt-catalog KEYS, not sentences: `render_system_contract` resolves each
# through `resolve_or_verbatim`, so a deployment rewrites a clause through the same seam as
# every other surface, while a business-authored SkillVersion may still store a literal
# sentence (it resolves to itself). `compute_hash` therefore hashes the key string — the
# prose the model actually saw is pinned by the overlay hash in the commit trailer, giving a
# two-axis identity (skill hash × overlay hash).
CITATION_GRANULARITY_RULE = "contract.rule.citation_granularity"
STRENGTH_LABEL_RULE = "contract.rule.strength_labels"
# One citation marker holds exactly ONE source and ONE ¶ range. Stated because the gate
# parses citations with a fixed grammar and rejects anything it cannot fully parse: a model
# that packs several sources or several ranges into one marker (`¶1,3`, `¶0-2; s07 ¶4`)
# writes a citation the projection cannot resolve, which is how a claim ends up committed
# with no recoverable provenance at all.
CITATION_SHAPE_RULE = "contract.rule.citation_shape"

_CITATION_GRANULARITY_RULE = CITATION_GRANULARITY_RULE
_STRENGTH_LABEL_RULE = STRENGTH_LABEL_RULE
_CITATION_SHAPE_RULE = CITATION_SHAPE_RULE

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


# Business-registered skill bases, keyed by version string. The skill BODY is a versioned
# asset rather than a prompt surface — it is domain content whose length and structure the
# deployment owns — so it has its own registration seam instead of riding the prompt
# catalog. Registering `v3` replaces the packaged v3 body everywhere `base_version` points
# at it, and `content_hash` keeps working unchanged (it is computed from whatever
# instructions are loaded).
_REGISTERED_BASES: dict[str, SkillVersion] = {}


def register_skill_base(version: str, skill: SkillVersion) -> None:
    """Register (or replace) the skill base loaded for `version` — the business seam.

    Call at startup (wiring), before any compile. `load_builtin_skill(version)` then returns
    this SkillVersion instead of reading the packaged asset, so a deployment can ship its
    own full skill body (its own language, its own domain sections) while every manifest,
    trailer and `base_version` reference keeps naming the same version string.
    """
    _REGISTERED_BASES[version] = skill


def registered_skill_bases() -> dict[str, SkillVersion]:
    """The currently registered bases (a copy) — for wiring inspection and tests."""
    return dict(_REGISTERED_BASES)


def reset_skill_bases() -> None:
    """Drop every registered base. Tests only — the startup contract is register-once."""
    _REGISTERED_BASES.clear()


def load_builtin_skill(version: str = "v1") -> SkillVersion:
    """Load a skill base: a business-registered one if present, else the packaged asset.

    `version` selects the asset (`personal_knowledge_<version>.md`). Versions coexist so
    forward-only upgrades can rebuild derived data without rewriting canonical history."""
    registered = _REGISTERED_BASES.get(version)
    if registered is not None:
        return registered
    asset = _ASSETS / f"personal_knowledge_{version}.md"
    if not asset.is_file():
        raise ValueError(f"unknown built-in skill version: {version!r}")
    instructions = asset.read_text(encoding="utf-8")
    rules = _CONTRACT_RULES.get(version, ())
    return SkillVersion(
        skill_id=_SKILL_ID,
        version=version,
        instructions=instructions,
        path_templates=list(_PERSONAL_KNOWLEDGE_TEMPLATES),
        contract_rules=rules,
        content_hash=SkillVersion.compute_hash(
            _SKILL_ID, version, instructions, _PERSONAL_KNOWLEDGE_TEMPLATES, rules
        ),
    )
