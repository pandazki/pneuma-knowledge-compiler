"""The deployment switch preserves L0/L1 and avoids every semantic startup/index call."""

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.intake import IntakePlan, with_semantic_retrieval
from pneuma_knowledge_service import wiring
from pneuma_knowledge_service.cli import _run, build_parser
from pneuma_knowledge_service.cli.read import ReadRuntime, cmd_search
from pneuma_knowledge_service.engine.apply import Change, plan_effects
from pneuma_knowledge_service.engine.resolve import engine_overrides
from pneuma_knowledge_service.ingest_document import ingest_document, preview_document
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers import compile_worker

from _cli_library import USER, library, source


class Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"semantic retrieval is off: touched {name}")


def fail(*args, **kwargs):
    raise AssertionError("semantic retrieval is off: performed semantic work")


async def test_off_startup_never_builds_embeddings_or_vectors_even_with_no_key(monkeypatch):
    store = SimpleNamespace(open=AsyncMock(), apply_schema=AsyncMock(), aclose=AsyncMock(), get_user_profile=AsyncMock())
    lexical = SimpleNamespace(aclose=AsyncMock())
    media = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(wiring, "PostgresStore", Mock(return_value=store))
    monkeypatch.setattr(wiring, "MeiliLexicalIndex", Mock(return_value=lexical))
    monkeypatch.setattr(wiring, "S3MediaStore", Mock(return_value=media))
    monkeypatch.setattr(wiring, "GitCanonicalStore", Mock(return_value=object()))
    monkeypatch.setattr(wiring, "build_embeddings", fail)
    monkeypatch.setattr(wiring, "QdrantVectorIndex", fail)
    settings = Settings(_env_file=None, semantic_retrieval="off", components="",
                        embedding_model="openrouter:synthetic/embedding", openrouter_api_key="")
    ctx = await wiring.build_context(settings, probe_agent=False)
    assert ctx.embeddings is None and ctx.vectors is None
    assert wiring.warn_missing_embedding_key(settings) == "semantic retrieval is off — no key needed"
    await ctx.aclose()
    store.aclose.assert_awaited_once()
    lexical.aclose.assert_awaited_once()
    media.aclose.assert_awaited_once()


def test_switch_is_an_engine_key_with_both_blast_radii(tmp_path):
    (tmp_path / "intake").mkdir()
    (tmp_path / "intake/intake.yaml").write_text('semantic_retrieval: "off"\n')
    overrides, origins = engine_overrides(tmp_path, {})
    assert overrides["semantic_retrieval"] == "off"
    assert origins["intake.semantic_retrieval"] == "engine"
    overrides, origins = engine_overrides(tmp_path, {"PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL": "on"})
    assert "semantic_retrieval" not in overrides
    assert origins["intake.semantic_retrieval"] == "env"
    effects = plan_effects(tmp_path, [Change("intake/intake.yaml", 'semantic_retrieval: "on"\n')])
    assert [(effect.key, effect.apply) for effect in effects] == [
        ("intake.semantic_retrieval", "restart"), ("intake.semantic_retrieval", "derived_rebuild")
    ]
    assert Settings(_env_file=None).semantic_retrieval == "on"
    with pytest.raises(ValueError):
        Settings(_env_file=None, semantic_retrieval="automatic")


async def test_preview_and_picker_apply_the_ceiling():
    from pneuma_knowledge_service.api.routes.v1 import list_intake_archetypes

    preview = preview_document("Synthetic chart", "# Survey\n\nThe delta shifted.",
                               intake_archetype="digest", semantic_retrieval=False)
    assert preview.proposed_plan.semantic_indexing == "none"
    assert preview.proposed_plan.canonical_treatment == "full"
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        ctx=SimpleNamespace(settings=Settings(_env_file=None, semantic_retrieval="off"))
    )))
    choices = await list_intake_archetypes(request)
    assert choices and all(choice.semantic_indexing == "none" for choice in choices)


@pytest.mark.parametrize("mode", ["full", "summary", "none"])
async def test_off_ingest_and_index_preserve_verbatim_and_lexical_access(monkeypatch, mode):
    lib = library(semantic_retrieval="off")
    lib.ctx.embeddings = lib.ctx.vectors = Forbidden()
    monkeypatch.setattr(compile_worker, "full_l2_chunks", fail)
    monkeypatch.setattr(compile_worker, "_summary_chunks", fail)
    monkeypatch.setattr(compile_worker, "embed_l2_chunks", fail)
    rows = {}
    async def index_blocks(user, sid, blocks, **kwargs):
        rows[(user, sid)] = blocks
    async def search(user, query, **kwargs):
        return [SimpleNamespace(source_id=sid, block_index=block.index, text=block.text, score=1)
                for (uid, sid), blocks in rows.items() if uid == user
                for block in blocks if query in block.text]
    lib.ctx.lexical = SimpleNamespace(index_blocks=index_blocks, search=search)
    result = await ingest_document(
        lib.ctx, USER, title="Synthetic survey", text="# Survey\n\nThe delta marker is cobalt.",
        plan_override={"canonical_treatment": "full", "semantic_indexing": mode},
    )
    ns = await lib.store.get(USER, result.source_id)
    assert ns.raw.intake_plan["semantic_indexing"] == "none"
    assert ns.raw.intake_plan["canonical_treatment"] == "full"
    assert ns.raw.intake_plan["semantic_indexing_requested"] == (None if mode == "none" else mode)
    job = await lib.store.claim_next(USER)
    await compile_worker.process_index_job(lib.ctx, USER, job)
    hits = await lib.ctx.lexical.search(USER, "cobalt")
    assert len(hits) == 1 and hits[0].source_id == result.source_id
    assert "cobalt" in await lib.store.fetch(USER, result.source_id, {"blocks": [hits[0].block_index, hits[0].block_index]})
    assert await lib.ctx.lexical.search(UserId("other-owner"), "cobalt") == []
    with pytest.raises(KeyError):
        await lib.store.fetch(UserId("other-owner"), result.source_id, {"blocks": [0, 0]})


