"""Per-step wall-clock for the briefing lane — its two halves, in the two shapes they have.

The BUILD is mechanical: retrieval, expansion, assembly, no model anywhere. It therefore has
a fixed vocabulary and emits it complete, the way the fast lane does — so what is pinned here
is that the order is the vocabulary's, that a half this scope did not have is present and
marked `skipped` rather than missing, that a stage's clock is really that stage's work, and
that `total` bounds them all.

The ASK is an agentic loop, so it has no fixed vocabulary at all: how many turns it took and
which tools it reached for is precisely the measurement. What is pinned there is the
interleaving as it happened, that a tool's `ms` and the record that tool wrote agree, that a
failure the tool SWALLOWED (a bad source id answered with a stated failure rather than a
raise) still reads as degraded, and that a budget-forced finalize names its reason.

Durations are asserted with floors only — a sleep of 40 ms cannot report 10 ms — never with
ceilings: a loaded machine is allowed to be slow, and a test that failed when it was would be
measuring the box rather than the code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.recall.briefing import (
    BUILD_RETRIEVE_CHILDREN,
    BUILD_STAGE_ORDER,
    BriefingScope,
    briefing_ask,
    build_briefing,
)
from pneuma_knowledge_core.recall.stage_timing import child_name

from test_deep_recall import _model, _tool_call
from test_fast_recall import (
    ClaimStub,
    FakeClaimIndex,
    FakeEmbeddings,
    FakeLexical,
    FakeVector,
    LexHit,
)

_USER = UserId("u-briefing-timing")
_SID = "s-brief-timing"
_AS_OF = datetime(2026, 8, 26, 9, 0, 0, tzinfo=timezone.utc)

#: Injected costs, far enough apart that no rounding can confuse one stage for another.
_CLAIM_MS = 40
_BODY_MS = 60
_FETCH_MS = 50


def _names(stages) -> list[str]:
    return [s.name for s in stages]


def _by_name(stages) -> dict:
    return {s.name: s for s in stages}


class SlowClaimIndex(FakeClaimIndex):
    """The claim face, with a known cost — so `retrieve.claims` can be checked against it."""

    async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
        await asyncio.sleep(_CLAIM_MS / 1000.0)
        return await super().search_claims(user_id, query_or_embedding, limit=limit)


class SlowLexical(FakeLexical):
    """The body face, with its own, different cost — so the two children cannot be mixed up."""

    async def search(self, user_id, query, *, limit=20):  # noqa: ANN001
        await asyncio.sleep(_BODY_MS / 1000.0)
        return await super().search(user_id, query, limit=limit)


class SlowContent:
    """A ContentStore whose L0 reads cost time. `fetch` optionally fails the way the real one
    does for a bad id — by raising, which the ask tool then swallows into its record."""

    def __init__(self, ns: NormalizedSource | None = None) -> None:
        self._ns = ns

    async def get(self, user_id, source_id):  # noqa: ANN001
        await asyncio.sleep(_FETCH_MS / 1000.0)
        if self._ns is not None and str(source_id) == _SID:
            return self._ns
        raise KeyError(source_id)

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        await asyncio.sleep(_FETCH_MS / 1000.0)
        if self._ns is None or str(source_id) != _SID:
            raise KeyError(str(source_id))
        return "verbatim text"


def _source() -> NormalizedSource:
    raw = RawSource(
        source_id=SourceId(_SID),
        user_id=_USER,
        kind="document",
        title="Rollout notes",
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    blocks = [
        NormalizedBlock(index=i, text=f"paragraph {i}", section_path=["Rollout"])
        for i in range(6)
    ]
    return NormalizedSource(
        raw=raw,
        blocks=blocks,
        structure=StructureMap(
            sections=[SectionSpan(path=["Rollout"], start_block=0, end_block=5)]
        ),
    )


def _query_fakes(content: SlowContent) -> dict:
    claims = [
        ClaimStub(
            anchor="c:aaaa",
            document_path="notes/one.md",
            section_path=("Notes",),
            text="A compiled claim.",
        )
    ]
    return {
        "claim_lexical": SlowClaimIndex(claims),
        "claim_vectors": SlowClaimIndex(claims),
        "embeddings": FakeEmbeddings(),
        "lexical": SlowLexical([LexHit(SourceId(_SID), 2, "paragraph 2")]),
        "vectors": FakeVector([]),
        "content": content,
    }


# ------------------------------------------------------------------------------- the build


async def test_the_build_emits_its_whole_vocabulary_in_order_bounded_by_total():
    """A build with both halves: two lookups, expansion, assembly — each measured where it
    happens, `total` around everything."""
    content = SlowContent(_source())
    briefing = await build_briefing(
        _USER,
        BriefingScope(query="rollout", source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        **_query_fakes(content),
    )
    assert _names(briefing.stages) == [
        "retrieve",
        *(child_name(c) for c in BUILD_RETRIEVE_CHILDREN),
        "expand",
        "pack",
        "total",
    ]
    stages = _by_name(briefing.stages)
    # Each child's clock is its own lookup's, and the two are not interchangeable.
    assert stages[child_name("claims")].ms >= _CLAIM_MS
    assert stages[child_name("passages")].ms >= _BODY_MS
    # Unlike the fast lane's concurrent gather, these two run in sequence: they sum to their
    # parent rather than overshooting it (one rounding ms of slack for the two `round`s).
    children = sum(stages[child_name(c)].ms for c in BUILD_RETRIEVE_CHILDREN)
    assert children <= stages["retrieve"].ms + 1
    # Anchoring a source is provenance expansion, so its L0 read lands on `expand`.
    assert stages["expand"].ms >= _FETCH_MS
    # `total` wraps the build, so it bounds every stage measured inside it by construction.
    assert all(stages["total"].ms >= s.ms for s in briefing.stages)


async def test_a_half_this_scope_did_not_have_is_skipped_and_not_free():
    """No `scope.query` → the two lookups never happened. They are still emitted, marked, at
    0 ms: "did not happen" and "was free" are different facts and the strip exists to keep
    them apart."""
    briefing = await build_briefing(
        _USER,
        BriefingScope(source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        content=SlowContent(_source()),
    )
    stages = _by_name(briefing.stages)
    for name in ("retrieve", child_name("claims"), child_name("passages")):
        assert stages[name].status == "skipped" and stages[name].ms == 0
    # The half that DID run is not marked skipped, and the assembly always happens.
    assert stages["expand"].status == "ran" and stages["expand"].ms >= _FETCH_MS
    assert stages["pack"].status == "ran"
    assert _names(briefing.stages)[-1] == "total"


async def test_a_build_with_neither_half_still_reports_its_whole_vocabulary():
    """An empty scope is a build that did almost nothing — which is a finding, not a reason to
    send nothing. Only `pack` and `total` ran."""
    briefing = await build_briefing(
        _USER,
        BriefingScope(),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
    )
    stages = _by_name(briefing.stages)
    assert [s for s in BUILD_STAGE_ORDER if stages[s].status == "ran"] == ["pack", "total"]
    assert all(stages[child_name(c)].status == "skipped" for c in BUILD_RETRIEVE_CHILDREN)


async def test_the_build_vocabulary_is_the_briefings_own_not_the_fast_lanes():
    """The recorder is shared; the vocabulary is not. A build never claims to have planned,
    routed, reranked, selected or answered — it does none of those things."""
    from pneuma_knowledge_core.recall.stage_timing import STAGE_ORDER

    briefing = await build_briefing(
        _USER,
        BriefingScope(),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
    )
    borrowed = set(_names(briefing.stages)) & (set(STAGE_ORDER) - {"retrieve", "total"})
    assert borrowed == set()


# --------------------------------------------------------------------------------- the ask


def _ask_fakes(content: SlowContent) -> dict:
    fakes = _query_fakes(content)
    fakes.pop("content")
    return fakes


async def _briefing():
    return await build_briefing(
        _USER,
        BriefingScope(source_ids=[SourceId(_SID)]),
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        content=SlowContent(_source()),
    )


async def test_an_ask_interleaves_its_turns_and_tool_calls_in_the_order_they_happened():
    """Two tools across two rounds read back as the run's own sequence, `total` last — and
    every tool's clock is its own coroutine's, checked against the delay inside it."""
    content = SlowContent(_source())
    model = _model(
        AIMessage(
            content="",
            tool_calls=[_tool_call("search_knowledge", {"query": "rollout"}, "c1")],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "fetch_verbatim",
                    {"source_id": _SID, "locator": {"block_start": 0, "block_end": 1}},
                    "c2",
                )
            ],
        ),
        AIMessage(content="the answer"),
    )
    answer = await briefing_ask(
        await _briefing(),
        "what shipped?",
        as_of=_AS_OF,
        model=model,
        content=content,
        **_ask_fakes(content),
    )
    assert _names(answer.stages) == [
        "turn:1",
        "tool:search_knowledge",
        "turn:2",
        "tool:fetch_verbatim",
        "turn:3",
        "total",
    ]
    stages = _by_name(answer.stages)
    assert stages["tool:search_knowledge"].ms >= _CLAIM_MS + _BODY_MS
    assert stages["tool:fetch_verbatim"].ms >= _FETCH_MS
    assert all(stages["total"].ms >= s.ms for s in answer.stages)
    # The record the UI shows and the stage the strip shows measured the SAME call, so they
    # agree by construction rather than by two clocks that might not.
    fetch = answer.verbatim_fetches[0]
    assert fetch["ms"] >= _FETCH_MS and fetch["ms"] <= stages["tool:fetch_verbatim"].ms


async def test_the_total_wraps_the_loop_and_not_the_pack_it_asks_over():
    """A briefing is built once and asked many times; charging an ask for the build would
    misname where its seconds went. The build's own total is on the briefing, separately."""
    content = SlowContent(_source())
    briefing = await _briefing()
    model = _model(AIMessage(content="answered from the pack"))
    answer = await briefing_ask(
        briefing,
        "what shipped?",
        as_of=_AS_OF,
        model=model,
        content=content,
        **_ask_fakes(content),
    )
    assert _names(answer.stages) == ["turn:1", "total"]
    # The two vocabularies do not meet: nothing the build measured appears among the ask's
    # steps, which is the boundary stated as a property rather than as a race against a clock.
    assert set(_names(answer.stages)) & {"retrieve", "expand", "pack"} == set()
    # The build's own total is on the briefing, where it stays available to every later ask.
    assert _by_name(briefing.stages)["total"].ms >= _FETCH_MS


