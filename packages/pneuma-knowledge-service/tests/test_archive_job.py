"""The `archive` job: what it moves, in what order, and what it does when a step refuses.

docs/design/archive.md §6. The order is the correctness argument — canonical first, then the
L0 mark, then the two derived index flags, then L3 — so the sequence itself is asserted here
rather than only its outcome. The derived flips are fail-soft on purpose: L1 and L2 are
rebuildable from the marks already written, and an index that will not take the flip must
never leave the two authorities disagreeing about what happened.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import (
    CanonicalDirtyError,
    CanonicalMoveError,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_service.workers import archive_job as archive_job_module
from pneuma_knowledge_service.workers.archive_job import run_archive_job

USER = UserId("u-archive-job")


def _item(
    kind: str, ref: str, *, selected: bool = True, volumes=(), record=None
) -> dict:
    item = {
        "kind": kind,
        "ref": ref,
        "title": ref,
        "role": "seed",
        "selected": selected,
        "reason": {"cited_by_live": [], "dependence": None, "note": "seed"},
        "volumes": list(volumes),
    }
    if record is not None:
        item["record"] = record
    return item


#: The line the CONFIRM computed and kept on every item that writes a record. Not a preview
#: like the numbers beside it: the job quotes this string rather than recomputing one, so the
#: page and what the Owner confirmed are one string by construction.
KEPT_REASON = "the reason the confirm kept"


def _record(title: str = "Aurora", **overrides) -> dict:
    """The record the planner computed for a document item, as the confirm kept it.

    The NUMBERS are deliberately wrong for `PAGE`: they are a preview, and the job recomputes
    every fact at execution over the final selected set and the tree at `library_ref` — so
    what they decide is only WHETHER this proposal writes a record at all (a row planned
    before records existed carries none and writes none).

    `reason` is the exception, and it is authoritative. It is a fact about the DECISION
    rather than about the page, computed at the confirm against the set the Owner finally
    ticked, and the job replays it. It travels with `reason_source`, the confirm's STAMP
    saying which of the two legal provenances it came from — the note sent with the confirm,
    or a `statement_ref` the Owner named — because the job may not mint the Owner's speech
    out of a line whose origin nothing in the row states. Pass `reason=None` for a row that
    kept none, or `reason_source=None` for one written before the stamp existed.
    """
    facts = {
        "title": title,
        "definition": f"{title} is the programme the team ran.",
        "span": ["2026-01-04", "2026-06-30"],
        "claims": 4,
        "sources": 2,
        "volumes": 1,
        "inbound": 3,
        "reason": KEPT_REASON,
        "reason_source": "note",
    }
    facts.update(overrides)
    if facts.get("reason") is None:
        facts.pop("reason")
    if facts.get("reason_source") is None:
        facts.pop("reason_source", None)
    return facts


def _owner_statement(text: str) -> SimpleNamespace:
    """One `owner-dialogue/v1` source as L0 answers it: the owner's turn line at ¶0."""
    return SimpleNamespace(
        raw=SimpleNamespace(kind="owner_dialogue"),
        blocks=[
            SimpleNamespace(
                text=prompt(
                    "ingest.turn_line", label=prompt("ingest.owner_label"), text=text
                )
            )
        ],
    )


#: The decision's own timestamp. Not decoration: it is what the Owner's statement is dated
#: with, and therefore what makes two runs of the statement step produce ONE source.
CONFIRMED_AT = datetime(2026, 9, 4, 11, 30, tzinfo=timezone.utc)


def _row(items, *, action="archive", status="confirmed", library_ref="sha-1") -> dict:
    return {
        "proposal_id": "p-1",
        "action": action,
        "seeds": {"documents": [], "sources": []},
        "items": items,
        "library_ref": library_ref,
        "status": status,
        "note": None,
        "statement_ref": None,
        "created_at": CONFIRMED_AT,
        "confirmed_at": CONFIRMED_AT,
        "executed_at": None,
        "job_id": "job-1",
        "detail": None,
    }


