#!/usr/bin/env python
"""Import preset demo users (four layers) onto a clean stack — NO OpenRouter key needed.

Loads what examples/export_presets.py dumped and renames the tenant from the source
user_id to the friendly id across every layer, so a fresh machine can browse
already-processed data and (with a key in .env) answer fast/deep — WITHOUT ever
compiling or re-embedding:

  PG      apply schema, then bulk-insert every preset table with user_id → friendly.
  Qdrant  create the shared collection at the SHIPPED vector dim, then upsert each point
          with its shipped vector and a RECOMPUTED deterministic point id (uuid5 over the
          friendly id + payload), payload.user_id rewritten. Vectors are shipped —
          import never calls an embedding provider.
  Meili   create blocks_<friendly> / claims_<friendly> and add the shipped documents.
  git     extract the canonical repo tar into <canonical_root>/<friendly>/.

Idempotent: each friendly user is fully wiped (all four layers) before load, so a re-run
replaces cleanly.

Usage:
    uv run python examples/import_presets.py                 # every bundle under data/preset
    uv run python examples/import_presets.py u-opc-lin      # only this friendly id

Run against the stack you want populated (docker compose up --wait). Needs the three
middleware endpoints from .env / defaults; needs NO OPENROUTER_API_KEY.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import asyncio
import sys
import tarfile
import uuid
from datetime import datetime
from pathlib import Path

from psycopg.types.json import Json
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qmodels

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_service.adapters.meilisearch import MeiliLexicalIndex, _claims_index_uid, _index_uid
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.adapters.qdrant import _POINT_NS, LAYER_CLAIM, QdrantVectorIndex
from pneuma_knowledge_service.settings import Settings

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
PRESET_ROOT = Path(__file__).resolve().parent / "data" / "preset"

# Insert order respects FKs (blocks/chunk_manifests reference sources).
PG_INSERT_ORDER = [
    "sources", "blocks", "chunk_manifests", "compile_jobs",
    "compile_events", "canonical_claims", "briefings", "user_profiles",
    "evolve_tasks",
]


def _read_gz_json(path: Path):
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read())


def _point_id(uid: str, payload: dict) -> str:
    """Recompute the deterministic Qdrant point id for the NEW tenant, mirroring the
    adapter's uuid5 scheme exactly (import must not drift from QdrantVectorIndex)."""
    if payload.get("layer") == LAYER_CLAIM:
        key = f"{uid}:claim:{payload['document_path']}:{payload['anchor']}"
    else:
        cs = payload.get("char_start", payload.get("block_start"))
        ce = payload.get("char_end", payload.get("block_end"))
        key = f"{uid}:{payload['source_id']}:{cs}:{ce}"
    return str(uuid.uuid5(_POINT_NS, key))


async def import_pg(pool, friendly, bundle, types) -> dict[str, int]:
    counts = {}
    async with pool.connection() as conn:
        for tbl in PG_INSERT_ORDER:
            tbl_path = bundle / "pg" / f"{tbl}.json.gz"
            if not tbl_path.is_file():
                # Dumps predating a table (e.g. evolve_tasks) simply lack the file.
                counts[tbl] = 0
                continue
            recs = _read_gz_json(tbl_path)
            counts[tbl] = len(recs)
            if not recs:
                continue
            cols = list(recs[0].keys())
            col_types = types[tbl]
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({placeholders})"
            rows = []
            _NS = uuid.uuid5(uuid.NAMESPACE_URL, "pneuma-knowledge-preset-import")

            def _remap_id(old_id: str) -> str:
                # compile_jobs.id / compile_events.job_id / evolve_tasks.task_id are
                # Global keys may collide when bundles share history. Namespace per friendly,
                # deterministically, so re-imports stay idempotent.
                return uuid.uuid5(_NS, f"{friendly}:{old_id}").hex

            for rec in recs:
                vals = []
                for c in cols:
                    v = rec[c]
                    if c == "user_id":
                        v = friendly
                    elif (
                        (tbl == "compile_jobs" and c == "id")
                        or (tbl == "compile_events" and c == "job_id")
                        or (tbl == "evolve_tasks" and c == "task_id")
                        or (tbl == "briefings" and c == "briefing_id")
                    ) and v is not None:
                        v = _remap_id(str(v))
                    elif col_types.get(c) == "jsonb":
                        v = Json(v) if v is not None else None
                    elif col_types.get(c) == "timestamp with time zone" and v is not None:
                        v = datetime.fromisoformat(v)
                    vals.append(v)
                rows.append(tuple(vals))
            async with conn.cursor() as cur:
                await cur.executemany(sql, rows)
    return counts


