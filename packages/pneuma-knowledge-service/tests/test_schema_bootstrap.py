"""What `PostgresStore.apply_schema` is allowed to do to an operator's database, and
where it finds the file at all.

Every process that boots an AppContext applies `infra/schema.sql`, on every start. That
makes it a bootstrap, and a bootstrap only ever CREATES: one destructive statement in it
turns a routine restart into an irreversible deletion of data nobody was asked about. A
pre-release table that nothing reads any more is left where it stands for the operator to
inspect, export and drop by hand.

The second half of the file is about reach rather than content: an installed edition
(`uv tool install pkc-personal`) has no repository around it, so the schema has to travel
inside the wheel or `pkchome setup` dies on a missing path.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

# The very text the adapter applies — read from the adapter, so a move cannot leave this
# test checking a file nothing runs.
from pneuma_knowledge_service.adapters.postgres import schema_sql

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
