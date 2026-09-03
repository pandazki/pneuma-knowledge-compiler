"""The evolve job's two accountability duties, driven off fakes — no git, no provider.

1. A terminated round records WHY. Phase 1 answering "no change" is legal and common, and
   for that round the reasoning IS the product: 30 consecutive no-change rounds in a 208-day
   replay recorded a verdict and not one word of reasoning, which made "why has the schema
   not moved" unanswerable after the fact. The rationale is persisted and read back through
   the same `rationale` field a proposal-bearing task uses.

2. The job sweeps the repository for oversized documents before phase 1. Grooming is
   orthogonal to schema evolution — this hangs off evolve only because evolve is the
   lowest-frequency pass in the system, and the write-path rollover trigger has a permanent
   blind spot the sweep closes (see `groom_service.scan_oversized_documents`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.evolve.propose import _EvolveDraft
from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_service.api.routes.evolve import get_evolve
from pneuma_knowledge_service.evolve_service import run_evolve_job
from pneuma_knowledge_service.groom_service import GROOM_JOB_KIND
from pneuma_knowledge_service.settings import Settings

USER = "u-evolve-job"
OVERSIZED = "work/products/aurora-planner.md"


# ------------------------------------------------------------------------------ the fakes


class _Store:
    def __init__(self, jobs=None):
        self._jobs = jobs or []
        self.tasks: list[dict] = []
        self.enqueued: list[tuple[str, dict]] = []
        self.completed: list[dict] = []

    async def list_evolve_tasks(self, user):  # noqa: ARG002
        return list(self.tasks)

    async def list_compile_events(self, user):  # noqa: ARG002
        return []

    async def list_jobs(self, user):  # noqa: ARG002
        return self._jobs

    async def enqueue(self, user, kind, payload):  # noqa: ARG002
        self.enqueued.append((kind, payload))
        return f"job-{len(self.enqueued)}"

    async def create_evolve_task(self, user, task_id, *, status, **fields):  # noqa: ARG002
        self.tasks.append(
            {
                "task_id": task_id,
                "status": status,
                "base_ref": fields.get("base_ref"),
                "branch": fields.get("branch"),
                "proposal": fields.get("proposal"),
                "summary": fields.get("summary"),
                "dropped": fields.get("dropped"),
                "detail": fields.get("detail"),
                "created_at": datetime.now(timezone.utc),
                "decided_at": None,
            }
        )

    async def get_evolve_task(self, user, task_id):  # noqa: ARG002
        return next((dict(t) for t in self.tasks if t["task_id"] == task_id), None)

    async def complete(  # noqa: ARG002
        self, user, job_id, *, ok=True, detail=None, snapshot_ref=None, token_usage=None
    ):
        self.completed.append({"job_id": job_id, "ok": ok, "detail": detail})


class _Canonical:
    def __init__(self, docs=()):
        self._docs = list(docs)

    async def list(self, user, *, at=None):  # noqa: ARG002
        return list(self._docs)


class _StubStructured:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        return {"parsed": self._payload, "raw": None}


class _StubModel:
    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, schema, include_raw=False):  # noqa: ARG002
        return _StubStructured(self._payload)


def _oversized_doc() -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId("d-aurora"),
        path=OVERSIZED,
        frontmatter={"doc_id": "d-aurora", "type": "product", "slug": "aurora-planner"},
        body="# Aurora planner\n\n" + "x" * 41_000 + "\n",
    )


def _ctx(store, docs=(), *, payload=None):
    return SimpleNamespace(
        settings=Settings(),
        store=store,
        canonical=_Canonical(docs),
        get_chat_model=lambda role="default": _StubModel(payload),
        langfuse_handler=lambda: None,
    )


def _install_skill(monkeypatch):
    async def _skill_for_user(ctx, user):  # noqa: ARG001
        return SkillVersion(
            skill_id="test-skill",
            version="t1",
            instructions="body",
            path_templates=["memory/topics/{slug}.md", "work/products/{slug}.md"],
            content_hash="0" * 64,
        )

    monkeypatch.setattr(
        "pneuma_knowledge_service.evolve_service.skill_for_user", _skill_for_user
    )


def _job():
    return SimpleNamespace(job_id="j-1", kind="evolve", payload={})


# --------------------------------------------------------------- 1. the rationale is kept


async def test_a_no_change_round_records_the_reason_not_only_the_verdict(monkeypatch):
    _install_skill(monkeypatch)
    store = _Store()
    ctx = _ctx(
        store,
        payload=_EvolveDraft(
            needs_change=False,
            rationale="The increment is three topic pages of one subject; no family boundary "
            "is under pressure yet.",
        ),
    )

    await run_evolve_job(ctx, USER, _job())

    assert [t["status"] for t in store.tasks] == ["no_change"]
    assert store.tasks[0]["detail"].startswith("The increment is three topic pages")
    assert store.completed == [{"job_id": "j-1", "ok": True, "detail": "evolve: no_change"}]


async def test_the_recorded_reason_reads_back_through_the_task_detail_endpoint(monkeypatch):
    """One field named `rationale` for the reader, whichever round produced it — a no-change
    round has no proposal to hang its reasoning on, so it comes off the task itself."""
    _install_skill(monkeypatch)
    store = _Store()
    ctx = _ctx(
        store,
        payload=_EvolveDraft(needs_change=False, rationale="No boundary is under pressure."),
    )
    await run_evolve_job(ctx, USER, _job())
    task_id = store.tasks[0]["task_id"]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))
    detail = await get_evolve(USER, task_id, request)

    assert detail.status == "no_change"
    assert detail.rationale == "No boundary is under pressure."
    assert detail.proposal is None  # there was never a proposal; the reasoning stands alone


async def test_a_silent_model_leaves_the_detail_empty_rather_than_inventing_one(monkeypatch):
    """The mechanism reports what the model said. When it said nothing, the task says nothing
    — a fabricated reason would be worse than the gap it fills."""
    _install_skill(monkeypatch)
    store = _Store()
    ctx = _ctx(store, payload=_EvolveDraft(needs_change=False, rationale="   "))

    await run_evolve_job(ctx, USER, _job())

    assert store.tasks[0]["status"] == "no_change"
    assert store.tasks[0]["detail"] is None


# ------------------------------------------------ 2. the repository sweep rides this job


async def test_the_job_sweeps_the_repository_for_oversized_documents_before_phase_one(
    monkeypatch,
):
    _install_skill(monkeypatch)
    store = _Store()
    ctx = _ctx(
        store,
        [_oversized_doc()],
        payload=_EvolveDraft(needs_change=False, rationale="nothing to do"),
    )
    doc = _oversized_doc()
    # The sweep measures the bytes that were COMMITTED, so the fixture has to be oversized as
    # a rendered file, not merely as a body.
    assert len(render_document(doc.frontmatter, doc.body)) > Settings().rollover_threshold_chars

    await run_evolve_job(ctx, USER, _job())

    # The groom job is enqueued even though this evolve round itself decided nothing: the two
    # channels are orthogonal, and evolve is only the carrier.
    assert store.enqueued == [(GROOM_JOB_KIND, {"path": OVERSIZED})]
    assert store.tasks[0]["status"] == "no_change"


async def test_the_sweep_does_not_re_enqueue_a_page_already_awaiting_a_groom(monkeypatch):
    _install_skill(monkeypatch)
    store = _Store(
        jobs=[{"kind": GROOM_JOB_KIND, "status": "queued", "payload": {"path": OVERSIZED}}]
    )
    ctx = _ctx(
        store,
        [_oversized_doc()],
        payload=_EvolveDraft(needs_change=False, rationale="nothing to do"),
    )

    await run_evolve_job(ctx, USER, _job())

    assert store.enqueued == []
