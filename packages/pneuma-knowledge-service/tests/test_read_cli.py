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
from pneuma_knowledge_core.domain.time_context import time_context_for
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
UTC_BASIS = "days: UTC (no Owner timezone recorded)"


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
    assert plain.strip() == UTC_BASIS + "\ns-01 ¶1 unknown · ¶2 unknown · imported 2026-08-01\nbeta\n\ngamma"


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
            "speaker": "unknown", "speakers": [{"span": "¶2", "speaker": "unknown"}],
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
        assert out == UTC_BASIS + "\n" + "\n".join(
            "spans " + " · ".join(f"¶{i} unknown" for i in range(*[item["blocks"][0], item["blocks"][1] + 1]))
            + f" · imported 2026-08-01\n{text}"
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
    assert page_items({"a": [1], "b": [2]}, 1, 10)["paging"]["list"] == "a"
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


async def _owner_calendar(lib, zone):
    from pneuma_knowledge_core.domain.user import UserProfile

    profile = UserProfile.unstated(USER)
    profile.display_name, profile.source = "Avery", "owner"
    profile.locale.timezone = zone
    await lib.store.upsert_user_profile(USER, profile.model_dump(mode="json"))
    return profile


def _stamp_envelope_ids(item):
    singular = "segment" if item.raw.kind == "meeting" else (
        "message" if item.raw.kind in {"email", "im"} else "turn"
    )
    rows = item.raw.meta[singular + "s"]
    ids = [f"{singular}-{i}" for i in range(len(rows))]
    item.raw.meta[singular + "_ids"] = ids
    for row, identity in zip(rows, ids):
        row[singular + "_id"] = identity


def _authored_source(sid=SESSION, *, owner_name="Avery"):
    item = source(sid, kind="agent_session", title="Synthetic planning session",
                  blocks=["Choose the blue plan.", "The blue plan has three stages.", "Stage two is review."])
    item.raw.meta = {
        "owner_name": owner_name, "agent": {"name": "TestCoder"}, "occurred_on": "2026-07-02",
        "turn_ids": ["t0", "t1", "t2"],
        "turns": [{"turn_id": "t0", "role": "owner"},
                  {"turn_id": "t1", "role": "agent"}, {"turn_id": "t2", "role": "agent"}],
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
        return "95c8cdb" + "0" * 33, "2026-09-07T12:00:00+00:00"

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
            "last_changed": "2026-09-07", "last_changed_at": "2026-09-07T12:00:00+00:00", "commit": "95c8cdb" + "0" * 33,
            "claims": 3, "overview_blocks": 0, "superseded": 1, "sources_cited": 2,
            "latest_cited_source": "imported 2026-09-06",
            "latest_cited_source_at": "2026-09-07T01:00:00+08:00", "queue_pending": 31, "queue_failed": 0,
        }
        assert page["sources"] == [
            {"source_id": SESSION, "kind": "agent-session", "agent": "TestCoder",
             "date": "2026-07-02", "title": "Synthetic planning session",
             "cited": [{"span": "¶0", "speaker": "Avery",
                        "speakers": [{"span": "¶0", "speaker": "Avery"}]},
                       {"span": "¶1-2", "speaker": "TestCoder",
                        "speakers": [{"span": "¶1", "speaker": "TestCoder"},
                                     {"span": "¶2", "speaker": "TestCoder"}]}]},
            {"source_id": STATEMENT, "kind": "document", "date": "imported 2026-09-06",
             "at": "2026-09-07T01:00:00+08:00",
             "title": "Synthetic review document", "cited": [{"span": "¶0", "speaker": "unknown",
                 "speakers": [{"span": "¶0", "speaker": "unknown"}]}]},
        ]
    code, prose, err = await run(lib, "canonical", "read", PAGE, OTHER, "--all-pages")
    assert code == 0, err
    for page in pages:
        assert f"page: {page['path']}\nlast changed: 2026-09-07 (commit 95c8cdb)" in prose
        assert page["document"] in prose
    assert prose.count("compile jobs: 31 pending · 0 failed") == 2
    assert "cited: ¶0 Avery · ¶1 TestCoder · ¶2 TestCoder" in prose
    assert f"{SESSION} · agent-session (TestCoder) · 2026-07-02" in prose
    assert "sources cited: 2 · latest cited source: imported 2026-09-06" in prose


async def test_canonical_missing_metadata_is_unknown_and_empty_queue_is_explicit():
    lib = _lib()
    code, out, err = await run(lib, "canonical", "read", PAGE, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["status"]["last_changed"] is None
    assert payload["status"]["latest_cited_source"] is None
    assert payload["status"]["sources_cited"] == 1
    assert payload["status"]["queue_pending"] == 0
    assert payload["sources"][0]["date"] is None
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert "last changed: unknown (commit unknown)" in out
    assert "compile jobs: 0 pending · 0 failed" in out
    assert "s-01 · unknown · unknown · unknown" in out


async def test_source_fetch_multiple_sources_labels_every_span_and_preserves_text():
    lib = _lib()
    await lib.store.add(USER, _authored_source())
    statement = source(STATEMENT, kind="owner_dialogue", title="Synthetic decision",
                       blocks=["Continue with the blue plan.", "Decision recorded."])
    statement.raw.meta = {"occurred_on": "2026-09-08", "owner_name": "Avery",
                          "turn_ids": ["t0", "t1"],
                          "turns": [{"turn_id": "t0", "role": "owner"},
                                    {"turn_id": "t1", "role": "steward"}]}
    await lib.store.add(USER, statement)
    args = ("source", "fetch", SESSION, "¶0", "¶1-2", STATEMENT, "¶0")
    code, out, err = await run(lib, *args, "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert [{k: v for k, v in row.items() if k not in {"speakers", "calendar"}} for row in rows] == [
        {"source_id": SESSION, "blocks": [0, 0], "span": "¶0", "speaker": "Avery",
         "date": "2026-07-02", "text": "Choose the blue plan."},
        {"source_id": SESSION, "blocks": [1, 2], "span": "¶1-2", "speaker": "TestCoder",
         "date": "2026-07-02", "text": "The blue plan has three stages.\n\nStage two is review."},
        {"source_id": STATEMENT, "blocks": [0, 0], "span": "¶0", "speaker": "Avery",
         "date": "2026-09-08", "text": "Continue with the blue plan."},
    ]
    code, out, err = await run(lib, *args)
    assert code == 0, err
    assert out == UTC_BASIS + "\n" + "\n".join(
        f"{row['source_id']} " + " · ".join(
            f"¶{index} {row['speaker']}" for index in range(row["blocks"][0], row["blocks"][1] + 1)
        ) + f" · {row['date']}\n{row['text']}"
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
               "messages": [{"from": {"address": "avery@example.invalid"}}]}, ["unknown", "unknown"]),
])
async def test_source_speaker_labels_follow_authorship_not_text(kind, meta, expected):
    lib = _lib()
    item = source(SESSION, kind=kind, blocks=["Blair says Avery spoke.", "Avery says Blair spoke."])
    item.raw.meta = meta
    _stamp_envelope_ids(item)
    await lib.store.add(USER, item)
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0", "¶1", "--json")
    assert code == 0, err
    assert [row.get("speaker") for row in json.loads(out)] == expected
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0-1", "--json")
    assert code == 0, err
    assert [row["speaker"] for row in json.loads(out)[0]["speakers"]] == expected
    assert json.loads(out)[0].get("speaker") == (expected[0] if len(set(expected)) == 1 else None)


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
    assert out.startswith(f"query: {query}\n{UTC_BASIS}\nindexed blocks holding every term: 0")
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
    assert code == 1 and "indexed blocks holding every term: 0" in out and "showing: 0 of 0" in out
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
    item.raw.meta["turns"][1]["role"] = "unknown"
    await lib.store.add(USER, item)
    signals = SourceSignals(lib.store, USER)
    assert await signals.span(SESSION, 1, 1) == {
        "span": "¶1", "speaker": "unknown", "speakers": [{"span": "¶1", "speaker": "unknown"}],
    }
    assert await signals.span(SESSION, 0, 10**12) == {
        "span": "¶0-1000000000000", "speakers": [
            {"span": "¶0", "speaker": "Avery"}, {"span": "¶1", "speaker": "unknown"},
            {"span": "¶2", "speaker": "TestCoder"},
            {"span": "¶3-1000000000000", "speaker": "unknown"},
        ],
    }


