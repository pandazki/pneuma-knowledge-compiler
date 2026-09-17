"""What `PostgresStore.apply_schema` is allowed to do to an operator's database, who is
allowed to run it, and where it finds the file at all.

The ENGINE applies `infra/schema.sql` at every start. That makes it a bootstrap, and a
bootstrap only ever CREATES: one destructive statement in it turns a routine restart into
an irreversible deletion of data nobody was asked about. A pre-release table that nothing
reads any more is left where it stands for the operator to inspect, export and drop by hand.

The second section is about who runs it: every other process checks the marker row first
(`ensure_schema`), because the batch is DDL and a `pkc` command ran it every few minutes
beside a live engine.

The last is about reach rather than content: an installed edition (`uv tool install
pkc-personal`) has no repository around it, so the schema has to travel inside the wheel or
`pkchome setup` dies on a missing path.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

# The very text the adapter applies — read from the adapter, so a move cannot leave this
# test checking a file nothing runs.
from pneuma_knowledge_service.adapters.postgres import (
    PostgresStore,
    schema_digest,
    schema_sql,
)

#: This repository's authoritative copy, the one the docs, compose and ops scripts name.
REPO_SCHEMA = Path(__file__).resolve().parents[3] / "infra" / "schema.sql"

#: Where the packaged copy lands inside a built wheel (`force-include` in the service
#: pyproject); the adapter looks here first.
WHEEL_SCHEMA_MEMBER = "pneuma_knowledge_service/infra/schema.sql"

#: `-- …` to end of line. Comments are prose, not DDL: the file may TELL an operator which
#: statement to run by hand without running it for them.
_COMMENT_RE = re.compile(r"--[^\n]*")

_DESTRUCTIVE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|DROP\s+SCHEMA|TRUNCATE)\b", re.IGNORECASE
)


def _statements() -> str:
    return _COMMENT_RE.sub("", schema_sql())


def test_the_bootstrap_schema_executes_nothing_destructive():
    assert schema_sql().strip(), "the adapter resolved an empty schema"
    found = _DESTRUCTIVE.findall(_statements())
    assert found == [], (
        f"infra/schema.sql executes {found} — it is applied on every process start, so a "
        "destructive statement here deletes an operator's data on a restart. Leave the "
        "table and document the manual drop instead."
    )


def test_the_retired_decisions_table_is_documented_and_not_dropped():
    """The specific one this rule was written for: the `people` component's pre-release
    decisions table. The declines are frontmatter now, so nothing reads it — and nothing
    drops it either."""
    text = schema_sql()
    assert "component_people_decisions" in text  # the operator is told about it…
    assert "component_people_decisions" not in _statements()  # …only in prose


def test_the_adapter_resolves_the_repositorys_schema_in_a_source_checkout():
    """The dev layout: no packaged copy beside the module, so the resolver falls through to
    `infra/schema.sql` five directories up — the same bytes the repository holds."""
    assert schema_sql() == REPO_SCHEMA.read_text(encoding="utf-8")


def test_the_schema_travels_inside_the_built_wheel(tmp_path):
    """The installed layout, proven by building rather than by reading the pyproject: an
    edition installed from a wheel has no checkout to fall back to, so the file must be in
    the wheel, byte-for-byte the repository's."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH; cannot build the service wheel")
    package_root = Path(__file__).resolve().parents[1]
    out = tmp_path / "wheel"
    env = dict(os.environ)
    # Build detached from the caller's environment: an ambient VIRTUAL_ENV would make uv
    # resolve against the test run's venv instead of building this package on its own.
    env.pop("VIRTUAL_ENV", None)
    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(out)],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheels = sorted(out.glob("*.whl"))
    assert wheels, f"no wheel built into {out}"
    with zipfile.ZipFile(wheels[-1]) as wheel:
        assert WHEEL_SCHEMA_MEMBER in wheel.namelist(), (
            f"{WHEEL_SCHEMA_MEMBER} is missing from the wheel — a bare-wheel install would "
            "have no schema to apply"
        )
        assert wheel.read(WHEEL_SCHEMA_MEMBER) == REPO_SCHEMA.read_bytes()