class _Ctx:
    """Every port the job touches, recording one ordered call log."""

    def __init__(self, row: dict, *, head: str = "sha-1") -> None:
        self.calls: list[tuple] = []
        self.row = row
        self.head = head
        self.move_error: CanonicalMoveError | None = None
        #: ref → the `Archive-Proposal` trailer on that commit. The one way a job can tell
        #: "the library moved under me" from "this is my own move commit, and I died before
        #: I could record it".
        self.trailers: dict[str, str] = {}
        #: The history above the plan's ref, NEWEST FIRST. `None` means "just HEAD", which is
        #: the shape every test that predates the range search wants; a test about a writer
        #: that committed on top of the move sets the list.
        self.commits: list[str] | None = None
        #: Runs inside `move_documents`, standing in for whatever else could reach the row
        #: while the job is running — the one window the terminal predicate is about.
        self.during_move = None
        #: Runs at the START of every `update_archive_proposal`, before its predicate is
        #: judged. The same window one step earlier: a lifecycle write this process did not
        #: make can land while the job is between its ingest and its commit.
        self.on_proposal_write = None
        self.lexical_error: Exception | None = None
        self.completed: list[tuple] = []
        #: The canonical tree the job reads to render records and to find the records an
        #: unarchive removes. Empty by default: most of these tests are about the ORDER of
        #: the steps, and a proposal whose items carry no `record` writes no record.
        self.documents: list = []
        #: What the one `move_documents` call was handed beside its moves.
        self.writes: dict[str, str] = {}
        self.removals: list[str] = []
        #: L0 as this job reads it: `source_id → the stored source`, for the statement the
        #: record cites (its kind and its block 0 are both checked) and for the block count
        #: the lexical flip needs.
        self.sources: dict[str, Any] = {}
        #: The source inventory the record's SPAN is computed from — L0's to state.
        self.raw_sources: list = []
        #: Source ids L0 does not hold — the `statement_unknown` case.
        self.missing_sources: set[str] = set()

        outer = self

        class _Canonical:
            async def snapshots_page(self, user_id, *, limit, after_ref=None):
                return ([SnapshotRef(ref=outer.head)], 1, False) if outer.head else ([], 0, False)

            async def commit_trailer(self, user_id, ref, key):
                return outer.trailers.get(ref.ref) if key == "Archive-Proposal" else None

            async def find_commit_with_trailer(self, user_id, *, key, value, since=None):
                # The range the adapter walks: newest-first, EXCLUSIVE of `since`.
                history = outer.commits if outer.commits is not None else [outer.head]
                for sha in history:
                    if since is not None and sha == since.ref:
                        break
                    if sha and key == "Archive-Proposal" and outer.trailers.get(sha) == value:
                        return SnapshotRef(ref=sha)
                return None

            async def list(self, user_id, *, at=None):
                return list(outer.documents)

            async def move_documents(
                self, user_id, moves, *, message, writes=None, removals=()
            ):
                outer.calls.append(("move", list(moves), message))
                outer.writes = dict(writes or {})
                outer.removals = list(removals)
                if outer.during_move is not None:
                    outer.during_move()
                if outer.move_error is not None:
                    raise outer.move_error
                return SnapshotRef(ref="sha-moved")

        class _Store:
            async def get_archive_proposal(self, user_id, proposal_id):
                return dict(outer.row) if proposal_id == outer.row["proposal_id"] else None

            async def update_archive_proposal(
                self, user_id, proposal_id, *, status, expected_status=None, **kw
            ):
                outer.calls.append(("proposal", status))
                if outer.on_proposal_write is not None:
                    outer.on_proposal_write()
                if expected_status is not None and outer.row["status"] != expected_status:
                    return False
                outer.row["status"] = status
                for key, value in kw.items():
                    if value is not None:
                        outer.row[key] = value
                return True

            async def set_source_archived(self, user_id, source_id, archived):
                outer.calls.append(("l0", str(source_id), archived))

            async def get(self, user_id, source_id):
                if str(source_id) in outer.sources:
                    return outer.sources[str(source_id)]
                if str(source_id) in outer.missing_sources:
                    raise KeyError(str(source_id))
                return SimpleNamespace(
                    raw=SimpleNamespace(kind="conversation"),
                    blocks=[SimpleNamespace(text=f"b{i}") for i in range(3)],
                )

            async def list(self, user_id):
                return list(outer.raw_sources)

            async def complete(self, user_id, job_id, *, ok=True, detail=None, snapshot_ref=None):
                outer.completed.append((job_id, ok, detail, snapshot_ref))

        class _Lexical:
            async def set_source_archived(self, user_id, source_id, block_count, archived):
                outer.calls.append(("l1", str(source_id), block_count, archived))
                if outer.lexical_error is not None:
                    raise outer.lexical_error

        class _Vectors:
            async def set_source_archived(self, user_id, source_id, archived):
                outer.calls.append(("l2", str(source_id), archived))

        self.canonical = _Canonical()
        self.store = _Store()
        self.lexical = _Lexical()
        self.vectors = _Vectors()


@pytest.fixture
def stubbed(monkeypatch):
    """The two collaborators that would otherwise reach git and three real indexes."""

    async def fake_skill(ctx, user):
        return SimpleNamespace(
            version="v1", skill_id="s-1", content_hash="deadbeef", path_templates=()
        )

    async def fake_sync(ctx, user, ref, **kwargs):
        ctx.calls.append(("l3", ref))
        return SimpleNamespace(total=7)

    monkeypatch.setattr(archive_job_module, "skill_for_user", fake_skill)
    monkeypatch.setattr(archive_job_module, "sync_projection", fake_sync)


@pytest.fixture
def stubbed_statement(stubbed, monkeypatch):
    """`stubbed`, plus the Owner-statement ingest — a real contract import otherwise.

    The stub records the CONTRACT and the intake override it was handed, because those two
    are the whole of what this job promises about the statement: one owner turn carrying the
    reason, and `canonical_treatment: none` so the compile model never paraphrases the
    decision onto another page.
    """
    seen: list[tuple] = []

    async def fake_ingest(ctx, user, contract, *, intake_plan=None):
        seen.append((contract, intake_plan))
        return SimpleNamespace(
            contract_schema=contract.contract_schema,
            sources=[SimpleNamespace(source_id="src-statement")],
        )

    monkeypatch.setattr(archive_job_module, "ingest_source_contract", fake_ingest)
    return seen


def _canonical(path: str, body: str, **frontmatter: str):
    return CanonicalDocument(
        doc_id=DocumentId("d-1"),
        path=path,
        frontmatter={"doc_id": "d-1", "type": "topic", "slug": "aurora", **frontmatter},
        body=body,
    )


PAGE = _canonical(
    "work/aurora.md",
    "# Aurora\n\n- Aurora ships fortnightly. [cite: src-a ¶0] <!-- c:aaaa0001 -->\n",
)


def _job() -> SimpleNamespace:
    return SimpleNamespace(job_id="job-1", payload={"proposal_id": "p-1"})


# ------------------------------------------------------------------ the happy order


async def test_the_sequence_is_canonical_then_l0_then_the_index_flags_then_l3(stubbed):
    ctx = _Ctx(
        _row(
            [
                _item("document", "work/aurora.md", volumes=["work/aurora/a01.md"]),
                _item("source", "src-a"),
            ]
        )
    )

    await run_archive_job(ctx, USER, _job())

    kinds = [call[0] for call in ctx.calls]
    assert kinds == ["move", "l0", "l1", "l2", "l3", "proposal"]

    _, moves, message = ctx.calls[0]
    # The document AND its volume, each to the archive path — one commit for the whole set.
    assert moves == [
        ("work/aurora.md", "archive/work/aurora.md"),
        ("work/aurora/a01.md", "archive/work/aurora/a01.md"),
    ]
    # The ordinary skill trailer, plus the decision that produced this commit.
    assert "Skill-Version: v1" in message
    assert message.endswith("Archive-Proposal: p-1")

    assert ctx.calls[1] == ("l0", "src-a", True)
    assert ctx.calls[2] == ("l1", "src-a", 3, True)  # block count read off L0, the authority
    assert ctx.calls[3] == ("l2", "src-a", True)
    assert ctx.calls[4] == ("l3", "sha-moved")

    assert ctx.row["status"] == "executed"
    detail = json.loads(ctx.row["detail"])
    assert detail == {
        "action": "archive",
        "moved": 2,
        # Both record counts are stated even at zero — this proposal predates records and
        # writes none, and an absent key would read the same as a write that never ran.
        "archive_records_written": 0,
        "archive_records_removed": 0,
        "proposal_id": "p-1",
        "projected": 7,
        "ref": "sha-moved",
        "sources": 1,
        # Named, not counted: which L0 marks landed is what a failure has to be read
        # against, so the successful detail carries the same field.
        "sources_marked": ["src-a"],
    }
    job_id, ok, _detail, snapshot_ref = ctx.completed[0]
    assert (job_id, ok, snapshot_ref) == ("job-1", True, "sha-moved")


