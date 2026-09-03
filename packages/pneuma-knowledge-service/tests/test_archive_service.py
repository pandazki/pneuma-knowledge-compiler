"""The archive's request-side flow: propose → confirm → job, over fake ports.

docs/design/archive.md §5. What is under test here is NOT the closure — that is core's, and
its own test file — but the three things this layer is responsible for: the computed set is
KEPT verbatim, `library_ref` identifies the state it was computed over, and a confirm may
only tick and untick what was listed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_service.archive_service import (
    ARCHIVE_JOB_KIND,
    ArchiveRequestError,
    confirm,
    drop,
    get_proposal,
    inventory,
    list_proposals,
    plan,
)
from pneuma_knowledge_service.snapshot_tenant import (
    SnapshotTenantWriteError,
    snapshot_tenant_id,
)

USER = UserId("u-archive-service")
NOW = datetime(2026, 9, 3, 10, tzinfo=timezone.utc)
#: Every CONFIRM carries one, because every confirm must: the reason is recorded as the
#: owner's own `owner-dialogue/v1` statement and the confirm is the decision it states, so a
#: confirm with neither a note nor a `statement_ref` is refused `note_required` (its own test
#: below). A plan needs none — its `note` is informational. Stated once here so the tests
#: that are about something else do not each invent a sentence.
NOTE = "Aurora shipped in June; the team is disbanded."


def _doc(path: str, *claims: tuple[str, ...]) -> CanonicalDocument:
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    lines = [f"# {stem.replace('-', ' ').title()}", ""]
    for i, sources in enumerate(claims):
        cites = " ".join(f"[cite: {sid} ¶0]" for sid in sources)
        anchor = hashlib.sha256(f"{path}:{i}".encode()).hexdigest()[:8]
        lines.append(f"- claim {i} of {stem}. {cites} <!-- c:{anchor} -->")
    return CanonicalDocument(
        doc_id=DocumentId(hashlib.sha256(path.encode()).hexdigest()[:12]),
        path=path,
        frontmatter={"type": "topic", "slug": stem},
        body="\n".join(lines),
    )


class _Canonical:
    """A tree plus a HEAD that a test can move under a plan, which is the whole point."""

    def __init__(self, docs: list[CanonicalDocument], head: str = "sha-1") -> None:
        self.docs = docs
        self.head = head
        self.written = {}

    async def list(self, user_id, *, at=None):
        return list(self.docs)

    async def snapshots_page(self, user_id, *, limit: int, after_ref=None):
        if not self.head:
            return [], 0, False
        return [SnapshotRef(ref=self.head)], 1, False

    async def written_on(self, user_id, *, prefix: str = ""):
        return dict(self.written)


class _Store:
    """The kept `archive_proposals` table, in memory, plus the source inventory."""

    def __init__(self, sources: list[SimpleNamespace] | None = None) -> None:
        self.sources = sources or []
        self.rows: dict[str, dict] = {}
        self.enqueued: list[tuple[str, dict]] = []
        #: Runs at the END of `confirm_archive_proposal`, standing in for the worker: the
        #: job the confirm just queued is a separate process, and nothing in the confirm
        #: waits for it — so it can finish before the confirm reads the row back.
        self.on_confirm = None
        #: Simulates a racing caller's READ: the snapshot it took before the winner's write
        #: landed. That is the whole race — both callers read `proposed` — so a test that
        #: wants the predicate rather than the read-side check sets this.
        self.reads_as: str | None = None

        #: L0 as the statement check reads it: `source_id → the stored source`, so a
        #: `statement_ref` can be validated (this user's, an owner dialogue, with a ¶0).
        self.stored: dict[str, SimpleNamespace] = {}

    async def list(self, user_id):
        return list(self.sources)

    async def get(self, user_id, source_id):
        try:
            return self.stored[str(source_id)]
        except KeyError:
            raise KeyError(f"source not found: {source_id!r}") from None

    async def archived_source_ids(self, user_id):
        return frozenset(
            str(s.source_id) for s in self.sources if s.archived_at is not None
        )

    async def create_archive_proposal(
        self,
        user_id,
        proposal_id,
        *,
        action,
        seeds,
        items,
        library_ref,
        note=None,
        statement_ref=None,
    ):
        self.rows[proposal_id] = {
            "proposal_id": proposal_id,
            "action": action,
            "seeds": seeds,
            "items": items,
            "library_ref": library_ref,
            "status": "proposed",
            "note": note,
            "statement_ref": statement_ref,
            "created_at": NOW,
            "confirmed_at": None,
            "executed_at": None,
            "job_id": None,
            "detail": None,
        }

    async def get_archive_proposal(self, user_id, proposal_id):
        row = self.rows.get(proposal_id)
        if row is None:
            return None
        if self.reads_as is not None:
            return {**row, "status": self.reads_as}
        return dict(row)

    async def list_archive_proposals(self, user_id, *, limit=50):
        return [dict(row) for row in list(self.rows.values())[:limit]]

    async def update_archive_proposal(
        self,
        user_id,
        proposal_id,
        *,
        status,
        items=None,
        confirmed_at=None,
        executed_at=None,
        job_id=None,
        detail=None,
        note=None,
        note_given=False,
        expected_status=None,
    ):
        row = self.rows[proposal_id]
        # The real statement puts `expected_status` in the WHERE clause, so a row that has
        # already moved matches nothing and the caller is told it lost. Honoured here for
        # the same reason: the one-winner property is what these tests are about.
        if expected_status is not None and row["status"] != expected_status:
            return False
        row["status"] = status
        for key, value in (
            ("items", items),
            ("confirmed_at", confirmed_at),
            ("executed_at", executed_at),
            ("job_id", job_id),
            ("detail", detail),
        ):
            if value is not None:  # COALESCE, like the real statement
                row[key] = value
        # …and the one column with an explicit CLEARED state: assigned outright when the
        # caller said something about it, COALESCE'd when they did not.
        if note_given:
            row["note"] = note
        elif note is not None:
            row["note"] = note
        return True

    async def confirm_archive_proposal(
        self,
        user_id,
        proposal_id,
        *,
        items,
        job_kind,
        payload,
        note=None,
        note_given=False,
        statement_ref=None,
    ):
        # ONE step, because the real one is one transaction: the row moves out of
        # `proposed` and the job that executes it is inserted under the same predicate, so
        # neither half can exist without the other. A row that has already moved matches
        # nothing, writes nothing, queues nothing, and answers None.
        row = self.rows.get(proposal_id)
        if row is None or row["status"] != "proposed":
            return None
        self.enqueued.append((job_kind, dict(payload)))
        job_id = f"job-{len(self.enqueued)}"
        row.update(
            {
                "status": "confirmed",
                "items": items,
                "confirmed_at": NOW,
                "job_id": job_id,
            }
        )
        # `note_given` is the difference between "said nothing about the note" and "cleared
        # it", which COALESCE alone cannot spell — and an emptied note falling back to the
        # plan's old one is exactly how the preview and the record came apart.
        if note_given:
            row["note"] = note
        elif note is not None:  # COALESCE, like the real statement
            row["note"] = note
        # COALESCE'd and never cleared, like the real statement: a confirm may NAME the
        # statement the plan did not, and the job reads it off the row.
        if statement_ref is not None:
            row["statement_ref"] = statement_ref
        if self.on_confirm is not None:
            self.on_confirm()
        return job_id


def _source(
    sid: str,
    title: str,
    *,
    archived_at=None,
    kind: str = "conversation",
    occurred_on: str = "",
):
    # `occurred_on` is a METHOD on RawSource (it reads `meta.occurred_on`), and the planner
    # calls it to compute an archive record's span — so the double answers it the same way.
    return SimpleNamespace(
        source_id=sid,
        title=title,
        kind=kind,
        archived_at=archived_at,
        occurred_on=lambda: occurred_on,
    )


def _ctx(canonical: _Canonical, store: _Store) -> SimpleNamespace:
    return SimpleNamespace(canonical=canonical, store=store)


def _owner_statement(text: str) -> SimpleNamespace:
    """One `owner-dialogue/v1` source as L0 answers it: the owner's turn line at ¶0.

    What a supplied `statement_ref` has to resolve to, and what the record's reason then
    QUOTES — so the citation names a block that actually contains the words next to it.
    """
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


def _library() -> tuple[_Canonical, _Store]:
    # Aurora cites src-a (its own) and src-b (shared with Atlas). Archiving Aurora retires
    # src-a and merely LISTS src-b, naming the document that kept it.
    canonical = _Canonical(
        [
            _doc("work/aurora.md", ("src-a",), ("src-b",)),
            _doc("work/atlas.md", ("src-b",), ("src-c",)),
        ]
    )
    store = _Store(
        [
            _source("src-a", "The Aurora kickoff"),
            _source("src-b", "The shared vendor review"),
            _source("src-c", "The Atlas standup"),
        ]
    )
    store.stored["src-statement"] = _owner_statement("Aurora shipped in June.")
    return canonical, store


# ------------------------------------------------------------------------- propose


async def test_a_plan_is_kept_verbatim_with_the_head_it_was_computed_against():
    canonical, store = _library()
    result = await plan(
        _ctx(canonical, store),
        USER,
        action="archive",
        documents=["work/aurora.md"],
        sources=[],
        note="Aurora shipped in June.",
        statement_ref="src-statement",
    )

    assert result["status"] == "proposed"
    assert result["library_ref"] == "sha-1"
    assert result["seeds"] == {"documents": ["work/aurora.md"], "sources": []}
    assert result["note"] == "Aurora shipped in June."
    assert result["statement_ref"] == "src-statement"
    assert result["created_at"] == NOW.isoformat()

    by_ref = {(i["kind"], i["ref"]): i for i in result["items"]}
    # The seed, the source only it cited, and the one another document still cites — the
    # whole set, including what STAYS, because that is the Owner's most useful line.
    assert by_ref[("document", "work/aurora.md")]["selected"] is True
    assert by_ref[("source", "src-a")]["selected"] is True
    assert by_ref[("source", "src-b")]["selected"] is False
    assert by_ref[("source", "src-b")]["reason"]["cited_by_live"] == ["work/atlas.md"]

    # …and the row that was stored is the row that was answered, field for field.
    stored = await store.get_archive_proposal(USER, result["proposal_id"])
    assert stored["items"] == result["items"]
    assert stored["library_ref"] == "sha-1"


async def test_the_plan_previews_a_quotable_line_ONLY_when_the_owner_already_spoke():
    """`reason` is the one part of the record that is a fact about the DECISION, and a plan is
    not the decision — so it previews a sentence only when the Owner named a statement, whose
    words they have already said. A note handed to the plan is informational: previewing it
    would show a sentence nothing will quote, kept on a row one step from being spoken for
    them. Without a statement the field is NULL and the console shows its own note box."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)

    typed = await plan(
        ctx,
        USER,
        action="archive",
        documents=["work/aurora.md"],
        sources=[],
        note="Aurora shipped in June.",
        statement_ref=None,
    )
    record = next(
        item["record"] for item in typed["items"] if item["kind"] == "document"
    )
    assert record["reason"] is None
    # Kept, and kept as what it is: a line to display, not a line to quote.
    assert typed["note"] == "Aurora shipped in June."
    # There is no second field beside it either — no default the console could fall back on.
    assert "reason_default" not in record

    spoken = await plan(
        ctx,
        USER,
        action="archive",
        documents=["work/aurora.md"],
        sources=[],
        note=None,
        statement_ref="src-statement",
    )
    quoted = next(
        item["record"] for item in spoken["items"] if item["kind"] == "document"
    )
    assert quoted["reason"] == "Aurora shipped in June."


