"""「说说我这两天的工作」 — the question the personal edition could not answer.

The Owner asked their own library about the last two days and got an answer assembled from
whatever the lexical and vector faces happened to rank: no component was registered, so the
question about a PERIOD had no path that answers periods. This file is the mechanism check
behind enabling `time` for that edition, over the material a personal library is actually
made of — `agent-session/v1` sources, one per coding session.

Keyless and store-free: the routing turn is scripted (a real routing model resolves 这两天
against `as_of` — D4; a test that needed a provider to prove that would prove nothing about
this code), and the projection is the same in-memory stand-in the rest of the component's
tests use. What is under test is everything between: that an agent-session source carries a
per-block day at all, that registering `time` by name offers the `timespan` path, and that
the path returns the two recent days' blocks and claims and NOT the month-old session's.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pneuma_knowledge_core.components import reset_components
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.domain.time_context import time_context_for
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.recall.paths import (
    fast_paths_from_registry,
    merge_component_evidence,
    route_paths,
    run_paths,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import register_components

from test_time_component import _Store, _UserInfo

USER = UserId("lib-notes")
ZONE = "Asia/Shanghai"
#: "now" for the whole file: 2026-09-17, 21:00 in the owner's zone (13:00Z).
NOW = datetime(2026, 9, 17, 13, 0, tzinfo=timezone.utc)
TODAY = "2026-09-17"
YESTERDAY = "2026-09-16"
LAST_MONTH = "2026-08-18"


@pytest.fixture(autouse=True)
def _clean():
    reset_components()
    yield
    reset_components()


def _session(session_id: str, day: str, turns: list[tuple[str, str, str]]) -> NormalizedSource:
    """One `agent-session/v1` source: the Owner speaking and the agent answering, on `day`
    in the Owner's own zone. The contract's turn instants are what the projection keys on."""
    payload = {
        "schema": "pneuma.source.agent-session/v1",
        "provider": "claude-code",
        "session_id": session_id,
        "owner_id": "owner-1",
        "owner_name": "主人",
        "agent": {"name": "Claude Code"},
        "project": {"path": "/projects/pkc", "name": "pkc"},
        "started_at": f"{day}T09:00:00+08:00",
        "turns": [
            {
                "turn_id": f"{session_id}-t{index}",
                "role": "owner" if kind == "say" else "agent",
                "kind": kind,
                "at": f"{day}T{clock}:00+08:00",
                "text": text,
            }
            for index, (kind, clock, text) in enumerate(turns)
        ],
    }
    time = time_context_for(USER, _UserInfo(ZONE).profile, now_utc=NOW)
    return normalize_source_contract(
        parse_source_contract(payload), USER, imported_at=NOW, time=time
    )[0]


def _page(body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId("d-pkc"),
        path="memory/projects/pkc.md",
        frontmatter={"doc_id": "d-pkc", "type": "project", "slug": "pkc"},
        body=body,
    )


class _Canonical:
    def __init__(self, documents: list[CanonicalDocument]) -> None:
        self._documents = documents

    async def list(self, user_id, *, at=None) -> list[CanonicalDocument]:
        assert str(user_id) == str(USER)  # I1: no cross-user read path exists
        return list(self._documents)


async def _library() -> tuple[_Store, dict[str, NormalizedSource], CanonicalDocument]:
    """Three sessions — today, yesterday, a month ago — indexed through the registered
    component's own projection channel, exactly as an index job would drive it."""
    sessions = {
        TODAY: _session(
            "s-today",
            TODAY,
            [
                ("say", "09:10", "把归档记录的闸门补上。"),
                ("narrative", "09:30", "I added the gate check and its test."),
            ],
        ),
        YESTERDAY: _session(
            "s-yesterday",
            YESTERDAY,
            [
                ("say", "20:05", "先把个人版的组件接上。"),
                ("narrative", "20:20", "I wired the component registration."),
            ],
        ),
        LAST_MONTH: _session(
            "s-old",
            LAST_MONTH,
            [
                ("say", "11:00", "重构一下 embedding 的重试。"),
                ("narrative", "11:40", "I rewrote the retry loop."),
            ],
        ),
    }
    page = _page(
        "\n".join(
            [
                f"- 补上了归档记录的闸门。[cite: {sessions[TODAY].raw.source_id} ¶0-1] <!-- c:aa01 -->",
                f"- 个人版接上了索引组件。[cite: {sessions[YESTERDAY].raw.source_id} ¶0-1] <!-- c:bb02 -->",
                f"- 重写了 embedding 重试。[cite: {sessions[LAST_MONTH].raw.source_id} ¶0-1] <!-- c:cc03 -->",
            ]
        )
    )
    store = _Store()
    register_components(
        Settings(components="time"),
        store=store,
        canonical=_Canonical([page]),
        user_info=_UserInfo(ZONE),
    )
    [component] = _registered()
    for source in sessions.values():
        await store.add(USER, source)
        await component.on_source_indexed(str(USER), source)
    return store, sessions, page


def _registered():
    from pneuma_knowledge_core.components import registered_components

    return list(registered_components())


class _RoutingModel:
    """The routing turn, scripted. A real model reads `as_of` and the owner's zone off the
    Human turn and resolves the phrase itself (D4); this stands in for that one call with
    the days it would produce, so the test measures the path and not a provider."""

    def __init__(self, since: str, until: str) -> None:
        self.since, self.until = since, until
        self.seen: list[str] = []

    def bind_tools(self, tools, **_kwargs):
        self.tools = [tool.name for tool in tools]
        return self

    async def ainvoke(self, messages, config=None):
        from langchain_core.messages import AIMessage

        self.seen = [str(message.content) for message in messages]
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "timespan",
                    "args": {"since": self.since, "until": self.until},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )


