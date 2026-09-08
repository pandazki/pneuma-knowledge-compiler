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
    assert json.loads(out)["text"] == "beta\n\ngamma"
    # The bare spelling addresses the same span — a shell that eats the pilcrow must not
    # change what a locator means.
    _code, plain, _err = await run(lib, "source", "fetch", "s-01", "1", "2")
    assert plain.strip() == "beta\n\ngamma"


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
        assert code == 0 and out == "\n".join(texts) + "\n", err
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
