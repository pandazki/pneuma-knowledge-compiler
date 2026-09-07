"""`pkc archive …` — the archive at the Steward's door (§5.5).

The mechanism is upstream and is stated once, in `docs/design/archive.md`: archiving is a
MOVE under `archive/` plus a short record left standing at the old path, a source is marked
by `archived_at`, nothing is ever deleted, and the set is COMPUTED and then CONFIRMED against
one library state. Nothing here adds to that. Every command calls the same `archive_service`
function the HTTP route calls — never over HTTP — and prints what it answered.

What this module does add is the two rules the Steward posture needs beyond the wire, and
both are refusals made before anything is computed:

- **The reason is the Owner's words, and it is sent with the DECISION.** The record's third
  block QUOTES somebody (archive.md §2.3), and that somebody is never the framework: there is
  no default sentence anywhere any more — `archive_service` refuses a confirm carrying
  neither a note nor a `statement_ref` (`422 note_required`) and the job refuses one
  defensively (`statement_missing`). So this door refuses the same confirm before it asks the
  service, in words that name the command a Steward reaches for: `pkc owner say`. A propose
  is NOT held to it — a plan decides nothing and quotes nothing, and its `--note-file` is
  informational — so the words are gathered where they are used.
- **Seeds by default; the cascade is asked for.** The planner computes what FOLLOWS from the
  seeds, and what follows is not what the Owner named. So a confirm ticks the `seed` items
  and unticks every `cascade` one unless `--cascade` says otherwise. Both are listed either
  way — a Steward that confirmed less than it showed would be hiding the closure it was
  handed.

Exit codes are `pkc`'s: 0 ok · 1 no such proposal · 2 refused (the service's own refusal
text, the missing-words refusal, a paraphrase inside a console Steward session).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from pneuma_knowledge_core.archive.record import RecordFacts, facts_line
from pneuma_knowledge_core.domain.ids import UserId

from ..archive_service import (
    STATUS_PROPOSED,
    STATUS_STALE,
    ArchiveRequestError,
    confirm,
    drop,
    get_proposal,
    inventory,
    list_proposals,
    plan,
)
from .owner import owner_said, steward_session

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2

#: The statuses a decision is still open under — `proposed`, and the `stale` a refused confirm
#: wrote (which is droppable and nothing else). Read from the service rather than spelled
#: again: what "still open" means is that module's to say.
OPEN = (STATUS_PROPOSED, STATUS_STALE)

#: The refusal that makes this door the Steward's rather than the console's. It names the
#: command that produces the thing it asks for, because the sequence is the answer: the
#: Owner says it, `pkc owner say` records it and prints the source id, and that id is what
#: `--statement` takes.
NEED_OWNER_WORDS = (
    "refused: say why. The archive records the reason as the owner's own statement — an "
    "`owner-dialogue/v1` source the record then cites — so it can only be words the owner "
    "wrote AT THIS DECISION. Record what they said with `pkc owner say --text-file -` and "
    "pass the source id it prints as `--statement <sid>`, or give the same words with "
    "`--note-file <f>`. A note left on the proposal is not one: it was typed against a set "
    "that may since have changed."
)

#: The same rule `pkc owner say` enforces, said about this text. Inside the console's Steward
#: session the bridge holds the transcript, so a note is checkable — and a note is quoted into
#: a claim on a live page, which is exactly what the check exists for.
NOT_VERBATIM = (
    "refused: inside a console Steward session, an archive note records the OWNER's words. "
    "This text is not a verbatim substring of anything the owner typed in this session "
    "(whitespace aside), and a paraphrase of the owner is not the owner's reason. Quote "
    "them, or name their statement with `--statement <sid>`."
)

#: The structured `reason.note` of an item, in words. The planner computes a machine code and
#: the console renders it beside a checkbox; a Steward reads a line, so the code is spelled
#: out here — one sentence per code, with the evidence the reason carries interpolated into
#: it. The vocabulary is the planner's (`archive/proposal.py`), and a code this table does not
#: know is printed as itself rather than swallowed.
REASON_WORDS = {
    "seed": "the owner named it",
    "orphaned": "no live page cites it any more",
    "still_cited": "still cited by {cited_by_live}",
    "restored_with_page": "comes back with {cited_by_archived}",
    "fully_dependent": "every one of its {total} ledger claims rests on the selected sources",
    "partially_dependent": (
        "{cited} of its {total} ledger claims rest on the selected sources"
    ),
    "already_archived": "already in the archive",
    "already_live": "already live",
    "unknown": "this library does not hold it",
}


def _emit(payload: Any, lines: Sequence[str], *, as_json: bool, out: TextIO) -> None:
    """One state, two renderings — the read commands' rule, restated here.

    `--json` prints the SERVICE's own shape, which is the wire's shape: a workflow branching
    on `pkc archive show --json` and one reading `GET /archive/proposals/{id}` are reading
    the same bytes, so nothing here can describe a proposal the API does not.
    """
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=out)
    else:
        for line in lines:
            print(line, file=out)


def _refused(exc: ArchiveRequestError, err: TextIO) -> int:
    """The service's own refusal, in the service's own words. 404 is `pkc`'s exit 1."""
    print(str(exc), file=err)
    return EXIT_NOTHING if exc.status_code == 404 else EXIT_REFUSED


