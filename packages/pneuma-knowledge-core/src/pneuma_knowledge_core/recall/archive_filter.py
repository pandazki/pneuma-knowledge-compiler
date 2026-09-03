"""The one assembly-time archive filter every answering lane applies (archive.md §3).

WHY IT EXISTS BESIDE THE INDEX FILTERS
--------------------------------------
The two search indexes already exclude the archive at query time, and they have to: an
archived claim admitted into the candidate list spends one of the 80 slots before the answer
ever sees a live one. But retrieval is not only those two indexes. A routed component path
reads its own projection and L0 and has never heard of the archive; a briefing pack is built
once out of whatever it was handed; a component written before this concept existed is still
a component. So the lanes apply ONE model-free filter over the evidence they assembled,
built from the two authoritative facts they already hold — the archived source ids
(`ContentStore.archived_source_ids`) and the `archive/` prefix on the documents they were
given (`domain/archive.ArchiveView`).

The index filters make the common case cheap; this makes the property hold wherever the
evidence came from.

AND WHY THE PATH ON A ROW IS NOT ENOUGH
---------------------------------------
The index rows are derived, and derived lags. A move rewrites the canonical path
immediately; the L3 rows carry the OLD live path until the projection sync lands, and a sync
that failed carries it indefinitely. Read straight off the row, that stale path says "live".
So the filter is stated the other way round wherever a lane holds its own document set: a
claim is admitted only when the pinned set still contains its page (`live_paths`, see
`_off_pin`). Authoritative canonical decides; the index only proposes.

WHAT EACH FUNCTION IS
---------------------
Pure, synchronous, and deliberately duck-typed: a claim is anything with `document_path`, a
window anything with `source_id`, a path result anything with `claims` and `windows`. Nothing
here imports `fast` or `paths` — those import this — and nothing here decides policy. Each
filter returns `(kept, dropped)`, because a lane that silently shows less is worse than one
that shows less and says so: the count goes into the lane's own telemetry channel the way
`hide_already_shown` reports `already_shown`.

The `mark_*` functions are the OTHER half — the `include_archived=True` path. An item
admitted from the archive is labelled (`archived`, the `superseded` discipline applied
again) and, for a claim, placed after the live ones, so a model handed history knows it is
history and a reader of the answer can see which is which.

AND ALL OF IT IS INERT UNTIL SOMETHING IS ARCHIVED
--------------------------------------------------
An unused feature must be an absent feature. Every function here is already a no-op over an
empty view by construction — no source is in an empty set, no path starts with `archive/`
in a tree with no `archive/`, and a label is only ever applied to an archived item — with
ONE exception, and it was a real one: the `live_paths` pin drops a claim whose page the
lane's document set does not contain, which happens in a library that has never archived
anything (a compile landing while the answer is being assembled, an index searched live
under a past-version `at=` pin). The pin exists to close the window between an archive
commit and the L3 sync that follows it, so it runs only while there is such a window:
`_pin` turns it off on an INACTIVE view (`ArchiveView.active` — no archived source, no
archived document). Same discipline as an unregistered index component: unregistered means
nonexistent, and the Owner who archives nothing can compare answers from before and after
this feature and find no difference.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from ..domain.archive import ArchiveView
from ..domain.ids import UserId

#: The label an admitted archived claim carries. A mechanical marker, never prose — it rides
#: `RetrievedClaim.labels` beside `superseded` and `via:<path>`, so it reaches the prompt and
#: the wire through machinery that already existed.
ARCHIVED_LABEL = "archived"


async def archive_view(
    user_id: UserId, content: Any, *, documents_archived: bool = False
) -> ArchiveView:
    """Read the archived source ids once, for the length of one retrieval.

    `documents_archived` is the canonical half of the mark, which no store can answer: the
    caller that listed the tree says whether it holds a page under `archive/`
    (`domain/archive.any_archived`). It defaults to False, so a caller that does not know —
    a core-only caller, a lane that was never handed a tree — gets the view a library with
    no archive gets, and the pin stays off.

    FAIL-SOFT ON THE PORT, not on the database. "This store never heard of the archive" is
    decided by INTROSPECTION and by nothing else: no `archived_source_ids` attribute, or one
    that is not callable, yields the empty view, and the document half of the filter still
    runs. That is the honest degradation for a core-only caller with no `ContentStore` at
    all, a fake written before the method existed, or a Protocol stub whose attribute is None.

    Once the method IS there, every exception it raises propagates — including the
    `TypeError` / `AttributeError` a real adapter raises from inside its own body. Catching
    those by exception TYPE was the bug: an adapter that breaks halfway through building its
    set is indistinguishable, at the `except` clause, from a store that has no set to build,
    and treating the two the same answers out of the archive without saying so — the one
    outcome this module exists to prevent.

    A method that returns None (rather than a coroutine) is the last shape of "not
    implemented" — a stub whose body is a bare `...` — and reads as the empty view. Any other
    non-awaitable return is taken at face value: a sync store that hands back a set is
    answering the question, not declining it.
    """
    blind = ArchiveView(documents_archived=documents_archived)
    if content is None:
        return blind
    reader = getattr(content, "archived_source_ids", None)
    if reader is None or not callable(reader):
        return blind
    found = reader(user_id)
    if found is None:
        return blind
    if inspect.isawaitable(found):
        found = await found
    if not found:
        return blind
    return ArchiveView(
        sources=frozenset(found), documents_archived=documents_archived
    )


def index_scope(include_archived: bool) -> dict[str, bool]:
    """The keyword an index search is handed — and NOTHING when the archive is excluded.

    `include_archived=False` is every port's own default, so omitting it is byte-for-byte
    the call this lane always made. Spelled here rather than inline at a dozen call sites so
    the one thing that could drift — whether the default is off — is stated once.
    """
    return {"include_archived": True} if include_archived else {}


def _claim_archived(claim: Any, view: ArchiveView) -> bool:
    """A claim is archived iff its PAGE is: the path is the state (archive.md §2.1)."""
    return view.path_archived(str(getattr(claim, "document_path", "") or ""))


def _window_archived(window: Any, view: ArchiveView) -> bool:
    """A window/passage/episode is archived iff its SOURCE is."""
    return view.source_archived(str(getattr(window, "source_id", "") or ""))


def _pin(view: ArchiveView, live_paths: frozenset[str] | None) -> frozenset[str] | None:
    """The document set to pin to — or None, which is "do not pin", on an INACTIVE view.

    THE ONE PLACE THIS FEATURE COULD CHANGE A LIBRARY THAT HAS NO ARCHIVE. Every other
    check here is a no-op when nothing is archived: no source is in an empty set, and no
    path starts with `archive/` in a tree that has no `archive/`. The pin is not — it drops
    a claim whose page the lane's document set does not hold, and that is a real drop in a
    library that never archived anything: a compile that landed while this very answer was
    being assembled, or a past-version `at=` pin read against live indexes, both name a page
    the set does not have.

    It is not needed there either. The pin closes ONE window — between the archive commit
    that rewrites a page's path and the L3 sync that catches the rows up, indefinitely if
    that sync failed — and a library with no archived source and no archived document has
    never opened that window. So the pin turns on with the first archived thing and is
    off until then, whatever `live_paths` says.

    Same discipline as an unregistered index component (AGENTS.md): with none registered
    every seam renders byte-for-byte as it did before the concept existed.
    """
    return live_paths if view.active else None


def _off_pin(claim: Any, live_paths: frozenset[str] | None) -> bool:
    """Whether this claim names a page the lane's own document set does not contain.

    THE MOVE IS THE STATE, THE INDEX IS DERIVED. After `work/x.md` becomes
    `archive/work/x.md`, its L3 rows keep the OLD path until the projection sync lands — and
    a sync that fails keeps them indefinitely. `_claim_archived` reads the path off the row
    and would read that stale path as live, so the assembly filter would pass the archived
    claim through with the archive nowhere in sight.

    So the check is inverted where the lane can afford it: a claim is admitted only when the
    document set the lane HOLDS still contains its page. That set is canonical, read for this
    call, and it is what the glance, the outline and every rendered document name came from.
    A claim on a page that set does not contain is evidence the lane cannot show — it has no
    title for it, no glance line, and no way to say whether it is live.

    THE TWO EMPTIES ARE NOT THE SAME. `live_paths=None` means the lane was HANDED NO
    DOCUMENT SET (rag, a briefing's `ask` over a stored pack) and nothing is dropped on this
    ground — there is no set to be off. An EMPTY frozenset is a set, and it says the library
    has no page the lane may show: every index claim is off-pin and every one is dropped.
    That is the correct reading and the whole of this finding — when the Owner archives the
    last live page the authoritative answer is "nothing", and a lane that read the empty set
    as "no pin" would serve a stale L3 row out of the archive instead.

    AND "NO SET" IS NEVER A FAILURE. `live_paths=None` is a lane that STRUCTURALLY has no
    document set, not a lane whose read of one failed: the service hands the answering lanes
    a real set always and refuses the call when canonical cannot be read
    (`api/routes/v1.CanonicalUnavailable` → `503 canonical_unavailable`), and the live lane
    skips its tick on the same failure (`live_pipeline.SKIP_CANONICAL_UNAVAILABLE`). So in
    production the pin is always on wherever a lane holds evidence to pin — once anything has
    been archived. Until then it does not run at all and `live_paths` is never consulted
    (`_pin`).
    """
    if live_paths is None:
        return False
    return str(getattr(claim, "document_path", "") or "") not in live_paths


def filter_claims(
    claims: Sequence[Any], view: ArchiveView, *, live_paths: frozenset[str] | None = None
) -> tuple[list[Any], int]:
    """Drop every claim whose document sits under `archive/` — or off the lane's pin.

    Returns `(kept, dropped)` with ONE COMBINED COUNT: both grounds are the same fact from
    the reader's side — a claim about a page this answer cannot show — and one number is what
    the lanes already surface as `archive_hidden`. Splitting it would put a second key on
    every stage preview to distinguish two omissions nobody can act on differently.

    `live_paths` is the lane's own document set (`frozenset(doc.path for doc in documents)`),
    or None when it was handed none; an EMPTY set pins to nothing and drops every claim (see
    `_off_pin`). A lane running `include_archived=True` passes the FULL set, archived pages
    included, so the archive is pinned rather than filtered here.

    ONE LEGITIMATE CASUALTY, and it is the correct reading of "pinned": the fast and deep
    lanes may be handed documents pinned at a snapshot while the indexes they search are
    live, so a claim on a page created after the pin is dropped. An answer assembled over a
    snapshot answers out of that snapshot; a claim from after it is not part of the library
    the caller asked about. That casualty is charged only to a library that HAS an archive —
    on an inactive view the pin does not run at all (`_pin`).
    """
    pinned = _pin(view, live_paths)
    kept = [
        c
        for c in claims
        if not _claim_archived(c, view) and not _off_pin(c, pinned)
    ]
    return kept, len(claims) - len(kept)


def pin_claims(
    claims: Sequence[Any], live_paths: frozenset[str] | None, view: ArchiveView
) -> tuple[list[Any], int]:
    """The stale-path half of `filter_claims` ALONE — for the `include_archived=True` path.

    There the archive is admitted, so `_claim_archived` must not drop; the pin still must.
    A row whose `document_path` no page in the lane's set carries is a row the projection has
    not caught up with, and admitting the archive is not the same as admitting a path that
    names nothing. `live_paths=None` — no set handed — keeps everything, as everywhere else;
    an empty set keeps nothing, as everywhere else.

    `view` is here for one reason and reads nothing else off it: an INACTIVE view turns the
    pin off entirely (`_pin`). A caller that asked for `include_archived` in a library with
    nothing archived asked for nothing, and must get the answer it got before this feature
    existed."""
    pinned = _pin(view, live_paths)
    if pinned is None:
        return list(claims), 0
    kept = [c for c in claims if not _off_pin(c, pinned)]
    return kept, len(claims) - len(kept)


def filter_windows(
    windows: Sequence[Any], view: ArchiveView
) -> tuple[list[Any], int]:
    """Drop every window, passage or episode summary from an archived source.

    One function for all three because all three are the same fact addressed the same way
    (I4): a source id and a block span."""
    kept = [w for w in windows if not _window_archived(w, view)]
    return kept, len(windows) - len(kept)


def filter_path_result(
    result: Any, view: ArchiveView, *, live_paths: frozenset[str] | None = None
) -> tuple[Any, int]:
    """The component face: both halves of one path's return, filtered together.

    Takes a `PathResult` or a `ComponentEvidence` — they carry the same two fields, and a
    component's evidence has to be judged by the same rule whichever shape it is in. The
    row comes back as itself when nothing was dropped, so a library with no archive is
    byte-for-byte untouched."""
    claims, dropped_claims = filter_claims(
        getattr(result, "claims", ()) or (), view, live_paths=live_paths
    )
    windows, dropped_windows = filter_windows(getattr(result, "windows", ()) or (), view)
    dropped = dropped_claims + dropped_windows
    if not dropped:
        return result, 0
    return replace(result, claims=tuple(claims), windows=tuple(windows)), dropped


def filter_path_results(
    results: Sequence[Any], view: ArchiveView, *, live_paths: frozenset[str] | None = None
) -> tuple[list[Any], int]:
    """`filter_path_result` over a whole component face; the counts sum."""
    kept: list[Any] = []
    dropped = 0
    for row in results:
        filtered, count = filter_path_result(row, view, live_paths=live_paths)
        kept.append(filtered)
        dropped += count
    return kept, dropped


def mark_path_result(result: Any, view: ArchiveView) -> Any:
    """The `include_archived=True` half of the component face: label, do not drop.

    Without this, an admitted archived component result was the ONE evidence face in the lane
    that reached the model unlabelled — the ranked faces were marked and ordered, and the
    routed path's claims arrived beside them looking exactly like the present. A component
    knows nothing of the archive (I7), so the label has to be applied here or nowhere."""
    claims = mark_archived_claims(getattr(result, "claims", ()) or (), view)
    windows = mark_archived_windows(getattr(result, "windows", ()) or (), view)
    if list(claims) == list(getattr(result, "claims", ()) or ()) and list(
        windows
    ) == list(getattr(result, "windows", ()) or ()):
        return result
    return replace(result, claims=tuple(claims), windows=tuple(windows))


def scope_path_results(
    results: Sequence[Any],
    view: ArchiveView,
    *,
    include_archived: bool,
    live_paths: frozenset[str] | None = None,
) -> tuple[list[Any], int]:
    """Drop or label a whole component face, whichever the call asked for.

    The mirror of `scope_claims` / `scope_windows` for the routed paths. On the opt-in path
    the stale-path guard still runs (`live_paths`), because a claim on a page the lane's
    document set does not contain is unshowable whether or not the archive was asked for."""
    if not include_archived:
        return filter_path_results(results, view, live_paths=live_paths)
    kept: list[Any] = []
    dropped = 0
    for row in results:
        claims, count = pin_claims(getattr(row, "claims", ()) or (), live_paths, view)
        if count:
            row = replace(row, claims=tuple(claims))
        kept.append(mark_path_result(row, view))
        dropped += count
    return kept, dropped


def mark_archived_claims(claims: Sequence[Any], view: ArchiveView) -> list[Any]:
    """Label the admitted archived claims and place them after the live ones.

    The same discipline `mark_superseded_claims` applies, for the same reason: an item the
    lane admitted out of the archive must never be readable as part of the present. Order is
    preserved within each group, so the ranking the retrieval produced survives."""
    live: list[Any] = []
    archived: list[Any] = []
    for claim in claims:
        if not _claim_archived(claim, view):
            live.append(claim)
        elif ARCHIVED_LABEL in getattr(claim, "labels", ()):
            archived.append(claim)
        else:
            archived.append(
                replace(claim, labels=(*getattr(claim, "labels", ()), ARCHIVED_LABEL))
            )
    return [*live, *archived]


def mark_archived_windows(windows: Sequence[Any], view: ArchiveView) -> list[Any]:
    """Stamp `archived` on every admitted window from an archived source.

    NOT reordered, unlike claims: windows are laid out by `order_lost_in_middle`, and that
    placement is a property of the attention curve rather than of ranking — reshuffling it
    here would quietly undo an ordering decision made elsewhere. The marker rides the
    rendered provenance header instead (`assembly._provenance`).

    A window shape that has no `archived` field is left exactly as it is: this is a render
    hint, and refusing to hand one over is not worth a TypeError inside an answer."""
    out: list[Any] = []
    for window in windows:
        if (
            _window_archived(window, view)
            and hasattr(window, "archived")
            and not getattr(window, "archived")
        ):
            out.append(replace(window, archived=True))
        else:
            out.append(window)
    return out


def scope_claims(
    claims: Sequence[Any],
    view: ArchiveView,
    *,
    include_archived: bool,
    live_paths: frozenset[str] | None = None,
) -> tuple[list[Any], int]:
    """Drop or label, whichever the call asked for. Returns (claims, dropped).

    The pin runs on BOTH paths (see `pin_claims`); only the archive rule follows the flag."""
    if include_archived:
        pinned, dropped = pin_claims(claims, live_paths, view)
        return mark_archived_claims(pinned, view), dropped
    return filter_claims(claims, view, live_paths=live_paths)


def scope_windows(
    windows: Sequence[Any], view: ArchiveView, *, include_archived: bool
) -> tuple[list[Any], int]:
    """Drop or mark, whichever the call asked for. Returns (windows, dropped)."""
    if include_archived:
        return mark_archived_windows(windows, view), 0
    return filter_windows(windows, view)


__all__ = [
    "ARCHIVED_LABEL",
    "archive_view",
    "filter_claims",
    "filter_path_result",
    "filter_path_results",
    "filter_windows",
    "index_scope",
    "mark_archived_claims",
    "mark_archived_windows",
    "mark_path_result",
    "pin_claims",
    "scope_claims",
    "scope_path_results",
    "scope_windows",
]