async def test_unarchive_is_the_same_move_with_the_pairs_reversed(stubbed):
    ctx = _Ctx(
        _row(
            [_item("document", "archive/work/aurora.md"), _item("source", "src-a")],
            action="unarchive",
        )
    )
    await run_archive_job(ctx, USER, _job())

    assert ctx.calls[0][1] == [("archive/work/aurora.md", "work/aurora.md")]
    assert ctx.calls[1] == ("l0", "src-a", False)
    assert ctx.calls[3] == ("l2", "src-a", False)
    assert ctx.row["status"] == "executed"


async def test_a_sources_only_proposal_makes_no_commit_and_no_projection(stubbed):
    ctx = _Ctx(_row([_item("source", "src-a"), _item("source", "src-b")]))

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["l0", "l1", "l2", "l0", "l1", "l2", "proposal"]
    detail = json.loads(ctx.row["detail"])
    assert detail["moved"] == 0 and detail["ref"] == "" and detail["sources"] == 2
    assert detail["sources_marked"] == ["src-a", "src-b"]
    assert "projected" not in detail  # nothing moved, so nothing to re-project
    assert ctx.completed[0][3] is None


async def test_an_unselected_item_is_left_where_it_is(stubbed):
    ctx = _Ctx(
        _row(
            [
                _item("document", "work/aurora.md"),
                _item("source", "src-a"),
                _item("source", "src-b", selected=False),
            ]
        )
    )
    await run_archive_job(ctx, USER, _job())
    assert [call for call in ctx.calls if call[0] == "l0"] == [("l0", "src-a", True)]


# ------------------------------------------------------------------- the refusals


async def test_a_refused_move_fails_the_proposal_and_touches_no_index(stubbed):
    ctx = _Ctx(_row([_item("document", "work/aurora.md"), _item("source", "src-a")]))
    ctx.move_error = CanonicalMoveError(
        "destination path already exists", "archive/work/aurora.md"
    )

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["move", "proposal"]
    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["error"] == "CanonicalMoveError"
    assert "archive/work/aurora.md" in detail["message"]
    assert ctx.completed[0][1] is False


async def test_a_library_holding_somebody_else_s_changes_fails_canonical_dirty(stubbed):
    """The adapter refused to discard uncommitted work it could not prove was its own, and
    the job STATES that rather than burying it under a class name.

    One code across every face (`canonical_dirty`), because the fix is one command and the
    operator has to be able to find it: the proposal's `error`, the job's completion detail
    and the API's 409 body all spell it the same way. Nothing moved, so the proposal is
    `failed` over a tree that is byte-for-byte what it was and the same decision runs again
    once the library is clean.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md"), _item("source", "src-a")]))
    ctx.move_error = CanonicalDirtyError(["work/aurora.md", "work/scratch.md"])

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["move", "proposal"]
    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["error"] == "canonical_dirty"
    assert "work/scratch.md" in detail["message"]
    # …and the job's own completion STARTS WITH the machine form. The shared worker's branch
    # for this fault completes with exactly `exc.detail`, and this job is the one kind that
    # does not pass through it (it has a proposal row to fail first): an `archive: ` PREFIX
    # here would make one fault two strings depending on which job met it. The contract is
    # therefore the prefix — which is what leaves room for the one honest suffix below.
    assert ctx.completed[0][1] is False
    assert ctx.completed[0][2].startswith("canonical_dirty:")
    assert ctx.completed[0][2].startswith(
        CanonicalDirtyError(["work/aurora.md", "work/scratch.md"]).detail
    )
    # Nothing else here, because the terminal write kept its predicate.
    assert ctx.completed[0][2] == "canonical_dirty:work/aurora.md,work/scratch.md"
    # No L0 mark, no index flip: the authorities were never touched.
    assert [call[0] for call in ctx.calls if call[0] in ("l0", "l1", "l2", "l3")] == []


async def test_a_dirty_library_whose_row_moved_still_leads_with_canonical_dirty(stubbed):
    """The contract is the PREFIX, and this is the one case that needs it to be.

    A terminal write that lost its predicate is a second fact about the same failure — the
    work's row was moved by somebody else while the job ran — and it is appended rather than
    dropped: an operator told only `canonical_dirty` over a row that says `dropped` would
    have no way to see the two are one event. Suppressing the suffix to keep the string
    byte-exact would be trading a true statement for a tidy one. The grep still works,
    because what every reader matches on is the front of the string.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]))
    ctx.during_move = lambda: ctx.row.update(status="dropped")
    ctx.move_error = CanonicalDirtyError(["work/aurora.md"])

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "dropped"
    job_id, ok, detail, _ref = ctx.completed[-1]
    assert (job_id, ok) == ("job-1", False)
    assert detail.startswith("canonical_dirty:work/aurora.md")
    assert "no longer confirmed" in detail


async def test_a_library_that_moved_since_the_confirm_fails_stale_and_moves_nothing(
    stubbed,
):
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]), head="sha-2")

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["proposal"]
    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "stale"
    assert ctx.completed[0][1] is False