async def test_a_note_typed_at_the_confirm_moves_the_preview_with_it():
    """The note is typed while reading the proposal, so the kept row has to follow it: a row
    whose preview said one thing while the commit quoted another would be a kept record of a
    decision nobody made."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    planned = next(
        item["record"] for item in proposal["items"] if item["kind"] == "document"
    )
    assert planned["reason"] is None  # nothing was quotable until the decision
    result = await confirm(
        ctx, USER, proposal["proposal_id"], note="The team is disbanded."
    )
    record = next(
        item["record"]
        for item in result["proposal"]["items"]
        if item["kind"] == "document"
    )
    assert record["reason"] == "The team is disbanded."


@pytest.mark.parametrize(
    "note",
    [
        "Shipped <!-- c:aaaa1111 -->",
        "Shipped <!-- supersedes: c:aaaa1111 -->",
        "Shipped __AUTO__ done",
    ],
)
async def test_a_note_carrying_machinery_is_refused_at_the_plan_and_at_the_confirm(note):
    """The note is interpolated into a block the projection indexes as a claim, so it is
    judged by the compile gate's own predicate — at the face where a person can fix it."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    with pytest.raises(ArchiveRequestError) as planned:
        await plan(
            ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
            note=note, statement_ref=None,
        )
    assert (planned.value.status_code, planned.value.code) == (422, "note_machinery")
    # The refusal NAMES the fragment to delete rather than saying "invalid".
    assert "<!--" in str(planned.value) or "__AUTO__" in str(planned.value)

    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    with pytest.raises(ArchiveRequestError) as confirmed:
        await confirm(ctx, USER, proposal["proposal_id"], note=note)
    assert confirmed.value.code == "note_machinery"
    assert store.enqueued == []


