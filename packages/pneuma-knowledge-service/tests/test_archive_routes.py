"""The archive HTTP surface: what each endpoint answers, and how a refusal reaches the wire.

The service's judgements are covered in `test_archive_service.py`; what could silently go
wrong HERE is the surface — a refusal that arrives as a 500, a 409 with no machine-readable
code beside the sentence, a proposal whose items lose their reason on the way out.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pneuma_knowledge_service.api.routes.archive import (
    ConfirmIn,
    ProposeIn,
    confirm_archive_proposal,
    get_archive,
    propose_archive,
    router as archive_router,
)
from pneuma_knowledge_service.archive_service import ArchiveRequestError

from test_archive_service import _Canonical, _Store, _doc, _source

USER = "u-archive-routes"
#: Every CONFIRM carries a reason, because every confirm must (`note_required`, its own test
#: below); a plan needs none — its `note` is an informational line. Stated once so the tests
#: that are about something else need not invent one.
NOTE = "Aurora shipped in June; the team is disbanded."


def _ctx() -> SimpleNamespace:
    canonical = _Canonical(
        [
            _doc("work/aurora.md", ("src-a",), ("src-b",)),
            _doc("work/atlas.md", ("src-b",)),
        ]
    )
    store = _Store(
        [_source("src-a", "The Aurora kickoff"), _source("src-b", "The vendor review")]
    )
    return SimpleNamespace(canonical=canonical, store=store)


def _request(ctx: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


def _app(ctx: SimpleNamespace) -> FastAPI:
    """The router under the one handler `api/app.py` registers for it."""
    app = FastAPI()

    async def refused(_request, exc: ArchiveRequestError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"detail": str(exc), "code": exc.code}
        )

    app.add_exception_handler(ArchiveRequestError, refused)
    app.include_router(archive_router)
    app.state.ctx = ctx
    return app


# --------------------------------------------------------------------------- routes


async def test_propose_answers_the_whole_computed_set_with_a_reason_per_item():
    ctx = _ctx()
    result = await propose_archive(
        USER,
        ProposeIn(action="archive", documents=["work/aurora.md"], note="shipped"),
        _request(ctx),
    )
    by_ref = {(i["kind"], i["ref"]): i for i in result["items"]}
    assert by_ref[("source", "src-a")]["reason"]["note"] == "orphaned"
    assert by_ref[("source", "src-b")]["reason"]["cited_by_live"] == ["work/atlas.md"]
    assert result["library_ref"] == "sha-1"


async def test_propose_refuses_a_request_that_names_nothing():
    with pytest.raises(HTTPException) as excinfo:
        await propose_archive(USER, ProposeIn(), _request(_ctx()))
    assert excinfo.value.status_code == 422


async def test_a_user_id_outside_the_one_pattern_is_refused():
    with pytest.raises(HTTPException) as excinfo:
        await get_archive("../etc", _request(_ctx()))
    assert excinfo.value.status_code == 422


async def test_confirm_accepts_a_body_with_no_overrides_at_all():
    ctx = _ctx()
    proposal = await propose_archive(
        USER, ProposeIn(documents=["work/aurora.md"], note=NOTE), _request(ctx)
    )
    result = await confirm_archive_proposal(
        USER, proposal["proposal_id"], _request(ctx), ConfirmIn(note=NOTE)
    )
    assert result["job_id"] == "job-1"
    assert ctx.store.enqueued == [("archive", {"proposal_id": proposal["proposal_id"]})]


# ---------------------------------------------------------------------- the wire


def test_the_unarchive_reason_keeps_cited_by_archived_through_the_response_model():
    """The finding: `ProposalReasonOut` declared only `cited_by_live`, so FastAPI validated
    `cited_by_archived` away and every unarchive proposal reached the console with a
    `restored_with_page` note and no evidence for it.

    Read through the APP rather than the handler, because that is where the response model
    runs — a direct call returns the service's dict and could never have shown the loss. The
    two fields are one per side of the library (archive.md §5): the page that brings this
    source back is ARCHIVED right now, so naming it under `cited_by_live` would have been the
    one place this planner said something untrue."""
    ctx = SimpleNamespace(
        canonical=_Canonical(
            [
                _doc("archive/work/aurora.md", ("src-a",)),
                _doc("work/atlas.md", ("src-a",), ("src-c",)),
            ]
        ),
        store=_Store(
            [
                _source("src-a", "The Aurora kickoff", archived_at="2026-08-01T00:00:00Z"),
                _source("src-c", "The vendor review"),
            ]
        ),
    )
    client = TestClient(_app(ctx))

    out = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={
            "action": "unarchive",
            "documents": ["archive/work/aurora.md"],
            "note": NOTE,
        },
    )

    assert out.status_code == 200, out.text
    reason = {
        (i["kind"], i["ref"]): i["reason"] for i in out.json()["items"]
    }[("source", "src-a")]
    assert reason["note"] == "restored_with_page"
    assert reason["cited_by_archived"] == ["archive/work/aurora.md"]
    # …and the other side of the library stays empty, rather than borrowing this evidence.
    assert reason["cited_by_live"] == []


def test_a_stale_confirm_reaches_the_wire_as_a_409_with_a_machine_code():
    ctx = _ctx()
    client = TestClient(_app(ctx))
    proposal = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": NOTE},
    ).json()
    assert proposal["status"] == "proposed"

    ctx.canonical.head = "sha-2"  # a compile landed under the preview
    response = client.post(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}/confirm", json={}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "stale"
    assert "re-plan" in body["detail"].lower()


def test_a_listing_reads_stale_off_the_current_head_without_writing_anything():
    """The console's own next call is where a proposal the library outran stops claiming to
    be open — computed from `library_ref` against HEAD, with no sweep behind it."""
    ctx = _ctx()
    client = TestClient(_app(ctx))
    proposal = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": NOTE},
    ).json()

    ctx.canonical.head = "sha-2"  # a compile landed and nobody came back to the dialogue

    listed = client.get(f"/v1/users/{USER}/archive/proposals").json()
    assert [row["status"] for row in listed] == ["stale"]
    one = client.get(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}"
    ).json()
    assert one["status"] == "stale"
    # The kept record was not touched by a read.
    assert ctx.store.rows[proposal["proposal_id"]]["status"] == "proposed"

    # …and the Owner can still clear it off the list, which is all that is left to do.
    dropped = client.post(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}/drop"
    )
    assert dropped.status_code == 200
    assert dropped.json()["status"] == "dropped"


def test_confirm_answers_202_and_the_inventory_lists_what_is_in_the_archive():
    ctx = _ctx()
    client = TestClient(_app(ctx))
    proposal = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": NOTE},
    ).json()

    accepted = client.post(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}/confirm",
        json={"note": NOTE},
    )
    assert accepted.status_code == 202
    assert accepted.json()["proposal"]["status"] == "confirmed"

    listed = client.get(f"/v1/users/{USER}/archive/proposals").json()
    assert [row["proposal_id"] for row in listed] == [proposal["proposal_id"]]
    assert client.get(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}"
    ).json()["job_id"] == "job-1"

    # Nothing has executed yet, so the archive is still empty — the job does the moving.
    assert client.get(f"/v1/users/{USER}/archive").json() == {
        "documents": [],
        "sources": [],
    }


def test_an_unknown_proposal_is_a_404_with_a_code():
    client = TestClient(_app(_ctx()))
    response = client.get(f"/v1/users/{USER}/archive/proposals/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_a_dropped_proposal_can_no_longer_be_confirmed():
    ctx = _ctx()
    client = TestClient(_app(ctx))
    proposal = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": NOTE},
    ).json()
    pid = proposal["proposal_id"]

    assert (
        client.post(f"/v1/users/{USER}/archive/proposals/{pid}/drop").json()["status"]
        == "dropped"
    )
    response = client.post(
        f"/v1/users/{USER}/archive/proposals/{pid}/confirm", json={}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "not_proposed"
    assert ctx.store.enqueued == []


def test_the_record_preview_carries_the_line_that_will_be_quoted():
    """The console previews the page each checkbox creates — its numbers AND its sentence.

    `reason` has to survive the response model: an undeclared field is silently stripped by
    FastAPI, and a console would then render a record preview with no reason in it and no
    error anywhere saying why. It is NULL on a plan that named no statement — the reason is
    the note sent with the confirm — and null has to reach the wire as null rather than as
    the empty string a `str` field would coerce it to, because the console reads "no line
    kept here" and shows its own box.
    """
    ctx = _ctx()
    client = TestClient(_app(ctx))
    proposal = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": "an informational line"},
    ).json()
    record = next(
        item["record"] for item in proposal["items"] if item["kind"] == "document"
    )
    assert record["reason"] is None
    assert record["title"] == "Aurora"

    # The confirm's own words are what the field then carries, all the way out.
    confirmed = client.post(
        f"/v1/users/{USER}/archive/proposals/{proposal['proposal_id']}/confirm",
        json={"note": "Aurora shipped in June."},
    ).json()
    quoted = next(
        item["record"]
        for item in confirmed["proposal"]["items"]
        if item["kind"] == "document"
    )
    assert quoted["reason"] == "Aurora shipped in June."


def test_a_confirm_with_no_reason_is_422_note_required_on_the_wire():
    """The framework never speaks for the Owner, and the wire says so with a machine code.

    The reason is kept as an `owner-dialogue/v1` source — L0 labelled as the Owner speaking
    — so the CONFIRM, which is the decision that source records, is refused unless it carries
    the words itself. A plan is not that decision: it takes no reason, keeps its `note` as an
    informational line, and is computed all the same. The console's answer to the friction is
    a PREFILLED suggestion in its own box, which the Owner edits and sends with the confirm.
    """
    ctx = _ctx()
    client = TestClient(_app(ctx))
    planned = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": NOTE},
    )
    assert planned.status_code == 200
    proposal = planned.json()
    pid = proposal["proposal_id"]

    # A confirm saying nothing, a cleared box, and a blank one: all three refused, and the
    # note the row happens to hold is a fallback for none of them.
    for body in ({}, {"note": ""}, {"note": "   \n "}):
        refused = client.post(
            f"/v1/users/{USER}/archive/proposals/{pid}/confirm", json=body
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "note_required"
        # Nothing moved: the row is still open, holding the line it was planned with.
        assert ctx.store.rows[pid]["status"] == "proposed"
        assert ctx.store.rows[pid]["note"] == NOTE
        assert ctx.store.enqueued == []

    # A plan with no note at all is computed and kept, with nothing quotable on it.
    noteless = client.post(
        f"/v1/users/{USER}/archive/proposals", json={"documents": ["work/atlas.md"]}
    )
    assert noteless.status_code == 200
    assert noteless.json()["note"] is None


def test_a_note_carrying_machinery_reaches_the_wire_as_422_note_machinery():
    """The refusal is machine-readable and names what to delete — the console can say so."""
    ctx = _ctx()
    client = TestClient(_app(ctx))
    response = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "note": "shipped <!-- c:aaaa1111 -->"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "note_machinery"
    assert "<!--" in response.json()["detail"]


def test_an_unknown_statement_ref_reaches_the_wire_as_422_statement_unknown():
    ctx = _ctx()
    client = TestClient(_app(ctx))
    response = client.post(
        f"/v1/users/{USER}/archive/proposals",
        json={"documents": ["work/aurora.md"], "statement_ref": "src-nowhere"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "statement_unknown"
