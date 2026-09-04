"""The archive API: propose, confirm, drop, and what is in the archive now.

docs/design/archive.md §5. Every endpoint here is about the Owner's judgement of attention,
and none of them moves anything: `confirm` enqueues one `archive` job onto the same per-user
queue the compiler drains, and the move happens there under the single-writer guarantee.

The refusals are the interesting part and they all come from `archive_service` as one
exception type, rendered by the handler in `api/app.py`:

- `409 stale` — HEAD moved since the plan. The set the Owner saw was computed over a tree
  that has since changed, so it is a preview of something else. Re-plan.
- `409 not_proposed` — already confirmed, executed, failed or dropped.
- `422 unknown_item` — a confirm naming a ref the plan did not compute. An override may
  only tick and untick what was listed; widening a cascade is a re-plan with more seeds.
- `422 empty` — nothing selected, so the confirm would move nothing.
- `422 note_machinery` — a note carrying the system's own machinery (an HTML comment, an
  `__AUTO__`). The note is quoted into a claim, so its text is words.
- `422 statement_unknown` / `422 statement_not_owner` — a `statement_ref` this library does
  not hold, or one that is not an `owner-dialogue/v1` source with a block to quote.
- `422 statement_mismatch` — a note and a `statement_ref` saying different things. The record
  quotes the source it cites, so one of the two has to go.
- `422 note_required` — a CONFIRM carrying neither a non-blank `note` nor a `statement_ref`
  (here or on the proposal). The reason is recorded as the owner's own `owner-dialogue/v1`
  statement, so it can only be words the owner wrote at the decision: the framework composes
  none on their behalf, and neither does a note left on the proposal, which decided nothing
  when it was typed. `plan` therefore does not require one at all — its `note` is
  informational — and the console answers the friction by prefilling a suggestion in its own
  box, which the owner edits and SENDS with the confirm.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pneuma_knowledge_core.domain.ids import UserId
from pydantic import BaseModel, Field

from ...archive_service import (
    ArchiveRequestError,
    confirm,
    drop,
    get_proposal,
    inventory,
    list_proposals,
    plan,
)
from ...wiring import AppContext
# The ONE user-id pattern this surface accepts, read from where it is already stated rather
# than copied — a second spelling of it is a second thing that can drift.
from .v1 import _USER_ID_RE

router = APIRouter(prefix="/v1/users/{user_id}")


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _user(user_id: str) -> UserId:
    if not _USER_ID_RE.match(user_id or ""):
        raise HTTPException(status_code=422, detail=f"invalid user_id: {user_id!r}")
    return UserId(user_id)


# ------------------------------------------------------------------------- wire shapes


class ProposalReasonOut(BaseModel):
    #: Live document paths that still cite this source (the `still_cited` evidence).
    cited_by_live: list[str] = []
    #: ARCHIVED document paths that cite this source — the unarchive direction's evidence,
    #: and the reason a source is selected under `restored_with_page`: these are the pages
    #: that bring it back with them (archive.md §5). One field per side of the library, and
    #: the split is not cosmetic: without this one, FastAPI silently stripped it out of the
    #: response model, so a console rendering the reason beside the checkbox was shown an
    #: empty `cited_by_live` and a note it had no evidence for.
    cited_by_archived: list[str] = []
    #: `[cited, total]` ledger claims — the document's dependence on the selected sources.
    dependence: list[int] | None = None
    #: A short mechanical code: seed | orphaned | still_cited | restored_with_page |
    #: fully_dependent | partially_dependent | already_archived | already_live | unknown.
    note: str = ""


class RecordPreviewOut(BaseModel):
    """The ARCHIVE RECORD this document would leave behind at its live path.

    Computed at plan time by the pure planner, so the console shows the owner the page each
    checkbox creates before anything moves — and the job writes exactly these numbers, since
    a confirm is refused unless HEAD is still the HEAD the plan was computed over.
    """

    #: The page's own name, which the record keeps.
    title: str = ""
    #: The page's `definition`, its `ledger:` line, or its title — whichever it has. Never
    #: generated: the record states what the page said about itself.
    definition: str = ""
    #: `[first, last]` `occurred_on` over the sources the page's claims cite, or null when no
    #: cited source states a day. Omitted from the record's line rather than guessed.
    span: list[str] | None = None
    claims: int = 0
    sources: int = 0
    volumes: int = 0
    #: Live pages, outside the set this proposal moves, that link to this one.
    inbound: int = 0
    #: The exact sentence the record's third block will quote, under the citation naming the
    #: owner's statement — always the OWNER'S OWN WORDS. On a PLAN it is the block 0 of a
    #: supplied `statement_ref`, and NULL when none was named: a plan decides nothing, so it
    #: previews no sentence of its own and the console shows the live content of its note box
    #: instead. On the kept row after a confirm it is the line that decision stood on, and
    #: the job quotes exactly it.
    reason: str | None = None
    #: Where that sentence came from — `statement` (block 0 of a `statement_ref` the owner
    #: named) or `note` (the words sent with the confirm). Null exactly when `reason` is.
    #: It is the record's PROVENANCE, and it is stamped rather than inferred: the job mints
    #: an `owner-dialogue/v1` source — L0 labelled as the owner speaking — out of `reason`,
    #: and refuses (`statement_missing`) a reason arriving without this stamp rather than
    #: trusting that whatever wrote the row followed the rule.
    reason_source: Literal["note", "statement"] | None = None


class ProposalItemOut(BaseModel):
    kind: Literal["document", "source"]
    ref: str
    title: str = ""
    role: Literal["seed", "cascade"]
    selected: bool
    reason: ProposalReasonOut
    #: A document's rollover volumes, at their CURRENT paths. They move with it.
    volumes: list[str] = []
    #: The record this document would leave behind. Only ever on a `document` item of an
    #: `archive` proposal: an unarchive REPLACES the record with the page it stood in for,
    #: and a source leaves nothing behind at all.
    record: RecordPreviewOut | None = None


class ProposalSeedsOut(BaseModel):
    documents: list[str] = []
    sources: list[str] = []


class ArchiveProposalOut(BaseModel):
    proposal_id: str
    action: str
    status: str
    #: The canonical HEAD the closure was computed against. A confirm against a different
    #: HEAD is refused `stale`.
    library_ref: str = ""
    note: str | None = None
    statement_ref: str | None = None
    seeds: ProposalSeedsOut
    items: list[ProposalItemOut]
    created_at: str | None = None
    confirmed_at: str | None = None
    executed_at: str | None = None
    job_id: str | None = None
    detail: str | None = None


class ProposeIn(BaseModel):
    action: Literal["archive", "unarchive"] = "archive"
    #: Document paths, in either spelling — a live path off the glance or an archived one
    #: off `GET /archive` both name the same subject.
    documents: list[str] = []
    sources: list[str] = []
    #: An informational line kept on the proposal for a listing to display. NOT a reason and
    #: never a statement: the record's reason is the note sent with the CONFIRM, because that
    #: request is the decision the record says the Owner made. Optional, therefore, and a
    #: plan carrying none is computed all the same.
    note: str | None = Field(default=None, max_length=2000)
    #: Optionally the `owner-dialogue/v1` source in which the Owner asked for this — the
    #: proposal's provenance in the one addressing scheme, and the other way to satisfy the
    #: reason requirement.
    statement_ref: str | None = None


class ItemOverrideIn(BaseModel):
    kind: Literal["document", "source"]
    ref: str
    selected: bool


class ConfirmIn(BaseModel):
    #: Per-item `selected` overrides. Only `selected` may change and only for a ref the plan
    #: already computed; to ADD to a cascade, re-plan with more seeds.
    items: list[ItemOverrideIn] | None = None
    #: The Owner's reason, in their own words — REQUIRED (non-blank) unless a
    #: `statement_ref` is named here or on the proposal. This is the sentence the record
    #: quotes and the owner-dialogue source it cites, so it can only be words sent with the
    #: decision: absent or blank it is `422 note_required`, and the note the plan happens to
    #: hold is never a fallback. Given, it replaces that note on the kept row.
    note: str | None = Field(default=None, max_length=2000)
    #: Optionally the `owner-dialogue/v1` source in which the Owner asked for this, when it
    #: was not named at the plan. Its block 0 becomes the reason and the note beside it is
    #: informational (and may not disagree — `422 statement_mismatch`).
    statement_ref: str | None = None


class ConfirmOut(BaseModel):
    proposal: ArchiveProposalOut
    job_id: str


class ArchivedRecordOut(BaseModel):
    """What the record standing at the live path states, read off its own frontmatter."""

    archived_on: str | None = None
    #: The `owner-dialogue/v1` source the record's reason cites.
    statement_ref: str | None = None
    #: The full copy the record points at — the other half of the pair.
    archive_of: str | None = None
    span: list[str] | None = None
    claims: int | None = None
    sources: int | None = None
    volumes: int | None = None
    inbound: int | None = None


class ArchivedDocumentOut(BaseModel):
    path: str
    live_path: str
    title: str
    #: The day the path was last written — for a moved file, the day of the move commit.
    archived_on: str | None = None
    #: How many rollover volumes travelled with it (they are not listed separately).
    volumes: int = 0
    #: Where the RECORD stands. Equal to `live_path` whenever one was written; null for a
    #: page archived before records existed, which left nothing behind.
    record_path: str | None = None
    record: ArchivedRecordOut | None = None


class ArchivedSourceOut(BaseModel):
    source_id: str
    title: str
    kind: str
    archived_at: str | None = None


class ArchiveInventoryOut(BaseModel):
    documents: list[ArchivedDocumentOut]
    sources: list[ArchivedSourceOut]


# ---------------------------------------------------------------------------- routes


@router.post("/archive/proposals", response_model=ArchiveProposalOut)
async def propose_archive(
    user_id: str, body: ProposeIn, request: Request
) -> dict[str, Any]:
    """Compute and keep one proposal: the seeds plus everything that follows from them.

    Nothing moves. The response lists the whole computed set — selected and merely listed —
    with the mechanical reason for each item, and `library_ref` names the library state it
    was computed over.
    """
    if not body.documents and not body.sources:
        raise HTTPException(
            status_code=422,
            detail="name at least one document or source to archive.",
        )
    return await plan(
        _ctx(request),
        _user(user_id),
        action=body.action,
        documents=body.documents,
        sources=body.sources,
        note=body.note,
        statement_ref=body.statement_ref,
    )


@router.get("/archive/proposals", response_model=list[ArchiveProposalOut])
async def list_archive_proposals(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """This Owner's proposals, newest first — a kept record of what was decided and when."""
    return await list_proposals(_ctx(request), _user(user_id), limit=limit)