async def test_a_statement_ref_is_checked_to_be_the_owner_speaking():
    """`[cite: <sid> ¶0]` must resolve to the owner. Three ways it could not, two codes."""
    canonical, store = _library()
    store.stored["src-meeting"] = SimpleNamespace(
        raw=SimpleNamespace(kind="meeting"), blocks=[object()]
    )
    store.stored["src-silent"] = SimpleNamespace(
        raw=SimpleNamespace(kind="owner_dialogue"), blocks=[]
    )
    for ref, code in (
        ("src-nowhere", "statement_unknown"),
        ("src-meeting", "statement_not_owner"),
        ("src-silent", "statement_unknown"),
    ):
        with pytest.raises(ArchiveRequestError) as refused:
            await plan(
                _ctx(canonical, store),
                USER,
                action="archive",
                documents=["work/aurora.md"],
                sources=[],
                note=None,
                statement_ref=ref,
            )
        assert (refused.value.status_code, refused.value.code) == (422, code)


async def test_a_note_that_disagrees_with_the_named_statement_is_refused():
    """The record quotes the source it cites, so the two cannot say different things — and
    picking one silently would be the framework deciding what the owner meant."""
    canonical, store = _library()
    with pytest.raises(ArchiveRequestError) as refused:
        await plan(
            _ctx(canonical, store),
            USER,
            action="archive",
            documents=["work/aurora.md"],
            sources=[],
            note="Something else entirely.",
            statement_ref="src-statement",
        )
    assert (refused.value.status_code, refused.value.code) == (422, "statement_mismatch")

    # Agreeing, the statement wins and the preview quotes ITS block 0 — label stripped, so a
    # reader sees the owner's words and not the ingest line's furniture.
    result = await plan(
        _ctx(canonical, store),
        USER,
        action="archive",
        documents=["work/aurora.md"],
        sources=[],
        note=None,
        statement_ref="src-statement",
    )
    record = next(
        item["record"] for item in result["items"] if item["kind"] == "document"
    )
    assert record["reason"] == "Aurora shipped in June."
    # …stamped with where it came from, because the job refuses a reason whose provenance the
    # row does not state. A plan can only ever quote a named statement.
    assert record["reason_source"] == "statement"


