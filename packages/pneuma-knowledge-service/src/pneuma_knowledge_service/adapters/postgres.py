"""PG-backed ContentStore + JobQueue (architecture.md §5).

Append-only content authority (L0). psycopg3 + connection pool, plain SQL, no ORM.
Every row is keyed by user_id first (invariant I1); there is no query path that
omits it. Content dedup: same user + same checksum returns the existing source_id
(append-only, never overwrites). The compile queue claims per-user serially via
`FOR UPDATE SKIP LOCKED` — the single-writer guarantee for the git canonical layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import (
    Locator,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from ..snapshot_tenant import RESERVED_PREFIX

_SCHEMA_PATH = Path(__file__).resolve().parents[5] / "infra" / "schema.sql"


class _JobRow:
    """Concrete JobQueue.Job — attributes match the Job protocol."""

    def __init__(
        self, job_id: str, user_id: UserId, kind: str, payload: dict[str, Any]
    ) -> None:
        self.job_id = job_id
        self.user_id = user_id
        self.kind = kind
        self.payload = payload


class PostgresStore:
    """ContentStore + JobQueue over one PG connection pool."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        # `open=False`: psycopg warns when an AsyncConnectionPool is opened from a
        # constructor (there may be no running loop, and the pool would then bind to
        # whichever loop happens to be current). Ownership is explicit instead — the
        # FastAPI lifespan / worker main / test fixture calls `await open()`, `await aclose()`.
        self._pool = AsyncConnectionPool(
            dsn, min_size=min_size, max_size=max_size, open=False
        )

    async def open(self) -> None:
        """Open the connection pool on the caller's event loop."""
        await self._pool.open()

    async def apply_schema(self) -> None:
        """Idempotently apply infra/schema.sql (v1 migration strategy, §5)."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._pool.connection() as conn:
            await conn.execute(sql)

    async def aclose(self) -> None:
        await self._pool.close()

    # --- ContentStore ---------------------------------------------------------

    async def add(self, user_id: UserId, source: NormalizedSource) -> SourceId:
        raw = source.raw
        async with self._pool.connection() as conn:
            async with conn.transaction():
                existing = await (await conn.execute(
                    "SELECT source_id FROM sources "
                    "WHERE user_id = %s AND checksum = %s",
                    (str(user_id), raw.checksum),
                )).fetchone()
                if existing is not None:
                    return SourceId(existing[0])

                await conn.execute(
                    "INSERT INTO sources (user_id, source_id, kind, "
                    "source_class, title, mime, checksum, created_at, meta, "
                    "intake_plan, structure_map, origin) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(user_id),
                        str(raw.source_id),
                        raw.kind,
                        raw.source_class,
                        raw.title,
                        raw.mime,
                        raw.checksum,
                        raw.created_at,
                        Json(raw.meta),
                        Json(raw.intake_plan) if raw.intake_plan is not None else None,
                        Json(source.structure.model_dump()),
                        raw.origin,
                    ),
                )
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO blocks (user_id, source_id, block_index, "
                        "text, section_path) VALUES (%s, %s, %s, %s, %s)",
                        [
                            (
                                str(user_id),
                                str(raw.source_id),
                                b.index,
                                b.text,
                                Json(b.section_path),
                            )
                            for b in source.blocks
                        ],
                    )
        return raw.source_id

    async def get(self, user_id: UserId, source_id: SourceId) -> NormalizedSource:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT kind, source_class, title, mime, checksum, created_at, "
                "meta, intake_plan, structure_map, origin FROM sources "
                "WHERE user_id = %s AND source_id = %s",
                (str(user_id), str(source_id)),
            )).fetchone()
            if row is None:
                raise KeyError(f"source not found: {source_id!r}")
            raw = self._raw_from_row(user_id, source_id, row, origin=row[9])
            structure = StructureMap.model_validate(row[8])
            blocks = [
                NormalizedBlock(index=r[0], text=r[1], section_path=r[2])
                for r in await (await conn.execute(
                    "SELECT block_index, text, section_path FROM blocks "
                    "WHERE user_id = %s AND source_id = %s ORDER BY block_index",
                    (str(user_id), str(source_id)),
                )).fetchall()
            ]
        return NormalizedSource(raw=raw, blocks=blocks, structure=structure)

    async def list_users(self) -> list[str]:
        """Distinct user_ids that own at least one source.

        This is an administrative/UI listing (the M2 experiment-bench user
        switcher), not a per-user data read path — it returns only the id set,
        never any user's content, so invariant I1's "no cross-user read of data"
        holds.

        Frozen snapshot tenants are excluded: they hold a copy of some user's rows, so they
        would otherwise appear in the user switcher as N phantom users owning the same data.
        A snapshot is reached through its owner's snapshot list, never as a user.
        """
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT DISTINCT user_id FROM sources "
                "WHERE user_id NOT LIKE %s ORDER BY user_id",
                (f"{RESERVED_PREFIX}%",),
            )).fetchall()
        return [r[0] for r in rows]

    async def workspace_counts(self, user_id: UserId) -> dict[str, int]:
        """Bounded overview counts without loading any collection rows."""
        uid = str(user_id)
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT "
                "(SELECT count(*) FROM sources WHERE user_id = %s), "
                "(SELECT count(*) FROM compile_jobs WHERE user_id = %s), "
                "(SELECT count(DISTINCT document_path) FROM canonical_claims "
                " WHERE user_id = %s), "
                "(SELECT count(*) FROM canonical_claims WHERE user_id = %s)",
                (uid, uid, uid, uid),
            )).fetchone()
        assert row is not None
        return {
            "sources": int(row[0]),
            "jobs": int(row[1]),
            "documents": int(row[2]),
            "claims": int(row[3]),
        }

    async def block_counts(
        self, user_id: UserId, source_ids: list[str] | None = None
    ) -> dict[str, int]:
        """source_id → block count for one user (single grouped query, no N+1)."""
        if source_ids == []:
            return {}
        source_filter = " AND source_id = ANY(%s)" if source_ids is not None else ""
        params: list[Any] = [str(user_id)]
        if source_ids is not None:
            params.append(source_ids)
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, count(*) FROM blocks "
                f"WHERE user_id = %s{source_filter} GROUP BY source_id",
                params,
            )).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    # --- chunk manifest (semantic-chunk determinism, §M5) ---------------------

    async def get_chunk_manifest(
        self, user_id: UserId, source_id: SourceId
    ) -> dict | None:
        """The recorded segmentation for a source, or None. Callers reuse it only when
        strategy + model + content_digest still match (a byte-deterministic replay)."""
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT strategy, model, content_digest, segments, result_digest "
                "FROM chunk_manifests WHERE user_id = %s AND source_id = %s",
                (str(user_id), str(source_id)),
            )).fetchone()
        if row is None:
            return None
        return {
            "strategy": row[0],
            "model": row[1],
            "content_digest": row[2],
            "segments": row[3],
            "result_digest": row[4],
        }

    async def put_chunk_manifest(
        self,
        user_id: UserId,
        source_id: SourceId,
        *,
        strategy: str,
        model: str,
        content_digest: str,
        segments: dict | list,
        result_digest: str,
    ) -> None:
        """Upsert the segmentation the LLM produced for this (source, strategy, model).

        `segments` is whatever `ingest.semantic.encode_manifest_segments` produced — today a
        versioned envelope, historically a bare list. The column is jsonb and the adapter
        stores it opaquely: what a record MEANS is core's business, not the store's."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO chunk_manifests (user_id, source_id, strategy, "
                "model, content_digest, segments, result_digest, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (user_id, source_id) DO UPDATE SET "
                "strategy = EXCLUDED.strategy, model = EXCLUDED.model, "
                "content_digest = EXCLUDED.content_digest, "
                "segments = EXCLUDED.segments, result_digest = EXCLUDED.result_digest, "
                "updated_at = now()",
                (
                    str(user_id),
                    str(source_id),
                    strategy,
                    model,
                    content_digest,
                    Json(segments),
                    result_digest,
                ),
            )

    async def list(self, user_id: UserId) -> list[RawSource]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, kind, source_class, title, mime, checksum, "
                "created_at, meta, intake_plan, origin FROM sources "
                "WHERE user_id = %s ORDER BY created_at",
                (str(user_id),),
            )).fetchall()
        return [
            self._raw_from_row(
                user_id,
                SourceId(r[0]),
                (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]),
                origin=r[9],
            )
            for r in rows
        ]

    async def list_sources_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        before: tuple[datetime, str] | None = None,
        query: str | None = None,
        kind: str | None = None,
    ) -> tuple[list[RawSource], int, bool]:
        """One keyset-paginated source page, newest first.

        The count and page query apply the same user/filter predicate. Only ``limit + 1``
        source rows cross the storage boundary; the extra row determines ``has_more``.
        """
        filters = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if query:
            filters.append("title ILIKE %s")
            params.append(f"%{query}%")
        if kind:
            filters.append("kind = %s")
            params.append(kind)
        filtered_where = " AND ".join(filters)

        page_filters = list(filters)
        page_params = list(params)
        if before is not None:
            page_filters.append("(created_at, source_id) < (%s, %s)")
            page_params.extend(before)
        page_where = " AND ".join(page_filters)

        async with self._pool.connection() as conn:
            count_row = await (await conn.execute(
                f"SELECT count(*) FROM sources WHERE {filtered_where}",
                params,
            )).fetchone()
            rows = await (await conn.execute(
                "SELECT source_id, kind, source_class, title, mime, checksum, "
                "created_at, meta, intake_plan, origin FROM sources "
                f"WHERE {page_where} "
                "ORDER BY created_at DESC, source_id DESC LIMIT %s",
                [*page_params, limit + 1],
            )).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        return (
            [
                self._raw_from_row(
                    user_id,
                    SourceId(r[0]),
                    (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]),
                    origin=r[9],
                )
                for r in rows
            ],
            int(count_row[0]) if count_row is not None else 0,
            has_more,
        )

    async def source_activity(
        self, user_id: UserId, *, offset_minutes: int
    ) -> list[dict[str, Any]]:
        """Daily source density in the caller's fixed calendar offset."""

        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                """
                SELECT
                    (
                        (created_at AT TIME ZONE 'UTC')
                        + make_interval(mins => %s)
                    )::date AS activity_date,
                    kind,
                    count(*)
                FROM sources
                WHERE user_id = %s
                GROUP BY activity_date, kind
                ORDER BY activity_date, kind
                """,
                (offset_minutes, str(user_id)),
            )).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for activity_date, kind, count in rows:
            key = activity_date.isoformat()
            day = grouped.setdefault(key, {"date": key, "count": 0, "kinds": {}})
            day["count"] += int(count)
            day["kinds"][kind] = int(count)
        return list(grouped.values())

    async def fetch(
        self, user_id: UserId, source_id: SourceId, locator: Locator
    ) -> str:
        """L0 verbatim: resolve locator → block interval → join block text."""
        async with self._pool.connection() as conn:
            smap_row = await (await conn.execute(
                "SELECT structure_map FROM sources "
                "WHERE user_id = %s AND source_id = %s",
                (str(user_id), str(source_id)),
            )).fetchone()
            if smap_row is None:
                raise KeyError(f"source not found: {source_id!r}")
            start, end = StructureMap.model_validate(smap_row[0]).resolve(locator)
            rows = await (await conn.execute(
                "SELECT text FROM blocks "
                "WHERE user_id = %s AND source_id = %s "
                "AND block_index BETWEEN %s AND %s ORDER BY block_index",
                (str(user_id), str(source_id), start, end),
            )).fetchall()
        return "\n".join(r[0] for r in rows)

    @staticmethod
    def _raw_from_row(
        user_id: UserId,
        source_id: SourceId,
        row: tuple,
        origin: str = "upload",
    ) -> RawSource:
        # row = (kind, source_class, title, mime, checksum, created_at, meta, intake_plan)
        return RawSource(
            source_id=source_id,
            user_id=user_id,
            kind=row[0],
            source_class=row[1],
            title=row[2],
            mime=row[3],
            checksum=row[4],
            created_at=row[5],
            meta=row[6] or {},
            intake_plan=row[7],
            origin=origin,
        )

    # --- JobQueue -------------------------------------------------------------

    async def enqueue(
        self, user_id: UserId, kind: str, payload: dict[str, Any]
    ) -> str:
        job_id = uuid.uuid4().hex
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO compile_jobs (id, user_id, kind, payload) "
                "VALUES (%s, %s, %s, %s)",
                (job_id, str(user_id), kind, Json(payload)),
            )
        return job_id

    async def requeue_claimed_jobs(self) -> int:
        """Reclaim orphaned jobs: any job still 'claimed' is returned to 'queued'.

        The queue is single-worker and per-user single-in-flight, so at worker startup
        nothing is legitimately in-flight — a 'claimed' row means a worker died mid-job
        (e.g. killed during a long LLM call), which otherwise blocks that user's queue
        forever. Called on worker startup so a restart self-heals instead of stranding
        jobs. Returns the number requeued."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE compile_jobs SET status='queued', claimed_at=NULL, claimed_by=NULL "
                "WHERE status='claimed'"
            )
            return cur.rowcount

    async def claim_next(self, user_id: UserId) -> _JobRow | None:
        """Claim the oldest queued job for this user, but only if the user has no
        job already in flight — per-user serialization (§5, single git writer)."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                row = await (await conn.execute(
                    "SELECT id, kind, payload FROM compile_jobs "
                    "WHERE user_id = %s AND status = 'queued' "
                    "AND NOT EXISTS (SELECT 1 FROM compile_jobs j2 "
                    "  WHERE j2.user_id = %s AND j2.status = 'claimed') "
                    "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1",
                    (str(user_id), str(user_id)),
                )).fetchone()
                if row is None:
                    return None
                await conn.execute(
                    "UPDATE compile_jobs SET status = 'claimed', "
                    "claimed_at = %s, claimed_by = %s WHERE id = %s",
                    (datetime.now(timezone.utc), "worker", row[0]),
                )
        return _JobRow(row[0], user_id, row[1], row[2])

    async def complete(
        self,
        user_id: UserId,
        job_id: str,
        *,
        ok: bool = True,
        detail: str | None = None,
        snapshot_ref: str | None = None,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE compile_jobs SET status = 'done', completed_at = %s, "
                "ok = %s, detail = %s, snapshot_ref = %s "
                "WHERE user_id = %s AND id = %s",
                (
                    datetime.now(timezone.utc),
                    ok,
                    detail,
                    snapshot_ref,
                    str(user_id),
                    job_id,
                ),
            )

    # --- compile results (M3b) ------------------------------------------------

    async def list_jobs(self, user_id: UserId) -> list[dict[str, Any]]:
        """All compile jobs for a user, newest first (jobs API + timeline projection)."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id, kind, payload, status, created_at, claimed_at, "
                "completed_at, ok, detail, snapshot_ref FROM compile_jobs "
                "WHERE user_id = %s ORDER BY created_at DESC",
                (str(user_id),),
            )).fetchall()
        return [
            {
                "job_id": r[0],
                "kind": r[1],
                "payload": r[2] or {},
                "status": r[3],
                "created_at": r[4],
                "claimed_at": r[5],
                "completed_at": r[6],
                "ok": r[7],
                "detail": r[8],
                "snapshot_ref": r[9],
            }
            for r in rows
        ]

    async def list_jobs_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        before: tuple[datetime, str] | None = None,
        status: str | None = None,
        kind: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """One keyset-paginated job page, newest first."""
        filters = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if status:
            filters.append("status = %s")
            params.append(status)
        if kind:
            filters.append("kind = %s")
            params.append(kind)
        filtered_where = " AND ".join(filters)

        page_filters = list(filters)
        page_params = list(params)
        if before is not None:
            page_filters.append("(created_at, id) < (%s, %s)")
            page_params.extend(before)
        page_where = " AND ".join(page_filters)

        async with self._pool.connection() as conn:
            count_row = await (await conn.execute(
                f"SELECT count(*) FROM compile_jobs WHERE {filtered_where}",
                params,
            )).fetchone()
            rows = await (await conn.execute(
                "SELECT id, kind, payload, status, created_at, claimed_at, "
                "completed_at, ok, detail, snapshot_ref FROM compile_jobs "
                f"WHERE {page_where} "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                [*page_params, limit + 1],
            )).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        return (
            [
                {
                    "job_id": r[0],
                    "kind": r[1],
                    "payload": r[2] or {},
                    "status": r[3],
                    "created_at": r[4],
                    "claimed_at": r[5],
                    "completed_at": r[6],
                    "ok": r[7],
                    "detail": r[8],
                    "snapshot_ref": r[9],
                }
                for r in rows
            ],
            int(count_row[0]) if count_row is not None else 0,
            has_more,
        )

    async def list_history_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        before: tuple[datetime, str, str] | None = None,
        kind: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
        """Merge source captures, jobs and committed patches into one bounded ledger."""
        uid = str(user_id)
        ledger_filters: list[str] = []
        ledger_params: list[Any] = []
        if kind is not None:
            ledger_filters.append("kind = %s")
            ledger_params.append(kind)
        if before is not None:
            ledger_filters.append("(ts, kind, ref) < (%s, %s, %s)")
            ledger_params.extend(before)
        ledger_clause = (
            "WHERE " + " AND ".join(ledger_filters) if ledger_filters else ""
        )

        async with self._pool.connection() as conn:
            counts_row = await (await conn.execute(
                "SELECT "
                "(SELECT count(*) FROM compile_events WHERE user_id = %s "
                " GROUP BY user_id), "
                "(SELECT count(*) FROM compile_jobs WHERE user_id = %s), "
                "(SELECT count(*) FROM sources WHERE user_id = %s)",
                (uid, uid, uid),
            )).fetchone()
            rows = await (await conn.execute(
                """
                WITH patch_items AS (
                    SELECT
                        'patch'::text AS kind,
                        COALESCE(j.snapshot_ref, min(e.snapshot_ref))::text AS ref,
                        COALESCE(j.completed_at, j.created_at, max(e.created_at)) AS ts,
                        jsonb_build_object(
                            'patch_id', COALESCE(j.snapshot_ref, min(e.snapshot_ref)),
                            'job_id', j.id,
                            'ts', COALESCE(j.completed_at, j.created_at, max(e.created_at)),
                            'base_commit', NULL,
                            'changed_paths', jsonb_agg(DISTINCT e.path),
                            'documents', '[]'::jsonb,
                            'sources_consumed',
                                COALESCE(j.payload -> 'source_ids', '[]'::jsonb),
                            'skill_version', NULL,
                            'effort', NULL,
                            'claims', jsonb_agg(
                                jsonb_build_object(
                                    'type', e.type,
                                    'path', e.path,
                                    'anchor', jsonb_build_object(
                                        'document_id', NULL,
                                        'anchor', e.anchor
                                    ),
                                    'flags', '[]'::jsonb,
                                    'before', e.before,
                                    'after', e.after
                                )
                                ORDER BY e.seq
                            ),
                            'escalations', '[]'::jsonb,
                            'merges', '[]'::jsonb,
                            'flag_counts', '{}'::jsonb,
                            'lineage', '{}'::jsonb
                        ) AS payload
                    FROM compile_events e
                    JOIN compile_jobs j
                      ON j.user_id = e.user_id AND j.id = e.job_id
                    WHERE e.user_id = %s
                    GROUP BY j.id
                ),
                audit AS (
                    SELECT
                        'snapshot'::text AS kind,
                        s.source_id::text AS ref,
                        s.created_at AS ts,
                        jsonb_build_object(
                            'source_id', s.source_id,
                            'source_type', s.kind,
                            'captured_at', s.created_at,
                            'checksum', s.checksum,
                            'source_class', s.source_class
                        ) AS payload
                    FROM sources s
                    WHERE s.user_id = %s
                    UNION ALL
                    SELECT
                        'job'::text AS kind,
                        j.id::text AS ref,
                        COALESCE(j.completed_at, j.created_at) AS ts,
                        jsonb_build_object(
                            'job_id', j.id,
                            'status',
                                CASE
                                    WHEN j.status <> 'done' THEN 'running'
                                    WHEN j.ok THEN 'compiled'
                                    ELSE 'failed'
                                END,
                            'patch_id', j.snapshot_ref,
                            'ts', COALESCE(j.completed_at, j.created_at)
                        ) AS payload
                    FROM compile_jobs j
                    WHERE j.user_id = %s
                    UNION ALL
                    SELECT kind, ref, ts, payload FROM patch_items
                )
                SELECT kind, ref, ts, payload
                FROM audit
                """
                + ledger_clause
                + " ORDER BY ts DESC, kind DESC, ref DESC LIMIT %s",
                [uid, uid, uid, *ledger_params, limit + 1],
            )).fetchall()

        snapshots = int(counts_row[2]) if counts_row and counts_row[2] else 0
        jobs = int(counts_row[1]) if counts_row and counts_row[1] else 0
        # One patch per job with compile events, not one patch per event.
        patches = 0
        if counts_row and counts_row[0]:
            async with self._pool.connection() as conn:
                patch_row = await (await conn.execute(
                    "SELECT count(DISTINCT job_id) FROM compile_events WHERE user_id = %s",
                    (uid,),
                )).fetchone()
            patches = int(patch_row[0]) if patch_row else 0
        totals_by_kind = {
            "patch": patches,
            "job": jobs,
            "snapshot": snapshots,
        }
        counts = {
            "patches": patches,
            "jobs": jobs,
            "snapshots": snapshots,
            "total": (
                totals_by_kind[kind]
                if kind in totals_by_kind
                else patches + jobs + snapshots
            ),
        }
        has_more = len(rows) > limit
        rows = rows[:limit]
        return (
            [
                {
                    "kind": row[0],
                    "ref": row[1],
                    "ts": row[2],
                    "payload": row[3],
                }
                for row in rows
            ],
            counts,
            has_more,
        )

    async def history_activity(
        self, user_id: UserId, *, offset_minutes: int, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Daily density for the same patch/job/source ledger as ``list_history_page``."""

        uid = str(user_id)
        kind_clause = "WHERE kind = %s" if kind is not None else ""
        query_params: list[Any] = [uid, uid, uid, offset_minutes]
        if kind is not None:
            query_params.append(kind)
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                """
                WITH patch_items AS (
                    SELECT
                        'patch'::text AS kind,
                        COALESCE(j.completed_at, j.created_at, max(e.created_at)) AS ts
                    FROM compile_events e
                    JOIN compile_jobs j
                      ON j.user_id = e.user_id AND j.id = e.job_id
                    WHERE e.user_id = %s
                    GROUP BY j.id
                ),
                audit AS (
                    SELECT 'snapshot'::text AS kind, s.created_at AS ts
                    FROM sources s
                    WHERE s.user_id = %s
                    UNION ALL
                    SELECT
                        'job'::text AS kind,
                        COALESCE(j.completed_at, j.created_at) AS ts
                    FROM compile_jobs j
                    WHERE j.user_id = %s
                    UNION ALL
                    SELECT kind, ts FROM patch_items
                )
                SELECT
                    (
                        (ts AT TIME ZONE 'UTC')
                        + make_interval(mins => %s)
                    )::date AS activity_date,
                    kind,
                    count(*)
                FROM audit
                """
                + kind_clause
                + """
                GROUP BY activity_date, kind
                ORDER BY activity_date, kind
                """,
                query_params,
            )).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for activity_date, kind, count in rows:
            key = activity_date.isoformat()
            day = grouped.setdefault(key, {"date": key, "count": 0, "kinds": {}})
            day["count"] += int(count)
            day["kinds"][kind] = int(count)
        return list(grouped.values())

    async def record_compile_events(
        self,
        user_id: UserId,
        job_id: str,
        snapshot_ref: str,
        events: list[dict[str, Any]],
    ) -> None:
        """Append the mechanically-derived claim events for one committed compile."""
        if not events:
            return
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO compile_events (user_id, job_id, seq, "
                    "snapshot_ref, type, path, anchor, before, after) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (user_id, job_id, seq) DO NOTHING",
                    [
                        (
                            str(user_id),
                            job_id,
                            i,
                            snapshot_ref,
                            e["type"],
                            e["path"],
                            e["anchor"],
                            e.get("before"),
                            e["after"],
                        )
                        for i, e in enumerate(events)
                    ],
                )

    async def list_compile_events(self, user_id: UserId) -> list[dict[str, Any]]:
        """All compile events for a user, oldest first (History / journal projection)."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT job_id, seq, snapshot_ref, type, path, anchor, before, "
                "after, created_at FROM compile_events "
                "WHERE user_id = %s ORDER BY created_at, job_id, seq",
                (str(user_id),),
            )).fetchall()
        return [
            {
                "job_id": r[0],
                "seq": r[1],
                "snapshot_ref": r[2],
                "type": r[3],
                "path": r[4],
                "anchor": r[5],
                "before": r[6],
                "after": r[7],
                "created_at": r[8],
            }
            for r in rows
        ]

    async def mark_digested(
        self, user_id: UserId, source_ids: list[str], at: datetime
    ) -> None:
        """Stamp digested_at on the given sources (worker success)."""
        if not source_ids:
            return
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sources SET digested_at = %s "
                "WHERE user_id = %s AND source_id = ANY(%s)",
                (at, str(user_id), list(source_ids)),
            )

    async def digested_map(
        self, user_id: UserId, source_ids: list[str] | None = None
    ) -> dict[str, str | None]:
        """source_id → digested_at ISO string (or None) for one user (Sources status)."""
        if source_ids == []:
            return {}
        source_filter = " AND source_id = ANY(%s)" if source_ids is not None else ""
        params: list[Any] = [str(user_id)]
        if source_ids is not None:
            params.append(source_ids)
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, digested_at FROM sources "
                f"WHERE user_id = %s{source_filter}",
                params,
            )).fetchall()
        return {r[0]: (r[1].isoformat() if r[1] is not None else None) for r in rows}

    async def undigested_source_ids(self, user_id: UserId) -> list[str]:
        """Sources with a canonical treatment that are not yet digested (POST /compile).

        Excludes canonical_treatment == 'none' (never compiled), sources already stamped
        digested_at, and sources already referenced by an in-flight (queued/claimed) job
        — so a repeated POST /compile is idempotent even before the worker runs."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, intake_plan FROM sources "
                "WHERE user_id = %s AND digested_at IS NULL ORDER BY created_at",
                (str(user_id),),
            )).fetchall()
            active = await (await conn.execute(
                "SELECT payload FROM compile_jobs "
                "WHERE user_id = %s AND status IN ('queued', 'claimed')",
                (str(user_id),),
            )).fetchall()
        in_flight: set[str] = set()
        for (payload,) in active:
            for sid in (payload or {}).get("source_ids", []):
                in_flight.add(str(sid))
        out: list[str] = []
        for sid, plan in rows:
            treatment = (plan or {}).get("canonical_treatment")
            if treatment == "none" or sid in in_flight:
                continue
            out.append(sid)
        return out

    # --- canonical_claims projection (M4) -------------------------------------

    async def replace_canonical_claims(
        self,
        user_id: UserId,
        snapshot_ref: str,
        claims: list[ProjectedClaim],
        at: datetime | None = None,
    ) -> None:
        """Full-rebuild the user's claim projection (derived, I2): delete all rows then
        re-insert the snapshot's claims in one transaction."""
        now = at or datetime.now(timezone.utc)
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM canonical_claims WHERE user_id = %s",
                    (str(user_id),),
                )
                if claims:
                    async with conn.cursor() as cur:
                        await cur.executemany(
                            "INSERT INTO canonical_claims (user_id, document_path, "
                            "anchor, section_path, text, citations, snapshot_ref, "
                            "updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                            [
                                (
                                    str(user_id),
                                    c.document_path,
                                    str(c.anchor),
                                    Json(list(c.section_path)),
                                    c.text,
                                    Json(
                                        [
                                            {
                                                "source_id": str(cit.source_id),
                                                "block_start": cit.block_start,
                                                "block_end": cit.block_end,
                                            }
                                            for cit in c.citations
                                        ]
                                    ),
                                    snapshot_ref,
                                    now,
                                )
                                for c in claims
                            ],
                        )

    async def sync_canonical_claims(
        self,
        user_id: UserId,
        snapshot_ref: str,
        upserts: list[ProjectedClaim],
        deleted_keys: list[tuple[str, str]],
        at: datetime | None = None,
    ) -> None:
        """Apply a deterministic claim delta, then advance the manifest snapshot.

        The transaction lands after remote indexes succeed. Unchanged content keeps
        its `updated_at`, but every surviving row records the new snapshot ref.
        """
        now = at or datetime.now(timezone.utc)
        uid = str(user_id)
        async with self._pool.connection() as conn:
            async with conn.transaction():
                if deleted_keys:
                    async with conn.cursor() as cur:
                        await cur.executemany(
                            "DELETE FROM canonical_claims "
                            "WHERE user_id = %s AND document_path = %s AND anchor = %s",
                            [(uid, path, anchor) for path, anchor in deleted_keys],
                        )
                if upserts:
                    async with conn.cursor() as cur:
                        await cur.executemany(
                            "INSERT INTO canonical_claims (user_id, document_path, "
                            "anchor, section_path, text, citations, snapshot_ref, "
                            "updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                            "ON CONFLICT (user_id, document_path, anchor) DO UPDATE SET "
                            "section_path = EXCLUDED.section_path, "
                            "text = EXCLUDED.text, citations = EXCLUDED.citations, "
                            "snapshot_ref = EXCLUDED.snapshot_ref, "
                            "updated_at = EXCLUDED.updated_at",
                            [
                                (
                                    uid,
                                    claim.document_path,
                                    str(claim.anchor),
                                    Json(list(claim.section_path)),
                                    claim.text,
                                    Json(
                                        [
                                            {
                                                "source_id": str(citation.source_id),
                                                "block_start": citation.block_start,
                                                "block_end": citation.block_end,
                                            }
                                            for citation in claim.citations
                                        ]
                                    ),
                                    snapshot_ref,
                                    now,
                                )
                                for claim in upserts
                            ],
                        )
                await conn.execute(
                    "UPDATE canonical_claims SET snapshot_ref = %s "
                    "WHERE user_id = %s AND snapshot_ref <> %s",
                    (snapshot_ref, uid, snapshot_ref),
                )

    @staticmethod
    def _claim_row(r: tuple) -> dict[str, Any]:
        return {
            "document_path": r[0],
            "anchor": r[1],
            "section_path": r[2] or [],
            "text": r[3],
            "citations": r[4] or [],
            "snapshot_ref": r[5],
        }

    async def list_canonical_claims(
        self, user_id: UserId
    ) -> list[dict[str, Any]]:
        """All projected claims for one user (deterministic order)."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT document_path, anchor, section_path, text, citations, "
                "snapshot_ref FROM canonical_claims WHERE user_id = %s "
                "ORDER BY document_path, anchor",
                (str(user_id),),
            )).fetchall()
        return [self._claim_row(r) for r in rows]

    async def claims_citing_source(
        self, user_id: UserId, source_id: SourceId
    ) -> list[dict[str, Any]]:
        """Citation reverse lookup via the GIN index — claims citing this source."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT document_path, anchor, section_path, text, citations, "
                "snapshot_ref FROM canonical_claims "
                "WHERE user_id = %s AND citations @> %s::jsonb "
                "ORDER BY document_path, anchor",
                (str(user_id), Json([{"source_id": str(source_id)}])),
            )).fetchall()
        return [self._claim_row(r) for r in rows]

    # --- kb snapshot registry + tenant copy (frozen-tenant versioning) --------
    #
    # The registry is bookkeeping; the interesting part is `copy_tenant_rows`, which is the
    # PG half of freezing a knowledge base. It is INSERT…SELECT with the user_id rewritten:
    # the tenant column IS the version axis, so the copy needs no new schema and the frozen
    # rows are read by exactly the same queries as live ones.

    @staticmethod
    def _kb_snapshot_row(row: tuple) -> dict[str, Any]:
        return {
            "snapshot_id": row[0],
            "label": row[1],
            "tenant_id": row[2],
            "canonical_ref": row[3],
            "status": row[4],
            "counts": row[5] or {},
            "detail": row[6],
            "created_at": row[7],
            "ready_at": row[8],
        }

    _KB_SNAPSHOT_COLUMNS = (
        "snapshot_id, label, tenant_id, canonical_ref, status, counts, detail, "
        "created_at, ready_at"
    )

    async def create_kb_snapshot(
        self,
        user_id: UserId,
        snapshot_id: str,
        *,
        label: str,
        tenant_id: str,
        canonical_ref: str,
        created_at: datetime,
    ) -> None:
        """Register a snapshot in status 'creating'. The row exists BEFORE any copying so a
        crashed pipeline leaves a visible, deletable record instead of orphaned tenant rows."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO kb_snapshots (user_id, snapshot_id, label, tenant_id, "
                "canonical_ref, status, counts, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'creating', '{}'::jsonb, %s)",
                (
                    str(user_id),
                    snapshot_id,
                    label,
                    tenant_id,
                    canonical_ref,
                    created_at,
                ),
            )

    async def finish_kb_snapshot(
        self,
        user_id: UserId,
        snapshot_id: str,
        *,
        status: str,
        counts: dict[str, int] | None = None,
        detail: str | None = None,
        ready_at: datetime | None = None,
        canonical_ref: str | None = None,
    ) -> None:
        """Move a snapshot to its terminal status ('ready' or 'failed'). Never partial.

        `canonical_ref` overwrites the provisional commit recorded at creation. It is settled
        here, not there, because the ref must be no OLDER than the copied claim rows — see
        `kb_snapshots.run_copy`. None keeps the provisional value (the failure path)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE kb_snapshots SET status = %s, counts = %s, detail = %s, "
                "ready_at = %s, canonical_ref = COALESCE(%s, canonical_ref) "
                "WHERE user_id = %s AND snapshot_id = %s",
                (
                    status,
                    Json(counts or {}),
                    detail,
                    ready_at,
                    canonical_ref,
                    str(user_id),
                    snapshot_id,
                ),
            )

    async def list_kb_snapshots(self, user_id: UserId) -> list[dict[str, Any]]:
        """This owner's snapshots, newest first. Unpaginated on purpose: snapshots are a
        low-frequency deliberate act, so the list is small by construction."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                f"SELECT {self._KB_SNAPSHOT_COLUMNS} FROM kb_snapshots "
                "WHERE user_id = %s ORDER BY created_at DESC, snapshot_id DESC",
                (str(user_id),),
            )).fetchall()
        return [self._kb_snapshot_row(r) for r in rows]

    async def get_kb_snapshot(
        self, user_id: UserId, ref: str
    ) -> dict[str, Any] | None:
        """One snapshot by id OR by label — both are how a caller names one.

        A label is the human handle the UI shows and a script types; the id is what the API
        returns. Labels are not unique (nothing stops two snapshots called "before reorg"), so
        an ambiguous label resolves to the NEWEST match rather than failing: the recent one is
        what a person means, and the id is always available for an exact pick."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                f"SELECT {self._KB_SNAPSHOT_COLUMNS} FROM kb_snapshots "
                "WHERE user_id = %s AND (snapshot_id = %s OR label = %s) "
                "ORDER BY (snapshot_id = %s) DESC, created_at DESC LIMIT 1",
                (str(user_id), ref, ref, ref),
            )).fetchall()
        return self._kb_snapshot_row(rows[0]) if rows else None

    async def delete_kb_snapshot(self, user_id: UserId, snapshot_id: str) -> None:
        """Drop the registry row. The tenant's rows are removed by `delete_tenant_rows`."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM kb_snapshots WHERE user_id = %s AND snapshot_id = %s",
                (str(user_id), snapshot_id),
            )

    async def copy_tenant_rows(
        self, source: UserId, target: UserId
    ) -> dict[str, int]:
        """Copy one tenant's L0 + claim-projection rows under `target`, idempotently.

        `ON CONFLICT DO NOTHING` (unqualified, so it covers the sources checksum index as
        well as each primary key) is what makes a retry after a failed pipeline safe: the
        rows already copied are left alone and the rest are filled in. All three statements
        run in ONE transaction, so a mid-copy failure leaves nothing behind for this store.

        `chunk_manifests` is deliberately NOT copied: it exists to make a FUTURE re-chunk
        byte-deterministic, and a frozen tenant is never re-chunked. Copying it would state a
        rebuild intent that can never apply.
        """
        src, dst = str(source), str(target)
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO sources (user_id, source_id, kind, source_class, title, "
                    "mime, checksum, created_at, meta, intake_plan, structure_map, "
                    "digested_at, origin) "
                    "SELECT %s, source_id, kind, source_class, title, mime, checksum, "
                    "created_at, meta, intake_plan, structure_map, digested_at, origin "
                    "FROM sources WHERE user_id = %s ON CONFLICT DO NOTHING",
                    (dst, src),
                )
                await conn.execute(
                    "INSERT INTO blocks (user_id, source_id, block_index, text, "
                    "section_path) "
                    "SELECT %s, source_id, block_index, text, section_path "
                    "FROM blocks WHERE user_id = %s ON CONFLICT DO NOTHING",
                    (dst, src),
                )
                await conn.execute(
                    "INSERT INTO canonical_claims (user_id, document_path, anchor, "
                    "section_path, text, citations, snapshot_ref, updated_at) "
                    "SELECT %s, document_path, anchor, section_path, text, citations, "
                    "snapshot_ref, updated_at "
                    "FROM canonical_claims WHERE user_id = %s ON CONFLICT DO NOTHING",
                    (dst, src),
                )
                counts: dict[str, int] = {}
                for name, table in (
                    ("sources", "sources"),
                    ("blocks", "blocks"),
                    ("claims", "canonical_claims"),
                ):
                    row = await (await conn.execute(
                        f"SELECT count(*) FROM {table} WHERE user_id = %s", (dst,)
                    )).fetchone()
                    counts[name] = int(row[0]) if row else 0
        return counts

    async def delete_tenant_rows(self, user_id: UserId) -> None:
        """Remove a snapshot tenant's PG rows (blocks + chunk_manifests cascade)."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM canonical_claims WHERE user_id = %s", (str(user_id),)
                )
                await conn.execute(
                    "DELETE FROM sources WHERE user_id = %s", (str(user_id),)
                )

    # --- briefings (M4) -------------------------------------------------------

    async def create_briefing(
        self,
        user_id: UserId,
        briefing_id: str,
        scope: dict[str, Any],
        snapshot_ref: str,
        system_prefix: str,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO briefings (briefing_id, user_id, scope, "
                "snapshot_ref, system_prefix) VALUES (%s, %s, %s, %s, %s)",
                (briefing_id, str(user_id), Json(scope), snapshot_ref, system_prefix),
            )

    async def get_briefing(
        self, user_id: UserId, briefing_id: str
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT briefing_id, scope, snapshot_ref, system_prefix, created_at "
                "FROM briefings WHERE user_id = %s AND briefing_id = %s",
                (str(user_id), briefing_id),
            )).fetchone()
        if row is None:
            return None
        return {
            "briefing_id": row[0],
            "scope": row[1] or {},
            "snapshot_ref": row[2],
            "system_prefix": row[3],
            "created_at": row[4],
        }

    async def list_briefings(self, user_id: UserId) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT briefing_id, scope, snapshot_ref, system_prefix, created_at "
                "FROM briefings WHERE user_id = %s ORDER BY created_at DESC",
                (str(user_id),),
            )).fetchall()
        return [
            {
                "briefing_id": r[0],
                "scope": r[1] or {},
                "snapshot_ref": r[2],
                "system_prefix": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    async def delete_briefing(self, user_id: UserId, briefing_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM briefings WHERE user_id = %s AND briefing_id = %s",
                (str(user_id), briefing_id),
            )

    # --- user_profiles (onboarding-editable picture) --------------------------

    async def get_user_profile(self, user_id: UserId) -> dict[str, Any] | None:
        """The persisted (user-filled) profile JSON for one user, or None if never set."""
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT profile FROM user_profiles WHERE user_id = %s",
                (str(user_id),),
            )).fetchone()
        return row[0] if row is not None else None

    async def upsert_user_profile(
        self, user_id: UserId, profile: dict[str, Any]
    ) -> None:
        """Insert or replace the persisted profile for one user (updated_at refreshed)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO user_profiles (user_id, profile, updated_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "profile = EXCLUDED.profile, updated_at = EXCLUDED.updated_at",
                (str(user_id), Json(profile), datetime.now(timezone.utc)),
            )

    # --- evolve_tasks (schema-evolve §2.5) ------------------------------------

    @staticmethod
    def _evolve_row(r: tuple) -> dict[str, Any]:
        return {
            "task_id": r[0],
            "user_id": r[1],
            "status": r[2],
            "base_ref": r[3],
            "branch": r[4],
            "proposal": r[5],
            "summary": r[6],
            "dropped": r[7],
            "detail": r[8],
            "created_at": r[9],
            "decided_at": r[10],
        }

    async def create_evolve_task(
        self,
        user_id: UserId,
        task_id: str,
        *,
        status: str,
        base_ref: str | None = None,
        branch: str | None = None,
        proposal: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        dropped: list[dict[str, Any]] | None = None,
        detail: str | None = None,
    ) -> None:
        """Insert one evolve task row (draft awaiting review, or a terminal outcome)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO evolve_tasks (task_id, user_id, status, base_ref, "
                "branch, proposal, summary, dropped, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    task_id,
                    str(user_id),
                    status,
                    base_ref,
                    branch,
                    Json(proposal) if proposal is not None else None,
                    Json(summary) if summary is not None else None,
                    Json(dropped) if dropped is not None else None,
                    detail,
                ),
            )

    async def get_evolve_task(
        self, user_id: UserId, task_id: str
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT task_id, user_id, status, base_ref, branch, proposal, "
                "summary, dropped, detail, created_at, decided_at FROM evolve_tasks "
                "WHERE user_id = %s AND task_id = %s",
                (str(user_id), task_id),
            )).fetchone()
        return self._evolve_row(row) if row is not None else None

    async def list_evolve_tasks(
        self, user_id: UserId
    ) -> list[dict[str, Any]]:
        """All evolve tasks for a user, newest first."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT task_id, user_id, status, base_ref, branch, proposal, "
                "summary, dropped, detail, created_at, decided_at FROM evolve_tasks "
                "WHERE user_id = %s ORDER BY created_at DESC",
                (str(user_id),),
            )).fetchall()
        return [self._evolve_row(r) for r in rows]

    async def decide_evolve_task(
        self,
        user_id: UserId,
        task_id: str,
        status: str,
        detail: str | None = None,
    ) -> None:
        """Move a task to a decided status (adopted/dropped/expired), stamping decided_at.

        `detail` is overwritten only when provided (else the existing value is kept)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE evolve_tasks SET status = %s, decided_at = %s, "
                "detail = COALESCE(%s, detail) WHERE user_id = %s AND task_id = %s",
                (status, datetime.now(timezone.utc), detail, str(user_id), task_id),
            )

    async def update_evolve_detail(
        self, user_id: UserId, task_id: str, detail: str
    ) -> None:
        """Overwrite a task's detail WITHOUT deciding it (a failed adopt keeps status=draft
        while recording why it failed)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE evolve_tasks SET detail = %s "
                "WHERE user_id = %s AND task_id = %s",
                (detail, str(user_id), task_id),
            )

    # --- test hygiene ---------------------------------------------------------

    async def delete_user(self, user_id: UserId) -> None:
        """Remove all rows for one user (blocks cascade from sources). Used by the
        integration test teardown to keep test users from accumulating in /v1/users."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM canonical_claims WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM briefings WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM compile_events WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM compile_jobs WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM user_profiles WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM evolve_tasks WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM kb_snapshots WHERE user_id = %s",
                    (str(user_id),),
                )
                await conn.execute(
                    "DELETE FROM sources WHERE user_id = %s",
                    (str(user_id),),
                )
