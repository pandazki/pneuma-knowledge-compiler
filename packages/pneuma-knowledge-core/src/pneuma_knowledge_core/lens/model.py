"""The structure lens's report, as data — no rendering, no I/O, no model.

The types here are the whole contract between the lens and everything that reads it: the
HTTP route, the CLI, the console. `to_dict()` is that contract's wire shape, and its field
names are fixed by docs/design/structure-lens.md §3 — a reader keys on them, so they are
part of the design and not of this module's convenience.

Every value is derived. A `Report` is a function of (documents, path templates) at one ref;
nothing in it is stored, and re-reading the same ref reproduces it byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: A finding's level — what kind of wrongness it is, and therefore who answers for it.
#: `shape` is a malformed page the write mechanism now refuses; `drift` is a page falling
#: short of what its family expects, repairable in one ordinary round; `principle` is a
#: layout no single page fixes.
LEVELS: tuple[str, ...] = ("principle", "drift", "shape")

#: Who the recommended action is addressed to (§3.1). One per level, by construction.
ACTORS: tuple[str, ...] = ("owner", "steward", "mechanism")

#: level → the actor that answers for it. The pairing is a table rather than a convention,
#: so a lens cannot quietly address a shape fault to the Steward.
ACTOR_OF_LEVEL: dict[str, str] = {
    "principle": "owner",
    "drift": "steward",
    "shape": "mechanism",
}

#: The report's ordering key (§3.4): principle before drift before shape.
LEVEL_ORDER: dict[str, int] = {level: index for index, level in enumerate(LEVELS)}

#: Evidence is bounded on both axes so a finding stays readable in a terminal and in a card.
MAX_EVIDENCE = 5
MAX_EVIDENCE_CHARS = 200


@dataclass(frozen=True)
class Decision:
    """A kept decline that still applies to a finding key.

    Reserved by §3 and filled by the Steward channel that docs/design/structure-lens.md §9
    describes; this version computes reports that carry `decision=None` unless a caller
    hands one in. The type is here rather than later because the report shape is what other
    surfaces code against, and a field that appears in v2 is a breaking change to them.
    """

    reason: str
    decided_at: str = ""
    ref: str = ""

    def to_dict(self) -> dict:
        return {"reason": self.reason, "decided_at": self.decided_at, "ref": self.ref}


@dataclass(frozen=True)
class Phrase:
    """One sentence the lens has to say, as a catalog key plus the fields it substitutes.

    Unrendered on purpose (§3.2): the bytes a Steward reads in a terminal, the bytes the
    console shows and the bytes a Chinese deployment shows are three renderings of ONE key,
    so the report carries the key and everybody resolves it through `prompts.prompt()`.
    """

    key: str
    fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "fields": dict(self.fields)}


@dataclass(frozen=True)
class Finding:
    """One thing the lens saw, addressed to someone, with what to do about it."""

    key: str
    lens: str
    level: Literal["principle", "drift", "shape"]
    actor: Literal["owner", "steward", "mechanism"]
    paths: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    impact: Phrase = field(default_factory=lambda: Phrase(""))
    action: Phrase = field(default_factory=lambda: Phrase(""))
    #: 0–1, the share of the base this finding touches. It ORDERS findings within a level
    #: (§3.4) and nothing else: the score is a count of clean subjects, not a sum of weights.
    weight: float = 0.0
    decision: Decision | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "lens": self.lens,
            "level": self.level,
            "actor": self.actor,
            "paths": list(self.paths),
            "targets": list(self.targets),
            "evidence": list(self.evidence),
            "impact": self.impact.to_dict(),
            "action": self.action.to_dict(),
            "weight": self.weight,
            "decision": self.decision.to_dict() if self.decision else None,
        }


@dataclass(frozen=True)
class FamilyRow:
    """One declared family's share of the library — the balance table under the report."""

    name: str
    pages: int
    claims: int
    share: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pages": self.pages,
            "claims": self.claims,
            "share": self.share,
        }


@dataclass(frozen=True)
class Report:
    """The whole reading, at one ref."""

    ref: str = ""
    read_at: str = ""
    subjects: int = 0
    files: int = 0
    claims: int = 0
    edges: int = 0
    score: int = 100
    findings: tuple[Finding, ...] = ()
    families: tuple[FamilyRow, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "read_at": self.read_at,
            "subjects": self.subjects,
            "files": self.files,
            "claims": self.claims,
            "edges": self.edges,
            "score": self.score,
            "findings": [finding.to_dict() for finding in self.findings],
            "families": [family.to_dict() for family in self.families],
        }


__all__ = [
    "ACTORS",
    "ACTOR_OF_LEVEL",
    "LEVELS",
    "LEVEL_ORDER",
    "MAX_EVIDENCE",
    "MAX_EVIDENCE_CHARS",
    "Decision",
    "FamilyRow",
    "Finding",
    "Phrase",
    "Report",
]