async def test_a_requeued_job_resumes_after_its_own_commit(stubbed):
    """A worker killed between the move commit and the terminal write is requeued, and the
    drift it then sees is ITS OWN WORK.

    Failing `stale` there would be the worst available answer: the move stands in the tree,
    and the proposal would end `failed` over it with the L0 marks and the projection that
    belong with it never written. The commit's `Archive-Proposal` trailer names the decision
    that produced it, so the job recognizes its own move, skips it, and finishes the steps
    after it — every one of which is idempotent.
    """
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md"), _item("source", "src-a")]),
        head="sha-moved",
    )
    ctx.trailers["sha-moved"] = "p-1"

    await run_archive_job(ctx, USER, _job())

    # No `move` at all — and everything after it ran, against the commit that is already in.
    assert [call[0] for call in ctx.calls] == ["l0", "l1", "l2", "l3", "proposal"]
    assert ("l3", "sha-moved") in ctx.calls
    assert ctx.row["status"] == "executed"
    detail = json.loads(ctx.row["detail"])
    assert detail["moved"] == "already_landed"  # not `0`: a resume is not an empty move
    assert detail["ref"] == "sha-moved"
    assert detail["sources_marked"] == ["src-a"]
    assert ctx.completed[0][1] is True
    assert ctx.completed[0][3] == "sha-moved"


async def test_a_foreign_commit_above_the_move_still_resumes(stubbed):
    """The skill manifest is written from the API process, off the queue — so a commit that
    is nobody's archive can land ON TOP of a crashed job's move.

    Reading HEAD's trailer alone would call the job's own landed work a stranger's drift,
    fail the proposal `stale`, and leave canonical moved with no L0 mark and no projection.
    The job searches the range since the plan's ref instead, so the move is found under the
    manifest write and the steps after it run.
    """
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md"), _item("source", "src-a")]),
        head="sha-manifest",
    )
    ctx.commits = ["sha-manifest", "sha-moved"]  # newest first, above the plan's `sha-1`
    ctx.trailers["sha-moved"] = "p-1"

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["l0", "l1", "l2", "l3", "proposal"]
    detail = json.loads(ctx.row["detail"])
    assert detail["moved"] == "already_landed"
    # The detail names THIS proposal's commit, which is what the tree is reconciled against.
    assert detail["ref"] == "sha-moved"
    # The projection is a re-derivation of the CURRENT library, so it runs from HEAD — the
    # manifest write standing above the move is part of the tree it must reflect.
    assert ("l3", "sha-manifest") in ctx.calls
    assert ctx.row["status"] == "executed"
    assert ctx.completed[0][1] is True


async def test_only_foreign_commits_since_the_plan_is_stale(stubbed):
    """No commit in the range carries this proposal's trailer, so nothing of its own ever
    landed: the drift is real and the proposal fails `stale`, having moved nothing."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]), head="sha-manifest")
    ctx.commits = ["sha-manifest", "sha-compile"]
    ctx.trailers["sha-compile"] = "p-someone-else"

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["proposal"]
    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "stale"


async def test_a_head_carrying_someone_else_s_commit_is_still_stale(stubbed):
    """Only THIS proposal's trailer means "my own work". A compile — or another archive —
    that landed under the confirm is the drift the check exists for."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]), head="sha-2")
    ctx.trailers["sha-2"] = "p-someone-else"

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["proposal"]
    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "stale"


async def test_an_index_flip_that_fails_is_recorded_and_does_not_undo_the_marks(stubbed):
    """L1 and L2 are DERIVED. A flip that will not land costs a stale search face until the
    next rebuild — never a half-executed archive, and never a silent one."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md"), _item("source", "src-a")]))
    ctx.lexical_error = RuntimeError("meili is down")

    await run_archive_job(ctx, USER, _job())

    assert [call[0] for call in ctx.calls] == ["move", "l0", "l1", "l2", "l3", "proposal"]
    assert ctx.row["status"] == "executed"
    failures = json.loads(ctx.row["detail"])["index_failures"]
    assert failures == ["lexical src-a: RuntimeError: meili is down"]
    assert ctx.completed[0][1] is True


async def test_a_proposal_that_was_never_confirmed_is_not_executed(stubbed):
    ctx = _Ctx(_row([_item("document", "work/aurora.md")], status="proposed"))

    await run_archive_job(ctx, USER, _job())

    assert ctx.calls == []  # the row is left exactly as it stands
    assert ctx.row["status"] == "proposed"
    assert ctx.completed[0][1] is False


async def test_a_job_for_a_proposal_that_is_gone_completes_without_raising(stubbed):
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]))
    job = SimpleNamespace(job_id="job-1", payload={"proposal_id": "missing"})

    await run_archive_job(ctx, USER, job)

    assert ctx.calls == []
    assert ctx.completed[0][1] is False


async def test_a_failure_after_the_move_still_names_the_ref_it_produced(stubbed):
    """The move commit is authoritative the moment it lands. A later step that raises turns
    the proposal `failed`, but the detail must still carry the ref, or the owner reads a
    `failed` proposal over a tree that moved and has nothing to reconcile it with."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md"), _item("source", "src-a")]))

    async def boom(user_id, source_id, archived):
        raise RuntimeError("l0 mark refused")

    ctx.store.set_source_archived = boom  # type: ignore[method-assign]

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["error"] == "RuntimeError"
    assert detail["ref"] == "sha-moved"
    assert detail["moved"] == 1
    assert ctx.completed[-1][1] is False


# ------------------------------------------------------- what a partial failure records


async def test_multi_source_partial_failure_records_each_l0_mark(stubbed):
    """A failure halfway through the source loop must name which authoritative marks
    LANDED. A count written after the loop would never be reached, and the owner would read
    a `failed` proposal with no way to tell which sources are now archived in L0."""
    ctx = _Ctx(
        _row(
            [
                _item("document", "work/aurora.md"),
                _item("source", "src-a"),
                _item("source", "src-b"),
                _item("source", "src-c"),
            ]
        )
    )

    marked: list[str] = []

    async def mark(user_id, source_id, archived):
        if str(source_id) == "src-c":
            raise RuntimeError("l0 mark refused")
        marked.append(str(source_id))
        ctx.calls.append(("l0", str(source_id), archived))

    ctx.store.set_source_archived = mark  # type: ignore[method-assign]

    await run_archive_job(ctx, USER, _job())

    assert marked == ["src-a", "src-b"]
    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["sources_marked"] == ["src-a", "src-b"]
    assert detail["sources"] == 2
    assert detail["ref"] == "sha-moved" and detail["moved"] == 1
    assert detail["error"] == "RuntimeError"
    assert ctx.completed[-1][1] is False


