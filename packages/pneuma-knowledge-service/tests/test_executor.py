"""Who runs a compile round, and what follows from the answer.

`agent:<backend>` is a model spec that names an EXECUTOR rather than a model
(docs/design/coding-agent-mode.md ruling 1): it resolves through the same routing table, it
is refused wherever a chat model would be built from it, and it changes exactly two
behaviours — the worker leaves compile jobs in the queue for the Steward, and a finished job
says which body typed its calls.

Keyless throughout: `executor_for` is pure over Settings, and the drain runs against the
in-memory queue with the two job bodies stubbed out. What is under test is the claim
decision, not what a compile or an index job does once claimed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import (
    build_chat_model_for,
    check_executors,
    executor_for,
    resolve_model_name,
    usable_model_name,
)
from pneuma_knowledge_service.workers import compile_worker

USER = UserId("u-exec-1")


def settings(**kwargs) -> Settings:
    """Settings with every role stated, so a deployment's `.env` cannot decide a test.

    Each role is given a plain model by default; a test that wants an `agent:` spec somewhere
    names that role itself.
    """
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_recall": "openrouter:x/recall",
        "llm_model_answer": "",
        "llm_model_deep": "openrouter:x/deep",
        "llm_model_skill": "openrouter:x/skill",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
        "llm_model_live_context": "openrouter:x/live",
        "llm_model_live_discover": "openrouter:x/live",
        "llm_model_live_pick": "openrouter:x/live",
    }
    return Settings(**{**base, **kwargs})


# ───────────────────────────────────────────────────────────── the spec resolves as a spec


def test_an_ordinary_spec_is_a_langchain_executor():
    executor = executor_for(settings(), "compile")
    assert executor.kind == "langchain"
    assert executor.spec == "openrouter:x/compile"
    assert executor.backend is None
    assert not executor.is_agent


def test_the_compile_role_may_name_a_coding_agent():
    executor = executor_for(settings(llm_model_compile="agent:codex"), "compile")
    assert executor.kind == "agent"
    assert executor.spec == "agent:codex"
    assert executor.backend == "codex"
    assert executor.is_agent
    # The spec travels unchanged through the routing table it shares with every model spec —
    # which is what makes switching executors one edit in `engine.yaml`.
    assert resolve_model_name(settings(llm_model_compile="agent:codex"), "compile") == (
        "agent:codex"
    )


def test_claude_code_is_the_other_shipped_backend():
    assert executor_for(
        settings(llm_model_compile="agent:claude-code"), "compile"
    ).backend == "claude-code"


def test_an_unknown_backend_fails_and_names_it():
    with pytest.raises(ValueError) as err:
        executor_for(settings(llm_model_compile="agent:kimi"), "compile")
    assert "kimi" in str(err.value)


@pytest.mark.parametrize(
    "role, field",
    [
        ("recall", "llm_model_recall"),
        ("answer", "llm_model_answer"),
        ("deep", "llm_model_deep"),
        ("evolve", "llm_model_evolve"),
        ("skill", "llm_model_skill"),
    ],
)
def test_only_compile_may_run_on_an_agent_and_the_refusal_names_the_role(role, field):
    with pytest.raises(ValueError) as err:
        executor_for(settings(**{field: "agent:codex"}), role)
    assert role in str(err.value)


def test_a_role_that_would_borrow_compiles_agent_spec_falls_to_the_base_model():
    """`evolve`, `challenge` and `brief` have no field of their own by default: they borrow
    compile's (`_ROLE_FALLBACK`). Pointing compile at a coding agent must not strand them, so
    the borrowed `agent:` spec is skipped and the chain lands on the base model — a deployment
    that states one line (`compile: agent:codex`) keeps every other role running as before."""
    config = settings(
        llm_model="openrouter:x/base",
        llm_model_compile="agent:codex",
        llm_model_evolve="",
        llm_model_challenge="",
        llm_model_brief="",
    )
    check_executors(config)
    for role in ("evolve", "challenge", "brief"):
        assert resolve_model_name(config, role) == "openrouter:x/base"
        assert executor_for(config, role).kind == "langchain"
    # compile itself still resolves to the agent.
    assert executor_for(config, "compile").kind == "agent"
    # …and a role that STATES the agent in its own field is still refused by name.
    with pytest.raises(ValueError) as err:
        executor_for(settings(llm_model_evolve="agent:codex"), "evolve")
    assert "evolve" in str(err.value)


def test_a_base_model_may_not_be_an_agent():
    with pytest.raises(ValueError) as err:
        check_executors(settings(llm_model="agent:codex"))
    assert "default" in str(err.value)


def test_a_scripted_base_model_still_overrides_every_role():
    """The keyless discipline is untouched: `scripted:` hard-overrides routing, so a
    deployment that names an agent for compile AND runs a scripted base model is a scripted
    run, all the way down. This is what keeps the default suite keyless."""
    config = settings(llm_model="scripted:/nowhere.json", llm_model_compile="agent:codex")
    executor = executor_for(config, "compile")
    assert executor.kind == "langchain"
    assert executor.spec == "scripted:/nowhere.json"
    check_executors(config)


# ─────────────────────────────────────────────────────── an executor is not a chat model


def test_building_a_chat_model_from_an_agent_spec_is_refused():
    with pytest.raises(RuntimeError) as err:
        build_chat_model_for(settings(llm_model_compile="agent:codex"), "compile")
    assert "executor" in str(err.value)


def test_an_agent_spec_is_not_a_model_this_process_can_run():
    """`usable_model_name` is what every dispatch point asks before it builds a model — the
    semantic chunker above all. An agent answers no, so chunking degrades to the mechanical
    sentence path exactly as it does for a keyless deployment (§3.1)."""
    # A plain provider spec, so the keyless-openrouter rule is not what is under test here.
    assert usable_model_name(settings(llm_model_compile="agent:codex"), "compile") == ""
    assert usable_model_name(
        settings(llm_model_compile="openai:gpt-x"), "compile"
    ) == "openai:gpt-x"


# ─────────────────────────────────────────────────────────────────── the worker's decision


class FakeCtx:
    """The two things a drain reads from its context, and nothing else."""

    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


async def _drain(config: Settings, monkeypatch) -> tuple[InMemoryJobQueue, list[str]]:
    """One drain over a queue holding a compile job and, behind it, an index job."""
    jobs = InMemoryJobQueue()
    compile_job = await jobs.enqueue(USER, "compile", {"source_ids": ["src-01"]})
    index_job = await jobs.enqueue(USER, "index", {"source_id": "src-02"})
    ran: list[str] = []

    async def fake_index(ctx, user_id, job):  # noqa: ANN001
        ran.append(f"index:{job.job_id}")
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    async def fake_compile(ctx, model, skill, user_id, job):  # noqa: ANN001
        ran.append(f"compile:{job.job_id}")
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="committed")

    monkeypatch.setattr(compile_worker, "process_index_job", fake_index)
    monkeypatch.setattr(compile_worker, "process_job", fake_compile)
    ctx = FakeCtx(config, jobs)
    # A skill is passed rather than resolved: `_resolve_user_skill` would read the user's
    # manifest out of git, and what is under test here is which job gets claimed.
    processed = await compile_worker.drain_user(ctx, None, SimpleNamespace(), USER)
    assert processed == len(ran)
    return jobs, [compile_job, index_job], ran


def agent_settings(**kwargs) -> Settings:
    """A deployment whose compile role is a coding agent, with every borrowing role pinned.

    `agent_unattended=False` by default here: these are the INTERACTIVE posture's tests — the
    Owner drives the harness, and the worker's part is to leave the compile jobs alone. The
    unattended posture (the worker launching the harness itself) is the default in production
    and is exercised in `test_agent_round.py`.
    """
    base = {
        "llm_model_compile": "agent:codex",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
        "agent_unattended": False,
    }
    return settings(**{**base, **kwargs})


async def test_under_an_agent_executor_a_compile_job_waits_and_the_work_behind_it_does_not(
    monkeypatch,
):
    """The queue is per-user serial, so "skip it" has to happen at the CLAIM.

    Claiming the compile job and putting it back would still have spent this user's single
    in-flight slot; the index job behind it would then wait on a round this process is never
    going to run. So the drain claims the oldest job that is NOT a compile, and the compile
    job stays exactly as it was — queued, and openable by `pkc draft open`.
    """
    jobs, (compile_job, index_job), ran = await _drain(agent_settings(), monkeypatch)
    assert ran == [f"index:{index_job}"]
    held = await jobs.get_job(USER, compile_job)
    assert held.status == "queued"
    assert not hasattr(held, "claimed_by")


async def test_under_a_model_executor_the_worker_drains_everything_as_before(monkeypatch):
    jobs, (compile_job, index_job), ran = await _drain(settings(), monkeypatch)
    assert ran == [f"compile:{compile_job}", f"index:{index_job}"]
    assert (await jobs.get_job(USER, compile_job)).status == "done"


async def test_the_waiting_jobs_are_reported_once_for_the_user_not_once_per_job(
    monkeypatch, caplog
):
    jobs = InMemoryJobQueue()
    for _ in range(3):
        await jobs.enqueue(USER, "compile", {"source_ids": ["src-01"]})
    ctx = FakeCtx(agent_settings(), jobs)
    with caplog.at_level("INFO", logger=compile_worker.log.name):
        assert await compile_worker.drain_user(ctx, None, SimpleNamespace(), USER) == 0
    waiting = [r for r in caplog.records if "waiting for the Steward" in r.getMessage()]
    assert len(waiting) == 1
    assert "3 compile job(s)" in waiting[0].getMessage()


# ─────────────────────────────────────────────────────────────── what the job record says


def test_the_worker_labels_a_job_with_the_model_that_ran_it():
    assert compile_worker.langchain_executor(settings()) == (
        "langchain:openrouter:x/compile"
    )


def test_the_cli_labels_a_job_with_the_harness_that_ran_it():
    assert compile_worker.agent_executor(settings(executor_backend="codex")) == (
        "agent:codex"
    )


def test_an_owners_own_terminal_session_names_no_harness():
    """Nothing set the backend, so the record says `agent` and stops there — the true
    statement. A guess would be worse than the shorter fact."""
    assert compile_worker.agent_executor(settings()) == "agent"


# ────────────────────────────────────────────────────── who the queue is waiting for


class _JobStore:
    """Just enough of `PostgresStore` for `GET /jobs`: one page of rows."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def list_jobs_page(self, user_id, *, limit, before=None, status=None, kind=None):  # noqa: ANN001
        return list(self.rows), len(self.rows), False


