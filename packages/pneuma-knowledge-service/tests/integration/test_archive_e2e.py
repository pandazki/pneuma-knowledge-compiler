"""The archive end to end, against live middleware: propose → confirm → job → every face.

docs/design/archive.md. Slice by slice the pieces are covered elsewhere; what only a live
stack can show is the property the whole design exists for — after ONE confirmed proposal,
the archived material is absent from every default face (L1 blocks, L2 chunks, both claim
indexes, the source catalogue) and present in all of them the moment a call says
`include_archived`. And that unarchiving is the same move back, not a repair.

Compile is deliberately not in the loop: the documents are written straight through
`commit_patch`, because what is under test is the MOVE and the marks, and a scripted compile
would only add a model to the fixture.
"""

from __future__ import annotations

import hashlib
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.canonical_glance import render_canonical_glance
from pneuma_knowledge_core.compile.anchor_ops import anchored_blocks
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.archive.record import record_doc_id
from pneuma_knowledge_core.compile.patch import assign_document_id
from pneuma_knowledge_core.domain.archive import live_documents
from pneuma_knowledge_core.domain.ids import SourceId, UserId, extract_anchors
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service import archive_service
from pneuma_knowledge_service.api.routes.archive import get_archive
from pneuma_knowledge_service.api.routes.v1 import list_sources, post_compile
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.projection import rebuild_projection
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs, drain_user
from types import SimpleNamespace


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def ctx(tmp_path):
    s = Settings(canonical_root=str(tmp_path / "canonical"))
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    c = await build_context(s)
    yield c
    await c.aclose()


