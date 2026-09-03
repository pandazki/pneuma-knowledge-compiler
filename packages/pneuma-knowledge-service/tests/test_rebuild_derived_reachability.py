"""`rebuild_derived` must reach every derived layer, including the ones L0 knows nothing about.

I7 says a projection is derived and rebuildable — re-derived by the same `rebuild_derived`
as every other derived layer. That promise used to hold only for tenants that owned an L0
source: `rebuild_user` returned before the use-side pass when there were none, and `--all`
enumerated tenants from `sources` alone. A tenant can make business consultations — and
accumulate misses — before importing anything, and its access ledger was then neither
replayable nor repairable.

The use-side pass also goes THROUGH THE QUEUE: it enqueues one `recall_rebuild` job and
drains it here, so the replay takes the same per-user claim a `recall_projection` takes and
the two cannot interleave. That is what the tests below pin — the enqueue, and the refusal
to claim a job this script has no model to run.

The ops script is imported directly (it is not an installed package), which is also the
cheapest way to say that these two decisions are the script's and nobody else's.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_OPS = Path(__file__).resolve().parents[3] / "scripts" / "ops"
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

rebuild_derived = pytest.importorskip("rebuild_derived")


class _Store:
    def __init__(self, *, sources=(), users=(), consultation_users=None) -> None:
        self._sources = list(sources)
        self._users = list(users)
        self._consultation_users = consultation_users

    async def list(self, user_id):  # noqa: ANN001
        return list(self._sources)

    async def list_users(self):
        return list(self._users)

    def __getattr__(self, name):  # noqa: ANN001
        if name == "list_consultation_users" and self._consultation_users is not None:
            async def lister():
                return list(self._consultation_users)

            return lister
        raise AttributeError(name)


class _Vectors:
    async def count_chunks(self, user_id):  # noqa: ANN001
        return 0


def _ctx(store) -> SimpleNamespace:  # noqa: ANN001
    return SimpleNamespace(store=store, vectors=_Vectors())


class _Queue:
    """The job-queue half of the store, in memory and claim-ordered like the real one.

    The row shape is the ADAPTER's: `PostgresStore.list_jobs` names the identifier
    `job_id`, and a fake that answered `id` would let a reader of the real listing pass
    its tests and raise `KeyError` in production.
    """

    def __init__(self, ahead=()) -> None:
        self.jobs: list[dict] = [
            {"job_id": f"pre-{i}", "kind": kind, "payload": {}, "status": "queued"}
            for i, kind in enumerate(ahead)
        ]
        self.ran: list[str] = []

    async def enqueue(self, user_id, kind, payload):  # noqa: ANN001
        job_id = f"j-{len(self.jobs)}"
        self.jobs.append(
            {"job_id": job_id, "kind": kind, "payload": dict(payload), "status": "queued"}
        )
        return job_id

    async def list_jobs(self, user_id):  # noqa: ANN001
        return list(reversed(self.jobs))  # newest first, like the adapter

    async def claim_next(self, user_id):  # noqa: ANN001
        for job in self.jobs:
            if job["status"] == "queued":
                job["status"] = "claimed"
                return SimpleNamespace(
                    job_id=job["job_id"], kind=job["kind"], payload=job["payload"]
                )
        return None

    async def complete(  # noqa: ANN001
        self, user_id, job_id, *, ok=True, detail=None, snapshot_ref=None, token_usage=None
    ):
        for job in self.jobs:
            if job["job_id"] == job_id:
                job["status"] = "done"
                job["detail"] = detail


class _QueueStore(_Store, _Queue):
    def __init__(self, *, sources=(), ahead=()) -> None:
        _Store.__init__(self, sources=sources)
        _Queue.__init__(self, ahead=ahead)


async def test_a_tenant_with_no_sources_still_has_its_use_side_pass(monkeypatch):
    """The early return. L1/L2/L3 are functions of the sources and have nothing to redo —
    but a projection derived from the use-side records is exactly the layer this tenant
    does own, and it is the one that needed repairing."""
    ran: list[str] = []

    async def fake_rebuild_job(ctx, user_id, job):  # noqa: ANN001
        ran.append(str(user_id))
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="replayed 0 record(s)")

    monkeypatch.setattr(rebuild_derived, "run_recall_rebuild_job", fake_rebuild_job)

    store = _QueueStore(sources=())
    await rebuild_derived.rebuild_user(_ctx(store), "u-mei")

    assert ran == ["u-mei"]
    assert [j["kind"] for j in store.jobs] == ["recall_rebuild"]


async def test_the_rebuild_is_enqueued_and_left_alone_when_a_compile_is_ahead_of_it(
    monkeypatch, capsys
):
    """The script has no model and no skill, so it claims only the two keyless kinds. A
    compile at the head of this user's queue is reported and left for the worker — which
    then runs the rebuild behind it, under the same claim."""

    async def fake_rebuild_job(ctx, user_id, job):  # noqa: ANN001
        raise AssertionError("the script must not run the rebuild past a compile job")

    monkeypatch.setattr(rebuild_derived, "run_recall_rebuild_job", fake_rebuild_job)

    store = _QueueStore(sources=(), ahead=("compile",))
    await rebuild_derived.rebuild_user(_ctx(store), "u-mei")

    assert [j["kind"] for j in store.jobs] == ["compile", "recall_rebuild"]
    assert [j["status"] for j in store.jobs] == ["queued", "queued"]
    assert "the worker will run it" in capsys.readouterr().out


async def test_a_projection_job_ahead_of_the_rebuild_is_drained_first(monkeypatch):
    """Both kinds are keyless, so the script may drain a projection queued ahead of its own
    job — and must, because that is what the queue's own order means."""
    drained: list[str] = []

    async def fake_projection_job(ctx, user_id, job):  # noqa: ANN001
        drained.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="projected")

    async def fake_rebuild_job(ctx, user_id, job):  # noqa: ANN001
        drained.append(job.job_id)
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="replayed")

    monkeypatch.setattr(rebuild_derived, "run_recall_projection_job", fake_projection_job)
    monkeypatch.setattr(rebuild_derived, "run_recall_rebuild_job", fake_rebuild_job)

    store = _QueueStore(sources=(), ahead=("recall_projection",))
    await rebuild_derived.rebuild_user(_ctx(store), "u-mei")

    assert drained == ["pre-0", "j-1"]