# ──────────────────────────────────────────────────────────── the owner's words


async def _owner_words(
    ctx: Any,
    user_id: UserId,
    *,
    statement_ref: str | None,
    note: str | None,
    err: TextIO,
    required: bool,
) -> tuple[bool, str | None]:
    """`(ok, note)` — the door's precondition, checked before anything is computed.

    Two ways to say the same thing and both are the Owner's: a `--statement` naming the
    `owner-dialogue/v1` source they spoke in (checked by the service, which resolves the
    block the record will cite), or a `--note-file` carrying their words. Neither is a
    refusal; both together are legal and are compared by the service, which refuses
    `statement_mismatch` rather than picking one.

    `required` is the CONFIRM, and it is the same question `archive_service._reason_line`
    asks with the same answer (`note_required`): that request IS the decision the record says
    the Owner made, so the words have to arrive on it. Said here as well as there because a
    Steward gathers them with a command — `pkc owner say` — and a refusal that names it is
    the difference between the door and the wire; the service's own refusal still surfaces
    verbatim as exit 2 when a request gets past this check (a note that sanitizes to nothing).
    A PROPOSE passes `required=False`: a plan decides nothing, quotes nothing and keeps its
    note as display text, so demanding the Owner's words there would ask for them at a moment
    that cannot use them.
    """
    if required and not statement_ref and not note:
        print(NEED_OWNER_WORDS, file=err)
        return (False, None)
    session = steward_session()
    if note and session and not await owner_said(ctx, user_id, session, note):
        print(NOT_VERBATIM, file=err)
        return (False, None)
    return (True, note)


# ─────────────────────────────────────────────────────────────────── rendering


def _reason_words(reason: Mapping[str, Any]) -> str:
    """One item's structured reason, in words."""
    note = str(reason.get("note") or "")
    template = REASON_WORDS.get(note)
    if template is None:
        return note
    dependence = reason.get("dependence") or [0, 0]
    return template.format(
        cited_by_live=", ".join(reason.get("cited_by_live") or []) or "no live page",
        cited_by_archived=", ".join(reason.get("cited_by_archived") or [])
        or "no archived page",
        cited=int(dependence[0]),
        total=int(dependence[1]),
    )