def _turn(text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker="A", text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


def _document(path: str, slug: str, claims: list[tuple[str, str]]) -> str:
    lines = [f"# {slug.title()}", ""]
    for i, (text, sid) in enumerate(claims):
        anchor = hashlib.sha256(f"{path}:{i}".encode()).hexdigest()[:8]
        lines.append(f"- {text} [cite: {sid} ¶0-0] <!-- c:{anchor} -->")
    return render_document({"type": "topic", "slug": slug}, "\n".join(lines))


async def _seed(ctx, user) -> tuple[str, str]:
    """Two sources, two documents: Aurora cites its own source plus the shared one."""
    aurora = await ingest_conversation(
        ctx, user, [_turn("Aurora delivery cadence and acceptance criteria")],
        title="Aurora kickoff",
    )
    vendor = await ingest_conversation(
        ctx, user, [_turn("Vendor review payment terms for the quarter")],
        title="Vendor review",
    )
    # Ingest enqueues an index job AND a compile job per source. This fixture writes the
    # documents itself, so the compile jobs are settled rather than run — otherwise they
    # would sit at the head of the queue and the archive job could not be drained alone.
    for job in await ctx.store.list_jobs(user):
        if job["kind"] == "compile" and job["status"] == "queued":
            await ctx.store.complete(
                user, job["job_id"], ok=True, detail="fixture writes canonical directly"
            )
    assert await drain_index_jobs(ctx, user) == 2
    sid_a, sid_b = str(aurora.source_id), str(vendor.source_id)

    snapshot = await ctx.canonical.commit_patch(
        user,
        {
            "work/aurora.md": _document(
                "work/aurora.md",
                "aurora",
                [
                    ("Aurora ships on a two-week cadence.", sid_a),
                    ("Aurora pays the vendor quarterly.", sid_b),
                ],
            ),
            "work/atlas.md": _document(
                "work/atlas.md",
                "atlas",
                [("Atlas pays the vendor quarterly too.", sid_b)],
            ),
        },
        message="seed the library",
    )
    await rebuild_projection(ctx, user, snapshot.ref)
    return sid_a, sid_b


def _request(ctx) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


async def _catalogue(ctx, user, *, include_archived: bool) -> set[str]:
    page = await list_sources(
        str(user),
        _request(ctx),
        limit=50,
        cursor=None,
        query=None,
        kind=None,
        include_archived=include_archived,
    )
    return {item.source_id for item in page.items}


async def _block_hits(ctx, user, query: str, *, include_archived: bool) -> set[str]:
    hits = await ctx.lexical.search(
        user, query, limit=20, include_archived=include_archived
    )
    return {str(hit.source_id) for hit in hits}


async def _claim_paths(ctx, user, query: str, *, include_archived: bool) -> set[str]:
    hits = await ctx.lexical.search_claims(
        user, query, limit=40, include_archived=include_archived
    )
    return {hit.document_path for hit in hits}


async def _chunk_hits(ctx, user, text: str, *, include_archived: bool) -> set[str]:
    vector = await ctx.embeddings.aembed_query(text)
    hits = await ctx.vectors.search(
        user, vector, limit=20, include_archived=include_archived
    )
    return {str(hit.source_id) for hit in hits}


async def _claim_vector_paths(ctx, user, text: str, *, include_archived: bool) -> set[str]:
    vector = await ctx.embeddings.aembed_query(text)
    hits = await ctx.vectors.search_claims(
        user, vector, limit=40, include_archived=include_archived
    )
    return {hit.document_path for hit in hits}


async def test_one_confirmed_proposal_moves_a_subject_out_of_every_default_face(ctx):
    user = UserId(f"u-it-archive-{uuid.uuid4().hex[:8]}")
    try:
        sid_a, sid_b = await _seed(ctx, user)

        # The page exactly as it stands before anything moves. An unarchive has to give it
        # back byte for byte — a move that also rewrote what it moved would make the archive
        # a lossy operation, and this is the only place that can be seen end to end.
        before = (ctx.canonical.repo_path(user) / "work" / "aurora.md").read_text(
            encoding="utf-8"
        )

        # ---------------------------------------------------------------- propose
        proposal = await archive_service.plan(
            ctx, user, action="archive", documents=["work/aurora.md"],
            sources=[], note="Aurora shipped.", statement_ref=None,
        )
        items = {(i["kind"], i["ref"]): i for i in proposal["items"]}
        # The source only Aurora cited is selected; the one Atlas still cites is LISTED and
        # not selected, naming the document that kept it.
        assert items[("document", "work/aurora.md")]["selected"] is True
        assert items[("source", sid_a)]["selected"] is True
        assert items[("source", sid_a)]["reason"]["note"] == "orphaned"
        assert items[("source", sid_b)]["selected"] is False
        assert items[("source", sid_b)]["reason"]["cited_by_live"] == ["work/atlas.md"]
        # The document item carries the RECORD it would leave behind, computed at plan
        # time so the console previews the page each checkbox creates. Two claims over
        # two sources; nothing in this library links to Aurora, so `inbound` is 0 —
        # stated either way rather than left implicit.
        preview = items[("document", "work/aurora.md")]["record"]
        assert preview["title"] == "Aurora"
        assert (preview["claims"], preview["sources"], preview["volumes"]) == (2, 2, 0)
        assert preview["inbound"] == 0
        assert preview["definition"]

        # ---------------------------------------------------------------- confirm
        # THE REASON TRAVELS WITH THE DECISION: the confirm carries the owner's words, and
        # they are what the statement source and the record's third block will say.
        confirmed = await archive_service.confirm(
            ctx, user, proposal["proposal_id"], note="Aurora shipped."
        )
        assert confirmed["proposal"]["status"] == "confirmed"
        # TWO jobs, drained through the ordinary worker dispatch: the archive itself, and
        # the `index` job the Owner's statement enqueued on its way in. The archive is a
        # queue citizen like every other canonical writer, and so is the statement — it is
        # L0 like any other L0, indexed the ordinary way.
        assert await drain_user(ctx, None, load_skill_base("v1"), user) == 2

        row = await ctx.store.get_archive_proposal(user, proposal["proposal_id"])
        assert row["status"] == "executed", row["detail"]

        # ------------------------------------------------------- the two authorities
        paths = {doc.path for doc in await ctx.canonical.list(user)}
        # THREE paths, not two: the page moved AND left a record standing where it was.
        # A subject that simply vanished would leave `work/atlas.md` linking into nothing
        # and every question about Aurora answered out of whatever mentions survived
        # elsewhere.
        assert paths == {
            "archive/work/aurora.md",
            "work/aurora.md",
            "work/atlas.md",
        }
        moved = next(
            doc
            for doc in await ctx.canonical.list(user)
            if doc.path == "archive/work/aurora.md"
        )
        # The MOVE moved: what stands under `archive/` is the page that stood at the live
        # path, byte for byte.
        assert (
            ctx.canonical.repo_path(user) / "archive" / "work" / "aurora.md"
        ).read_text(encoding="utf-8") == before
        assert await ctx.store.archived_source_ids(user) == frozenset(
            {SourceId(sid_a)}
        )
        # L0 by address is unconditional (I3): the archived source still answers verbatim.
        assert await ctx.store.fetch(user, SourceId(sid_a), {"blocks": [0, 0]})

        # ------------------------------------------------------------- the record
        record = next(
            doc for doc in await ctx.canonical.list(user) if doc.path == "work/aurora.md"
        )
        assert record.frontmatter["type"] == "archived"
        assert record.frontmatter["archive_of"] == "archive/work/aurora.md"
        assert record.frontmatter["title"] == "Aurora"
        assert record.frontmatter["archive_claims"] == "2"
        assert record.frontmatter["archive_sources"] == "2"
        statement_ref = record.frontmatter["archive_statement"]
        # The record and the full copy are TWO documents, so they carry two ids: the copy
        # keeps the id it had while it stood here, the record's is derived from its own key.
        # One id on both would make `read(user, doc_id)` answer with whichever of the two the
        # listing happened to reach first.
        assert record.frontmatter["doc_id"] == str(record_doc_id("work/aurora.md"))
        assert record.frontmatter["doc_id"] != str(
            assign_document_id("work/aurora.md")
        )
        # …and nothing else in the tree answers to it, so `read(user, doc_id)` is a question
        # with one answer.
        assert [
            doc.path
            for doc in await ctx.canonical.list(user)
            if str(doc.doc_id) == record.frontmatter["doc_id"]
        ] == ["work/aurora.md"]

        blocks = anchored_blocks(record.body)
        assert len(blocks) == 3
        assert blocks[0].endswith("— archived <!-- c:%s -->" % extract_anchors(blocks[0])[0])
        assert "ledger claims" in blocks[1] and "[cite:" not in blocks[1]
        assert f"[cite: {statement_ref} ¶0]" in blocks[2]
        assert "Aurora shipped." in blocks[2]

        # The statement is an ORDINARY source: verbatim in L0, addressable, and compiled by
        # nobody — the record is already its canonical expression.
        statement = await ctx.store.get(user, SourceId(statement_ref))
        assert statement.raw.kind == "owner_dialogue"
        assert statement.raw.intake_plan["canonical_treatment"] == "none"
        assert "Aurora shipped." in statement.blocks[0].text
        assert not [
            job
            for job in await ctx.store.list_jobs(user)
            if job["kind"] == "compile" and job["status"] == "queued"
        ]

        # -------------------------------------------------------- the derived faces
        assert sid_a not in await _block_hits(ctx, user, "Aurora", include_archived=False)
        assert sid_a in await _block_hits(ctx, user, "Aurora", include_archived=True)
        assert sid_b in await _block_hits(ctx, user, "vendor", include_archived=False)

        # THE PROPERTY THE RECORD EXISTS FOR. A default question about Aurora reaches the
        # record's claims and nothing from the full copy: the subject still answers, and it
        # answers "this is what it was, and the owner retired it on this day because of
        # this" rather than with silence or with a stale claim.
        default_claims = await _claim_paths(ctx, user, "Aurora", include_archived=False)
        assert "work/aurora.md" in default_claims
        assert "archive/work/aurora.md" not in default_claims
        assert "archive/work/aurora.md" in await _claim_paths(
            ctx, user, "Aurora", include_archived=True
        )
        # …and specifically the reason line, which is the sentence a reader quotes back.
        assert "work/aurora.md" in await _claim_paths(
            ctx, user, "Archived by the owner", include_archived=False
        )
        assert "work/aurora.md" in await _claim_vector_paths(
            ctx, user, "why was Aurora archived", include_archived=False
        )

        # The GLANCE lists the record, marked, so a reader deciding what to open sees that
        # this page is a record rather than the subject itself.
        glance = render_canonical_glance(
            live_documents(await ctx.canonical.list(user)),
            templates=["work/*.md"],
        )
        assert "`work/aurora.md`" in glance
        entry = next(
            line for line in glance.splitlines() if "`work/aurora.md`" in line
        )
        assert entry.endswith("archived)")

        assert sid_a not in await _chunk_hits(
            ctx, user, "Aurora delivery cadence", include_archived=False
        )
        assert sid_a in await _chunk_hits(
            ctx, user, "Aurora delivery cadence", include_archived=True
        )
        assert "archive/work/aurora.md" not in await _claim_vector_paths(
            ctx, user, "Aurora ships on a cadence", include_archived=False
        )
        assert "archive/work/aurora.md" in await _claim_vector_paths(
            ctx, user, "Aurora ships on a cadence", include_archived=True
        )

        # ------------------------------------------------------------ the listings
        # The owner's statement is in the catalogue like any other source — that is what it
        # is. Nothing about it is privileged, including its visibility.
        assert await _catalogue(ctx, user, include_archived=False) == {
            sid_b,
            statement_ref,
        }
        assert await _catalogue(ctx, user, include_archived=True) == {
            sid_a,
            sid_b,
            statement_ref,
        }

        archive = await get_archive(str(user), _request(ctx))
        assert [d["path"] for d in archive["documents"]] == ["archive/work/aurora.md"]
        assert archive["documents"][0]["live_path"] == "work/aurora.md"
        assert archive["documents"][0]["archived_on"]  # the day of the move commit
        assert [s["source_id"] for s in archive["sources"]] == [sid_a]
        # …and the inventory names the record standing on the other side of the move.
        assert archive["documents"][0]["record_path"] == "work/aurora.md"
        inventory_record = archive["documents"][0]["record"]
        assert inventory_record["archive_of"] == "archive/work/aurora.md"
        assert inventory_record["claims"] == 2
        assert inventory_record["sources"] == 2
        assert inventory_record["statement_ref"]

        # An archived source is not offered to compile again: the Owner said the material
        # is not current, and a compile of it would write LIVE claims about it.
        compiled = await post_compile(str(user), _request(ctx))
        assert compiled.source_ids == [sid_b]
        for enqueued_job in compiled.enqueued:
            await ctx.store.complete(
                user, enqueued_job, ok=True, detail="fixture writes canonical directly"
            )

        # -------------------------------------------------------- and back again
        back = await archive_service.plan(
            ctx, user, action="unarchive", documents=["archive/work/aurora.md"],
            sources=[], note="Aurora is back on the roadmap.", statement_ref=None,
        )
        back_items = {(i["kind"], i["ref"]): i for i in back["items"]}
        assert back_items[("document", "archive/work/aurora.md")]["selected"] is True
        assert back_items[("source", sid_a)]["selected"] is True

        await archive_service.confirm(
            ctx, user, back["proposal_id"], note="Aurora is back on the roadmap."
        )
        assert await drain_user(ctx, None, load_skill_base("v1"), user) == 1

        assert {doc.path for doc in await ctx.canonical.list(user)} == {
            "work/aurora.md",
            "work/atlas.md",
        }
        # BYTE FOR BYTE: the record was replaced by the page it stood in for, in one commit,
        # and the page is exactly the one that went in.
        assert (ctx.canonical.repo_path(user) / "work" / "aurora.md").read_text(
            encoding="utf-8"
        ) == before
        # No second statement on the way back: the owner is undoing a decision, not making
        # another one.
        assert [
            str(raw.source_id)
            for raw in await ctx.store.list(user)
            if raw.kind == "owner_dialogue"
        ] == [statement_ref]
        assert await ctx.store.archived_source_ids(user) == frozenset()
        assert sid_a in await _block_hits(ctx, user, "Aurora", include_archived=False)
        assert "work/aurora.md" in await _claim_paths(
            ctx, user, "Aurora", include_archived=False
        )
        assert await _catalogue(ctx, user, include_archived=False) == {
            sid_a,
            sid_b,
            statement_ref,
        }
        assert await get_archive(str(user), _request(ctx)) == {
            "documents": [],
            "sources": [],
        }

        # The WORKING TREE, not just the commit. git tracks files and not directories, so an
        # unarchive that moved the last page out of `archive/work/` would leave both folders
        # behind as empty shells — `git status` clean, every mechanism correct, and a
        # repository that still shows an `archive/` to anyone reading it as a library.
        repo = ctx.canonical.repo_path(user)
        assert not (repo / "archive").exists()
        assert (repo / "work" / "aurora.md").is_file()  # and the pages themselves are there
        assert (repo / "work" / "atlas.md").is_file()
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
