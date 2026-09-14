"""The reading: the library along six dimensions, at one ref, against the previous one (§4).

`build_reading` is pure and sync — documents, templates and (optionally) the kept consultation
records in, a `LensReading` out. It calls no port, reads no clock of its own beyond the
`read_at` a caller hands it, and runs no model, so the reading a route serves is the reading a
CLI prints and the reading a test asserts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..prompts import prompt
from ..shape.phrase import Phrase
from ..shape.view import build_view, judged_documents
from .dimensions import Consultation, Observation, read_dimensions
from .model import DIMENSION_IDS, Dimension, LensReading, Metric


def build_reading(
    documents: Sequence[object] | Mapping[str, object],
    path_templates: Sequence[str],
    *,
    ref: str = "",
    read_at: str = "",
    previous: tuple[Sequence[object] | Mapping[str, object], str] | None = None,
    consultations: Sequence[Consultation] | None = None,
    written_on: Mapping[str, str] | None = None,
) -> LensReading:
    """The whole reading: base counts, the six dimensions, and their movement.

    `previous` is `(documents, ref)` of an earlier reading — the previous canonical commit by
    default, any ref or frozen snapshot on request. It is read with the SAME dimension
    functions and with no consultations and no write dates of its own: what a trend compares
    has to be the same measurement taken twice, and a metric whose substrate was supplied on
    one side only would report a movement that is a change of instrument.

    `consultations` is the use side (`demand_supply`); `written_on` maps a subject's path to
    the ISO date it was last written (the service reads it off git). Without either, the
    metrics that need them are null and say so.
    """
    judged, known = judged_documents(documents)
    view = build_view(judged, path_templates, known_paths=known)
    observations = read_dimensions(
        view, consultations=consultations, written_on=written_on, read_at=read_at
    )
    before: dict[str, Observation] = {}
    previous_ref = ""
    if previous is not None:
        previous_documents, previous_ref = previous
        previous_judged, previous_known = judged_documents(previous_documents)
        before = {
            observation.id: observation
            for observation in read_dimensions(
                build_view(
                    previous_judged, path_templates, known_paths=previous_known
                )
            )
        }
    return LensReading(
        ref=ref,
        read_at=read_at,
        previous_ref=previous_ref,
        subjects=len(view.subjects),
        files=len(judged),
        claims=view.total_claims,
        edges=len(view.edges),
        dimensions=tuple(
            _dimension(observation, before.get(observation.id))
            for observation in observations
        ),
    )


def _dimension(observation: Observation, before: Observation | None) -> Dimension:
    return Dimension(
        id=observation.id,
        band=observation.band,
        statement=Phrase(
            f"lens.{observation.id}.{observation.band}.statement", observation.fields
        ),
        direction=Phrase(
            f"lens.{observation.id}.{observation.band}.direction", observation.fields
        ),
        metrics=tuple(
            _metric(name, value, (before.metrics if before else {}).get(name))
            for name, value in observation.metrics.items()
        ),
        evidence=observation.evidence,
        previous_band=before.band if before is not None else None,
    )


def _metric(
    name: str, value: float | int | None, previous: float | int | None
) -> Metric:
    """One metric with its movement. A delta needs both numbers: a metric that was not read
    on one side moved by an unknown amount, which is null and not zero."""
    delta = None
    if value is not None and previous is not None:
        delta = round(value - previous, 4)
    return Metric(name=name, value=value, previous=previous, delta=delta)


def dimension_of(reading: LensReading, dimension_id: str) -> Dimension | None:
    """One dimension of a reading, by id."""
    return next((d for d in reading.dimensions if d.id == dimension_id), None)


def render_statement(dimension: Dimension) -> str:
    """What this dimension sees, as the reader's language renders it."""
    return prompt(dimension.statement.key, **dimension.statement.fields)


def render_direction(dimension: Dimension) -> str:
    """What it implies — the lever, never a page — in the same language."""
    return prompt(dimension.direction.key, **dimension.direction.fields)


__all__ = [
    "DIMENSION_IDS",
    "build_reading",
    "dimension_of",
    "render_direction",
    "render_statement",
]
