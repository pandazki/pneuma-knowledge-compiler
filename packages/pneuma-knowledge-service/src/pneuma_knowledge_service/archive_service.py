"""The archive's request-side flow: propose → confirm → (job) → executed, and the inventory.

docs/design/archive.md §5–§6. Nothing here moves anything. The Owner names seeds, core's
pure planner (`archive/proposal.py`) computes the closure against ONE library state, this
module keeps that computation as a record, and a separate confirm enqueues the one job that
writes. The split is the whole point: knowledge hangs together, so what the Owner named is
never the whole set, and a set that was previewed against a tree that has since compiled is
a preview of something else.

Three properties this module is responsible for:

- **The plan is computed once.** `plan_archive` runs at proposal time and its items are
  stored verbatim. A confirm never re-plans, so the set that executes is byte-for-byte the
  set the Owner ticked — not a fresh reading of a tree that moved under them.
- **`library_ref` is the identity of that state.** It is written with the items and
  re-checked twice: at confirm (409 `stale`, the Owner re-plans) and again inside the job,
  which runs on the per-user queue and could still be behind a compile that landed between
  the confirm and the claim. "Outrun by the library" is COMPUTED AT READ — `library_ref` is
  not HEAD, therefore this row cannot be confirmed — and written only where the comparison
  is also a decision: the confirm that refuses. A sweep over other people's rows would be a
  write racing every confirm in flight to say something any reader can derive from the two
  fields it is already holding.
- **One decision, one job.** The flip out of `proposed` and the INSERT of the job it
  enqueues are one transaction (`PostgresStore.confirm_archive_proposal`), with `status =
  'proposed'` in the WHERE clause. The transition is therefore decided by the row and not by
  the read above it — two confirms, or a confirm racing a drop, have exactly one winner —
  and the two halves cannot exist apart: there is no `confirmed` proposal without a job to
  execute it, and no job for a decision that was never recorded. A failure leaves nothing
  changed, so it is an ordinary 500 and the proposal is still open.
- **An override may only tick and untick.** The confirm's `items` narrows what was listed;
  it cannot introduce a ref the plan did not compute. Adding to a cascade is a RE-PLAN with
  more seeds — the closure is a computation over the library, and hand-adding to its output
  would be an unexplained set that no reason field describes.

The exception type is the frozen-tenant pattern applied again: the SERVICE raises, one
handler in `api/app.py` renders it, and a new endpoint inherits the status codes for free.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pneuma_knowledge_core.archive.proposal import plan_archive
from pneuma_knowledge_core.archive.record import (
    note_machinery,
    record_reason,
    sanitize_note,
    statement_quote,
)
from pneuma_knowledge_core.canonical_glance import document_title, volume_origin
from pneuma_knowledge_core.domain.archive import (
    ARCHIVE_CLAIMS_KEY,
    ARCHIVE_INBOUND_KEY,
    ARCHIVE_OF_KEY,
    ARCHIVE_ROOT,
    ARCHIVE_SOURCES_KEY,
    ARCHIVE_SPAN_KEY,
    ARCHIVE_STATEMENT_KEY,
    ARCHIVE_VOLUMES_KEY,
    ARCHIVED_ON_KEY,
    is_archive_record,
    live_path,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef

from .snapshot_tenant import assert_writable

#: The job kind. On the shared per-user queue next to compile / index / groom / evolve, which
#: is exactly why the archive never races a compile: one in-flight job per user IS the
#: single-writer guarantee, and a move is a canonical write like any other.
ARCHIVE_JOB_KIND = "archive"

#: The statuses a proposal moves through. `proposed` is the only one a confirm accepts; the
#: rest are terminal as far as this surface is concerned, except `stale` — which a drop
#: still closes, because a proposal the library outran is exactly the one an Owner wants to
#: clear off the list.
STATUS_PROPOSED = "proposed"
STATUS_CONFIRMED = "confirmed"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"
STATUS_DROPPED = "dropped"
#: The plan was computed against a HEAD the library has moved past, so the set it shows is
#: no longer the set that would follow. A row in this state can never be confirmed, and the
#: Owner's one remaining action on it is to drop it.
#:
#: COMPUTED AT READ, WRITTEN ONLY AT CONFIRM. `library_ref != HEAD` is the whole definition,
#: and every read already holds both halves of it — so the API presents `stale` (see
#: `serialize_proposal`) while the row goes on saying `proposed`. The one write is the
#: confirm's: it compared against the HEAD it refused on, so recording the refusal is a fact
#: about a decision that was actually attempted rather than a guess about one that was not.
#: A sweep over everyone else's rows would be that guess, and would race every confirm in
#: flight to write what any reader can derive.
STATUS_STALE = "stale"

#: What a drop may close: an open proposal, or one the library outran.
DROPPABLE = (STATUS_PROPOSED, STATUS_STALE)

#: The one L0 kind a `statement_ref` may name. The Owner acts on the library by SPEAKING
#: (docs/design/steward-owner-visitor.md §1), and the record's third block cites that speech
#: — so a `statement_ref` pointing at a meeting, a document or anything else would have the
#: record quote a sentence the Owner never said, under a citation that resolves.
OWNER_DIALOGUE_KIND = "owner_dialogue"


class ArchiveRequestError(RuntimeError):
    """A proposal request the archive refuses, carrying the status and a machine code.

    Its own type for the same reason `SnapshotTenantWriteError` has one: the mapping to HTTP
    lives in ONE handler in `api/app.py`, so every archive endpoint — including ones written
    later — answers `stale` and `not_proposed` in the same shape, and no route has to
    remember to catch anything.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        proposal: Mapping[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        #: The proposal as it stands AFTER the refusal, when the refusal moved it. A `stale`
        #: confirm writes the row before it answers, so a console that only reads the error
        #: would otherwise still be holding a `proposed` copy of a row that is now `stale`.
        self.proposal = dict(proposal) if proposal is not None else None
        super().__init__(message)


# ------------------------------------------------------------------ the library's HEAD


async def library_head(ctx: Any, user_id: UserId) -> str:
    """The canonical HEAD this plan is (or was) computed against; `""` for an empty library.

    Read through `snapshots_page(limit=1)` rather than a new port method: the newest-first
    history page's first entry IS HEAD, the adapter already answers it in one `git log`, and
    a second way to ask the same question is a second thing that can drift. An empty
    repository answers `""`, which compares equal to the `""` a plan over an empty library
    stored — a library with no commits is a state like any other.
    """
    refs, _total, _has_more = await ctx.canonical.snapshots_page(user_id, limit=1)
    return refs[0].ref if refs else ""


# --------------------------------------------------------------------- serialization
#
# The wire shape of a proposal is the planner's shape, spelled in JSON. It is written by
# `plan` and read back by every other endpoint out of the kept row, so both directions go
# through these two functions and cannot disagree.


#: Where a kept `reason` came from. Written beside the line itself, because the JOB — which
#: mints an `owner-dialogue/v1` source out of that line, L0 labelled as the Owner SPEAKING —
#: may not take the words of anything it cannot see the provenance of. The two legal
#: provenances are the whole of the rule in `_reason_line`: the note sent WITH the confirm,
#: or block 0 of a `statement_ref` the Owner named. An item carrying a `reason` with no stamp
#: is a row no confirm of this code wrote, and the job refuses it (`statement_missing`)
#: rather than guessing which of the two it was.
REASON_SOURCE_NOTE = "note"
REASON_SOURCE_STATEMENT = "statement"


def _record_dict(
    item: Any, reason: str | None, reason_source: str | None = None
) -> dict[str, Any] | None:
    """The item's record PREVIEW, or None when this item leaves no record behind.

    `reason` is the exact line the record's third block will quote — the Owner's own words,
    read off the statement they named or sent with the confirm — and it rides inside the
    preview because it is the one part of the page the console cannot derive from the item.
    It is not a fact about the PAGE (every other field is), so the pure planner does not
    compute it: it is a fact about the DECISION, and the decision is this layer's.

    It is NULL on a plan that named no statement, and null is the honest preview of a page
    whose reason has not been spoken yet. The framework composes none (`record_reason`), a
    note typed at the plan is not a decision, and the console shows the live content of the
    box instead — so the line the Owner reads is always the line they are about to send.

    `reason_source` is that line's PROVENANCE, stamped beside it and never inferred. Without
    it the job could only assume that a `reason` on a confirmed row was confirm-written —
    true of this code, and provable by nothing, which is the shape of constraint this project
    does not accept. Stamped, the job can REFUSE a line whose provenance is not stated rather
    than mint the Owner's speech out of it. Null exactly when `reason` is null.
    """
    facts = getattr(item, "record", None)
    if not facts:
        return None
    return {
        **facts.as_dict(),
        "reason": reason,
        "reason_source": reason_source if reason is not None else None,
    }


def _item_dict(
    item: Any, reason: str | None = None, reason_source: str | None = None
) -> dict[str, Any]:
    return {
        # The RECORD this document will leave behind at its live path, or None. Computed at
        # PLAN time and kept so the console previews the page the owner is about to create.
        # A PREVIEW: the job recomputes the facts at execution over the set the owner finally
        # confirmed, through the same function the planner used, because a confirm may untick
        # a box and unticking one changes another item's `inbound`.
        "record": _record_dict(item, reason, reason_source),
        "kind": item.kind,
        "ref": item.ref,
        "title": item.title,
        "role": item.role,
        "selected": bool(item.selected),
        "reason": {
            "cited_by_live": list(item.reason.cited_by_live),
            "cited_by_archived": list(item.reason.cited_by_archived),
            "dependence": (
                list(item.reason.dependence)
                if item.reason.dependence is not None
                else None
            ),
            "note": item.reason.note,
        },
        "volumes": list(item.volumes),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _presented_status(row: Mapping[str, Any], head: str | None) -> str:
    """`stale` for an open proposal the library has moved past; the stored status otherwise.

    The comparison is the definition — a plan previews ONE library state, and a confirm
    against any other is refused — so it is done where the answer is used rather than
    written into the row by a sweep. Every caller that knows HEAD passes it; a caller that
    does not (`head=None`) gets the row verbatim, which is the honest answer to "what does
    the record say" when nothing here has read the library.
    """
    stored = str(row["status"])
    if head is None or stored != STATUS_PROPOSED:
        return stored
    return STATUS_STALE if (row.get("library_ref") or "") != head else stored


def serialize_proposal(
    row: Mapping[str, Any], *, head: str | None = None
) -> dict[str, Any]:
    """One kept `archive_proposals` row as the API answers it.

    `head` is the canonical HEAD this answer is being read against. Given, an open proposal
    whose `library_ref` is no longer HEAD is PRESENTED as `stale` — the row itself is not
    touched, because a read is not a decision.
    """
    seeds = row.get("seeds") or {}
    return {
        "proposal_id": row["proposal_id"],
        "action": row["action"],
        "status": _presented_status(row, head),
        "library_ref": row.get("library_ref") or "",
        "note": row.get("note"),
        "statement_ref": row.get("statement_ref"),
        "seeds": {
            "documents": list(seeds.get("documents") or []),
            "sources": list(seeds.get("sources") or []),
        },
        "items": [dict(item) for item in (row.get("items") or [])],
        "created_at": _iso(row.get("created_at")),
        "confirmed_at": _iso(row.get("confirmed_at")),
        "executed_at": _iso(row.get("executed_at")),
        "job_id": row.get("job_id"),
        "detail": row.get("detail"),
    }


# ------------------------------------------------------- the owner's words, checked once
#
# Everything below decides ONE string: the sentence the archive record's third block will
# quote, under `[cite: <statement_sid> ¶0]`. It is checked at the REQUEST rather than only in
# the job, because every one of these refusals is something the Owner can fix by typing
# something else — and a job that discovered it would fail a decision that was already made,
# with a canonical commit possibly already in the tree.


def _refuse_note_machinery(note: str | None) -> None:
    """Refuse a note carrying the system's own machinery, naming the fragment to delete.

    The record interpolates the note into a block the projection then indexes as a claim, so
    an `<!-- c:… -->`, a `<!-- supersedes: … -->` or an invented `__AUTO__` inside it would be
    machinery minted by hand in canonical — the exact thing `check_claim_text_machinery`
    refuses on every other write path, arriving through the one channel no model touches.
    Same predicate, stated at the face where a person can still fix it.
    """
    found = note_machinery(note or "")
    if found is None:
        return
    raise ArchiveRequestError(
        422,
        "note_machinery",
        f"the note carries the system's own machinery ({found!r}); an archive note is "
        "words, and its text is quoted into a claim. Remove it and say it in prose.",
    )


async def _statement_words(ctx: Any, user: UserId, statement_ref: str) -> str:
    """The Owner's own words in the statement they named — or the refusal that says why not.

    Three things are checked, and they are the three ways `[cite: <sid> ¶0]` could otherwise
    resolve to something that is not the Owner speaking: the source is THIS user's, its kind
    is `owner_dialogue`, and it has a block 0 to quote. What comes back is that block's words
    (`statement_quote`), sanitized the way a note is — so the preview, the comparison against
    a note, and the committed block are all one string, and the one block of a record that
    carries a citation carries exactly the one the renderer appends.
    """
    try:
        source = await ctx.store.get(user, SourceId(str(statement_ref)))
    except LookupError as exc:
        raise ArchiveRequestError(
            422,
            "statement_unknown",
            f"no source {statement_ref!r} in this library; a `statement_ref` names the "
            "`owner-dialogue/v1` source in which the owner asked for this.",
        ) from exc
    if str(source.raw.kind) != OWNER_DIALOGUE_KIND:
        raise ArchiveRequestError(
            422,
            "statement_not_owner",
            f"source {statement_ref!r} is a {source.raw.kind!r} source, not "
            f"{OWNER_DIALOGUE_KIND!r}. The record's reason cites the owner speaking, so it "
            "may only cite an owner-dialogue source.",
        )
    if not source.blocks:
        raise ArchiveRequestError(
            422,
            "statement_unknown",
            f"source {statement_ref!r} carries no block, so there is nothing at ¶0 for the "
            "record to quote.",
        )
    return sanitize_note(statement_quote(source.blocks[0].text))


async def _reason_line(
    ctx: Any,
    user: UserId,
    *,
    note: str | None,
    statement_ref: str | None,
    required: bool,
) -> str | None:
    """The exact sentence the record will quote, validated. The preview and the page agree.

    THE OWNER'S OWN WORDS OR NOTHING, and — the whole of this rule — only the words they
    sent WITH THE DECISION. The archive ingests an `owner-dialogue/v1` source, L0 labelled as
    the Owner SPEAKING, so a sentence this layer composed when they typed none would stand
    there as words they never said. A note stored earlier is the same fault one step removed:
    it was typed against a different set, at a moment that decided nothing, and promoting it
    to a statement at execution would record the Owner as having said something at a time
    they did not. So the statement can come from exactly two places — the `note` in the
    CONFIRM request, or the block 0 of a `statement_ref` the Owner named — and `required`
    says which caller is standing at that decision.

    `required=True` (the confirm) refuses `422 note_required` when the request carries
    neither. Whitespace is not a note: a box holding only spaces is refused exactly as an
    empty one is (`sanitize_note` folds it to "").

    `required=False` (the plan) answers None instead. A plan decides nothing and stores
    nothing quotable: its preview quotes a line only when the Owner named a statement, which
    is words they have already spoken. Friction at the box is answered by the console, which
    PREFILLS a suggested sentence the Owner reads, edits and SENDS with the confirm; it is
    not answered by this layer keeping the suggestion and quoting it back.

    With a `statement_ref`, the source WINS: the quote is that source's block 0, and a note
    given beside it is informational only — so if the two differ they are refused
    (`statement_mismatch`) rather than silently resolved, because either answer would be a
    record quoting one thing and citing another.
    """
    _refuse_note_machinery(note)
    if not statement_ref:
        if not required:
            # A plan quotes NOTHING of its own, note or no note. Answering the note here
            # would preview a sentence this call is not entitled to keep, and a preview is a
            # promise about what the page will say.
            return None
        words = record_reason(note or "")
        if words:
            return words
        raise ArchiveRequestError(
            422,
            "note_required",
            "say why. The archive records the reason as the owner's own statement — an "
            "`owner-dialogue/v1` source the record then cites — so it can only be words "
            "the owner wrote AT THIS DECISION: send a `note` with the confirm, or a "
            "`statement_ref` naming the statement they already made. A note left on the "
            "proposal is not one: it was typed against a set that may since have changed.",
        )
    words = await _statement_words(ctx, user, statement_ref)
    typed = sanitize_note(note or "")
    if typed and typed != words:
        raise ArchiveRequestError(
            422,
            "statement_mismatch",
            f"the note and the statement {statement_ref!r} say different things — the "
            f"statement's first block says {words!r}. The record quotes the source it "
            "cites, so drop the note or name a statement that says it.",
        )
    return words


# --------------------------------------------------------------------------- propose


async def plan(
    ctx: Any,
    user_id: UserId,
    *,
    action: str,
    documents: Sequence[str] = (),
    sources: Sequence[str] = (),
    note: str | None = None,
    statement_ref: str | None = None,
) -> dict[str, Any]:
    """Compute one proposal against the current library state and keep it.

    Reads the whole canonical tree and the source inventory once — the planner is pure and
    takes both by value — then stores the computed items beside the HEAD they explain. The
    proposal is a KEPT record from this moment: it states what the Owner was shown, and
    nothing recomputes it later.

    `note` IS NOT A REASON HERE. A plan decides nothing, so nothing it is given may become
    the Owner's statement: the note is kept on the row as the informational line a listing
    displays, and the statement is the note sent with the CONFIRM (`_reason_line`). The one
    quotable line a plan can preview is a `statement_ref`'s block 0 — words the Owner has
    already spoken — and without one the preview's `record.reason` is null and the console
    shows the live content of its own note box.
    """
    assert_writable(user_id)
    user = UserId(str(user_id))

    # HEAD FIRST, then the tree pinned to it. Reading the tree and only afterwards asking
    # what HEAD is would bind `library_ref` to whatever commit landed in between, so the
    # kept proposal would name a state its own items were never computed over — and the
    # confirm's staleness check would pass on a tree the Owner never saw. Pinned at `at=`,
    # `library_ref` names EXACTLY the tree the closure was computed on.
    ref = await library_head(ctx, user)
    docs = await ctx.canonical.list(
        user, at=SnapshotRef(ref=ref) if ref else None
    )
    archived = await ctx.store.archived_source_ids(user)
    raw_sources = await ctx.store.list(user)
    source_titles = {str(raw.source_id): raw.title for raw in raw_sources}
    # The day each source is ABOUT — `meta.occurred_on`, never the ingest wall clock. It is
    # the only input a record's SPAN can honestly come from, and it belongs to L0, so the
    # pure planner is handed it rather than deriving anything date-shaped of its own.
    source_occurrence = {
        str(raw.source_id): raw.occurred_on() for raw in raw_sources
    }

    proposal = plan_archive(
        action,  # type: ignore[arg-type]
        documents=docs,
        source_titles=source_titles,
        archived_sources={str(sid) for sid in archived},
        seed_documents=[str(ref) for ref in documents],
        seed_sources=[str(ref) for ref in sources],
        source_occurrence=source_occurrence,
    )
    # The one line of the record the planner cannot compute — it is a fact about the DECISION
    # and not about the page. `required=False`: this call is not the decision, so a plan
    # carrying no statement previews no reason (None) rather than quoting a note that has
    # decided nothing. What IS checked here is everything the Owner can still fix by typing
    # something else — a `statement_ref` that is not this owner speaking, a note carrying the
    # system's own machinery — because the alternative is discovering it in the job.
    reason = await _reason_line(
        ctx, user, note=note, statement_ref=statement_ref, required=False
    )

    proposal_id = uuid.uuid4().hex
    await ctx.store.create_archive_proposal(
        user,
        proposal_id,
        action=proposal.action,
        seeds={
            "documents": list(proposal.seeds_documents),
            "sources": list(proposal.seeds_sources),
        },
        # A plan's only quotable line is a `statement_ref`'s block 0 — words the Owner
        # already spoke — so the stamp beside it can only ever be `statement` here.
        items=[
            _item_dict(item, reason, REASON_SOURCE_STATEMENT if reason else None)
            for item in proposal.items
        ],
        library_ref=ref,
        # Trimmed to None the way the confirm trims its own: a box holding only spaces is a
        # box nobody typed in, and storing it would put a blank line on a listing.
        note=((note or "").strip() or None),
        statement_ref=(statement_ref or None),
    )
    row = await ctx.store.get_archive_proposal(user, proposal_id)
    if row is None:  # pragma: no cover — inserted in the same pool one statement ago
        raise ArchiveRequestError(500, "not_stored", "the proposal was not stored")
    return serialize_proposal(row, head=ref)


# --------------------------------------------------------------------------- confirm


def _apply_overrides(
    items: Sequence[Mapping[str, Any]],
    overrides: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """The stored items with `selected` replaced where the Owner ticked or unticked.

    ONLY `selected` moves. A ref the plan did not compute is refused rather than appended:
    the cascade is a computation over the library and every item carries the reason it is
    there, so an item added by hand would be a decision with no explanation behind it. The
    way to widen a cascade is to re-plan with more seeds.
    """
    result = [dict(item) for item in items]
    if not overrides:
        return result
    index = {(str(item["kind"]), str(item["ref"])): item for item in result}
    for override in overrides:
        key = (str(override.get("kind") or ""), str(override.get("ref") or ""))
        target = index.get(key)
        if target is None:
            raise ArchiveRequestError(
                422,
                "unknown_item",
                f"{key[0] or '?'} {key[1] or '?'!r} is not in this proposal; a confirm may "
                "only tick or untick what was listed. Re-plan with more seeds to widen the "
                "set.",
            )
        target["selected"] = bool(override.get("selected"))
    return result


async def confirm(
    ctx: Any,
    user_id: UserId,
    proposal_id: str,
    *,
    items_override: Sequence[Mapping[str, Any]] | None = None,
    note: str | None = None,
    statement_ref: str | None = None,
) -> dict[str, Any]:
    """Accept a proposal (optionally narrowed) and enqueue the one job that executes it.

    THE REASON IS WHAT THIS REQUEST CARRIES. `note` is the Owner's stated reason, and the
    confirm is not merely where it naturally lands — it is the only place it may come from,
    because this call IS the decision the record says they made. So the statement is the
    `note` in THIS body, or the block 0 of a `statement_ref` named here or at the plan (a
    named source is words the Owner already spoke, and naming it is itself an act). A
    confirm carrying neither is refused `422 note_required` — there is NO fallback to the
    note the row happens to hold, which was typed against a set that may since have been
    narrowed and decided nothing when it was typed.

    The note that IS sent replaces the row's, so the kept record states the words the
    decision stood on. The store keeps a `note_given` flag beside the value because silence
    and an erasure cannot share a spelling under `COALESCE` — a confirm may leave the
    plan-time note alone (informational, beside a statement) or clear it outright.

    The decision and the job are ONE TRANSACTION. Refuses 409 `not_proposed` when another
    writer reached the row first — which is what the store answering `None` means: the
    predicate `status = 'proposed'` matched nothing, so neither half was written. Anything
    else that goes wrong rolls both halves back and is an ordinary 500 over a proposal that
    is still open, which is why there is no `enqueue_failed` and nothing to undo.
    """
    assert_writable(user_id)
    user = UserId(str(user_id))

    row = await ctx.store.get_archive_proposal(user, proposal_id)
    if row is None:
        raise ArchiveRequestError(
            404, "not_found", f"archive proposal not found: {proposal_id}"
        )
    if row["status"] != STATUS_PROPOSED:
        raise ArchiveRequestError(
            409,
            "not_proposed",
            f"proposal status is {row['status']}, so it cannot be confirmed.",
        )

    head = await library_head(ctx, user)
    if head != (row.get("library_ref") or ""):
        # RECORD it, then refuse. The refusal is the moment this proposal is known to be
        # unconfirmable, and a row that answers `proposed` after it is a row that will be
        # offered for confirmation again — by this console, by a Steward, by anything
        # reading the list. The write is conditional on the row still being `proposed` for
        # the same one-winner reason every other transition here is: a confirm that lost the
        # race to a drop must not reopen the drop's row as `stale`.
        marked = await ctx.store.update_archive_proposal(
            user,
            proposal_id,
            status=STATUS_STALE,
            expected_status=STATUS_PROPOSED,
        )
        stale_row = await ctx.store.get_archive_proposal(user, proposal_id)
        if not marked:
            # The predicate matched nothing, so a concurrent confirm or drop already moved
            # this row and NOTHING here was written. Answering `stale` anyway would name a
            # status the row does not hold and hand back a proposal that is now confirmed or
            # dropped — the caller would read "re-plan" over a decision someone else made.
            # It is the same lost race the confirm below reports, and it gets the same answer.
            raise ArchiveRequestError(
                409,
                "not_proposed",
                "proposal status is "
                f"{_presented_status(stale_row, head) if stale_row is not None else 'unknown'}"
                ", so it cannot be confirmed.",
                proposal=(
                    serialize_proposal(stale_row, head=head)
                    if stale_row is not None
                    else None
                ),
            )
        raise ArchiveRequestError(
            409,
            "stale",
            "the library has changed since this plan was computed "
            f"({row.get('library_ref') or '(empty)'} → {head or '(empty)'}); the set it "
            "shows may no longer be the set that follows. Re-plan and confirm that one.",
            proposal=serialize_proposal(stale_row) if stale_row is not None else None,
        )

    items = _apply_overrides(row.get("items") or [], items_override)
    if not any(item.get("selected") for item in items):
        raise ArchiveRequestError(
            422,
            "empty",
            "nothing is selected, so this confirm would move nothing.",
        )

    # The reason is decided HERE and nowhere else. The note read is the one in THIS request —
    # never `row["note"]`, which is display text a plan happened to keep — so a confirm that
    # says nothing is refused rather than quietly standing on words typed at another moment
    # against another set. The preview kept on each item is refreshed to the line that will
    # actually be quoted, because a row whose preview said one thing while the commit quoted
    # another would be a kept record of a decision nobody made.
    #
    # A `statement_ref` may arrive here or have been named at the plan: either is the Owner
    # pointing at their own speech, and the request's own wins so a confirm can name one the
    # plan did not.
    named_statement = (statement_ref or "").strip() or None
    effective_statement = named_statement or row.get("statement_ref")
    reason = await _reason_line(
        ctx, user, note=note, statement_ref=effective_statement, required=True
    )
    # STAMPED with where the line came from, not just refreshed. The job mints an
    # `owner-dialogue/v1` source — L0 labelled as the Owner speaking — out of this string, and
    # "a confirmed row's reason is always confirm-written" was true of this code and proved by
    # nothing in the row. The stamp is the proof: `statement` when the Owner named their own
    # speech, `note` when they sent the words with this decision, and nothing else can put
    # either one there. An unstamped `reason` on a confirmed row is refused in the job.
    reason_source = (
        REASON_SOURCE_STATEMENT if effective_statement else REASON_SOURCE_NOTE
    )
    for item in items:
        record = item.get("record")
        if isinstance(record, Mapping):
            item["record"] = {
                **record,
                "reason": reason,
                "reason_source": reason_source,
            }

    # ONE TRANSACTION: the flip out of `proposed` and the job row that executes it. Two
    # statements here would have to be ordered, and both orders are a real failure mode —
    # flip-then-enqueue can leave a `confirmed` proposal nothing executes and nothing
    # reports, and enqueue-then-flip can leave a job for a decision that was never made.
    # Committed together, neither state exists, and the id the job carries is the id the row
    # records because the store minted it once for both.
    #
    # `status = 'proposed'` rides the same statement's WHERE clause, so the transition is
    # decided by the ROW and not by the read above it: two confirms in flight both read
    # `proposed`, and so does a confirm racing a drop. The loser matches nothing, writes
    # nothing, queues nothing, and is told `not_proposed` — which is what `None` means here.
    job_id = await ctx.store.confirm_archive_proposal(
        user,
        proposal_id,
        items=items,
        job_kind=ARCHIVE_JOB_KIND,
        payload={"proposal_id": proposal_id},
        # `None` says nothing about the note and leaves the plan's informational one; any
        # given string — `""` included — replaces it. `note_given` is what lets the store
        # write NULL on purpose rather than read it as silence.
        note=(note.strip() or None) if note is not None else None,
        note_given=note is not None,
        # A statement named HERE is written with the decision, in the same statement pair:
        # the job cites `statement_ref` off the row, and one that reached the queue without
        # it would mint a second `owner-dialogue/v1` source saying what the first already says.
        statement_ref=named_statement,
    )
    if job_id is None:
        raise ArchiveRequestError(
            409,
            "not_proposed",
            "this proposal is no longer awaiting a decision — another confirm or a drop "
            "reached it first — so it cannot be confirmed.",
        )
    # Read back rather than answer from what was written: the worker is a separate process
    # and nothing here waits for it, so by now the row may legitimately say `executed`.
    stored = await ctx.store.get_archive_proposal(user, proposal_id)
    return {
        "proposal": serialize_proposal(stored if stored is not None else row, head=head),
        "job_id": job_id,
    }


async def drop(ctx: Any, user_id: UserId, proposal_id: str) -> dict[str, Any]:
    """Close one proposal the Owner is not going to act on.

    Only from `proposed` or `stale`. A confirmed proposal has a job on the queue and dropping
    the row would leave that job pointing at a decision that was withdrawn — the queue is the
    thing that would have to be cancelled, and it is not this surface's to cancel. A stale
    one is the opposite case: nothing will ever execute it, so closing it is bookkeeping the
    Owner is entitled to do.

    The check is against the STORED status, which is what makes both spellings of stale
    droppable without a special case: a proposal the library outran still says `proposed` in
    the row (the API merely presents it as `stale`), and one a refused confirm wrote says
    `stale`. Both are in `DROPPABLE`, and the Owner clicking "drop" on either is doing the
    one thing left to do with it.
    """
    user = UserId(str(user_id))
    row = await ctx.store.get_archive_proposal(user, proposal_id)
    if row is None:
        raise ArchiveRequestError(
            404, "not_found", f"archive proposal not found: {proposal_id}"
        )
    if row["status"] not in DROPPABLE:
        raise ArchiveRequestError(
            409,
            "not_proposed",
            f"proposal status is {row['status']}, so it cannot be dropped.",
        )
    # `expected_status` is the status THIS call read, not a constant: a drop from `stale`
    # closes a stale row and a drop from `proposed` closes an open one, and neither may
    # close the other's — a row that went stale between the read and the write is a row
    # whose drop was decided about something else.
    moved = await ctx.store.update_archive_proposal(
        user, proposal_id, status=STATUS_DROPPED, expected_status=row["status"]
    )
    if not moved:
        # The same one-winner predicate as the confirm, from the other side: a drop that
        # lost the race to a confirm must not close a proposal that now has a job.
        raise ArchiveRequestError(
            409,
            "not_proposed",
            "this proposal is no longer awaiting a decision — a confirm or another drop "
            "reached it first — so it cannot be dropped.",
        )
    stored = await ctx.store.get_archive_proposal(user, proposal_id)
    return serialize_proposal(stored if stored is not None else row)


async def list_proposals(
    ctx: Any, user_id: UserId, *, limit: int = 50
) -> list[dict[str, Any]]:
    """This Owner's proposals, newest first, each read against the CURRENT HEAD.

    One HEAD read for the whole page, and it is what makes the listing's `proposed` count
    the number of decisions that can actually still be made: a row the library has moved
    past is presented `stale` here without anything having written to it.
    """
    user = UserId(str(user_id))
    head = await library_head(ctx, user)
    rows = await ctx.store.list_archive_proposals(user, limit=limit)
    return [serialize_proposal(row, head=head) for row in rows]


async def get_proposal(
    ctx: Any, user_id: UserId, proposal_id: str
) -> dict[str, Any]:
    user = UserId(str(user_id))
    row = await ctx.store.get_archive_proposal(user, proposal_id)
    if row is None:
        raise ArchiveRequestError(
            404, "not_found", f"archive proposal not found: {proposal_id}"
        )
    return serialize_proposal(row, head=await library_head(ctx, user))


# ------------------------------------------------------------------------- inventory


async def inventory(ctx: Any, user_id: UserId) -> dict[str, Any]:
    """What is in the archive now: documents by path with the day they went in, and sources.

    `archived_on` comes from the commit history (`written_on` over the `archive/` prefix) —
    the day that path was last written, which for a moved file is the day of the move
    commit. Nothing stores it: the move IS the record, and a side table stating the same
    fact would be one more thing that can be wrong.

    Rollover volumes are folded into their document, exactly as the proposal folds them: a
    volume is the document's own frozen history and has never been a thing of its own.

    Each row also names the RECORD the move left at the live path (`record_path`) and the
    facts that record states, read off its frontmatter. That is what lets a console show
    "this subject is archived, and here is what still answers for it" rather than a path
    with nothing on the other side of it.
    """
    user = UserId(str(user_id))
    docs = await ctx.canonical.list(user)
    written = await ctx.canonical.written_on(user, prefix=f"{ARCHIVE_ROOT}/")

    present = {doc.path for doc in docs}
    archived_docs = sorted(
        (doc for doc in docs if doc.path.startswith(f"{ARCHIVE_ROOT}/")),
        key=lambda doc: doc.path,
    )
    volume_counts: dict[str, int] = {}
    owners = []
    for doc in archived_docs:
        origin = volume_origin(doc, present)
        if origin is None:
            owners.append(doc)
        else:
            volume_counts[origin] = volume_counts.get(origin, 0) + 1

    # The RECORD standing at each archived page's live path, read off the tree by that path.
    # Nothing stores the join: the record's own `archive_of` names the copy, so the two halves
    # point at each other and a side table saying it again would be one more thing that can
    # be wrong.
    records = {
        live_path(doc.path): doc for doc in docs if is_archive_record(doc)
    }

    def _int(frontmatter: Mapping[str, Any], key: str) -> int | None:
        raw = str(frontmatter.get(key) or "").strip()
        return int(raw) if raw.isdigit() else None

    documents = []
    for doc in owners:
        row: dict[str, Any] = {
            "path": doc.path,
            "live_path": live_path(doc.path),
            "title": document_title(doc),
            "archived_on": written.get(doc.path),
            "volumes": volume_counts.get(doc.path, 0),
            "record_path": None,
            "record": None,
        }
        record = records.get(live_path(doc.path))
        if record is not None:
            frontmatter = record.frontmatter or {}
            span = str(frontmatter.get(ARCHIVE_SPAN_KEY) or "").strip()
            row["record_path"] = record.path
            row["record"] = {
                "archived_on": str(frontmatter.get(ARCHIVED_ON_KEY) or "") or None,
                "statement_ref": str(frontmatter.get(ARCHIVE_STATEMENT_KEY) or "")
                or None,
                "archive_of": str(frontmatter.get(ARCHIVE_OF_KEY) or "") or None,
                "span": span.split("/", 1) if "/" in span else None,
                "claims": _int(frontmatter, ARCHIVE_CLAIMS_KEY),
                "sources": _int(frontmatter, ARCHIVE_SOURCES_KEY),
                "volumes": _int(frontmatter, ARCHIVE_VOLUMES_KEY),
                "inbound": _int(frontmatter, ARCHIVE_INBOUND_KEY),
            }
        documents.append(row)

    sources = [
        {
            "source_id": str(raw.source_id),
            "title": raw.title,
            "kind": raw.kind,
            "archived_at": _iso(raw.archived_at),
        }
        for raw in await ctx.store.list(user)
        if raw.archived_at is not None
    ]
    return {"documents": documents, "sources": sources}


__all__ = [
    "ARCHIVE_JOB_KIND",
    "DROPPABLE",
    "STATUS_CONFIRMED",
    "STATUS_DROPPED",
    "STATUS_EXECUTED",
    "STATUS_FAILED",
    "STATUS_PROPOSED",
    "STATUS_STALE",
    "ArchiveRequestError",
    "confirm",
    "drop",
    "get_proposal",
    "inventory",
    "library_head",
    "list_proposals",
    "plan",
    "serialize_proposal",
]
