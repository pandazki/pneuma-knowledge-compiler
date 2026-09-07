"""`pkc archive …` — the archive at the Steward's door (coding-agent-mode §5.5).

Driven through `dispatch`, so what is under test is the command as the process runs it: the
parser's own arguments, the same `archive_service` functions the HTTP routes call, and the
exit codes the rest of `pkc` speaks. The doubles are the archive service's own
(`test_archive_service`), because a second in-memory `archive_proposals` table would be a
second answer to "what does a confirm do".

Two of these tests are about where this door differs from the wire — a confirm is refused
without the owner's words in terms that name `pkc owner say` (the requirement itself is the
service's too, `422 note_required`), and only what the owner NAMED is confirmed — and they
are the reason the module exists at all.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.cli.archive import NEED_OWNER_WORDS
from pneuma_knowledge_service.coding_agent.steward_turns import (
    SESSION_ENV,
    InMemoryStewardTurnStore,
)

from test_archive_service import (  # noqa: E402
    USER,
    _Canonical,
    _ctx,
    _doc,
    _library,
    _owner_statement,
    _source,
    _Store,
)

STATEMENT = "src-statement"
SAID = "Aurora shipped in June."


async def run(ctx, *argv):
    """One `pkc …` invocation, parsed as the process parses it. `(code, stdout, stderr)`."""
    args = build_parser().parse_args(["--user", str(USER), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def note_file(tmp_path, text: str) -> str:
    path = tmp_path / "note.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return str(path)


async def propose(ctx, *extra):
    return await run(
        ctx,
        "archive",
        "propose",
        "--document",
        "work/aurora.md",
        "--statement",
        STATEMENT,
        *extra,
    )


async def proposal_id(ctx) -> str:
    code, out, _err = await propose(ctx, "--json")
    assert code == 0
    return json.loads(out)["proposal_id"]


# ── the owner's words ──────────────────────────────────────────────────────────────────


async def test_a_proposal_without_the_owners_words_is_computed_and_quotes_nothing():
    """A plan decides nothing, so it is not where the owner's words are asked for.

    The service made this its own rule: `_reason_line(required=False)` previews NO sentence
    for a plan carrying no statement, and the note a plan holds is display text that will
    never become a record's reason. A door that demanded the words here would be asking for
    them at the one moment that cannot use them — and would teach a Steward that the note
    they gave is the sentence the page will quote.
    """
    canonical, store = _library()
    code, out, err = await run(
        _ctx(canonical, store), "archive", "propose", "--document", "work/aurora.md"
    )
    assert code == 0
    assert err == ""
    # The record preview says where the reason WILL come from rather than showing one.
    assert "pkc archive confirm" in out
    assert "«" not in out


async def test_a_confirm_without_the_owners_words_is_refused_and_queues_nothing():
    """Where the rule lives now, on both sides: this door refuses before it asks, and the
    service would refuse the same request `note_required` if it got there."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)
    code, _out, err = await run(ctx, "archive", "confirm", pid)
    assert code == 2
    assert err.strip() == NEED_OWNER_WORDS
    assert "pkc owner say" in err
    assert store.enqueued == []
    assert store.rows[pid]["status"] == "proposed"


async def test_the_services_own_note_required_surfaces_as_exit_two(tmp_path):
    """A note this door accepted and the service did not: whitespace sanitizes to nothing, so
    `_reason_line` refuses `note_required` and the CLI prints the service's own words."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    code, out, _err = await run(
        ctx, "archive", "propose", "--document", "work/aurora.md", "--json"
    )
    assert code == 0
    pid = json.loads(out)["proposal_id"]
    code, _out, err = await run(
        ctx, "archive", "confirm", pid, "--note-file", note_file(tmp_path, "   ")
    )
    assert code == 2
    assert "say why" in err
    assert store.enqueued == []


async def test_a_note_that_says_something_other_than_the_statement_is_refused(tmp_path):
    """The service's own `statement_mismatch`, in the service's own words: the record quotes
    the source it cites, so the two cannot disagree."""
    canonical, store = _library()
    code, _out, err = await propose(
        _ctx(canonical, store), "--note-file", note_file(tmp_path, "Aurora was cancelled.")
    )
    assert code == 2
    assert "say different things" in err
    assert store.rows == {}


async def test_inside_a_steward_session_a_note_must_be_what_the_owner_typed(
    tmp_path, monkeypatch
):
    """Ruling 13's check, applied to the one other text a Steward records for the owner: the
    note is quoted into a claim on a live page, which is exactly what the check is for."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    turns = InMemoryStewardTurnStore()
    await turns.append(USER, "stw-1", "Aurora shipped in June. Retire it please.")
    ctx.steward_turns = turns
    monkeypatch.setenv(SESSION_ENV, "stw-1")

    code, _out, err = await run(
        ctx,
        "archive",
        "propose",
        "--document",
        "work/aurora.md",
        "--note-file",
        note_file(tmp_path, "The owner wants Aurora gone."),
    )
    assert code == 2
    assert "verbatim" in err
    assert store.rows == {}

    code, _out, _err = await run(
        ctx,
        "archive",
        "propose",
        "--document",
        "work/aurora.md",
        "--note-file",
        note_file(tmp_path, "Aurora shipped in June."),
    )
    assert code == 0
    assert len(store.rows) == 1


