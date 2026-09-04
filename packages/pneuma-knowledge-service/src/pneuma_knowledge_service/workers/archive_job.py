"""The `archive` job: the one place anything actually moves (docs/design/archive.md §6).

It rides the per-user queue like every other canonical writer, which is the whole reason
the archive needs no lock of its own: one in-flight job per user IS the single-writer
guarantee, so a move never races a compile, a groom or an evolve adopt on the same tree.

The order below is the correctness argument, not a convenience:

1. **Re-check `library_ref`.** The confirm checked it too, but a compile can land between
   the confirm and the claim. Moving against a tree the Owner never saw would execute a set
   whose reasons no longer hold, so a drifted HEAD fails the proposal `stale` and moves
   nothing — UNLESS this proposal's own move commit is already in the history. A worker
   killed between the move commit and the terminal write is requeued on restart, and the
   drift it then sees is its own work; the `Archive-Proposal` trailer says so by name. The
   search is over the RANGE since the plan's ref, not over HEAD alone, because a writer that
   does not ride the queue (the skill manifest, written from the API process) can commit
   above the move — and a HEAD-only check would then call the job's own landed work a
   stranger's drift and strand the move with no L0 marks and no projection.
2. **The Owner's STATEMENT, before anything moves.** An archive that writes a record needs
   the evidence its reason cites, and the Owner acts on the library only by speaking
   (docs/design/steward-owner-visitor.md §1): so one `owner-dialogue/v1` source is ingested
   per proposal — the confirm-time note, or a default sentence naming the archived titles —
   through the ordinary contract path, with `canonical_treatment: none`. The record IS that
   statement's canonical expression, and a compile of the same statement would paraphrase
   the decision onto whatever pages the model thought it touched. The id is written onto the
   proposal BEFORE the move, so a job that crashes and is requeued cites the statement it
   already ingested rather than minting a second one. An Owner who named a `statement_ref`
   at plan time gets none ingested at all: they already spoke, and the record cites THAT.
3. **One commit for every document, its volumes, AND the record.** `move_documents` is
   all-or-nothing and refuses before touching anything, so a rejected move leaves canonical
   byte-for-byte. Archiving moves the page to `archive/<path>` and writes the RECORD onto the
   live path the move just vacated; unarchiving removes the record and moves the page back
   onto it. One commit either way, because the record and the move are one act: a tree in
   which the page has left and the record has not arrived is a tree in which the subject
   silently vanished, which is the state this whole mechanism exists to prevent.
4. **The L0 marks.** `sources.archived_at` is the authority for a source; it is written
   before the indexes derived from it.
5. **The derived index flags, FAIL-SOFT.** L1 and L2 are rebuildable from the two marks
   already written, so an index that will not take the flip costs a stale search face until
   the next `rebuild_derived` — never a half-executed archive with the authorities
   disagreeing about what happened. Every failure is recorded in the proposal's detail so
   the staleness is nameable rather than silent.
6. **The L3 projection**, from the new HEAD, only when something moved. The projection is
   keyed by `(document_path, anchor)`, so a move reaches the claim indexes as an ordinary
   delete-at-the-old-path + insert-at-the-new-one; nothing here has to tell it a move
   happened.

A sources-only proposal makes no commit at all — there is nothing to move — ingests no
statement and writes no record: nothing left the library's answering set, so nothing is left
behind. Steps 1, 4 and 5 still apply in full.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.archive.record import (
    record_facts_in_move,
    record_reason,
    render_record,
    run_archive_record_gate,
    sanitize_note,
    statement_quote,
)
from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.compile.runner import with_skill_trailer
from pneuma_knowledge_core.domain.archive import (
    archived_path,
    is_archive_record,
    live_path,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId, extract_anchors
from pneuma_knowledge_core.domain.intake import IntakePlan
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ingest.source_contracts import (
    OwnerDialogueSource,
    OwnerDialogueTurn,
)

from ..archive_service import (
    ARCHIVE_JOB_KIND,
    OWNER_DIALOGUE_KIND,
    STATUS_CONFIRMED,
    STATUS_EXECUTED,
    STATUS_FAILED,
    library_head,
)
from ..ingest_sources import ingest_source_contract
from ..projection import sync_projection
from ..skills import skill_for_user
from ..wiring import AppContext

_log = logging.getLogger(__name__)


class ArchiveJobError(RuntimeError):
    """A refusal the job states as the proposal's failure detail (`stale`, and its kin)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


