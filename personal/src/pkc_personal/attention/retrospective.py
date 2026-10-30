"""Dated project activity from L0, through a dedicated read-only database connection.

Owner turns are a visible proxy for recorded involvement, never measured work hours.
Collection identity is read from completed kept observations without taking the writer lock.
"""

from __future__ import annotations
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import make_conninfo


def bindings(library) -> dict:
    path = library.path / "collection-observations.jsonl"
    if not path.exists():
        return {}
    # A writer may be appending. Only newline-terminated records are observations.
    lines = path.read_bytes().splitlines(keepends=True)
    result = {}
    for line in lines:
        if not line.endswith(b"\n"):
            continue
        row = json.loads(line)
        if row.get("provider") and row.get("session_id"):
            result[(row["provider"], row["session_id"], row.get("project_path"))] = (
                row.get("project_id")
            )
    return result


def aggregate(
    rows: list[dict], identities: dict, since: str, until: str, *, truncated=False
) -> dict:
    daily = defaultdict(lambda: defaultdict(int))
    projects = {}
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        # Incremental source exports can contain the same native turn. Count it once.
        key = (
            row["provider"],
            row["session"],
            row["turn_id"] or (row["source_id"], row["block"]),
        )
        if key in seen:
            continue
        seen.add(key)
        path = row.get("project_path")
        identity = identities.get((row["provider"], row["session"], path))
        identity = (
            identity
            or "path-"
            + hashlib.sha256((path or "unattributed").encode()).hexdigest()[:16]
        ).replace("_", "-")
        name = Path(path).name if path else "Unattributed"
        projects[identity] = {
            "id": identity,
            "name": name,
            "attribution": "collection"
            if identities.get((row["provider"], row["session"], path))
            else "source_path"
            if path
            else "unknown",
        }
        day = str(row["day"])
        daily[day][identity] += 1
        groups[(day, identity)].append(row)
    start, end = (
        datetime.fromisoformat(since).date(),
        datetime.fromisoformat(until).date(),
    )
    days = []
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        counts = dict(daily[day])
        days.append({"date": day, "counts": counts, "total": sum(counts.values())})
    totals = {
        identity: sum(d["counts"].get(identity, 0) for d in days)
        for identity in projects
    }
    ordered = sorted(projects.values(), key=lambda p: (-totals[p["id"]], p["id"]))
    selected = {p["id"] for p in ordered[:10]}
    samples = []
    for (day, identity), group in sorted(groups.items()):
        if identity not in selected:
            continue
        # First and last recorded Owner turns give temporal context without treating a
        # model's activity stubs as the Owner's investment. The selection is declared.
        for row in group[:1] if len(group) == 1 else [group[0], group[-1]]:
            samples.append(
                {
                    "ref": f"source:{row['source_id']}:{row['block']}",
                    "path": f"source/{row['source_id']}/{row['block']}",
                    "head": None,
                    "text": row["text"],
                    "project_id": identity,
                    "date": day,
                    "source_id": row["source_id"],
                    "block": row["block"],
                    "truncated": row.get("text_length", len(row["text"]))
                    > len(row["text"]),
                }
            )
    candidate_count = len(samples)
    if candidate_count > 96:
        # Evenly sample the whole interval, retaining both endpoints and bounding context.
        samples = [samples[round(i * (candidate_count - 1) / 95)] for i in range(96)]
    return {
        "since": since,
        "until": until,
        "metric": "recorded_owner_turns",
        "projects": ordered,
        "days": days,
        "samples": samples,
        "coverage": {
            "truncated": truncated,
            "dated_owner_turns": len(seen),
            "external_channels": "unknown",
            "sample_count": len(samples),
            "candidate_samples": candidate_count,
            "sampling": "first and last Owner turn per day/project; top ten projects; at most 96 evenly spaced samples",
            "interpretation": "Recorded involvement, not time spent. A zero is no matching record, not proof of inactivity.",
        },
    }


async def read_landscape(library, settings, now: float, days: int = 14) -> dict:
    zone = ZoneInfo(settings.default_timezone or "UTC")
    until = datetime.fromtimestamp(now, zone).date()
    since = until - timedelta(days=days - 1)
    dsn = make_conninfo(
        settings.pg_dsn,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    )
    async with await psycopg.AsyncConnection.connect(
        dsn, connect_timeout=5, application_name="pkc-attention-readonly"
    ) as conn:
        cursor = await conn.execute(
            """
            SELECT t.local_day, t.source_id, t.block_index,
                   s.meta->>'provider', s.meta->>'session_id',
                   s.meta->'project'->>'path', s.meta->'turns'->t.block_index->>'turn_id',
                   left(b.text, 1200), length(b.text)
            FROM component_time_blocks t
            JOIN sources s ON s.user_id=t.user_id AND s.source_id=t.source_id
            JOIN blocks b ON b.user_id=t.user_id AND b.source_id=t.source_id AND b.block_index=t.block_index
            WHERE t.user_id=%s AND t.local_day BETWEEN %s AND %s
              AND s.archived_at IS NULL AND s.kind='agent_session'
              AND s.meta->'turns'->t.block_index->>'role'='owner'
            ORDER BY t.local_day, t.instant_utc, t.source_id, t.block_index LIMIT 20001
        """,
            (library.state.tenant, since, until),
        )
        rows = await cursor.fetchall()
    keys = (
        "day",
        "source_id",
        "block",
        "provider",
        "session",
        "project_path",
        "turn_id",
        "text",
        "text_length",
    )
    return aggregate(
        [dict(zip(keys, row)) for row in rows[:20000]],
        bindings(library),
        since.isoformat(),
        until.isoformat(),
        truncated=len(rows) > 20000,
    )
