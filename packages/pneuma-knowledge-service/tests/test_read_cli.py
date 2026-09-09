"""`pkc`'s read commands — the Steward's eyes (coding-agent-mode §5.1).

One test per command, over the keyless doubles the suite already runs on. What each asserts
is the same thing twice: that `--json` reports the state a workflow can branch on, and that
the state is the LIBRARY's rather than a second description of it — a page rendered as the
compile model reads it, a span returned verbatim, a hit addressed `source_id ¶a-b`.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_service.cli import build_parser, dispatch

from _cli_library import (  # noqa: E402
    USER,
    LexHit,
    VecHit,
    document,
    library,
    source,
)

PAGE = "memory/topics/pricing.md"
OTHER = "memory/people/cheng-ye.md"


async def run(lib, *argv):
    """One `pkc …` invocation, parsed exactly as the process parses it, with its output
    captured. Returns `(exit_code, stdout, stderr)`."""
    # `--user` in front of every invocation: the tenant is the first parameter of every
    # port (I1), and a test that let it default would be exercising a different library
    # than the one it seeded.
    args = build_parser().parse_args(["--user", str(USER), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(lib.ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _lib(**kw):
    return library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(OTHER, "## 程野\n\n- 程野 leads backend. [cite: s-01 ¶0] <!-- c:bbb2 -->\n"),
        ],
        **kw,
    )


#: A page the owner retired, and the source it rested on. `archive/` IS the document mark and
#: `archived_at` IS the source one (docs/design/archive.md §2), so a fixture needs nothing
#: else to be archived.
ARCHIVED = "archive/memory/topics/harbour.md"


def _archived_lib():
    return library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(ARCHIVED, "## Harbour\n\n- Harbour shipped. [cite: s-02 ¶0] <!-- c:ccc3 -->\n"),
        ],
        lexical_hits=[
            LexHit(source_id="s-01", block_index=1, text="seats"),
            LexHit(source_id="s-02", block_index=0, text="harbour seats"),
        ],
    )


# ───────────────────────────────────────────────────────────────────────── glance


async def test_glance_renders_the_same_overview_the_answering_lanes_open_with():
    lib = _lib()
    code, out, _err = await run(lib, "glance", "--json")
    assert code == 0
    payload = json.loads(out)
    assert PAGE in payload["glance"] and OTHER in payload["glance"]
    assert payload["chars"] == len(payload["glance"])


async def test_glance_on_an_empty_library_says_so_and_exits_one():
    code, _out, err = await run(library(), "glance")
    assert code == 1
    assert "no canonical pages" in err


# ────────────────────────────────────────────────────────────────────── canonical


async def test_canonical_ls_lists_every_page_by_path():
    code, out, _err = await run(_lib(), "canonical", "ls", "--json")
    assert code == 0
    assert [d["path"] for d in json.loads(out)["documents"]] == sorted([OTHER, PAGE])


async def test_canonical_read_renders_the_page_the_way_read_document_does():
    lib = _lib()
    code, out, _err = await run(lib, "canonical", "read", PAGE, "--json")
    assert code == 0
    doc = next(d for d in await lib.canonical.list(USER) if d.path == PAGE)
    assert json.loads(out)["document"] == render_document(doc.frontmatter, doc.body)


async def test_canonical_read_of_a_missing_page_exits_one():
    code, _out, err = await run(_lib(), "canonical", "read", "memory/topics/nope.md")
    assert code == 1
    assert "no such page" in err


async def test_canonical_history_shows_the_chain_a_superseding_claim_left():
    lib = library(
        docs=[
            document(
                PAGE,
                "## Pricing\n\n"
                "- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n\n"
                "- Seats cost 25. [cite: s-01 ¶2] <!-- supersedes: c:aaa1 --> <!-- c:aaa2 -->\n",
            )
        ]
    )
    code, out, _err = await run(lib, "canonical", "history", PAGE, "--json")
    assert code == 0
    chain = json.loads(out)["chains"][0]
    assert [link["anchor"] for link in chain] == ["c:aaa1", "c:aaa2"]

    code, out, _err = await run(lib, "canonical", "history", PAGE, "c:aaa2", "--json")
    assert code == 0 and len(json.loads(out)["chains"]) == 1


async def test_canonical_history_on_a_page_with_no_supersession_exits_one():
    code, _out, err = await run(_lib(), "canonical", "history", PAGE)
    assert code == 1
    assert "no supersession chain" in err


# ──────────────────────────────────────────────────────────────────────────── L0


async def _seeded():
    lib = _lib()
    await lib.store.add(USER, source("s-01", blocks=["alpha", "beta", "gamma"]))
    return lib


async def test_source_ls_lists_L0_with_its_block_span():
    lib = await _seeded()
    code, out, _err = await run(lib, "source", "ls", "--json")
    assert code == 0
    item = json.loads(out)["sources"][0]
    assert item["source_id"] == "s-01" and item["blocks"] == 3


async def test_source_show_reports_the_structure_map():
    lib = await _seeded()
    code, out, _err = await run(lib, "source", "show", "s-01", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["blocks"] == 3
    assert payload["structure"] == [{"path": ["body"], "blocks": [0, 2]}]


async def test_source_fetch_returns_the_verbatim_span():
    lib = await _seeded()
    code, out, _err = await run(lib, "source", "fetch", "s-01", "¶1-2", "--json")
    assert code == 0
    assert json.loads(out)[0]["text"] == "beta\n\ngamma"
    # The bare spelling addresses the same span — a shell that eats the pilcrow must not
    # change what a locator means.
    _code, plain, _err = await run(lib, "source", "fetch", "s-01", "1", "2")
    assert plain.strip() == "s-01 ¶1-2 · 2026-08-01\nbeta\n\ngamma"


async def test_source_fetch_refuses_an_argument_that_is_not_a_span():
    lib = await _seeded()
    code, _out, err = await run(lib, "source", "fetch", "s-01", "the-middle-bit")
    assert code == 2
    assert "not a block span" in err


# ──────────────────────────────────────────────────────────────────────── search


async def test_search_reports_each_hit_as_a_source_id_and_span():
    lib = library(
        lexical_hits=[LexHit(source_id="s-01", block_index=2, text="gamma")],
        vector_hits=[VecHit(source_id="s-02", block_start=0, block_end=1, text="delta")],
    )
    code, out, _err = await run(lib, "search", "seats", "--lexical", "--json")
    assert code == 0
    # `archived` is on every hit, in both scopes and like every other face on the wire: a
    # reader must never have to tell the label's absence from a `false`.
    assert json.loads(out)["hits"] == [
        {
            "source_id": "s-01",
            "blocks": [2, 2],
            "score": 1.0,
            "text": "gamma",
            "archived": False,
        }
    ]

    code, out, _err = await run(lib, "search", "seats", "--semantic", "--json")
    assert code == 0
    assert json.loads(out)["hits"][0]["blocks"] == [0, 1]

    # Fused is the `rag` lane's own RRF over both faces.
    code, out, _err = await run(lib, "search", "seats", "--fused", "--json")
    assert code == 0
    assert {h["source_id"] for h in json.loads(out)["hits"]} == {"s-01", "s-02"}


async def test_search_that_finds_nothing_exits_one():
    code, _out, err = await run(library(), "search", "seats", "--lexical")
    assert code == 1
    assert "nothing found" in err


# ────────────────────────────────────────────────────── queue, history, brief


async def test_jobs_reports_the_queue():
    lib = _lib()
    job_id = await lib.store.enqueue(USER, "compile", {"source_ids": ["s-01"]})
    code, out, _err = await run(lib, "jobs", "--json")
    assert code == 0
    row = json.loads(out)["jobs"][0]
    assert row["job_id"] == job_id and row["status"] == "queued"


async def test_history_reports_the_ledger_newest_first():
    lib = _lib()
    lib.store.history = [
        {
            "user_id": str(USER),
            "kind": "patch",
            "ref": "abc123",
            "ts": datetime(2026, 8, 2, tzinfo=timezone.utc),
            "payload": {"job_id": "job-01", "brief": "wrote two claims", "claims": []},
        }
    ]
    code, out, _err = await run(lib, "history", "--json")
    assert code == 0
    assert json.loads(out)["history"][0]["ref"] == "abc123"


async def test_brief_finds_a_version_by_prefix_and_prints_its_narration():
    lib = _lib()
    lib.store.history = [
        {
            "user_id": str(USER),
            "kind": "patch",
            "ref": "abc123def",
            "ts": datetime(2026, 8, 2, tzinfo=timezone.utc),
            "payload": {"job_id": "job-01", "brief": "wrote two claims", "claims": []},
        }
    ]
    code, out, _err = await run(lib, "brief", "abc", "--json")
    assert code == 0
    assert json.loads(out)["brief"] == "wrote two claims"

    code, _out, err = await run(lib, "brief", "zzz")
    assert code == 1 and "no compile version" in err


# ───────────────────────────────────────────────────────────── use-side records


def _record(**over):
    from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef

    return ConsultationRecord(
        consultation_id=over.pop("consultation_id", "k1"),
        user_id=str(USER),
        created_at=over.pop("created_at", datetime.now(timezone.utc)),
        lane="fast",
        visitor_class=over.pop("visitor_class", "business"),
        question=over.pop("question", "what do seats cost?"),
        as_of=None,
        library_ref="c0",
        evidence_handed=(EvidenceRef(kind="claim", ref="c:aaa1", path=PAGE),),
        answer_kind="answer",
        answer="20.",
        token_usage=(("input_tokens", 100),),
        **over,
    )


async def test_consultations_lists_the_kept_records():
    lib = _lib()
    await lib.store.create_consultation(USER, _record())
    code, out, _err = await run(lib, "consultations", "--json")
    assert code == 0
    row = json.loads(out)["consultations"][0]
    assert row["question"] == "what do seats cost?" and row["evidence_handed"] == 1


async def test_spend_sums_the_tokens_of_the_window():
    lib = _lib()
    await lib.store.create_consultation(USER, _record())
    code, out, _err = await run(lib, "spend", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["consultations"] == 1
    assert payload["token_usage"] == {"input_tokens": 100}


async def test_spend_on_a_library_nobody_consulted_exits_one():
    code, _out, err = await run(_lib(), "spend")
    assert code == 1
    assert "nothing was consulted" in err


# ──────────────────────────────────────────────────────────────────────── evolve


async def test_evolve_ls_and_show_read_the_proposals(monkeypatch):
    import pneuma_knowledge_service.evolve_service as evolve_service

    task = {"task_id": "e1", "status": "proposed", "summary": "add a family"}

    async def _list(ctx, user):  # noqa: ANN001
        return [task]

    async def _get(ctx, user, task_id):  # noqa: ANN001
        return task if task_id == "e1" else None

    monkeypatch.setattr(evolve_service, "list_tasks_with_expiry", _list)
    monkeypatch.setattr(evolve_service, "get_task_with_expiry", _get)

    lib = _lib()
    code, out, _err = await run(lib, "evolve", "ls", "--json")
    assert code == 0 and json.loads(out)["proposals"][0]["task_id"] == "e1"

    code, out, _err = await run(lib, "evolve", "show", "e1", "--json")
    assert code == 0 and json.loads(out)["summary"] == "add a family"

    code, _out, err = await run(lib, "evolve", "show", "nope")
    assert code == 1 and "no such proposal" in err


async def test_recall_without_an_answer_model_points_at_the_evidence_face():
    code, _out, err = await run(_lib(), "recall", "what do seats cost?")
    assert code == 2
    assert "--evidence" in err


async def test_the_queue_reports_what_a_round_cost_when_something_counted_it():
    """B3's whole point: the unattended launcher reads the harness's own counters onto the job
    row, and a row that stores them while the CLI hides them is the same as not storing them.
    Absent stays absent — never a zero, which would read as "this compile was free"."""
    lib = _lib()
    agent = await lib.store.enqueue(USER, "compile", {"source_ids": ["s-01"]})
    indexed = await lib.store.enqueue(USER, "index", {"source_id": "s-01"})
    await lib.store.complete(
        USER,
        agent,
        ok=True,
        detail='projection:{"upserted": 4}',
        snapshot_ref="c0ffee",
        executor="agent:codex",
    )
    await lib.store.record_job_usage(
        USER,
        agent,
        token_usage={"input_tokens": 900, "output_tokens": 250, "total_tokens": 1150},
        executor="agent:codex",
    )
    await lib.store.complete(USER, indexed, ok=True, detail="indexed")

    code, out, _err = await run(lib, "jobs", "--json")
    assert code == 0
    rows = {r["job_id"]: r for r in json.loads(out)["jobs"]}
    assert rows[agent]["executor"] == "agent:codex"
    assert rows[agent]["token_usage"]["total_tokens"] == 1150
    # An index job counted nothing, and nothing is what it reports.
    assert rows[indexed]["token_usage"] is None

    code, prose, _err = await run(lib, "jobs")
    assert code == 0
    assert "1150 tok" in prose
    # Absent is absent, not " 0 tok": the index job's line says nothing about tokens.
    index_line = next(line for line in prose.splitlines() if line.startswith(indexed))
    assert "tok" not in index_line


# ─────────────────────────────────────────────────── the archive, and the one flag


async def test_the_glance_omits_the_archive_and_the_flag_puts_it_back_labelled():
    lib = _archived_lib()
    code, out, _err = await run(lib, "glance")
    assert code == 0
    assert PAGE in out and ARCHIVED not in out

    code, out, _err = await run(lib, "glance", "--include-archived")
    assert code == 0
    assert ARCHIVED in out
    # The renderer's own label, not a second one invented here: an item admitted from the
    # archive says so, filed under the family of its live path.
    assert "archived" in out


async def test_canonical_ls_omits_the_archive_and_labels_what_the_flag_admits():
    lib = _archived_lib()
    code, out, _err = await run(lib, "canonical", "ls", "--json")
    assert [d["path"] for d in json.loads(out)["documents"]] == [PAGE]
    assert json.loads(out)["documents"][0]["archived"] is False

    code, out, _err = await run(lib, "canonical", "ls", "--include-archived", "--json")
    payload = json.loads(out)
    assert payload["include_archived"] is True
    marks = {d["path"]: d["archived"] for d in payload["documents"]}
    assert marks == {PAGE: False, ARCHIVED: True}

    code, out, _err = await run(lib, "canonical", "ls", "--include-archived")
    assert f"{ARCHIVED}  [archived]" in out


async def test_a_page_addressed_by_path_answers_whether_or_not_it_is_archived():
    """No flag, and the absence is the promise (I3, I4): the archive changes what a SEARCH
    returns by default, never whether an address resolves."""
    lib = _archived_lib()
    code, out, _err = await run(lib, "canonical", "read", ARCHIVED)
    assert code == 0
    assert "Harbour shipped" in out


async def test_source_ls_omits_archived_sources_and_labels_them_when_asked():
    lib = _archived_lib()
    await lib.store.add(USER, source("s-01", title="pricing call"))
    await lib.store.add(
        USER,
        source(
            "s-02",
            title="harbour standup",
            archived_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
    )

    code, out, _err = await run(lib, "source", "ls", "--json")
    assert [s["source_id"] for s in json.loads(out)["sources"]] == ["s-01"]

    code, out, _err = await run(lib, "source", "ls", "--include-archived", "--json")
    rows = {s["source_id"]: s for s in json.loads(out)["sources"]}
    assert rows["s-02"]["archived"] is True
    assert rows["s-02"]["archived_at"].startswith("2026-09-04")
    assert rows["s-01"]["archived"] is False

    code, out, _err = await run(lib, "source", "ls", "--include-archived")
    assert "[archived]" in out
    # And L0 by id is unconditional, with no flag to type.
    code, _out, _err = await run(lib, "source", "fetch", "s-02", "¶0")
    assert code == 0


async def test_search_excludes_the_archive_and_labels_the_hits_the_flag_admits():
    lib = _archived_lib()
    await lib.store.add(
        USER,
        source(
            "s-02",
            title="harbour standup",
            archived_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
    )
    # WHAT THE FLAG HAS TO REACH IS THE INDEX. The real exclusion is a predicate inside
    # Meilisearch and Qdrant (docs/design/archive.md §3) — a post-filter here would let
    # archived blocks spend the candidate caps first — so what this pins is the scope the
    # PORT was asked for, and the double answers whatever it holds either way.
    lib.lexical.search = _recording_search(lib.lexical)

    code, out, _err = await run(lib, "search", "harbour", "--lexical", "--json")
    assert code == 0
    assert lib.lexical.asked == [False]
    # Nothing is labelled in the default scope, because nothing archived is admitted into it:
    # the label exists for what the exception let through.
    assert all(h["archived"] is False for h in json.loads(out)["hits"])

    code, out, _err = await run(
        lib, "search", "harbour", "--lexical", "--include-archived", "--json"
    )
    assert lib.lexical.asked == [False, True]
    payload = json.loads(out)
    assert payload["include_archived"] is True
    marks = {h["source_id"]: h["archived"] for h in payload["hits"]}
    assert marks == {"s-01": False, "s-02": True}

    code, out, _err = await run(
        lib, "search", "harbour", "--lexical", "--include-archived"
    )
    assert "[archived]" in out


def _recording_search(lexical):
    """`search`, remembering the scope it was asked for, and answering as it did before."""
    lexical.asked = []
    original = lexical.search

    async def search(user_id, query, *, limit=20, include_archived=False):  # noqa: ANN001
        lexical.asked.append(include_archived)
        return await original(user_id, query, limit=limit, include_archived=include_archived)

    return search


async def test_source_fetch_multiple_spans_preserve_shell_argument_boundaries():
    lib = _lib()
    await lib.store.add(USER, source("spans", blocks=[f"Block {i}" for i in range(7)]))
    for tokens, expected in (
        (("¶1", "¶5"), [[1, 1], [5, 5]]),
        (("¶2-3",), [[2, 3]]),
        (("4", "6"), [[4, 6]]),
        (("¶1", "¶2-3", "4-6"), [[1, 1], [2, 3], [4, 6]]),
        (("1", "3", "5"), [[1, 1], [3, 3], [5, 5]]),
    ):
        code, out, err = await run(lib, "source", "fetch", "spans", *tokens, "--json")
        assert code == 0, err
        payload = json.loads(out)
        items = payload if isinstance(payload, list) else [payload]
        assert [item["blocks"] for item in items] == expected
        texts = ["\n\n".join(f"Block {i}" for i in range(a, b + 1)) for a, b in expected]
        assert [item["text"] for item in items] == texts
        code, out, err = await run(lib, "source", "fetch", "spans", *tokens)
        assert code == 0, err
        assert out == "\n".join(
            f"spans {item['span']} · 2026-08-01\n{text}"
            for item, text in zip(items, texts)
        ) + "\n"
    code, out, err = await run(lib, "source", "fetch", "spans", "¶1", "not-a-span")
    assert code == 2 and not out and "'not-a-span'" in err


async def test_only_two_bare_integer_arguments_form_one_span():
    lib = await _seeded()
    for token in ("¶1 2", "1 2"):
        code, out, err = await run(lib, "source", "fetch", "s-01", token)
        assert code == 2 and not out and "not a block span" in err
    parser = build_parser()
    import argparse

    def children(p):
        return next(a.choices for a in p._actions if isinstance(a, argparse._SubParsersAction))

    help_text = children(children(parser)["source"])["fetch"].format_help()
    assert "exactly two bare integers" in " ".join(help_text.split())


def test_prose_paging_cuts_at_line_boundaries_and_never_drops_text():
    from pneuma_knowledge_service.cli.read import paginate

    text = "\n".join(f"line {i:03d} " + "x" * 20 for i in range(100))
    pages = paginate(text, 500)
    assert len(pages) > 1
    assert "\n".join(pages) == text
    assert all(len(page) <= 500 for page in pages)
    assert all(not page.startswith("x") for page in pages)  # a cut lands between lines
    assert paginate(text, 0) == [text] and paginate("short", 500) == ["short"]
    long_line = "y" * 1200
    assert paginate(long_line, 500) == ["y" * 500, "y" * 500, "y" * 200]


def test_json_paging_cuts_the_one_list_by_items_and_names_the_next_page():
    from pneuma_knowledge_service.cli.read import page_items

    hits = [{"i": i, "text": "z" * 300} for i in range(30)]
    payload = {"query": "q", "hits": hits}
    first = page_items(payload, 1, 2000)
    assert first["query"] == "q" and first["paging"]["page"] == 1
    assert first["paging"]["items"] == 30 and first["paging"]["next"] == "--page 2"
    assert 0 < len(first["hits"]) < 30
    pages = first["paging"]["pages"]
    last = page_items(payload, 99, 2000)
    assert last["paging"]["page"] == pages and last["paging"]["next"] is None
    gathered = [h["i"] for p in range(1, pages + 1) for h in page_items(payload, p, 2000)["hits"]]
    assert gathered == list(range(30))
    assert page_items({"a": [1], "b": [2]}, 1, 10) == {"a": [1], "b": [2]}  # two lists: whole
    assert page_items({"hits": hits[:2]}, 1, 100000) == {"hits": hits[:2]}  # fits: untouched


async def test_canonical_read_takes_several_pages_in_one_process():
    lib = _lib()
    code, out, err = await run(lib, "canonical", "read", PAGE, "memory/topics/nope.md", OTHER, "--json")
    assert code == 0
    assert [p["path"] for p in json.loads(out)["pages"]] == [PAGE, OTHER]
    assert "no such page: memory/topics/nope.md" in err
    code, out, _err = await run(lib, "canonical", "read", PAGE, OTHER)
    assert code == 0 and out.count("---") >= 2


# Reader signals use only declared, synthetic identities and recorded library state.
SESSION = "a" * 32
STATEMENT = "b" * 32


def _authored_source(sid=SESSION, *, owner_name="Avery"):
    item = source(sid, kind="agent_session", title="Synthetic planning session",
                  blocks=["Choose the blue plan.", "The blue plan has three stages.", "Stage two is review."])
    item.raw.meta = {
        "owner_name": owner_name, "agent": {"name": "TestCoder"}, "occurred_on": "2026-07-02",
        "turns": [{"role": "owner"}, {"role": "agent"}, {"role": "agent"}],
    }
    return item


async def test_canonical_reader_status_and_per_span_source_index(monkeypatch):
    body = (
        f"- Initial plan. [cite: {SESSION} ¶0] <!-- c:aaaa -->\n\n"
        f"- Three stages. [cite: {SESSION} ¶1-2] <!-- c:bbbb --> "
        "<!-- supersedes: c:aaaa -->\n\n"
        f"- Written review. [cite: {STATEMENT} ¶0] [cite: {SESSION} ¶0,1-2] <!-- c:cccc -->\n"
    )
    lib = library(docs=[document(PAGE, body), document(OTHER, body)])
    await lib.store.add(USER, _authored_source())
    written = source(STATEMENT, kind="document", title="Synthetic review document")
    written.raw.created_at = datetime.fromisoformat("2026-09-07T01:00:00+08:00")
    await lib.store.add(USER, written)
    calls = []

    async def last_commit(user, path, *, at=None):
        calls.append((user, path, at.ref))
        return "95c8cdb" + "0" * 33, "2026-09-07"

    monkeypatch.setattr(lib.canonical, "last_commit", last_commit)
    # More than one default job page; completed jobs, index jobs and another tenant do
    # not contribute. A claimed compile still owes its work just as a queued one does.
    active = await lib.store.enqueue(USER, "compile", {})
    await lib.store.claim(USER, active)
    for _ in range(30):
        await lib.store.enqueue(USER, "compile", {})
    done = await lib.store.enqueue(USER, "compile", {})
    await lib.store.complete(USER, done, ok=True)
    await lib.store.enqueue(USER, "index", {})
    await lib.store.enqueue("other-tenant", "compile", {})
    code, out, err = await run(lib, "canonical", "read", PAGE, OTHER, "--json")
    assert code == 0, err
    pages = json.loads(out)["pages"]
    assert calls == [(USER, PAGE, "c0"), (USER, OTHER, "c0")]
    for page in pages:
        assert page["status"] == {
            "compiled_at": "2026-09-07", "commit": "95c8cdb" + "0" * 33,
            "claims": 3, "superseded": 1, "sources_cited": 2,
            "latest_source": "2026-09-06", "queue_pending": 31,
        }
        assert page["sources"] == [
            {"source_id": SESSION, "kind": "agent-session", "agent": "TestCoder",
             "date": "2026-07-02", "title": "Synthetic planning session",
             "cited": [{"span": "¶0", "speaker": "Avery"},
                       {"span": "¶1-2", "speaker": "TestCoder"}]},
            {"source_id": STATEMENT, "kind": "document", "date": "2026-09-06",
             "title": "Synthetic review document", "cited": [{"span": "¶0"}]},
        ]
    code, prose, err = await run(lib, "canonical", "read", PAGE, OTHER, "--all-pages")
    assert code == 0, err
    for page in pages:
        assert f"page: {page['path']}\ncompiled: 2026-09-07 (commit 95c8cdb)" in prose
        assert page["document"] in prose
    assert prose.count("queue: 31 compile jobs pending for this library") == 2
    assert "cited: ¶0 Avery · ¶1-2 TestCoder" in prose
    assert f"{SESSION} · agent-session (TestCoder) · 2026-07-02" in prose
    assert "sources cited: 2 · latest source: 2026-09-06" in prose


async def test_canonical_missing_metadata_is_unknown_and_empty_queue_is_explicit():
    lib = _lib()
    code, out, err = await run(lib, "canonical", "read", PAGE, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["status"]["compiled_at"] is None
    assert payload["status"]["latest_source"] is None
    assert payload["status"]["sources_cited"] == 1
    assert payload["status"]["queue_pending"] == 0
    assert payload["sources"][0]["date"] is None
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert "compiled: unknown (commit unknown)" in out
    assert "queue: no compile pending" in out
    assert "s-01 · unknown · unknown · unknown" in out


async def test_source_fetch_multiple_sources_labels_every_span_and_preserves_text():
    lib = _lib()
    await lib.store.add(USER, _authored_source())
    statement = source(STATEMENT, kind="owner_dialogue", title="Synthetic decision",
                       blocks=["Continue with the blue plan.", "Decision recorded."])
    statement.raw.meta = {"occurred_on": "2026-09-08", "owner_name": "Avery",
                          "turns": [{"role": "owner"}, {"role": "steward"}]}
    await lib.store.add(USER, statement)
    args = ("source", "fetch", SESSION, "¶0", "¶1-2", STATEMENT, "¶0")
    code, out, err = await run(lib, *args, "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert rows == [
        {"source_id": SESSION, "blocks": [0, 0], "span": "¶0", "speaker": "Avery",
         "date": "2026-07-02", "text": "Choose the blue plan."},
        {"source_id": SESSION, "blocks": [1, 2], "span": "¶1-2", "speaker": "TestCoder",
         "date": "2026-07-02", "text": "The blue plan has three stages.\n\nStage two is review."},
        {"source_id": STATEMENT, "blocks": [0, 0], "span": "¶0", "speaker": "Avery",
         "date": "2026-09-08", "text": "Continue with the blue plan."},
    ]
    code, out, err = await run(lib, *args)
    assert code == 0, err
    assert out == "\n".join(
        f"{row['source_id']} {row['span']} · {row['speaker']} · {row['date']}\n{row['text']}"
        for row in rows
    ) + "\n"
    code, out, err = await run(lib, *args, "missing-source")
    assert code == 2 and out == "" and "missing-source" in err
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0", "missing", "¶0")
    assert code == 1 and out == ""  # no partial result when another source cannot resolve


@pytest.mark.parametrize("kind,meta,expected", [
    ("agent_session", {"agent": {"name": "TestCoder"}, "turns": [{"role": "owner"}, {"role": "agent"}]},
     ["User", "TestCoder"]),
    ("owner_dialogue", {"turns": [{"role": "owner"}, {"role": "steward"}]}, ["User", "Steward"]),
    ("meeting", {"owner_participant_ids": ["m1"],
                 "participants": [{"participant_id": "m1", "display_name": "Avery"},
                                  {"participant_id": "m2", "display_name": "Blair"}],
                 "segments": [{"speaker_id": "m1"}, {"speaker_id": "m2"}]}, ["Avery", "Blair"]),
    ("im", {"owner_user_ids": ["m1"],
            "users": [{"user_id": "m1", "display_name": "Avery"},
                      {"user_id": "m2", "display_name": "Blair"}],
            "messages": [{"sender_id": "m1"}, {"sender_id": "m2"}]}, ["Avery", "Blair"]),
    ("email", {"owner_addresses": ["avery@example.invalid"],
               "messages": [{"from": {"address": "avery@example.invalid"}}]}, [None, None]),
])
async def test_source_speaker_labels_follow_authorship_not_text(kind, meta, expected):
    lib = _lib()
    item = source(SESSION, kind=kind, blocks=["Blair says Avery spoke.", "Avery says Blair spoke."])
    item.raw.meta = meta
    await lib.store.add(USER, item)
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0", "¶1", "--json")
    assert code == 0, err
    assert [row.get("speaker") for row in json.loads(out)] == expected
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0-1", "--json")
    assert code == 0, err
    speakers = ", ".join(dict.fromkeys(name for name in expected if name))
    assert json.loads(out)[0].get("speaker") == (speakers or None)


async def test_search_counts_terms_and_phrases_without_using_limited_hit_length(monkeypatch):
    lib = library(lexical_hits=[LexHit(source_id=SESSION, block_index=0, text="blue plan")])
    await lib.store.add(USER, _authored_source())
    query = 'blue "three stages"'
    counted = []

    async def search_with_total(user, q, *, limit, include_archived):
        assert user == USER and q == query and limit == 1
        return lib.lexical.hits, 37

    async def count(user, q, *, all_terms=False, include_archived=False):
        counted.append((user, q, all_terms, include_archived))
        return {query: 0, "blue": 37, '"three stages"': 120}[q]

    monkeypatch.setattr(lib.lexical, "search_with_total", search_with_total)
    monkeypatch.setattr(lib.lexical, "count", count)
    args = ("search", query, "--lexical", "--limit", "1", "--include-archived")
    code, out, err = await run(lib, *args, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["counts"] == {"all_terms": 0, "per_term": {"blue": 37, "three stages": 120}}
    assert payload["showing"] == 1 and payload["total"] == 37
    assert payload["hits"][0]["speaker"] == "Avery"
    assert counted == [(USER, q, True, True) for q in (query, "blue", '"three stages"')]
    code, out, err = await run(lib, *args)
    assert code == 0, err
    assert out.startswith(f"query: {query}\nblocks matching every term: 0")
    assert '"blue": 37 · "three stages": 120' in out
    assert "showing: 1 of 37" in out
    assert f"{SESSION} ¶0 Avery" in out
    counted.clear()
    code, out, err = await run(lib, "search", query, "--semantic", "--json")
    assert code == 1 and counted == []
    assert "counts" not in json.loads(out)


async def test_search_zero_counts_are_visible_and_fused_total_does_not_count_vectors():
    code, out, err = await run(library(), "search", "absent", "--lexical", "--json")
    assert code == 1 and "nothing found" in err
    assert json.loads(out)["counts"] == {"all_terms": 0, "per_term": {"absent": 0}}
    code, out, _err = await run(library(), "search", "absent", "--lexical")
    assert code == 1 and "blocks matching every term: 0" in out and "showing: 0 of 0" in out
    lib = library(lexical_hits=[LexHit(source_id=SESSION, block_index=0, text="blue")],
                  vector_hits=[VecHit(source_id=STATEMENT, block_start=0, block_end=0, text="plan")])
    code, out, err = await run(lib, "search", "blue", "--fused", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["showing"] == 2 and payload["total"] is None and payload["lexical_total"] == 1
    assert payload["counts"] == {"all_terms": 1, "per_term": {"blue": 1}}


async def test_search_preserves_single_word_quotes_apostrophes_and_deduplicates_terms(monkeypatch):
    lib = library()
    query = 'can\'t "plan" "plan"'
    asked = []

    async def count(user, q, **kwargs):
        asked.append(q)
        return 0

    monkeypatch.setattr(lib.lexical, "count", count)
    code, out, err = await run(lib, "search", query, "--lexical", "--json")
    assert code == 1
    assert asked == [query, "can't", '"plan"']
    assert json.loads(out)["counts"]["per_term"] == {"can't": 0, "plan": 0}
    asked.clear()
    code, out, err = await run(lib, "search", '"unfinished phrase', "--lexical")
    assert code == 2 and not out and not asked and "quotation" in err


async def test_source_authorship_is_bounded_and_never_borrows_an_unknown_role():
    from pneuma_knowledge_service.cli.reader_signals import SourceSignals

    lib = _lib()
    item = _authored_source()
    item.raw.meta["turns"][1] = {"role": "unknown"}
    await lib.store.add(USER, item)
    signals = SourceSignals(lib.store, USER)
    assert await signals.span(SESSION, 1, 1) == {"span": "¶1"}
    assert await signals.span(SESSION, 0, 10**12) == {
        "span": "¶0-1000000000000", "speaker": "Avery, TestCoder, unknown",
    }


async def test_reader_help_and_labels_follow_the_catalog_in_both_languages():
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service.coding_agent.skillpack import render_cli_md

    english = render_cli_md(build_parser())
    assert "map last for a reader who already holds it" in english
    assert "source index with cited-span speakers" in english
    assert "estimated per-term and all-terms block counts" in english
    assert "JSON is a list" in english
    try:
        override_prompts(chinese_overlay())
        lib = _lib()
        await lib.store.add(USER, _authored_source(owner_name=None))
        code, out, err = await run(lib, "source", "fetch", SESSION, "¶0")
        assert code == 0, err
        assert f"{SESSION} ¶0 · 用户 · 2026-07-02" in out
        code, out, err = await run(lib, "canonical", "read", PAGE)
        assert code == 0, err
        assert out.startswith(f"页面：{PAGE}\n编译：未知")
        assert "队列：无待处理编译" in out and "来源：" in out
        assert "地图放最后" in render_cli_md(build_parser())
    finally:
        reset_prompt_overrides()


async def test_recall_reader_tally_order_and_handle_source_index_keep_model_bytes(monkeypatch):
    from pneuma_knowledge_core.recall.fast import fast_recall, message_text
    from pneuma_knowledge_service import cli
    from pneuma_knowledge_service.cli.read import ReadRuntime, _fast_kwargs

    lib = _lib()
    await lib.store.add(USER, _authored_source())
    await lib.store.add(USER, _authored_source(STATEMENT))
    claims = [SimpleNamespace(anchor=anchor, document_path=path, text=text,
                              citations=[], section_path=[])
              for anchor, path, text in [
                  ("aaaa", PAGE, f"The blue plan has three stages. [cite: {SESSION} ¶1]"),
                  ("bbbb", OTHER, f"Avery requested a review. [cite: {STATEMENT} ¶0]"),
                  ("cccc", PAGE, f"Stage two is review. [cite: {SESSION} ¶2]"),
              ]]

    async def search_claims(*args, **kwargs):
        return claims

    async def vector_search(*args, representation="raw", **kwargs):
        if representation == "episode":
            return [VecHit(source_id=STATEMENT, block_start=0, block_end=2, text="",
                           representation="episode", episode_summary_text="A synthetic plan and its review.")]
        return [VecHit(source_id=SESSION, block_start=0, block_end=0, text="Choose the blue plan.")]

    monkeypatch.setattr(lib.lexical, "search_claims", search_claims)
    monkeypatch.setattr(lib.vectors, "search", vector_search)
    monkeypatch.setattr(cli, "_handoffs", lambda ctx: lib.handoffs)
    when = datetime(2026, 9, 9, 1, 23, tzinfo=timezone.utc)
    query = "What is the blue plan?"
    args = ("recall", query, "--evidence", "--as-of", when.isoformat(), "--all-pages")
    rt = ReadRuntime(user_id=USER, ctx=lib.ctx)
    evidence = await fast_recall(USER, query, evidence_only=True,
                                 **await _fast_kwargs(rt, as_of=when, style=None, evidence_only=True))
    code, out, err = await run(lib, *args, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["content"] == message_text(evidence.content)
    assert payload["tally"] == {
        "claims": 3, "pages": [{"path": PAGE, "claims": 2}, {"path": OTHER, "claims": 1}],
        "windows": len(evidence.used_windows), "window_sources": 2, "episodes": 1,
    }
    assert payload["sources"] == [
        {"handle": handle, "source_id": sid, "kind": "agent-session", "agent": "TestCoder",
         "date": "2026-07-02", "title": "Synthetic planning session"}
        for handle, sid in evidence.handles.items()
    ]
    code, out, err = await run(lib, *args)
    assert code == 0, err
    assert out.startswith(f"evidence for: {query}\nas_of: 2026-09-09 01:23 UTC\n")
    assert f"pages: {PAGE} (2) · {OTHER} (1)" in out
    assert "3 claims from 2 pages" in out and "1 episode summaries (derived)" in out
    positions = [out.index(header) for header in (
        "# 1 claim notes", "# 2 raw excerpts", "# 3 derived episode summaries", "# 4 map", "sources:", "handoff:",
    )]
    assert positions == sorted(positions)
    for kind, section in evidence.sections:
        section_body = section.partition("\n")[2] if kind in {"claims", "windows", "episodes"} else section
        assert section_body in out
    for handle, sid in evidence.handles.items():
        assert f"{handle} = {sid} · agent-session (TestCoder) · 2026-07-02" in out
