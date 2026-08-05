"""Challenge job orchestration (challenge_service.py) — no middleware, fakes only.

Pins the service half of the coverage challenge: the trigger's switch and its
anti-recursion flag, the round loop's outcome routing (gaps → ONE compensation compile
carrying rendered guidance; no gaps → a quiet completion), and the job detail record.
The judgement half lives in core and is pinned by core's test_challenge.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pneuma_knowledge_service.challenge_service as challenge_service
from pneuma_knowledge_core.compile.challenge import (
    ChallengeGap,
    ChallengeQuestions,
    ChallengeReflection,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_service.challenge_service import (
    maybe_trigger_challenge,
    run_challenge_job,
)

UID = UserId("u-chal")


def _source(sid: str = "s-1") -> NormalizedSource:
    raw = RawSource(
        source_id=SourceId(sid),
        user_id=UID,
        kind="document",
        title="notes",
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    return NormalizedSource(
        raw=raw,
        blocks=[NormalizedBlock(index=0, text="Alice hands QA to Bob on Friday.")],
        structure=StructureMap(sections=[]),
    )


def _skill() -> SkillVersion:
    return SkillVersion.from_parts(
        skill_id="t", version="t1", instructions="Record handovers.",
        path_templates=["notes/{slug}.md"],
    )


class _Store:
    def __init__(self, sources: dict[str, NormalizedSource] | None = None) -> None:
        self.sources = sources or {}
        self.enqueued: list[tuple[str, dict]] = []
        self.completed: list[dict] = []

    async def get(self, user_id, source_id):
        return self.sources[str(source_id)]

    async def enqueue(self, user_id, kind, payload):
        self.enqueued.append((kind, payload))
        return f"job-{len(self.enqueued)}"

    async def complete(self, user_id, job_id, *, ok=True, detail=None, snapshot_ref=None):
        self.completed.append({"job_id": job_id, "ok": ok, "detail": detail})


class _NoClaims:
    async def search_claims(self, user_id, query, *, limit=6):
        return []


class _Embeddings:
    async def aembed_query(self, text):
        return [0.0]


def _ctx(store: _Store, **settings_overrides) -> SimpleNamespace:
    values = dict(
        challenge_enabled=True,
        challenge_max_rounds=2,
        challenge_max_questions=6,
        challenge_compensate=True,
    )
    values.update(settings_overrides)
    settings = SimpleNamespace(**values)
    return SimpleNamespace(
        settings=settings,
        store=store,
        lexical=_NoClaims(),
        vectors=_NoClaims(),
        embeddings=_Embeddings(),
    )


class _Model:
    """Dispatches structured-output calls by schema: scripted questions, then reflections."""

    def __init__(self, questions: list[ChallengeQuestions], reflections: list[ChallengeReflection]):
        self._by_schema = {ChallengeQuestions: list(questions), ChallengeReflection: list(reflections)}

    def with_structured_output(self, schema, *, include_raw=False):
        queue = self._by_schema[schema]

        class _Runnable:
            async def ainvoke(self, messages, config=None):
                return queue.pop(0)

        return _Runnable()


def _patch_call_config(monkeypatch):
    monkeypatch.setattr(
        challenge_service,
        "llm_call_config",
        lambda ctx, **kw: {"callbacks": None, "trace_metadata": None},
    )


async def test_trigger_respects_switch_flag_and_emptiness():
    store = _Store()
    ctx = _ctx(store)
    await maybe_trigger_challenge(ctx, UID, {}, ["s-1"])
    assert store.enqueued == [("challenge", {"source_ids": ["s-1"]})]

    store.enqueued.clear()
    # The compensation compile never re-triggers the audit — one round-trip, not a loop.
    await maybe_trigger_challenge(ctx, UID, {"challenge_compensation": True}, ["s-1"])
    # No sources → nothing to audit.
    await maybe_trigger_challenge(ctx, UID, {}, [])
    # Switch off → silent.
    off = _ctx(store, challenge_enabled=False)
    await maybe_trigger_challenge(off, UID, {}, ["s-1"])
    assert store.enqueued == []


async def test_gaps_enqueue_one_compensation_compile(monkeypatch):
    _patch_call_config(monkeypatch)
    store = _Store({"s-1": _source()})
    ctx = _ctx(store)
    model = _Model(
        questions=[ChallengeQuestions(questions=["Who took over QA?"], exhausted=False)],
        reflections=[
            ChallengeReflection(
                gaps=[ChallengeGap(question="Who took over QA?", missing_fact="Bob took QA over on Friday.")],
                exhausted=True,
            )
        ],
    )
    job = SimpleNamespace(job_id="j-1", payload={"source_ids": ["s-1"]})
    await run_challenge_job(ctx, model, _skill(), UID, job)

    (kind, payload), = store.enqueued
    assert kind == "compile"
    assert payload["source_ids"] == ["s-1"]
    assert payload["challenge_compensation"] is True
    assert "Bob took QA over on Friday." in payload["challenge_guidance"]

    (done,) = store.completed
    assert done["ok"] is True
    assert '"gaps": ["Who took over QA?"]' in done["detail"]
    assert '"compensation_enqueued": true' in done["detail"]


async def test_no_gaps_completes_quietly_and_stops_on_exhaustion(monkeypatch):
    _patch_call_config(monkeypatch)
    store = _Store({"s-1": _source()})
    ctx = _ctx(store)
    model = _Model(
        questions=[ChallengeQuestions(questions=["Anything new?"], exhausted=True)],
        reflections=[ChallengeReflection(gaps=[], exhausted=False)],
    )
    job = SimpleNamespace(job_id="j-2", payload={"source_ids": ["s-1"]})
    await run_challenge_job(ctx, model, _skill(), UID, job)

    assert store.enqueued == []  # nothing to compensate
    (done,) = store.completed
    assert done["ok"] is True
    # Generator exhaustion ended the loop after one round despite the two-round budget.
    assert '"rounds": 1' in done["detail"]
    assert '"exhausted": true' in done["detail"]


async def test_model_failure_degrades_the_audit_but_never_fails_the_job(monkeypatch):
    """2026-08-05: a mid-round model failure must complete the job ok with a `degraded`
    note (compensating any gaps already confirmed) — a failed challenge job wedges the
    queue's tail, observed live killing a 500-day build at day 100."""
    _patch_call_config(monkeypatch)
    store = _Store({"s-1": _source()})
    ctx = _ctx(store)

    class _Exploding:
        def with_structured_output(self, schema, *, include_raw=False):
            class _Runnable:
                async def ainvoke(self, messages, config=None):
                    raise TypeError("'NoneType' object is not iterable")

            return _Runnable()

    job = SimpleNamespace(job_id="j-deg", payload={"source_ids": ["s-1"]})
    await run_challenge_job(ctx, _Exploding(), _skill(), UID, job)

    (done,) = store.completed
    assert done["ok"] is True
    assert '"degraded"' in done["detail"]
    assert "NoneType" in done["detail"]
    assert store.enqueued == []  # no gaps confirmed → nothing to compensate


async def test_gone_sources_complete_without_running_the_model(monkeypatch):
    _patch_call_config(monkeypatch)
    store = _Store({})  # store.get raises KeyError for every id

    async def _get(user_id, source_id):
        raise KeyError(str(source_id))

    store.get = _get
    ctx = _ctx(store)
    job = SimpleNamespace(job_id="j-3", payload={"source_ids": ["s-gone"]})
    await run_challenge_job(ctx, None, _skill(), UID, job)
    (done,) = store.completed
    assert done["ok"] is True and "sources gone" in done["detail"]
    assert store.enqueued == []
