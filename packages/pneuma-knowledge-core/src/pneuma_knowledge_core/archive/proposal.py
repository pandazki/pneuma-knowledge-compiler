"""The archive PROPOSAL: what follows, mechanically, from what the Owner named.

Knowledge hangs together. A document cites sources; a source is cited by documents. So
"archive Aurora" is never one move: the sources only Aurora cited stop being worth
indexing, and a document that cited nothing but those sources is about a subject that just
left. The Owner names the seeds, this module computes the closure, and the console shows
the whole set with a reason per item — nothing moves until the Owner confirms that exact
set against that exact library state (docs/design/archive.md §5).

The rules, and they are the whole judgement:

- **From a document.** Every source its claims cite is a candidate. A source no live
  document OUTSIDE the selected set still cites is selected (`orphaned`); one some other
  live document still cites is listed and NOT selected (`still_cited`), naming those
  documents in `cited_by_live`.
- **From a source.** Every live document citing it is a candidate, carrying its
  **dependence**: ledger claims citing selected sources over all its ledger claims. At
  `1.0` it is selected (`fully_dependent`); below that it is listed with the ratio
  (`partially_dependent`).
- The two rules run to a **fixed point**, so a document that becomes fully dependent only
  once its second source is selected is caught. The selected set only grows, so it
  terminates, and nothing iterates a set — the same tree and the same seeds produce the
  same proposal, item for item.
- A document's rollover volumes are **part of its item**, never items of their own: a
  volume is the document's own frozen history and travels with it.
- `unarchive` is the mirror, over the same two rules: an archived document's archived
  sources are candidates and selected (`restored_with_page`, naming the returning pages in
  `cited_by_archived`); an archived document is selected when every source it cites would be
  live after the move (`fully_dependent`).
- A seed already in the state the action would put it in is LISTED and not selected, with
  `already_archived` / `already_live` — a complete answer about what the Owner named, rather
  than silence or an error.

Two asymmetries are deliberate rather than oversights:

- A claim with no source citation (a claim derived from existing canonical, which the gate
  allows) can never count as *citing a selected source*, so it holds its document below
  dependence `1.0` and out of an `archive` cascade — the conservative direction, since the
  Owner can always tick the box. In the `unarchive` direction the same claim poses no
  obstacle at all: it names no archived source, so it is already satisfied.
- A document's dependence is computed over its ledger AND its volumes' ledgers, because
  the item moves as one thing. Overview blocks are excluded from the denominator on both
  sides: the head is a reading of the ledger, not a claim of its own.

Pure and sync: no port, no I/O, no clock. The caller reads the tree and the archived
source ids once and hands them in.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..canonical_glance import document_title, volume_origin
from ..compile.anchor_ops import anchored_blocks
from ..compile.documents import strip_overview
from ..domain.archive import archived_path, is_archived_path, live_path
from ..domain.canonical import CanonicalDocument, iter_canonical_citations
from .record import RecordFacts, record_facts_in_move

ArchiveAction = Literal["archive", "unarchive"]

#: The seed the Owner named, already in the state the action would put it in — listed so the
#: proposal is a complete answer about the seeds, never selected.
NOTE_ALREADY_ARCHIVED = "already_archived"
NOTE_ALREADY_LIVE = "already_live"
#: A source no live document outside the selected set still cites.
NOTE_ORPHANED = "orphaned"
#: A source live documents still cite, which is why it is NOT selected for the archive. The
#: documents that kept it ride in `reason.cited_by_live`.
NOTE_STILL_CITED = "still_cited"
#: The `unarchive` mirror, and a code of its own because the fact is a different one: this
#: source comes back because a page coming back cites it. The pages ride in
#: `reason.cited_by_archived` — they are archived paths at the moment the plan is read, and
#: calling them `cited_by_live` was the one place this planner said something untrue.
NOTE_RESTORED_WITH_PAGE = "restored_with_page"
#: Every one of the document's ledger claims rests on the selected sources.
NOTE_FULLY_DEPENDENT = "fully_dependent"
#: Some of them do. The ratio rides in `reason.dependence`.
NOTE_PARTIALLY_DEPENDENT = "partially_dependent"
#: The Owner named it.
NOTE_SEED = "seed"
#: The Owner named something this library does not have.
NOTE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProposalReason:
    """Why an item is in the proposal, in machine-readable form.

    Structured rather than prose so the console can render it beside the checkbox and a
    Steward can read it in a message, both from one computation.
    """

    #: LIVE document paths that cite this source (the `still_cited` evidence). Only ever
    #: live ones: a reader deciding whether to untick a box is reading which pages would
    #: lose the source, and an archived path in this field would be answering a different
    #: question.
    cited_by_live: tuple[str, ...] = ()
    #: ARCHIVED document paths named as this item's reason — in `unarchive`, the pages whose
    #: return brings the source back out with them (`restored_with_page`). Empty in the
    #: `archive` direction, where nothing on the archived side decides anything.
    cited_by_archived: tuple[str, ...] = ()
    #: `(cited, total)` ledger claims — the document's dependence on the selected sources.
    dependence: tuple[int, int] | None = None
    #: A short mechanical code; see the NOTE_* constants above.
    note: str = ""


@dataclass(frozen=True)
class ProposalItem:
    """One thing the proposal names: a canonical document, or an L0 source."""

    kind: Literal["document", "source"]
    #: A document's path, or a source id.
    ref: str
    title: str
    role: Literal["seed", "cascade"]
    selected: bool
    reason: ProposalReason
    #: A document's rollover volumes, which move with it. Empty for a source.
    volumes: tuple[str, ...] = ()
    #: What the ARCHIVE RECORD for this document will say — computed here so the console can
    #: preview the page the owner is about to create, and read back by the job that writes
    #: it. Only ever on a `document` item of an `archive` proposal: an unarchive REPLACES the
    #: record with the page it stood in for, and a source leaves nothing behind at all.
    record: RecordFacts | None = None


@dataclass(frozen=True)
class ArchiveProposal:
    """The computed set, in a stable order: the seeds as given, then the cascade."""

    action: ArchiveAction
    seeds_documents: tuple[str, ...]
    seeds_sources: tuple[str, ...]
    items: tuple[ProposalItem, ...] = field(default_factory=tuple)

    def selected_documents(self) -> tuple[str, ...]:
        """The document paths this proposal would move, in item order (volumes ride along)."""
        return tuple(
            item.ref
            for item in self.items
            if item.kind == "document" and item.selected
        )

    def selected_sources(self) -> tuple[str, ...]:
        """The source ids this proposal would flag, in item order."""
        return tuple(
            item.ref for item in self.items if item.kind == "source" and item.selected
        )


# ----------------------------------------------------------------- the reading of a tree


@dataclass(frozen=True)
class _Unit:
    """One document plus the rollover volumes that move with it — the unit of the move."""

    path: str
    title: str
    volumes: tuple[str, ...]
    #: Every source id cited anywhere in the unit, overview included: the head may cite a
    #: source span directly, and a source the unit points at at all is a candidate.
    sources: frozenset[str]
    #: One entry per LEDGER claim (overview excluded): the source ids that claim cites.
    claims: tuple[frozenset[str], ...]

    @property
    def archived(self) -> bool:
        return is_archived_path(self.path)


def _claim_sources(body: str) -> tuple[frozenset[str], ...]:
    return tuple(
        frozenset(str(c.source_id) for c in iter_canonical_citations(block))
        for block in anchored_blocks(strip_overview(body))
    )


def _all_sources(body: str) -> set[str]:
    return {str(c.source_id) for c in iter_canonical_citations(body)}


def _read_units(documents: Sequence[CanonicalDocument]) -> dict[str, _Unit]:
    """The tree as units, keyed by the document's CURRENT path. Deterministic."""
    ordered = sorted(documents, key=lambda d: d.path)
    present = {doc.path for doc in ordered}
    volumes: dict[str, list[str]] = {}
    owners: list[CanonicalDocument] = []
    for doc in ordered:
        origin = volume_origin(doc, present)
        if origin is None:
            owners.append(doc)
        else:
            volumes.setdefault(origin, []).append(doc.path)
    bodies = {doc.path: doc.body for doc in ordered}
    units: dict[str, _Unit] = {}
    for doc in owners:
        own = tuple(sorted(volumes.get(doc.path, ())))
        sources = _all_sources(doc.body)
        claims: list[frozenset[str]] = list(_claim_sources(doc.body))
        for volume in own:
            sources |= _all_sources(bodies[volume])
            claims.extend(_claim_sources(bodies[volume]))
        units[doc.path] = _Unit(
            path=doc.path,
            title=document_title(doc),
            volumes=own,
            sources=frozenset(sources),
            claims=tuple(claims),
        )
    return units


