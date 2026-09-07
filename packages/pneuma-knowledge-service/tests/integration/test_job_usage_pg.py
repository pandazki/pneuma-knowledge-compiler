"""`record_job_usage` against real Postgres — and why this test can only live here.

PG-TIER ON PURPOSE. The in-memory job queue (`adapters/draft_mock.py`) stores whatever it is
handed in a Python dict, so both bugs below are invisible to it and were invisible to the
whole keyless tier:

* `token_usage` was adapted as `json` while the column is `jsonb`. A direct assignment gets
  an assignment cast for free — which is why `complete()` always worked — but
  `coalesce(json, jsonb)` has no common type and raises at execution time. Every unattended
  agent compile therefore ended `ok = false` with `worker error: COALESCE could not convert
  type jsonb to json`, its executor and its usage never stored, and a drain that read that
  flag re-compiled the whole library on every run.
* a job can be completed TWICE — the round's own `pkc draft finish` writes the real record,
  and the worker's catch-all error path writes a second one if anything after it raises. The
  second caller knows neither the usage nor the executor, and an assignment there erased what
  the round had measured.

Both are properties of the SQL, so the assertion has to read the row back out of Postgres.
"""

from __future__ import annotations

import uuid

from pneuma_knowledge_core.domain.ids import UserId


async def _job(store, user: UserId) -> str:
    job_id = await store.enqueue(user, "compile", {"source_ids": ["s-1"]})
    claimed = await store.claim_next(user)
    assert claimed is not None and claimed.job_id == job_id
    return job_id


def _row(jobs: list[dict], job_id: str) -> dict:
    return next(j for j in jobs if j["job_id"] == job_id)


async def test_usage_and_executor_are_written_through_a_jsonb_coalesce(pg_store):
    """What the unattended launcher does, in order: the round's own finish writes the record,
    then the worker adds what the harness's counters said it cost."""
    user = UserId(f"u-it-usage-{uuid.uuid4().hex[:8]}")
    job_id = await _job(pg_store, user)

    await pg_store.complete(
        user, job_id, ok=True, detail='projection:{"upserted": 4}', snapshot_ref="c0ffee",
        executor="agent",
    )
    await pg_store.record_job_usage(
        user,
        job_id,
        token_usage={"input_tokens": 12000, "output_tokens": 900, "total_tokens": 12900},
        executor="agent:codex",
    )

    row = _row(await pg_store.list_jobs(user), job_id)
    assert row["ok"] is True
    assert row["executor"] == "agent:codex"
    assert row["token_usage"] == {
        "input_tokens": 12000,
        "output_tokens": 900,
        "total_tokens": 12900,
    }
    assert row["snapshot_ref"] == "c0ffee"


async def test_usage_alone_does_not_erase_the_executor_the_finish_recorded(pg_store):
    """The COALESCE the docstring promises, read back rather than trusted."""
    user = UserId(f"u-it-usage-{uuid.uuid4().hex[:8]}")
    job_id = await _job(pg_store, user)
    await pg_store.complete(user, job_id, ok=True, executor="agent")
    await pg_store.record_job_usage(user, job_id, token_usage={"input_tokens": 1})

    row = _row(await pg_store.list_jobs(user), job_id)
    assert row["executor"] == "agent"
    assert row["token_usage"] == {"input_tokens": 1}

    # And the mirror: an executor alone does not erase the usage.
    await pg_store.record_job_usage(user, job_id, executor="agent:codex")
    row = _row(await pg_store.list_jobs(user), job_id)
    assert row["executor"] == "agent:codex"
    assert row["token_usage"] == {"input_tokens": 1}


async def test_a_second_completion_does_not_erase_what_the_round_measured(pg_store):
    """The worker's error path calls `complete(ok=False, detail=…)` with no usage and no
    executor. It must record the failure and keep the measurement — the round really did
    commit, and the row is where an operator looks for what it cost."""
    user = UserId(f"u-it-usage-{uuid.uuid4().hex[:8]}")
    job_id = await _job(pg_store, user)
    await pg_store.complete(
        user,
        job_id,
        ok=True,
        detail='projection:{"upserted": 4}',
        snapshot_ref="c0ffee",
        token_usage={"input_tokens": 7},
        executor="agent:codex",
    )
    await pg_store.complete(user, job_id, ok=False, detail="worker error: something after")

    row = _row(await pg_store.list_jobs(user), job_id)
    assert row["ok"] is False and row["detail"].startswith("worker error:")
    assert row["executor"] == "agent:codex"
    assert row["token_usage"] == {"input_tokens": 7}


async def test_nothing_measured_stays_absent_rather_than_zero(pg_store):
    user = UserId(f"u-it-usage-{uuid.uuid4().hex[:8]}")
    job_id = await _job(pg_store, user)
    await pg_store.complete(user, job_id, ok=True, detail="indexed")
    await pg_store.record_job_usage(user, job_id, token_usage=None, executor=None)

    row = _row(await pg_store.list_jobs(user), job_id)
    # `list_jobs` renders an absent count as `{}`; what matters is that nothing invented a
    # zero — the column itself is NULL.
    assert row["token_usage"] == {}
    assert row["executor"] is None