async def test_projection_failure_after_move_is_recorded_with_the_ref(stubbed, monkeypatch):
    """The L3 sync is NOT fail-soft the way the index flips are — it is how the move reaches
    the claim indexes at all. It fails the proposal, and the detail carries the ref, the
    move count, the marks that landed, and the projection's own error."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md"), _item("source", "src-a")]))

    async def boom(ctx_, user, ref, **kwargs):
        raise RuntimeError("qdrant is down")

    monkeypatch.setattr(archive_job_module, "sync_projection", boom)

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["ref"] == "sha-moved"
    assert detail["moved"] == 1
    assert detail["sources_marked"] == ["src-a"]
    assert detail["projection_error"] == "RuntimeError: qdrant is down"
    assert detail["error"] == "RuntimeError"
    assert ctx.completed[-1][1] is False


# ------------------------------------------- the terminal write is guarded, never forced


async def test_terminal_writes_are_guarded_by_confirmed(stubbed):
    """A finished job writes onto a `confirmed` row or onto nothing at all.

    The job re-reads the proposal when it starts, but the read cannot hold: the row can move
    under it while the archive runs. The terminal write therefore asks the row itself, and a
    lost predicate is not an error — the commit is in the tree, the marks are on L0, and
    failing the job would say the opposite of what happened. It is logged and named in the
    completion detail instead, which is where an operator can see that the work landed while
    the row did not follow it.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]))
    ctx.during_move = lambda: ctx.row.update(status="dropped")

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "dropped"  # not overwritten by the finished job
    assert ctx.row["detail"] is None  # and nothing else was written either
    job_id, ok, detail, snapshot_ref = ctx.completed[-1]
    assert (job_id, ok, snapshot_ref) == ("job-1", True, "sha-moved")
    recorded = json.loads(detail.removeprefix("archive:"))
    assert recorded["ref"] == "sha-moved"
    assert "no longer confirmed" in recorded["proposal_write"]


async def test_a_guarded_failure_write_that_loses_still_completes_the_job(stubbed):
    """The same predicate on the `failed` write, and the same refusal to raise over it."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]))
    ctx.during_move = lambda: ctx.row.update(status="dropped")
    ctx.move_error = CanonicalMoveError("destination path already exists", "archive/x.md")

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "dropped"
    assert ctx.row["detail"] is None
    job_id, ok, detail, _ref = ctx.completed[-1]
    assert (job_id, ok) == ("job-1", False)
    assert "destination path already exists" in detail
    assert "no longer confirmed" in detail


async def test_a_terminal_write_onto_a_confirmed_row_says_nothing_extra(stubbed):
    """The guard is invisible in the ordinary case: no marker, and the detail is the work's."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]))

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "executed"
    _job_id, _ok, detail, _ref = ctx.completed[-1]
    assert "proposal_write" not in json.loads(detail.removeprefix("archive:"))


# ------------------------------------------------------- the record, and the statement


async def test_archiving_writes_the_record_and_the_move_in_one_commit(stubbed_statement):
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md", record=_record(volumes=0))])
    )
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    # ONE call to move_documents, carrying both halves of the act: the page leaves, and the
    # record lands on the path the move just vacated.
    moves = [call for call in ctx.calls if call[0] == "move"]
    assert len(moves) == 1
    assert moves[0][1] == [("work/aurora.md", "archive/work/aurora.md")]
    assert list(ctx.writes) == ["work/aurora.md"]
    assert ctx.removals == []

    record = ctx.writes["work/aurora.md"]
    assert "type: archived" in record
    assert "archive_of: archive/work/aurora.md" in record
    assert "archive_statement: src-statement" in record
    # The numbers are the TREE's, not the preview's: `PAGE` holds one claim over one source.
    assert "archive_claims: 1" in record
    assert "archive_sources: 1" in record
    assert "— archived" in record
    assert "sources 1" in record
    assert "[cite: src-statement ¶0]" in record
    # The reason the confirm kept, quoted verbatim — this proposal named no other.
    assert KEPT_REASON in record

    detail = json.loads(ctx.row["detail"])
    assert detail["archive_records_written"] == 1
    assert detail["archive_records_removed"] == 0
    assert detail["statement_ref"] == "src-statement"


async def test_the_statement_is_one_owner_turn_that_is_never_compiled(stubbed_statement):
    reason = "Aurora shipped in June; the team is disbanded."
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md", record=_record(reason=reason))])
    )
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    contract, intake = stubbed_statement[0]
    assert contract.contract_schema == "pneuma.source.owner-dialogue/v1"
    assert contract.dialogue_id == "p-1"
    assert [t.role for t in contract.turns] == ["owner"]
    assert contract.turns[0].text == reason
    # The one thing the policy could not know: the RECORD is this statement's canonical
    # expression, so no compile of it is queued.
    assert intake.canonical_treatment == "none"
    assert intake.semantic_indexing == "full"
    # …and the record quotes exactly what the statement says.
    assert reason in ctx.writes["work/aurora.md"]
    # The id is written onto the proposal, so a requeued job cites it rather than minting a
    # second statement.
    assert ctx.row["statement_ref"] == "src-statement"


async def test_a_statement_the_owner_already_made_is_cited_rather_than_a_second_one(
    stubbed_statement,
):
    row = _row([_item("document", "work/aurora.md", record=_record())])
    row["statement_ref"] = "src-owner-said-it"
    ctx = _Ctx(row)
    ctx.documents = [PAGE]
    ctx.sources["src-owner-said-it"] = _owner_statement("Aurora is done; retire it.")

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    record = ctx.writes["work/aurora.md"]
    assert "[cite: src-owner-said-it ¶0]" in record
    # And it QUOTES that source's block 0 rather than a sentence typed beside it, so the
    # citation names a block that actually contains the words next to it.
    assert "Aurora is done; retire it." in record