async def test_a_snapshot_tenant_refuses_the_whole_path():
    canonical, store = _library()
    with pytest.raises(SnapshotTenantWriteError):
        await plan(
            _ctx(canonical, store),
            snapshot_tenant_id("0" * 32),
            action="archive",
            documents=["work/aurora.md"],
            sources=[],
            note=None,
            statement_ref=None,
        )


# ------------------------------------------------------------------------- confirm


async def test_confirm_enqueues_one_archive_job_and_records_the_decision():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    result = await confirm(ctx, USER, pid, note=NOTE)

    assert store.enqueued == [(ARCHIVE_JOB_KIND, {"proposal_id": pid})]
    assert result["job_id"] == "job-1"
    assert result["proposal"]["status"] == "confirmed"
    assert result["proposal"]["job_id"] == "job-1"
    assert result["proposal"]["confirmed_at"] is not None
    # The items the confirm kept are the items the plan computed — TWO fields apart, and both
    # are the point: `record.reason` was null on the plan (nothing was decided yet) and holds
    # the words THIS request sent, and `record.reason_source` stamps where those words came
    # from. Everything the planner computed is byte-for-byte.
    def _without_reason(items):
        return [
            {
                **item,
                "record": (
                    {**item["record"], "reason": None, "reason_source": None}
                    if item["record"]
                    else None
                ),
            }
            for item in items
        ]

    assert _without_reason(result["proposal"]["items"]) == _without_reason(proposal["items"])
    assert [
        (item["record"]["reason"], item["record"]["reason_source"])
        for item in result["proposal"]["items"]
        if item["record"]
    ] == [(NOTE, "note")]


async def test_a_confirm_stamps_where_its_reason_came_from():
    """The stamp is the mechanism behind "a confirmed row's reason is confirm-written".

    Before it, that sentence was true of this code and provable by nothing in the row — the
    job read the line and trusted whatever wrote it. Now the two legal provenances are the
    only two values that can appear, each written by the branch that produced the words, and
    the job refuses a reason that carries neither.
    """
    canonical, store = _library()

    ctx = _ctx(canonical, store)
    plain = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=None, statement_ref=None,
    )
    # A plan quotes nothing of its own, so there is nothing to stamp yet.
    previewed = next(i["record"] for i in plain["items"] if i["kind"] == "document")
    assert (previewed["reason"], previewed["reason_source"]) == (None, None)

    typed = await confirm(ctx, USER, plain["proposal_id"], note=NOTE)
    assert [
        (i["record"]["reason"], i["record"]["reason_source"])
        for i in typed["proposal"]["items"]
        if i["record"]
    ] == [(NOTE, "note")]

    # The other provenance: the Owner names their own speech, and the source wins.
    ctx = _ctx(canonical, store)
    named = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=None, statement_ref="src-statement",
    )
    spoken = await confirm(ctx, USER, named["proposal_id"], statement_ref="src-statement")
    assert [
        (i["record"]["reason"], i["record"]["reason_source"])
        for i in spoken["proposal"]["items"]
        if i["record"]
    ] == [("Aurora shipped in June.", "statement")]


async def test_confirm_refuses_stale_when_the_library_moved_under_the_plan():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    canonical.head = "sha-2"  # a compile landed while the Owner was reading the preview

    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)
    assert excinfo.value.code == "stale"
    assert excinfo.value.status_code == 409
    assert store.enqueued == []
    # Nothing MOVED — no job, no canonical write. But the row is no longer awaiting a
    # decision, because there is no decision left to make on it: it previews a library state
    # that is past, and a confirm will refuse it forever. Saying `proposed` after that is the
    # row claiming to be something it is not.
    assert store.rows[proposal["proposal_id"]]["status"] == "stale"
    # …and the refusal carries the moved row back, so a console that only reads the error is
    # not left rendering a `proposed` copy of a row that is now `stale`.
    assert excinfo.value.proposal is not None
    assert excinfo.value.proposal["status"] == "stale"
    assert excinfo.value.proposal["proposal_id"] == proposal["proposal_id"]