async def test_old_queued_full_plan_is_also_skipped_while_off(monkeypatch):
    lib = library(semantic_retrieval="off")
    ns = source()
    ns.raw.intake_plan = IntakePlan(canonical_treatment="full", semantic_indexing="full", rationale="synthetic").model_dump()
    await lib.store.add(USER, ns)
    job_id = await lib.store.enqueue(USER, "index", {"source_id": str(ns.raw.source_id)})
    lib.ctx.lexical = SimpleNamespace(index_blocks=AsyncMock())
    lib.ctx.embeddings = lib.ctx.vectors = Forbidden()
    monkeypatch.setattr(compile_worker, "full_l2_chunks", fail)
    await compile_worker.process_index_job(lib.ctx, USER, await lib.store.claim_next(USER))
    lib.ctx.lexical.index_blocks.assert_awaited_once()
    assert ns.raw.intake_plan["semantic_indexing"] == "full", "the kept intake record is not rewritten"


@pytest.mark.parametrize("kind", ["meeting/v1", "document-library/v1", "im/v1", "email/v1", "owner-dialogue/v1"])
async def test_every_official_intake_contract_obeys_the_switch(kind):
    from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
    from pneuma_knowledge_service.ingest_sources import ingest_source_contract
    from test_owner_ingest_cli import _payload

    lib = library(semantic_retrieval="off")
    lib.ctx.embeddings = lib.ctx.vectors = Forbidden()
    result = await ingest_source_contract(lib.ctx, USER, parse_source_contract(_payload(kind)))
    assert result.sources
    for item in result.sources:
        normalized = await lib.store.get(USER, item.source_id)
        assert normalized.blocks
        assert item.intake_plan.semantic_indexing == "none"
        assert item.intake_plan.semantic_indexing_requested == "full"


async def test_confirming_an_off_preview_keeps_the_requested_mode_for_rebuild():
    lib = library(semantic_retrieval="off")
    preview = preview_document("Synthetic survey", "The delta is cobalt.", semantic_retrieval=False)
    result = await ingest_document(lib.ctx, USER, title="Synthetic survey", text="The delta is cobalt.",
                                   plan_override=preview.proposed_plan.model_dump())
    assert result.intake_plan.semantic_indexing == "none"
    assert result.intake_plan.semantic_indexing_requested == "full"


async def test_claim_projection_sync_and_rebuild_keep_pg_and_lexical_without_embeddings():
    from pneuma_knowledge_service.projection import rebuild_projection, sync_projection
    from test_projection_sync import USER as PROJECTION_USER, _ctx

    ctx = _ctx()
    ctx.vectors = ctx.embeddings = None
    result = await sync_projection(ctx, PROJECTION_USER, "synthetic-head")
    assert result.upserted == 2 and result.unchanged == 1
    assert ctx.store.synced[0] == PROJECTION_USER
    assert ctx.lexical.synced[1:] == ctx.store.synced[2:]
    ctx.store.replace_canonical_claims = AsyncMock()
    ctx.lexical.index_claims = AsyncMock()
    assert await rebuild_projection(ctx, PROJECTION_USER, "synthetic-head") == 3
    ctx.store.replace_canonical_claims.assert_awaited_once()
    claims = ctx.store.replace_canonical_claims.call_args.args[2]
    assert all(claim.citations for claim in claims)
    ctx.lexical.index_claims.assert_awaited_once_with(PROJECTION_USER, claims)


async def test_snapshots_copy_and_delete_the_lexical_library_while_off():
    from pneuma_knowledge_service import kb_snapshots
    from test_kb_snapshots import OWNER, _ctx

    ctx = _ctx()
    ctx.vectors = None
    snapshot = await kb_snapshots.create(ctx, OWNER, "synthetic lexical snapshot")
    ready = await kb_snapshots.run_copy(ctx, OWNER, snapshot)
    assert ready.ready and ready.counts["claims"] == 1
    assert ready.counts["points"] == ready.counts["chunks"] == 0
    assert ctx.store.sources[str(ready.tenant_id)] == ctx.store.sources[str(OWNER)]
    await kb_snapshots.delete(ctx, OWNER, ready.snapshot_id)
    assert ctx.store.sources[str(OWNER)]


