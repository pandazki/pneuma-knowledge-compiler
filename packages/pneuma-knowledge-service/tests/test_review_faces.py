"""Tier two — the check's faces, and the round that acts on it.

Three things are under test and they are deliberately separate. The READ faces (`GET
/…/review`, `pkc library review`) are one report assembled once in `service/lens.py`, so a
test that compares the route's body with the command's `--json` is testing the mechanism
rather than two renderings that happen to agree today. The ENQUEUE faces are the Owner's only
door to the round. And the ROUND itself is a coding-agent round on the canonical lane whose
task is that report — which is the claim that most needs a mechanical check, because a task
that silently dropped half the findings would tell the Steward the library was cleaner than
it is (docs/design/structure-lens.md §3).

Keyless throughout, over the same stand-in library the other `pkc` tests use. The check is
pure core and model-free, so there is nothing here to mock but the adapters.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.api.routes.v1 import router
from pneuma_knowledge_service.cli import build_parser, dispatch
from pneuma_knowledge_service.job_lanes import CANONICAL_LANE, JOB_LANES, lane_of
from pneuma_knowledge_service.lens import read_check
from pneuma_knowledge_service.review_service import (
    REVIEW_JOB_KIND,
    REVIEW_TASK_KEY,
    enqueue_review,
    render_check_task,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker

from _cli_library import USER, document, library  # noqa: E402

PAGE = "memory/topics/pricing.md"
OTHER = "memory/people/cheng-ye.md"


def _lib(**kw):
    """Two pages that cite a source and never link to each other — an ordinary small library,
    and one the navigability findings have something to say about."""
    return library(
        docs=[
            document(PAGE, "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n"),
            document(OTHER, "## 程野\n\n- 程野 leads backend. [cite: s-01 ¶0] <!-- c:bbb2 -->\n"),
        ],
        **kw,
    )


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


async def run(lib, *argv):
    """One `pkc …` invocation, parsed as the process parses it. `(exit, stdout, stderr)`."""
    args = build_parser().parse_args(["--user", str(USER), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(lib.ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _app(lib):
    app = FastAPI()
    app.state.ctx = lib.ctx
    app.include_router(router)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def get(lib, path: str):
    async with _app(lib) as client:
        return await client.get(path)


async def post(lib, path: str):
    async with _app(lib) as client:
        return await client.post(path)


# ─────────────────────────────────────────────────────────────────────────── the route


async def test_the_route_answers_the_report_shape_the_design_fixes():
    response = await get(_lib(), f"/v1/users/{USER}/review")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "ref", "read_at", "subjects", "files", "claims", "edges", "findings",
    }
    assert body["files"] == 2 and body["claims"] == 2
    for finding in body["findings"]:
        # §3.1: a finding says what it is about and what to do — every one of them, or the
        # report is back to being an instrument printing counts.
        assert finding["kind"] in {"judgement", "legacy"}
        assert finding["id"] and finding["key"]
        assert finding["impact"]["key"] and finding["action"]["key"]


async def test_the_route_always_names_the_commit_it_read():
    """HEAD is not a ref a reader can come back to: a report that left `ref` empty for the
    default read could not say which library it came out of."""
    lib = _lib(snapshots=[SnapshotRef(ref="c1"), SnapshotRef(ref="c0")])
    assert (await get(lib, f"/v1/users/{USER}/review")).json()["ref"] == "c1"
    at = (await get(lib, f"/v1/users/{USER}/review?at=c0")).json()
    assert at["ref"] == "c0"  # a named ref stays exactly as it was passed
    assert at["files"] == 2


async def test_a_library_with_no_history_names_no_commit_rather_than_inventing_one():
    lib = _lib(snapshots=[])
    assert (await get(lib, f"/v1/users/{USER}/review")).json()["ref"] == ""


async def test_an_empty_library_is_a_report_and_not_an_error():
    body = (await get(library(), f"/v1/users/{USER}/review")).json()
    assert body["files"] == 0 and body["claims"] == 0 and body["subjects"] == 0


async def test_the_report_is_a_function_of_the_ref_and_nothing_else():
    """Twice at the same ref → the same bytes, `read_at` aside. Nothing is stored, so a
    second read cannot see a first read's leftovers (§7)."""
    lib = _lib()
    first = (await get(lib, f"/v1/users/{USER}/review")).json()
    second = (await get(lib, f"/v1/users/{USER}/review")).json()
    first.pop("read_at"), second.pop("read_at")
    assert first == second


# ───────────────────────────────────────────────────────────────────────────── the CLI