def _record_lines(record: Mapping[str, Any]) -> list[str]:
    """The record this item would leave at the live path, as its three blocks read.

    The facts line comes from the record channel's OWN renderer (`facts_line`) over the
    preview's numbers, so what the Steward shows the Owner is the sentence the page will
    carry rather than a second arrangement of the same figures.
    """
    facts = RecordFacts.from_dict(record)
    lines = [f"      record: {str(record.get('definition') or '').strip()}"]
    if facts is not None:
        lines.append(f"              {facts_line(facts)}")
    # The reason AND where it came from. The service stamps `reason_source` on the row rather
    # than leaving it to be inferred (`archive_service._record_dict`), and the job refuses a
    # reason arriving without it — so a Steward reading this line reads the same provenance
    # the commit will stand on. A plan quotes nothing of its own: `reason` is null until the
    # confirm carries the words, and saying so is what stops a Steward showing the Owner a
    # sentence nobody has written yet.
    reason = str(record.get("reason") or "").strip()
    if reason:
        lines.append(f"              reason: «{reason}»{_reason_provenance(record)}")
    else:
        lines.append(
            "              reason: the words sent with `pkc archive confirm` "
            "(--note-file <f>, or the --statement this proposal names)"
        )
    return lines


def _reason_provenance(record: Mapping[str, Any]) -> str:
    """Where the quoted line came from, in words — `statement` or `note`, and nothing else."""
    source = str(record.get("reason_source") or "")
    if source == "statement":
        return "  (the owner's statement, first block)"
    if source == "note":
        return "  (the owner's words, sent with the confirm)"
    return ""


def _item_lines(item: Mapping[str, Any]) -> list[str]:
    """One item: what it is, what it is called, why it is here, and whether it is ticked."""
    mark = "[x]" if item.get("selected") else "[ ]"
    volumes = item.get("volumes") or []
    lines = [
        f"  {mark} {str(item.get('kind') or ''):<8} {item.get('ref')}  "
        f"{str(item.get('role') or ''):<7} {item.get('title') or ''}"
        + (f"  (+{len(volumes)} closed volume(s))" if volumes else ""),
        f"      why: {_reason_words(item.get('reason') or {})}",
    ]
    record = item.get("record")
    if isinstance(record, Mapping):
        lines += _record_lines(record)
    return lines


def _proposal_lines(proposal: Mapping[str, Any]) -> list[str]:
    lines = [
        f"proposal {proposal.get('proposal_id')}  {proposal.get('action')}  "
        f"{proposal.get('status')}",
        f"library: {proposal.get('library_ref') or '(empty)'}",
    ]
    if proposal.get("statement_ref"):
        lines.append(f"statement: {proposal['statement_ref']}")
    if proposal.get("note"):
        lines.append(f"note: {proposal['note']}")
    if proposal.get("job_id"):
        lines.append(f"job: {proposal['job_id']}")
    if proposal.get("detail"):
        lines.append(f"detail: {proposal['detail']}")
    for item in proposal.get("items") or []:
        lines += _item_lines(item)
    return lines


def _cascade_note(proposal: Mapping[str, Any]) -> list[str]:
    """What a confirm would leave behind, said where the Owner can still ask for it."""
    waiting = [
        str(item.get("ref"))
        for item in proposal.get("items") or []
        if item.get("selected") and str(item.get("role")) == "cascade"
    ]
    if not waiting:
        return []
    return [
        "",
        f"{len(waiting)} item(s) follow from what the owner named and are NOT confirmed "
        "unless the owner says so: " + ", ".join(waiting),
        "confirm them together with `pkc archive confirm <id> --cascade`.",
    ]


# ─────────────────────────────────────────────────────────────────── commands


