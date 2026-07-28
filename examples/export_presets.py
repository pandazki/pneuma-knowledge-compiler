#!/usr/bin/env python
"""Export a preset demo user's FOUR layers to examples/data/preset/<friendly-id>/.

For each (source user_id → friendly id) pair this dumps every layer a fresh
machine needs to *browse already-processed data with no compilation*:

  L0/L3-pg  PostgreSQL — every table keyed by user_id (sources, blocks,
            chunk_manifests, compile_jobs, compile_events, canonical_claims,
            briefings, user_profiles), deterministic order, gzipped JSON.
  L1        Meilisearch — the per-user blocks_<uid> + claims_<uid> index documents
            (the index name is the tenant boundary; docs carry no user_id).
  L2        Qdrant — every point for the tenant (chunk + claim layer) WITH its
            vector + payload; the point id is recomputed on import from the payload,
            so we ship vectors, never re-embed (no OpenRouter key needed to import).
  L3-git    the per-user canonical git repo, as a tar (the one non-rebuildable layer).

A manifest.json records the source uid, per-layer counts, PG column types (so import
knows which columns are jsonb / timestamptz), the embedding model + vector dim the
shipped vectors were produced with, and the friendly id.

Run against the stack that HOLDS the data (the main compose stack is fine — this is
read-only). Uses direct adapters/clients, so it needs NO OpenRouter key.

Usage:
    uv run python examples/export_presets.py
    uv run python examples/export_presets.py <source_uid>=<friendly_id> [...]
"""

from __future__ import annotations

import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from meilisearch_python_sdk import Client as MeiliClient
from meilisearch_python_sdk.errors import MeilisearchApiError
from psycopg_pool import ConnectionPool
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_service.settings import Settings

# Public default preset: a synthetic OPC developer processed through all four layers.
# friendly id → source user_id.
DEFAULT_PRESETS = {
    "u-opc-lin": "u-opc-lin",
}

# Deterministic per-table sort (primary keys) so a re-export is byte-stable.
PG_TABLES = {
    "sources": ["source_id"],
    "blocks": ["source_id", "block_index"],
    "chunk_manifests": ["source_id"],
    "compile_jobs": ["id"],
    "compile_events": ["job_id", "seq"],
    "canonical_claims": ["document_path", "anchor"],
    "briefings": ["briefing_id"],
    "user_profiles": ["user_id"],
    "evolve_tasks": ["task_id"],
}

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
PRESET_ROOT = Path(__file__).resolve().parent / "data" / "preset"


def _json_default(o):
    # timestamptz columns arrive as datetime → ISO string; import re-parses them by
    # consulting the per-column type map (never by sniffing the value), so a jsonb
    # column that merely holds a timestamp-looking string is never misread.
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not JSON-serializable: {type(o)}")


def _gz_writer(path: Path):
    """GzipFile with mtime=0 so the compressed bytes are reproducible run-to-run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return gzip.GzipFile(filename=str(path), mode="wb", mtime=0)


def _write_gz_json(path: Path, obj) -> int:
    raw = json.dumps(obj, ensure_ascii=False, default=_json_default).encode("utf-8")
    with _gz_writer(path) as fh:
        fh.write(raw)
    return path.stat().st_size


def _column_types(pool: ConnectionPool) -> dict[str, dict[str, str]]:
    """table -> {column: data_type} for the preset tables (import replays types)."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT table_name, column_name, ordinal_position, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name = ANY(%s) "
            "ORDER BY table_name, ordinal_position",
            (list(PG_TABLES),),
        ).fetchall()
    out: dict[str, dict[str, str]] = {}
    order: dict[str, list[str]] = {}
    for tbl, col, _pos, dtype in rows:
        out.setdefault(tbl, {})[col] = dtype
        order.setdefault(tbl, []).append(col)
    return out, order


def export_pg(pool, uid, types, order, out_dir) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tbl, sort_cols in PG_TABLES.items():
        cols = order[tbl]
        col_types = types[tbl]
        order_by = ", ".join(sort_cols)
        with pool.connection() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM {tbl} "
                f"WHERE user_id = %s ORDER BY {order_by}",
                (uid,),
            ).fetchall()
        records = []
        for r in rows:
            rec = {}
            for col, val in zip(cols, r):
                # datetimes come back as datetime; wrap via _json_default. jsonb comes
                # back as python obj already; everything else is a scalar.
                rec[col] = val
            records.append(rec)
        _write_gz_json(out_dir / "pg" / f"{tbl}.json.gz", records)
        counts[tbl] = len(records)
    return counts


def export_qdrant(qc, collection, uid, out_dir) -> tuple[int, int]:
    chunk, claim = 0, 0
    path = out_dir / "qdrant" / "points.jsonl.gz"
    with io.TextIOWrapper(_gz_writer(path), encoding="utf-8") as fh:
        next_off = None
        while True:
            points, next_off = qc.scroll(
                collection,
                scroll_filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="user_id",
                        match=qmodels.MatchValue(value=uid))]),
                limit=256, offset=next_off,
                with_payload=True, with_vectors=True,
            )
            for p in points:
                payload = dict(p.payload or {})
                if payload.get("layer") == "claim":
                    claim += 1
                else:
                    chunk += 1
                fh.write(json.dumps(
                    {"payload": payload, "vector": list(p.vector)},
                    ensure_ascii=False) + "\n")
            if next_off is None:
                break
    return chunk, claim