async def test_a_stale_confirm_that_lost_the_row_says_not_proposed_not_stale():
    """The `stale` write is a CAS, and its result is the answer.

    A confirm that finds HEAD moved marks the row `stale` conditionally on it still being
    `proposed` — and when a concurrent confirm or drop got there first, that write lands on
    nothing. Reporting `stale` anyway would name a status the row does not hold and hand the
    console back a proposal that is now `confirmed`, with "re-plan" written over someone
    else's decision. The lost predicate is the same lost race the confirm reports below it,
    and it gets the same answer.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    # The winner: another caller confirmed the row while this one was reading it.
    await confirm(ctx, USER, pid, note=NOTE)
    canonical.head = "sha-2"  # …and only now does this caller see HEAD has moved
    store.reads_as = "proposed"  # its own read predates the winner's write — that IS the race

    real_update = store.update_archive_proposal

    async def update_then_tell_the_truth(*args, **kwargs):
        moved = await real_update(*args, **kwargs)
        if not moved:
            # The re-read happens AFTER the losing write, so it is not the stale snapshot any
            # more: it sees the row as the winner left it. That is the whole point of reading
            # it again rather than reporting the status this caller came in holding.
            store.reads_as = None
        return moved

    store.update_archive_proposal = update_then_tell_the_truth

    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, pid, note=NOTE)

    assert excinfo.value.code == "not_proposed"
    assert excinfo.value.status_code == 409
    # The winner's row is untouched — a lost CAS wrote nothing — and the refusal reports the
    # status it really holds, with the real row attached.
    assert store.rows[pid]["status"] == "confirmed"
    assert str(excinfo.value) == "proposal status is confirmed, so it cannot be confirmed."
    assert excinfo.value.proposal is not None
    assert excinfo.value.proposal["status"] == "confirmed"
    assert store.enqueued == [(ARCHIVE_JOB_KIND, {"proposal_id": pid})]


async def test_a_stale_proposal_can_be_dropped_but_never_confirmed():
    """The two halves of what `stale` is for: it closes the confirm path and leaves the
    Owner the one action that makes sense — clearing it off the list."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    canonical.head = "sha-2"
    with pytest.raises(ArchiveRequestError):
        await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)

    # A second confirm is refused as the status it now carries, not as `stale` again: there
    # is nothing left to record, and the row already says why.
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)
    assert excinfo.value.code == "not_proposed"
    assert store.enqueued == []

    dropped = await drop(ctx, USER, proposal["proposal_id"])
    assert dropped["status"] == "dropped"


