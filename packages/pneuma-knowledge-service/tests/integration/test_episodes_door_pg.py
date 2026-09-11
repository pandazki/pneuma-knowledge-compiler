"""The episodes door against the real Postgres claim, draft, manifest and Qdrant points."""

import pytest

from pneuma_knowledge_service.cli import draft, episodes
from test_episodes_door import PROPOSAL, make_runtime, open_job, propose, round_trip


@pytest.mark.parametrize("proposal", [PROPOSAL, []])
async def test_episodes_pg_qdrant_rebuild_round_trip(pg_store, qdrant, meili, user, tmp_path, monkeypatch, proposal):
    rt = await make_runtime(tmp_path, store=pg_store, vectors=qdrant, lexical=meili, user=user)
    await round_trip(rt, tmp_path, monkeypatch, proposal)


async def test_episodes_pg_windows_compose_rebuild_and_claim_in_order(pg_store, qdrant, meili, user, tmp_path, monkeypatch):
    """Window records in `chunk_manifest_windows`, composed and replayed over real PG +
    Qdrant; windowed jobs that share one inherited place are claimed in write order."""
    from datetime import datetime, timedelta, timezone

    from test_episodes_windows import windowed_round_trip

    rt = await make_runtime(tmp_path, store=pg_store, vectors=qdrant, lexical=meili, user=user)
    await windowed_round_trip(rt, tmp_path, monkeypatch)
    place = datetime.now(timezone.utc) - timedelta(days=1)
    written = [
        await pg_store.enqueue(user, "episodes", {"source_id": "s-order", "window": {"start": n, "end": n}}, order_at=place)
        for n in range(4)
    ]
    claimed = []
    while (job := await pg_store.claim_next(user)) is not None:
        claimed.append(job.job_id)
        await pg_store.complete(user, job.job_id, ok=True, detail="synthetic")
    assert claimed == written


async def test_episodes_pg_refusal_ttl_and_abandon(pg_store, qdrant, user, tmp_path):
    rt = await make_runtime(tmp_path, store=pg_store, vectors=qdrant, user=user)
    job = await open_job(rt)
    assert await propose(rt, tmp_path, [{**PROPOSAL[0], "title": ""}]) == draft.EXIT_REFUSED
    assert await propose(rt, tmp_path) == 0
    assert await pg_store.requeue_claimed_jobs(draft_ttl=3600, tenants=(str(user),)) == 0
    assert (await pg_store.get_job(user, job)).status == "claimed"
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_drafts SET updated_at = now() - interval '2 hours' "
            "WHERE user_id = %s AND job_id = %s", (str(user), job),
        )
    assert await pg_store.requeue_claimed_jobs(draft_ttl=3600, tenants=(str(user),)) == 1
    assert await rt.drafts.get(user, job) is None
    assert await episodes.cmd_open(rt, job) == 0
    assert await draft.cmd_abandon(rt) == 0
    assert (await pg_store.get_job(user, job)).status == "queued"
