"""Truth-set loading: the labelled corpus that group B (admission judgement) needs.

WHY THIS IS A SEPARATE, PROTOCOL-SHAPED LAYER
---------------------------------------------
Four of the six metric groups need nothing but the artifacts. Group B — and only group B —
needs a corpus whose facts, noise and supersessions were labelled BEFORE compilation. That
labelling is a property of a corpus, not of the framework, so it enters through one adapter
type (`TruthSet`) and every future corpus implements the same shape.

A truth set is only meaningful against artifacts compiled FROM that corpus. Binding one
corpus's labels to another corpus's canonical would report ~0 recall and read as a quality
finding when it is really a mismatched input, so `TruthSet.corpus_key` exists to be checked
by the caller and `admission` reports `unavailable` rather than guessing.

Category flattening and normalization come from the package's generic matching
contract. Corpus-specific adapters only translate their assets into this shape.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .matching import (
    TRUTH_CATEGORIES,
    normalize_text,
    truth_entries,
)

from .errors import EvalInputError

_SUPERSEDED_STATUSES = frozenset({"superseded", "cancelled"})


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class TruthEntry:
    """One labelled statement that SHOULD be in canonical (or should have been, once)."""

    truth_id: str
    category: str
    value: str
    status: str | None = None
    effective_at: datetime | None = None
    source_types: tuple[str, ...] = ()

    @property
    def current(self) -> bool:
        return (self.status or "current") not in _SUPERSEDED_STATUSES


@dataclass(frozen=True)
class NegativeControl:
    """Labelled exhaust: a statement that must NOT enter canonical unguarded."""

    truth_id: str
    value: str
    reason: str = ""


@dataclass(frozen=True)
class Supersession:
    """A before→after pair: after must be present, before must not stand unguarded."""

    supersession_id: str
    before_truth_id: str
    after_truth_id: str
    effective_at: datetime | None = None


@dataclass(frozen=True)
class RetrievalCase:
    """One outcome question plus the truth ids a correct answer has to carry (group F)."""

    case_id: str
    question: str
    expected_truth_ids: tuple[str, ...]
    as_of: datetime | None = None


@dataclass(frozen=True)
class BatchWindow:
    """A corpus intake batch — the unit admission latency is measured in."""

    batch_id: str
    started_at: datetime | None
    ended_at: datetime | None

    def covers(self, moment: datetime) -> bool:
        if self.started_at is not None and moment < self.started_at:
            return False
        if self.ended_at is not None and moment > self.ended_at:
            return False
        return True


@dataclass(frozen=True)
class TruthSet:
    """A labelled corpus, adapted to one shape for group B and group F."""

    experiment_id: str
    corpus_key: str
    entries: tuple[TruthEntry, ...]
    negatives: tuple[NegativeControl, ...] = ()
    supersessions: tuple[Supersession, ...] = ()
    retrieval_cases: tuple[RetrievalCase, ...] = ()
    batches: tuple[BatchWindow, ...] = ()
    #: Normalized authored text → `content_class` ("signal" / "noise" / "ambiguous"), when the
    #: corpus labels its raw material before compilation. This is a much larger admission label
    #: set than the handful of negative controls — every authored block, not just the statements
    #: someone thought to write down as exhaust — and it is what `admission.noise_support`
    #: consumes. Empty when the corpus ships no such labels, and that metric then reports
    #: `unavailable` rather than assuming every block is signal.
    content_classes: Mapping[str, str] = field(default_factory=dict)
    origin: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entries:
            raise EvalInputError(f"truth set {self.experiment_id!r} holds no truth entries")
        ids = [entry.truth_id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise EvalInputError(f"truth set {self.experiment_id!r} has duplicate truth ids")
        known = set(ids)
        for supersession in self.supersessions:
            missing = {supersession.before_truth_id, supersession.after_truth_id} - known
            if missing:
                raise EvalInputError(
                    f"supersession {supersession.supersession_id} references unknown truth "
                    f"{sorted(missing)}"
                )
        for case in self.retrieval_cases:
            unknown = set(case.expected_truth_ids) - known
            if unknown:
                raise EvalInputError(
                    f"retrieval case {case.case_id} references unknown truth {sorted(unknown)}"
                )

    def by_id(self) -> dict[str, TruthEntry]:
        return {entry.truth_id: entry for entry in self.entries}

    def current_entries(self) -> tuple[TruthEntry, ...]:
        return tuple(entry for entry in self.entries if entry.current)

    def batch_index_for(self, moment: datetime | None) -> int | None:
        """The 0-based intake batch whose window covers `moment` (None when unknown)."""
        if moment is None or not self.batches:
            return None
        for index, window in enumerate(self.batches):
            if window.covers(moment):
                return index
        return None


# ─────────────────────────────────────────────────────────────────────────── loaders


def _entries_from_manifest(manifest: dict[str, Any]) -> tuple[TruthEntry, ...]:
    """Flatten the labelled categories via the existing evaluator's own accessor."""
    rows = truth_entries(manifest)
    return tuple(
        TruthEntry(
            truth_id=str(row["truth_id"]),
            category=str(row["category"]),
            value=str(row["value"]),
            status=(str(row["status"]) if row.get("status") is not None else None),
            effective_at=_timestamp(row.get("effective_from") or row.get("effective_at")),
            source_types=tuple(str(kind) for kind in row.get("source_types", ()) or ()),
        )
        for row in rows
    )