async def test_a_statement_ref_that_is_not_the_owner_speaking_fails_before_anything_moves(
    stubbed_statement,
):
    """`[cite: <sid> ¶0]` has to resolve to the owner. Three ways it could not, three codes."""
    for statement, setup, code in (
        ("src-gone", lambda ctx: ctx.missing_sources.add("src-gone"), "statement_unknown"),
        (
            "src-meeting",
            lambda ctx: ctx.sources.__setitem__(
                "src-meeting",
                SimpleNamespace(raw=SimpleNamespace(kind="meeting"), blocks=[object()]),
            ),
            "statement_not_owner",
        ),
        (
            "src-silent",
            lambda ctx: ctx.sources.__setitem__(
                "src-silent",
                SimpleNamespace(raw=SimpleNamespace(kind="owner_dialogue"), blocks=[]),
            ),
            "statement_unknown",
        ),
    ):
        row = _row([_item("document", "work/aurora.md", record=_record())])
        row["statement_ref"] = statement
        ctx = _Ctx(row)
        ctx.documents = [PAGE]
        setup(ctx)

        await run_archive_job(ctx, USER, _job())

        assert ctx.row["status"] == "failed"
        assert json.loads(ctx.row["detail"])["error"] == code
        assert [call[0] for call in ctx.calls if call[0] == "move"] == []


async def test_a_note_that_disagrees_with_the_cited_statement_fails_rather_than_picking_one(
    stubbed_statement,
):
    """A record quoting one thing and citing another is a fabrication with a citation on it."""
    row = _row([_item("document", "work/aurora.md", record=_record())])
    row["statement_ref"] = "src-owner-said-it"
    row["note"] = "Something else entirely."
    ctx = _Ctx(row)
    ctx.documents = [PAGE]
    ctx.sources["src-owner-said-it"] = _owner_statement("Aurora is done; retire it.")

    await run_archive_job(ctx, USER, _job())

    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "statement_mismatch"
    assert ctx.writes == {}


async def test_the_statement_is_derived_from_the_proposal_so_a_retry_mints_no_second_one(
    stubbed, monkeypatch,
):
    """The crash this closes: ingest lands, the worker dies before `statement_ref` is saved,
    the requeued job ingests again. With `said_at` off the wall clock the contract digest
    differed on the second attempt and L0 gained a source the owner never made.

    Here the ingest is the REAL identity computation (`normalize_owner_dialogue` +
    `_identity`), so what is asserted is the thing that matters: two runs of the step produce
    one source id, because they produce one contract.
    """
    seen: list[str] = []

    async def fake_ingest(ctx, user, contract, *, intake_plan=None):
        normalized = normalize_source_contract(
            contract, UserId(str(USER)), imported_at=datetime.now(timezone.utc)
        )[0]
        seen.append(str(normalized.raw.source_id))
        return SimpleNamespace(
            contract_schema=contract.contract_schema,
            sources=[SimpleNamespace(source_id=normalized.raw.source_id)],
        )

    monkeypatch.setattr(archive_job_module, "ingest_source_contract", fake_ingest)

    for _ in range(2):
        ctx = _Ctx(_row([_item("document", "work/aurora.md", record=_record())]))
        ctx.documents = [PAGE]
        # The row this run reads still has no `statement_ref`: that is exactly the crashed
        # state — the source was stored, and the proposal never learned its id.
        await run_archive_job(ctx, USER, _job())

    assert len(seen) == 2
    assert seen[0] == seen[1]


async def test_the_record_is_recomputed_over_the_set_the_owner_finally_confirmed(stubbed_statement):
    """Unticking a page that another selected page links to changes that page's `inbound`.

    The plan-time preview said "both are leaving, so nothing links to me". The confirm left
    Atlas live. A job that wrote the preview would commit a sentence that was true of a move
    that did not happen, and the gate would pass it — frontmatter and body come off the same
    facts, so both halves would be wrong together.
    """
    atlas = _canonical(
        "work/atlas.md",
        "# Atlas\n\n- Atlas depends on [Aurora](aurora.md). [cite: src-b ¶0] "
        "<!-- c:bbbb0001 -->\n",
        slug="atlas",
    )
    ctx = _Ctx(
        _row(
            [
                _item("document", "work/aurora.md", record=_record()),
                _item("document", "work/atlas.md", selected=False, record=_record("Atlas")),
            ]
        )
    )
    ctx.documents = [PAGE, atlas]

    await run_archive_job(ctx, USER, _job())

    assert list(ctx.writes) == ["work/aurora.md"]
    record = ctx.writes["work/aurora.md"]
    # Atlas stayed, so it IS a live page linking to this one — the preview said 3.
    assert "archive_inbound: 1" in record
    assert "linked from live pages 1" in record


async def test_a_resumed_unarchive_still_declares_the_anchors_its_move_retired(
    stubbed, monkeypatch
):
    """The one step left to run on the resume path is the one that would refuse.

    A record's anchors retire with it, and the projection is TOLD so. On the already-landed
    path the record is gone from HEAD and gone from the new claim set, so the only place it
    can be read is the tree the plan was computed over — and without that read, an unarchive
    whose record held most of the projected ledger fails its last step on every requeue.
    """
    record = _canonical(
        "work/aurora.md",
        "# Aurora\n\n- Aurora was archived. <!-- c:cccc0001 -->\n"
        "- It covered a span. <!-- c:cccc0002 -->\n",
        type="archived",
        archive_of="archive/work/aurora.md",
    )
    ctx = _Ctx(
        _row([_item("document", "archive/work/aurora.md")], action="unarchive"),
        head="sha-2",
    )
    ctx.documents = [record]
    ctx.trailers["sha-2"] = "p-1"

    retired: list[set] = []

    async def fake_sync(ctx_, user, ref, **kwargs):
        retired.append(set(kwargs.get("retired_anchors") or ()))
        return SimpleNamespace(total=7)

    monkeypatch.setattr(archive_job_module, "sync_projection", fake_sync)
    await run_archive_job(ctx, USER, _job())

    detail = json.loads(ctx.row["detail"])
    assert detail["moved"] == "already_landed"
    assert retired == [{"cccc0001", "cccc0002"}]
    # And the counts are stated here too: the landed commit took one record away.
    assert detail["archive_records_removed"] == 1
    assert detail["archive_records_written"] == 0


