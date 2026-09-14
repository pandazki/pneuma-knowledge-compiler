"""Tier three — the structure lens's two read faces: `GET /…/lens` and `pkc lens`.

One property holds both together and is what most of these assert: the console and the
terminal read ONE reading. The service assembles it once (`service/lens.py`), so a test that
compares the route's body with the command's `--json` is testing the mechanism rather than
two renderings that happen to agree today (docs/design/structure-lens.md §4.5).

The second property is the one the lens is FOR: it lists no pages. A page-level finding
belongs to the check (`test_review_faces.py`) and a write-time fault to the gate, so what is
left here is the reading that needs the god's-eye — six dimensions and their movement.

Keyless throughout, over the same stand-in library the other `pkc` tests use. The lens is
pure core and model-free, so there is nothing here to mock but the adapters.
"""

from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_service.adapters.read_mock import InMemoryLibraryStore
from pneuma_knowledge_service.api.routes.v1 import router
from pneuma_knowledge_service.cli import build_parser, dispatch, needs_semantic
from pneuma_knowledge_service.lens import read_reading

from _cli_library import USER, document, library  # noqa: E402

PAGE = "memory/topics/pricing.md"
OTHER = "memory/people/cheng-ye.md"

#: The dimensions §4.2 fixes. The lens answers all six or it is not the lens.
DIMENSIONS = {
    "walkability", "shape", "knowledge_vs_log", "liveness", "type_structure", "demand_supply",
}


def _history(*refs: str):
    """A canonical history, newest first — the order the adapter's own page comes back in."""
    return [SnapshotRef(ref=ref, label=f"compile {index}") for index, ref in enumerate(refs)]


def _lib(**kw):
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


async def test_the_route_answers_the_reading_shape_the_design_fixes():
    response = await get(_lib(), f"/v1/users/{USER}/lens")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "ref", "read_at", "previous_ref", "subjects", "files", "claims", "edges",
        "dimensions",
    }
    assert body["files"] == 2 and body["claims"] == 2
    assert {d["id"] for d in body["dimensions"]} == DIMENSIONS
    for dimension in body["dimensions"]:
        # §4.2: a dimension says what it sees and what that implies, both through the
        # catalog — a number with no sentence is the instrument the lens is not.
        assert dimension["band"]
        assert dimension["statement"]["key"] and dimension["direction"]["key"]
        for metric in dimension["metrics"]:
            assert set(metric) == {"name", "value", "previous", "delta"}


async def test_the_reading_lists_no_pages_anywhere():
    """The tier ruling, as a property of the body: no `findings` key, at any depth."""
    body = (await get(_lib(), f"/v1/users/{USER}/lens")).json()
    assert "findings" not in json.dumps(body)


async def test_the_route_always_names_the_commit_it_read():
    """HEAD is not a ref a reader can come back to. A reading that left `ref` empty for the
    default read could not say which library it came out of, so two readings taken either
    side of a compile were indistinguishable after the fact."""
    lib = _lib(snapshots=_history("c1", "c0"))
    assert (await get(lib, f"/v1/users/{USER}/lens")).json()["ref"] == "c1"
    at = (await get(lib, f"/v1/users/{USER}/lens?at=c0")).json()
    assert at["ref"] == "c0"  # a named ref stays exactly as it was passed
    assert at["files"] == 2


async def test_a_library_with_no_history_names_no_commit_rather_than_inventing_one():
    lib = _lib(snapshots=[])
    assert (await get(lib, f"/v1/users/{USER}/lens")).json()["ref"] == ""


async def test_the_reading_is_a_function_of_the_ref_and_nothing_else():
    lib = _lib()
    first = (await get(lib, f"/v1/users/{USER}/lens")).json()
    second = (await get(lib, f"/v1/users/{USER}/lens")).json()
    first.pop("read_at"), second.pop("read_at")
    assert first == second


# ──────────────────────────────────────────────────────────────── the previous reading


async def test_the_default_previous_reading_is_the_commit_before_this_one():
    """§4.3: a reading carries the previous one when one exists, and the one every library
    has without anybody naming it is the commit before `at`."""
    lib = _lib(snapshots=_history("c2", "c1", "c0"))  # newest first: HEAD is c2
    # HEAD's PARENT, not HEAD: comparing a reading with itself is a movement of zero, which
    # is a different sentence from no movement, and only one of the two would be true.
    assert (await get(lib, f"/v1/users/{USER}/lens")).json()["previous_ref"] == "c1"
    at_c1 = (await get(lib, f"/v1/users/{USER}/lens?at=c1")).json()
    assert at_c1["previous_ref"] == "c0"


async def test_a_named_previous_wins_over_the_default():
    lib = _lib(snapshots=_history("c2", "c1", "c0"))
    body = (await get(lib, f"/v1/users/{USER}/lens?previous=c0")).json()
    assert body["previous_ref"] == "c0"


async def test_previous_none_asks_for_a_reading_with_no_movement():
    lib = _lib(snapshots=_history("c2", "c1", "c0"))
    body = (await get(lib, f"/v1/users/{USER}/lens?previous=none")).json()
    assert body["previous_ref"] == ""
    for dimension in body["dimensions"]:
        for metric in dimension["metrics"]:
            assert metric["previous"] is None and metric["delta"] is None


async def test_a_library_with_one_commit_reads_without_a_previous_one():
    """The first reading of a new library is a reading, not an error: there is simply
    nothing behind it to move against."""
    lib = _lib(snapshots=_history("c0"))
    assert (await get(lib, f"/v1/users/{USER}/lens")).json()["previous_ref"] == ""