async def test_the_rebuild_reports_the_jobs_own_detail_from_the_listing(monkeypatch, capsys):
    """The report reads the completed job back out of `list_jobs`, which names the
    identifier `job_id`. Indexing it as `id` raised `KeyError` AFTER the replay had
    already been written — the command reported failure over work it had done, and
    `--all` abandoned every user behind this one."""

    async def fake_rebuild_job(ctx, user_id, job):  # noqa: ANN001
        await ctx.store.complete(
            user_id, job.job_id, ok=True, detail="replayed 3 record(s)"
        )

    monkeypatch.setattr(rebuild_derived, "run_recall_rebuild_job", fake_rebuild_job)

    store = _QueueStore(sources=())
    await rebuild_derived.rebuild_user(_ctx(store), "u-mei")

    assert "rebuilt the use-side projections: replayed 3 record(s)" in capsys.readouterr().out


async def test_all_enumerates_tenants_from_the_consultations_table_too():
    """`--all` used to ask `sources` who exists. A tenant that has only ever ASKED is
    invisible to that question and was silently skipped."""
    store = _Store(users=("u-bao",), consultation_users=("u-mei", "u-bao"))

    assert [str(u) for u in await rebuild_derived.all_users(_ctx(store))] == [
        "u-bao",
        "u-mei",
    ]


async def test_a_store_without_the_consultation_listing_still_enumerates():
    """The listing is optional on the port, so an adapter that predates it degrades to the
    old answer rather than failing the whole rebuild."""
    store = _Store(users=("u-bao",))
    assert [str(u) for u in await rebuild_derived.all_users(_ctx(store))] == ["u-bao"]
