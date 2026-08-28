"""What `PostgresStore.apply_schema` is allowed to do to an operator's database.

Every process that boots an AppContext applies `infra/schema.sql`, on every start. That
makes it a bootstrap, and a bootstrap only ever CREATES: one destructive statement in it
turns a routine restart into an irreversible deletion of data nobody was asked about. A
pre-release table that nothing reads any more is left where it stands for the operator to
inspect, export and drop by hand.
"""

from __future__ import annotations

import re

# The very file the adapter applies — read from the adapter, so a move cannot leave this
# test checking a path nothing runs.
from pneuma_knowledge_service.adapters.postgres import _SCHEMA_PATH as SCHEMA_PATH

#: `-- …` to end of line. Comments are prose, not DDL: the file may TELL an operator which
#: statement to run by hand without running it for them.
_COMMENT_RE = re.compile(r"--[^\n]*")

_DESTRUCTIVE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|DROP\s+SCHEMA|TRUNCATE)\b", re.IGNORECASE
)


def _statements() -> str:
    return _COMMENT_RE.sub("", SCHEMA_PATH.read_text(encoding="utf-8"))


def test_the_bootstrap_schema_executes_nothing_destructive():
    assert SCHEMA_PATH.exists(), SCHEMA_PATH
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
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "component_people_decisions" in text  # the operator is told about it…
    assert "component_people_decisions" not in _statements()  # …only in prose