async def test_a_previous_ref_the_history_does_not_hold_is_no_movement_not_a_failure():
    lib = _lib(snapshots=_history("c0"))
    body = (await get(lib, f"/v1/users/{USER}/lens?at=not-a-ref")).json()
    assert body["ref"] == "not-a-ref" and body["previous_ref"] == ""
    assert {d["id"] for d in body["dimensions"]} == DIMENSIONS


# ─────────────────────────────────────────────────── what the reading is computed over


class _Consulted(InMemoryLibraryStore):
    """A store whose consultation ledger answers the replay face the lens reads."""

    def __init__(self, records) -> None:  # noqa: ANN001
        super().__init__()
        self._records = list(records)

    async def list_consultations(self, user_id, **_kw):  # noqa: ANN001
        return list(self._records)


def _record(index: int, *paths: str, cited: bool = True) -> ConsultationRecord:
    refs = tuple(EvidenceRef(kind="claim", ref=f"c:x{index}", path=path) for path in paths)
    return ConsultationRecord(
        consultation_id=f"k-{index}",
        user_id=str(USER),
        created_at=datetime(2026, 3, 1, 12, index, tzinfo=timezone.utc),
        lane="fast",
        visitor_class="business",
        question="what does pricing say?",
        as_of=None,
        library_ref="c0",
        evidence_handed=refs,
        answer_kind="answer",
        answer="…",
        citations=refs if cited else (),
        miss=not cited,
    )


async def test_demand_is_read_from_the_kept_consultation_records():
    """§4.2: `demand_supply` is `unread` with no consultations and reads them when they are
    there — and it is the KEPT records it reads, never a second copy of anything."""
    lib = _lib()
    unread = next(
        d for d in (await get(lib, f"/v1/users/{USER}/lens")).json()["dimensions"]
        if d["id"] == "demand_supply"
    )
    assert unread["band"] == "unread"

    lib.ctx.store = _Consulted([_record(1, PAGE), _record(2, PAGE, cited=False)])
    reading = await read_reading(lib.ctx, USER)
    demand = next(d for d in reading.to_dict()["dimensions"] if d["id"] == "demand_supply")
    assert demand["band"] != "unread"


async def test_a_consultation_ledger_that_cannot_be_read_is_unread_and_never_an_error():
    """A deployment whose consultation table is unreachable must report "not read" rather
    than "nobody asks this library anything"."""

    class _Broken(InMemoryLibraryStore):
        async def list_consultations(self, user_id, **_kw):  # noqa: ANN001
            raise RuntimeError("no such table")

    lib = _lib()
    lib.ctx.store = _Broken()
    demand = next(
        d for d in (await read_reading(lib.ctx, USER)).to_dict()["dimensions"]
        if d["id"] == "demand_supply"
    )
    assert demand["band"] == "unread"


# ───────────────────────────────────────────────────────────────────────────── the CLI


async def test_pkc_lens_prints_the_counts_and_every_dimension():
    lib = _lib()
    reading = await read_reading(lib.ctx, USER)
    code, out, err = await run(lib, "lens", "--all-pages")
    assert code == 0, err
    assert f"{reading.files} files" in out and f"{reading.claims} claims" in out
    for dimension in reading.dimensions:
        assert dimension.id in out
        assert dimension.band in out


async def test_pkc_lens_json_is_the_reading_the_route_serves():
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


async def test_pkc_lens_previous_takes_the_ref_or_none():
    lib = _lib(snapshots=_history("c2", "c1", "c0"))
    code, out, _err = await run(lib, "lens", "--json", "--previous", "c0", "--all-pages")
    assert code == 0 and json.loads(out)["previous_ref"] == "c0"
    code, out, _err = await run(lib, "lens", "--json", "--previous", "none", "--all-pages")
    assert code == 0 and json.loads(out)["previous_ref"] == ""


async def test_pkc_lens_on_an_empty_library_says_so_and_exits_one():
    code, _out, err = await run(library(), "lens")
    assert code == 1


async def test_json_is_never_a_page_however_small_the_page_is():
    """A caller cannot tell a page from a reading, so the reading is never a page."""
    lib = _lib()
    code, out, err = await run(lib, "lens", "--json", "--page-chars", "200")
    assert code == 0, err
    assert {d["id"] for d in json.loads(out)["dimensions"]} == DIMENSIONS


async def test_prose_pages_and_says_how_many_dimensions_it_did_not_show():
    lib = _lib()
    code, out, err = await run(lib, "lens", "--page-chars", "300")
    assert code == 0, err
    assert "of 6 dimensions" in out
    assert "--all-pages for everything" in out


# ──────────────────────────────────────────────────────────── it is only a read face


def test_the_lens_registers_no_component_and_no_setting():
    """§6: it reaches no compile task. Nothing registers a `lens` component, and there is no
    knob to bound readings nobody raises."""
    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.wiring import register_components

    assert not any("lens" in name for name in Settings.model_fields)
    with pytest.raises(ValueError):
        register_components(Settings(components="lens"), store=None, canonical=None)


# ────────────────────────── a reading over canonical needs no half of the deployment


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


def test_the_two_shape_commands_need_no_l2_half_of_the_deployment():
    """`NO_L2_GROUPS` for a whole family, `NO_L2_COMMANDS` for one subcommand of a family
    whose others do reach L2 — the same rule, asked of the parsed command."""
    parse = build_parser().parse_args
    assert not needs_semantic(parse(["lens"]))
    assert not needs_semantic(parse(["library", "review"]))
    assert needs_semantic(parse(["library", "check"]))


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