# ------------------------------------------------------------------ the day is in the row


async def test_an_agent_session_carries_the_owners_day_on_every_block():
    """The projection keys on a per-block day, and an agent-session source has one: ingest
    sections each turn under the Owner's local day (`section_path[0]`) and keeps the turn's
    own instant in `meta["turns"][i]["at"]`. A session that ran past midnight is two days."""
    store, sessions, _page_ = await _library()

    rows = store.rows[(str(USER), str(sessions[YESTERDAY].raw.source_id))]
    assert [row["local_day"].isoformat() for row in rows] == [YESTERDAY, YESTERDAY]
    assert [row["kind"] for row in rows] == ["agent_session", "agent_session"]
    # the clock is the turn's own, normalized to UTC (20:05+08:00 → 12:05Z)
    assert rows[0]["instant_utc"] == datetime(2026, 9, 16, 12, 5, tzinfo=timezone.utc)
    assert rows[0]["zone"] == ZONE and rows[0]["zone_source"] == "profile"


# --------------------------------------------------------------- the question, end to end


@pytest.mark.parametrize("question", ["说说我这两天的工作", "what did I work on these two days"])
async def test_a_two_day_question_reaches_the_two_recent_sessions_and_not_the_old_one(question):
    """The Owner's own question, through the seam that was missing: `time` registered by
    name offers `timespan`, the routing turn resolves the phrase into two ISO days, and the
    path returns those days' blocks and the claims cited from them — the month-old session
    is not in the answer at all."""
    _store, sessions, _page_ = await _library()

    paths = fast_paths_from_registry(str(USER))
    assert [path.name for path in paths] == ["timespan"]

    model = _RoutingModel(YESTERDAY, TODAY)
    chosen, _usage, degraded, rejected = await route_paths(
        model, question, paths, as_of=NOW, zone=ZONE
    )
    assert degraded is None and rejected == []
    assert [(path.name, args.model_dump()) for path, args in chosen] == [
        ("timespan", {"since": YESTERDAY, "until": TODAY})
    ]
    # what the routing turn was told: the two volatile facts a relative phrase needs.
    assert NOW.isoformat() in model.seen[1] and ZONE in model.seen[1]

    [evidence] = await run_paths(
        str(USER), chosen, question=question, documents=None, as_of=NOW
    )
    assert evidence.degraded is None

    recent = {str(sessions[TODAY].raw.source_id), str(sessions[YESTERDAY].raw.source_id)}
    old = str(sessions[LAST_MONTH].raw.source_id)
    assert {str(window.source_id) for window in evidence.windows} == recent
    assert all(window.paths == ("time",) for window in evidence.windows)
    # each day's whole run of blocks, addressed as an ordinary source span (I4)
    assert {(window.block_start, window.block_end) for window in evidence.windows} == {(0, 1)}
    # the two days are labelled and ordered by day: yesterday, then today
    assert [window.text.split(" ·")[0] for window in evidence.windows] == [
        f"{YESTERDAY} (Wed, yesterday) 20:05–20:20 {ZONE}",
        f"{TODAY} (Thu, today) 09:10–09:30 {ZONE}",
    ]
    assert "先把个人版的组件接上。" in evidence.windows[0].text

    anchors = [str(claim.anchor) for claim in evidence.claims]
    assert anchors == ["aa01", "bb02"]  # the old session's c:cc03 is not reachable from here
    assert all(
        old not in str(citation.source_id)
        for claim in evidence.claims
        for citation in claim.citations
    )

    # and the merge spends nothing: two days is well inside the path's cap, and each
    # claim's citation span lies INSIDE the day window that already carries it verbatim, so
    # the claim is folded into the window rather than printed a second time.
    [merged], _hidden = merge_component_evidence([evidence], claims=[], windows=[])
    assert merged.dropped == 0 and len(merged.windows) == 2
    assert merged.claims == () and merged.covered_by_windows == 2


async def test_without_the_component_registered_the_question_has_no_path_at_all():
    """The state the personal edition was in: `components` empty, so the lane offers no
    path, spends no routing call, and a date-scoped question is answered by ranking alone."""
    store = _Store()
    assert register_components(Settings(components=""), store=store, canonical=None) == []
    assert fast_paths_from_registry(str(USER)) == []

    chosen, _usage, degraded, rejected = await route_paths(
        _RoutingModel(YESTERDAY, TODAY), "说说我这两天的工作", [], as_of=NOW, zone=ZONE
    )
    assert (chosen, degraded, rejected) == ([], None, [])


async def test_the_projection_is_rebuildable_from_l0_alone():
    """I7/I2: enabling the component on a library that already holds sources is a REBUILD,
    not a re-import — `rebuild` drops this tenant's rows and re-derives every one of them
    from L0, which is what makes enabling it on an existing library answerable."""
    store, sessions, _page_ = await _library()
    [component] = _registered()
    before = {key: list(rows) for key, rows in store.rows.items()}

    await store.delete_time_blocks(USER)
    assert not store.rows
    await component.rebuild(str(USER))

    assert store.rows == before
    assert len(store.rows) == len(sessions)