async def test_reader_help_and_labels_follow_the_catalog_in_both_languages():
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service.coding_agent.skillpack import render_cli_md

    english = render_cli_md(build_parser())
    assert "--handoff ID pages the retained result without retrieval" in english
    assert "source index with cited-block speakers and days" in english
    assert "estimated per-term and all-terms indexed-block counts" in english
    assert "JSON is a list" in english
    try:
        override_prompts(chinese_overlay())
        lib = _lib()
        await lib.store.add(USER, _authored_source(owner_name=None))
        code, out, err = await run(lib, "source", "fetch", SESSION, "¶0")
        assert code == 0, err
        assert f"{SESSION} ¶0 用户 · 2026-07-02" in out
        code, out, err = await run(lib, "canonical", "read", PAGE)
        assert code == 0, err
        assert out.startswith(f"日期：UTC（未记录 Owner 时区）\n页面：{PAGE}\n最后改动：未知")
        assert "编译作业：0 待处理 · 0 失败" in out and "来源：" in out
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
    assert [{k: v for k, v in row.items() if k != "cited"} for row in payload["sources"]] == [
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
        "# 1 claims", "# 2 verbatim windows", "# 3 episode summaries (derived)", "# 4 map", "sources:",
    )]
    assert positions == sorted(positions)
    assert out.splitlines()[2].startswith("handoff: ")
    assert "cited: ¶0 Avery" in out
    assert "¶1 TestCoder" in out and "¶2 TestCoder" in out
    for kind, section in evidence.sections:
        section_body = section.partition("\n")[2] if kind in {"claims", "windows", "episodes"} else section
        assert section_body in out
    for handle, sid in evidence.handles.items():
        assert f"{handle} = {sid} · agent-session (TestCoder) · 2026-07-02" in out