async def cmd_archive_propose(
    ctx: Any,
    user_id: UserId,
    *,
    action: str = "archive",
    documents: Sequence[str] = (),
    sources: Sequence[str] = (),
    statement_ref: str | None = None,
    note: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Compute one proposal and print it whole. Nothing moves."""
    out = out or sys.stdout
    err = err or sys.stderr
    if not documents and not sources:
        print(
            "name at least one page (`--document <path>`) or source (`--source <id>`)",
            file=err,
        )
        return EXIT_REFUSED
    ok, note = await _owner_words(
        ctx, user_id, statement_ref=statement_ref, note=note, err=err, required=False
    )
    if not ok:
        return EXIT_REFUSED
    try:
        proposal = await plan(
            ctx,
            user_id,
            action=action,
            documents=list(documents),
            sources=list(sources),
            note=note,
            statement_ref=statement_ref,
        )
    except ArchiveRequestError as exc:
        return _refused(exc, err)
    _emit(
        proposal,
        _proposal_lines(proposal) + _cascade_note(proposal),
        as_json=as_json,
        out=out,
    )
    return EXIT_OK


async def cmd_archive_ls(
    ctx: Any,
    user_id: UserId,
    *,
    limit: int = 50,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """This Owner's proposals, newest first — `stale` computed against the current HEAD."""
    out = out or sys.stdout
    err = err or sys.stderr
    rows = await list_proposals(ctx, user_id, limit=limit)
    if not rows:
        print("no archive proposal has been made in this library", file=err)
        return EXIT_NOTHING
    _emit(
        {"proposals": rows},
        [
            f"{row['proposal_id']}  {str(row['action']):<9} {str(row['status']):<9} "
            f"{len([i for i in row.get('items') or [] if i.get('selected')])} selected"
            for row in rows
        ],
        as_json=as_json,
        out=out,
    )
    return EXIT_OK


async def cmd_archive_show(
    ctx: Any,
    user_id: UserId,
    proposal_id: str,
    *,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """One proposal, whole: the status as it reads NOW, every item, and the job when queued."""
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        proposal = await get_proposal(ctx, user_id, proposal_id)
    except ArchiveRequestError as exc:
        return _refused(exc, err)
    payload = dict(proposal)
    lines = _proposal_lines(proposal)
    state = await _job_state(ctx, user_id, proposal.get("job_id"))
    if state is not None:
        payload["job_status"] = state
        lines.append(f"job status: {state}")
    # The cascade note is advice about a decision that can still be made, so it is printed
    # for a proposal that is still open and for no other.
    if str(proposal.get("status")) in OPEN:
        lines += _cascade_note(proposal)
    _emit(payload, lines, as_json=as_json, out=out)
    return EXIT_OK


async def _job_state(ctx: Any, user_id: UserId, job_id: Any) -> str | None:
    """The queue's own word on the job a confirm queued, when the store can answer it.

    Read defensively: `get_job` is the Postgres store's, and a stand-in that carries only the
    archive tables is a legitimate context to run this command against — a proposal reads the
    same either way, minus one line.
    """
    if not job_id:
        return None
    reader = getattr(ctx.store, "get_job", None)
    if reader is None or not callable(reader):
        return None
    job = await reader(user_id, str(job_id))
    if job is None:
        return None
    return str(getattr(job, "status", "") or "") or None


async def cmd_archive_drop(
    ctx: Any,
    user_id: UserId,
    proposal_id: str,
    *,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Close one proposal nobody is going to act on. Only from `proposed` or `stale`."""
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        proposal = await drop(ctx, user_id, proposal_id)
    except ArchiveRequestError as exc:
        return _refused(exc, err)
    _emit(
        proposal,
        [f"proposal {proposal['proposal_id']} {proposal['status']}"],
        as_json=as_json,
        out=out,
    )
    return EXIT_OK


async def cmd_archive_confirm(
    ctx: Any,
    user_id: UserId,
    proposal_id: str,
    *,
    cascade: bool = False,
    deselect: Sequence[str] = (),
    statement_ref: str | None = None,
    note: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Accept a proposal — the seeds alone unless `--cascade` — and queue the one job.

    The overrides are computed HERE and applied by the service's own `_apply_overrides`, which
    only ever ticks and unticks what the plan already computed. So the narrowing this posture
    performs is the same narrowing the console performs with a checkbox: nothing is added, and
    widening a set is a re-plan with more seeds.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    ok, note = await _owner_words(
        ctx, user_id, statement_ref=statement_ref, note=note, err=err, required=True
    )
    if not ok:
        return EXIT_REFUSED
    try:
        proposal = await get_proposal(ctx, user_id, proposal_id)
    except ArchiveRequestError as exc:
        return _refused(exc, err)

    if statement_ref:
        # The statement is named at PLAN time — it is what the record's third block cites,
        # and the plan validated it against L0 then. A confirm may only name the same one:
        # accepting a different id here would either quote a statement the kept proposal does
        # not name, or ingest a second copy of words the library already holds.
        named = str(proposal.get("statement_ref") or "")
        if named != statement_ref:
            print(
                f"refused: this proposal names {named or 'no statement'}, and the statement "
                f"the record cites is fixed when the set is computed. Re-plan with "
                f"`pkc archive propose … --statement {statement_ref}`, or confirm this one "
                "with the owner's words as `--note-file <f>`.",
                file=err,
            )
            return EXIT_REFUSED

    items = list(proposal.get("items") or [])
    index = {str(item.get("ref")): item for item in items}
    unticked = [ref for ref in deselect if str(ref) not in index]
    if unticked:
        print(
            f"refused: {', '.join(unticked)} — not in this proposal; `--deselect` unticks "
            "what the plan listed. It lists: " + ", ".join(index),
            file=err,
        )
        return EXIT_REFUSED

    overrides = [
        {"kind": item["kind"], "ref": item["ref"], "selected": False}
        for item in items
        if item.get("selected")
        and (
            str(item.get("ref")) in {str(ref) for ref in deselect}
            or (not cascade and str(item.get("role")) == "cascade")
        )
    ]
    try:
        result = await confirm(
            ctx,
            user_id,
            proposal_id,
            items_override=overrides or None,
            note=note,
        )
    except ArchiveRequestError as exc:
        return _refused(exc, err)
    confirmed = result["proposal"]
    lines = _proposal_lines(confirmed) + [
        "",
        f"queued {result['job_id']} — the move happens on this library's own queue, next to "
        "the compiler, so it never races one.",
    ]
    _emit(result, lines, as_json=as_json, out=out)
    return EXIT_OK


async def cmd_archive_inventory(
    ctx: Any,
    user_id: UserId,
    *,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """What is in the archive NOW: pages with the day they went in, and sources."""
    out = out or sys.stdout
    err = err or sys.stderr
    found = await inventory(ctx, user_id)
    documents = found.get("documents") or []
    sources = found.get("sources") or []
    if not documents and not sources:
        print("nothing in this library is archived", file=err)
        return EXIT_NOTHING
    lines: list[str] = []
    for row in documents:
        lines.append(
            f"{row['path']}  {row.get('archived_on') or '(unknown day)'}  "
            f"{row.get('title') or ''}"
            + (f"  (+{row['volumes']} closed volume(s))" if row.get("volumes") else "")
        )
        # WHERE THE SUBJECT STILL ANSWERS. The record is a live page standing at the vacated
        # path (archive.md §2.3), so the pair of paths is the whole of what the archive did:
        # the detail moved, the subject did not leave.
        lines.append(
            f"  record: {row.get('record_path') or '(none — archived before records existed)'}"
        )
    for row in sources:
        lines.append(
            f"{row['source_id']}  {row.get('archived_at') or ''}  "
            f"{str(row.get('kind') or ''):<18} {row.get('title') or ''}"
        )
    _emit(found, lines, as_json=as_json, out=out)
    return EXIT_OK


__all__ = [
    "NEED_OWNER_WORDS",
    "NOT_VERBATIM",
    "cmd_archive_confirm",
    "cmd_archive_drop",
    "cmd_archive_inventory",
    "cmd_archive_ls",
    "cmd_archive_propose",
    "cmd_archive_show",
]