async def test_the_reason_the_confirm_kept_is_the_one_the_statement_and_the_record_carry(
    stubbed_statement,
):
    """The line is REPLAYED from the item, not recomputed from the row's note.

    The confirm computed it against the set the Owner finally ticked and showed it to them;
    recomputing here made the page's third block the output of a second implementation, and
    the two came apart the moment the note stored beside them was not the note the preview
    was computed with (an emptied note that the store's COALESCE read as silence). A row
    whose note disagrees with the kept line is exactly that stale row, and the line the
    Owner confirmed is the one that stands.
    """
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md", record=_record(reason="Aurora is done."))])
    )
    ctx.documents = [PAGE]
    ctx.row["note"] = "a note the confirm already replaced"

    await run_archive_job(ctx, USER, _job())

    contract, _ = stubbed_statement[0]
    # The statement and the record say the SAME sentence — a record quoting something its
    # cited source does not say would be the one fabrication this framework makes impossible.
    assert contract.turns[0].text == "Aurora is done."
    assert contract.turns[0].text in ctx.writes["work/aurora.md"]
    assert "a note the confirm already replaced" not in ctx.writes["work/aurora.md"]


async def test_a_row_note_is_never_promoted_to_the_owners_statement(stubbed_statement):
    """There is NO fallback to the note the row holds, and dropping it was the fix.

    That note is display text a PLAN happened to keep: typed against a set that may since
    have been narrowed, at a moment that decided nothing. The confirm refuses to stand on it
    (`note_required`), so the job may not either — promoting it here would record the Owner
    as having said something at a time they did not. The row below is exactly that shape, and
    it is refused rather than quietly spoken for.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md", record=_record(reason=None))]))
    ctx.row["note"] = "Aurora shipped in June."
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    assert ctx.writes == {}
    assert [call[0] for call in ctx.calls if call[0] == "move"] == []
    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "statement_missing"


async def test_a_reason_with_no_stamped_provenance_is_refused(stubbed_statement):
    """The mechanism behind "a confirmed row's reason is confirm-written".

    It was TRUE of the code and proved by NOTHING in the row: the job read the line and
    trusted that whatever wrote it had followed the rule. Now the confirm stamps every reason
    it writes with `reason_source`, and a reason arriving without the stamp is refused — the
    step this guards mints an `owner-dialogue/v1` source, L0 labelled as the Owner SPEAKING,
    and words whose provenance cannot be seen are not words to put in it.
    """
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md", record=_record(reason_source=None))])
    )
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    assert ctx.writes == {}
    assert [call[0] for call in ctx.calls if call[0] == "move"] == []
    assert ctx.row["status"] == "failed"
    detail = json.loads(ctx.row["detail"])
    assert detail["error"] == "statement_missing"
    assert "reason_source" in detail["message"]


async def test_a_reason_stamped_by_the_confirm_runs(stubbed_statement):
    """The other side of the stamp: both legal provenances carry the line straight through."""
    for source in ("note", "statement"):
        ctx = _Ctx(
            _row(
                [
                    _item(
                        "document",
                        "work/aurora.md",
                        record=_record(reason_source=source),
                    )
                ]
            )
        )
        ctx.documents = [PAGE]

        await run_archive_job(ctx, USER, _job())

        assert ctx.row["status"] == "executed", source
        contract, _ = stubbed_statement[-1]
        assert contract.turns[0].text == KEPT_REASON
        assert KEPT_REASON in ctx.writes["work/aurora.md"]


async def test_a_row_carrying_no_reason_at_all_refuses_rather_than_speaking_for_the_owner(
    stubbed_statement,
):
    """The defensive half of the correction, at the far side of the QUEUE.

    `plan` and `confirm` both refuse a proposal with neither a note nor a `statement_ref`, so
    a row like this cannot be made through the API any more — but the request and the
    execution are separated by a job queue, and a row written before that rule existed (or
    repaired by hand) still reaches here. The step it would reach is the one that INGESTS an
    `owner-dialogue/v1` source: L0 labelled as the owner speaking. With no words of theirs to
    put in it, the only sentence left would be one the framework wrote and then cited as
    theirs — so the job refuses, ingests nothing, and moves nothing.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md", record=_record(reason=None))]))
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    assert ctx.writes == {}
    assert [call[0] for call in ctx.calls if call[0] == "move"] == []
    assert ctx.row["status"] == "failed"
    assert json.loads(ctx.row["detail"])["error"] == "statement_missing"
    assert "statement_missing" in ctx.completed[0][2] or "no reason" in ctx.completed[0][2]


async def test_a_sources_only_proposal_ingests_nothing_and_writes_no_record(
    stubbed_statement,
):
    ctx = _Ctx(_row([_item("source", "src-a")]))

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    assert ctx.writes == {}
    detail = json.loads(ctx.row["detail"])
    # The counts are stated at ZERO rather than omitted: an absent key made "this proposal
    # wrote no record" indistinguishable from "the write never ran" (validation B-S9-2).
    assert detail["archive_records_written"] == 0
    assert detail["archive_records_removed"] == 0
    assert "statement_ref" not in detail


async def test_unarchiving_removes_the_record_and_makes_no_second_statement(
    stubbed_statement,
):
    record = _canonical(
        "work/aurora.md",
        "# Aurora\n\n- Aurora was. — archived <!-- c:bbbb0001 -->\n",
        type="archived",
        archive_of="archive/work/aurora.md",
    )
    ctx = _Ctx(
        _row([_item("document", "archive/work/aurora.md")], action="unarchive")
    )
    ctx.documents = [record]

    await run_archive_job(ctx, USER, _job())

    assert stubbed_statement == []
    assert ctx.removals == ["work/aurora.md"]
    assert ctx.writes == {}
    detail = json.loads(ctx.row["detail"])
    assert detail["archive_records_removed"] == 1
    assert detail["archive_records_written"] == 0