def _resolve_document(ref: str, units: Mapping[str, _Unit]) -> str | None:
    """The unit `ref` names, accepting either spelling of the path.

    The Owner reads a live path off the glance and an archived one off `GET /archive`, and
    a move renames the document — so both spellings name the same subject and both resolve.
    A ref that names a rollover volume resolves to the document that owns it: a volume is
    never a unit of its own, and refusing the reference would be refusing the subject.
    """
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref in units:
        return ref
    other = live_path(ref) if is_archived_path(ref) else archived_path(ref)
    if other in units:
        return other
    for path, unit in units.items():
        if ref in unit.volumes or other in unit.volumes:
            return path
    return None


# ------------------------------------------------------------------------- the closure


def plan_archive(
    action: ArchiveAction,
    *,
    documents: Sequence[CanonicalDocument],
    source_titles: Mapping[str, str],
    archived_sources: Collection[str],
    seed_documents: Sequence[str] = (),
    seed_sources: Sequence[str] = (),
    source_occurrence: Mapping[str, str] | None = None,
) -> ArchiveProposal:
    """Compute the whole proposal for one action over one library state.

    `documents` is the WHOLE canonical tree (live and archived); `source_titles` names every
    source the library holds — it is also what "this source exists" means here, so a seed
    outside it is reported `unknown` rather than silently dropped. `archived_sources` is the
    set of source ids currently carrying `archived_at`.

    `source_occurrence` is `source_id → occurred_on` and exists for ONE thing: the span an
    archive record states. It is an input rather than a read because this planner is pure —
    the caller holds the source inventory already, and the day a source is ABOUT is L0's to
    state, never something derived from a path or a commit.
    """
    units = _read_units(documents)
    already = {str(s) for s in archived_sources}
    known_sources = {str(s) for s in source_titles} | already
    to_archive = action == "archive"

    # The universe each direction reasons over: archiving moves LIVE things out, unarchiving
    # moves ARCHIVED things back.
    in_scope = {
        path: unit for path, unit in units.items() if unit.archived is not to_archive
    }

    # DEDUPED, first occurrence wins, order preserved. A seed named twice is one seed: the
    # Owner ticking the same page in two places, or a console that sent both the live and the
    # archived spelling of one path. Duplicates reaching the items below would produce two
    # rows for one subject and — through `selected_documents()` — two moves for one document,
    # so the identity is settled HERE, at the one place a ref becomes a subject. Identity is
    # the RESOLVED path (both spellings of a moved page resolve to the same unit); a ref that
    # resolves to nothing is its own identity, so two different unknown refs both get their
    # `unknown` row and the same one twice does not.
    seed_docs: list[tuple[str, str | None]] = []  # (ref as given, resolved path or None)
    seen_docs: set[str] = set()
    for ref in seed_documents:
        path = _resolve_document(ref, units)
        key = path if path is not None else f"?{str(ref or '').strip()}"
        if key in seen_docs:
            continue
        seen_docs.add(key)
        seed_docs.append((ref, path))
    seed_srcs: list[str] = []
    seen_srcs: set[str] = set()
    for ref in seed_sources:
        source_id = str(ref)
        if source_id in seen_srcs:
            continue
        seen_srcs.add(source_id)
        seed_srcs.append(source_id)

    selected_docs = {
        path
        for _, path in seed_docs
        if path is not None and path in in_scope
    }
    selected_srcs = {
        ref
        for ref in seed_srcs
        if ref in known_sources and (ref in already) is not to_archive
    }

    def cited_by_live(source_id: str, selected: set[str]) -> tuple[str, ...]:
        """The in-scope documents outside `selected` that cite `source_id`."""
        return tuple(
            sorted(
                path
                for path, unit in in_scope.items()
                if path not in selected and source_id in unit.sources
            )
        )

    def dependence(unit: _Unit, selected: set[str]) -> tuple[int, int]:
        """`(cited, total)` ledger claims — read in the direction of the action.

        Archiving: a claim counts when it cites a source that is going into the archive.
        Unarchiving: a claim counts when nothing it cites would still be in the archive
        after the move — which is the same equality test (`cited == total`) standing for
        "every source this document cites would be live".
        """
        total = len(unit.claims)
        if to_archive:
            cited = sum(1 for claim in unit.claims if claim & selected)
        else:
            cited = sum(
                1
                for claim in unit.claims
                if not (claim & already) - selected
            )
        return cited, total

    # The fixed point. Both sets only grow and both are bounded by the library, so it
    # terminates; the iteration order never reaches the output, which is assembled below.
    while True:
        grew = False
        for path in sorted(selected_docs):
            for source_id in sorted(units[path].sources):
                if source_id in selected_srcs or (source_id in already) is to_archive:
                    continue
                if to_archive and cited_by_live(source_id, selected_docs):
                    continue
                selected_srcs.add(source_id)
                grew = True
        for path, unit in sorted(in_scope.items()):
            if path in selected_docs or not unit.sources & selected_srcs:
                continue
            cited, total = dependence(unit, selected_srcs)
            if total and cited == total:
                selected_docs.add(path)
                grew = True
        if not grew:
            break

    # ------------------------------------------------------- what each page leaves behind
    #
    # The RECORD is computed for every DOCUMENT item of an `archive` proposal, selected or
    # not, so the console can show the owner the page each checkbox would create. An
    # unarchive computes none: it REPLACES the record with the page the record stood in for,
    # and there is nothing to preview.
    #
    # `inbound` counts the live pages that link to this one and are NOT themselves leaving —
    # a link from a page that is going into the archive in the same commit is not a link the
    # record is left holding. "Leaving" is the plan's own selected set here, which is what a
    # PREVIEW can know: a confirm may still untick a box, and that changes the number. So the
    # job recomputes every record over the set the Owner finally confirmed, through the SAME
    # function this calls (`record_facts_in_move`) — one definition of the count, two callers,
    # and the page states what was true of the tree the commit is about to change.
    moving_units = {path: units[path].volumes for path in selected_docs}

    def _record(path: str, volumes: tuple[str, ...]) -> RecordFacts | None:
        if not to_archive or path not in in_scope:
            # Not the archive direction, or a seed already sitting in the archive: there is
            # no page here to leave a record of.
            return None
        return record_facts_in_move(
            documents,
            path,
            volumes=volumes,
            moving=moving_units,
            source_occurrence=source_occurrence,
        )

    # ------------------------------------------------------------------ the items
    items: list[ProposalItem] = []
    seeded_docs: set[str] = set()
    seeded_srcs: set[str] = set()

    for ref, path in seed_docs:
        if path is None:
            items.append(
                ProposalItem(
                    kind="document",
                    ref=ref,
                    title="",
                    role="seed",
                    selected=False,
                    reason=ProposalReason(note=NOTE_UNKNOWN),
                )
            )
            continue
        seeded_docs.add(path)
        unit = units[path]
        in_target_state = path not in in_scope
        items.append(
            ProposalItem(
                kind="document",
                ref=path,
                title=unit.title,
                role="seed",
                selected=not in_target_state,
                reason=ProposalReason(
                    note=(
                        (NOTE_ALREADY_ARCHIVED if to_archive else NOTE_ALREADY_LIVE)
                        if in_target_state
                        else NOTE_SEED
                    )
                ),
                volumes=unit.volumes,
                record=_record(path, unit.volumes),
            )
        )

    for ref in seed_srcs:
        if ref not in known_sources:
            items.append(
                ProposalItem(
                    kind="source",
                    ref=ref,
                    title="",
                    role="seed",
                    selected=False,
                    reason=ProposalReason(note=NOTE_UNKNOWN),
                )
            )
            continue
        seeded_srcs.add(ref)
        in_target_state = (ref in already) is to_archive
        items.append(
            ProposalItem(
                kind="source",
                ref=ref,
                title=str(source_titles.get(ref, "")),
                role="seed",
                selected=not in_target_state,
                reason=ProposalReason(
                    note=(
                        (NOTE_ALREADY_ARCHIVED if to_archive else NOTE_ALREADY_LIVE)
                        if in_target_state
                        else NOTE_SEED
                    )
                ),
            )
        )

    # Cascade sources: every source the selected documents cite that is not already in the
    # target state. Selected or not, it is LISTED — a source that stays is the Owner's most
    # useful line, because it names the documents that kept it.
    cascade_sources: dict[str, ProposalItem] = {}
    for path in sorted(selected_docs):
        for source_id in sorted(units[path].sources):
            if source_id in seeded_srcs or source_id in cascade_sources:
                continue
            if (source_id in already) is to_archive:
                continue
            selected = source_id in selected_srcs
            if to_archive and selected:
                # Orphaned: nothing outside the selected set still cites it, so there is no
                # document to name.
                reason = ProposalReason(note=NOTE_ORPHANED)
            elif to_archive:
                reason = ProposalReason(
                    cited_by_live=cited_by_live(source_id, selected_docs),
                    note=NOTE_STILL_CITED,
                )
            else:
                # Unarchiving: the mirror fact, and its own code. The source is cited by
                # pages that are coming back, so it comes back with them — and those pages
                # are ARCHIVED right now, which is why they are named in `cited_by_archived`
                # and not in the field that means "live documents would lose this".
                reason = ProposalReason(
                    cited_by_archived=tuple(
                        sorted(
                            other
                            for other in selected_docs
                            if source_id in units[other].sources
                        )
                    ),
                    note=NOTE_RESTORED_WITH_PAGE,
                )
            cascade_sources[source_id] = ProposalItem(
                kind="source",
                ref=source_id,
                title=str(source_titles.get(source_id, "")),
                role="cascade",
                selected=selected,
                reason=reason,
            )

    # Cascade documents: every in-scope document citing a source that IS being moved.
    cascade_documents: list[ProposalItem] = []
    for path, unit in sorted(in_scope.items()):
        if path in seeded_docs or not unit.sources & selected_srcs:
            continue
        cited, total = dependence(unit, selected_srcs)
        selected = path in selected_docs
        cascade_documents.append(
            ProposalItem(
                kind="document",
                ref=path,
                title=unit.title,
                role="cascade",
                selected=selected,
                reason=ProposalReason(
                    dependence=(cited, total),
                    note=(
                        NOTE_FULLY_DEPENDENT if selected else NOTE_PARTIALLY_DEPENDENT
                    ),
                ),
                volumes=unit.volumes,
                record=_record(path, unit.volumes),
            )
        )

    cascade = sorted(
        [*cascade_documents, *cascade_sources.values()],
        key=lambda item: (item.kind, item.ref),
    )
    items.extend(cascade)

    return ArchiveProposal(
        action=action,
        seeds_documents=tuple(ref for ref, _ in seed_docs),
        seeds_sources=tuple(seed_srcs),
        items=tuple(items),
    )


__all__ = [
    "NOTE_ALREADY_ARCHIVED",
    "NOTE_ALREADY_LIVE",
    "NOTE_FULLY_DEPENDENT",
    "NOTE_ORPHANED",
    "NOTE_PARTIALLY_DEPENDENT",
    "NOTE_RESTORED_WITH_PAGE",
    "NOTE_SEED",
    "NOTE_STILL_CITED",
    "NOTE_UNKNOWN",
    "ArchiveAction",
    "ArchiveProposal",
    "ProposalItem",
    "ProposalReason",
    "plan_archive",
]