#: The trailer the move commit carries, read back to recognize this job's own work after a
#: crash. One spelling, written by `_commit_message` and read by `_execute`.
ARCHIVE_TRAILER = "Archive-Proposal"

#: What `progress["moved"]` says when the history already carries this proposal's move: the
#: canonical half is done, and this run is finishing the steps after it. A string where the
#: ordinary value is a count, deliberately — an operator reading the detail must not mistake
#: a resumed job for one that moved nothing.
ALREADY_LANDED = "already_landed"


def _target_path(path: str, action: str) -> str:
    return archived_path(path) if action == "archive" else live_path(path)


def _moves(items: list[dict[str, Any]], action: str) -> list[tuple[str, str]]:
    """`(from, to)` for every selected document AND each of its volumes, in item order.

    A volume travels with its document because it IS the document's own frozen history; it
    is never an item of its own, and the paths stored on the item are its CURRENT ones. A
    pair that would not move (the file is already where the action wants it) is dropped
    rather than sent, so a re-run over a partly-applied state is not a refusal.
    """
    moves: list[tuple[str, str]] = []
    for item in items:
        if item.get("kind") != "document" or not item.get("selected"):
            continue
        for path in [str(item.get("ref") or ""), *(str(v) for v in item.get("volumes") or [])]:
            if not path:
                continue
            target = _target_path(path, action)
            if target != path:
                moves.append((path, target))
    return moves


