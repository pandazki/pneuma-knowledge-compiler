"""Official import acknowledges L0 and its jobs as one transaction in an isolated PG DB."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.intake import IntakePlan
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.source_receipt import SourceImportJob

USER = UserId("synthetic-atomic-owner")
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def bundle():
    return parse_source_contract({
        "schema": "pneuma.source.document-library/v1", "provider": "mock",
        "library_id": "synthetic-atomic-library", "title": "Synthetic working notes",
        "documents": [
            {"document_id": f"note-{index}", "path": f"notes/{index}.md", "title": f"Note {index}",
             "content": f"Synthetic decision {index}: preserve the original evidence.",
             "frontmatter": {}, "tags": [], "links": []}
            for index in range(2)
        ],
    })


def plan(treatment="full"):
    return IntakePlan(canonical_treatment=treatment, semantic_indexing="none",
                      rationale="Synthetic explicit intake", user_confirmed=True)


@dataclass(repr=False)
class IsolatedPg:
    store: PostgresStore
    dsn: str
    ctx: object

    def __repr__(self):
        return "<isolated synthetic PostgreSQL test database>"


@pytest.fixture
async def isolated_pg():
    # Connect only to the server's maintenance database, then create a dedicated random
    # database. No DDL, fault trigger, source or job touches the configured application DB.
    settings = Settings()
    admin_dsn = make_conninfo(settings.pg_dsn, dbname="postgres", connect_timeout=2)
    try:
        admin = await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres middleware unreachable")
    name = "pkc_atomic_test_" + uuid.uuid4().hex[:16]
    await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(settings.pg_dsn, dbname=name, connect_timeout=2)
    store = PostgresStore(dsn, application_name="synthetic-atomic-import-test")
    try:
        await store.open()
        await store.apply_schema()
        ctx = SimpleNamespace(store=store, media=None, settings=settings)
        yield IsolatedPg(store=store, dsn=dsn, ctx=ctx)
    finally:
        await store.aclose()
        await admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        await admin.close()


async def rows(pg, query, args=()):
    async with await psycopg.AsyncConnection.connect(pg.dsn) as conn:
        return await (await conn.execute(query, args)).fetchall()


@pytest.mark.parametrize("failure", ["blocks", "index", "compile"])
async def test_failure_rolls_back_every_source_block_and_job_before_retry(isolated_pg, failure):
    pg = isolated_pg
    table = "blocks" if failure == "blocks" else "compile_jobs"
    condition = sql.SQL("") if failure == "blocks" else sql.SQL("WHEN (NEW.kind = {}) ").format(sql.Literal(failure))
    async with await psycopg.AsyncConnection.connect(pg.dsn) as conn:
        await conn.execute("CREATE FUNCTION reject_synthetic_import() RETURNS trigger LANGUAGE plpgsql AS $$ "
                           "BEGIN RAISE EXCEPTION 'synthetic atomic import failure'; END $$")
        await conn.execute(sql.SQL("CREATE TRIGGER reject_synthetic BEFORE INSERT ON {} "
                                   "FOR EACH ROW {}EXECUTE FUNCTION reject_synthetic_import()").format(
                                       sql.Identifier(table), condition))
    with pytest.raises(psycopg.errors.RaiseException, match="synthetic atomic import failure"):
        await ingest_source_contract(pg.ctx, USER, bundle(), intake_plan=plan())
    assert await rows(pg, "SELECT count(*) FROM sources") == [(0,)]
    assert await rows(pg, "SELECT count(*) FROM blocks") == [(0,)]
    assert await rows(pg, "SELECT count(*) FROM compile_jobs") == [(0,)]
    async with await psycopg.AsyncConnection.connect(pg.dsn) as conn:
        await conn.execute(sql.SQL("DROP TRIGGER reject_synthetic ON {}").format(sql.Identifier(table)))
    receipt = await ingest_source_contract(pg.ctx, USER, bundle(), intake_plan=plan(), about_paths=["work/synthetic.md"])
    assert len(receipt.sources) == 2 and not any(item.deduplicated for item in receipt.sources)
    assert len(receipt.compile_jobs) == 2
    queued = await rows(pg, "SELECT kind, payload, created_at FROM compile_jobs WHERE user_id = %s ORDER BY created_at", (str(USER),))
    ids = [str(item.source_id) for item in receipt.sources]
    assert [kind for kind, _, _ in queued] == ["index", "index", "compile", "compile"]
    assert [item[1]["source_id"] for item in queued[:2]] == ids
    assert [item[1]["source_ids"][0] for item in queued[2:]] == ids
    assert all(item[1]["about_paths"] == ["work/synthetic.md"] for item in queued[2:])
    assert all(left[2] < right[2] for left, right in zip(queued, queued[1:]))
    # The original caller may have lost this successful response. Exact retry acknowledges
    # the same evidence, with no second job even if the requested policy has since changed.
    replay = await ingest_source_contract(pg.ctx, USER, bundle(), intake_plan=plan("none"))
    assert all(item.deduplicated and item.intake_plan.canonical_treatment == "full" for item in replay.sources)
    assert not replay.compile_jobs
    assert len(await rows(pg, "SELECT id FROM compile_jobs")) == 4


async def test_concurrent_identical_imports_enqueue_once_per_tenant(isolated_pg):
    pg = isolated_pg
    receipts = await asyncio.gather(*(
        ingest_source_contract(pg.ctx, USER, bundle(), intake_plan=plan()) for _ in range(8)
    ))
    assert sum(not receipt.sources[0].deduplicated for receipt in receipts) == 1
    assert sum(len(receipt.compile_jobs) for receipt in receipts) == 2
    ids = [str(item.source_id) for item in receipts[0].sources]
    assert all([str(item.source_id) for item in receipt.sources] == ids for receipt in receipts)
    assert await rows(pg, "SELECT count(*) FROM sources WHERE user_id = %s", (str(USER),)) == [(2,)]
    assert await rows(pg, "SELECT count(*) FROM compile_jobs WHERE user_id = %s", (str(USER),)) == [(4,)]
    other = UserId("synthetic-other-owner")
    with pytest.raises(KeyError):
        await pg.store.get(other, SourceId(ids[0]))
    another = await ingest_source_contract(pg.ctx, other, bundle(), intake_plan=plan("none"))
    assert [str(item.source_id) for item in another.sources] == ids
    assert not any(item.deduplicated for item in another.sources)
    assert not another.compile_jobs
    assert await rows(pg, "SELECT count(*) FROM compile_jobs WHERE user_id = %s", (str(other),)) == [(2,)]
    assert all(item.raw.user_id == other for item in [await pg.store.get(other, SourceId(sid)) for sid in ids])


async def test_source_identity_collision_refuses_whole_bundle(isolated_pg):
    pg = isolated_pg
    normalized = normalize_source_contract(bundle(), USER, imported_at=NOW)
    original = normalized[0]
    original.raw.intake_plan = plan().model_dump()
    await pg.store.add(USER, original)
    collision = original.model_copy(deep=True)
    collision.raw.checksum = "synthetic-different-evidence"
    jobs = [SourceImportJob(source.raw.source_id, "index", {"source_id": str(source.raw.source_id)})
            for source in [normalized[1], collision]]
    with pytest.raises(RuntimeError, match="source identity collision"):
        await pg.store.add_sources_with_jobs(USER, [normalized[1], collision], jobs)
    assert await rows(pg, "SELECT count(*) FROM sources") == [(1,)]
    assert await rows(pg, "SELECT count(*) FROM compile_jobs") == [(0,)]
    saved = await pg.store.get(USER, original.raw.source_id)
    assert saved.raw.checksum == original.raw.checksum


async def test_checksum_dedup_returns_legacy_identity_without_rewriting_plan(isolated_pg):
    pg = isolated_pg
    contract = bundle()
    sources = normalize_source_contract(contract, USER, imported_at=NOW)
    originals = []
    for index, source in enumerate(sources):
        source.raw.source_id = SourceId(f"legacy-synthetic-{index}")
        source.raw.intake_plan = plan("none").model_dump()
        originals.append(source.raw.source_id)
        await pg.store.add(USER, source)
    receipt = await ingest_source_contract(pg.ctx, USER, contract, intake_plan=plan())
    assert [item.source_id for item in receipt.sources] == originals
    assert all(item.deduplicated and item.intake_plan.canonical_treatment == "none" for item in receipt.sources)
    assert not receipt.compile_jobs
    assert await rows(pg, "SELECT count(*) FROM compile_jobs") == [(0,)]