async def test_pkc_library_review_prints_the_counts_and_every_finding():
    lib = _lib()
    report, _documents = await read_check(lib.ctx, USER)
    code, out, err = await run(lib, "library", "review", "--all-pages")
    assert code == 0, err
    assert f"{report.files} files" in out and f"{report.claims} claims" in out
    for finding in report.findings:
        assert finding.key in out, finding.key
        assert finding.id in out


async def test_pkc_library_review_json_is_the_report_the_route_serves():
    lib = _lib()
    code, out, _err = await run(lib, "library", "review", "--json", "--all-pages")
    assert code == 0
    command = json.loads(out)
    served = (await get(lib, f"/v1/users/{USER}/review")).json()
    command.pop("read_at"), served.pop("read_at")
    assert command == served


async def test_pkc_library_review_at_a_ref_reports_that_ref():
    code, out, _err = await run(
        _lib(), "library", "review", "--json", "--at", "c0", "--all-pages"
    )
    assert code == 0 and json.loads(out)["ref"] == "c0"


async def test_pkc_library_review_path_narrows_to_one_page():
    lib = _lib()
    report, _documents = await read_check(lib.ctx, USER)
    code, out, err = await run(
        lib, "library", "review", "--path", PAGE, "--json", "--all-pages"
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["path"] == PAGE
    keys = {finding["key"] for finding in payload["findings"]}
    assert keys == {f.key for f in report.findings if PAGE in f.paths}


async def test_pkc_library_review_refuses_to_call_a_page_the_library_lacks_clean():
    code, out, err = await run(_lib(), "library", "review", "--path", "memory/topics/nope.md")
    assert code == 1 and not out
    assert "no such page" in err


async def test_pkc_library_review_on_an_empty_library_says_so_and_exits_one():
    code, _out, err = await run(library(), "library", "review")
    assert code == 1
    assert "no canonical pages" in err


async def test_json_serialises_every_finding_however_small_the_page_is():
    """A caller cannot tell a page from a report, so the report is never a page."""
    lib = _many()
    report, _documents = await read_check(lib.ctx, USER)
    assert len(report.findings) > 10, "the fixture must not fit one page"
    code, out, err = await run(lib, "library", "review", "--json", "--page-chars", "400")
    assert code == 0, err
    payload = json.loads(out)
    assert [f["key"] for f in payload["findings"]] == [f.key for f in report.findings]


async def test_prose_pages_and_says_how_many_findings_it_did_not_show():
    """The other half of the same rule: prose may page — a reader asked for one page — but a
    page that stopped silently would make the same false claim the JSON one did."""
    lib = _many()
    report, _documents = await read_check(lib.ctx, USER)
    code, out, err = await run(lib, "library", "review", "--page-chars", "600")
    assert code == 0, err
    assert f"of {len(report.findings)} findings" in out
    assert "--page 2 for the next" in out
    assert f"{report.files} files" in out  # the counts ride every page, never paged away
    whole = (await run(lib, "library", "review", "--all-pages"))[1]
    for finding in report.findings:
        assert finding.key in whole
    assert "page 1/" not in whole


def test_the_lens_no_longer_answers_for_one_page():
    """The tier ruling, as a fact about the parser: a page-level finding belongs to the
    check, so `pkc lens --path` is gone rather than deprecated (§1)."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["lens", "--path", PAGE])


def test_the_command_reference_lists_both_faces_where_the_parser_renders_it():
    from pneuma_knowledge_service.coding_agent.skillpack import render_cli_md

    reference = render_cli_md(build_parser())
    assert "`pkc library review`" in reference
    assert "`pkc lens`" in reference
    assert "`pkc draft reorder-chronology`" in reference
    assert prompt("steward.cli.library_review") in reference


# ───────────────────────────────────────────────────────────── the round: its enqueue


def test_the_review_kind_is_in_the_canonical_lane():
    """It holds a draft over the whole library and commits through the gate, so it is the
    single writer for as long as it is open."""
    assert lane_of(REVIEW_JOB_KIND) == CANONICAL_LANE
    assert REVIEW_JOB_KIND in JOB_LANES


async def test_pkc_jobs_enqueue_review_queues_one_round():
    lib = _lib()
    code, out, err = await run(lib, "jobs", "enqueue", "review")
    assert code == 0, err
    rows = await lib.store.list_jobs(USER)
    assert [row["kind"] for row in rows] == [REVIEW_JOB_KIND]
    assert rows[0]["job_id"] in out


async def test_the_enqueue_route_queues_the_same_round():
    lib = _lib()
    response = await post(lib, f"/v1/users/{USER}/jobs/review")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == REVIEW_JOB_KIND
    rows = await lib.store.list_jobs(USER)
    assert [row["job_id"] for row in rows] == [body["job_id"]]


def test_nothing_but_the_owner_enqueues_a_review():
    """§3.2: scheduling it is a later decision. A version that had started scheduling it
    would have a caller of `enqueue_review` somewhere in the worker; it has none."""
    import inspect

    assert "enqueue_review" not in inspect.getsource(compile_worker)


# ───────────────────────────────────────────────────── the round: what the Steward reads


async def test_the_round_task_carries_the_report_and_the_one_instruction():
    lib = _many()
    report, _documents = await read_check(lib.ctx, USER)
    assert report.findings, "the fixture must give the round something to be about"
    task = render_check_task(report, bound=0)
    for finding in report.findings:
        assert finding.key in task
    # ONE catalog sentence-set, verbatim — not a briefing composed at the call site.
    assert prompt(REVIEW_TASK_KEY).strip("\n") in task
    # The report first and the instruction after it: the instruction is written about the
    # report, and a reader meets the subject before the thing said about it.
    assert task.index(report.findings[0].key) < task.index(prompt(REVIEW_TASK_KEY).strip("\n"))


async def test_the_round_task_is_bounded_and_says_what_it_left_out():
    """A library of three hundred findings must not hand a harness a task the size of its own
    library — and what is cut is stated in FINDINGS, because a task that stopped silently
    would tell the round the library was cleaner than it is."""
    lib = _many()
    report, _documents = await read_check(lib.ctx, USER)
    bounded = render_check_task(report, bound=900)
    assert len(bounded) < len(render_check_task(report, bound=0))
    assert "more finding(s) not shown" in bounded
    assert prompt(REVIEW_TASK_KEY).strip("\n") in bounded  # the instruction is never cut


async def test_the_task_is_computed_when_the_round_opens_not_when_it_is_queued():
    """A review job may sit behind a compile that repairs half of what the check found. A
    task frozen at enqueue would send the round after findings that no longer exist, so the
    queued row carries no task at all."""
    lib = _lib()
    job_id = await enqueue_review(lib.ctx, USER)
    row = next(r for r in await lib.store.list_jobs(USER) if r["job_id"] == job_id)
    assert not (row.get("payload") or {})


# ──────────────────────────────────────────────────────── the round: how it is dispatched


class _Ctx:
    """The two things a drain reads from its context, and nothing else."""

    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        from pneuma_knowledge_service.wiring import executor_for

        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


def _settings(**over) -> Settings:
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
        "agent_unattended": True,
    }
    return Settings(**{**base, **over})


async def _drain(config: Settings, monkeypatch):
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, REVIEW_JOB_KIND, {})
    launched: list[str] = []

    async def fake_agent_job(ctx, user_id, job):  # noqa: ANN001
        launched.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="reviewed")

    monkeypatch.setattr(compile_worker, "process_agent_job", fake_agent_job)
    ctx = _Ctx(config, jobs)
    await compile_worker.drain_user(ctx, None, SimpleNamespace(), UserId(str(USER)))
    return jobs, job_id, launched


async def test_a_review_job_is_dispatched_to_a_coding_agent_round(monkeypatch):
    """Not to `process_job`: the round's body is a Steward typing `pkc draft` commands
    against the check's report, and there is no source for a compile to compile."""
    jobs, job_id, launched = await _drain(
        _settings(llm_model_compile="agent:codex"), monkeypatch
    )
    assert launched == [job_id]
    assert (await jobs.get_job(USER, job_id)).status == "done"


async def test_under_a_model_executor_the_review_round_is_skipped_and_says_so(monkeypatch):
    """`run_compile` composes its round out of SOURCES and this round has none, so a model
    executor is told the job was skipped rather than handed a round it cannot run."""
    jobs, job_id, launched = await _drain(_settings(), monkeypatch)
    assert launched == []
    assert (await jobs.get_job(USER, job_id)).status == "done"
    completed = next(row for row in jobs.completed if row["job_id"] == job_id)
    assert completed["ok"] and "not a coding agent" in (completed["detail"] or "")


def test_the_review_round_is_finished_by_the_ordinary_gate():
    """No second rulebook: its OPEN is its own (the task is a report, not a source), and its
    FINISH is `cli/draft.py`'s — the same predicates judging the same kind of draft."""
    import inspect

    from pneuma_knowledge_service.cli import review as review_cli
    from pneuma_knowledge_service.coding_agent import round_runner

    assert not hasattr(review_cli, "cmd_finish")
    body = inspect.getsource(round_runner.AgentRoundRunner._run_owned_job)
    assert 'elif rt.kind == "review"' in body
    assert "from ..cli.review import open_round as open_draft" in body