def _meili_all_docs(index) -> list[dict]:
    # meilisearch-python-sdk takes limit/offset as keyword args (the old official client
    # took a dict) and already hands back plain dicts in `.results`.
    docs, offset = [], 0
    while True:
        batch = index.get_documents(limit=1000, offset=offset).results
        if not batch:
            break
        docs.extend(dict(d) for d in batch)
        offset += len(batch)
        if len(batch) < 1000:
            break
    return docs


def export_meili(mc, uid, out_dir) -> tuple[int, int]:
    safe = _UID_SAFE.sub("_", uid)
    counts = {}
    for face in ("blocks", "claims"):
        try:
            docs = _meili_all_docs(mc.index(f"{face}_{safe}"))
        except MeilisearchApiError:
            docs = []
        _write_gz_json(out_dir / "meili" / f"{face}.json.gz", docs)
        counts[face] = len(docs)
    return counts["blocks"], counts["claims"]


def export_canonical(canonical_root, uid, out_dir) -> int:
    safe = _UID_SAFE.sub("_", uid)
    repo = Path(canonical_root) / safe
    if not (repo / ".git").is_dir():
        raise SystemExit(f"canonical repo missing for {uid} at {repo}")
    tar_path = out_dir / "canonical.tar.gz"
    # Deterministic tar: sorted names, zeroed mtime/uid/gid, and the gzip wrapper's own
    # header mtime zeroed (via _gz_writer) — tarfile("w:gz") would otherwise stamp the
    # current time into the gzip header, making identical content hash differently.
    with tarfile.open(fileobj=_gz_writer(tar_path), mode="w") as tar:
        for p in sorted(repo.rglob("*"), key=lambda x: str(x.relative_to(repo))):
            arc = p.relative_to(repo)
            ti = tar.gettarinfo(str(p), arcname=str(arc))
            ti.mtime = 0
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            if ti.isfile():
                with open(p, "rb") as f:
                    tar.addfile(ti, f)
            else:
                tar.addfile(ti)
    ncommits = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    return int(ncommits or 0)


def main() -> int:
    args = sys.argv[1:]
    if args:
        presets = {}
        for a in args:
            friendly, _, src = a.partition("=")
            presets[friendly] = src
    else:
        presets = DEFAULT_PRESETS

    settings = Settings()
    pool = ConnectionPool(settings.pg_dsn, min_size=1, max_size=4, open=True)
    qc = QdrantClient(url=settings.qdrant_url)
    mc = MeiliClient(settings.meili_url, settings.meili_key or None)
    coll = qc.get_collection(settings.qdrant_collection)
    dim = coll.config.params.vectors.size
    types, order = _column_types(pool)

    try:
        for friendly, src in presets.items():
            out_dir = PRESET_ROOT / friendly
            print(f"\n== export {src} → {friendly} ==")
            # Fail BEFORE any file is written: a mistyped/mis-ordered src (args are
            # <friendly>=<src>) once clobbered an existing bundle with empty dumps —
            # the canonical check alone came too late to protect the pg/meili files.
            src_repo = Path(settings.canonical_root) / _UID_SAFE.sub("_", src)
            with pool.connection() as _c:
                _n = _c.execute(
                    "SELECT count(*) FROM sources WHERE user_id = %s", (src,)
                ).fetchone()[0]
            if _n == 0 and not (src_repo / ".git").is_dir():
                raise SystemExit(
                    f"source user {src!r} has no data (0 sources, no canonical repo) — "
                    f"refusing to export an empty bundle over {out_dir}. "
                    "Args are <friendly_id>=<source_uid>."
                )
            pg_counts = export_pg(pool, src, types, order, out_dir)
            q_chunk, q_claim = export_qdrant(qc, settings.qdrant_collection, src, out_dir)
            m_blocks, m_claims = export_meili(mc, src, out_dir)
            n_commits = export_canonical(settings.canonical_root, src, out_dir)

            manifest = {
                "friendly_id": friendly,
                "source_user_id": src,
                "embedding_model": settings.embedding_model,
                "vector_dim": dim,
                "qdrant_distance": str(coll.config.params.vectors.distance),
                "pg_column_types": types,
                "pg_column_order": order,
                "counts": {
                    "pg": pg_counts,
                    "qdrant_chunks": q_chunk,
                    "qdrant_claims": q_claim,
                    "meili_blocks": m_blocks,
                    "meili_claims": m_claims,
                    "canonical_commits": n_commits,
                },
            }
            (out_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            print(f"  PG {pg_counts}")
            print(f"  Qdrant chunks={q_chunk} claims={q_claim} (dim={dim})")
            print(f"  Meili blocks={m_blocks} claims={m_claims}")
            print(f"  canonical commits={n_commits}")
            total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
            print(f"  bundle size: {total/1e6:.2f} MB → {out_dir}")
    finally:
        pool.close()
    print("\nOK: preset export complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
