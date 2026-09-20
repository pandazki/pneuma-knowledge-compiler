"""A coding-agent session says which project it ran in.

The transcript shows the work, never the subject it belongs to — and the sentence beside this
one has just told the compiler that action stubs, the only place a directory appears, are
activity rather than knowledge. So the project is stated from the source boundary's own
metadata, the same footing a component's source line stands on. Without it, two projects whose
definitions read alike are separated by a guess."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pneuma_knowledge_core.compile.runner import _render_task
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)

MARKER = "The agent ran in the project"


def _task(meta: dict[str, Any]) -> str:
    source = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="agent_session",
            title="Agent session 0001",
            mime="application/json",
            checksum="src-01",
            created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            meta=meta,
        ),
        blocks=[NormalizedBlock(index=0, text="Owner: rename the keep floor.")],
        structure=StructureMap(),
    )
    return _render_task([source], [])


def test_the_project_the_agent_ran_in_reaches_the_task():
    task = _task({"project": {"name": "aurora-notes", "path": "/Users/mei/Codes/aurora-notes"}})
    assert f"{MARKER} aurora-notes (/Users/mei/Codes/aurora-notes)." in task


def test_it_rides_beside_the_session_sentence_rather_than_replacing_it():
    task = _task({"project": {"name": "aurora-notes", "path": "/x"}})
    assert "coding-agent session" in task and MARKER in task


def test_a_boundary_that_recorded_no_project_says_nothing_extra():
    """Silence, not a placeholder: an unstated project must never become a subject."""
    task = _task({})
    assert MARKER not in task
    assert "None" not in task


def test_a_name_without_a_path_still_binds():
    task = _task({"project": {"name": "aurora-notes"}})
    assert f"{MARKER} aurora-notes (aurora-notes)." in task


def test_a_malformed_project_is_ignored_rather_than_rendered():
    for broken in ("aurora-notes", ["aurora-notes"], {"name": ""}, {"path": "/tmp/x"}):
        assert MARKER not in _task({"project": broken})


def test_a_source_that_is_not_a_session_is_untouched():
    source = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-02"),
            user_id=UserId("u-1"),
            kind="document",
            title="sync",
            mime="text/markdown",
            checksum="src-02",
            created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            meta={"project": {"name": "aurora-notes", "path": "/x"}},
        ),
        blocks=[NormalizedBlock(index=0, text="body")],
        structure=StructureMap(),
    )
    assert MARKER not in _render_task([source], [])
