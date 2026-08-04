"""SkillVersion: an immutable vertical-skill asset, and the registry an application fills.

A SkillVersion is instructions + path templates + contract rules; the content hash is
system-computed for identity/versioning.

THE FRAMEWORK SHIPS NO CONTRACT. This module used to package three worked contracts for
one domain ("personal knowledge") and hand one of them to any caller who did not choose —
`load_builtin_skill()` defaulted to v1, `settings.user_schema_base_version` to v3. A
framework has no business holding an opinion about someone else's domain, and a default
that quietly supplies one is worse than no default: the resulting knowledge base looks
like it was designed for the subject when it was designed for someone else. So the
contracts moved out (to `pneuma-knowledge-strategies`, as reference starting points), and
what remains here is the mechanism: an application builds a SkillVersion and registers it
under a version string, and `load_skill_base` returns it — or fails loudly, naming the
format doc and the shipped examples.

Multiple versions coexist (milestone M5). A skill upgrade is forward-only — new compiles
use the new version; existing canonical is never re-written (invariant I2). Each version's
`content_hash` is independent and byte-stable, so the version used to compile a snapshot
can be stamped into the commit trailer as a free git audit trace.

  how to write one (format and judgement): docs/guides/compile-contract.md
  reference contracts:       packages/pneuma-knowledge-strategies/
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

# Extra write-contract clauses a SkillVersion may fold into render_system_contract. These
# are mechanism refinements (a controlled vocabulary, a presentation convention), not
# persuasion (§0 discipline 1), and they ride the byte-stable SystemMessage, so they are
# part of the version's identity.
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

    @classmethod
    def from_parts(
        cls,
        *,
        skill_id: str,
        version: str,
        instructions: str,
        path_templates: Sequence[str],
        contract_rules: Sequence[str] = (),
    ) -> SkillVersion:
        """Build a SkillVersion and compute its `content_hash` from the same four parts.

        Every application that owns a contract has to do this, and every one of them was
        hand-rolling the `compute_hash(...)` call with the arguments repeated — a shape in
        which one transposed argument yields a wrong-but-plausible provenance hash that
        nothing downstream can catch. The parts are supplied once here.
        """
        templates = list(path_templates)
        rules = tuple(contract_rules)
        return cls(
            skill_id=skill_id,
            version=version,
            instructions=instructions,
            path_templates=templates,
            contract_rules=rules,
            content_hash=cls.compute_hash(skill_id, version, instructions, templates, rules),
        )


# The registered skill bases, keyed by version string — the ONLY place a contract can come
# from. The skill BODY is a versioned asset rather than a prompt surface (it is domain
# content whose length and structure the deployment owns), so it has its own registration
# seam instead of riding the prompt catalog.
_REGISTERED_BASES: dict[str, SkillVersion] = {}


def register_skill_base(version: str, skill: SkillVersion) -> None:
    """Register (or replace) the skill base loaded for `version` — the application seam.

    Call at startup (wiring), before any compile. `load_skill_base(version)` then returns
    this SkillVersion, so a deployment ships its own full skill body (its own language, its
    own domain sections) while every manifest, trailer and `base_version` reference keeps
    naming the same version string.
    """
    _REGISTERED_BASES[version] = skill


def registered_skill_bases() -> dict[str, SkillVersion]:
    """The currently registered bases (a copy) — for wiring inspection and tests."""
    return dict(_REGISTERED_BASES)


def reset_skill_bases() -> None:
    """Drop every registered base. Tests only — the startup contract is register-once."""
    _REGISTERED_BASES.clear()


def _unregistered_message(version: str) -> str:
    """The failure a caller sees when nothing was wired — it has to be actionable.

    The old behaviour on this path was to return a packaged personal-knowledge contract,
    which is why it needs saying explicitly: not choosing is not a state this framework can
    resolve on the caller's behalf, and the message names every door out.
    """
    known = ", ".join(sorted(_REGISTERED_BASES)) or "(none)"
    subject = f"version {version!r}" if version.strip() else "an empty version string"
    return (
        f"no skill base registered for {subject}. This framework ships no domain contract: "
        "an application must build a SkillVersion and call "
        "register_skill_base(version, skill) at startup (services read the version from "
        "settings.user_schema_base_version, which has no default either).\n"
        f"  registered versions: {known}\n"
        "  how to write one (format and judgement): docs/guides/compile-contract.md\n"
        "  reference contracts to start from: packages/pneuma-knowledge-strategies/ "
        "(personal-knowledge)"
    )


def load_skill_base(version: str) -> SkillVersion:
    """The registered skill base for `version`, or a loud LookupError.

    `version` is required and must be non-blank: there is no built-in contract to fall back
    to, and inventing one would be inventing a domain for the caller.
    """
    registered = _REGISTERED_BASES.get(version)
    if registered is None:
        raise LookupError(_unregistered_message(version))
    return registered
