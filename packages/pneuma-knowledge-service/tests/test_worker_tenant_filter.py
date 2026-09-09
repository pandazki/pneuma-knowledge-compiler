"""WHICH tenants a worker drains — `PNEUMA_KNOWLEDGE_WORKER_TENANTS`.

One Postgres can carry more than one library, and a library is a tenant
(docs/design/single-machine-edition.md §11.7): each library's engine process registers its
own compile contract, so a worker that claimed a neighbour's job would compile that
knowledge under the wrong contract. Empty is every tenant — what a single worker over a
single stack has always been.

Keyless: the queue is the in-memory one and both job bodies are stubbed, because what is
under test is the claim decision and not what a job does once claimed. The same restriction
against real Postgres is `tests/integration/test_worker_tenant_filter.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import executor_for
from pneuma_knowledge_service.workers import compile_worker

MINE = UserId("u-tenant-mine")
THEIRS = UserId("u-tenant-theirs")


def settings(**kwargs) -> Settings:
    """Every model role stated, so a deployment's `.env` cannot decide a test."""
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
    }
    return Settings(**{**base, **kwargs})


class WorkerCtx:
    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


# ─────────────────────────────────────────────────────────────── the setting reads as a list


def test_an_unset_filter_is_every_tenant():
    assert settings().worker_tenant_ids() == ()
    assert settings(worker_tenants="  ").worker_tenant_ids() == ()


def test_the_filter_drops_blanks_and_repeats_and_keeps_what_was_written():
    parsed = settings(worker_tenants=" alice , bob ,, alice ").worker_tenant_ids()
    assert parsed == ("alice", "bob")


# ─────────────────────────────────────────────────────────── the sweep looks at its own only


async def test_the_sweep_asks_about_its_own_tenants_and_never_enumerates_the_store():
    """With a filter, the tenants ARE the answer — a store lookup would only add the rest."""

    class RefusingStore:
        async def list_users(self):  # noqa: ANN001
            raise AssertionError("a filtered worker must not enumerate the store's tenants")

    ctx = SimpleNamespace(settings=settings(worker_tenants="u-b,u-a"), store=RefusingStore())
    assert await compile_worker._users_with_jobs(ctx) == ["u-a", "u-b"]


async def test_without_a_filter_the_sweep_enumerates_as_it_always_did():
    class Store:
        async def list_users(self):  # noqa: ANN001
            return ["u-a", "u-b"]

    ctx = SimpleNamespace(settings=settings(), store=Store())
    assert await compile_worker._users_with_jobs(ctx) == ["u-a", "u-b"]


# ────────────────────────────────────────────────────────── the drain claims its own only


async def test_a_filtered_worker_claims_its_tenants_job_and_leaves_the_others_queued(
    monkeypatch,
):
    """Not claimed-and-released: the neighbour's row is never handed out at all.

    Releasing would have spent that tenant's single in-flight slot for as long as the round
    took, and everything queued behind it would have waited on this process."""
    jobs = InMemoryJobQueue()
    mine = await jobs.enqueue(MINE, "index", {"source_id": "src-mine"})
    theirs = await jobs.enqueue(THEIRS, "index", {"source_id": "src-theirs"})
    ran: list[str] = []

    async def fake_index(ctx, user_id, job):  # noqa: ANN001
        ran.append(f"{user_id}:{job.job_id}")
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", fake_index)
    ctx = WorkerCtx(settings(worker_tenants=str(MINE)), jobs)

    assert await compile_worker.drain_user(ctx, None, None, MINE) == 1
    assert await compile_worker.drain_user(ctx, None, None, THEIRS) == 0

    assert ran == [f"{MINE}:{mine}"]
    assert (await jobs.get_job(MINE, mine)).status == "done"
    held = await jobs.get_job(THEIRS, theirs)
    assert held.status == "queued"
    assert not hasattr(held, "claimed_by")


async def test_an_empty_filter_drains_both_tenants_as_before(monkeypatch):
    jobs = InMemoryJobQueue()
    mine = await jobs.enqueue(MINE, "index", {"source_id": "src-mine"})
    theirs = await jobs.enqueue(THEIRS, "index", {"source_id": "src-theirs"})

    async def fake_index(ctx, user_id, job):  # noqa: ANN001
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", fake_index)
    ctx = WorkerCtx(settings(), jobs)

    assert await compile_worker.drain_user(ctx, None, None, MINE) == 1
    assert await compile_worker.drain_user(ctx, None, None, THEIRS) == 1
    assert (await jobs.get_job(MINE, mine)).status == "done"
    assert (await jobs.get_job(THEIRS, theirs)).status == "done"
