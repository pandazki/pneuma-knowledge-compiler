"""In-memory stand-ins for the read faces `pkc`'s read commands call.

The shipped store is Postgres. What the read commands depend on is not its SQL but its
SHAPE — the page tuples, the row dicts, the block spans a locator resolves to — and that
shape is a contract between the routes, the CLI and the console. So it is implemented once
more here, over dicts, and the keyless suite exercises every read command against it; the
Postgres tier re-checks the same questions against real SQL when middleware is reachable.

Nothing here is a production path: no persistence, no paging cursors beyond a slice, no
attempt to be fast. What it does keep faithfully is `user_id` isolation (I1) — every method
takes it first and answers only about that tenant — because a double that ignored it would
let a test pass that the real store would fail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.consultation import ConsultationRecord
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.domain.source import NormalizedSource

from .draft_mock import InMemoryJobQueue


class InMemoryLibraryStore(InMemoryJobQueue):
    """L0 + the queue + the use-side records, as one store — the way `PostgresStore` is one.

    Inherits the job queue rather than reimplementing it: `pkc jobs` reads the same rows
    `pkc draft open` claims, and two doubles disagreeing about a job's status would be a bug
    the suite invented.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sources: dict[tuple[str, str], NormalizedSource] = {}
        #: Ledger rows a test seeds directly — `pkc history` and `pkc brief` read the same
        #: ledger, and deriving one from the queue here would be inventing a projection the
        #: real store builds in SQL out of tables this double does not have. Each row is
        #: `{user_id, kind, ref, ts, payload}` in the shape `list_history_page` returns.
        self.history: list[dict[str, Any]] = []
        self.consultations: list[dict[str, Any]] = []
        self.projection_jobs: list[str] = []
        #: The owner's own picture, as `PostgresStore` keeps it: one JSON document per
        #: tenant, written by `pkc profile set` / `app.py init` and read back by the
        #: composite provider.
        self.profiles: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------- the owner's own profile

    async def upsert_user_profile(self, user_id, profile: dict[str, Any]) -> None:  # noqa: ANN001
        self.profiles[str(user_id)] = dict(profile)

    async def get_user_profile(self, user_id) -> dict[str, Any] | None:  # noqa: ANN001
        stored = self.profiles.get(str(user_id))
        return dict(stored) if stored is not None else None

    # ---------------------------------------------------------------- L0 (ContentStore)

    async def add(self, user_id, source: NormalizedSource) -> SourceId:  # noqa: ANN001
        key = (str(user_id), str(source.raw.source_id))
        self._sources.setdefault(key, source)
        return self._sources[key].raw.source_id

    async def get(self, user_id, source_id) -> NormalizedSource:  # noqa: ANN001
        try:
            return self._sources[(str(user_id), str(source_id))]
        except KeyError as exc:
            raise KeyError(f"no such source: {source_id}") from exc

    async def list(self, user_id):  # noqa: ANN001
        return [
            ns.raw for (uid, _sid), ns in self._sources.items() if uid == str(user_id)
        ]

    async def fetch(self, user_id, source_id, locator) -> str:  # noqa: ANN001
        source = await self.get(user_id, source_id)
        start, end = source.structure.resolve(locator)
        blocks = [b for b in source.blocks if start <= b.index <= end]
        if not blocks:
            raise ValueError(f"no blocks in {source_id} ¶{start}-{end}")
        return "\n\n".join(b.text for b in blocks)

    async def block_counts(self, user_id, source_ids=None) -> dict[str, int]:  # noqa: ANN001
        wanted = None if source_ids is None else {str(s) for s in source_ids}
        return {
            str(ns.raw.source_id): len(ns.blocks)
            for (uid, sid), ns in self._sources.items()
            if uid == str(user_id) and (wanted is None or sid in wanted)
        }

    async def digested_map(self, user_id, source_ids=None) -> dict[str, str | None]:  # noqa: ANN001
        return {}

    async def archived_source_ids(self, user_id):  # noqa: ANN001
        """The L0 half of the archive mark, as the assembly filter reads it.

        Answered rather than left absent: `archive_view` treats a store WITHOUT this method
        as a library that has never archived anything, so a double that stayed silent would
        label nothing and every `include_archived` test would pass over evidence it never
        marked (docs/design/archive.md §2.2).
        """
        return frozenset(
            str(ns.raw.source_id)
            for (uid, _sid), ns in self._sources.items()
            if uid == str(user_id) and getattr(ns.raw, "archived_at", None) is not None
        )

    async def list_sources_page(  # noqa: ANN001
        self, user_id, *, limit=25, before=None, query=None, kind=None, include_archived=False
    ):
        # `archived_at` is filtered here rather than accepted and ignored: a stand-in that
        # takes the keyword and returns the archive anyway is how a leak passes a test suite
        # (docs/design/archive.md §3).
        rows = [
            ns.raw
            for (uid, _sid), ns in self._sources.items()
            if uid == str(user_id)
            and (include_archived or getattr(ns.raw, "archived_at", None) is None)
            and (not query or query.lower() in (ns.raw.title or "").lower())
            and (not kind or ns.raw.kind == kind)
        ]
        rows.sort(key=lambda r: (r.created_at, str(r.source_id)), reverse=True)
        return rows[:limit], len(rows), len(rows) > limit

    # -------------------------------------------------------------------- queue pages

    async def list_jobs_page(  # noqa: ANN001
        self, user_id, *, limit=25, before=None, status=None, kind=None
    ):
        rows = [
            {
                "job_id": job.job_id,
                "kind": job.kind,
                "status": job.status,
                "payload": dict(job.payload),
                "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
                "completed_at": None,
                # The OUTCOME as this queue actually recorded it (`complete`, then
                # `record_job_usage`), not a row of Nones: a double that always reported
                # "no executor, no usage" made the queue's own report untestable keyless,
                # which is how a job row that stored neither went unnoticed for a whole
                # end-to-end run (docs/design/coding-agent-mode.md §9).
                **self._outcome(user_id, job.job_id),
            }
            for job in reversed(self.jobs)
            if str(job.user_id) == str(user_id)
            and (not status or job.status == status)
            and (not kind or job.kind == kind)
        ]
        return rows[:limit], len(rows), len(rows) > limit

    def _outcome(self, user_id, job_id: str) -> dict:  # noqa: ANN001
        """What the last `complete` for this job recorded, or the un-finished shape."""
        blank = {"ok": None, "detail": None, "snapshot_ref": None, "executor": None,
                 "token_usage": {}}
        for record in reversed(self.completed):
            if record["job_id"] == job_id and record["user_id"] == str(user_id):
                return {
                    "ok": record.get("ok"),
                    "detail": record.get("detail"),
                    "snapshot_ref": record.get("snapshot_ref"),
                    "executor": record.get("executor"),
                    "token_usage": dict(record.get("token_usage") or {}),
                }
        return blank

    async def list_history_page(  # noqa: ANN001
        self, user_id, *, limit=25, before=None, kind=None
    ):
        rows = [r for r in self.history if r.get("user_id", str(user_id)) == str(user_id)]
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        counts = {"total": len(rows), "patch": 0, "job": 0, "snapshot": 0}
        for row in rows:
            counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        return rows[:limit], counts, len(rows) > limit

    # ----------------------------------------------------------------- use-side records

    async def create_consultation(self, user_id, record: ConsultationRecord):  # noqa: ANN001
        self.consultations.append(
            {
                "user_id": str(user_id),
                "consultation_id": record.consultation_id,
                "created_at": record.created_at,
                "lane": record.lane,
                "visitor_class": record.visitor_class,
                "question": record.question,
                "as_of": record.as_of,
                "library_ref": record.library_ref,
                "evidence_handed": [
                    {"kind": e.kind, "ref": e.ref, "path": e.path}
                    for e in record.evidence_handed
                ],
                "answer_kind": record.answer_kind,
                "answer": record.answer,
                "citations": [
                    {"kind": c.kind, "ref": c.ref, "path": c.path, "origin": c.origin}
                    for c in record.citations
                ],
                "miss": record.miss,
                "citations_direct": record.citations_direct,
                "evidence_count": len(record.evidence_handed),
                "citation_count": len(record.citations),
                "degraded": list(record.degraded),
                "token_usage": dict(record.token_usage),
            }
        )
        # The real store enqueues delivery for a `business` visitor in the same transaction;
        # this records the same fact, so a test can ask whether one job was queued.
        if record.visitor_class == "business":
            job_id = await self.enqueue(
                user_id, "recall_projection", {"consultation_id": record.consultation_id}
            )
            self.projection_jobs.append(job_id)
            return job_id
        return None

    async def list_consultations_page(  # noqa: ANN001
        self,
        user_id,
        *,
        limit=25,
        before=None,
        lane=None,
        visitor_class=None,
        miss=None,
        target=None,
    ):
        rows = [
            row
            for row in reversed(self.consultations)
            if row["user_id"] == str(user_id)
            and (not lane or row["lane"] == lane)
            and (not visitor_class or row["visitor_class"] == visitor_class)
            and (miss is None or bool(row["miss"]) is bool(miss))
        ]
        return rows[:limit], len(rows), len(rows) > limit

    async def consultation_spend(self, user_id, *, since, until):  # noqa: ANN001
        cells: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.consultations:
            if row["user_id"] != str(user_id):
                continue
            if not (since <= row["created_at"] <= until):
                continue
            key = (row["lane"], row["visitor_class"])
            cell = cells.setdefault(
                key,
                {
                    "lane": row["lane"],
                    "visitor_class": row["visitor_class"],
                    "consultations": 0,
                    "with_usage": 0,
                    "token_usage": {},
                },
            )
            cell["consultations"] += 1
            if row["token_usage"]:
                cell["with_usage"] += 1
            for name, value in row["token_usage"].items():
                cell["token_usage"][name] = cell["token_usage"].get(name, 0) + int(value)
        return list(cells.values())


__all__ = ["InMemoryLibraryStore"]
