"""The episodes door over the real Qdrant adapter, with a keyless local client.

The same round-trip runs on Postgres and remote Qdrant in the integration tier.
Every source and description here is synthetic.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client import AsyncQdrantClient, models

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, SectionSpan, StructureMap
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk, chunk_source, build_chunker
from pneuma_knowledge_core.ingest.semantic import decode_manifest_episodes
from pneuma_knowledge_core.prompts import chinese_overlay, override_prompts, reset_prompt_overrides
from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore, InMemoryJobQueue
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore
from pneuma_knowledge_service.adapters.qdrant import QdrantVectorIndex
from pneuma_knowledge_service.cli import build_parser, dispatch, draft, episodes
from pneuma_knowledge_service.coding_agent.backends import CODEX
from pneuma_knowledge_service.coding_agent.launcher import LaunchResult
from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_embeddings, embed_l2_chunks, executor_for, plan_l2_chunks
from pneuma_knowledge_service.workers import compile_worker

SID = SourceId("synthetic-episodes")
HASH = "e" * 64
PROPOSAL = [
    {"start": 1, "end": 2, "title": "Aurora delivery", "description": "Aurora will deliver in June, subject to a passing test."},
    {"start": 4, "end": 4, "title": "Borealis review", "description": "Borealis reviews the delivery on Monday."},
]


def source(user, *, semantic="full"):
    texts = ["Hello.", "Aurora will deliver in June.", "Delivery requires a passing test.",
             "Thanks.", "Borealis reviews the delivery on Monday.", "A command exited successfully."]
    return NormalizedSource(
        raw=RawSource(
            source_id=SID, user_id=user, kind="agent_session", origin="mock",
            title="Synthetic delivery discussion", mime="text/plain", checksum="synthetic-episodes-checksum",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            intake_plan={"canonical_treatment": "full", "semantic_indexing": semantic, "rationale": "synthetic test selection"},
            meta={"turns": [{"role": "owner" if i < 5 else "agent", "kind": "message" if i < 5 else "activity"} for i in range(6)]},
        ),
        blocks=[NormalizedBlock(index=i, text=text) for i, text in enumerate(texts)],
        structure=StructureMap(sections=[SectionSpan(path=["Discussion"], start_block=0, end_block=5)]),
    )


class MemoryStore(InMemoryJobQueue):
    def __init__(self):
        super().__init__()
        self._pool = None
        self.sources = {}
        self.manifests = {}
        self.windows = {}
        self.manifest_writes = 0

    async def add(self, user, value):
        self.sources[str(user), str(value.raw.source_id)] = value.model_copy(deep=True)
        return value.raw.source_id

    async def get(self, user, sid):
        return self.sources[str(user), str(sid)].model_copy(deep=True)

    async def list(self, user):
        return [s.raw for (u, _), s in self.sources.items() if u == str(user)]

    async def block_counts(self, user, *args):
        return {sid: len(s.blocks) for (u, sid), s in self.sources.items() if u == str(user)}

    async def get_chunk_manifest(self, user, sid):
        value = self.manifests.get((str(user), str(sid)))
        return json.loads(json.dumps(value)) if value is not None else None

    async def put_chunk_manifest(self, user, sid, **manifest):
        self.manifest_writes += 1
        self.manifests[str(user), str(sid)] = json.loads(json.dumps(manifest))

    async def get_chunk_manifest_windows(self, user, sid):
        rows = [row for (u, s, _), row in sorted(self.windows.items(), key=lambda kv: kv[0][2])
                if u == str(user) and s == str(sid)]
        return json.loads(json.dumps(rows))

    async def put_chunk_manifest_window(self, user, sid, *, window_start, window_end, **manifest):
        self.manifest_writes += 1
        self.windows[str(user), str(sid), int(window_start)] = json.loads(json.dumps(
            {"window_start": int(window_start), "window_end": int(window_end), **manifest}
        ))


async def make_runtime(tmp_path, *, store=None, user=None, vectors=None, lexical=None, **settings):
    user = user or UserId("u-episodes-test")
    store = store or MemoryStore()
    config = Settings(**{
        "canonical_root": str(tmp_path / "canonical"), "llm_model": "",
        "llm_model_compile": "agent:codex", "llm_model_evolve": "",
        "embedding_model": "fake:384", "chunk_strategy": "semantic",
        "semantic_retrieval": "on", "agent_unattended": False,
        "agent_probe_on_start": False, "user_schema_packs": False,
        **settings,
    })
    if vectors is None:
        vectors = QdrantVectorIndex.__new__(QdrantVectorIndex)
        vectors._collection, vectors._dim = "synthetic-episodes-test", 384
        vectors._client = AsyncQdrantClient(location=":memory:")
        await vectors.ensure_collection()
    ctx = SimpleNamespace(
        settings=config, store=store, vectors=vectors,
        canonical=GitCanonicalStore(config.canonical_root),
        lexical=lexical or SimpleNamespace(index_blocks=AsyncMock(), delete_user=AsyncMock()),
        embeddings=build_embeddings(config), flush_traces=AsyncMock(),
        get_chat_model=lambda role: pytest.fail("an agent index must never build a chat model"),
    )
    rt = await episodes.build_runtime(ctx, user, executor="agent:codex")
    if isinstance(store, MemoryStore):
        rt.drafts = InMemoryDraftStore(store)
    rt.executor_skill = HASH
    rt.out, rt.err = io.StringIO(), io.StringIO()
    await store.add(user, source(user))
    return rt


@pytest.fixture
async def rt(tmp_path):
    runtime = await make_runtime(tmp_path)
    yield runtime
    await runtime.ctx.vectors.aclose()


async def open_job(rt):
    job_id = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    assert await episodes.cmd_open(rt, job_id) == 0, rt.err.getvalue()
    return job_id


async def propose(rt, tmp_path, value=PROPOSAL):
    path = tmp_path / "episodes.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return await episodes.cmd_propose(rt, file=str(path))


async def points(rt, user=None):
    rows, _ = await rt.ctx.vectors._client.scroll(
        rt.ctx.vectors._collection,
        scroll_filter=models.Filter(must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=str(user or rt.user_id)))]),
        with_vectors=True, limit=100,
    )
    return sorted([row.model_dump() for row in rows], key=lambda row: row["id"])


async def replay_via_rebuild(rt, monkeypatch):
    # Exercise the real ops entry point's L1/L2 loop; unrelated L3/component rebuilds have
    # their own tests and do not need a canonical library in this retrieval-only fixture.
    import importlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts" / "ops"))
    rebuild = importlib.import_module("rebuild_derived")
    monkeypatch.setattr(rebuild, "rebuild_projection", AsyncMock(return_value=0))
    monkeypatch.setattr(rebuild, "rebuild_component_projections", AsyncMock())
    await rebuild.rebuild_user(rt.ctx, rt.user_id)


async def round_trip(rt, tmp_path, monkeypatch, proposal=PROPOSAL):
    original = await rt.ctx.store.get(rt.user_id, SID)
    # Start with stale full coverage: accepting gaps or [] must actively remove it.
    stale = await chunk_source(SID, original.blocks, original.structure)
    await rt.ctx.vectors.upsert_chunks(rt.user_id, await embed_l2_chunks(rt.ctx, stale, original))
    job_id = await open_job(rt)
    assert '"role": "owner"' in rt.out.getvalue()
    assert '"kind": "activity"' in rt.out.getvalue()
    assert await propose(rt, tmp_path, proposal) == 0, rt.err.getvalue()
    assert await episodes.cmd_status(rt) == 0
    assert await episodes.cmd_finish(rt) == 0, rt.err.getvalue()
    manifest = await rt.ctx.store.get_chunk_manifest(rt.user_id, SID)
    assert manifest["model"] == "agent:codex" and manifest["strategy"] == "semantic"
    assert manifest["segments"]["Executor-Skill"] == HASH
    assert manifest["segments"]["producer"] == "agent"
    assert manifest["segments"]["coverage"] == "partial"
    assert manifest["segments"]["episodes"] == proposal
    decoded = decode_manifest_episodes(manifest["segments"], block_indices=list(range(6)))
    assert decoded is not None and len(decoded[0]) == len(proposal)
    before = await points(rt)
    before_chunks = await plan_l2_chunks(rt.ctx, SID, original, rt.user_id)
    before_embeddings = await embed_l2_chunks(rt.ctx, before_chunks, original)
    assert len(before) == len(proposal) * 2
    assert {(p["payload"]["block_start"], p["payload"]["block_end"]) for p in before} == {(p["start"], p["end"]) for p in proposal}
    await replay_via_rebuild(rt, monkeypatch)
    after = await points(rt)
    assert await plan_l2_chunks(rt.ctx, SID, original, rt.user_id) == before_chunks
    assert await embed_l2_chunks(rt.ctx, before_chunks, original) == before_embeddings
    assert len(after) == len(before)
    for left, right in zip(before, after):
        assert left["payload"] == right["payload"]
        assert left["id"] == right["id"]
        # Qdrant local uses float32 on insert and float64 on update before storing float32.
        # Inputs and payloads are byte-identical; that adapter rounding is not segmentation.
        assert left["vector"] == pytest.approx(right["vector"], abs=2e-8, rel=0)
    assert await rt.ctx.store.get_chunk_manifest(rt.user_id, SID) == manifest
    assert await rt.ctx.store.get(rt.user_id, SID) == original
    assert await rt.canonical.snapshots(rt.user_id) == []
    assert await rt.drafts.get(rt.user_id, job_id) is None
    assert (await rt.jobs.get_job(rt.user_id, job_id)).status == "done"


@pytest.mark.parametrize("proposal", [PROPOSAL, []])
async def test_round_trip_replaces_vectors_and_rebuilds_exactly(rt, tmp_path, monkeypatch, proposal):
    await round_trip(rt, tmp_path, monkeypatch, proposal)
    assert rt.ctx.store.manifest_writes == 1


@pytest.mark.parametrize("proposal,violation", [
    ([{**PROPOSAL[0], "start": 0, "end": 5}, {**PROPOSAL[1], "start": 1, "end": 5}], "episodes.overlap"),
    ([PROPOSAL[1], PROPOSAL[0]], "episodes.starts"),
    ([PROPOSAL[0]] * 7, "episodes.count"),
    ([{**PROPOSAL[0], "title": "  "}], "episodes.title"),
    ([{**PROPOSAL[0], "description": ""}], "episodes.description"),
    ([{**PROPOSAL[0], "start": 99}], "episodes.endpoints"),
    ([{**PROPOSAL[0], "end": 0}], "episodes.endpoints"),
    ([{**PROPOSAL[0], "start": True}], "episodes.endpoints"),
    ([{**PROPOSAL[0], "start": 1.0}], "episodes.endpoints"),
    ({"episodes": PROPOSAL}, "episodes.shape"),
])
async def test_refusals_name_violations_and_keep_last_selection(rt, tmp_path, proposal, violation):
    job = await open_job(rt)
    assert await propose(rt, tmp_path) == 0
    before = json.loads(json.dumps(await rt.drafts.get(rt.user_id, job)))
    assert await propose(rt, tmp_path, proposal) == draft.EXIT_REFUSED
    after = await rt.drafts.get(rt.user_id, job)
    assert violation in rt.err.getvalue()
    assert after["session"]["context"] == before["session"]["context"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1
    assert await rt.ctx.store.get_chunk_manifest(rt.user_id, SID) is None


async def test_missing_proposal_repairs_then_aborts_instead_of_recording_empty(rt):
    job = await open_job(rt)
    assert await episodes.cmd_finish(rt) == draft.EXIT_GATE
    assert (await rt.drafts.get(rt.user_id, job))["session"]["round"] == "repair"
    assert await episodes.cmd_finish(rt) == draft.EXIT_GATE
    assert await rt.drafts.get(rt.user_id, job) is None
    assert rt.ctx.store.manifest_writes == 0


async def test_budget_is_spent_on_bad_json_and_abandon_releases_claim(rt, tmp_path):
    rt.max_tool_calls = 1
    job = await open_job(rt)
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    assert await episodes.cmd_propose(rt, file=str(path)) == draft.EXIT_REFUSED
    assert await propose(rt, tmp_path) == draft.EXIT_BUDGET
    assert await draft.cmd_status(replace(rt, kind="compile")) == draft.EXIT_NOTHING
    assert await draft.cmd_abandon(rt) == 0
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "queued"
    assert await episodes.cmd_status(rt) == draft.EXIT_NOTHING


async def test_tenant_claim_and_vector_replacement_isolation(rt, tmp_path):
    other = UserId("u-episodes-other")
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    assert await episodes.cmd_open(replace(rt, user_id=other), job) == draft.EXIT_NOTHING
    assert await episodes.cmd_open(rt, job) == 0
    another = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    assert await episodes.cmd_open(rt, another) == draft.EXIT_REFUSED
    point = EmbeddedChunk(source_id=SID, block_start=0, block_end=5, text="synthetic", char_start=0, char_end=9, embedding=[0.1] * 384)
    await rt.ctx.vectors.upsert_chunks(other, [point])
    await rt.ctx.vectors.upsert_chunks(rt.user_id, [replace(point, source_id=SourceId("synthetic-other-source"))])
    before_other = await points(rt, other)
    assert await propose(rt, tmp_path, []) == 0
    assert await episodes.cmd_finish(rt) == 0
    assert await points(rt, other) == before_other
    assert {p["payload"]["source_id"] for p in await points(rt)} == {"synthetic-other-source"}


@pytest.mark.parametrize("semantic,on,expected", [("full", "on", 1), ("summary", "on", 1), ("none", "on", 0), ("full", "off", 0)])
async def test_agent_index_enqueues_episodes_without_mechanical_fallback(rt, monkeypatch, semantic, on, expected):
    rt.ctx.settings.semantic_retrieval = on
    await rt.ctx.store.add(rt.user_id, source(rt.user_id, semantic=semantic))
    monkeypatch.setattr("pneuma_knowledge_core.ingest.chunking.chunk_source", AsyncMock(side_effect=AssertionError("mechanical fallback")))
    for _ in range(2):
        job_id = await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
        job = await rt.jobs.claim(rt.user_id, job_id)
        await compile_worker.process_index_job(rt.ctx, rt.user_id, job)
    jobs = await rt.jobs.list_jobs(rt.user_id)
    assert sum(j["kind"] == "episodes" for j in jobs) == expected
    assert rt.ctx.lexical.index_blocks.await_count == 2
    assert await points(rt) == []
    assert rt.ctx.store.manifest_writes == 0


async def test_the_index_job_queues_episodes_at_its_own_place_ahead_of_the_compile(rt):
    """The episodes job is written when the index job RUNS — after the source's compile was
    queued. It inherits the index job's place, so the claim hands it out before that compile
    instead of behind every compile already waiting."""
    index_id = await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
    compile_id = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": [str(SID)]})
    job = await rt.jobs.claim_next(rt.user_id)
    assert job.job_id == index_id
    await compile_worker.process_index_job(rt.ctx, rt.user_id, job)
    episodes_job = await rt.jobs.claim_next(rt.user_id)
    assert episodes_job.kind == "episodes"
    assert episodes_job.order_at == job.order_at
    await rt.jobs.complete(rt.user_id, episodes_job.job_id, ok=True)
    assert (await rt.jobs.claim_next(rt.user_id)).job_id == compile_id


async def test_api_index_keeps_the_same_mechanical_path(rt):
    rt.ctx.settings.llm_model_compile = ""
    ns = await rt.ctx.store.get(rt.user_id, SID)
    expected = await chunk_source(SID, ns.blocks, ns.structure, chunker=build_chunker("sentence", rt.ctx.settings.chunk_size, rt.ctx.settings.chunk_overlap))
    assert await plan_l2_chunks(rt.ctx, SID, ns, rt.user_id) == expected
    job_id = await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
    await compile_worker.process_index_job(rt.ctx, rt.user_id, await rt.jobs.claim(rt.user_id, job_id))
    assert len(await points(rt)) == len(expected)
    assert not any(j["kind"] == "episodes" for j in await rt.jobs.list_jobs(rt.user_id))


@pytest.mark.parametrize("language", ["en", "zh"])
async def test_unattended_handover_and_i5(rt, tmp_path, language):
    if language == "zh":
        override_prompts(chinese_overlay())
    try:
        job = await open_job(rt)
        code, system, task = await episodes.open_round(rt, job)
        assert await draft.cmd_abandon(rt) == 0
        assert await rt.jobs.claim(rt.user_id, job) is not None
        requests = []

        async def launcher(request):
            requests.append(request)
            assert request.system_text == system
            assert task in request.task_text
            assert "pkc index episodes propose" in request.task_text
            assert await propose(rt, tmp_path) == 0
            return LaunchResult(exit_code=0, stdout="", stderr="", usage={"input_tokens": 7})

        runner = AgentRoundRunner(manifest=CODEX, project_dir=str(tmp_path), timeout_s=10, launcher=launcher)
        result = await runner.run_job(rt, job)
        assert result.launches == 1 and result.usage == {"input_tokens": 7}
        assert await rt.drafts.get(rt.user_id, job) is None
        assert len(await points(rt)) == 4
        rt.max_tool_calls = 100
        changed = source(rt.user_id)
        changed.blocks[0].text = "Different synthetic greeting."
        await rt.ctx.store.add(rt.user_id, changed)
        second = await open_job(rt)
        _, second_system, second_task = await episodes.open_round(rt, second)
        assert system == second_system and task != second_task
    finally:
        reset_prompt_overrides()


async def test_published_manifest_survives_failed_embedding_and_cannot_be_rejudged(rt, tmp_path, monkeypatch):
    job = await open_job(rt)
    assert await propose(rt, tmp_path) == 0
    with monkeypatch.context() as patch:
        patch.setattr(episodes, "embed_l2_chunks", AsyncMock(side_effect=RuntimeError("embedding unavailable")))
        with pytest.raises(RuntimeError, match="embedding unavailable"):
            await episodes.cmd_finish(rt)
    recorded = await rt.ctx.store.get_chunk_manifest(rt.user_id, SID)
    assert await propose(rt, tmp_path, []) == draft.EXIT_REFUSED
    assert await draft.cmd_abandon(rt) == 0
    assert await episodes.cmd_open(rt, job) == 0
    assert await episodes.cmd_finish(rt) == 0
    assert await rt.ctx.store.get_chunk_manifest(rt.user_id, SID) == recorded
    assert rt.ctx.store.manifest_writes == 1


async def test_cli_dispatch_uses_the_episodes_door(rt, monkeypatch):
    monkeypatch.setattr(episodes, "build_runtime", AsyncMock(return_value=rt))
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    for tail in (["open", job], ["status"], ["propose", "-"], ["finish"]):
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        args = build_parser().parse_args(["--user", str(rt.user_id), "index", "episodes", *tail])
        assert await dispatch(rt.ctx, args, out=rt.out, err=rt.err) == 0, rt.err.getvalue()


async def test_challenge_skipped_even_with_a_usable_api_role(rt):
    from pneuma_knowledge_service.challenge_service import maybe_trigger_challenge

    rt.ctx.settings.challenge_enabled = True
    rt.ctx.settings.llm_model_challenge = "openrouter:synthetic/challenge"
    rt.ctx.settings.openrouter_api_key = "synthetic-key"
    assert not compile_worker.optional_role_runnable(rt.ctx.settings, "challenge")
    await maybe_trigger_challenge(rt.ctx, rt.user_id, {}, [str(SID)])
    assert await rt.jobs.list_jobs(rt.user_id) == []


@pytest.mark.parametrize("unattended", [False, True])
async def test_worker_claims_episodes_only_in_unattended_posture(rt, tmp_path, monkeypatch, unattended):
    import pneuma_knowledge_service.coding_agent.round_runner as runner_module

    rt.ctx.settings.agent_unattended = unattended
    rt.ctx.compile_executor = executor_for(rt.ctx.settings, "compile")
    rt.ctx.store.record_job_usage = AsyncMock()
    requests = []

    async def launcher(request):
        requests.append(request)
        assert "pkc index episodes propose" in request.task_text
        assert await propose(rt, tmp_path) == 0
        assert await episodes.cmd_finish(rt) == 0
        return LaunchResult(exit_code=0, stdout="", stderr="", usage={"input_tokens": 17})

    monkeypatch.setattr(episodes, "build_runtime", AsyncMock(return_value=rt))
    monkeypatch.setattr(runner_module, "AgentRoundRunner", lambda **kwargs: AgentRoundRunner(**kwargs, launcher=launcher))
    compile_job = None
    if not unattended:
        compile_job = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": [str(SID)]})
    await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
    count = await compile_worker.drain_user(rt.ctx, None, None, rt.user_id)
    assert count == (2 if unattended else 1)
    selected = next(j for j in await rt.jobs.list_jobs(rt.user_id) if j["kind"] == "episodes")
    assert selected["status"] == ("done" if unattended else "queued")
    assert len(requests) == int(unattended)
    if unattended:
        assert len(await points(rt)) == 4
        rt.ctx.store.record_job_usage.assert_awaited_once()
    else:
        # Compile can claim its slot with an episodes job still queued: no L2 dependency.
        assert await rt.jobs.claim(rt.user_id, compile_job) is not None


async def test_finished_manifest_is_replayed_on_index_retry_without_new_judgement(rt, tmp_path):
    await open_job(rt)
    await propose(rt, tmp_path)
    assert await episodes.cmd_finish(rt) == 0
    job = await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
    await compile_worker.process_index_job(rt.ctx, rt.user_id, await rt.jobs.claim(rt.user_id, job))
    assert len([j for j in await rt.jobs.list_jobs(rt.user_id) if j["kind"] == "episodes"]) == 1
    assert rt.ctx.store.manifest_writes == 1


async def test_finish_with_retrieval_off_keeps_the_record_for_later_rebuild(rt, tmp_path):
    await open_job(rt)
    await propose(rt, tmp_path)
    rt.ctx.settings.semantic_retrieval = "off"
    saved_vectors = rt.ctx.vectors
    rt.ctx.vectors = rt.ctx.embeddings = None
    assert await episodes.cmd_finish(rt) == 0
    assert await rt.ctx.store.get_chunk_manifest(rt.user_id, SID) is not None
    rt.ctx.vectors = saved_vectors


async def test_finish_refuses_missing_skill_identity(rt, tmp_path):
    rt.executor_skill = ""
    await open_job(rt)
    await propose(rt, tmp_path)
    assert await episodes.cmd_finish(rt) == draft.EXIT_REFUSED
    assert "episodes.executor_skill" in rt.err.getvalue()
    assert rt.ctx.store.manifest_writes == 0


async def test_api_worker_does_not_announce_compile_as_waiting_for_steward(rt, monkeypatch, caplog):
    rt.ctx.settings.llm_model_compile = ""
    job = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": [str(SID)]})

    async def process(ctx, model, skill, user, claimed):
        await ctx.store.complete(user, claimed.job_id, ok=True)

    monkeypatch.setattr(compile_worker, "process_job", process)
    with caplog.at_level("INFO"):
        assert await compile_worker.drain_user(rt.ctx, None, rt.skill, rt.user_id) == 1
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "done"
    assert "waiting for the Steward" not in caplog.text