def _rows() -> list[dict]:
    made = datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc)
    common = {
        "payload": {"source_ids": ["src-01"]},
        "created_at": made,
        "claimed_at": None,
        "completed_at": None,
        "ok": None,
        "detail": None,
        "snapshot_ref": None,
        "token_usage": {},
        "executor": None,
    }
    return [
        {"job_id": "j-compile", "kind": "compile", "status": "queued", **common},
        {"job_id": "j-index", "kind": "index", "status": "queued", **common},
        {
            "job_id": "j-done",
            "kind": "compile",
            "status": "done",
            **{
                **common,
                "ok": True,
                "completed_at": made,
                "executor": "langchain:openrouter:x/compile",
            },
        },
    ]


def _client(config: Settings) -> httpx.AsyncClient:
    from pneuma_knowledge_service.api.app import create_app

    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=_JobStore(_rows()),
        settings=config,
        compile_executor=executor_for(config, "compile"),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _jobs(config: Settings) -> dict[str, dict]:
    async with _client(config) as client:
        response = await client.get(f"/v1/users/{USER}/jobs")
    assert response.status_code == 200, response.text
    return {item["job_id"]: item for item in response.json()["items"]}


async def test_a_queued_compile_job_waits_for_the_steward_under_an_agent_executor():
    """Story 2.24: the process view must be able to say WHO is expected to act.

    A queued compile job under an agent executor is not a stalled worker — it is work
    addressed to the Owner's coding agent. Everything else in the queue is still the
    worker's, and a job that has left the queue is nobody's.
    """
    items = await _jobs(agent_settings())
    assert items["j-compile"]["waiting_for"] == "steward"
    assert items["j-index"]["waiting_for"] == "worker"
    assert items["j-done"]["waiting_for"] is None


async def test_under_a_model_executor_every_queued_job_waits_for_the_worker():
    items = await _jobs(settings())
    assert items["j-compile"]["waiting_for"] == "worker"
    assert items["j-index"]["waiting_for"] == "worker"


async def test_a_finished_job_reports_the_executor_that_ran_it():
    items = await _jobs(settings())
    assert items["j-done"]["executor"] == "langchain:openrouter:x/compile"
    assert items["j-compile"]["executor"] is None
