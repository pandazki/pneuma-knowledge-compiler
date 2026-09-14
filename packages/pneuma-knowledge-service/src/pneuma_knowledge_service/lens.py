"""The library's shape at the service face: the check (tier two) and the lens (tier three).

Both are pure core — `pneuma_knowledge_core.check` lists the page-level findings a Steward
can act on, `pneuma_knowledge_core.lens` reads the six dimensions only the whole library
shows (docs/design/structure-lens.md §3, §4). What this module adds is the one thing core
cannot do for itself: resolving WHICH documents, WHICH path templates, and — for the lens —
which previous reading, which kept consultations and which write dates the reading is
computed over, out of the adapters this deployment wired.

Both readers of each tier come through here, so what the Owner sees in the console is what a
Steward sees at the terminal, computed once in one place.

It reads and nothing else. No table, no registration: neither tier keeps state of its own,
and neither reaches a compile task. The one thing that ACTS on a reading is the review round
(`review_service.py`), and it acts on the check's report — which it obtains from here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pneuma_knowledge_core.check import CheckReport, build_check
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.lens import Consultation, LensReading, build_reading

from .skills import path_templates_for

log = logging.getLogger(__name__)

#: How many kept consultation records the `demand_supply` dimension reads. The dimension is a
#: SHAPE of demand — which families are asked for, how often an answer cited nothing — so it
#: is answered by a bounded recent window rather than by the whole ledger: a library with a
#: hundred thousand consultations must not make a read face walk all of them, and the last
#: few thousand are what "what people ask it" means for a reading taken today.
CONSULTATION_WINDOW = 2000

#: `--previous none`: the spelling that asks for a reading with no movement at all.
NO_PREVIOUS = "none"


def _read_at() -> str:
    """When this reading was taken.

    Stamped HERE and not in core: both tiers are pure functions of (documents, templates),
    and reading a clock inside them would make two reports of one ref differ. It is also why
    `read_at` is not part of a finding's key — the report says when it was taken, and says
    nothing different because of when.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _history(ctx, user_id: UserId, *, limit: int, after: str = ""):
    """One newest-first page of this user's canonical history, or `[]` if it cannot be read.

    Every ref question both tiers ask goes through here, so a library whose history is
    unreadable — a fresh repository with no commit, a store that does not keep one — answers
    the same way everywhere: the reading is still true, it simply cannot name a commit.
    """
    try:
        page, _total, _more = await ctx.canonical.snapshots_page(
            user_id, limit=limit, **({"after_ref": after} if after else {})
        )
    except Exception as exc:  # noqa: BLE001 — an unnameable commit is not a failed reading
        log.debug("canonical history unreadable for %s (after %r): %s", user_id, after, exc)
        return []
    return list(page)


async def _read_ref(ctx, user_id: UserId, *, at: str) -> str:
    """WHICH COMMIT this reading was taken at — `at` as passed, else HEAD, resolved.

    HEAD is not a ref a reader can come back to. A report that left `ref` empty for the
    default read could not say which library it came out of: the console showed a dash, and
    two readings taken either side of a compile were indistinguishable after the fact. The
    documents are still read at HEAD (not re-read at the resolved ref) — resolving is how the
    report NAMES what it read, not a second read of it.
    """
    if at:
        return at
    page = await _history(ctx, user_id, limit=1)
    return page[0].ref if page else ""


async def _library_at(
    ctx, user_id: UserId, *, at: str | None
) -> tuple[list[CanonicalDocument], dict]:
    """The documents at one ref and the templates they are judged against.

    `path_templates_for` is the read-only resolution of the user's families: it never writes
    a manifest and never calls a model, which is what makes it usable from a read face.
    """
    ref = SnapshotRef(ref=at) if at else None
    documents, templates = await asyncio.gather(
        ctx.canonical.list(user_id, at=ref),
        path_templates_for(ctx.settings, ctx.canonical, user_id),
    )
    return list(documents), templates


# ────────────────────────────────────────────────────────────────────── tier two: the check


async def read_check(
    ctx, user_id: UserId, *, at: str | None = None
) -> tuple[CheckReport, list[CanonicalDocument]]:
    """The check's report at one ref, and the documents it was computed over.

    The documents come back because a caller that addresses ONE page (`pkc library review
    --path`) has to be able to say "no such page" rather than "no findings" — a clean page
    and a typo must not render the same. Nothing else reads them.
    """
    at = (at or "").strip()
    (documents, templates), ref = await asyncio.gather(
        _library_at(ctx, user_id, at=at or None), _read_ref(ctx, user_id, at=at)
    )
    report = build_check(documents, templates, ref=ref, read_at=_read_at())
    return report, documents


async def check_report(ctx, user_id: UserId, *, at: str | None = None) -> CheckReport:
    """The report alone — the HTTP route's whole body, and the review round's task."""
    report, _documents = await read_check(ctx, user_id, at=at)
    return report


# ───────────────────────────────────────────────────────────────────── tier three: the lens