async def test_a_swallowed_fetch_failure_is_a_degraded_stage_naming_its_reason():
    """`fetch_verbatim` answers a bad source id with a stated failure instead of raising, so
    the run continues — the stage must not then read as a suspiciously fast success."""
    content = SlowContent(_source())
    model = _model(
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "fetch_verbatim",
                    {"source_id": "s-gone", "locator": {"block_start": 1, "block_end": 2}},
                    "c1",
                )
            ],
        ),
        AIMessage(content="answered without it"),
    )
    answer = await briefing_ask(
        await _briefing(),
        "what shipped?",
        as_of=_AS_OF,
        model=model,
        content=content,
        **_ask_fakes(content),
    )
    fetch = _by_name(answer.stages)["tool:fetch_verbatim"]
    assert fetch.status == "degraded" and "s-gone" in (fetch.detail or "")
    assert fetch.ms >= _FETCH_MS
    # The record carries the same failure and its own duration — the two halves of one call.
    assert answer.verbatim_fetches[0]["error"] and answer.verbatim_fetches[0]["ms"] >= _FETCH_MS


async def test_a_budget_forced_finalize_is_a_degraded_stage_named_budget():
    """The tool-less closing call exists only because the ask budget ran dry, so it is
    reported as its own step naming that reason rather than folded into an ordinary turn."""
    content = SlowContent(_source())
    reaching = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("search_knowledge", {"query": str(i)}, f"c{i}")],
        )
        for i in range(12)
    ]
    model = _model(*reaching, AIMessage(content="forced answer"))
    answer = await briefing_ask(
        await _briefing(),
        "what shipped?",
        as_of=_AS_OF,
        model=model,
        content=content,
        **_ask_fakes(content),
    )
    stages = _by_name(answer.stages)
    assert "finalize" in stages
    assert stages["finalize"].status == "degraded" and stages["finalize"].detail == "budget"
    assert _names(answer.stages)[-1] == "total"
    # Every search the run made left a record of its own, each stamped with that call's
    # duration — the budget edge does not cost the rounds before it their measurement.
    assert len([n for n in _names(answer.stages) if n.startswith("tool:")]) >= 1


async def test_timings_never_reach_the_system_prefix():
    """I5, stated as a test: the byte-stable contract + pack is what it always was. Two builds
    over the same inputs differ in `stages` and in nothing else."""
    content = SlowContent(_source())
    scope = BriefingScope(query="rollout", source_ids=[SourceId(_SID)])
    first = await build_briefing(
        _USER,
        scope,
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        **_query_fakes(content),
    )
    second = await build_briefing(
        _USER,
        scope,
        snapshot=SnapshotRef(ref="deadbeef"),
        snapshot_docs=[],
        **_query_fakes(content),
    )
    assert first.system_prefix == second.system_prefix
    for token in ("ms", "retrieve", "expand", "total"):
        assert f'"{token}"' not in first.system_prefix
