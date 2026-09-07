"""The draft's home in Postgres, and the queue rules a held round depends on.

The keyless suite proves the `pkc draft` lifecycle against the in-memory stand-ins; this is
the same set of claims against real SQL — the named claim under the per-user lock, the release
that puts a job back undecided, and the self-heal that must not reclaim a job an agent is
still holding.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pneuma_knowledge_service.adapters.postgres import PostgresDraftStore


async def _age(pg_store, user, job_id: str, *, seconds: int) -> None:
    """Backdate one draft's `updated_at` by `seconds`."""
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_drafts SET updated_at = now() - make_interval(secs => %s) "
            "WHERE user_id = %s AND job_id = %s",
            (float(seconds), str(user), job_id),
        )


async def test_a_draft_round_trips_and_is_found_as_this_users_open_round(pg_store, user):
    drafts = PostgresDraftStore(pg_store)
    job_id = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-1"]})

    assert await drafts.get(user, job_id) is None
    assert await drafts.list_open(user) == []

    state = {"draft": {"path_templates": ["memory/people/{slug}.md"]}, "session": {"round": "first"}}
    await drafts.put(user, job_id, state)
    assert await drafts.get(user, job_id) == state
    assert await drafts.list_open(user) == [job_id]

    await drafts.put(user, job_id, {"draft": {}, "session": {"round": "repair"}})
    assert (await drafts.get(user, job_id))["session"]["round"] == "repair"

    await drafts.delete(user, job_id)
    assert await drafts.get(user, job_id) is None
    assert await drafts.list_open(user) == []
    await drafts.delete(user, job_id)  # idempotent


async def test_claim_takes_one_named_job_under_the_same_per_user_lock(pg_store, user):
    first = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-1"]})
    second = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-2"]})

    # The named claim takes the SECOND job — a body told which job to work on is not served
    # whatever is oldest.
    held = await pg_store.claim(user, second, claimed_by="draft")
    assert held is not None and held.job_id == second

    # …and while it is held, the user's queue hands out nothing else, to anybody.
    assert await pg_store.claim_next(user) is None
    assert await pg_store.claim(user, first, claimed_by="draft") is None

    await pg_store.release(user, second)
    assert (await pg_store.get_job(user, second)).status == "queued"
    taken = await pg_store.claim_next(user)
    assert taken is not None and taken.job_id == first


async def test_the_self_heal_leaves_a_held_round_alone_and_reclaims_an_abandoned_one(
    pg_store, user
):
    drafts = PostgresDraftStore(pg_store)
    live = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-1"]})
    await pg_store.claim(user, live, claimed_by="draft")
    await drafts.put(user, live, {"draft": {}, "session": {"round": "first"}})

    # A fresh draft is an agent still working: the job stays claimed.
    await pg_store.requeue_claimed_jobs(draft_ttl=3600)
    assert (await pg_store.get_job(user, live)).status == "claimed"
    assert await drafts.get(user, live) is not None

    # Age the row rather than sleeping through the TTL: what is under test is the rule, and
    # `updated_at` is the whole of the liveness signal it reads.
    await _age(pg_store, user, live, seconds=7200)
    assert (str(user), live) in await drafts.list_stale(
        datetime.now(timezone.utc) - timedelta(seconds=60)
    )

    # Past the TTL the draft is deleted and the job goes back to the queue — the same
    # outcome a worker killed mid-job gets, and no canonical write either way.
    await pg_store.requeue_claimed_jobs(draft_ttl=3600)
    assert await drafts.get(user, live) is None
    assert (await pg_store.get_job(user, live)).status == "queued"


async def test_without_a_ttl_the_self_heal_behaves_as_it_did_before_drafts_existed(
    pg_store, user
):
    drafts = PostgresDraftStore(pg_store)
    job_id = await pg_store.enqueue(user, "compile", {"source_ids": ["sid-1"]})
    await pg_store.claim(user, job_id, claimed_by="draft")
    await drafts.put(user, job_id, {"draft": {}, "session": {}})

    await pg_store.requeue_claimed_jobs()
    assert (await pg_store.get_job(user, job_id)).status == "queued"
    await drafts.delete(user, job_id)