# --------------------------------------------------------------- who may run the DDL
#
# The second defect this file answers: every `pkc` command applied the whole batch at
# startup. `CREATE INDEX IF NOT EXISTS` takes a ShareLock on its table whether or not it
# creates anything, so a sync ingesting every fifteen minutes — plus a home screen shelling
# out to `pkc` — ran DDL against a live engine constantly, and one of those runs deadlocked
# the engine's own rebuild (`app=pkc-cli:profile` waiting for a ShareLock on
# `component_time_blocks`, behind a rebuild holding a RowShareLock on `sources`).
#
# These exercise the mechanism on a fake connection: what matters is not what Postgres does
# with the statements but WHICH statements are sent, so they are counted.

_DDL = re.compile(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE)\b", re.IGNORECASE)


class _Cursor:
    def __init__(self, row) -> None:
        self._row = row

    async def fetchone(self):
        return self._row


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _Conn:
    """Answers the two marker SELECTs and records every statement it is given."""

    def __init__(self, log: list[str], marker: str | None) -> None:
        self.log = log
        self.marker = marker

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, sql, params=None):  # noqa: ANN001
        text = str(sql)
        self.log.append(text)
        if "to_regclass" in text:
            return _Cursor((None,) if self.marker is None else ("schema_applied",))
        if "schema_hash FROM schema_applied" in text:
            return _Cursor((self.marker,))
        return _Cursor(None)


class _Pool:
    def __init__(self, marker: str | None) -> None:
        self.log: list[str] = []
        self.marker = marker

    @asynccontextmanager
    async def connection(self, timeout=None):  # noqa: ANN001
        yield _Conn(self.log, self.marker)


def _store(marker: str | None) -> tuple[PostgresStore, _Pool]:
    store = PostgresStore("postgresql://pneuma:pneuma@127.0.0.1:1/pneuma")
    pool = _Pool(marker)
    store._pool = pool  # noqa: SLF001 — the point of the test is what reaches the wire
    return store, pool


async def test_a_matching_marker_means_a_cli_process_runs_no_ddl_at_all():
    store, pool = _store(schema_digest())
    assert await store.ensure_schema() is False
    ddl = [s for s in pool.log if _DDL.search(s)]
    assert ddl == [], f"a CLI with an up-to-date schema still sent {ddl}"
    # And it is two plain SELECTs, not a scan of anything: the marker table, then its row.
    assert len(pool.log) == 2 and all(s.lstrip().upper().startswith("SELECT") for s in pool.log)


async def test_a_mismatched_marker_applies_the_schema_and_records_the_new_hash():
    """An upgraded build whose engine has not restarted yet. The check is not a refusal —
    the process that noticed applies, so a fresh checkout behaves exactly as it always did."""
    store, pool = _store("0" * 64)
    assert await store.ensure_schema() is True
    assert any("CREATE TABLE IF NOT EXISTS sources" in s for s in pool.log)
    marker_writes = [s for s in pool.log if "INSERT INTO schema_applied" in s]
    assert len(marker_writes) == 1


async def test_a_database_with_no_marker_at_all_applies_it():
    """Every deployment that existed before this row: the table is not there, the question
    still has an answer (nothing has been applied here), and the batch runs."""
    store, pool = _store(None)
    assert await store.ensure_schema() is True
    assert any("CREATE TABLE IF NOT EXISTS sources" in s for s in pool.log)
    # It never asked for the row of a table it had just been told does not exist.
    assert not any("schema_hash FROM schema_applied" in s for s in pool.log)


def test_the_marker_table_is_created_by_the_schema_itself():
    """Otherwise the first `ensure_schema` on a cold database would have nothing to write
    its hash into — the marker has to be part of the batch it describes."""
    assert "CREATE TABLE IF NOT EXISTS schema_applied" in _statements()


def test_the_digest_is_the_schema_text_and_nothing_else():
    assert schema_digest() == hashlib.sha256(schema_sql().encode("utf-8")).hexdigest()