def _selected_documents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The document items this proposal moves, in item order."""
    return [
        item
        for item in items
        if item.get("kind") == "document" and item.get("selected") and item.get("ref")
    ]


#: The intake this job forces on the Owner's statement. `none` because the archive RECORD is
#: already that statement's canonical expression — written mechanically, in the same commit
#: as the move, citing this very source — and a compile of the same text would paraphrase
#: the decision onto whatever pages the model believed it touched. `full` semantic indexing
#: because the statement is L0 like any other L0: searchable, addressable, quotable.
STATEMENT_INTAKE = IntakePlan(
    canonical_treatment="none",
    semantic_indexing="full",
    rationale=(
        "the owner's archive statement: its canonical expression is the archive record "
        "written in the same commit as the move, so the compile model never paraphrases "
        "the decision onto another page; fully indexed and fully addressable like any L0"
    ),
)


def _reason(row: dict[str, Any], documents: list[dict[str, Any]]) -> str:
    """The Owner's words when this job is the one minting the statement — REPLAYED, not redone.

    ONE string, used twice — it is the text of the statement source AND the text the record
    quotes — because those two must be the same sentence. It is also the third string the
    console showed the Owner in the confirm's preview, and that is why it is READ off the
    item rather than recomputed here: the confirm computed it against the set the Owner
    finally ticked and kept it on every item that writes a record
    (`archive_service._record_dict`), so preview and page are one string by construction
    instead of by two implementations agreeing. They stopped agreeing once already — an
    explicitly emptied note fell back to the plan's old one in the store, and the record
    quoted a sentence the preview had replaced.

    A row kept before the confirm refreshed that field carries no `reason`, and only then is
    the line computed here — through core's `record_reason`, the same function the request
    face uses, over the note the row holds and the titles it is still moving.
    """
    for item in documents:
        record = item.get("record")
        if isinstance(record, Mapping) and str(record.get("reason") or "").strip():
            return str(record["reason"])
    return record_reason(
        str(row.get("note") or ""),
        [str(item.get("title") or item.get("ref") or "") for item in documents],
    )


async def _statement_words(
    ctx: AppContext, user: UserId, statement_ref: str
) -> str:
    """The Owner's own words at ¶0 of the statement this record will cite — checked, then read.

    The execution-side half of the check `plan` and `confirm` already made. It is made AGAIN
    here for the reason every re-check in this job exists: the request and the execution are
    separated by a queue, and a source can be gone, or the row can have been repaired by hand,
    between them. Cheap, and the alternative is a committed claim whose citation resolves to
    something that is not the Owner speaking.

    What comes back is the block's own words, sanitized the way a note is, and the record
    quotes exactly them — so the sentence a reader quotes back is the sentence the block they
    are pointed at contains, and the one block of a record that carries a citation carries
    exactly the one the renderer appends.
    """
    try:
        source = await ctx.store.get(user, SourceId(str(statement_ref)))
    except LookupError as exc:
        raise ArchiveJobError(
            "statement_unknown",
            f"the statement this proposal cites ({statement_ref!r}) is not in this "
            "library, so there is nothing for the record's reason to rest on.",
        ) from exc
    if str(source.raw.kind) != OWNER_DIALOGUE_KIND:
        raise ArchiveJobError(
            "statement_not_owner",
            f"the statement this proposal cites ({statement_ref!r}) is a "
            f"{source.raw.kind!r} source, not {OWNER_DIALOGUE_KIND!r}; a record's reason "
            "cites the owner speaking.",
        )
    if not source.blocks:
        raise ArchiveJobError(
            "statement_unknown",
            f"the statement this proposal cites ({statement_ref!r}) carries no block, so "
            "there is nothing at ¶0 to quote.",
        )
    return sanitize_note(statement_quote(source.blocks[0].text))


def _statement_said_at(row: dict[str, Any]) -> datetime:
    """WHEN the Owner said it — the decision's own timestamp, never this job's wall clock.

    This is the whole of the statement's idempotency. `ingest_source_contract` identifies a
    source by the digest of the contract, and `ContentStore.add` dedups on that checksum: two
    ingests of the same contract are one source with one id. `datetime.now()` in the contract
    made the digest different on every attempt, so a job that crashed between the ingest and
    the write of `statement_ref` minted a SECOND statement on the retry — a second L0 source
    the Owner never made, and a first one nothing cites.

    `confirmed_at` is the honest answer as well as the stable one: the Owner said this when
    they confirmed. `created_at` stands behind it for a row from before the confirm stamped
    one, and the refusal behind that is deliberate — a proposal with no timestamp at all
    cannot produce a reproducible statement, and inventing one would put the defect back.

    BOTH are stable per proposal, which is the whole property this function needs: each is
    written once by the statement that creates or confirms the row and never rewritten
    (`create_archive_proposal` stamps `created_at`; the confirm stamps `confirmed_at`, and
    every later lifecycle write COALESCEs it). So the fallback is not a weaker answer for the
    identity — a row that has only `created_at` yields the same instant on every retry, the
    same contract, and the same source id.
    """
    for key in ("confirmed_at", "created_at"):
        value = row.get(key)
        if isinstance(value, datetime):
            return value
    raise ArchiveJobError(
        "statement_undated",
        "this proposal carries neither `confirmed_at` nor `created_at`, so the owner's "
        "statement has no reproducible time and a retry could not recognize it.",
    )


async def _ingest_statement(
    ctx: AppContext,
    user: UserId,
    proposal_id: str,
    *,
    reason: str,
    action: str,
    said_at: datetime,
) -> str:
    """Ingest ONE `owner-dialogue/v1` source carrying the Owner's reason; return its id.

    An ordinary contract import — the same `ingest_source_contract` the console calls — with
    one override: the intake plan (see `STATEMENT_INTAKE`). Nothing about this source is
    privileged; it is one owner turn, verbatim in L0, cited `[cite: <sid> ¶0]` by the
    record exactly as a chat message is cited by a claim.

    `dialogue_id` is the proposal id, so the statement and the decision address each other
    in the one scheme, and a reader of either can find the other. Every OTHER field is
    derived from the proposal too — the turn id, the metadata, and `said_at`
    (`_statement_said_at`) — so the whole contract is a function of the decision and two runs
    of this step produce one source rather than two (docs/design/archive.md §6).
    """
    contract = OwnerDialogueSource(
        schema="pneuma.source.owner-dialogue/v1",
        provider="console",
        dialogue_id=proposal_id,
        owner_id=str(user),
        turns=[
            OwnerDialogueTurn(
                turn_id=f"{proposal_id}-1",
                role="owner",
                said_at=said_at,
                text=reason,
            )
        ],
        metadata={"archive_proposal": proposal_id, "archive_action": action},
    )
    result = await ingest_source_contract(
        ctx, user, contract, intake_plan=STATEMENT_INTAKE
    )
    if not result.sources:  # pragma: no cover — one turn always normalizes to one source
        raise ArchiveJobError(
            "statement_not_stored", "the owner's archive statement was not stored"
        )
    return str(result.sources[0].source_id)


def _record_files(
    documents: Sequence[CanonicalDocument],
    items: list[dict[str, Any]],
    *,
    archived_on: str,
    statement_ref: str,
    reason: str,
    source_occurrence: dict[str, str] | None = None,
) -> dict[str, str]:
    """`live path → the record file` for every document this proposal archives.

    **The facts are computed HERE**, over the FINAL selected set and the tree this commit is
    about to change, through the same pure function the planner previewed them with
    (`record_facts_in_move`). The item's own `record` is read for one bit only: whether this
    proposal writes records at all. An item that carries none — a row planned before records
    existed, a sources-only proposal — writes none.

    Recomputed rather than replayed because the confirm's one legal override changes the
    answer. `library_ref` pins the TREE, so the numbers derived from a page cannot drift; it
    says nothing about the SET, and unticking a page that another selected page links to
    turns that page's `inbound` from "a link that is leaving too" into "a link this record is
    left holding". The kept preview then describes a move that did not happen, and the gate —
    which only checks the frontmatter against the body, both written from the same facts —
    would pass it, because both halves would be wrong together.

    The anchor seed is every anchor the WHOLE tree holds — the pages going into the archive
    included, because they keep their anchors on the other side of the move — so a record's
    three ids are unique repository-wide from the moment they are minted. `doc_id`s are
    seeded the same way, one level up.
    """
    taken = {
        anchor for doc in documents for anchor in extract_anchors(doc.body)
    }
    doc_ids = {str(doc.doc_id) for doc in documents if doc.doc_id}
    by_path = {doc.path: doc for doc in documents}
    # `path → its volumes` for the whole selected set: the ONE definition of what is leaving
    # in this commit, which is what `inbound` is counted against.
    moving = {
        str(item.get("ref")): [str(volume) for volume in item.get("volumes") or []]
        for item in items
        if item.get("ref")
    }
    files: dict[str, str] = {}
    for item in items:
        path = str(item.get("ref") or "")
        doc = by_path.get(path)
        if item.get("record") is None or doc is None:
            continue
        facts = record_facts_in_move(
            documents,
            path,
            volumes=moving.get(path, ()),
            moving=moving,
            source_occurrence=source_occurrence,
        )
        if facts is None:  # pragma: no cover — `doc` came out of the same tree
            continue
        frontmatter = doc.frontmatter or {}
        content = render_record(
            path,
            facts,
            slug=str(frontmatter.get("slug") or path.rsplit("/", 1)[-1].removesuffix(".md")),
            archived_on=archived_on,
            statement_ref=statement_ref,
            reason=reason,
            taken=taken,
        )
        record_frontmatter, record_body = parse_document(content)
        violations = run_archive_record_gate(
            path=path,
            frontmatter=record_frontmatter,
            body=record_body,
            facts=facts,
            statement_ref=statement_ref,
            # The move is a `git mv`, so the copy under `archive/` IS the page byte for byte
            # — the adapter has no way to write it otherwise. The check is here as the
            # statement of the rule, for any caller that ever builds the two apart.
            moved_body=doc.body,
            base_body=doc.body,
            repository_anchors=taken,
            repository_doc_ids=doc_ids,
        )
        if violations:
            raise ArchiveJobError(
                "record_rejected",
                "the archive record was refused: "
                + "; ".join(v.render() for v in violations),
            )
        files[path] = content
        taken.update(extract_anchors(record_body))
        doc_ids.add(str(record_frontmatter.get("doc_id") or ""))
    return files


def _retired_anchors(
    documents: Sequence[CanonicalDocument], removals: Sequence[str]
) -> set[str]:
    """The anchors of the records this run REMOVES — retired on purpose, not lost.

    Handed to the projection so its loss guardrail does not read the replacement of a record
    by the page it stood in for as knowledge being destroyed. The record's three blocks carry
    no permanent identity — the page whose identity they stood in for is back — which is the
    same standing an overview region's anchors have, and the reason the guardrail exempts
    those too. Only this channel can name them, so this channel declares them.
    """
    by_path = {doc.path: doc for doc in documents}
    return {
        str(anchor)
        for path in removals
        if path in by_path
        for anchor in extract_anchors(by_path[path].body)
    }


def _record_removals(
    documents: Sequence[CanonicalDocument], items: list[dict[str, Any]]
) -> list[str]:
    """The record paths an UNARCHIVE removes: the live path each returning page lands on.

    Only a path that actually holds a record is named. A page archived before records existed
    left none behind, and a removal of a path holding nothing would refuse the whole move.
    """
    by_path = {doc.path: doc for doc in documents}
    out: list[str] = []
    for item in items:
        target = live_path(str(item.get("ref") or ""))
        doc = by_path.get(target)
        if doc is not None and is_archive_record(doc):
            out.append(target)
    return out


def _selected_sources(items: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("ref") or "")
        for item in items
        if item.get("kind") == "source" and item.get("selected") and item.get("ref")
    ]


def _commit_message(action: str, proposal_id: str, moves: int, skill: Any) -> str:
    """The move commit: the ordinary skill trailer plus the proposal that decided it.

    `Archive-Proposal` sits in the same trailer block as `Skill-Version`, so
    `git log --format=%(trailers:key=Archive-Proposal,valueonly)` reads back which decision
    produced any commit in the history — the archive's half of the audit chain, free from
    git like the rest of it.
    """
    verb = "archive" if action == "archive" else "unarchive"
    subject = f"{verb} {moves} document{'s' if moves != 1 else ''}"
    return with_skill_trailer(subject, skill) + f"\n{ARCHIVE_TRAILER}: {proposal_id}"


async def _execute(
    ctx: AppContext,
    user: UserId,
    proposal_id: str,
    row: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    """Apply one confirmed proposal; `progress` is filled IN PLACE as steps land.

    In place so that a failure after the move commit still names the ref it produced: the
    authoritative marks that did land are part of what happened, and a failure detail that
    hid them would leave the owner reading a `failed` proposal over a tree that moved.
    """
    action = str(row.get("action") or "archive")
    items = [dict(item) for item in (row.get("items") or [])]

    planned = str(row.get("library_ref") or "")
    head = await library_head(ctx, user)
    landed_at: SnapshotRef | None = None
    if head != planned:
        # HEAD drifted. Two different things look identical from here — a compile landed
        # under the confirm, or THIS job already committed its move and died before it could
        # record it (the queue requeues a `claimed` job on worker restart). The commit itself
        # tells them apart: the move carries `Archive-Proposal: <id>`.
        #
        # The question is asked of the RANGE `planned..HEAD`, not of HEAD alone. HEAD alone
        # would be right only if nothing could commit above the move, and something can: the
        # skill manifest is written from the API process, off the queue. A manifest write
        # landing on top of a crashed job's move would otherwise make the requeued job read a
        # stranger's commit at HEAD, fail `stale`, and leave canonical moved with the L0
        # marks and the projection never written. Searching the range finds the job's own
        # commit wherever it sits under the newer ones.
        #
        # Failing `stale` there would be the worse of two wrong answers, so a found commit is
        # treated as done and the rest of the sequence runs — every step after it is
        # idempotent by construction (`set_source_archived` sets or clears a column, the
        # index flips write the same flag, the projection is re-derived from a ref).
        landed_at = await ctx.canonical.find_commit_with_trailer(
            user,
            key=ARCHIVE_TRAILER,
            value=proposal_id,
            since=SnapshotRef(ref=planned) if planned else None,
        )
        if landed_at is None:
            raise ArchiveJobError(
                "stale",
                "the library moved between the confirm and this job "
                f"({row.get('library_ref') or '(empty)'} → {head or '(empty)'}); nothing was "
                "moved. Re-plan against the current tree.",
            )

    detail = progress
    detail.update({"action": action, "proposal_id": proposal_id})
    # Declared by this channel and by nothing else: the anchors of a record it is about to
    # replace with the page that record stood in for. Empty on every other path.
    retired: set[str] = set()

    # 2 + 3. the statement and the canonical commit — or no commit at all for a sources-only
    # proposal, or none because the commit is already in the tree and this is a resumed job.
    if landed_at is not None:
        _log.warning(
            "archive: proposal %s for user %s already has its move commit at %s "
            "(HEAD is now %s); resuming after it",
            proposal_id,
            user,
            landed_at.ref,
            head,
        )
        detail["moved"] = ALREADY_LANDED
        # The detail names THIS proposal's own commit, which is what an operator reconciles
        # the tree against; HEAD may be someone else's commit standing above it.
        ref = landed_at.ref
        # The tree the PLAN was computed over — the state the landed commit changed, and the
        # only place a resumed run can read what that commit did. Read on BOTH actions: an
        # unarchive needs the anchors its move retired (below), and an archive needs to say
        # how many records the commit wrote, which is a question about the same tree.
        planned_documents = await ctx.canonical.list(
            user, at=SnapshotRef(ref=planned) if planned else None
        )
        selected = _selected_documents(items)
        if action == "archive":
            # Reconstructed, not remembered: `_record_files` writes one record per selected
            # item that carries a `record` preview AND stood in the plan-time tree, so the
            # same two conditions over the same inputs give the same number. Nothing is
            # re-rendered — the commit is already in the history and this is a count.
            present = {doc.path for doc in planned_documents}
            records_written = sum(
                1
                for item in selected
                if item.get("record") is not None
                and str(item.get("ref") or "") in present
            )
            records_removed = 0
        else:
            # The projection still has to be told which anchors this move RETIRED, and the
            # resumed run cannot see them: they belonged to records the landed commit already
            # removed, so they are in neither HEAD nor the new claim set — only in the tree
            # the plan was computed over. Read them from there. Without this, the one step
            # left to run is the one that refuses: an unarchive of a page whose record held
            # more than half the projected ledger reads as knowledge being destroyed, and the
            # job that already moved everything fails on its last step, forever, on every
            # requeue.
            landed_removals = _record_removals(planned_documents, selected)
            retired = _retired_anchors(planned_documents, landed_removals)
            records_written = 0
            records_removed = len(landed_removals)
    else:
        ref = ""
        moves = _moves(items, action)
        writes: dict[str, str] = {}
        removals: list[str] = []
        if moves:
            # The tree PINNED to the plan's own ref, which is HEAD here (the drift branch
            # above either failed `stale` or took the resume path). Pinned rather than
            # floating, because everything derived from it — the record's facts, its anchor
            # seed, which live paths hold a record — has to describe the tree this commit is
            # about to change and not one that moved under the read.
            documents = await ctx.canonical.list(
                user, at=SnapshotRef(ref=planned) if planned else None
            )
            selected = _selected_documents(items)
            if action != "archive":
                # Unarchiving REPLACES the record with the page it stood in for. No new
                # statement: the owner is undoing a decision, not making a second one, and
                # the record that quoted the first one goes with it — its anchors declared
                # RETIRED to the projection rather than counted as knowledge lost.
                removals = _record_removals(documents, selected)
                retired = _retired_anchors(documents, removals)
            elif any(item.get("record") for item in selected):
                # 2. the owner's statement, BEFORE the move. Written onto the proposal in the
                # same step, so a crash between here and the commit leaves a statement this
                # job will cite rather than a second one it would mint on the retry.
                #
                # Guarded on there being a RECORD to write, and that is the whole condition:
                # the statement exists to be the evidence the record's reason cites, so a
                # proposal that writes none — a sources-only one, or a row planned before
                # records existed — ingests none. A statement nothing cites would be L0 the
                # owner never asked for.
                statement_ref = str(row.get("statement_ref") or "").strip()
                if statement_ref:
                    # A statement that already exists — the Owner named one at plan time, or
                    # THIS job ingested it and died before the commit. Either way the record
                    # quotes the source it cites, read back from ¶0 and checked to be the
                    # owner speaking; a note beside it is informational and may not disagree.
                    reason = await _statement_words(ctx, user, statement_ref)
                    typed = sanitize_note(str(row.get("note") or ""))
                    if typed and typed != reason:
                        raise ArchiveJobError(
                            "statement_mismatch",
                            f"the note and the statement {statement_ref!r} say different "
                            f"things; the statement's first block says {reason!r}, and a "
                            "record quotes the source it cites.",
                        )
                else:
                    reason = _reason(row, selected)
                    statement_ref = await _ingest_statement(
                        ctx,
                        user,
                        proposal_id,
                        reason=reason,
                        action=action,
                        said_at=_statement_said_at(row),
                    )
                    # Written onto the row IMMEDIATELY, before anything else can fail. The
                    # contract is derived from the proposal, so a retry re-ingests the same
                    # bytes and the checksum dedup answers with the SAME source id — but the
                    # row saying so is what makes the retry cite it rather than re-derive it.
                    saved = await ctx.store.update_archive_proposal(
                        user,
                        proposal_id,
                        status=STATUS_CONFIRMED,
                        statement_ref=statement_ref,
                        expected_status=STATUS_CONFIRMED,
                    )
                    if not saved:
                        # The predicate lost, so NOTHING was written and the row no longer
                        # names the statement its record is about to cite. Continuing to the
                        # commit is the one unacceptable answer: the move would land quoting
                        # a source the decision does not mention, the terminal write would
                        # lose the same predicate and record nothing, and the audit chain
                        # from proposal to statement to record would have a hole in it that
                        # no later run can close. Refusing here moves nothing at all.
                        raise ArchiveJobError(
                            "statement_ref_unsaved",
                            f"the owner's statement ({statement_ref!r}) was ingested, but "
                            "this proposal was no longer `confirmed` when its id was "
                            "written back, so nothing was saved and nothing was moved. The "
                            "statement stands in L0 and a re-run of this decision cites it "
                            "rather than minting a second one.",
                        )
                detail["statement_ref"] = statement_ref
                # The day each source is ABOUT, for the record's span. L0's to state, so it
                # is read here and handed to the pure computation, exactly as the planner
                # does at plan time.
                writes = _record_files(
                    documents,
                    selected,
                    archived_on=datetime.now(timezone.utc).date().isoformat(),
                    statement_ref=statement_ref,
                    reason=reason,
                    source_occurrence={
                        str(raw.source_id): raw.occurred_on()
                        for raw in await ctx.store.list(user)
                    },
                )
            skill = await skill_for_user(ctx, user)
            snapshot = await ctx.canonical.move_documents(
                user,
                moves,
                message=_commit_message(action, proposal_id, len(moves), skill),
                writes=writes,
                removals=removals,
            )
            ref = snapshot.ref
        detail["moved"] = len(moves)
        records_written = len(writes)
        records_removed = len(removals)
    # Named separately from the moves and from each other: an operator reading a detail has
    # to be able to see that a subject left a page behind, or that a restore took one away,
    # without inferring it from the action.
    #
    # ALWAYS BOTH, ZERO INCLUDED, ON EVERY PATH — the RESUME included. Emitting a count only
    # when it is non-zero made the two cases an operator most needs to tell apart look
    # identical: unarchiving a page that was archived before records existed leaves NO record
    # to remove, and unarchiving a page whose record removal never ran leaves one behind —
    # and neither detail said anything at all. Emitting them only off the non-resume path put
    # the same hole back for exactly the run an operator is most likely to be reading: the
    # one that crashed. A count that is always there answers the question; an absent key only
    # says the key is absent.
    #
    # `archive_records_*` rather than `records_*` because "record" is already taken in
    # operator output: `rebuild_derived` replays KEPT RECORDS (consultations), and one
    # maintenance log carrying both had the same word meaning two things.
    detail["archive_records_written"] = records_written
    detail["archive_records_removed"] = records_removed
    detail["ref"] = ref
    if retired:
        detail["archive_records_retired_anchors"] = len(retired)
    # The projection is a re-derivation of the CURRENT library, so it runs from HEAD when
    # this job is resuming — a projection built from the move commit alone would drop
    # whatever a writer above it has since put in the tree.
    projection_ref = head if landed_at is not None else ref

    # 4 + 5. the L0 mark, then the two derived index flags that are read off it.
    archived = action == "archive"
    index_failures: list[str] = []
    sources = _selected_sources(items)
    # Progress is written INSIDE the loop, per source, because a failure halfway through it
    # is exactly the case the detail has to survive: `sources_marked` names which L0 marks
    # landed, so a `failed` proposal is legible against the authorities as they now stand
    # rather than as a count that was never reached. A list appended after each mark, not a
    # tally computed after the loop.
    marked: list[str] = []
    detail["sources_marked"] = marked
    detail["sources"] = 0
    for sid in sources:
        source_id = SourceId(sid)
        await ctx.store.set_source_archived(user, source_id, archived)
        marked.append(sid)
        detail["sources"] = len(marked)
        try:
            block_count = len((await ctx.store.get(user, source_id)).blocks)
            await ctx.lexical.set_source_archived(
                user, source_id, block_count, archived
            )
        except Exception as exc:  # noqa: BLE001 — derived, rebuildable; see the docstring
            index_failures.append(f"lexical {sid}: {type(exc).__name__}: {exc}")
            _log.warning("archive: lexical flip failed for %s: %s", sid, exc)
        try:
            await ctx.vectors.set_source_archived(user, source_id, archived)
        except Exception as exc:  # noqa: BLE001
            index_failures.append(f"vectors {sid}: {type(exc).__name__}: {exc}")
            _log.warning("archive: vector flip failed for %s: %s", sid, exc)
    if index_failures:
        detail["index_failures"] = index_failures

    # 6. L3, from the tree the move produced. A failure here is NOT fail-soft the way the
    # index flips are — the projection is how the move reaches the claim indexes at all —
    # so it is named in place and re-raised: the proposal ends `failed`, and its detail
    # still carries the `ref` the move produced and every L0 mark that landed beside it.
    if projection_ref:
        try:
            projection = await sync_projection(
                ctx, user, projection_ref, retired_anchors=retired
            )
        except Exception as exc:
            detail["projection_error"] = f"{type(exc).__name__}: {exc}"
            raise
        detail["projected"] = projection.total
    return detail


_NOT_CONFIRMED = "the proposal was no longer confirmed; its row was left as it stands"


async def _record_terminal(
    ctx: AppContext,
    user: UserId,
    proposal_id: str,
    status: str,
    detail: dict[str, Any],
    *,
    executed_at: datetime | None,
) -> bool:
    """Write the proposal's terminal state, but only onto a row that is still `confirmed`.

    The predicate is what keeps the lifecycle monotonic. Anything that moved the row while
    the job ran — a lifecycle write this process did not make, a hand-edited row, an
    operator's repair — has a claim on it that a finished job does not get to overwrite: the
    row would otherwise read `executed` over a decision that is no longer the one that ran.

    A lost predicate is NOT an error to raise: the archive itself already happened, the
    canonical commit is in the tree, and failing the job would say the opposite. So the loss
    is logged, returned, and named in the job's completion detail — the one place an
    operator can see that the work landed while the row did not follow it.
    """
    recorded = await ctx.store.update_archive_proposal(
        user,
        proposal_id,
        status=status,
        executed_at=executed_at,
        detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
        expected_status=STATUS_CONFIRMED,
    )
    if not recorded:
        _log.warning(
            "archive: proposal %s for user %s was not %r at its terminal write "
            "(%s); the work landed and the row was left as it stands",
            proposal_id,
            user,
            STATUS_CONFIRMED,
            status,
        )
    return recorded


async def run_archive_job(ctx: AppContext, user_id: UserId, job: object) -> None:
    """Run one confirmed archive proposal. Never raises: it records, then completes the job."""
    payload = getattr(job, "payload", {}) or {}
    job_id = getattr(job, "job_id")
    proposal_id = str(payload.get("proposal_id", ""))
    user = UserId(str(user_id))

    row = await ctx.store.get_archive_proposal(user, proposal_id)
    if row is None:
        await ctx.store.complete(
            user, job_id, ok=False, detail=f"archive: no proposal {proposal_id!r}"
        )
        return
    if row["status"] != STATUS_CONFIRMED:
        # Not a failure of the proposal — it is a job for a decision that is not (or is no
        # longer) awaiting execution, so the row is left exactly as it stands.
        await ctx.store.complete(
            user,
            job_id,
            ok=False,
            detail=f"archive: proposal status is {row['status']}, not confirmed",
        )
        return

    progress: dict[str, Any] = {}
    try:
        detail = await _execute(ctx, user, proposal_id, row, progress)
    except Exception as exc:  # noqa: BLE001 — every failure is the proposal's, and stated
        code = exc.code if isinstance(exc, ArchiveJobError) else type(exc).__name__
        failure = {**progress, "error": code, "message": str(exc)}
        recorded = await _record_terminal(
            ctx, user, proposal_id, STATUS_FAILED, failure, executed_at=None
        )
        await ctx.store.complete(
            user,
            job_id,
            ok=False,
            detail=f"archive: {exc}"
            + ("" if recorded else f" [{_NOT_CONFIRMED}]"),
        )
        return

    recorded = await _record_terminal(
        ctx,
        user,
        proposal_id,
        STATUS_EXECUTED,
        detail,
        executed_at=datetime.now(timezone.utc),
    )
    if not recorded:
        detail = {**detail, "proposal_write": _NOT_CONFIRMED}
    await ctx.store.complete(
        user,
        job_id,
        ok=True,
        detail=f"archive:{json.dumps(detail, ensure_ascii=False, sort_keys=True)}",
        snapshot_ref=str(detail.get("ref") or "") or None,
    )


__all__ = ["ARCHIVE_JOB_KIND", "ArchiveJobError", "run_archive_job"]