# ── propose ────────────────────────────────────────────────────────────────────────────


async def test_a_proposal_prints_the_whole_computed_set_with_the_reason_for_each_item():
    canonical, store = _library()
    code, out, _err = await propose(_ctx(canonical, store))
    assert code == 0
    # The seed, its orphaned source, and the source another live page still holds — each with
    # the mechanical reason rendered in words rather than as its code.
    assert "work/aurora.md" in out and "seed" in out
    assert "no live page cites it any more" in out
    assert "still cited by work/atlas.md" in out
    # The record the page would leave, previewed under it: what it was, what it held, why.
    assert "record:" in out
    assert "ledger claims" in out
    assert f"«{SAID}»" in out
    # And what a confirm would leave behind unless the owner says otherwise.
    assert "--cascade" in out


async def test_the_json_of_a_proposal_is_the_wires_own_shape():
    canonical, store = _library()
    code, out, _err = await propose(_ctx(canonical, store), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "proposed"
    assert payload["library_ref"] == "sha-1"
    assert payload["statement_ref"] == STATEMENT
    assert payload["seeds"] == {"documents": ["work/aurora.md"], "sources": []}
    kinds = {(item["kind"], item["ref"]): item for item in payload["items"]}
    assert kinds[("document", "work/aurora.md")]["role"] == "seed"
    assert kinds[("source", "src-a")]["selected"] is True
    assert kinds[("source", "src-b")]["selected"] is False
    assert kinds[("document", "work/aurora.md")]["record"]["reason"] == SAID


async def test_a_proposal_naming_nothing_is_refused():
    canonical, store = _library()
    code, _out, err = await run(
        _ctx(canonical, store), "archive", "propose", "--statement", STATEMENT
    )
    assert code == 2
    assert "name at least one page" in err


# ── ls · show · drop ───────────────────────────────────────────────────────────────────


async def test_ls_lists_the_proposals_and_show_prints_one_whole():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, out, _err = await run(ctx, "archive", "ls")
    assert code == 0 and pid in out and "proposed" in out

    code, out, _err = await run(ctx, "archive", "show", pid, "--json")
    assert code == 0
    assert json.loads(out)["proposal_id"] == pid

    code, _out, err = await run(ctx, "archive", "show", "nope")
    assert code == 1
    assert "not found" in err


async def test_an_empty_list_exits_one():
    canonical, store = _library()
    code, _out, err = await run(_ctx(canonical, store), "archive", "ls")
    assert code == 1
    assert "no archive proposal" in err


async def test_drop_closes_a_proposal_and_a_second_drop_is_refused():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, out, _err = await run(ctx, "archive", "drop", pid)
    assert code == 0 and "dropped" in out
    assert store.rows[pid]["status"] == "dropped"

    code, _out, err = await run(ctx, "archive", "drop", pid)
    assert code == 2
    assert "cannot be dropped" in err


# ── confirm ────────────────────────────────────────────────────────────────────────────


def _selected(store, pid) -> set[str]:
    return {
        str(item["ref"]) for item in store.rows[pid]["items"] if item.get("selected")
    }


async def test_a_confirm_takes_the_seeds_and_leaves_the_cascade_where_it_is():
    """The Steward posture (§5.5): the planner computes what FOLLOWS, and what follows is not
    what the owner said. It is listed either way — hiding it would be worse than leaving it."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, out, _err = await run(ctx, "archive", "confirm", pid, "--statement", STATEMENT)
    assert code == 0
    assert "queued job-1" in out
    assert _selected(store, pid) == {"work/aurora.md"}
    assert store.enqueued == [("archive", {"proposal_id": pid})]
    # And the reason the confirm stood on, with the PROVENANCE the service stamped beside it
    # — the job refuses a reason arriving without that stamp, so a Steward reads the same
    # thing the commit will stand on rather than an unattributed sentence.
    assert f"«{SAID}»" in out
    assert "the owner's statement, first block" in out


async def test_a_confirm_on_the_owners_own_note_says_the_words_came_with_the_decision(
    tmp_path,
):
    """The other provenance, and the one the corrections added the stamp for: a note sent
    WITH the confirm. `show` and the confirm's own output say which of the two it was."""
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    code, out, _err = await run(
        ctx, "archive", "propose", "--document", "work/aurora.md", "--json"
    )
    assert code == 0
    pid = json.loads(out)["proposal_id"]

    code, out, _err = await run(
        ctx, "archive", "confirm", pid, "--note-file", note_file(tmp_path, SAID)
    )
    assert code == 0
    assert f"«{SAID}»" in out
    assert "the owner's words, sent with the confirm" in out

    code, out, _err = await run(ctx, "archive", "show", pid)
    assert code == 0
    assert "the owner's words, sent with the confirm" in out


async def test_cascade_confirms_what_follows_from_the_seed_too():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, _out, _err = await run(
        ctx, "archive", "confirm", pid, "--cascade", "--statement", STATEMENT
    )
    assert _selected(store, pid) == {"work/aurora.md", "src-a"}


async def test_deselect_unticks_one_item_the_plan_selected():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, _out, _err = await run(
        ctx,
        "archive",
        "confirm",
        pid,
        "--cascade",
        "--deselect",
        "src-a",
        "--statement",
        STATEMENT,
    )
    assert code == 0
    assert _selected(store, pid) == {"work/aurora.md"}


async def test_deselecting_something_the_plan_never_listed_is_refused():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, _out, err = await run(
        ctx, "archive", "confirm", pid, "--deselect", "src-z", "--statement", STATEMENT
    )
    assert code == 2
    assert "src-z" in err
    assert store.enqueued == []


async def test_a_confirm_naming_another_statement_is_refused():
    """The statement is what the record CITES, and it is fixed when the set is computed."""
    canonical, store = _library()
    store.stored["src-other"] = _owner_statement("Something else entirely.")
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, _out, err = await run(
        ctx, "archive", "confirm", pid, "--statement", "src-other"
    )
    assert code == 2
    assert "Re-plan" in err
    assert store.enqueued == []


async def test_a_confirm_against_a_library_that_moved_is_refused_and_says_to_re_plan():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)
    canonical.head = "sha-2"  # a compile landed between the plan and the decision

    code, _out, err = await run(ctx, "archive", "confirm", pid, "--statement", STATEMENT)
    assert code == 2
    assert "sha-1 → sha-2" in err and "Re-plan" in err
    assert store.enqueued == []
    # And the row is left where a stale row belongs: unconfirmable, droppable.
    assert store.rows[pid]["status"] == "stale"


