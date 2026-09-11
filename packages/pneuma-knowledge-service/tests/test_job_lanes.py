"""Two lanes drain one library at once, and the canonical writer is still one.

A library's queue used to hand out one job at a time whatever it was, for the sake of the
single writer on the git canonical layer. Half of a real machine's queue could not write a
byte of the library — 273 `episodes` rounds of six to eight minutes behind 271 compile
rounds — and waited for it anyway. So the kinds are classified into a canonical lane and a
derived lane (`job_lanes.py`), one job in flight per lane, and the canonical lane's rule is
the rule the whole queue used to have.

Keyless: the in-memory queue implements the same predicates as the SQL, the worker's drains
run with stubbed job bodies, and `tests/integration/test_job_lanes_pg.py` re-checks two
lanes claiming at once against real Postgres.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import psycopg
import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore, InMemoryJobQueue
from pneuma_knowledge_service.adapters.postgres import CLAIM_FIRST_KINDS
from pneuma_knowledge_service.job_lanes import (
    CANONICAL_LANE,
    DERIVED_LANE,
    DERIVED_LANE_KINDS,
    JOB_LANES,
    LANES,
    lane_of,
    lane_reason,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import executor_for
from pneuma_knowledge_service.workers import compile_worker

USER = UserId("u-lanes")


# ─────────────────────────────────────────────────────────── the classification itself


def test_every_kind_the_worker_dispatches_is_classified_with_a_reason():
    """The lane table names the kinds by literal (it is imported by the adapter, which the
    modules defining those constants import in turn), so every constant is pinned here."""
    from pneuma_knowledge_service.access_stats import (
        RECALL_PROJECTION_JOB_KIND,
        RECALL_REBUILD_JOB_KIND,
    )
    from pneuma_knowledge_service.archive_service import ARCHIVE_JOB_KIND
    from pneuma_knowledge_service.challenge_service import CHALLENGE_JOB_KIND
    from pneuma_knowledge_service.groom_service import GROOM_JOB_KIND
    from pneuma_knowledge_service.workers.compile_worker import COMPILE_JOB_KIND

    dispatched = {
        COMPILE_JOB_KIND, "episodes", "evolve", "evolve_adopt", GROOM_JOB_KIND,
        ARCHIVE_JOB_KIND, RECALL_PROJECTION_JOB_KIND, RECALL_REBUILD_JOB_KIND,
        CHALLENGE_JOB_KIND, "index",
    }
    assert dispatched == set(JOB_LANES), "a dispatched kind is in no lane, or vice versa"
    for kind in dispatched:
        assert lane_of(kind) in LANES
        assert len(lane_reason(kind)) > 20, f"{kind} has no reason for its lane"


def test_the_derived_lane_is_exactly_the_kinds_that_cannot_write_canonical():
    assert set(DERIVED_LANE_KINDS) == {
        "index", "episodes", "recall_projection", "recall_rebuild"
    }
    for writer in ("compile", "evolve", "evolve_adopt", "groom", "archive", "challenge"):
        assert lane_of(writer) == CANONICAL_LANE
    # Every kind handed out ahead of the queue is derived — the two classifications agree.
    assert set(CLAIM_FIRST_KINDS) <= set(DERIVED_LANE_KINDS)


def test_a_kind_nobody_classified_is_in_the_strict_lane():
    """Forgetting the table can cost parallelism; it cannot cost the single writer."""
    assert lane_of("some_future_kind") == CANONICAL_LANE
    assert lane_of("") == CANONICAL_LANE


# ───────────────────────────────────────────────────────────── the claim, lane by lane


async def test_two_lanes_claim_at_once_for_one_user_and_neither_lane_claims_twice():
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "groom", {"path": "p"})
    await jobs.enqueue(USER, "index", {"source_id": "s2"})
    await jobs.enqueue(USER, "recall_projection", {"source_id": "c1"})

    writer = await jobs.claim_next(USER, lane=CANONICAL_LANE)
    derived = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert (writer.kind, derived.kind) == ("compile", "index")
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None, "two canonical writers"
    assert await jobs.claim_next(USER, lane=DERIVED_LANE) is None, "two derived jobs"


async def test_two_canonical_lane_jobs_never_overlap():
    jobs = InMemoryJobQueue()
    for kind in ("compile", "evolve", "groom", "archive", "challenge", "evolve_adopt"):
        await jobs.enqueue(USER, kind, {"source_ids": ["s1"]})
    held = await jobs.claim_next(USER, lane=CANONICAL_LANE)
    assert held is not None
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None
    # …and nothing that can write the library is handed out by the other lane either.
    assert await jobs.claim_next(USER, lane=DERIVED_LANE) is None


async def test_a_claim_naming_no_lane_is_the_whole_tenant_exactly_as_before():
    """Every caller outside the worker's own sweep — an ops command, a scaffolded app's
    `compile`, a test asserting one ordering — keeps the rule it has always had."""
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "index", {"source_id": "s1"})
    # A DIFFERENT source: this claim is about the lanes, and a compile also waits for the
    # derived lane's work on its own sources (`test_a_compile_waits_for_its_own_sources…`).
    await jobs.enqueue(USER, "compile", {"source_ids": ["s2"]})
    first = await jobs.claim_next(USER)
    assert first.kind == "index"
    assert await jobs.claim_next(USER) is None
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is not None, (
        "a derived job in flight must not reserve the canonical lane"
    )


# ─────────────────────────────────────────────────────── drafts reserve their own lane


async def _open_draft(
    jobs: InMemoryJobQueue, drafts: InMemoryDraftStore, kind: str, user: UserId = USER
) -> str:
    """Claim a job of `kind` and open a worker draft on it, as a launched round does."""
    payload = {"source_id": "s-draft", "source_ids": ["s-draft"]}
    job_id = await jobs.enqueue(user, kind, payload)
    executor = f"worker:codex:{kind}"
    assert await jobs.claim(user, job_id, claimed_by=executor) is not None
    await drafts.put(
        user, job_id, {"kind": kind, "session": {"executor": executor, "kind": kind}}
    )
    return job_id


async def test_an_open_compile_draft_does_not_block_an_episodes_claim():
    jobs = InMemoryJobQueue()
    drafts = InMemoryDraftStore(jobs)
    await _open_draft(jobs, drafts, "compile")
    await jobs.enqueue(USER, "episodes", {"source_id": "s9"})
    await jobs.enqueue(USER, "groom", {"path": "p"})

    claimed = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert claimed is not None and claimed.kind == "episodes"
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None, (
        "the compile draft must still reserve the canonical lane"
    )


async def test_an_open_episodes_draft_does_not_block_a_compile_claim():
    jobs = InMemoryJobQueue()
    drafts = InMemoryDraftStore(jobs)
    await _open_draft(jobs, drafts, "episodes")
    compile_job = await jobs.enqueue(USER, "compile", {"source_ids": ["s9"]})
    await jobs.enqueue(USER, "index", {"source_id": "s10"})

    claimed = await jobs.claim_next(USER, lane=CANONICAL_LANE)
    assert claimed is not None and claimed.job_id == compile_job
    assert await jobs.claim_next(USER, lane=DERIVED_LANE) is None
    # And the named claim — `pkc draft open <job>` — respects the same lane, not the tenant.
    assert await jobs.claim_next(USER) is None, "a lane-less claim still sees one in flight"


async def test_a_kept_draft_still_lets_its_own_job_be_claimed_in_its_lane():
    """The self-heal's one exception, inside a lane: a draft a dead launch left with work in
    it is kept and marked `continue_from`, and its own job is then the one row that lane may
    claim (`PostgresStore.requeue_claimed_jobs`)."""
    jobs = InMemoryJobQueue()
    drafts = InMemoryDraftStore(jobs)
    job_id = await _open_draft(jobs, drafts, "episodes")
    drafts._rows[(str(USER), job_id)]["continue_from"] = "worker:codex:episodes"
    await jobs.release(USER, job_id)
    resumed = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert resumed is not None and resumed.job_id == job_id


async def test_the_steward_holding_one_lane_does_not_stop_the_other(monkeypatch):
    """A Steward's compile round at a terminal reserves the canonical lane and says so; the
    derived lane goes on indexing behind it rather than standing still for it."""
    jobs = InMemoryJobQueue()
    drafts = InMemoryDraftStore(jobs)
    job_id = await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    assert await jobs.claim(USER, job_id, claimed_by="steward:session-a") is not None
    await drafts.put(
        USER, job_id,
        {"kind": "compile", "session": {"executor": "steward:session-a", "kind": "compile"}},
    )
    await jobs.enqueue(USER, "index", {"source_id": "s2"})
    ran: list[str] = []

    async def indexed(ctx, user_id, job):  # noqa: ANN001
        ran.append(job.kind)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", indexed)
    ctx = _Ctx(Settings(_env_file=None, embedding_model="fake:384"), jobs)
    assert await compile_worker.drain_user(ctx, None, None, USER, lane=CANONICAL_LANE) == 0
    assert await compile_worker.drain_user(ctx, None, None, USER, lane=DERIVED_LANE) == 1
    assert ran == ["index"]


async def test_the_draft_door_admits_one_round_per_lane_and_refuses_two_in_one():
    """`pkc draft open` is refused while another canonical round is open, and is NOT refused
    by the episodes round the worker is judging in the other lane."""
    from pneuma_knowledge_service.cli import draft as draft_cmd
    from pneuma_knowledge_core.ports.draft_store import DraftOwnershipError

    from test_draft_cli import harness

    h = await harness([])
    h.rt.draft_executor = "steward:session-a"
    await _open_draft(h.jobs, h.drafts, "episodes", user=h.rt.user_id)
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == 0

    other = await h.jobs.enqueue(h.rt.user_id, "compile", {"source_ids": ["s-other"]})
    with pytest.raises(DraftOwnershipError, match="already open"):
        await draft_cmd.require_open_slot(h.rt, other)


# ───────────────────────────────────── a compile waits for its own source's episodes


async def test_a_compile_waits_for_its_own_sources_index_job_too():
    """The episodes job does not exist yet when a source is imported — the index job is what
    commissions it. A compile that waited only for a queued episodes job would overtake the
    index job and compile a source whose episodes were never judged."""
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "index", {"source_id": "s1"})
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None

    index = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert index.kind == "index"
    # What `process_index_job` does under an agent executor: the judgement is written now,
    # at the index job's own place — so the compile keeps waiting, for the judgement.
    await jobs.enqueue(USER, "episodes", {"source_id": "s1"}, order_at=index.order_at)
    await jobs.complete(USER, index.job_id, ok=True)
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None

    judged = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert judged.kind == "episodes"
    await jobs.complete(USER, judged.job_id, ok=True)
    assert (await jobs.claim_next(USER, lane=CANONICAL_LANE)).kind == "compile"


async def test_a_compile_whose_source_has_a_pending_episodes_job_is_skipped():
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "compile", {"source_ids": ["s2"]})
    await jobs.enqueue(USER, "episodes", {"source_id": "s1"})

    # s1's judgement is still queued, so the canonical lane takes s2's compile instead.
    second = await jobs.claim_next(USER, lane=CANONICAL_LANE)
    assert second.payload["source_ids"] == ["s2"]
    await jobs.complete(USER, second.job_id, ok=True)

    # Claimed counts too: the derived lane is running it right now.
    judgement = await jobs.claim_next(USER, lane=DERIVED_LANE)
    assert judgement.kind == "episodes"
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None, (
        "the canonical lane must idle rather than compile a source whose episodes are pending"
    )

    # Once the judgement is recorded, the compile it was holding back is claimable.
    await jobs.complete(USER, judgement.job_id, ok=True)
    first = await jobs.claim_next(USER, lane=CANONICAL_LANE)
    assert first.payload["source_ids"] == ["s1"]


async def test_a_compile_of_several_sources_waits_for_any_of_them():
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1", "s2"]})
    await jobs.enqueue(USER, "episodes", {"source_id": "s2"})
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is None
    await jobs.complete(USER, (await jobs.claim_next(USER, lane=DERIVED_LANE)).job_id, ok=True)
    assert await jobs.claim_next(USER, lane=CANONICAL_LANE) is not None


# ──────────────────────────────────────────────────── the worker, both lanes at once


class _Ctx:
    def __init__(self, config: Settings, jobs: InMemoryJobQueue) -> None:
        self.settings = config
        self.store = jobs

    @property
    def compile_executor(self):
        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


def _agent_settings(**kwargs) -> Settings:
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "agent:codex",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
    }
    return Settings(_env_file=None, **{**base, **kwargs})


async def test_one_agent_round_per_lane_runs_at_the_same_time_and_never_two_in_one(monkeypatch):
    """The bound the lanes state: two harness processes for one library, one per lane."""
    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "episodes", {"source_id": "s2"})
    await jobs.enqueue(USER, "compile", {"source_ids": ["s3"]})
    await jobs.enqueue(USER, "episodes", {"source_id": "s4"})
    live: set[str] = set()
    both = asyncio.Event()
    peak = 0

    async def agent(ctx, user_id, job):  # noqa: ANN001
        nonlocal peak
        assert job.job_id not in live
        live.add(job.job_id)
        peak = max(peak, len(live))
        if len(live) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=2)
        live.discard(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="committed")

    monkeypatch.setattr(compile_worker, "_run_agent_job", _spy(agent))
    from pneuma_knowledge_service.cli import episodes

    async def never_split(*args):  # noqa: ANN001, ANN002
        return None

    monkeypatch.setattr(episodes, "split_oversized", never_split)
    ctx = _Ctx(_agent_settings(agent_unattended=True), jobs)
    await asyncio.gather(
        compile_worker.drain_user(ctx, None, SimpleNamespace(), USER, lane=CANONICAL_LANE),
        compile_worker.drain_user(ctx, None, SimpleNamespace(), USER, lane=DERIVED_LANE),
    )
    assert peak == 2, "the two lanes never had a round out at the same time"
    assert all(row["status"] == "done" for row in await jobs.list_jobs(USER))


def _spy(body):  # noqa: ANN001
    """`_run_agent_job`'s signature, so `process_agent_job`'s own lane guard still runs."""

    async def run(ctx, user_id, job, *, kind, role, executor):  # noqa: ANN001
        await body(ctx, user_id, job)

    return run


async def test_a_second_round_in_one_lane_is_refused_rather_than_launched(monkeypatch):
    """If a claim ever let two jobs of one lane fly, the harness must not be launched twice
    over one library: the lane guard says so out loud."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    ctx = _Ctx(_agent_settings(agent_unattended=True), jobs)
    job = await jobs.claim(USER, job_id)
    compile_worker._AGENT_ROUNDS[(str(USER), CANONICAL_LANE)] = "job-other"
    try:
        with pytest.raises(RuntimeError, match="second canonical-lane harness round"):
            await compile_worker.process_agent_job(ctx, USER, job)
    finally:
        compile_worker._AGENT_ROUNDS.clear()


