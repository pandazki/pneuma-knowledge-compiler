"""The worker tenant filter against real Postgres — the claim query and the startup self-heal.

`PNEUMA_KNOWLEDGE_WORKER_TENANTS` (docs/design/single-machine-edition.md §11.7) is the
answer to two engine processes sharing one Postgres, one library each: each drains its own
tenant and neither touches the other's queue. The restriction is one predicate in the SQL
that hands a job out — never a claim followed by a release, which would already have spent
the neighbour's single in-flight slot — and the same predicate bounds the orphan sweep,
because another engine's claimed job is that engine's work in flight rather than an orphan.

Skips only when Postgres is unreachable (the `pg_store` fixture's own reason).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import requeue_orphaned_jobs


@pytest.fixture
def two_tenants() -> tuple[UserId, UserId]:
    """Two libraries on one store: this engine's tenant, and the neighbour's."""
    stamp = uuid.uuid4().hex[:10]
    return UserId(f"u-it-mine-{stamp}"), UserId(f"u-it-theirs-{stamp}")


async def _status(pg_store, user_id: UserId, job_id: str) -> str:
    jobs = await pg_store.list_jobs(user_id)
    return next(job["status"] for job in jobs if job["job_id"] == job_id)


async def test_the_claim_query_hands_out_only_the_named_tenants_job(pg_store, two_tenants):
    mine, theirs = two_tenants
    mine_job = await pg_store.enqueue(mine, "index", {"source_id": "src-mine"})
    theirs_job = await pg_store.enqueue(theirs, "index", {"source_id": "src-theirs"})

    assert await pg_store.claim_next(theirs, tenants=[str(mine)]) is None
    assert await _status(pg_store, theirs, theirs_job) == "queued"

    claimed = await pg_store.claim_next(mine, tenants=[str(mine)])
    assert claimed is not None and claimed.job_id == mine_job
    assert await _status(pg_store, mine, mine_job) == "claimed"
    # And the neighbour's row is untouched by that claim, not merely unclaimed by it.
    assert await _status(pg_store, theirs, theirs_job) == "queued"


async def test_an_empty_filter_claims_every_tenant_as_before(pg_store, two_tenants):
    mine, theirs = two_tenants
    mine_job = await pg_store.enqueue(mine, "index", {"source_id": "src-mine"})
    theirs_job = await pg_store.enqueue(theirs, "index", {"source_id": "src-theirs"})

    first = await pg_store.claim_next(mine)
    second = await pg_store.claim_next(theirs, tenants=[])
    assert {first.job_id, second.job_id} == {mine_job, theirs_job}


async def test_the_orphan_sweep_leaves_another_engines_claimed_job_alone(
    pg_store, two_tenants
):
    """A claimed job outside the filter is the other engine's round, not this one's orphan."""
    mine, theirs = two_tenants
    mine_job = await pg_store.enqueue(mine, "index", {"source_id": "src-mine"})
    theirs_job = await pg_store.enqueue(theirs, "index", {"source_id": "src-theirs"})
    assert await pg_store.claim_next(mine) is not None
    assert await pg_store.claim_next(theirs) is not None

    ctx = SimpleNamespace(
        store=pg_store,
        settings=Settings(worker_tenants=str(mine), recall_handoff_ttl=0),
    )
    assert await requeue_orphaned_jobs(ctx, label="test") == 1

    assert await _status(pg_store, mine, mine_job) == "queued"
    assert await _status(pg_store, theirs, theirs_job) == "claimed"

    # The pre-draft branch (`draft_ttl=0`) is bounded by the same predicate.
    assert await pg_store.claim_next(mine, tenants=[str(mine)]) is not None
    assert await pg_store.requeue_claimed_jobs(draft_ttl=0, tenants=[str(mine)]) == 1
    assert await _status(pg_store, mine, mine_job) == "queued"
    assert await _status(pg_store, theirs, theirs_job) == "claimed"