async def test_turning_on_builds_missing_manifests_then_replays_without_rewriting_l0():
    from test_l2_manifest_replay import _ctx, _EpisodeModel, _Store, _record

    store = _Store()
    model = _EpisodeModel()
    ctx = _ctx(model, overlap="smart", store=store)
    ctx.settings.semantic_retrieval = "off"
    from test_l2_manifest_replay import SID, USER as MANIFEST_USER
    ns = source(str(SID), blocks=[f"Synthetic survey block {i}." for i in range(10)])
    plan = with_semantic_retrieval(IntakePlan(canonical_treatment="full", semantic_indexing="full", rationale="synthetic"), False)
    ns.raw.user_id = MANIFEST_USER
    ns.raw.intake_plan = plan.model_dump()
    original = ns.model_dump(mode="json")
    assert await wiring.plan_l2_chunks(ctx, SID, ns, MANIFEST_USER) == []
    assert not store.rows and not model.schemas
    ctx.settings.semantic_retrieval = "on"
    first = await wiring.plan_l2_chunks(ctx, SID, ns, MANIFEST_USER)
    assert first and _record(store)
    manifest = dict(_record(store))
    calls = len(model.schemas)
    second = await wiring.plan_l2_chunks(ctx, SID, ns, MANIFEST_USER)
    assert second == first
    assert len(model.schemas) == calls
    assert _record(store) == manifest
    assert ns.model_dump(mode="json") == original
    ctx.settings.semantic_retrieval = "off"
    assert await wiring.plan_l2_chunks(ctx, SID, ns, MANIFEST_USER) == []
    assert _record(store) == manifest
    ctx.settings.semantic_retrieval = "on"
    ns.raw.intake_plan = IntakePlan(canonical_treatment="none", semantic_indexing="none", rationale="owner choice").model_dump()
    assert await wiring.plan_l2_chunks(ctx, SID, ns, MANIFEST_USER) == []


async def test_semantic_cli_search_explains_the_disabled_arm():
    lib = library(semantic_retrieval="off")
    lib.ctx.embeddings = lib.ctx.vectors = None
    rt = ReadRuntime(USER, lib.ctx, out=io.StringIO(), err=io.StringIO())
    assert await cmd_search(rt, "cobalt", mode="semantic") == 1
    assert "semantic retrieval is off" in rt.err.getvalue()
    assert "--mode lexical" in rt.err.getvalue()


async def test_config_can_disable_semantics_before_embeddings_or_middleware_start(tmp_path, monkeypatch):
    from pneuma_knowledge_service import settings as settings_module
    from pneuma_knowledge_service.cli import config, isolation
    from pneuma_knowledge_service.engine.files import read_mapping

    settings = Settings(_env_file=None, engine_dir=str(tmp_path), embedding_model="openrouter:synthetic/embedding", openrouter_api_key="")
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(isolation, "project_isolation_problems", lambda _: [])
    monkeypatch.setattr(wiring, "build_context", fail)
    # The code uses the engine's normal apply path; this test writes only its temporary file.
    def apply(root, changes, label):
        for change in changes:
            path = root / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.content)
        return "synthetic-sha", []
    monkeypatch.setattr(config, "apply_changes", lambda root, changes, label: apply(Path(root), changes, label))
    args = build_parser().parse_args(["config", "set", "semantic_retrieval", "off"])
    assert await _run(args, (), build_parser) == 0
    assert read_mapping(tmp_path, "intake/intake.yaml")["semantic_retrieval"] == "off"


def _ops(name):
    path = Path(__file__).resolve().parents[3] / "scripts/ops" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"task3_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_ops_scripts_skip_l2_with_a_printed_line_and_still_rebuild_other_layers(monkeypatch, capsys):
    rebuild, reindex = _ops("rebuild_derived"), _ops("reindex_l2")
    lib = library(semantic_retrieval="off")
    ns = source()
    await lib.store.add(USER, ns)
    lib.ctx.vectors = lib.ctx.embeddings = Forbidden()
    lib.ctx.lexical = SimpleNamespace(delete_user=AsyncMock(), index_blocks=AsyncMock())
    projection, components = AsyncMock(return_value=2), AsyncMock()
    monkeypatch.setattr(rebuild, "rebuild_projection", projection)
    monkeypatch.setattr(rebuild, "rebuild_component_projections", components)
    monkeypatch.setattr(rebuild, "_chunks_for", fail)
    await rebuild.rebuild_user(lib.ctx, USER)
    assert "L2  skipped: semantic retrieval is off" in capsys.readouterr().out
    lib.ctx.lexical.index_blocks.assert_awaited_once()
    projection.assert_awaited_once_with(lib.ctx, USER)
    components.assert_awaited_once_with(lib.ctx, USER)
    await reindex.reindex_user(lib.ctx, USER)
    assert "L2  skipped" in capsys.readouterr().out