def _shared_sections(manifest: dict[str, Any]) -> dict[str, Any]:
    truth = manifest.get("truth") or {}
    negatives = tuple(
        NegativeControl(
            truth_id=str(row["truth_id"]),
            value=str(row["value"]),
            reason=str(row.get("reason") or ""),
        )
        for row in truth.get("negative_controls", []) or []
    )
    supersessions = tuple(
        Supersession(
            supersession_id=str(row["supersession_id"]),
            before_truth_id=str(row["before_truth_id"]),
            after_truth_id=str(row["after_truth_id"]),
            effective_at=_timestamp(row.get("effective_at")),
        )
        for row in truth.get("supersessions", []) or []
    )
    cases = tuple(
        RetrievalCase(
            case_id=str(row["case_id"]),
            question=str(row["question"]),
            expected_truth_ids=tuple(str(tid) for tid in row.get("expected_truth_ids", ()) or ()),
            as_of=_timestamp(row.get("as_of")),
        )
        for row in truth.get("retrieval_cases", []) or []
    )
    return {"negatives": negatives, "supersessions": supersessions, "retrieval_cases": cases}


def load_84d_truth_set(corpus_dir: Path | str) -> TruthSet:
    """Load a generated longitudinal corpus directory as a TruthSet.

    Reads `manifest.json` for the labels and `index.json` for the 12 weekly intake windows,
    which is what makes admission LATENCY measurable in rounds rather than only pass/fail.
    """
    corpus_dir = Path(corpus_dir)
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.is_file():
        raise EvalInputError(f"no corpus manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batches: list[BatchWindow] = []
    index_path = corpus_dir / "index.json"
    if index_path.is_file():
        for row in json.loads(index_path.read_text(encoding="utf-8")):
            batches.append(
                BatchWindow(
                    batch_id=str(row["batch_id"]),
                    started_at=_timestamp(row.get("started_at")),
                    ended_at=_timestamp(row.get("ended_at")),
                )
            )
    return TruthSet(
        experiment_id=str(manifest.get("experiment_id") or corpus_dir.name),
        corpus_key=str(manifest.get("experiment_id") or corpus_dir.name),
        entries=_entries_from_manifest(manifest),
        batches=tuple(batches),
        origin={"kind": "generated_corpus", "path": str(corpus_dir)},
        **_shared_sections(manifest),
    )


def load_frozen_truth_manifest(path: Path | str) -> TruthSet:
    """Load a frozen truth asset (the v2 shape: labels only, no intake index).

    The v2 asset carries per-entry `evidence` with an `as_of`, so effective timestamps are
    recovered from the earliest evidence date when the entry has no explicit one.
    """
    path = Path(path)
    if not path.is_file():
        raise EvalInputError(f"no truth manifest at {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = []
    for row in truth_entries(manifest):
        evidence_dates = [
            _timestamp(item.get("as_of")) for item in row.get("evidence", []) or []
        ]
        known = sorted(date for date in evidence_dates if date is not None)
        entries.append(
            TruthEntry(
                truth_id=str(row["truth_id"]),
                category=str(row["category"]),
                value=str(row["value"]),
                status=(str(row["status"]) if row.get("status") is not None else None),
                effective_at=(
                    _timestamp(row.get("effective_from"))
                    or _timestamp(row.get("effective_at"))
                    or (known[0] if known else None)
                ),
                source_types=tuple(
                    str(item.get("source_family") or "")
                    for item in row.get("evidence", []) or []
                ),
            )
        )
    return TruthSet(
        experiment_id=str(manifest.get("experiment_id") or path.stem),
        corpus_key=str(manifest.get("experiment_id") or path.stem),
        entries=tuple(entries),
        origin={"kind": "frozen_manifest", "path": str(path)},
        **_shared_sections(manifest),
    )


#: Keys that carry the human-readable body of an authored unit, in the authoring schemas seen so
#: far (meeting utterance / agenda item, document visible block, IM message, email message).
#: Matched by name rather than by family so a new source family needs no change here.
_AUTHORED_TEXT_KEYS: tuple[str, ...] = (
    "text",
    "markdown",
    "full_text",
    "full_markdown",
    "body",
    "subject",
)


def load_content_classes(root: Path | str) -> dict[str, str]:
    """Read a labelled corpus's pre-compilation `content_class` labels: text → class.

    Some corpora label every authored unit as signal / noise / ambiguous BEFORE anything is
    compiled. That is the largest admission label set such a corpus has — orders of magnitude
    bigger than its negative-control list — and it is the only way to ask "how much of canonical
    rests on material the corpus itself called exhaust?".

    Deliberately structural rather than schema-specific: walk the JSON, and every object that
    carries BOTH an `authorship.content_class` AND a text-bearing key contributes one entry. A
    corpus with a new source family needs no change here. Keyed on `normalize_text` output so the
    lookup survives whitespace and punctuation reformatting between authoring and ingest.

    Duplicate texts keep their FIRST label rather than the last: a re-labelled duplicate would
    otherwise make the result depend on filesystem order.
    """
    root = Path(root)
    if not root.exists():
        raise EvalInputError(f"no content-class corpus at {root}")
    paths = sorted(root.glob("*.json")) if root.is_dir() else [root]
    if not paths:
        raise EvalInputError(f"no authored JSON files under {root}")
    out: dict[str, str] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            authorship = node.get("authorship")
            klass = (
                authorship.get("content_class") if isinstance(authorship, dict) else None
            )
            if isinstance(klass, str) and klass:
                for key in _AUTHORED_TEXT_KEYS:
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        out.setdefault(normalize_text(value), klass)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for path in paths:
        visit(json.loads(path.read_text(encoding="utf-8")))
    if not out:
        raise EvalInputError(
            f"{root} carries no authorship.content_class labels: nothing to bind"
        )
    return out


def load_truth_set(
    path: Path | str, *, content_classes: Path | str | None = None
) -> TruthSet:
    """Load whichever truth shape `path` points at: a corpus directory or a frozen asset.

    `content_classes` optionally binds the corpus's pre-compilation signal/noise labels (see
    `load_content_classes`), which is what turns `admission.noise_support` on.
    """
    path = Path(path)
    truth = (
        load_84d_truth_set(path) if path.is_dir() else load_frozen_truth_manifest(path)
    )
    if content_classes is None:
        return truth
    labels = load_content_classes(content_classes)
    return replace(
        truth,
        content_classes=labels,
        origin={**truth.origin, "content_classes": str(content_classes)},
    )


def batch_windows_from(spans: Sequence[tuple[str, str | None, str | None]]) -> tuple[BatchWindow, ...]:
    """Build intake windows from `(batch_id, started_at, ended_at)` triples (tests/adapters)."""
    return tuple(
        BatchWindow(batch_id=batch_id, started_at=_timestamp(start), ended_at=_timestamp(end))
        for batch_id, start, end in spans
    )