async def import_qdrant(qc, collection, friendly, bundle) -> tuple[int, int]:
    chunk, claim = 0, 0
    points = []
    with gzip.open(bundle / "qdrant" / "points.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            payload = dict(obj["payload"])
            payload["user_id"] = friendly
            if payload.get("layer") == LAYER_CLAIM:
                claim += 1
            else:
                chunk += 1
            points.append(qmodels.PointStruct(
                id=_point_id(friendly, payload),
                vector=obj["vector"],
                payload=payload,
            ))
    for i in range(0, len(points), 256):
        await qc.upsert(collection, points=points[i:i + 256], wait=True)
    return chunk, claim


async def import_meili(mli: MeiliLexicalIndex, friendly, bundle) -> tuple[int, int]:
    client = mli._client
    out = {}
    for face, uid_fn, ensure in (
        ("blocks", _index_uid, mli._ensure_index),
        ("claims", _claims_index_uid, mli._ensure_claims_index),
    ):
        docs = _read_gz_json(bundle / "meili" / f"{face}.json.gz")
        uid = uid_fn(friendly)
        await ensure(uid)  # configure searchable/displayed attributes exactly like the app
        if docs:
            task = await client.index(uid).add_documents(docs, primary_key="id")
            await client.wait_for_task(task.task_uid)
        out[face] = len(docs)
    return out["blocks"], out["claims"]


def import_canonical(canonical_root, friendly, bundle) -> None:
    dest = Path(canonical_root) / _UID_SAFE.sub("_", friendly)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle / "canonical.tar.gz", "r:gz") as tar:
        tar.extractall(dest, filter="data")


async def wipe_friendly(store, qc, collection, mli, canonical_root, friendly) -> None:
    """Full idempotent wipe across all four layers for a friendly id."""
    await store.delete_user(friendly)  # PG: sources(+cascade blocks/chunk_manifests) + rest
    await qc.delete(collection, points_selector=qmodels.FilterSelector(
        filter=qmodels.Filter(must=[qmodels.FieldCondition(
            key="user_id", match=qmodels.MatchValue(value=friendly))])), wait=True)
    await mli.delete_user(friendly)
    dest = Path(canonical_root) / _UID_SAFE.sub("_", friendly)
    if dest.exists():
        shutil.rmtree(dest)


async def run() -> int:
    wanted = set(sys.argv[1:])
    settings = Settings()

    bundles = sorted(p for p in PRESET_ROOT.iterdir()
                     if (p / "manifest.json").is_file()) if PRESET_ROOT.is_dir() else []
    if wanted:
        bundles = [b for b in bundles if b.name in wanted]
    if not bundles:
        print(f"no preset bundles found under {PRESET_ROOT}", file=sys.stderr)
        return 2

    store = PostgresStore(settings.pg_dsn)
    await store.open()
    await store.apply_schema()  # ensure schema exists before load (clean stack)
    pool = store._pool
    qc = AsyncQdrantClient(url=settings.qdrant_url)
    mli = MeiliLexicalIndex(settings.meili_url, settings.meili_key or None)

    try:
        for bundle in bundles:
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            friendly = manifest["friendly_id"]
            dim = int(manifest["vector_dim"])
            # Ensure the shared collection exists at the SHIPPED dim (no embedding probe).
            probe = QdrantVectorIndex(
                settings.qdrant_url, dim, collection=settings.qdrant_collection
            )
            await probe.ensure_collection()
            await probe.aclose()

            print(f"\n== import {bundle.name} (from {manifest['source_user_id']}) ==")
            await wipe_friendly(store, qc, settings.qdrant_collection, mli,
                                settings.canonical_root, friendly)

            pg = await import_pg(pool, friendly, bundle, manifest["pg_column_types"])
            qchunk, qclaim = await import_qdrant(
                qc, settings.qdrant_collection, friendly, bundle
            )
            mblocks, mclaims = await import_meili(mli, friendly, bundle)
            import_canonical(settings.canonical_root, friendly, bundle)

            print(f"  PG {pg}")
            print(f"  Qdrant chunks={qchunk} claims={qclaim} (dim={dim})")
            print(f"  Meili blocks={mblocks} claims={mclaims}")
            exp = manifest["counts"]
            ok = (qchunk == exp["qdrant_chunks"] and qclaim == exp["qdrant_claims"]
                  and mblocks == exp["meili_blocks"] and mclaims == exp["meili_claims"]
                  and pg["canonical_claims"] == exp["pg"]["canonical_claims"])
            print(f"  reconcile vs manifest: {'OK' if ok else 'MISMATCH'}")
    finally:
        await store.aclose()
        await mli.aclose()
        await qc.close()
    print("\nOK: preset import complete — users now visible at GET /v1/users")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
