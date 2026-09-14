"""The structure lens's two read faces: `GET /…/lens` and `pkc lens`.

One property holds both together and is what most of these assert: the console and the
terminal read ONE report. The service assembles it once (`service/lens.py`), so a test that
compares the route's body with the command's `--json` is testing the mechanism rather than
two renderings that happen to agree today (docs/design/structure-lens.md §5).

Keyless throughout, over the same stand-in library the other `pkc` tests use. The lens is
pure core and model-free, so there is nothing here to mock but the adapters.
"""

from __future__ import annotations

import io
import json
import subprocess

import httpx
import pytest
from fastapi import FastAPI

from pneuma_knowledge_service.adapters.read_mock import InMemoryLibraryStore
from pneuma_knowledge_service.api.routes.v1 import router
from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.lens import read_lens

from _cli_library import USER, document, library  # noqa: E402

PAGE = "memory/topics/pricing.md"
OTHER = "memory/people/cheng-ye.md"


def _lib(**kw):
    """Two pages that cite a source and never link to each other — an ordinary small library,
    and one the navigability lenses have something to say about."""
    return library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(OTHER, "## 程野\n\n- 程野 leads backend. [cite: s-01 ¶0] <!-- c:bbb2 -->\n"),
        ],
        **kw,
    )


async def run(lib, *argv):
    """One `pkc …` invocation, parsed as the process parses it. `(exit, stdout, stderr)`."""
    args = build_parser().parse_args(["--user", str(USER), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(lib.ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def get(lib, path: str):
    app = FastAPI()
    app.state.ctx = lib.ctx
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


# ─────────────────────────────────────────────────────────────────────────── the route


async def test_the_route_answers_the_report_shape_the_design_fixes():
    response = await get(_lib(), f"/v1/users/{USER}/lens")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "ref", "read_at", "subjects", "files", "claims", "edges", "score",
        "findings", "families",
    }
    assert body["files"] == 2 and body["claims"] == 2
    assert 0 <= body["score"] <= 100
    for finding in body["findings"]:
        # §3: a finding is addressed to someone and says what to do — every one of them,
        # or the report is back to being an instrument printing numbers.
        assert finding["level"] in {"principle", "drift", "shape"}
        assert finding["actor"] in {"owner", "steward", "mechanism"}
        assert finding["impact"]["key"] and finding["action"]["key"]
        assert finding["key"]
        # This version keeps no decline record, so nothing is ever decided (§9).
        assert finding["decision"] is None


async def test_the_route_reads_the_ref_it_is_given_and_says_which_one():
    lib = _lib()
    assert (await get(lib, f"/v1/users/{USER}/lens")).json()["ref"] == ""
    at = (await get(lib, f"/v1/users/{USER}/lens?at=c0")).json()
    assert at["ref"] == "c0"
    assert at["files"] == 2


async def test_an_empty_library_is_a_report_and_not_an_error():
    """Nothing to read is a reading with nothing in it — the counts are zero and the only
    thing the lens can say is that the contract declares families no page lives under."""
    body = (await get(library(), f"/v1/users/{USER}/lens")).json()
    assert body["files"] == 0 and body["claims"] == 0 and body["subjects"] == 0
    assert {f["lens"] for f in body["findings"]} <= {"bal.family_empty"}


async def test_the_report_is_a_function_of_the_ref_and_nothing_else():
    """Twice at the same ref → the same bytes, `read_at` aside. Nothing is stored, so a
    second read cannot see a first read's leftovers (§3, §7)."""
    lib = _lib()
    first = (await get(lib, f"/v1/users/{USER}/lens")).json()
    second = (await get(lib, f"/v1/users/{USER}/lens")).json()
    first.pop("read_at"), second.pop("read_at")
    assert first == second


# ───────────────────────────────────────────────────────────────────────────── the CLI


async def test_pkc_lens_prints_the_counts_the_score_and_every_finding():
    lib = _lib()
    report, _documents = await read_lens(lib.ctx, USER)
    code, out, err = await run(lib, "lens", "--all-pages")
    assert code == 0, err
    assert f"score {report.score}" in out
    assert f"{report.files} files" in out and f"{report.claims} claims" in out
    for finding in report.findings:
        assert finding.key in out, finding.key
        assert finding.lens in out


async def test_pkc_lens_json_is_the_report_the_route_serves():
    lib = _lib()
    code, out, _err = await run(lib, "lens", "--json", "--all-pages")
    assert code == 0
    command = json.loads(out)
    served = (await get(lib, f"/v1/users/{USER}/lens")).json()
    command.pop("read_at"), served.pop("read_at")
    assert command == served


async def test_pkc_lens_at_a_ref_reports_that_ref():
    code, out, _err = await run(_lib(), "lens", "--json", "--at", "c0", "--all-pages")
    assert code == 0 and json.loads(out)["ref"] == "c0"


async def test_pkc_lens_path_narrows_to_one_page():
    lib = _lib()
    report, _documents = await read_lens(lib.ctx, USER)
    code, out, err = await run(lib, "lens", "--path", PAGE, "--json", "--all-pages")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["path"] == PAGE
    keys = {finding["key"] for finding in payload["findings"]}
    assert keys == {f.key for f in report.findings if PAGE in f.paths}
    assert keys <= {f.key for f in report.findings}


async def test_pkc_lens_refuses_to_call_a_page_the_library_lacks_clean():
    code, out, err = await run(_lib(), "lens", "--path", "memory/topics/nope.md")
    assert code == 1 and not out
    assert "no such page" in err


async def test_pkc_lens_on_an_empty_library_says_so_and_exits_one():
    code, _out, err = await run(library(), "lens")
    assert code == 1
    assert "no canonical pages" in err


# ──────────────────────────────────────────────────────────── it is only a read face


def test_the_lens_registers_no_component_and_no_setting():
    """§9: this version reaches no compile task. Nothing registers a `lens` component, and
    there is no knob to bound notes that are not raised."""
    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.wiring import register_components

    assert not any("lens" in name for name in Settings.model_fields)
    with pytest.raises(ValueError):
        register_components(Settings(components="lens"), store=None, canonical=None)


def test_the_command_reference_lists_pkc_lens_beside_the_other_maps():
    """The generated skill package names it as a read face and instructs nothing: it is a
    line in the command reference, rendered from the parser like every other command."""
    from pneuma_knowledge_core.prompts import prompt
    from pneuma_knowledge_service.coding_agent.skillpack import render_cli_md

    reference = render_cli_md(build_parser())
    assert "`pkc lens`" in reference
    assert prompt("steward.cli.lens") in reference


# ───────────────────────────────────────────── a machine face is never a partial one


def _many(count: int = 24):
    """A library with enough subjects that the findings cannot fit one small page."""
    return library(
        docs=[
            document(
                f"memory/topics/t{index:02}.md",
                f"## T{index}\n\n- Fact {index}. [cite: s-01 ¶{index}] <!-- c:t{index:03}1 -->\n",
            )
            for index in range(count)
        ]
    )


async def test_json_serialises_every_finding_however_small_the_page_is():
    """The defect this pins: `--json` went through prose paging and returned nine findings of
    three hundred, as a well-formed document with nothing saying it was cut. A caller cannot
    tell a page from a report, so the report is never a page."""
    lib = _many()
    report, _documents = await read_lens(lib.ctx, USER)
    assert len(report.findings) > 10, "the fixture must not fit one page"
    code, out, err = await run(lib, "lens", "--json", "--page-chars", "400")
    assert code == 0, err
    payload = json.loads(out)
    assert [f["key"] for f in payload["findings"]] == [f.key for f in report.findings]
    assert "paging" not in payload


async def test_prose_pages_and_says_how_many_findings_it_did_not_show():
    """The other half of the same rule: prose may page — a reader asked for one page — but a
    page that stopped silently would make the same false claim the JSON one did."""
    lib = _many()
    report, _documents = await read_lens(lib.ctx, USER)
    code, out, err = await run(lib, "lens", "--page-chars", "600")
    assert code == 0, err
    assert f"of {len(report.findings)} findings" in out
    assert "--page 2 for the next" in out
    # The counts and the score are above the fold on every page, never paged away.
    assert f"score {report.score}" in out
    whole, _err = (await run(lib, "lens", "--all-pages"))[1:]
    for finding in report.findings:
        assert finding.key in whole
    assert "page 1/" not in whole


# ──────────────────────────────── a report over canonical needs no half of the deployment


class _MemoryStore(InMemoryLibraryStore):
    """`InMemoryLibraryStore` with the lifecycle `build_context` drives, so the real
    `build_context` runs without Postgres. Everything else below is the shipped path:
    settings, wiring, the parser, dispatch."""

    def __init__(self, _dsn: str, **_connection) -> None:  # noqa: ANN003 — application_name
        super().__init__()

    async def open(self) -> None:
        return None

    async def apply_schema(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _canonical_repo(tmp_path):
    """One committed page in a real git canonical repository, as the adapter reads it."""
    root = tmp_path / "canonical"
    repo = root / str(USER)
    (repo / "memory" / "topics").mkdir(parents=True)
    (repo / "memory" / "topics" / "pricing.md").write_text(
        "---\ndoc_id: doc-pricing\ntype: topic\nslug: pricing\n---\n\n"
        "# Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n",
        encoding="utf-8",
    )
    for command in (
        ["init", "-q"],
        ["config", "user.email", "pneuma_knowledge@local"],
        ["config", "user.name", "pneuma-knowledge"],
        ["add", "-A"],
        ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "seed"],
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True)
    return root


def test_lens_needs_no_embedding_key_on_a_semantic_deployment(tmp_path, monkeypatch, capsys):
    """The same cold start `pkc profile` answers (PR #25): semantic retrieval is on, the
    embedding spec is real, and no key has been stored yet — so constructing that model
    REFUSES. Reading the shape of the library the Owner already has must not depend on the
    half of the deployment they are still setting up. Nothing here is faked into working:
    the spec below is the one that raises.
    """
    from pneuma_knowledge_service import wiring
    from pneuma_knowledge_service.cli import main
    from pneuma_knowledge_service.settings import Settings

    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENV_FILE", "")  # the machine's `.env` states nothing here
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CANONICAL_ROOT", str(_canonical_repo(tmp_path)))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL", "on")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_EMBEDDING_MODEL", "openrouter:google/gemini-embedding-2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr(wiring, "PostgresStore", _MemoryStore)

    # The premise, stated as a fact rather than assumed: this deployment cannot build
    # embeddings at all right now.
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        wiring.build_embeddings(Settings(_env_file=None))

    assert main(["--user", str(USER), "lens", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 1 and payload["claims"] == 1