async def test_a_proposal_the_library_outran_is_PRESENTED_stale_without_a_write():
    """`library_ref != HEAD` is the whole definition of stale, and every read holds both
    halves of it. So the listing computes it — the row is not touched, no sweep races the
    confirms in flight, and a console never sees a `proposed` row it could not confirm."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    first = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    second = await plan(
        ctx, USER, action="archive", documents=["work/atlas.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    # Same HEAD: both are still real previews of the library as it stands.
    assert [row["status"] for row in await list_proposals(ctx, USER)] == [
        "proposed",
        "proposed",
    ]

    canonical.head = "sha-2"  # a compile landed, and nobody came back to either dialogue
    third = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )

    by_id = {row["proposal_id"]: row["status"] for row in await list_proposals(ctx, USER)}
    assert by_id[first["proposal_id"]] == "stale"
    assert by_id[second["proposal_id"]] == "stale"
    # The plan computed against the new HEAD is a live preview of it.
    assert by_id[third["proposal_id"]] == "proposed"
    assert third["library_ref"] == "sha-2"
    # A single read answers the same way…
    assert (await get_proposal(ctx, USER, first["proposal_id"]))["status"] == "stale"
    # …and the KEPT RECORD is untouched by any of it: a read is not a decision.
    assert store.rows[first["proposal_id"]]["status"] == "proposed"
    assert store.rows[second["proposal_id"]]["status"] == "proposed"


async def test_only_an_open_proposal_is_ever_presented_stale():
    """It closes a claim about being OPEN, and only that. A confirmed proposal has a job on
    the queue and an executed one is history; neither becomes stale because HEAD moved —
    which it always does, since executing the move is itself a commit."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    confirmed = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    await confirm(ctx, USER, confirmed["proposal_id"], note=NOTE)
    dropped = await plan(
        ctx, USER, action="archive", documents=["work/atlas.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    await drop(ctx, USER, dropped["proposal_id"])

    canonical.head = "sha-2"
    by_id = {row["proposal_id"]: row["status"] for row in await list_proposals(ctx, USER)}
    assert by_id[confirmed["proposal_id"]] == "confirmed"
    assert by_id[dropped["proposal_id"]] == "dropped"


async def test_a_proposal_presented_stale_is_still_droppable():
    """The Owner's one remaining action on it. The stored status is `proposed` and the
    presented one is `stale`; the drop is decided on the row, so both spellings close."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    canonical.head = "sha-2"
    assert (await get_proposal(ctx, USER, proposal["proposal_id"]))["status"] == "stale"

    dropped = await drop(ctx, USER, proposal["proposal_id"])
    assert dropped["status"] == "dropped"
    assert store.enqueued == []


async def test_an_override_may_untick_a_listed_item_but_never_add_one():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(
            ctx,
            USER,
            pid,
            items_override=[
                {"kind": "document", "ref": "work/atlas.md", "selected": True}
            ],
            note=NOTE,
        )
    assert excinfo.value.code == "unknown_item"
    assert excinfo.value.status_code == 422

    result = await confirm(
        ctx,
        USER,
        pid,
        items_override=[{"kind": "source", "ref": "src-a", "selected": False}],
        note=NOTE,
    )
    kept = {(i["kind"], i["ref"]): i["selected"] for i in result["proposal"]["items"]}
    assert kept[("source", "src-a")] is False
    assert kept[("document", "work/aurora.md")] is True


async def test_confirm_refuses_a_set_narrowed_to_nothing():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    overrides = [
        {"kind": item["kind"], "ref": item["ref"], "selected": False}
        for item in proposal["items"]
    ]
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(
            ctx, USER, proposal["proposal_id"], items_override=overrides, note=NOTE
        )
    assert excinfo.value.code == "empty"
    assert store.enqueued == []


async def test_confirming_twice_is_refused_rather_than_enqueuing_a_second_job():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)
    assert excinfo.value.code == "not_proposed"
    assert len(store.enqueued) == 1


async def test_an_unknown_proposal_is_a_404():
    canonical, store = _library()
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(_ctx(canonical, store), USER, "nope", note=NOTE)
    assert (excinfo.value.status_code, excinfo.value.code) == (404, "not_found")


# ---------------------------------------------------------------------------- drop


async def test_drop_closes_a_proposal_and_only_an_unconfirmed_one():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    dropped = await drop(ctx, USER, proposal["proposal_id"])
    assert dropped["status"] == "dropped"

    with pytest.raises(ArchiveRequestError) as excinfo:
        await drop(ctx, USER, proposal["proposal_id"])
    assert excinfo.value.code == "not_proposed"
    # A dropped proposal is not confirmable either — the decision was withdrawn.
    with pytest.raises(ArchiveRequestError):
        await confirm(ctx, USER, proposal["proposal_id"], note=NOTE)


# ----------------------------------------------------------------------- inventory


async def test_the_inventory_folds_volumes_and_names_the_day_each_page_went_in():
    canonical = _Canonical(
        [
            _doc("work/atlas.md", ("src-c",)),
            _doc("archive/work/aurora.md", ("src-a",)),
            _doc("archive/work/aurora/a01.md", ("src-a",)),
        ]
    )
    canonical.docs[2] = canonical.docs[2].model_copy(
        update={
            "frontmatter": {
                **canonical.docs[2].frontmatter,
                "archived_from": "work/aurora.md",
            }
        }
    )
    canonical.written = {
        "archive/work/aurora.md": "2026-09-02",
        "archive/work/aurora/a01.md": "2026-09-02",
    }
    store = _Store(
        [
            _source("src-a", "The Aurora kickoff", archived_at=NOW),
            _source("src-c", "The Atlas standup"),
        ]
    )

    result = await inventory(_ctx(canonical, store), USER)

    assert result["documents"] == [
        {
            "path": "archive/work/aurora.md",
            "live_path": "work/aurora.md",
            "title": "Aurora",
            "archived_on": "2026-09-02",
            # The volume travelled with its document and is NOT a row of its own.
            "volumes": 1,
            # This fixture's library was archived before records existed, so the page left
            # nothing behind at its live path and the row says so rather than guessing one.
            "record_path": None,
            "record": None,
        }
    ]
    assert result["sources"] == [
        {
            "source_id": "src-a",
            "title": "The Aurora kickoff",
            "kind": "conversation",
            "archived_at": NOW.isoformat(),
        }
    ]


async def test_the_inventory_names_the_record_standing_at_the_live_path():
    """The two halves point at each other: the row names where the record stands, and the
    record's own frontmatter says which copy it is the record OF. Nothing stores the join."""
    record = CanonicalDocument(
        doc_id=DocumentId("d-record"),
        path="work/aurora.md",
        frontmatter={
            "doc_id": "d-record",
            "type": "archived",
            "slug": "aurora",
            "title": "Aurora",
            "archive_of": "archive/work/aurora.md",
            "archived_on": "2026-09-04",
            "archive_statement": "src-stmt",
            "archive_span": "2026-01-04/2026-06-30",
            "archive_claims": "7",
            "archive_sources": "3",
            "archive_volumes": "1",
            "archive_inbound": "2",
        },
        body="# Aurora\n\n- Aurora was the programme. — archived <!-- c:cc330001 -->\n",
    )
    canonical = _Canonical([_doc("archive/work/aurora.md", ("src-a",)), record])
    canonical.written = {"archive/work/aurora.md": "2026-09-04"}
    store = _Store([_source("src-a", "The Aurora kickoff", archived_at=NOW)])

    result = await inventory(_ctx(canonical, store), USER)

    row = result["documents"][0]
    assert row["record_path"] == "work/aurora.md"
    assert row["record"] == {
        "archived_on": "2026-09-04",
        "statement_ref": "src-stmt",
        "archive_of": "archive/work/aurora.md",
        "span": ["2026-01-04", "2026-06-30"],
        "claims": 7,
        "sources": 3,
        "volumes": 1,
        "inbound": 2,
    }


async def test_the_owner_s_reason_lands_at_the_confirm_and_a_stored_note_is_never_one():
    """The confirm's own note IS the reason, and a note the plan happens to hold is not.

    The row's note was typed at a moment that decided nothing, possibly against a set the
    Owner has since narrowed — so promoting it at the confirm would record them as having
    said something at a time they did not. A confirm that says nothing is therefore refused
    even over a row that carries a note, and nothing is written.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    first = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note="planned reason", statement_ref=None,
    )
    result = await confirm(ctx, USER, first["proposal_id"], note="  Aurora shipped.  ")
    assert result["proposal"]["note"] == "Aurora shipped."
    quoted = next(
        item["record"]
        for item in result["proposal"]["items"]
        if item["kind"] == "document"
    )
    assert quoted["reason"] == "Aurora shipped."

    store.enqueued.clear()
    second = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note="planned reason", statement_ref=None,
    )
    with pytest.raises(ArchiveRequestError) as silent:
        await confirm(ctx, USER, second["proposal_id"])
    assert (silent.value.status_code, silent.value.code) == (422, "note_required")
    row = store.rows[second["proposal_id"]]
    assert (row["status"], row["note"]) == ("proposed", "planned reason")
    assert store.enqueued == []


async def test_a_statement_named_at_the_confirm_is_the_reason_and_is_written_with_it():
    """The other way to satisfy the confirm: point at speech that already exists.

    A plan that named none is confirmed by naming one here, and the ref is stored in the same
    transaction as the decision — the job reads it off the row, and a confirmed row without it
    would mint a SECOND `owner-dialogue/v1` source saying what the one the Owner named says.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=None, statement_ref=None,
    )
    result = await confirm(
        ctx, USER, proposal["proposal_id"], statement_ref="src-statement"
    )
    assert result["proposal"]["statement_ref"] == "src-statement"
    quoted = next(
        item["record"]
        for item in result["proposal"]["items"]
        if item["kind"] == "document"
    )
    # The statement's own block 0, label stripped — never the note beside it.
    assert quoted["reason"] == "Aurora shipped in June."


async def test_a_confirm_that_empties_the_note_is_refused_rather_than_defaulted():
    """Clearing the box is not a way to archive without a reason.

    An emptied note used to fall through to a sentence the framework composed and then
    ingested as the Owner's own `owner-dialogue/v1` statement — L0 saying they said
    something they never typed. There is no such sentence any more, so `""` is refused where
    it is typed and NOTHING is written: the plan's note stands, the row is untouched, and no
    job is queued.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note="planned reason", statement_ref=None,
    )
    with pytest.raises(ArchiveRequestError) as refused:
        await confirm(ctx, USER, proposal["proposal_id"], note="")
    assert (refused.value.status_code, refused.value.code) == (422, "note_required")
    # Whitespace is not a reason either — the same fold `sanitize_note` applies.
    with pytest.raises(ArchiveRequestError) as blank:
        await confirm(ctx, USER, proposal["proposal_id"], note="   \n ")
    assert blank.value.code == "note_required"

    row = store.rows[proposal["proposal_id"]]
    assert row["note"] == "planned reason"
    assert row["status"] == "proposed"
    assert store.enqueued == []


async def test_a_plan_needs_no_reason_and_the_CONFIRM_is_where_one_is_required():
    """Where the requirement lives, and why it is not one step earlier.

    A plan is a computation: it moves nothing, decides nothing, and the reason it would keep
    is a sentence typed against a set the Owner may still narrow. So a noteless plan is
    computed and kept with `note: null` and a null preview reason — and the refusal belongs
    to the CONFIRM, which is the decision the record states. Composing a sentence at either
    face would put the framework's prose into L0 under the Owner's name; keeping one at the
    plan and quoting it at execution would do the same thing one step removed.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    for note in (None, "", "   \n\t "):
        computed = await plan(
            ctx,
            USER,
            action="archive",
            documents=["work/aurora.md"],
            sources=[],
            note=note,
            statement_ref=None,
        )
        assert computed["status"] == "proposed"
        assert computed["note"] is None
        assert all(
            item["record"]["reason"] is None
            for item in computed["items"]
            if item["record"]
        )
        # …and the decision over it is refused, in the owner's absence of words.
        with pytest.raises(ArchiveRequestError) as refused:
            await confirm(ctx, USER, computed["proposal_id"], note=note)
        assert (refused.value.status_code, refused.value.code) == (422, "note_required")
        assert store.rows[computed["proposal_id"]]["status"] == "proposed"
    assert store.enqueued == []

    # A `statement_ref` satisfies it without a note — the Owner already spoke, and the
    # record cites THAT.
    spoken = await plan(
        ctx,
        USER,
        action="archive",
        documents=["work/aurora.md"],
        sources=[],
        note=None,
        statement_ref="src-statement",
    )
    assert spoken["status"] == "proposed"
    # …and a confirm over it needs no note at all: the words are the statement's.
    confirmed = await confirm(ctx, USER, spoken["proposal_id"])
    assert confirmed["job_id"]


# ------------------------------------------------- the ref names the tree that was read


class _MovingCanonical(_Canonical):
    """A canonical whose HEAD advances the instant its tree is read.

    The window the plan has to close: between "read the tree" and "read HEAD" a compile can
    land, and whichever of the two happens second decides what the proposal binds. Reading
    the tree first leaves `library_ref` naming a commit the items were never computed over.
    """

    def __init__(self, at_first: list, after: list) -> None:
        super().__init__(at_first, head="sha-1")
        self._trees = {"sha-1": at_first, "sha-2": after}
        self.listed_at: str | None = None

    async def list(self, user_id, *, at=None):
        # `at=None` means "whatever HEAD is now" — which is what it is BEFORE the compile
        # this call is about to let land.
        tree = self._trees[at.ref] if at is not None else self._trees[self.head]
        self.listed_at = at.ref if at is not None else None
        self.head = "sha-2"  # …and a compile lands, mid-plan.
        return list(tree)


async def test_plan_binds_exact_tree_ref_when_head_changes_during_list():
    # sha-1: Atlas still cites src-b, so archiving Aurora only LISTS src-b.
    # sha-2: Atlas is gone, so over that tree src-b would have been SELECTED.
    canonical = _MovingCanonical(
        [
            _doc("work/aurora.md", ("src-a",), ("src-b",)),
            _doc("work/atlas.md", ("src-b",), ("src-c",)),
        ],
        [_doc("work/aurora.md", ("src-a",), ("src-b",))],
    )
    store = _Store(
        [
            _source("src-a", "The Aurora kickoff"),
            _source("src-b", "The shared vendor review"),
            _source("src-c", "The Atlas standup"),
        ]
    )
    ctx = _ctx(canonical, store)

    result = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )

    # The listing was PINNED, and to the ref the proposal now carries.
    assert canonical.listed_at == "sha-1"
    assert result["library_ref"] == "sha-1"
    # …and the items are that tree's, not the one HEAD moved to: src-b is listed because
    # Atlas — a document that exists only at sha-1 — still cites it.
    by_ref = {(i["kind"], i["ref"]): i for i in result["items"]}
    assert by_ref[("source", "src-b")]["selected"] is False
    assert by_ref[("source", "src-b")]["reason"]["cited_by_live"] == ["work/atlas.md"]

    # And because the ref is the tree's own, the compile that landed is now visible as
    # staleness rather than being silently absorbed.
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, result["proposal_id"], note=NOTE)
    assert excinfo.value.code == "stale"