async def test_cooling_stops_both_lanes_agent_rounds_and_neither_lane_stops_indexing(
    monkeypatch,
):
    """A spent subscription is a fact about the provider: no lane may claim work a harness
    would have to run, and every lane keeps draining the work that needs none."""
    from datetime import datetime, timedelta, timezone

    jobs = InMemoryJobQueue()
    await jobs.enqueue(USER, "compile", {"source_ids": ["s1"]})
    await jobs.enqueue(USER, "episodes", {"source_id": "s1"})
    await jobs.enqueue(USER, "index", {"source_id": "s2"})
    await jobs.enqueue(USER, "groom", {"path": "p"})
    ran: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        ran.append(job.kind)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="done")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    monkeypatch.setattr(compile_worker, "process_agent_job", body)
    monkeypatch.setattr(compile_worker, "run_groom_job", body)
    ctx = _Ctx(_agent_settings(agent_unattended=True), jobs)
    compile_worker._COOLING[str(USER)] = (
        datetime.now(timezone.utc) + timedelta(hours=1), "codex usage limit",
    )
    try:
        for lane in LANES:
            await compile_worker.drain_user(ctx, None, SimpleNamespace(), USER, lane=lane)
    finally:
        compile_worker._COOLING.clear()
    assert ran == ["groom", "index"] or ran == ["index", "groom"]
    queued = {row["kind"] for row in await jobs.list_jobs(USER) if row["status"] == "queued"}
    assert queued == {"compile", "episodes"}


