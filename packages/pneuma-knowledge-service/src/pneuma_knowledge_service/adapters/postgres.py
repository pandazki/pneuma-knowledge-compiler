"""PG-backed ContentStore + JobQueue (architecture.md §5).

Append-only content authority (L0). psycopg3 + connection pool, plain SQL, no ORM.
Every row is keyed by user_id first (invariant I1); there is no query path that
omits it. Content dedup: same user + same checksum returns the existing source_id
(append-only, never overwrites). The compile queue claims per-user serially via
`FOR UPDATE SKIP LOCKED` — the single-writer guarantee for the git canonical layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pneuma_knowledge_core.domain.consultation import (
    ConsultationRecord,
    EvidenceRef,
)
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.pricing import USAGE_FIELDS, usage_pairs
from pneuma_knowledge_core.domain.source import (
    Locator,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from psycopg.types.json import Json, Jsonb
from psycopg_pool import AsyncConnectionPool

from ..access_stats import RECALL_PROJECTION_JOB_KIND
from ..snapshot_tenant import RESERVED_PREFIX

_SCHEMA_PATH = Path(__file__).resolve().parents[5] / "infra" / "schema.sql"

#: The default page a consultation walk takes. Bounded rather than open because the
#: caller of the replay face is a rebuild, and a rebuild that loads a year of records
#: into one list is a rebuild that stops working exactly when the library gets used.
CONSULTATION_PAGE = 500

#: The job-status QUERY vocabulary, and the only place it is defined.
#:
#: The COLUMN has three values — `queued`, `claimed`, `done` — and keeps them: the worker's
#: claim loop, the self-heal on restart and every operational query read them directly, and a
#: fourth value would be a storage migration for a question that is not about storage.
#: "Failed" was never a status. A compile the gate rejected finishes like any other job:
#: `status='done'`, `ok=false`. So `?status=failed` matched no row and always answered 0 —
#: the one question an operator actually asks, answered wrong by construction.
#:
#: These two names are DERIVED predicates over the same column, offered beside the three raw
#: ones. `done` keeps meaning both halves, so nothing that already worked changes.
JOB_STATUS_SQL: dict[str, str] = {
    "failed": "status = 'done' AND ok IS FALSE",
    "succeeded": "status = 'done' AND ok IS TRUE",
}

#: Everything `?status=` accepts, for the API's own validation and for the docs.
JOB_STATUS_QUERY_VALUES = ("queued", "claimed", "done", "succeeded", "failed")

#: Advisory-lock key for schema application. An arbitrary fixed constant in the
#: bigint space — its only job is that every process picks the SAME number.
_SCHEMA_LOCK_KEY = 0x504E_4B43_0001  # "PNKC" + 1

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
        """Idempotently apply infra/schema.sql (v1 migration strategy, §5).

        Serialized by a transaction-scoped advisory lock. `CREATE TABLE IF NOT EXISTS` is
        idempotent but NOT concurrency-safe: two starters racing against the same cold
        database both pass the existence check and both try to create the type row, and the
        loser dies on `pg_type_typname_nsp_index`. Every process that boots an AppContext
        runs this, so on a fresh deployment (or a fresh test database) N starters meant
        N-1 crashes. The lock is held for the transaction and released when it ends, so a
        warm database still costs one no-op round trip and nothing else."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,)
                )
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
                        "text, section_path, images) VALUES (%s, %s, %s, %s, %s, %s)",
                        [
                            (
                                str(user_id),
                                str(raw.source_id),
                                b.index,
                                b.text,
                                Json(b.section_path),
                                Json([image.model_dump(mode="json") for image in b.images]),
                            )
                            for b in source.blocks
                        ],
                    )
        return raw.source_id

    async def get(self, user_id: UserId, source_id: SourceId) -> NormalizedSource:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT kind, source_class, title, mime, checksum, created_at, "
                "meta, intake_plan, structure_map, origin, archived_at FROM sources "
                "WHERE user_id = %s AND source_id = %s",
                (str(user_id), str(source_id)),
            )).fetchone()
            if row is None:
                raise KeyError(f"source not found: {source_id!r}")
            # An archived source still answers here: L0 reachability is unconditional (I3).
            raw = self._raw_from_row(
                user_id, source_id, row, origin=row[9], archived_at=row[10]
            )
            structure = StructureMap.model_validate(row[8])
            blocks = [
                NormalizedBlock(index=r[0], text=r[1], section_path=r[2], images=r[3])
                for r in await (await conn.execute(
                    "SELECT block_index, text, section_path, images FROM blocks "
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
        """Bounded overview counts without loading any collection rows.

        `jobs_failed` rides here because a total job count answers "did anything run" and
        nothing else: a gate-rejected compile is `done` like a committed one, so a workspace
        whose every compile aborted looked exactly like a healthy one from the summary. It is
        the same `done ∧ ok=false` the `failed` filter selects — one definition
        (`JOB_STATUS_SQL`), so the number and the list can never disagree.
        """
        uid = str(user_id)
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT "
                "(SELECT count(*) FROM sources WHERE user_id = %s), "
                "(SELECT count(*) FROM compile_jobs WHERE user_id = %s), "
                f"(SELECT count(*) FROM compile_jobs WHERE user_id = %s "
                f" AND {JOB_STATUS_SQL['failed']}), "
                "(SELECT count(DISTINCT document_path) FROM canonical_claims "
                " WHERE user_id = %s), "
                "(SELECT count(*) FROM canonical_claims WHERE user_id = %s)",
                (uid, uid, uid, uid, uid),
            )).fetchone()
        assert row is not None
        return {
            "sources": int(row[0]),
            "jobs": int(row[1]),
            "jobs_failed": int(row[2]),
            "documents": int(row[3]),
            "claims": int(row[4]),
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

    # --- component projections: the `time` component's block index ---------------
    # A component projection is DERIVED (I2): it is written only from L0 + canonical and is
    # re-derivable in full. The store keeps it opaque — what a row MEANS (why the subject's
    # local day rather than the UTC one) is the component's business, stated there.

    async def put_time_blocks(
        self, user_id: UserId, source_id: SourceId, rows: list[dict]
    ) -> int:
        """Replace one source's time rows, in one transaction. Returns the row count.

        Wholesale replacement rather than a per-row upsert on purpose: a re-derivation may
        legitimately produce FEWER blocks than the last one (a source re-imported after an
        edit), and an upsert that only touched the rows it was given would leave the tail of
        the previous derivation behind as phantom days. Delete + insert is idempotent and
        cannot.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM component_time_blocks "
                    "WHERE user_id = %s AND source_id = %s",
                    (str(user_id), str(source_id)),
                )
                if not rows:
                    return 0
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO component_time_blocks (user_id, source_id, "
                        "block_index, instant_utc, local_day, zone, zone_source, "
                        "source_zone, kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [
                            (
                                str(user_id),
                                str(source_id),
                                int(r["block_index"]),
                                r.get("instant_utc"),
                                r["local_day"],
                                r["zone"],
                                r["zone_source"],
                                r.get("source_zone"),
                                r["kind"],
                            )
                            for r in rows
                        ],
                    )
        return len(rows)

    async def delete_time_blocks(self, user_id: UserId) -> int:
        """Drop this user's whole time projection (the first half of a rebuild)."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM component_time_blocks WHERE user_id = %s", (str(user_id),)
            )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    async def time_blocks_in_range(
        self, user_id: UserId, since: date, until: date, *, limit: int = 5000
    ) -> list[dict]:
        """Every projected block whose SUBJECT-local day falls in `[since, until]`.

        One indexed range scan plus a join for the source's title/kind, so enumerating a
        window costs the window rather than the library: the whole reason this projection is
        persisted at all. Deterministically ordered (day, instant, source, block) so a
        digest built from it is byte-stable.

        ARCHIVED SOURCES ARE NOT IN THE ANSWER (docs/design/archive.md §4). The projection
        itself keeps them — it is derived from all of L0 and rebuilt from all of it — but a
        window read is a READ, and its caller is a component face that returns prose: the
        `time` component's timeline and timespan hand back verbatim block text, which the
        framework's assembly filter cannot redact after the fact. So the exclusion is made
        here, in the query the read goes through, and no component has to learn that the
        archive exists. `LEFT JOIN` plus `IS NULL` also keeps a projected block whose source
        row is gone, exactly as before.
        """
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT t.source_id, t.block_index, t.instant_utc, t.local_day, t.zone, "
                "t.zone_source, t.source_zone, t.kind, s.title "
                "FROM component_time_blocks t "
                "LEFT JOIN sources s ON s.user_id = t.user_id "
                "AND s.source_id = t.source_id "
                "WHERE t.user_id = %s AND t.local_day >= %s AND t.local_day <= %s "
                "AND s.archived_at IS NULL "
                "ORDER BY t.local_day, t.instant_utc NULLS FIRST, t.source_id, "
                "t.block_index LIMIT %s",
                (str(user_id), since, until, limit),
            )).fetchall()
        return [
            {
                "source_id": r[0],
                "block_index": r[1],
                "instant_utc": r[2],
                "local_day": r[3],
                "zone": r[4],
                "zone_source": r[5],
                "source_zone": r[6],
                "kind": r[7],
                "title": r[8] or "",
            }
            for r in rows
        ]

    async def time_days_for_sources(
        self, user_id: UserId, source_ids: list[str]
    ) -> dict[str, str]:
        """source_id → its EARLIEST projected subject-local day, as an ISO string.

        The as-of walk needs "when is this claim's evidence from" for a handful of cited
        sources; asking for exactly those beats loading every source's meta.
        """
        ids = [str(s) for s in source_ids]
        if not ids:
            return {}
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, min(local_day) FROM component_time_blocks "
                "WHERE user_id = %s AND source_id = ANY(%s) GROUP BY source_id",
                (str(user_id), ids),
            )).fetchall()
        return {r[0]: r[1].isoformat() for r in rows if r[1] is not None}

    # --- component projections: the `people` component's address-term index ------
    # Same discipline as the time projection above and one deliberate difference: these rows
    # ACCUMULATE. A term's meaning is its distribution across the whole library, so each
    # indexed source ADDS its counts rather than replacing a slice — see the component and
    # infra/schema.sql for why. What makes that safe is that the addition happens at most
    # once per source: `component_people_indexed` is the manifest, claimed in the same
    # transaction as the counts.

    async def add_people_terms(
        self, user_id: UserId, source_id: str, rows: list[dict]
    ) -> bool:
        """Add ONE source's (term → target) counts to this user's projection — at most once.

        Returns whether this call was the one that added them. The manifest row is claimed
        first, `ON CONFLICT DO NOTHING`, in the same transaction as the counts: a second job
        for the same source inserts no row, learns it from `rowcount`, and adds nothing. Same
        at-most-once shape as `apply_access_stats`, and for the same reason — the queue is
        at-least-once, and an accumulation applied twice cannot be un-applied. The archive
        subtracts ONE copy of a source's contribution recomputed from L0, so a doubled source
        would leave half of itself in every read that excludes it.

        A source with no rows still claims the manifest: it HAS been accumulated, and what it
        contributed is nothing.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO component_people_indexed (user_id, source_id) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (str(user_id), str(source_id)),
                )
                if not cur.rowcount:
                    return False
                if not rows:
                    return True
                await cur.executemany(
                    "INSERT INTO component_people_terms (user_id, term, target_identity, "
                    "target_name, answered, co_mention, non_vocative, sources, first_day, "
                    "last_day) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (user_id, term, target_identity) DO UPDATE SET "
                    "answered = component_people_terms.answered + EXCLUDED.answered, "
                    "co_mention = component_people_terms.co_mention + EXCLUDED.co_mention, "
                    "non_vocative = component_people_terms.non_vocative "
                    "+ EXCLUDED.non_vocative, "
                    "sources = component_people_terms.sources + EXCLUDED.sources, "
                    "first_day = LEAST(component_people_terms.first_day, EXCLUDED.first_day), "
                    "last_day = GREATEST(component_people_terms.last_day, EXCLUDED.last_day), "
                    "target_name = CASE WHEN component_people_terms.target_name = '' "
                    "THEN EXCLUDED.target_name ELSE component_people_terms.target_name END",
                    [
                        (
                            str(user_id),
                            r["term"],
                            r["target_identity"],
                            r.get("target_name") or "",
                            int(r.get("answered") or 0),
                            int(r.get("co_mention") or 0),
                            int(r.get("non_vocative") or 0),
                            int(r.get("sources") or 1),
                            r.get("first_day") or None,
                            r.get("last_day") or None,
                        )
                        for r in rows
                    ],
                )
        return True

    async def set_people_terms_reported_since(
        self, user_id: UserId, pairs: list[dict], day: str
    ) -> int:
        """Stamp `reported_since = day` on the given (term → target) pairs — ONCE.

        `WHERE reported_since IS NULL` is the whole of "first satisfied": the day a pair
        crossed the reporting bar is written when it crosses and never moved, so a pair whose
        concentration later shifts keeps the day the library started asking about it. A
        rebuild deletes the rows first, so there the predicate is always true and the replay
        decides the dates on its own.
        """
        if not pairs or not day:
            return 0
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "UPDATE component_people_terms SET reported_since = %s "
                    "WHERE user_id = %s AND term = %s AND target_identity = %s "
                    "AND reported_since IS NULL",
                    [
                        (day, str(user_id), p["term"], p["target_identity"])
                        for p in pairs
                    ],
                )
        return len(pairs)

    async def delete_people_terms(self, user_id: UserId) -> int:
        """Drop this user's whole address-term projection — the counts AND the manifest of
        the sources already accumulated into them — in ONE transaction. The first half of a
        rebuild; returns how many count rows went.

        Both tables or neither. The manifest says which sources the counts already hold, so a
        rebuild that emptied the counts alone would find every source claimed, add nothing,
        and leave the library projected as empty.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    "DELETE FROM component_people_terms WHERE user_id = %s",
                    (str(user_id),),
                )
                dropped = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                await conn.execute(
                    "DELETE FROM component_people_indexed WHERE user_id = %s",
                    (str(user_id),),
                )
        return dropped

    async def people_terms(
        self, user_id: UserId, terms: list[str] | None = None
    ) -> list[dict]:
        """This user's (term → target) rows, optionally restricted to `terms` (comparison
        keys). Deterministically ordered so any render built from them is byte-stable."""
        where = "user_id = %s"
        params: list[object] = [str(user_id)]
        if terms is not None:
            if not terms:
                return []
            where += " AND term = ANY(%s)"
            params.append([str(t) for t in terms])
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT term, target_identity, target_name, answered, co_mention, "
                f"non_vocative, sources, first_day, last_day, reported_since "
                f"FROM component_people_terms WHERE {where} "
                "ORDER BY term, target_identity",
                tuple(params),
            )).fetchall()
        return [
            {
                "term": r[0],
                "target_identity": r[1],
                "target_name": r[2] or "",
                "answered": int(r[3] or 0),
                "co_mention": int(r[4] or 0),
                "non_vocative": int(r[5] or 0),
                "sources": int(r[6] or 0),
                "first_day": r[7].isoformat() if r[7] is not None else "",
                "last_day": r[8].isoformat() if r[8] is not None else "",
                "reported_since": r[9].isoformat() if r[9] is not None else "",
            }
            for r in rows
        ]

    # --- recall access statistics (the framework's built-in consumer) ---------
    #
    # Not a component's tables: the worker's `recall_projection` handler applies these for
    # every `business` consultation, registered components or not (access_stats.py). Access
    # metadata lives HERE, in the derived layer, keyed by address — never in a canonical
    # file, because a read must never become a write to the authority.

    async def apply_access_stats(
        self,
        user_id: UserId,
        consultation_id: str,
        hits: list[dict],
        misses: list[dict],
    ) -> bool:
        """Apply one record's rows AND stamp it `projected_at` — in one transaction.

        Returns whether this call was the one that applied it. The stamp is claimed first,
        with `projected_at IS NULL` in the `WHERE`: a second job for the same consultation
        updates no row, learns it from `rowcount`, and writes nothing. That is the whole
        at-most-once guarantee, and it is one statement rather than a lock — a retried job
        (a worker killed mid-job, the queue's self-heal on restart) cannot double-count.

        The rows arrive already summed (`access_stats.ledger_rows`), because one
        `INSERT … ON CONFLICT` may not touch the same row twice in a statement and a record
        whose evidence was also cited produces exactly that duplicate. `hits` ADDS rather
        than replaces: a day accumulates across every consultation that happened in it.

        `last_seen` takes the LATER of the two instants, so a record that arrives out of
        order — a projection job drained after a newer one — never drags a target's last
        access backwards.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor() as cur:
                await cur.execute(
                    "UPDATE consultations SET projected_at = %s "
                    "WHERE user_id = %s AND consultation_id = %s "
                    "AND projected_at IS NULL",
                    (datetime.now(timezone.utc), str(user_id), consultation_id),
                )
                if not cur.rowcount:
                    return False
                if hits:
                    await cur.executemany(
                        "INSERT INTO recall_access_hits "
                        "(user_id, target_kind, target_ref, day, hits, last_seen) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (user_id, target_kind, target_ref, day) DO UPDATE "
                        "SET hits = recall_access_hits.hits + EXCLUDED.hits, "
                        "last_seen = GREATEST("
                        "recall_access_hits.last_seen, EXCLUDED.last_seen)",
                        [
                            (
                                str(user_id),
                                str(r["target_kind"]),
                                str(r["target_ref"]),
                                r["day"],
                                int(r["hits"]),
                                r["last_seen"],
                            )
                            for r in hits
                        ],
                    )
                if misses:
                    await cur.executemany(
                        "INSERT INTO recall_access_misses "
                        "(user_id, day, question, count) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (user_id, day, question) DO UPDATE "
                        "SET count = recall_access_misses.count + EXCLUDED.count",
                        [
                            (str(user_id), r["day"], str(r["question"]), int(r["count"]))
                            for r in misses
                        ],
                    )
        return True

    async def replace_access_stats(
        self, user_id: UserId, hits: list[dict], misses: list[dict]
    ) -> int:
        """Swap this user's whole access ledger for a rebuilt one, ATOMICALLY.

        Delete both tables and insert the replacement set in ONE transaction, so no reader
        ever sees the gap. The rows are the already-summed replacement, so this INSERTs
        rather than accumulates — that is the difference from `apply_access_stats`, and the
        reason it is a separate method rather than a flag.

        Both halves of the ledger go together: a rebuild that cleared the hits and kept
        yesterday's misses would produce a report nothing can reproduce from the records.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor() as cur:
                for table in ("recall_access_hits", "recall_access_misses"):
                    await cur.execute(
                        f"DELETE FROM {table} WHERE user_id = %s", (str(user_id),)
                    )
                if hits:
                    await cur.executemany(
                        "INSERT INTO recall_access_hits "
                        "(user_id, target_kind, target_ref, day, hits, last_seen) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        [
                            (
                                str(user_id),
                                str(r["target_kind"]),
                                str(r["target_ref"]),
                                r["day"],
                                int(r["hits"]),
                                r["last_seen"],
                            )
                            for r in hits
                        ],
                    )
                if misses:
                    await cur.executemany(
                        "INSERT INTO recall_access_misses "
                        "(user_id, day, question, count) VALUES (%s, %s, %s, %s)",
                        [
                            (str(user_id), r["day"], str(r["question"]), int(r["count"]))
                            for r in misses
                        ],
                    )
        return len(hits) + len(misses)

    async def access_rows_for(
        self, user_id: UserId, pairs: Sequence[tuple[str, str]]
    ) -> list[dict]:
        """Every day row for a page of targets — the read face's one query.

        Bulk by construction: a caller joining a list of documents against their access
        metadata asks once, not once per row, and a single target is a page of one. Whole
        history rather than a window, because `last_accessed_at` is the MAX over EVERY day
        row: a target last read forty-five days ago has a real last access and no recent
        hits, and a windowed query would report the first as absent.
        """
        if not pairs:
            return []
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT target_kind, target_ref, day, hits, last_seen "
                "FROM recall_access_hits WHERE user_id = %s "
                "AND (target_kind, target_ref) IN "
                "(SELECT * FROM unnest(%s::text[], %s::text[])) "
                "ORDER BY target_kind, target_ref, day",
                (
                    str(user_id),
                    [str(k) for k, _ in pairs],
                    [str(r) for _, r in pairs],
                ),
            )).fetchall()
        return [
            {
                "target_kind": r[0],
                "target_ref": r[1],
                "day": r[2],
                "hits": int(r[3] or 0),
                "last_seen": r[4],
            }
            for r in rows
        ]

    async def access_hits_since(
        self, user_id: UserId, since: date, *, until: date | None = None
    ) -> list[dict]:
        """This user's hit rows inside `[since, until]`, deterministically ordered.

        `until` closes the window at the top. A report states its bounds out loud
        (`window A..B`), so a row dated after B — clock skew on a writer, a record imported
        with a bad timestamp — was being counted in a window that says it does not contain
        it, and counted at a NEGATIVE age, which the decay curve amplifies.
        """
        clauses = ["user_id = %s", "day >= %s"]
        params: list = [str(user_id), since]
        if until is not None:
            clauses.append("day <= %s")
            params.append(until)
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT target_kind, target_ref, day, hits, last_seen "
                "FROM recall_access_hits WHERE " + " AND ".join(clauses)
                + " ORDER BY target_kind, target_ref, day",
                tuple(params),
            )).fetchall()
        return [
            {
                "target_kind": r[0],
                "target_ref": r[1],
                "day": r[2],
                "hits": int(r[3] or 0),
                "last_seen": r[4],
            }
            for r in rows
        ]

    async def access_misses_since(
        self, user_id: UserId, since: date, *, until: date | None = None
    ) -> list[dict]:
        """This user's unanswered questions inside `[since, until]`, deterministically
        ordered. Same closed window as the hits — see `access_hits_since`."""
        clauses = ["user_id = %s", "day >= %s"]
        params: list = [str(user_id), since]
        if until is not None:
            clauses.append("day <= %s")
            params.append(until)
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT day, question, count FROM recall_access_misses "
                "WHERE " + " AND ".join(clauses) + " ORDER BY day, question",
                tuple(params),
            )).fetchall()
        return [
            {"day": r[0], "question": r[1], "count": int(r[2] or 0)} for r in rows
        ]

    async def list(self, user_id: UserId) -> list[RawSource]:
        """Every source this user owns, oldest first — ARCHIVED ONES INCLUDED.

        L0 is the verbatim record and its reachability is unconditional (invariant I3), so
        the authority's own enumeration hides nothing; each row carries `archived_at` and a
        reader that wants only live material filters on it. The face that defaults to
        excluding the archive is the paginated LISTING (`list_sources_page`), because that
        one answers a question the Owner asked.
        """
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, kind, source_class, title, mime, checksum, "
                "created_at, meta, intake_plan, origin, archived_at FROM sources "
                "WHERE user_id = %s ORDER BY created_at",
                (str(user_id),),
            )).fetchall()
        return [
            self._raw_from_row(
                user_id,
                SourceId(r[0]),
                (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]),
                origin=r[9],
                archived_at=r[10],
            )
            for r in rows
        ]

    async def list_since(
        self, user_id: UserId, *, after: tuple[datetime, str] | None = None
    ) -> list[RawSource]:
        """This user's sources after a `(created_at, source_id)` watermark, oldest first.

        The same keyset predicate `list_sources_page` uses, forward instead of backward: the
        pair is the cursor because `created_at` is not unique — a batch import stamps one
        wall clock on every source in it, and a `> created_at` cursor would drop all but the
        last of them permanently. A reader that folds each source into a mirror once (the
        `people` component's source boundary) then transfers only what arrived since its last
        job, rather than pulling every envelope the library holds to discard all but the new.
        """
        where = "user_id = %s"
        params: list[Any] = [str(user_id)]
        if after is not None:
            where += " AND (created_at, source_id) > (%s, %s)"
            params.extend([after[0], str(after[1])])
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, kind, source_class, title, mime, checksum, "
                "created_at, meta, intake_plan, origin, archived_at FROM sources "
                f"WHERE {where} ORDER BY created_at, source_id",
                params,
            )).fetchall()
        return [
            self._raw_from_row(
                user_id,
                SourceId(r[0]),
                (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]),
                origin=r[9],
                archived_at=r[10],
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
        include_archived: bool = False,
    ) -> tuple[list[RawSource], int, bool]:
        """One keyset-paginated source page, newest first.

        The count and page query apply the same user/filter predicate. Only ``limit + 1``
        source rows cross the storage boundary; the extra row determines ``has_more``.

        The archive is excluded by default (docs/design/archive.md §4): the Owner said this
        material is no longer current, and a listing that still leads with it costs every
        read. ``include_archived=True`` is the stated exception. Either way every returned
        row carries `archived_at`, so a caller can label what it shows.
        """
        filters = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if not include_archived:
            filters.append("archived_at IS NULL")
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
                "created_at, meta, intake_plan, origin, archived_at FROM sources "
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
                    archived_at=r[10],
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

    # --- the archive mark on L0 (docs/design/archive.md §2.2) -----------------

    async def set_source_archived(
        self, user_id: UserId, source_id: SourceId, archived: bool
    ) -> datetime | None:
        """Set or clear one source's archive mark; return the value it now holds.

        The column IS the state — nothing else records it, so a rebuild of every derived
        layer reads it off here and never off a side table. Setting an already-archived
        source re-stamps the day it was archived, which is why the caller (the archive job)
        only writes the sources its confirmed proposal actually selected.
        """
        now = datetime.now(timezone.utc) if archived else None
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "UPDATE sources SET archived_at = %s "
                "WHERE user_id = %s AND source_id = %s RETURNING archived_at",
                (now, str(user_id), str(source_id)),
            )).fetchone()
        if row is None:
            raise KeyError(f"source not found: {source_id!r}")
        return row[0]

    async def archived_source_ids(self, user_id: UserId) -> frozenset[SourceId]:
        """This user's archived source ids — one read for one retrieval's assembly filter."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id FROM sources "
                "WHERE user_id = %s AND archived_at IS NOT NULL",
                (str(user_id),),
            )).fetchall()
        return frozenset(SourceId(r[0]) for r in rows)

    @staticmethod
    def _raw_from_row(
        user_id: UserId,
        source_id: SourceId,
        row: tuple,
        origin: str = "upload",
        archived_at: datetime | None = None,
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
            archived_at=archived_at,
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
        token_usage: dict[str, int] | None = None,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE compile_jobs SET status = 'done', completed_at = %s, "
                "ok = %s, detail = %s, snapshot_ref = %s, token_usage = %s "
                "WHERE user_id = %s AND id = %s",
                (
                    datetime.now(timezone.utc),
                    ok,
                    detail,
                    snapshot_ref,
                    Json(dict(token_usage)) if token_usage else None,
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
                "completed_at, ok, detail, snapshot_ref, token_usage FROM compile_jobs "
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
                "token_usage": r[10] or {},
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
        """One keyset-paginated job page, newest first.

        `status` is the QUERY vocabulary, not the column: `failed` and `succeeded` are the
        two halves of `done` (see `JOB_STATUS_SQL`). The column keeps its three values, so
        the queue's storage semantics — and everything that reads them — are untouched.
        """
        filters = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if status:
            derived = JOB_STATUS_SQL.get(status)
            if derived is not None:
                filters.append(derived)
            else:
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
                "completed_at, ok, detail, snapshot_ref, token_usage FROM compile_jobs "
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
                    "token_usage": r[10] or {},
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
                            'brief', j.brief,
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

    async def record_compile_brief(
        self, user_id: UserId, job_id: str, brief: str
    ) -> None:
        """Attach the derived narration to a completed compile job (brief_enabled)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE compile_jobs SET brief = %s WHERE user_id = %s AND id = %s",
                (brief, str(user_id), job_id),
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
        — so a repeated POST /compile is idempotent even before the worker runs.

        Archived sources are excluded too (docs/design/archive.md §2.2): the Owner has said
        the material is not current, and compiling it would write LIVE claims about an
        archived subject."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source_id, intake_plan FROM sources "
                "WHERE user_id = %s AND digested_at IS NULL AND archived_at IS NULL "
                "ORDER BY created_at",
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
                            "updated_at, archived) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                                    c.archived,
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
                            "updated_at, archived) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                            "ON CONFLICT (user_id, document_path, anchor) DO UPDATE SET "
                            "section_path = EXCLUDED.section_path, "
                            "text = EXCLUDED.text, citations = EXCLUDED.citations, "
                            "snapshot_ref = EXCLUDED.snapshot_ref, "
                            "updated_at = EXCLUDED.updated_at, "
                            "archived = EXCLUDED.archived",
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
                                    claim.archived,
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
            "archived": bool(r[6]),
        }

    async def list_canonical_claims(
        self, user_id: UserId
    ) -> list[dict[str, Any]]:
        """All projected claims for one user (deterministic order)."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT document_path, anchor, section_path, text, citations, "
                "snapshot_ref, archived FROM canonical_claims WHERE user_id = %s "
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
                "snapshot_ref, archived FROM canonical_claims "
                "WHERE user_id = %s AND citations @> %s::jsonb "
                "ORDER BY document_path, anchor",
                (str(user_id), Json([{"source_id": str(source_id)}])),
            )).fetchall()
        return [self._claim_row(r) for r in rows]

    # --- archive proposals (docs/design/archive.md §5) ------------------------
    #
    # A KEPT RECORD, not a derived layer (invariant I2): what the Owner proposed, against
    # which library state, and what they decided. A rebuild replays it and never rewrites
    # it, and nothing here recomputes a plan — the planner is pure core and runs once, at
    # proposal time, so the set the Owner confirms is byte-for-byte the set they saw.

    _ARCHIVE_PROPOSAL_COLUMNS = (
        "proposal_id, action, seeds, items, library_ref, status, note, statement_ref, "
        "created_at, confirmed_at, executed_at, job_id, detail"
    )

    @staticmethod
    def _archive_proposal_row(row: tuple) -> dict[str, Any]:
        return {
            "proposal_id": row[0],
            "action": row[1],
            "seeds": row[2] or {},
            "items": row[3] or [],
            "library_ref": row[4] or "",
            "status": row[5],
            "note": row[6],
            "statement_ref": row[7],
            "created_at": row[8],
            "confirmed_at": row[9],
            "executed_at": row[10],
            "job_id": row[11],
            "detail": row[12],
        }

    async def create_archive_proposal(
        self,
        user_id: UserId,
        proposal_id: str,
        *,
        action: str,
        seeds: dict[str, Any],
        items: list[dict[str, Any]],
        library_ref: str,
        note: str | None = None,
        statement_ref: str | None = None,
    ) -> None:
        """Record one computed proposal, `status='proposed'`.

        `library_ref` is the canonical HEAD the closure was computed against and is written
        in the SAME statement as the items it explains: a confirm re-checks it and refuses
        as stale when HEAD has moved, and an item list stored without the ref it was
        computed from would be a preview of a library nobody can identify.
        """
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO archive_proposals (user_id, proposal_id, action, seeds, "
                "items, library_ref, status, note, statement_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'proposed', %s, %s)",
                (
                    str(user_id),
                    proposal_id,
                    action,
                    Json(dict(seeds)),
                    Json(list(items)),
                    library_ref,
                    note,
                    statement_ref,
                ),
            )

    async def get_archive_proposal(
        self, user_id: UserId, proposal_id: str
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                f"SELECT {self._ARCHIVE_PROPOSAL_COLUMNS} FROM archive_proposals "
                "WHERE user_id = %s AND proposal_id = %s",
                (str(user_id), proposal_id),
            )).fetchone()
        return self._archive_proposal_row(row) if row is not None else None

    async def list_archive_proposals(
        self, user_id: UserId, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """This user's proposals, newest first. Bounded: a listing is a page, not a history."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                f"SELECT {self._ARCHIVE_PROPOSAL_COLUMNS} FROM archive_proposals "
                "WHERE user_id = %s ORDER BY created_at DESC, proposal_id DESC LIMIT %s",
                (str(user_id), limit),
            )).fetchall()
        return [self._archive_proposal_row(r) for r in rows]

    async def confirm_archive_proposal(
        self,
        user_id: UserId,
        proposal_id: str,
        *,
        items: list[dict[str, Any]],
        job_kind: str,
        payload: dict[str, Any],
        note: str | None = None,
        note_given: bool = False,
    ) -> str | None:
        """Accept one proposal AND queue the job that executes it — in one transaction.

        Returns the job id, or None when the row was no longer `proposed` (another confirm
        or a drop reached it first) and therefore nothing at all was written.

        The two halves are one statement pair on purpose. Split across two calls they have
        to be ordered, and BOTH orders are a real state the system cannot reconcile: flip
        first and a queue that refuses leaves a `confirmed` proposal nothing will ever
        execute and nothing will ever fail — invisible, not stuck; enqueue first and a flip
        that loses its predicate leaves a job for a decision that was never made. Committed
        together, neither exists, and there is nothing to compensate for — which is why the
        caller has no undo path and an exception here is an ordinary failure over a proposal
        that is still open.

        The job id is minted HERE and written into both rows, so the proposal names the job
        that carries it from the moment either exists. That also removes the second write the
        old shape needed: there is no window in which the row is `confirmed` with a null
        `job_id`, and therefore no bookkeeping update that a worker finishing first could
        race. `status = 'proposed'` in the WHERE clause is what decides the transition — the
        caller's read above it cannot, because two confirms in flight both read `proposed`.

        `note_given` is the difference between "the Owner said nothing about the note" and
        "the Owner CLEARED it", and the two cannot share a spelling. `COALESCE(%s, note)`
        reads a NULL as the first, so an explicitly emptied note fell through to the plan's
        old one — and the record then quoted a sentence the confirm's preview had already
        replaced with the default. Given, the column is assigned outright and a `None` writes
        SQL NULL on purpose; absent, the old COALESCE stands and the plan's note is kept.
        """
        job_id = uuid.uuid4().hex
        # Assigned outright when the caller SAID something about the note (`""` cleared it
        # to NULL included); COALESCE'd — "keep what the plan recorded" — when they did not.
        note_clause = "note = %s " if note_given else "note = COALESCE(%s, note) "
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor() as cur:
                await cur.execute(
                    "UPDATE archive_proposals SET status = 'confirmed', "
                    # `::jsonb` explicitly: psycopg adapts a Json() to `json`, which the
                    # jsonb column will not take without the cast.
                    "items = %s::jsonb, confirmed_at = %s, job_id = %s, "
                    # The Owner's reason is typed at the decision; a confirm that says
                    # nothing leaves whatever the plan recorded.
                    + note_clause
                    + "WHERE user_id = %s AND proposal_id = %s AND status = 'proposed'",
                    (
                        Json(list(items)),
                        datetime.now(timezone.utc),
                        job_id,
                        note,
                        str(user_id),
                        proposal_id,
                    ),
                )
                if cur.rowcount != 1:
                    # The predicate lost. Returning inside the transaction block commits an
                    # UPDATE that matched nothing — no job is inserted, and the caller is
                    # told it was not the one that decided.
                    return None
                await cur.execute(
                    "INSERT INTO compile_jobs (id, user_id, kind, payload) "
                    "VALUES (%s, %s, %s, %s)",
                    (job_id, str(user_id), job_kind, Json(dict(payload))),
                )
        return job_id

    async def update_archive_proposal(
        self,
        user_id: UserId,
        proposal_id: str,
        *,
        status: str,
        items: list[dict[str, Any]] | None = None,
        confirmed_at: datetime | None = None,
        executed_at: datetime | None = None,
        job_id: str | None = None,
        detail: str | None = None,
        note: str | None = None,
        note_given: bool = False,
        statement_ref: str | None = None,
        expected_status: str | None = None,
    ) -> bool:
        """Advance one proposal's lifecycle; True when this call is the one that moved it.

        The lifecycle writes that are NOT the confirm: the stale mark, the drop, and the
        job's own terminal `executed` / `failed`. (The confirm has its own statement,
        `confirm_archive_proposal`, because it must commit the job in the same transaction.)

        Every optional field is written only when given (`COALESCE`), so a later stage never
        blanks what an earlier one recorded: an `executed` update does not erase the
        `confirmed_at` the confirm stamped, and a `failed` update keeps the job that ran.
        What is kept in `items` is what was EXECUTED, and the seeds and library_ref beside it
        stay untouched.

        `note` is the one field with an explicit "cleared" state, and it takes the same
        `note_given` flag `confirm_archive_proposal` does: COALESCE cannot spell the
        difference between "say nothing about it" and "empty it", and a caller that means the
        second must be able to write NULL deliberately rather than have it read as the first.

        `expected_status` makes the lifecycle transition ATOMIC. Read-then-write cannot
        decide "is this proposal still `confirmed`" — a finished job and an operator's
        repair both read it and both write. Appended to the WHERE clause, the predicate is
        evaluated by the row lock: exactly one statement matches, the loser updates nothing,
        and `rowcount == 1` is how the caller learns which it was. Without it the statement
        is unconditional.
        """
        clause = "" if expected_status is None else " AND status = %s"
        tail: tuple = (
            (str(user_id), proposal_id)
            if expected_status is None
            else (str(user_id), proposal_id, expected_status)
        )
        note_clause = "note = %s, " if note_given else "note = COALESCE(%s, note), "
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE archive_proposals SET status = %s, "
                # `::jsonb` explicitly: psycopg adapts a Json() to `json`, and COALESCE
                # will not coerce json to the column's jsonb on its own.
                "items = COALESCE(%s::jsonb, items), "
                "confirmed_at = COALESCE(%s, confirmed_at), "
                "executed_at = COALESCE(%s, executed_at), "
                "job_id = COALESCE(%s, job_id), "
                "detail = COALESCE(%s, detail), "
                + note_clause +
                # The job fills this in when it ingests the owner's statement, so the
                # proposal names the source its record cites. COALESCE like the rest: a
                # statement_ref the OWNER supplied at plan time is never overwritten.
                "statement_ref = COALESCE(%s, statement_ref) "
                "WHERE user_id = %s AND proposal_id = %s" + clause,
                (
                    status,
                    Json(list(items)) if items is not None else None,
                    confirmed_at,
                    executed_at,
                    job_id,
                    detail,
                    note,
                    statement_ref,
                    *tail,
                ),
            )
        return cur.rowcount == 1

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

        `archive_proposals` is not copied either, for the same shape of reason: a proposal is
        the OWNER's record of a decision about the live library, and a frozen tenant refuses
        every write — a proposal that could never be confirmed there would be a decision the
        snapshot cannot make. The RESULT of an executed proposal does ride along, because it
        lives on the two authorities: `sources.archived_at` above, and the `archive/` paths
        in the canonical repository the snapshot pins by ref.
        """
        src, dst = str(source), str(target)
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO sources (user_id, source_id, kind, source_class, title, "
                    "mime, checksum, created_at, meta, intake_plan, structure_map, "
                    "digested_at, origin, archived_at) "
                    "SELECT %s, source_id, kind, source_class, title, mime, checksum, "
                    "created_at, meta, intake_plan, structure_map, digested_at, origin, "
                    "archived_at "
                    "FROM sources WHERE user_id = %s ON CONFLICT DO NOTHING",
                    (dst, src),
                )
                await conn.execute(
                    "INSERT INTO blocks (user_id, source_id, block_index, text, "
                    "section_path, images) "
                    "SELECT %s, source_id, block_index, text, section_path, images "
                    "FROM blocks WHERE user_id = %s ON CONFLICT DO NOTHING",
                    (dst, src),
                )
                await conn.execute(
                    "INSERT INTO canonical_claims (user_id, document_path, anchor, "
                    "section_path, text, citations, snapshot_ref, updated_at, archived) "
                    "SELECT %s, document_path, anchor, section_path, text, citations, "
                    "snapshot_ref, updated_at, archived "
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

    async def list_media_objects(self, user_id: UserId) -> dict[str, str]:
        """Return this tenant's media storage keys and authoritative digests."""

        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT images FROM blocks WHERE user_id = %s AND images <> '[]'::jsonb",
                (str(user_id),),
            )).fetchall()
        objects: dict[str, str] = {}
        for (images,) in rows:
            for image in images:
                key = str(image["storage_key"])
                digest = str(image["sha256"])
                previous = objects.setdefault(key, digest)
                if previous != digest:
                    raise RuntimeError(
                        f"media key {key!r} is associated with conflicting digests"
                    )
        return objects

    async def rewrite_media_keys(
        self, user_id: UserId, replacements: Mapping[str, str]
    ) -> int:
        """Retarget copied block manifests to media owned by the copied tenant."""

        if not replacements:
            return 0
        changed = 0
        async with self._pool.connection() as conn:
            async with conn.transaction():
                rows = await (await conn.execute(
                    "SELECT source_id, block_index, images FROM blocks "
                    "WHERE user_id = %s AND images <> '[]'::jsonb FOR UPDATE",
                    (str(user_id),),
                )).fetchall()
                for source_id, block_index, images in rows:
                    updated = [dict(image) for image in images]
                    touched = False
                    for image in updated:
                        old_key = str(image["storage_key"])
                        if old_key in replacements:
                            image["storage_key"] = replacements[old_key]
                            touched = True
                            changed += 1
                    if touched:
                        await conn.execute(
                            "UPDATE blocks SET images = %s WHERE user_id = %s "
                            "AND source_id = %s AND block_index = %s",
                            (Json(updated), str(user_id), source_id, block_index),
                        )
        return changed

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
        stages: list[dict[str, Any]] | None = None,
        pack_manifest: list[dict[str, str]] | None = None,
    ) -> None:
        """Persist one built pack. `stages` is the build's measured breakdown in the wire
        shape ([{name, ms, status, detail}]) — stored beside the pack so a briefing built
        weeks ago can still say where its seconds went; omitted, the column keeps its '[]'.

        `pack_manifest` is what that pack put in front of the model ([{kind, ref, path}]),
        and it is written in the SAME statement as the text it describes: an ask admits its
        citations against it, and a pack stored without one would be a pack whose answers
        can cite nothing. Neither can be recovered afterwards — the build happened once."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO briefings (briefing_id, user_id, scope, "
                "snapshot_ref, system_prefix, stages, pack_manifest) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    briefing_id,
                    str(user_id),
                    Json(scope),
                    snapshot_ref,
                    system_prefix,
                    Json(list(stages or [])),
                    Json(list(pack_manifest or [])),
                ),
            )

    async def get_briefing(
        self, user_id: UserId, briefing_id: str
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT briefing_id, scope, snapshot_ref, system_prefix, created_at, "
                "stages, pack_manifest "
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
            "stages": row[5] or [],
            # Kept in the stored shape: the ask route turns it into `EvidenceRef`s, and the
            # detail route never shows it. A row from before the column reads as [].
            "pack_manifest": row[6] or [],
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

    # --- consultations (use-side L0) ------------------------------------------
    #
    # The one table in this file that `rebuild_derived` must never touch: a consultation is
    # a RECORD of something that happened, not a projection of something stored elsewhere,
    # so there is nothing to re-derive it from. It is also never read by the knowledge side
    # — no gate, contract or compile input joins against it (I6's read-side sibling).

    @staticmethod
    def _evidence_json(refs: Any) -> list[dict[str, str]]:
        return [{"kind": r.kind, "ref": r.ref, "path": r.path} for r in refs or ()]

    @staticmethod
    def _evidence_refs(raw: Any) -> tuple[EvidenceRef, ...]:
        return tuple(
            EvidenceRef(
                kind=str(item.get("kind", "")),
                ref=str(item.get("ref", "")),
                path=str(item.get("path", "")),
            )
            for item in (raw or [])
        )

    async def list_consultation_users(self) -> list[str]:
        """Distinct user_ids that made at least one consultation.

        The sibling of `list_users`, and the reason it exists: a component projection may be
        derived from these records rather than from L0, so a tenant that asked questions
        before importing anything owns a derived layer that `rebuild_derived --all` would
        otherwise never visit. Same shape as `list_users` — the id set and nothing else, so
        no cross-user data read exists here either (I1) — and frozen snapshot tenants are
        excluded for the same reason.
        """
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT DISTINCT user_id FROM consultations "
                "WHERE user_id NOT LIKE %s ORDER BY user_id",
                (f"{RESERVED_PREFIX}%",),
            )).fetchall()
        return [r[0] for r in rows]

    async def create_consultation(
        self, user_id: UserId, record: ConsultationRecord
    ) -> str | None:
        """Write one consultation and, for a `business` visitor, ENQUEUE its delivery — in
        one transaction. Returns the job id, or None when nothing was queued.

        `user_id` is the caller's, not the record's: the row is keyed by the tenant whose
        library answered (I1), and the record's own copy travels with it so a consumer
        reading the record never has to be told which user it is.

        The row and the job commit together, so neither half can exist alone: no job ever
        names a consultation that is not there, and no `business` record is ever written
        with nobody scheduled to read it. The enqueue is conditional on the INSERT having
        actually inserted (`rowcount`, past the `ON CONFLICT`), because a replayed record —
        an import, a retry above this layer — must not mint a second job for a row that
        already has one.

        Nothing is processed here. Delivery is the ordinary job queue the ingest side
        already uses, drained per user by the compile worker, and the request path that
        called this waits on none of it.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO consultations (user_id, consultation_id, created_at, "
                    "lane, visitor_class, question, as_of, library_ref, evidence_handed, "
                    "answer_kind, answer, citations, miss, degraded, token_usage) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (user_id, consultation_id) DO NOTHING",
                    (
                        str(user_id),
                        record.consultation_id,
                        record.created_at,
                        record.lane,
                        record.visitor_class,
                        record.question,
                        record.as_of,
                        record.library_ref,
                        Json(self._evidence_json(record.evidence_handed)),
                        record.answer_kind,
                        record.answer,
                        Json(self._evidence_json(record.citations)),
                        record.miss,
                        Json([list(pair) for pair in record.degraded]),
                        # An OBJECT, not the record's pairs: `/spend` sums these in SQL,
                        # and summing an array of pairs would mean shipping every row to
                        # Python. Field order is restored on read from `USAGE_FIELDS`.
                        Json(dict(record.token_usage)),
                    ),
                )
                if not cur.rowcount or record.visitor_class != "business":
                    return None
                job_id = uuid.uuid4().hex
                await cur.execute(
                    "INSERT INTO compile_jobs (id, user_id, kind, payload) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        job_id,
                        str(user_id),
                        RECALL_PROJECTION_JOB_KIND,
                        Json({"consultation_id": record.consultation_id}),
                    ),
                )
        return job_id

    async def get_consultation(
        self, user_id: UserId, consultation_id: str
    ) -> ConsultationRecord | None:
        """One record by id, or None — the projection job's own read (I1: another tenant's
        id is simply not there)."""
        rows = await self._consultation_rows(
            ["user_id = %s", "consultation_id = %s"],
            [str(user_id), consultation_id],
            user_id,
            limit=1,
        )
        return rows[0] if rows else None

    async def list_consultations(
        self,
        user_id: UserId,
        *,
        since: datetime | None = None,
        visitor_class: str | None = None,
        projected: bool | None = None,
        limit: int = CONSULTATION_PAGE,
        after: tuple[datetime, str] | None = None,
    ) -> list[ConsultationRecord]:
        """One user's consultations, oldest first, bounded.

        This is the REPLAY face: a component's ledger is rebuilt by re-applying these in the
        order they were recorded, so the order has to be total. `created_at` alone is not —
        two calls can land in the same microsecond — so the id is the tie-break, in the sort
        and in the `after` cursor alike. `after` is the last record of the previous page as
        `(created_at, consultation_id)`; newer rows arriving mid-walk never shift a page.

        `projected=True` restricts the walk to records already stamped `projected_at` —
        the ones whose own projection job has run. That is what a replay must count, and
        `rebuild_access_stats` explains why.
        """
        clauses = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        if visitor_class is not None:
            clauses.append("visitor_class = %s")
            params.append(visitor_class)
        if projected is not None:
            clauses.append(
                "projected_at IS NOT NULL" if projected else "projected_at IS NULL"
            )
        if after is not None:
            clauses.append("(created_at, consultation_id) > (%s, %s)")
            params.extend([after[0], after[1]])
        return await self._consultation_rows(
            clauses, params, user_id, limit=max(1, int(limit))
        )

    async def list_consultations_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        before: tuple[datetime, str] | None = None,
        lane: str | None = None,
        visitor_class: str | None = None,
        miss: bool | None = None,
        target: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """One keyset-paginated page of consultation SUMMARIES, newest first.

        A different face from `list_consultations`, and deliberately not a flag on it. That
        one is the REPLAY face — ascending, whole records, the order a rebuild re-applies
        them in — and a descending page that shared its code would put the rebuild one
        parameter away from replaying the ledger backwards. This one is the READING face: a
        human scanning what was asked, newest first, with the record's body left on the
        detail route.

        `citation_count` is counted in SQL rather than by shipping the array to Python: the
        listing's whole point is to stay small, and a page of fifty consultations that each
        carry their evidence manifest is the detail route fifty times over.

        `target` is the reverse lookup — which consultations put THIS address in front of a
        model — and it matches on `ref` and on `path`, in both arrays. A page is reached two
        ways: opened and read in full (its path is the `ref`) or through a claim that lives
        on it (its path is the claim's `path`), so a `ref`-only predicate would answer
        "nothing" for exactly the page whose access card offered the link.
        """
        filters = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if lane:
            filters.append("lane = %s")
            params.append(lane)
        if visitor_class:
            filters.append("visitor_class = %s")
            params.append(visitor_class)
        if miss is not None:
            filters.append("miss = %s")
            params.append(bool(miss))
        if target:
            filters.append(
                "(evidence_handed @> %s OR evidence_handed @> %s "
                "OR citations @> %s OR citations @> %s)"
            )
            # `Jsonb`, not `Json`: `@>` is a jsonb operator and there is no implicit cast
            # from `json` to it — an INSERT into a jsonb column casts, a containment test
            # does not.
            by_ref = Jsonb([{"ref": target}])
            by_path = Jsonb([{"path": target}])
            params.extend([by_ref, by_path, by_ref, by_path])
        filtered_where = " AND ".join(filters)

        page_filters = list(filters)
        page_params = list(params)
        if before is not None:
            page_filters.append("(created_at, consultation_id) < (%s, %s)")
            page_params.extend(before)
        page_where = " AND ".join(page_filters)

        async with self._pool.connection() as conn:
            count_row = await (await conn.execute(
                f"SELECT count(*) FROM consultations WHERE {filtered_where}",
                params,
            )).fetchone()
            rows = await (await conn.execute(
                "SELECT consultation_id, created_at, lane, visitor_class, question, "
                "miss, answer_kind, library_ref, jsonb_array_length(citations), "
                "jsonb_array_length(evidence_handed), token_usage FROM consultations "
                f"WHERE {page_where} "
                "ORDER BY created_at DESC, consultation_id DESC LIMIT %s",
                [*page_params, limit + 1],
            )).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        return (
            [
                {
                    "consultation_id": r[0],
                    "created_at": r[1],
                    "lane": r[2],
                    "visitor_class": r[3],
                    "question": r[4],
                    "miss": bool(r[5]),
                    "answer_kind": r[6],
                    "library_ref": r[7],
                    "citation_count": int(r[8] or 0),
                    "evidence_count": int(r[9] or 0),
                    "token_usage": usage_pairs(r[10] or {}),
                }
                for r in rows
            ],
            int(count_row[0]) if count_row is not None else 0,
            has_more,
        )

    async def consultation_spend(
        self, user_id: UserId, *, since: datetime, until: datetime
    ) -> list[dict[str, Any]]:
        """What this library's recorded consultations spent over a window, grouped.

        One row per `(lane, visitor_class)` cell with the consultation count and the summed
        token counters. Summed IN SQL: an aggregate that shipped every row to Python would
        get slower exactly as a library gets more use, which is the moment somebody starts
        asking what it costs.

        A missing counter (an old row, a lane that reported none) is NULL to `->>` and is
        skipped by `sum`, so it contributes nothing rather than a zero standing in for it.
        That leaves a hole a sum cannot show: a cell of rows that all reported NOTHING sums
        to null and coalesces to an all-zero usage map, which reads exactly like a cell of
        calls that were genuinely free. So the cell also carries `with_usage` — how many of
        its consultations reported any counter at all — and a reader compares it against
        `consultations` to know whether the tokens beside it are the whole story.

        This is the spend of RECORDED consultations and nothing else — the deployment's total
        bill is elsewhere by construction: a `silent` visitor leaves no row at all, and the
        Live Context lane records none. The endpoint over this says so.
        """
        counters = ", ".join(
            f"coalesce(sum((token_usage->>'{name}')::bigint), 0)" for name in USAGE_FIELDS
        )
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT lane, visitor_class, count(*), "
                "count(*) FILTER (WHERE token_usage <> '{}'::jsonb), "
                f"{counters} FROM consultations "
                "WHERE user_id = %s AND created_at >= %s AND created_at <= %s "
                "GROUP BY lane, visitor_class ORDER BY lane, visitor_class",
                (str(user_id), since, until),
            )).fetchall()
        return [
            {
                "lane": r[0],
                "visitor_class": r[1],
                "consultations": int(r[2] or 0),
                "with_usage": int(r[3] or 0),
                "token_usage": {
                    name: int(r[4 + i] or 0) for i, name in enumerate(USAGE_FIELDS)
                },
            }
            for r in rows
        ]

    async def _consultation_rows(
        self, clauses: list[str], params: list[Any], user_id: UserId, *, limit: int
    ) -> list[ConsultationRecord]:
        """The one SELECT + row→record mapping both consultation reads share."""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT consultation_id, created_at, lane, visitor_class, question, "
                "as_of, library_ref, evidence_handed, answer_kind, answer, citations, "
                "miss, degraded, token_usage FROM consultations WHERE " + " AND ".join(clauses)
                + " ORDER BY created_at, consultation_id LIMIT %s",
                tuple([*params, limit]),
            )).fetchall()
        return [
            ConsultationRecord(
                consultation_id=r[0],
                user_id=str(user_id),
                created_at=r[1],
                lane=r[2],
                visitor_class=r[3],
                question=r[4],
                as_of=r[5],
                library_ref=r[6],
                evidence_handed=self._evidence_refs(r[7]),
                answer_kind=r[8],
                answer=r[9],
                citations=self._evidence_refs(r[10]),
                miss=bool(r[11]),
                degraded=tuple((str(a), str(b)) for a, b in (r[12] or [])),
                token_usage=usage_pairs(r[13] or {}),
            )
            for r in rows
        ]

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
                # The Owner's archive decisions: kept records with no FK to cascade from.
                await conn.execute(
                    "DELETE FROM archive_proposals WHERE user_id = %s",
                    (str(user_id),),
                )
                # The people projection is the one component table with no source FK to
                # cascade from — a term's row belongs to the library, not to one source —
                # and the manifest of the sources accumulated into it is keyed the same way,
                # so the two go together here as they do in `delete_people_terms`.
                for table in ("component_people_terms", "component_people_indexed"):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE user_id = %s", (str(user_id),)
                    )
                # The use-side record and everything projected from it. Neither hangs off a
                # source either, and a consultation holds the owner's QUESTIONS verbatim —
                # so a tenant deletion that left them behind would leave exactly the rows
                # nobody would think to look for.
                for table in (
                    "consultations",
                    "recall_access_hits",
                    "recall_access_misses",
                ):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE user_id = %s", (str(user_id),)
                    )
                await conn.execute(
                    "DELETE FROM sources WHERE user_id = %s",
                    (str(user_id),),
                )