async def test_the_json_of_a_confirm_carries_the_proposal_and_the_job():
    canonical, store = _library()
    ctx = _ctx(canonical, store)
    pid = await proposal_id(ctx)

    code, out, _err = await run(
        ctx, "archive", "confirm", pid, "--statement", STATEMENT, "--json"
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["job_id"] == "job-1"
    assert payload["proposal"]["status"] == "confirmed"


# ── inventory ──────────────────────────────────────────────────────────────────────────


async def test_inventory_names_what_is_archived_now_and_where_the_subject_still_answers():
    canonical = _Canonical(
        [
            _doc("archive/work/aurora.md", ("src-a",)),
            _doc("work/atlas.md", ("src-c",)),
        ]
    )
    canonical.written = {"archive/work/aurora.md": "2026-09-04"}
    canonical.docs.append(
        _record_page("work/aurora.md", "archive/work/aurora.md")
    )
    store = _Store(
        [
            _source(
                "src-a",
                "The Aurora kickoff",
                archived_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            )
        ]
    )
    ctx = _ctx(canonical, store)

    code, out, _err = await run(ctx, "archive", "inventory")
    assert code == 0
    assert "archive/work/aurora.md" in out
    assert "2026-09-04" in out
    assert "record: work/aurora.md" in out
    assert "src-a" in out

    code, out, _err = await run(ctx, "archive", "inventory", "--json")
    payload = json.loads(out)
    assert payload["documents"][0]["record_path"] == "work/aurora.md"
    assert payload["sources"][0]["source_id"] == "src-a"
    assert payload["sources"][0]["archived_at"].startswith("2026-09-04")


async def test_an_empty_archive_says_so_and_exits_one():
    canonical, store = _library()
    code, _out, err = await run(_ctx(canonical, store), "archive", "inventory")
    assert code == 1
    assert "nothing in this library is archived" in err


def _record_page(path: str, archive_of: str):
    """The live page a moved subject leaves behind — enough of one for the inventory to
    recognize it: the `archive_of` key naming its full copy (core `domain/archive.py`)."""
    doc = _doc(path)
    return type(doc)(
        doc_id=doc.doc_id,
        path=path,
        frontmatter={"type": "archived", "archive_of": archive_of, "archived_on": "2026-09-04"},
        body=doc.body,
    )