# ------------------------------------------------------- one winner, and never stranded


async def test_the_decision_and_the_job_it_queues_are_written_together():
    """One transaction, so neither half can be alone.

    A `confirmed` proposal with no job is a decision nothing executes and nothing fails —
    invisible rather than stuck. A job with no confirmed proposal is a mover for a decision
    nobody made. The store writes both under one predicate or writes neither, so the confirm
    has nothing to compensate for and no undo path to get wrong.
    """
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    result = await confirm(ctx, USER, pid, note=NOTE)

    assert store.rows[pid]["status"] == "confirmed"
    # The id the job carries IS the id the row records — one value, minted once.
    assert store.enqueued == [(ARCHIVE_JOB_KIND, {"proposal_id": pid})]
    assert store.rows[pid]["job_id"] == result["job_id"]
    # …and there is no window where the row is `confirmed` with no job to execute it, so
    # nothing later has to write the id in a second statement.


async def test_a_fast_worker_that_finishes_first_is_never_walked_back():
    """The worker is another process, and nothing in the confirm waits for it: it can claim,
    run and finish the whole archive before the confirm reads the row back. The confirm
    answers what the row SAYS rather than what it wrote, so `executed` stands."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    def the_worker_finishes_first():
        store.rows[pid]["status"] = "executed"
        store.rows[pid]["executed_at"] = NOW
        store.rows[pid]["detail"] = '{"ref": "sha-moved"}'

    store.on_confirm = the_worker_finishes_first

    result = await confirm(ctx, USER, pid, note=NOTE)

    assert store.rows[pid]["status"] == "executed"  # not walked back to `confirmed`
    assert store.rows[pid]["job_id"] == result["job_id"]  # and the id landed in the flip
    assert store.rows[pid]["detail"] == '{"ref": "sha-moved"}'
    assert result["proposal"]["status"] == "executed"


async def test_concurrent_confirms_enqueue_exactly_one_job():
    """Two confirms in flight both READ `proposed`. The predicate on the write is what
    decides between them, so only one job is ever queued for one move."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    proposal = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    pid = proposal["proposal_id"]

    # Both confirms read `proposed` — that IS the race — so the read-side check clears
    # both and only the write can decide.
    store.reads_as = "proposed"
    first = await confirm(ctx, USER, pid, note=NOTE)
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, pid, note=NOTE)

    assert first["job_id"] == "job-1"
    assert excinfo.value.code == "not_proposed"
    assert store.enqueued == [(ARCHIVE_JOB_KIND, {"proposal_id": pid})]


async def test_confirm_and_drop_have_one_atomic_winner():
    """The same predicate from the other side: a drop that lost the race must not close a
    proposal that now has a job, and a confirm that lost must not queue a withdrawn one."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)

    first = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    store.reads_as = "proposed"  # both callers read the row before either wrote
    await confirm(ctx, USER, first["proposal_id"], note=NOTE)
    with pytest.raises(ArchiveRequestError) as excinfo:
        await drop(ctx, USER, first["proposal_id"])
    assert excinfo.value.code == "not_proposed"
    assert store.rows[first["proposal_id"]]["status"] == "confirmed"

    second = await plan(
        ctx, USER, action="archive", documents=["work/aurora.md"], sources=[],
        note=NOTE, statement_ref=None,
    )
    await drop(ctx, USER, second["proposal_id"])
    with pytest.raises(ArchiveRequestError) as excinfo:
        await confirm(ctx, USER, second["proposal_id"], note=NOTE)
    assert excinfo.value.code == "not_proposed"
    assert len(store.enqueued) == 1  # the dropped one never reached the queue
