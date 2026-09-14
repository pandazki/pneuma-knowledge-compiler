"""The lens reading, as data — no rendering, no I/O, no model.

The types here are the whole contract between the lens and everything that reads it: the HTTP
route, the CLI, the console. `to_dict()` is that contract's wire shape, and its field names
are fixed by docs/design/structure-lens.md §5.2 — a reader keys on them, so they are part of
the design and not of this module's convenience.

The lens does not list pages, and there is no score. Six dimensions, each with a band chosen
by named thresholds, one statement, one direction, its metrics and their movement since the
previous reading. Every value is derived: a `LensReading` is a function of (documents, path
templates, the kept consultation records) at one ref.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..shape.phrase import Phrase

#: The six dimensions, in the order a reading presents them (§4.2).
DIMENSION_IDS: tuple[str, ...] = (
    "walkability",
    "shape",
    "knowledge_vs_log",
    "liveness",
    "type_structure",
    "demand_supply",
)

#: dimension → its bands, best-read first. A band is a WORD the Owner reads, so the set is
#: closed and enumerable: a test asserts that each of them carries a statement and a direction
#: in both shipped packs, and a dimension cannot ship a band nobody has written a sentence for.
DIMENSION_BANDS: dict[str, tuple[str, ...]] = {
    "walkability": ("open", "thin", "broken"),
    "shape": ("even", "leaning", "collapsing"),
    "knowledge_vs_log": ("knowledge", "mixed", "log"),
    "liveness": ("living", "settling", "still"),
    "type_structure": ("aligned", "strained", "misfiled"),
    # `unread` is not a worse `skewed`: it is the honest answer when nobody has asked this
    # library anything, and there is nothing to compare its holdings against.
    "demand_supply": ("matched", "skewed", "unread"),
}


@dataclass(frozen=True)
class Metric:
    """One number a dimension rests on, and how it moved.

    `previous` and `delta` are null when there is no previous reading — and also when the
    metric needs a substrate this reading was not given (the dates behind `liveness`, the
    consultations behind `demand_supply`). A null is an honest "not read", never a zero: a
    library with no write history is not a library written today.
    """

    name: str
    value: float | int | None = None
    previous: float | int | None = None
    delta: float | int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "previous": self.previous,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class Dimension:
    """One of the six readings: what it sees, what that implies, and how it moved."""

    id: str
    band: str
    statement: Phrase = field(default_factory=lambda: Phrase(""))
    direction: Phrase = field(default_factory=lambda: Phrase(""))
    metrics: tuple[Metric, ...] = ()
    evidence: tuple[str, ...] = ()
    #: The band the previous reading stood in, or null when there is none. §4.3 asks a
    #: dimension to say whether the band CHANGED; the metrics carry their own movement, and
    #: this is the one fact about movement that is not a number.
    previous_band: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "band": self.band,
            "previous_band": self.previous_band,
            "statement": self.statement.to_dict(),
            "direction": self.direction.to_dict(),
            "metrics": [metric.to_dict() for metric in self.metrics],
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class LensReading:
    """The whole reading, at one ref."""

    ref: str = ""
    read_at: str = ""
    previous_ref: str = ""
    subjects: int = 0
    files: int = 0
    claims: int = 0
    edges: int = 0
    dimensions: tuple[Dimension, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "read_at": self.read_at,
            "previous_ref": self.previous_ref,
            "subjects": self.subjects,
            "files": self.files,
            "claims": self.claims,
            "edges": self.edges,
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
        }


__all__ = [
    "DIMENSION_BANDS",
    "DIMENSION_IDS",
    "Dimension",
    "LensReading",
    "Metric",
]