# ───────────────────────────────────────── an outage in one lane leaves the other alone


class _OutageQueue(InMemoryJobQueue):
    """A queue whose canonical-lane claims meet a database that went away, twice."""

    def __init__(self) -> None:
        super().__init__()
        self.canonical_failures = 0
        self.pings = 0

    async def list_users(self) -> list[str]:
        return [str(USER)]

    async def claim_next(self, user_id, *, lane=None, **kwargs):  # noqa: ANN001
        if lane == CANONICAL_LANE and self.canonical_failures:
            self.canonical_failures -= 1
            raise psycopg.OperationalError(
                "consuming input failed: server closed the connection unexpectedly"
            )
        return await super().claim_next(user_id, lane=lane, **kwargs)

    async def ping(self) -> None:
        self.pings += 1


async def test_an_outage_in_one_lane_does_not_kill_the_other(monkeypatch, capsys):
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_START_S", 0.01)
    monkeypatch.setattr(compile_worker, "INFRA_BACKOFF_MAX_S", 0.02)
    monkeypatch.setattr(compile_worker, "IDLE_SWEEP_S", 0.01)
    jobs = _OutageQueue()
    jobs.canonical_failures = 2
    index_job = await jobs.enqueue(USER, "index", {"source_id": "s1"})
    groom_job = await jobs.enqueue(USER, "groom", {"path": "p"})

    async def body(ctx, user_id, job):  # noqa: ANN001
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="done")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    monkeypatch.setattr(compile_worker, "run_groom_job", body)
    ctx = _Ctx(Settings(_env_file=None, embedding_model="fake:384"), jobs)
    task = asyncio.create_task(compile_worker.drain_forever(ctx, None))
    try:
        async with asyncio.timeout(5):
            while True:
                rows = {r["job_id"]: r["status"] for r in await jobs.list_jobs(USER)}
                if rows.get(index_job) == "done":
                    break
                assert not task.done(), "the derived lane died with the canonical lane"
                await asyncio.sleep(0.005)
        # …and the lane that met the outage waits it out and then does its own work.
        async with asyncio.timeout(5):
            while (await jobs.get_job(USER, groom_job)).status != "done":
                assert not task.done()
                await asyncio.sleep(0.005)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    out = capsys.readouterr().out
    assert f"[compile-worker] draining {len(LANES)} lanes (canonical, derived)" in out
    assert f"[compile-worker] {CANONICAL_LANE} lane: infrastructure unavailable" in out
    assert f"{DERIVED_LANE} lane: infrastructure unavailable" not in out
