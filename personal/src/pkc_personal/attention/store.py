"""Library-local attention records; SQLite transactions never touch canonical or PG jobs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import kernel


def stamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    board: Literal["home", "space", "river", "drops", "mosaic", "lineage", "yield"] = (
        "space"
    )
    horizon_days: int = Field(default=14, ge=7, le=90)
    window_seconds: int = Field(default=300, ge=30, le=86400)
    threshold: int = Field(default=5, ge=1, le=1000)
    min_interval_seconds: int = Field(default=300, ge=30, le=86400)
    idle_seconds: int = Field(default=21600, ge=300, le=604800)


def initial() -> dict:
    return {
        "snapshot": kernel.initial_snapshot(),
        "observed_head": None,
        "pending": {},
        "pending_count": 0,
        "pending_since": None,
        "last_run": None,
        "last_attempt": None,
        "retry_at": 0,
        "failures": 0,
        "error": None,
        "running": False,
        "heartbeat": None,
        "requested": False,
        "generation": 0,
    }


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "attention.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS frames (id INTEGER PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL);
            """)
            db.execute(
                "INSERT OR IGNORE INTO state VALUES(1, ?)", (json.dumps(initial()),)
            )
            db.execute(
                "INSERT OR IGNORE INTO preferences VALUES(1, ?)",
                (Preferences().model_dump_json(),),
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(
                db.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
            )
            yield db, state
            db.execute(
                "UPDATE state SET body=? WHERE id=1",
                (json.dumps(state, ensure_ascii=False),),
            )

    def read(self) -> dict:
        with self.connect() as db:
            return json.loads(
                db.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
            )

    def preferences(self) -> Preferences:
        with self.connect() as db:
            return Preferences.model_validate_json(
                db.execute("SELECT body FROM preferences WHERE id=1").fetchone()[0]
            )

    def configure(self, changes: dict) -> Preferences:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = json.loads(
                db.execute("SELECT body FROM preferences WHERE id=1").fetchone()[0]
            )
            prefs = Preferences.model_validate(old | changes)
            db.execute(
                "UPDATE preferences SET body=? WHERE id=1", (prefs.model_dump_json(),)
            )
            return prefs

    def request(self):
        with self.transaction() as (_, state):
            state["requested"] = True

    def frames(self, before: int | None = None, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, body FROM frames WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before or 2**63 - 1, limit),
            ).fetchall()
            return [dict(json.loads(body), id=identity) for identity, body in rows]

    def frame_headers(self, before: int | None = None, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, at, json_extract(body, '$.signal'), json_extract(body, '$.head') "
                "FROM frames WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before or 2**63 - 1, limit),
            ).fetchall()
            return [
                {"id": identity, "at": at, "signal": json.loads(signal), "head": head}
                for identity, at, signal, head in rows
            ]

    def frame(self, identity: int) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT body FROM frames WHERE id=?", (identity,)
            ).fetchone()
            return dict(json.loads(row[0]), id=identity) if row else None

    def annotate(
        self, item: str, text: str, batch: str, now: float, event_seq: int | None = None
    ) -> dict:
        with self.transaction() as (_, state):
            duplicate = kernel.check_duplicate(
                state["snapshot"],
                batch,
                kernel.canonical_request("annotate", "owner", item=item, text=text),
            )
            if duplicate is not None:
                return duplicate
            if event_seq is not None and state["snapshot"]["event_seq"] != event_seq:
                raise ValueError("The board changed; refresh before leaving a note.")
            updated, receipt = kernel.annotate(
                state["snapshot"], batch, item, text, "owner", stamp(now)
            )
            state["snapshot"] = updated
            state["generation"] += 1
            state["requested"] = True
            return receipt

    def accept(
        self,
        before: dict,
        snapshot: dict,
        receipt: dict,
        signal: dict,
        documents: list[dict],
        now: float,
        skill_hash: str,
        *,
        reflection: dict | None = None,
        landscape: dict | None = None,
    ) -> bool:
        with self.transaction() as (db, state):
            # A concurrent Owner annotation is never overwritten by a slow model response.
            if state["generation"] != before["generation"]:
                state["running"] = False
                state["retry_at"] = now + 30
                return False
            state["snapshot"] = snapshot
            state["reflection"] = reflection
            state["landscape"] = landscape
            state["generation"] += 1
            for document in documents:
                if state["pending"].get(document["path"]) == document["head"]:
                    state["pending"].pop(document["path"], None)
            state.update(
                last_run=now,
                running=False,
                error=None,
                failures=0,
                retry_at=0,
                pending_count=state["pending_count"] if state["pending"] else 0,
                requested=False,
            )
            state["pending_since"] = now if state["pending"] else None
            frame = {
                "at": stamp(now),
                "state": kernel.project_state(snapshot, stamp(now)),
                "signal": signal,
                "receipt": receipt,
                "head": before["observed_head"],
                "skill_hash": skill_hash,
                "evidence": documents,
                "reflection": reflection,
                "landscape": landscape,
            }
            db.execute(
                "INSERT INTO frames(at,body) VALUES(?,?)",
                (stamp(now), json.dumps(frame, ensure_ascii=False)),
            )
            return True
