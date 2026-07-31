"""Snapshot-scoped answering: what core does when a question is pinned to a frozen snapshot.

Core's whole share of snapshot support is the ANSWERING face — the prompt has to state which
frozen version is open, and an L0 miss under a snapshot has to read as "not in this snapshot"
rather than as a broken fetch. The storage side (a frozen tenant) is the service's, and is
tested there.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import fast_recall, recall_human
from pneuma_knowledge_core.recall.scope import (
    SnapshotScope,
    out_of_scope_source,
    scope_declaration,
)
from langchain_core.messages import AIMessage

from test_deep_recall import FakeContent, _model, _tool_call
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings

_AS_OF = datetime(2026, 7, 20, 12, 0, 0)
_FROZEN = datetime(2026, 3, 1, 9, 30, 0, tzinfo=timezone.utc)
_USER = UserId("u-scope")
_SCOPE = SnapshotScope(label="before the reorg", created_at=_FROZEN)


def test_no_scope_renders_no_snapshot_section():
    # The HEAD case must be byte-identical to the pre-snapshot prompt: absence of a scope is
    # absence of a section, not an empty one.
    assert scope_declaration(None) is None
    human = recall_human("q", [], as_of=_AS_OF)
    assert "snapshot" not in human.lower()


def test_declaration_names_the_label_and_the_freeze_time():
    declaration = _SCOPE.declaration()
    assert "before the reorg" in declaration
    assert _FROZEN.isoformat() in declaration
    # And it is catalog prose, not a literal in the code — the whole point of the key.
    assert declaration == prompt(
        "recall.snapshot.declaration", snapshot=_SCOPE.moment()
    )


def test_declaration_survives_an_unknown_freeze_time():
    # A snapshot whose timestamp the caller could not read still gets a declaration: naming
    # the wrong moment would be worse, naming none is honest.
    undated = SnapshotScope(label="week-02")
    assert "week-02" in undated.declaration()


def test_snapshot_section_sits_above_the_glance_and_as_of_still_closes():
    # Assembly order matters: the snapshot governs the glance and both evidence faces, so it
    # must be read before them; `as_of` is a different fact and still closes the turn.
    human = recall_human(
        "q",
        [],
        as_of=_AS_OF,
        profile="Name: Owner",
        glance="# Knowledge base at a glance\n- `a.md`",
        snapshot=_SCOPE.declaration(),
    )
    assert human.index("before the reorg") < human.index("at a glance")
    assert human.index("Name: Owner") < human.index("before the reorg")
    assert f"as_of: {_AS_OF.isoformat()}" in human
    assert human.index("as_of:") > human.index("before the reorg")


async def test_fast_lane_carries_the_declaration_into_the_prompt():
    claim = ClaimStub("aaaa", "memory/a.md", "the pilot shipped")
    model = _model(AIMessage(content="it shipped"))
    answer = await fast_recall(
        _USER,
        "did the pilot ship?",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([claim]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        scope=_SCOPE,
    )
    assert answer.answer == "it shipped"
    human = model.seen[0][-1].content
    assert "before the reorg" in human
    assert _FROZEN.isoformat() in human


async def test_deep_opens_with_the_snapshot_declaration():
    claim = ClaimStub("aaaa", "memory/a.md", "the pilot shipped")
    model = _model(AIMessage(content="it shipped"))
    await deep_recall(
        _USER,
        "did the pilot ship?",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([claim]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=FakeContent(),
        scope=_SCOPE,
    )
    opening = model.seen[0][-1].content
    assert "before the reorg" in opening
    assert _FROZEN.isoformat() in opening


class _AbsentContent:
    """ContentStore whose fetch raises KeyError — a source the tenant does not hold."""

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        raise KeyError(source_id)

    async def get(self, user_id, source_id):  # noqa: ANN001
        raise KeyError(source_id)


async def test_fetch_miss_under_a_snapshot_is_reported_as_not_in_this_snapshot():
    # In a frozen tenant "no such source" IS "not part of this snapshot". Saying it in those
    # words is what stops the model from reading a transport failure and retrying.
    model = _model(
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "fetch_verbatim",
                    {"source_id": "src-later", "locator": {"blocks": [0, 1]}},
                    "t1",
                )
            ],
        ),
        AIMessage(content="that source is not in the snapshot"),
    )
    result = await deep_recall(
        _USER,
        "what does src-later say?",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=_AbsentContent(),
        scope=_SCOPE,
    )
    step = next(s for s in result.trail if s["tool"] == "fetch_verbatim")
    assert step["result"] == out_of_scope_source(_SCOPE, "src-later")
    assert "before the reorg" in step["result"]
    assert "src-later" in step["result"]


async def test_fetch_miss_without_a_snapshot_keeps_the_generic_failure_wording():
    # Zero behavior change off the snapshot path: a HEAD fetch miss still reads as a fetch
    # failure, because at HEAD it genuinely is one.
    model = _model(
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "fetch_verbatim",
                    {"source_id": "src-gone", "locator": {"blocks": [0, 1]}},
                    "t1",
                )
            ],
        ),
        AIMessage(content="could not fetch"),
    )
    result = await deep_recall(
        _USER,
        "what does src-gone say?",
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        content=_AbsentContent(),
    )
    step = next(s for s in result.trail if s["tool"] == "fetch_verbatim")
    assert "snapshot" not in step["result"].lower()
    assert step["result"] == prompt(
        "recall.deep.tool.fetch_verbatim_failed", error=step["error"]
    )
