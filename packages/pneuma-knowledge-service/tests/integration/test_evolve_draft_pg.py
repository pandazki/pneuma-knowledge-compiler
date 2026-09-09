"""The evolve door's lifecycle on the real queue and DraftStore, with real git branches."""

from pneuma_knowledge_service.cli import draft, evolve

from pneuma_knowledge_core.compile.patch import PatchDraft

from test_evolve_draft import A, B, make_runtime, propose, round_trip


async def test_evolve_door_round_trip_on_postgres(pg_store, user, tmp_path, monkeypatch):
    rt = await make_runtime(tmp_path, pg_store, user)
    await round_trip(rt, tmp_path, monkeypatch)


async def test_evolve_ttl_and_abandon_release_the_claim(pg_store, user, tmp_path):
    rt = await make_runtime(tmp_path, pg_store, user)
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(user))[0]
    await propose(rt, tmp_path)
    await pg_store.requeue_claimed_jobs(draft_ttl=3600)
    assert (await pg_store.get_job(user, job_id)).status == "claimed"
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE compile_drafts SET updated_at = now() - interval '2 hours' "
            "WHERE user_id = %s AND job_id = %s", (str(user), job_id),
        )
    await pg_store.requeue_claimed_jobs(draft_ttl=3600)
    assert await rt.drafts.get(user, job_id) is None
    assert (await pg_store.get_job(user, job_id)).status == "queued"
    assert await evolve.cmd_open(rt, job_id) == 0
    assert await draft.cmd_abandon(rt) == 0
    assert await rt.drafts.get(user, job_id) is None
    assert (await pg_store.get_job(user, job_id)).status == "queued"


async def test_evolve_refusals_and_budget_on_postgres(pg_store, user, tmp_path, monkeypatch):
    rt = await make_runtime(tmp_path, pg_store, user)
    rt.max_tool_calls = 3
    await evolve.cmd_open(rt, new=True)
    job_id = (await rt.drafts.list_open(user))[0]
    assert await propose(rt, tmp_path, {"packs": "invalid"}) == draft.EXIT_REFUSED
    assert await propose(rt, tmp_path) == 0
    before = await rt.drafts.get(user, job_id)
    original = PatchDraft.move_claim

    def drops_anchor(self, from_path, anchor_id, to_path, heading):
        result = original(self, from_path, anchor_id, to_path, heading)
        self.delete_claim(to_path, anchor_id)
        return result

    monkeypatch.setattr(PatchDraft, "move_claim", drops_anchor)
    assert await evolve.run_command(rt, "move-claim", from_path=A, anchor="aa11", to_path=B) == draft.EXIT_REFUSED
    after = await rt.drafts.get(user, job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == 3
    assert await propose(rt, tmp_path) == draft.EXIT_BUDGET
    assert await draft.cmd_abandon(rt) == 0


async def test_a_brief_only_fills_a_successful_version_and_never_replaces_one(pg_store, user):
    other = type(user)(str(user) + "-other")
    job_id = await pg_store.enqueue(user, "compile", {})
    await pg_store.record_compile_brief(user, job_id, "Too early", if_missing=True)
    await pg_store.complete(user, job_id, ok=True, snapshot_ref="synthetic-version")
    await pg_store.record_compile_brief(other, job_id, "Wrong tenant", if_missing=True)
    await pg_store.record_compile_brief(user, job_id, "The explicit Steward brief.", if_missing=True)
    await pg_store.record_compile_brief(user, job_id, "A later harness message", if_missing=True)
    async with pg_store._pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT brief FROM compile_jobs WHERE user_id = %s AND id = %s", (str(user), job_id)
        )).fetchone()
    assert row[0] == "The explicit Steward brief."