async def test_the_record_s_anchors_are_declared_retired_rather_than_lost(
    stubbed_statement, monkeypatch
):
    """A record's three blocks carry no permanent identity — the page whose identity they
    stood in for is coming back — so the projection's loss guardrail must not read the
    replacement as knowledge being destroyed. Only this channel can name them."""
    seen: dict = {}

    async def fake_sync(ctx, user, ref, **kwargs):
        seen.update(kwargs)
        ctx.calls.append(("l3", ref))
        return SimpleNamespace(total=7)

    monkeypatch.setattr(archive_job_module, "sync_projection", fake_sync)
    record = _canonical(
        "work/aurora.md",
        "# Aurora\n\n- A. <!-- c:bbbb0001 -->\n\n- B. <!-- c:bbbb0002 -->\n",
        type="archived",
        archive_of="archive/work/aurora.md",
    )
    ctx = _Ctx(
        _row([_item("document", "archive/work/aurora.md")], action="unarchive")
    )
    ctx.documents = [record]

    await run_archive_job(ctx, USER, _job())

    assert seen["retired_anchors"] == {"bbbb0001", "bbbb0002"}
    assert json.loads(ctx.row["detail"])["archive_records_retired_anchors"] == 2


async def test_unarchiving_a_page_that_left_no_record_removes_nothing(stubbed_statement):
    """A page archived before records existed left none behind, and a removal of a path
    holding nothing would refuse the whole move."""
    ctx = _Ctx(
        _row([_item("document", "archive/work/aurora.md")], action="unarchive")
    )
    ctx.documents = []

    await run_archive_job(ctx, USER, _job())

    assert ctx.removals == []
    assert ctx.row["status"] == "executed"
    # And the detail SAYS so. This is the case B-S9-2 was about: with the key omitted at
    # zero, "this page left no record behind" and "the removal step never ran" produced the
    # same detail, and an operator had nothing to read them apart by.
    assert json.loads(ctx.row["detail"])["archive_records_removed"] == 0


async def test_a_statement_id_that_was_not_saved_fails_before_the_move(
    stubbed_statement,
):
    """The write-back is predicated, so it can lose — and losing it is a refusal, not a step.

    The statement is in L0 by then. If the job carried on, the move would land committing a
    record that cites a source the proposal does not name, the terminal write would lose the
    same predicate and record nothing, and no later run could reconnect the two. Refusing
    here leaves the tree untouched and the statement re-derivable by the next run of the
    same decision.
    """
    ctx = _Ctx(_row([_item("document", "work/aurora.md", record=_record())]))
    ctx.documents = [PAGE]
    # Something else moved the row while this job was between its ingest and its commit.
    ctx.on_proposal_write = lambda: ctx.row.update(status="dropped")

    await run_archive_job(ctx, USER, _job())

    assert [call for call in ctx.calls if call[0] == "move"] == []
    assert ctx.writes == {}
    assert ctx.row["status"] == "dropped"  # nothing here overwrites a row that moved on
    job_id, ok, detail, ref = ctx.completed[-1]
    assert (job_id, ok, ref) == ("job-1", False, None)
    assert "no longer `confirmed`" in detail
    assert "src-statement" in detail  # the statement that stands in L0, named
    assert "no longer confirmed" in detail  # …and the row that would not take the terminal write


async def test_a_resumed_archive_still_counts_the_records_its_move_wrote(stubbed):
    """The counts are stated on EVERY path, and the resume is the path most likely read.

    Emitting them only off the non-resume branch put back the hole they were added to close,
    for exactly the run an operator reconciles by hand: a crashed job's. The number is
    reconstructed from the plan-time tree and the confirmed set — the same two conditions
    `_record_files` writes under — because the commit is already in the history.
    """
    ctx = _Ctx(
        _row([_item("document", "work/aurora.md", record=_record())]),
        head="sha-moved",
    )
    ctx.documents = [PAGE]
    ctx.trailers["sha-moved"] = "p-1"

    await run_archive_job(ctx, USER, _job())

    assert [call for call in ctx.calls if call[0] == "move"] == []
    detail = json.loads(ctx.row["detail"])
    assert detail["moved"] == "already_landed"
    assert detail["archive_records_written"] == 1
    assert detail["archive_records_removed"] == 0


async def test_a_resumed_archive_of_a_page_that_left_no_record_says_zero(stubbed):
    """Zero, not absent — the same distinction, on the same path."""
    ctx = _Ctx(_row([_item("document", "work/aurora.md")]), head="sha-moved")
    ctx.documents = [PAGE]
    ctx.trailers["sha-moved"] = "p-1"

    await run_archive_job(ctx, USER, _job())

    detail = json.loads(ctx.row["detail"])
    assert detail["archive_records_written"] == 0
    assert detail["archive_records_removed"] == 0


async def test_a_record_its_own_gate_refuses_fails_the_proposal_before_the_move(
    stubbed_statement, monkeypatch
):
    """The channel is all-or-nothing: a record the gate will not take moves nothing."""
    monkeypatch.setattr(
        archive_job_module,
        "run_archive_record_gate",
        lambda **_: [SimpleNamespace(render=lambda: "[archive_record] x: refused")],
    )
    ctx = _Ctx(_row([_item("document", "work/aurora.md", record=_record())]))
    ctx.documents = [PAGE]

    await run_archive_job(ctx, USER, _job())

    # Nothing moved, no L0 mark, no index flip — only the statement_ref bookkeeping the
    # step above it had already written, and the terminal `failed`.
    assert [call[0] for call in ctx.calls] == ["proposal", "proposal"]
    detail = json.loads(ctx.row["detail"])
    assert detail["error"] == "record_rejected"
    assert ctx.row["status"] == "failed"