@router.get("/archive/proposals/{proposal_id}", response_model=ArchiveProposalOut)
async def get_archive_proposal(
    user_id: str, proposal_id: str, request: Request
) -> dict[str, Any]:
    return await get_proposal(_ctx(request), _user(user_id), proposal_id)


@router.post(
    "/archive/proposals/{proposal_id}/confirm",
    response_model=ConfirmOut,
    status_code=202,
)
async def confirm_archive_proposal(
    user_id: str, proposal_id: str, request: Request, body: ConfirmIn | None = None
) -> dict[str, Any]:
    """Accept a proposal (optionally narrowed) and enqueue the job that executes it."""
    overrides = (
        [item.model_dump() for item in body.items]
        if body is not None and body.items is not None
        else None
    )
    return await confirm(
        _ctx(request),
        _user(user_id),
        proposal_id,
        items_override=overrides,
        note=body.note if body is not None else None,
        statement_ref=body.statement_ref if body is not None else None,
    )


@router.post("/archive/proposals/{proposal_id}/drop", response_model=ArchiveProposalOut)
async def drop_archive_proposal(
    user_id: str, proposal_id: str, request: Request
) -> dict[str, Any]:
    """Close one proposal the Owner is not going to act on. Only from `proposed`."""
    return await drop(_ctx(request), _user(user_id), proposal_id)


@router.get("/archive", response_model=ArchiveInventoryOut)
async def get_archive(user_id: str, request: Request) -> dict[str, Any]:
    """What is in the archive now: documents with the day they went in, and sources."""
    return await inventory(_ctx(request), _user(user_id))


__all__ = ["ArchiveRequestError", "router"]