async def _refs(ctx, user_id: UserId, *, at: str) -> tuple[str, str]:
    """`(the commit this reading is at, the commit before it)` — both resolved, either "".

    One history page answers both, because they are two rows of the same walk. A named `at`
    is its own answer and one page of its ancestors; an unnamed one is HEAD and its parent,
    of which the FIRST names the reading and the SECOND is what it moved from. Taking the
    first for both would compare a reading with itself, which is a movement of zero rather
    than no movement — two different sentences, and only one of them true.

    A ref the history does not hold — a tag that moved, a frozen snapshot, a typo — is not a
    failure of the reading: the reading is still true, it simply has nothing to move against.
    """
    if at:
        page = await _history(ctx, user_id, limit=1, after=at)
        return at, (page[0].ref if page else "")
    page = await _history(ctx, user_id, limit=2)
    return (
        page[0].ref if page else "",
        page[1].ref if len(page) > 1 else "",
    )


def _consultation(record) -> Consultation:  # noqa: ANN001 — core's ConsultationRecord
    """One kept record as the dimension reads it: which pages, and whether it cited anything.

    The paths are the canonical pages this consultation TOUCHED — the ones handed to the
    model and the ones its answer cited, in that order, deduplicated. Handed and cited both,
    because the dimension asks two different questions of one record: which families this
    library is being asked about (what the retrieval found, cited or not) and whether the
    answer rested on anything at all. A span carries no page and contributes none.

    `cited` is literal: did the answer cite an address. That is the gap the dimension counts,
    and it is deliberately not `miss` — a record's `miss` also fires when the model said
    `no_record`, which is the same observation arriving by a different door but is a judgement
    the lane made rather than a fact about the library's supply.
    """
    paths: list[str] = []
    for ref in (*record.evidence_handed, *record.citations):
        path = (getattr(ref, "path", "") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return Consultation(
        paths=tuple(paths),
        cited=bool(record.citations),
        at=record.created_at.isoformat() if record.created_at else "",
    )


async def _consultations(ctx, user_id: UserId) -> tuple[Consultation, ...]:
    """The kept consultation records this reading's demand dimension is computed over.

    Absent rather than empty when the store cannot answer: `demand_supply` reads `unread`
    when there are no consultations, and a deployment whose consultation table is unreachable
    must report "not read" rather than "nobody asks this library anything".
    """
    try:
        records = await ctx.store.list_consultations(user_id, limit=CONSULTATION_WINDOW)
    except Exception as exc:  # noqa: BLE001 — a dimension that cannot be read is `unread`
        log.debug("consultations unreadable for %s: %s", user_id, exc)
        return ()
    return tuple(_consultation(record) for record in records)


async def _written_on(ctx, user_id: UserId) -> dict[str, str]:
    """path → the day that page was last written, from the canonical history itself.

    Free from git and stored nowhere (`ports/canonical_store.py:written_on`), which is what
    makes "has this subject ever been corrected" answerable by a read face.
    """
    try:
        return dict(await ctx.canonical.written_on(user_id))
    except Exception as exc:  # noqa: BLE001 — liveness reads what it can; it never fails
        log.debug("write dates unreadable for %s: %s", user_id, exc)
        return {}


async def read_reading(
    ctx, user_id: UserId, *, at: str | None = None, previous: str | None = None
) -> LensReading:
    """The six dimensions at one ref, against the previous reading.

    `previous` is a ref to compare against, `"none"` for no comparison at all, or None for
    the default — the canonical commit before `at`. The default is what makes a reading carry
    movement without anyone having to name a second ref; the explicit `none` is what makes it
    possible to ask for the reading alone.
    """
    at = (at or "").strip()
    (documents, templates), (ref, parent) = await asyncio.gather(
        _library_at(ctx, user_id, at=at or None), _refs(ctx, user_id, at=at)
    )

    wanted = (previous or "").strip()
    if wanted.lower() == NO_PREVIOUS:
        previous_ref = ""
    elif wanted:
        previous_ref = wanted
    else:
        previous_ref = parent

    before: tuple[list[CanonicalDocument], str] | None = None
    if previous_ref:
        try:
            before = (
                list(await ctx.canonical.list(user_id, at=SnapshotRef(ref=previous_ref))),
                previous_ref,
            )
        except Exception as exc:  # noqa: BLE001 — a ref nobody can read is no movement
            log.debug("previous ref %r unreadable for %s: %s", previous_ref, user_id, exc)
            before = None

    consultations, written_on = await asyncio.gather(
        _consultations(ctx, user_id), _written_on(ctx, user_id)
    )
    return build_reading(
        documents,
        templates,
        ref=ref,
        read_at=_read_at(),
        previous=before,
        consultations=consultations,
        written_on=written_on,
    )


__all__ = [
    "CONSULTATION_WINDOW",
    "NO_PREVIOUS",
    "check_report",
    "read_check",
    "read_reading",
]
