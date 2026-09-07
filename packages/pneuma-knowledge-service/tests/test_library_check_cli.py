"""`pkc library check` — the gate's predicates over the committed library (ruling 10).

Four defects, one fixture, one finding each, in the gate's own rendering: a duplicate anchor,
a citation past its source's block count, a page outside the composed templates, and a
canonical commit with no attribution trailer. Then the same command over a clean library,
which must exit 0 — a check that reports something about every repository is a check nobody
reads.

It never repairs. The assertion that it does not is the tail of each test: the documents the
store holds are the documents it held.
"""

from __future__ import annotations

import io
import json

from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_service.cli import check as check_cmd

from _cli_library import USER, document, library, source

# Inside the reference contract's templates (`memory/...`), so a clean fixture is clean.
PAGE = "memory/topics/pricing.md"
PERSON = "memory/people/cheng-ye.md"
OUTSIDE = "notes/scratch.md"


async def _check(lib, *, as_json=True):
    out, err = io.StringIO(), io.StringIO()
    code = await check_cmd.cmd_library_check(
        lib.ctx, USER, as_json=as_json, out=out, err=err
    )
    return code, out.getvalue(), err.getvalue()


def _findings(out: str) -> list[dict]:
    return json.loads(out)["findings"]


async def _clean(**kw):
    lib = library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(
                PERSON,
                "## Cheng Ye\n\n- Cheng Ye leads backend. [cite: s-01 ¶0] <!-- c:bbb2 -->\n",
                type="person",
            ),
        ],
        **kw,
    )
    await lib.store.add(USER, source("s-01", blocks=["a", "b", "c"]))
    return lib


async def test_a_clean_library_reports_nothing_and_exits_zero():
    lib = await _clean()
    code, out, _err = await _check(lib)
    assert code == 0, _findings(out)
    assert _findings(out) == []


async def test_a_duplicate_anchor_is_reported_once_in_the_gates_own_rendering():
    lib = library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(
                PERSON,
                "## Cheng Ye\n\n- Cheng Ye leads backend. [cite: s-01 ¶0] <!-- c:aaa1 -->\n",
                type="person",
            ),
        ]
    )
    await lib.store.add(USER, source("s-01", blocks=["a", "b", "c"]))
    code, out, _err = await _check(lib)
    assert code == 4
    kinds = [f["kind"] for f in _findings(out)]
    assert kinds.count("anchor_uniqueness") == 1

    # …and the prose face prints the same line `post_write_violations` renders.
    _code, plain, _err = await _check(lib, as_json=False)
    assert "[anchor_uniqueness]" in plain


async def test_a_citation_past_a_sources_block_count_is_reported():
    lib = library(
        docs=[
            document(
                PAGE,
                "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶9] <!-- c:aaa1 -->\n",
            )
        ]
    )
    await lib.store.add(USER, source("s-01", blocks=["a", "b", "c"]))
    code, out, _err = await _check(lib)
    assert code == 4
    citation = [f for f in _findings(out) if f["kind"] == "citation"]
    assert len(citation) == 1 and citation[0]["path"] == PAGE


async def test_a_page_outside_the_templates_is_reported_as_unowned():
    lib = library(
        docs=[
            document(OUTSIDE, "## Scratch\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n")
        ]
    )
    await lib.store.add(USER, source("s-01", blocks=["a", "b", "c"]))
    code, out, _err = await _check(lib)
    assert code == 4
    assert [f["path"] for f in _findings(out) if f["kind"] == "path"] == [OUTSIDE]


async def test_a_commit_without_the_framework_trailer_is_reported():
    lib = await _clean(
        snapshots=[SnapshotRef(ref="c1", label="compile 1"), SnapshotRef(ref="c0", label="init")],
        trailers={"c1": "v1"},
    )
    code, out, _err = await _check(lib)
    assert code == 4
    trailer = [f for f in _findings(out) if f["kind"] == "trailer"]
    assert len(trailer) == 1 and trailer[0]["path"] == "c0"
    assert "Skill-Version" in trailer[0]["detail"]


async def test_the_check_reports_and_never_repairs():
    lib = library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶9] <!-- c:aaa1 -->\n")
        ]
    )
    await lib.store.add(USER, source("s-01", blocks=["a", "b", "c"]))
    before = [(d.path, d.body) for d in await lib.canonical.list(USER)]
    await _check(lib)
    assert [(d.path, d.body) for d in await lib.canonical.list(USER)] == before


async def test_an_empty_library_has_nothing_to_check():
    code, _out, err = await _check(library(), as_json=False)
    assert code == 1
    assert "no canonical pages" in err