async def test_canonical_supersession_uses_the_pinned_repository_and_claims_match_outline(monkeypatch):
    from pneuma_knowledge_core.canonical_glance import claim_count
    from pneuma_knowledge_core.domain.snapshot import SnapshotRef

    body = (
        "<!-- overview -->\n<!-- overview:definition -->\n### What this is\n\n"
        "A synthetic plan. c:aaaa <!-- c:eeee -->\n<!-- /overview -->\n\n"
        f"- Initial plan. [cite: {SESSION} ¶0] <!-- c:aaaa -->\n\n"
        f"- Original stage. [cite: {SESSION} ¶1] <!-- c:cccc -->\n\n"
        f"- New stage. [cite: {SESSION} ¶2] <!-- c:dddd --> <!-- supersedes: c:cccc -->\n"
    )
    page = document(PAGE, body)
    successor = document(OTHER, f"- Revised plan. [cite: {STATEMENT} ¶0] "
                         "<!-- c:bbbb --> <!-- supersedes: c:aaaa -->\n")
    lib = library(docs=[page, successor])
    calls = []

    async def pinned_list(user, *, at=None):
        calls.append((user, at))
        # The reader must not use an unpinned second listing to resolve successors.
        return [page, successor] if at is not None else [page]

    monkeypatch.setattr(lib.canonical, "list", pinned_list)
    code, out, err = await run(lib, "canonical", "read", PAGE, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert calls == [(USER, SnapshotRef(ref="c0", label="compile 1"))]
    assert payload["status"]["claims"] == claim_count(page) == 3
    assert payload["status"]["overview_blocks"] == 1
    assert payload["status"]["superseded"] == 2
    assert payload["supersessions"] == [
        {"predecessor": "c:aaaa", "successor": "c:bbbb", "path": OTHER},
        {"predecessor": "c:cccc", "successor": "c:dddd", "path": PAGE},
    ]
    code, outline, err = await run(lib, "outline", "--json")
    assert code == 0, err
    listed = [doc for family in json.loads(outline)["families"] for doc in family["documents"]]
    assert next(doc["claims"] for doc in listed if doc["path"] == PAGE) == payload["status"]["claims"]
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert f"superseded: 2 · c:aaaa → c:bbbb ({OTHER}) · c:cccc → c:dddd (this page)" in out
    assert "claims: 3 · overview blocks: 1" in out


async def test_compile_and_index_queue_signals_count_pending_and_failed_for_this_tenant():
    lib = _lib()
    queued = await lib.store.enqueue(USER, "compile", {})
    await lib.store.claim(USER, queued)
    await lib.store.enqueue(USER, "compile", {})
    failed = await lib.store.enqueue(USER, "compile", {})
    await lib.store.complete(USER, failed, ok=False)
    for tenant, kind, ok in [(USER, "compile", True), ("other", "compile", False),
                              (USER, "index", False), (USER, "index", True)]:
        job = await lib.store.enqueue(tenant, kind, {})
        await lib.store.complete(tenant, job, ok=ok)
    for _ in range(3):
        await lib.store.enqueue(USER, "index", {})
    await lib.store.enqueue("other", "index", {})
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert "compile jobs: 2 pending · 1 failed (pkc jobs --status failed)" in out
    code, out, err = await run(lib, "jobs", "--status", "failed", "--kind", "compile", "--json")
    assert code == 0, err
    assert [row["job_id"] for row in json.loads(out)["jobs"]] == [failed]
    code, out, _ = await run(lib, "search", "blue green", "--lexical")
    assert code == 1
    assert "indexed blocks holding every term: 0" in out
    assert "single-block matches" in out and "adjacent blocks" in out and "index may lag L0" in out
    assert "index jobs: 3 pending · 1 failed (pkc jobs --status failed)" in out
    code, out, _ = await run(lib, "search", "blue green", "--fused", "--json")
    assert json.loads(out)["index_queue_pending"] == 3
    assert json.loads(out)["index_queue_failed"] == 1


@pytest.mark.parametrize("kind,envelope,time_key", [
    ("agent_session", "turns", "at"), ("owner_dialogue", "turns", "said_at"),
    ("im", "messages", "sent_at"), ("meeting", "segments", "started_at"),
])
async def test_cited_blocks_use_their_own_days_and_individual_speakers(kind, envelope, time_key):
    lib = library(docs=[document(PAGE, f"- A synthetic decision. [cite: {SESSION} ¶0-2] <!-- c:aaaa -->")])
    item = source(SESSION, kind=kind, blocks=["First day.", "Later reply.", "Unknown speaker."])
    item.raw.meta = {
        "occurred_on": "2026-07-01", "owner_name": "Avery", "agent": {"name": "TestCoder"},
        "users": [{"user_id": "p1", "display_name": "Avery"},
                  {"user_id": "p2", "display_name": "TestCoder"}],
        "participants": [{"participant_id": "p1", "display_name": "Avery"},
                         {"participant_id": "p2", "display_name": "TestCoder"}],
        envelope: [
            {"role": "owner", "sender_id": "p1", "speaker_id": "p1", time_key: "2026-07-10T01:00:00+08:00"},
            {"role": "agent", "sender_id": "p2", "speaker_id": "p2", time_key: "2026-07-11T01:00:00+08:00"},
            {"role": "unknown", time_key: "2026-07-12T01:00:00+08:00"},
        ],
    }
    _stamp_envelope_ids(item)
    await _owner_calendar(lib, "Asia/Shanghai")
    # Owner-dialogue's counterpart is the declared Steward, not an arbitrary agent name.
    if kind == "owner_dialogue":
        item.raw.meta[envelope][1]["role"] = "steward"
    other_name = "Steward" if kind == "owner_dialogue" else "TestCoder"
    await lib.store.add(USER, item)
    for args in (("canonical", "read", PAGE), ("source", "fetch", SESSION, "¶0-2")):
        code, out, err = await run(lib, *args)
        assert code == 0, err
        assert f"¶0 Avery 2026-07-10 · ¶1 {other_name} 2026-07-11 · ¶2 unknown 2026-07-12" in out
        assert f"Avery, {other_name}" not in out
    code, out, _ = await run(lib, "canonical", "read", PAGE, "--json")
    assert json.loads(out)["sources"][0]["date"] == "2026-07-01"
    assert json.loads(out)["sources"][0]["cited"][0]["speakers"][1]["date"] == "2026-07-11"


def test_source_date_prefers_occurrence_and_labels_import_in_both_languages():
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service.cli.reader_signals import source_day

    time = time_context_for(USER)
    raw = source("dates").raw
    raw.created_at = datetime.fromisoformat("2026-09-07T01:00:00+08:00")
    assert source_day(raw, time) == "imported 2026-09-06"
    raw.meta["occurred_on"] = "2026-07-10"
    assert source_day(raw, time) == "2026-07-10"
    raw.meta["occurred_on"] = "2026-07-10T01:00:00+08:00"
    assert source_day(raw, time) == "2026-07-09"
    raw.meta["occurred_on"] = "invalid"
    try:
        override_prompts(chinese_overlay())
        assert source_day(raw, time) == "导入 2026-09-06"
    finally:
        reset_prompt_overrides()


def test_json_pages_top_level_and_largest_list_without_losing_other_fields():
    from pneuma_knowledge_service.cli.read import page_items

    rows = [{"index": i, "text": "synthetic " * 20} for i in range(12)]
    for payload, key in [(rows, "items"), ({"small": [1, 2, 3], "windows": rows, "query": "q"}, "windows")]:
        first = page_items(payload, 1, 500)
        assert first["paging"]["list"] == key
        assert first["paging"]["items"] == len(rows)
        gathered = []
        for n in range(1, first["paging"]["pages"] + 1):
            page = page_items(payload, n, 500)
            gathered.extend(page[key])
            if isinstance(payload, dict):
                assert page["small"] == [1, 2, 3] and page["query"] == "q"
        assert gathered == rows
    assert page_items(rows, 1, 100000) == rows


async def test_source_fetch_json_pages_list_and_all_pages_returns_original_list():
    lib = _lib()
    await lib.store.add(USER, source(SESSION, blocks=["synthetic " * 80] * 3))
    args = ("source", "fetch", SESSION, "¶0", "¶1", "¶2", "--json", "--page-chars", "1000")
    code, out, err = await run(lib, *args)
    assert code == 0, err
    first = json.loads(out)
    assert first["paging"]["list"] == "items" and len(first["items"]) == 1
    code, out, err = await run(lib, *args, "--page", "2")
    assert json.loads(out)["items"][0]["blocks"] == [1, 1]
    code, out, err = await run(lib, *args, "--all-pages")
    assert isinstance(json.loads(out), list) and len(json.loads(out)) == 3


def _ranked_evidence():
    from pneuma_knowledge_core.domain.canonical import Citation
    from pneuma_knowledge_core.recall.citation_alias import SessionAliaser, alias_sources
    from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim, recall_human_content

    claims = tuple(RetrievedClaim(
        anchor=anchor, document_path=path, section_path=(), text=text,
        citations=(Citation(source_id=SESSION, block_start=index, block_end=index),), score=score,
    ) for anchor, path, text, index, score in (
        ("aaaa", PAGE, "First ranked claim.", 0, 3),
        ("cccc", OTHER, "Third ranked claim.", 2, 1),
        ("bbbb", PAGE, "Second ranked claim.", 1, 2),
    ))
    windows = tuple(VecHit(source_id=SESSION, block_start=i, block_end=i,
                           text=f"Window {i}. " + "Synthetic material. " * 20, score=score)
                    for i, score in ((0, 3), (2, 1), (1, 2)))
    when = datetime(2026, 9, 9, tzinfo=timezone.utc)
    sections = []
    original = recall_human_content("synthetic query", list(claims), as_of=when,
                                    windows=list(windows), glance="A synthetic map.",
                                    evidence_sections=sections)
    body, handles = alias_sources(original)
    aliaser = SessionAliaser()
    return FastEvidence(
        question="synthetic query", as_of=when, system="Synthetic contract", content=body,
        handles=handles, used_claims=claims, used_windows=windows,
        sections=tuple((kind, aliaser.alias(section)) for kind, section in sections),
    )


@pytest.mark.parametrize("language", ["en", "zh"])
async def test_recall_sorts_scored_claims_and_windows_and_shares_section_labels(language, monkeypatch):
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service import cli
    from pneuma_knowledge_service.cli import read

    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        evidence = _ranked_evidence()
        lib = _lib()
        item = _authored_source()
        item.raw.meta["turns"][1]["at"] = "2026-07-10T12:00:00+08:00"
        await lib.store.add(USER, item)

        async def retrieve(*args, **kwargs):
            return evidence

        monkeypatch.setattr(read, "fast_recall", retrieve)
        monkeypatch.setattr(cli, "_handoffs", lambda ctx: lib.handoffs)
        code, out, err = await run(lib, "recall", "synthetic query", "--evidence", "--all-pages")
        assert code == 0, err
        positions = [out.index(f"[c:{anchor}") for anchor in ("aaaa", "bbbb", "cccc")]
        assert positions == sorted(positions)
        assert [out.index(f"Window {i}.") for i in range(3)] == sorted(out.index(f"Window {i}.") for i in range(3))
        assert "¶1 TestCoder 2026-07-10" in out
        labels = (("claims", "verbatim windows", "episode summaries (derived)", "map") if language == "en"
                  else ("断言", "原文窗口", "片段摘要（派生）", "地图"))
        section_index = next(line for line in out.splitlines() if line.startswith(("sections:", "章节：")))
        for n, label in enumerate(labels, 1):
            assert f"{n} {label}" in section_index and f"# {n} {label}\n" in out
        assert ("claims: ranked by relevance" if language == "en" else "断言: 按相关性排序") in out
        assert ("episode summaries (derived): in the lane's order" if language == "en"
                else "片段摘要（派生）: 保留 lane 顺序") in out
        handoff = out.splitlines()[2].split(": ", 1)[1]
        code, out, err = await run(lib, "recall", "--evidence", "--handoff", handoff, "--json", "--page-chars", "1")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["content"] == evidence.content and "paging" not in payload
        spans = payload["sources"][0]["cited"]
        assert [row["span"] for row in spans] == ["¶0", "¶1", "¶2"]
    finally:
        reset_prompt_overrides()


def test_recall_without_scores_preserves_lane_order_and_does_not_claim_ranking():
    from dataclasses import replace
    from pneuma_knowledge_service.cli.reader_signals import evidence_lines, evidence_tally

    evidence = _ranked_evidence()
    evidence = replace(evidence, used_claims=tuple(replace(c, score=0) for c in evidence.used_claims))
    header, lines = evidence_lines(evidence, evidence_tally(evidence), time_context_for(USER))
    assert "claims: in the lane's order" in "\n".join(header)
    body = "\n".join(lines)
    positions = [body.index(f"[c:{anchor}") for anchor in ("aaaa", "cccc", "bbbb")]
    assert positions == sorted(positions)


@pytest.mark.parametrize("visitor_class", ["business", "silent"])
async def test_recall_pages_are_retained_without_another_retrieval_or_handoff(visitor_class, monkeypatch):
    from pneuma_knowledge_service import cli
    from pneuma_knowledge_service.cli import read

    lib = _lib()
    await lib.store.add(USER, _authored_source())
    evidence = _ranked_evidence()
    calls = []

    async def retrieve(*args, **kwargs):
        calls.append(args)
        return evidence

    monkeypatch.setattr(read, "fast_recall", retrieve)
    monkeypatch.setattr(cli, "_handoffs", lambda ctx: lib.handoffs)
    code, first, err = await run(lib, "recall", "synthetic query", "--evidence", "--page-chars", "300",
                                 "--visitor-class", visitor_class)
    assert code == 0, err
    handoff = first.splitlines()[2].removeprefix("handoff: ")
    assert "new retrieval; pages of a retained result: --handoff " + handoff in first
    prefix = f"pkc --user {USER} recall --evidence --handoff {handoff}"
    assert first.splitlines()[3] == f"next page: {prefix} --page 2"
    assert len(calls) == 1 and len(await lib.handoffs.list_pending(USER)) == 1
    saved = await lib.handoffs.get(USER, handoff)
    assert saved["visitor_class"] == visitor_class
    assert saved["retained_result"]["payload"]["content"] == evidence.content
    pages = read.paginate(saved["retained_result"]["text"], 300)

    async def no_read(*args, **kwargs):
        raise AssertionError("retained paging touched live retrieval state")

    with monkeypatch.context() as patch:
        patch.setattr(read, "fast_recall", no_read)
        patch.setattr(read, "_fast_kwargs", no_read)
        patch.setattr(lib.store, "get", no_read)
        patch.setattr(lib.canonical, "snapshots", no_read)
        for n in range(2, len(pages) + 1):
            code, out, err = await run(lib, "recall", "--evidence", "--handoff", handoff, "--page", str(n))
            assert code == 0, err
            assert out.splitlines()[:3] == first.splitlines()[:3]
            assert pages[n - 1] in out
            assert f"[page {n}/{len(pages)}" in out and "new retrieval;" not in out
        code, whole, err = await run(lib, "recall", "--evidence", "--handoff", handoff, "--all-pages")
        assert code == 0 and saved["retained_result"]["text"] in whole
        code, json_result, err = await run(lib, "recall", "--evidence", "--handoff", handoff,
                                          "--json", "--page", "999", "--page-chars", "1")
        assert code == 0, err
        assert json.loads(json_result) == saved["retained_result"]["payload"]
        assert len(await lib.handoffs.list_pending(USER)) == 1
        # A different tenant cannot read the saved evidence; an absent result never retrieves.
        args = build_parser().parse_args(["--user", "other", "recall", "--evidence", "--handoff", handoff])
        out, err = io.StringIO(), io.StringIO()
        assert await dispatch(lib.ctx, args, out=out, err=err) == 1
        assert out.getvalue() == "" and "no retained handoff" in err.getvalue()
    # --page alone is deliberately a new call and identifies itself as such.
    code, fresh, err = await run(lib, "recall", "synthetic query", "--evidence", "--page", "2", "--page-chars", "300")
    assert code == 0, err
    assert "new retrieval;" in fresh and fresh.splitlines()[2] != first.splitlines()[2]
    assert len(calls) == 2 and len(await lib.handoffs.list_pending(USER)) == 2
    code, _, err = await run(lib, "consultations")
    assert code == 1 and "nobody has asked" in err


@pytest.mark.parametrize("argv", [
    ("recall",), ("recall", "--handoff", "id"),
    ("recall", "new query", "--evidence", "--handoff", "id"),
    ("recall", "--evidence", "--handoff", "id", "--include-archived"),
    ("recall", "--evidence", "--handoff", "id", "--visitor-class", "silent"),
])
async def test_recall_refuses_ambiguous_retained_arguments(argv):
    code, out, err = await run(_lib(), *argv)
    assert code == 2 and not out and err


def test_main_renders_chinese_cli_descriptions_after_applying_the_language(tmp_path, monkeypatch):
    from pneuma_knowledge_core.prompts import prompt, reset_prompt_overrides
    from pneuma_knowledge_service import cli, settings as settings_module
    from pneuma_knowledge_service.settings import Settings

    settings = Settings(engine_dir="", canonical_root=str(tmp_path / "canonical"),
                        user_schema_base_version="v1", components="")
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    output = tmp_path / "rendered"
    reset_prompt_overrides()
    try:
        # Enter through main: using build_parser as a thunk directly would miss the bug
        # where main captured an English parser before resolve_deployment applied zh.
        assert cli.main(["skill", "render", "--out", str(output), "--language", "zh"]) == 0
        reference = (output / "references" / "cli.md").read_text()
        for key in ("outline", "glance", "canonical_read", "source_fetch", "search", "recall"):
            assert prompt("steward.cli." + key) in reference
        assert "全库替代关系及后继地址" in reference
        assert "最新被引块日期" in reference
        assert "无条件读取一页或多页" in reference
    finally:
        reset_prompt_overrides()


async def test_latest_cited_source_compares_days_without_sorting_the_import_label():
    from pneuma_knowledge_core.prompts import override_prompts, reset_prompt_overrides

    lib = library(docs=[document(PAGE,
        f"- Synthetic comparison. [cite: {SESSION} ¶0] [cite: {STATEMENT} ¶0] <!-- c:aaaa -->")])
    imported = source(SESSION)
    imported.raw.created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    occurred = source(STATEMENT)
    occurred.raw.meta["occurred_on"] = "2026-09-08"
    await lib.store.add(USER, imported)
    await lib.store.add(USER, occurred)
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert "latest cited source: 2026-09-08" in out
    assert "imported 2026-08-01" in out
    occurred.raw.meta["occurred_on"] = "2026-07-01"
    await lib.store.add(USER, occurred)
    try:
        override_prompts({"steward.read.imported": "{day} (imported)"})
        code, out, err = await run(lib, "canonical", "read", PAGE)
        assert code == 0, err
        assert "latest cited source: 2026-08-01 (imported)" in out
    finally:
        reset_prompt_overrides()


async def test_recall_source_index_uses_evidence_citations_without_mining_the_query(monkeypatch):
    from dataclasses import replace
    from pneuma_knowledge_service import cli
    from pneuma_knowledge_service.cli import read

    lib = _lib()
    await lib.store.add(USER, _authored_source())
    evidence = _ranked_evidence()
    evidence = replace(evidence, content=evidence.content + f"\nQuestion: [cite: {STATEMENT} ¶99]")

    async def retrieve(*args, **kwargs):
        return evidence

    monkeypatch.setattr(read, "fast_recall", retrieve)
    monkeypatch.setattr(cli, "_handoffs", lambda ctx: lib.handoffs)
    code, out, err = await run(lib, "recall", "synthetic query", "--evidence", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["content"] == evidence.content
    assert [row["source_id"] for row in payload["sources"]] == [SESSION]
    assert [row["span"] for row in payload["sources"][0]["cited"]] == ["¶0", "¶1", "¶2"]


@pytest.mark.parametrize("language", ["en", "zh"])
async def test_every_reader_day_uses_the_owner_calendar_and_keeps_original_instants(language, monkeypatch):
    from dataclasses import replace
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service import cli
    from pneuma_knowledge_service.cli import read

    lib = library(
        docs=[document(PAGE, f"- Synthetic decision. [cite: {SESSION} ¶1] <!-- c:aaaa -->")],
        lexical_hits=[LexHit(source_id=SESSION, block_index=1, text="synthetic decision")],
    )
    profile = await _owner_calendar(lib, "Asia/Shanghai")
    # A deployment provider can differ from the persisted profile; use compile's provider.
    provider_calls = []

    async def get_profile(user):
        provider_calls.append(user)
        return profile

    monkeypatch.setattr(lib.ctx.user_info, "get_profile", get_profile)
    await lib.store.upsert_user_profile("other", {"locale": {"timezone": "America/New_York"}})
    item = _authored_source()
    item.raw.meta["occurred_on"] = "2026-09-07T20:30:00+00:00"
    block_at = "2026-09-08T20:30:00+00:00"
    for row, at in zip(item.raw.meta["turns"], (
        "2026-09-07T20:30:00+00:00", block_at, "2026-09-10T20:30:00+00:00",
    )):
        row["at"] = at
    await lib.store.add(USER, item)
    commit_at = "2026-09-08T22:00:00+00:00"

    async def last_commit(user, path, *, at=None):
        assert user == USER and at.ref == "c0"
        return "a" * 40, commit_at

    monkeypatch.setattr(lib.canonical, "last_commit", last_commit)
    when = datetime.fromisoformat(block_at)
    evidence = _ranked_evidence()
    evidence = replace(
        evidence, as_of=when, used_claims=(evidence.used_claims[2],), used_windows=(),
        sections=(("claims", f"# claims\nSynthetic decision. [cite: {SESSION} ¶1]"),),
    )

    async def retrieve(*args, **kwargs):
        return evidence

    monkeypatch.setattr(read, "fast_recall", retrieve)
    monkeypatch.setattr(cli, "_handoffs", lambda ctx: lib.handoffs)
    basis = "days: Owner's calendar (Asia/Shanghai)" if language == "en" else "日期：按 Owner 时区（Asia/Shanghai）"
    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        commands = (
            ("canonical", "read", PAGE), ("source", "fetch", SESSION, "¶1"),
            ("search", "synthetic", "--lexical"),
            ("recall", "synthetic", "--evidence", "--as-of", block_at),
        )
        for args in commands:
            provider_calls.clear()
            code, out, err = await run(lib, *args, "--all-pages")
            assert code == 0, err
            assert out.count(basis) == 1
            assert "¶1 TestCoder 2026-09-09" in out
            assert provider_calls == [USER]
            # Basis remains in the header when the body is paged past its first page.
            code, paged, err = await run(lib, *args, "--page", "2", "--page-chars", "60")
            assert code == 0, err
            assert paged.count(basis) == 1
            code, out, err = await run(lib, *args, "--json", "--all-pages")
            assert code == 0, err
            payload = json.loads(out)
            if args[0] == "canonical":
                status = payload["status"]
                assert status["last_changed"] == "2026-09-09"
                assert status["last_changed_at"] == commit_at
                # The uncited third turn is later, but cannot date this page's evidence.
                assert status["latest_cited_source"] == "2026-09-09"
                assert status["latest_cited_source_at"] == block_at
                assert payload["sources"][0]["date"] == "2026-09-08"
                assert payload["sources"][0]["at"] == item.raw.meta["occurred_on"]
                block = payload["sources"][0]["cited"][0]["speakers"][0]
            elif args[0] == "recall":
                assert payload["as_of"] == block_at
                assert payload["as_of_day"] == "2026-09-09"
                assert payload["content"] == evidence.content
                block = payload["sources"][0]["cited"][0]["speakers"][0]
                retained = await lib.handoffs.get(USER, payload["handoff_id"])
                assert "as_of: 2026-09-09 04:30 Asia/Shanghai" in retained["retained_result"]["header"]
            elif args[0] == "source":
                payload = payload[0]
                block = payload["speakers"][0]
            else:
                block = payload["hits"][0]["speakers"][0]
            assert payload["calendar"] == {"timezone": "Asia/Shanghai", "basis": "owner"}
            assert block["date"] == "2026-09-09" and block["at"] == block_at
    finally:
        reset_prompt_overrides()


DEFAULT_BASIS = "days: this deployment's default calendar (Pacific/Auckland); the Owner has not declared a timezone"


@pytest.mark.parametrize("zone,day,basis", [
    # No usable profile zone: the reader resolves the calendar the way the compile does —
    # the deployment's default next — and says so; 20:30 UTC is already the 9th in Auckland.
    (None, "2026-09-09", DEFAULT_BASIS),
    ("invalid/zone", "2026-09-09", DEFAULT_BASIS),
    ("UTC", "2026-09-08", "days: Owner's calendar (UTC)"),
    ("Asia/Shanghai", "2026-09-09", "days: Owner's calendar (Asia/Shanghai)"),
    ("America/New_York", "2026-09-08", "days: Owner's calendar (America/New_York)"),
])
async def test_reader_import_days_and_naive_storage_instants_share_the_stated_calendar(zone, day, basis):
    lib = _lib()
    lib.ctx.settings.default_timezone = "Pacific/Auckland"
    if zone is not None:
        await _owner_calendar(lib, zone)
    item = _authored_source()
    item.raw.meta.pop("occurred_on")
    # A naive storage instant is UTC; the DAY it is filed under follows the stated calendar.
    item.raw.created_at = datetime(2026, 9, 8, 20, 30)
    item.raw.meta["turns"][0]["at"] = "2026-09-08T20:30:00"
    await lib.store.add(USER, item)
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0", "--json")
    assert code == 0, err
    row = json.loads(out)[0]
    assert row["date"] == f"imported {day}"
    assert row["speakers"][0]["date"] == day
    assert row["at"] == row["speakers"][0]["at"] == "2026-09-08T20:30:00+00:00"
    code, out, err = await run(lib, "source", "fetch", SESSION, "¶0")
    assert code == 0, err
    assert out.startswith(basis + "\n")
    assert f"¶0 Avery {day}" in out


@pytest.mark.parametrize("kind,envelope,time_key", [
    ("agent_session", "turns", "at"), ("owner_dialogue", "turns", "said_at"),
    ("im", "messages", "sent_at"), ("meeting", "segments", "started_at"),
    ("email", "messages", "sent_at"),
])
@pytest.mark.parametrize("damage", ["short", "long", "reordered", "duplicate", "missing_ids", "bad_row", "block_order"])
async def test_reader_omits_dates_speakers_and_roles_from_misaligned_envelopes(kind, envelope, time_key, damage):
    lib = library(
        docs=[document(PAGE, f"- Synthetic decision. [cite: {SESSION} ¶0-1] <!-- c:aaaa -->")],
        lexical_hits=[LexHit(source_id=SESSION, block_index=0, text="synthetic decision")],
    )
    item = source(SESSION, kind=kind, blocks=["Original one.", "Original two."])
    item.raw.meta = {
        "owner_name": "Wrong attached name", "occurred_on": "2026-07-01",
        "agent": {"name": "Wrong agent"},
        "users": [{"user_id": "p", "display_name": "Wrong sender"}],
        "participants": [{"participant_id": "p", "display_name": "Wrong speaker"}],
        envelope: [{"role": "owner", "sender_id": "p", "speaker_id": "p",
                    "from": {"address": "wrong@example.invalid"}, time_key: "2026-09-08T20:30:00+00:00"}
                   for _ in range(2)],
    }
    _stamp_envelope_ids(item)
    ids_key = envelope[:-1] + "_ids"
    rows = item.raw.meta[envelope]
    if damage == "short":
        rows.pop()
    elif damage == "long":
        rows.append(dict(rows[0]))
    elif damage == "reordered":
        rows.reverse()
    elif damage == "duplicate":
        item.raw.meta[ids_key][1] = item.raw.meta[ids_key][0]
        rows[1][envelope[:-1] + "_id"] = rows[0][envelope[:-1] + "_id"]
    elif damage == "missing_ids":
        item.raw.meta.pop(ids_key)
    elif damage == "bad_row":
        rows[0] = None
    else:
        item.blocks.reverse()
    await lib.store.add(USER, item)
    for args in (("source", "fetch", SESSION, "¶0-1"), ("canonical", "read", PAGE),
                 ("search", "synthetic", "--lexical")):
        code, out, err = await run(lib, *args, "--json")
        assert code == 0, err
        payload = json.loads(out)
        if args[0] == "source":
            blocks = payload[0]["speakers"]
        elif args[0] == "canonical":
            blocks = payload["sources"][0]["cited"][0]["speakers"]
        else:
            blocks = payload["hits"][0]["speakers"]
        assert all(row == {"span": row["span"], "speaker": "unknown"} for row in blocks)


@pytest.mark.parametrize("owner_display", [None, "Avery"])
async def test_email_reader_exposes_normalized_roles_and_latest_cited_message_day(owner_display):
    from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
    from pneuma_knowledge_core.ingest.source_contracts import EmailSource

    lib = library()
    profile = await _owner_calendar(lib, "Asia/Shanghai")
    instants = ("2026-09-07T20:00:00+00:00", "2026-09-08T20:00:00+00:00", "2026-09-10T20:00:00+00:00")
    contract = EmailSource.model_validate({
        "schema": "pneuma.source.email/v1", "provider": "mock", "archive_id": "synthetic-mail",
        "owner_addresses": ["Avery@Example.Invalid"], "threads": [{
            "thread_id": "synthetic-thread", "subject": "Synthetic schedule",
            "messages": [{"message_id": f"m{i}", "sent_at": at,
                          "from": {"address": address, "display_name": display},
                          "to": [], "cc": [], "subject": "Synthetic schedule", "text": f"Synthetic message {i}."}
                         for i, (at, address, display) in enumerate(zip(instants,
                             ("blair@example.invalid", "avery@example.invalid", "blair@example.invalid"),
                             ("Blair", owner_display, "Blair")))],
        }],
    })
    item = normalize_source_contract(contract, USER, imported_at=datetime.now(timezone.utc),
                                     time=time_context_for(USER, profile))[0]
    sid = str(item.raw.source_id)
    await lib.store.add(USER, item)
    lib.canonical._docs = [document(PAGE, f"- Synthetic schedule. [cite: {sid} ¶0-1] <!-- c:aaaa -->")]
    code, out, err = await run(lib, "canonical", "read", PAGE, "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["sources"][0]["date"] == "2026-09-08"
    assert payload["status"]["latest_cited_source"] == "2026-09-09"
    assert payload["status"]["latest_cited_source_at"] == instants[1]
    blocks = payload["sources"][0]["cited"][0]["speakers"]
    assert [b["role"] for b in blocks] == ["other", "owner"]
    assert [b["date"] for b in blocks] == ["2026-09-08", "2026-09-09"]
    assert [b["at"] for b in blocks] == list(instants[:2])
    code, out, err = await run(lib, "canonical", "read", PAGE)
    assert code == 0, err
    assert f"cited: ¶0 Blair 2026-09-08 · ¶1 {owner_display or 'avery@example.invalid'} 2026-09-09" in out


async def test_failed_index_jobs_remain_visible_when_none_are_pending():
    lib = library()
    failed = await lib.store.enqueue(USER, "index", {})
    await lib.store.complete(USER, failed, ok=False)
    other = await lib.store.enqueue("other", "index", {})
    await lib.store.complete("other", other, ok=False)
    for mode in ("--lexical", "--fused"):
        code, out, err = await run(lib, "search", "unindexed", mode)
        assert code == 1
        assert "index jobs: 0 pending · 1 failed (pkc jobs --status failed)" in out
        assert "none pending" not in out


def test_all_static_cli_help_uses_the_active_catalog():
    import argparse
    from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
    from pneuma_knowledge_service.coding_agent.skillpack import render_cli_md

    def help_strings(parser):
        if parser.description:
            yield parser.description
        for action in parser._actions:
            if action.help:
                yield action.help
            if isinstance(action, argparse._SubParsersAction):
                for entry in action._choices_actions:
                    if entry.help:
                        yield entry.help
                for child in action.choices.values():
                    yield from help_strings(child)

    english = list(help_strings(build_parser()))
    try:
        override_prompts(chinese_overlay())
        parser = build_parser()
        chinese = list(help_strings(parser))
        assert len(english) == len(chinese)
        for en, zh in zip(english, chinese):
            assert en != zh, en
            assert any("\u4e00" <= char <= "\u9fff" for char in zh), zh
        reference = render_cli_md(parser)
        for text in ("每页字符数", "输出全部正文或 JSON", "仅 L1", "解析相对时间所用的基准时刻", "写入技能包的目录"):
            assert text in reference
        override_prompts({"steward.cli.page": "自定义分页说明"})
        assert "自定义分页说明" in render_cli_md(build_parser())
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("engine", [False, True])
def test_main_help_applies_chinese_before_argparse_exits(engine, tmp_path, monkeypatch, capsys):
    from pneuma_knowledge_core.prompts import reset_prompt_overrides
    from pneuma_knowledge_service import cli, settings as settings_module
    from pneuma_knowledge_service.settings import Settings

    engine_dir = tmp_path / "engine"
    if engine:
        (engine_dir / "prompts").mkdir(parents=True)
        (engine_dir / "prompts" / "overlays.yaml").write_text("language: zh\n")
    settings = Settings(engine_dir=str(engine_dir) if engine else "", prompt_language="zh",
                        user_schema_base_version="v1", components="")
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    reset_prompt_overrides()
    try:
        with pytest.raises(SystemExit) as exc:
            cli.main(["search", "-h"])
        assert exc.value.code == 0
        help_text = " ".join(capsys.readouterr().out.split())
        assert "显示帮助并退出" in help_text
        assert "每页字符数" in help_text and "仅 L1" in help_text
        assert "characters per page" not in help_text
    finally:
        reset_prompt_overrides()


async def test_the_reader_counts_days_on_the_deployment_default_calendar_when_the_owner_declared_none():
    """The compile resolves the Owner's calendar as profile zone → deployment default → UTC;
    the read commands must resolve it the same way, and say which link answered."""
    from types import SimpleNamespace
    from pneuma_knowledge_service.cli.reader_signals import SourceSignals, calendar_basis

    lib = _lib()
    lib.settings = SimpleNamespace(**{**getattr(lib, "settings", SimpleNamespace()).__dict__, "default_timezone": "Asia/Shanghai"}) \
        if hasattr(lib, "settings") else SimpleNamespace(default_timezone="Asia/Shanghai")
    signals = await SourceSignals.for_runtime(lib, USER)
    assert signals.time.zone_name == "Asia/Shanghai"
    assert calendar_basis(signals.time) == "deployment_default"
    lib.settings = SimpleNamespace(default_timezone="UTC")
    signals = await SourceSignals.for_runtime(lib, USER)
    assert calendar_basis(signals.time) == "utc_fallback"
