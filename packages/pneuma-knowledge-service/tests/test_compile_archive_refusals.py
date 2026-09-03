"""What one compile RUN cost and refused, as the job's completion detail says it.

Two facts the outcome's own detail cannot carry, both assembled by `_with_run_facts`:

- `rounds:<n>` — one round, or two because the first failed the gate and the repair round
  ran. On every branch, `aborted` included: a repair that ran and still could not pass is
  the most expensive shape a compile has, and it is indistinguishable from a one-round abort
  unless the number is written down.
- `archive_refusals:[…]` — new material came in about a subject the owner RETIRED
  (docs/design/archive.md §2.1, finding O3). Not a compile event: events are derived from
  the file diff, and a refusal wrote no file — so it travels on the compile result and into
  the `detail` column, which is what `GET /jobs` shows.

Keyless and middleware-free: `process_job` runs over fakes with `run_compile` itself
stubbed, so what is under test is the worker's own assembly of the detail and nothing about
the model.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.compile.runner import CompileResult
from pneuma_knowledge_core.domain.ids import UserId

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker
from pneuma_knowledge_service.workers.compile_worker import process_job

USER = UserId("u-archive-refusal")

REFUSALS = [
    {
        "kind": "title",
        "path": "threads/small-scale-invitation.md",
        "archived": "archive/threads/small-group-invitation.md",
        "title": "小范围邀请与首次成功",
    }
]


class _Store:
    def __init__(self) -> None:
        self.completed: list[dict] = []
        self.digested: list[tuple] = []

    async def block_counts(self, user_id):
        return {}

    async def mark_digested(self, user_id, source_ids, now):
        self.digested.append((user_id, list(source_ids), now))

    async def complete(self, user_id, job_id, *, ok, detail, token_usage=None, **kw):
        self.completed.append({"job_id": job_id, "ok": ok, "detail": detail})


class _Canonical:
    async def snapshots_page(self, user_id, *, limit=1):
        # No snapshot at all: the noop branch stays off the projection path, which is a
        # different mechanism with its own tests.
        return [], None, None


class _UserInfo:
    async def get_profile(self, user_id):
        return None


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        settings=Settings(),
        store=_Store(),
        canonical=_Canonical(),
        user_info=_UserInfo(),
        lexical=None,
        media=None,
        langfuse_handler=lambda: None,
        get_chat_model=lambda role: None,
    )


def _result(status: str, **kw) -> CompileResult:
    return CompileResult(
        status=status,
        files={},
        events=[],
        violations=kw.pop("violations", []),
        rounds=kw.pop("rounds", 1),
        tool_calls=1,
        token_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        archive_refusals=kw.pop("archive_refusals", []),
    )


async def _run(monkeypatch, result: CompileResult) -> dict:
    ctx = _ctx()

    async def fake_run_compile(**kwargs):
        return result

    monkeypatch.setattr(compile_worker, "run_compile", fake_run_compile)
    monkeypatch.setattr(compile_worker, "maybe_trigger_evolve", _noop)
    job = SimpleNamespace(job_id="job-1", payload={"source_ids": []})
    await process_job(ctx, None, _skill(), USER, job)
    return ctx.store.completed[0]


async def _noop(*args, **kwargs):
    return None


def _skill():
    from pneuma_knowledge_core.skill import load_skill_base

    return load_skill_base("v1")


async def test_the_job_detail_names_the_archived_subject_the_round_went_looking_for(
    monkeypatch,
):
    done = await _run(monkeypatch, _result("noop", archive_refusals=REFUSALS))
    assert done["ok"] is True
    head, rounds, rendered = done["detail"].split("; ")
    # The outcome's own detail is untouched and comes first; the run facts are appended.
    assert head == "noop"
    assert rounds == "rounds:1"
    assert rendered.startswith("archive_refusals:")
    assert json.loads(rendered.removeprefix("archive_refusals:")) == REFUSALS
    # Readable as written: the subject's name is not escaped into codepoints.
    assert "小范围邀请与首次成功" in rendered


async def test_an_aborted_round_reports_its_refusals_beside_its_violations(monkeypatch):
    result = _result(
        "aborted",
        violations=[Violation("citation", "memory/topics/x.md", "no such source")],
        archive_refusals=REFUSALS,
    )
    done = await _run(monkeypatch, result)
    assert done["ok"] is False
    assert done["detail"].startswith("[citation] memory/topics/x.md: no such source; ")
    assert "archive_refusals:" in done["detail"]


async def test_a_compile_that_hit_no_archive_says_only_what_the_round_cost(monkeypatch):
    """The refusal field is invisible to a library that has never archived anything; the
    round count is not, because every compile has one."""
    done = await _run(monkeypatch, _result("noop"))
    assert done["detail"] == "noop; rounds:1"


async def test_a_repair_round_is_visible_on_every_branch_including_an_abort(monkeypatch):
    """Two rounds and still aborted is the most expensive shape a compile has — and next to
    a one-round abort it is invisible unless the number rides the detail."""
    aborted = await _run(
        monkeypatch,
        _result(
            "aborted",
            rounds=2,
            violations=[Violation("citation", "memory/topics/x.md", "no such source")],
        ),
    )
    assert aborted["ok"] is False
    assert aborted["detail"].endswith("; rounds:2")

    noop = await _run(monkeypatch, _result("noop", rounds=2))
    assert noop["detail"] == "noop; rounds:2"
