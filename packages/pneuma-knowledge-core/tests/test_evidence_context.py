"""Mixed-scope recall retains lookup provenance and source clocks (issue #55).

All material is synthetic. Tests exercise the real lane, including selection, component
folding, assembly, citation aliasing and the evidence-only handoff.
"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pydantic import create_model

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap
from pneuma_knowledge_core.recall import fast
from pneuma_knowledge_core.recall.assembly import expand_and_merge
from pneuma_knowledge_core.recall.evidence_context import (
    enrich_evidence, evidence_time, retrieval_origin, share_retrieval_origins,
)
from pneuma_knowledge_core.recall.fast import RetrievedClaim, SelectedEvidence
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.rag import EpisodeSummarySignal, RecallHit

from test_fast_paths import _Model
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings

USER = UserId("synthetic-scope-owner")
WHEN = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)


def source(sid, day, texts, *, clocks=None):
    meta = {"occurred_on": day}
    if clocks is not None:
        meta["turns"] = [{"at": clock} for clock in clocks]
    return NormalizedSource(
        raw=RawSource(source_id=SourceId(sid), user_id=USER, kind="agent_session",
                      title="Synthetic work log", mime="text/plain", checksum="synthetic",
                      created_at=WHEN, meta=meta),
        blocks=[NormalizedBlock(index=i, text=text) for i, text in enumerate(texts)],
        structure=StructureMap(),
    )


class Content:
    def __init__(self, *sources):
        self.sources = {str(s.raw.source_id): s for s in sources}
        self.reads = []

    async def get(self, user_id, source_id):
        assert user_id == USER
        self.reads.append(str(source_id))
        return self.sources[str(source_id)]


def claim(anchor, sid, *, start=0, end=0, text="Synthetic project statement"):
    return RetrievedClaim(
        AnchorId(anchor), "projects/orion.md", ("progress",), text,
        (Citation(source_id=SourceId(sid), block_start=start, block_end=end),),
    )


def window(sid, start, end, text, *, origins=()):
    return RecallHit(SourceId(sid), start, end, text, ("lexical",), 1.0,
                     retrieval_origins=origins)


async def test_each_citation_keeps_its_own_date_and_unknown_never_means_ingest_time():
    old = source("old", "2026-07-30", ["Older Orion work"])
    new = source("new", "2026-09-20", ["New Orion work"])
    unknown = source("unknown", "", ["An undated note"])
    mixed = replace(claim("a001", "old"), citations=(
        *claim("a001", "old").citations, *claim("a002", "new").citations,
    ))
    rows = await enrich_evidence(
        [mixed, claim("a003", "unknown"), claim("a004", "missing")],
        user_id=USER, content=Content(old, new, unknown),
    )
    assert [t.occurred_on for t in rows[0].source_times] == ["2026-07-30", "2026-09-20"]
    rendered = fast.render_claims(rows)
    assert "source occurred_on=2026-07-30" in rendered
    assert "source occurred_on=2026-09-20" in rendered
    assert "source occurred_on=unknown" in rendered
    assert WHEN.isoformat() not in rendered
    assert rows[0].text == mixed.text and rows[0].citations == mixed.citations


def test_span_clocks_are_exact_utc_and_partial_or_misaligned_metadata_is_visible():
    ns = source("multi", "2026-07-30", ["July", "September", "Undated"], clocks=[
        "2026-07-30T12:00:00+08:00", "2026-09-20T12:00:00+08:00", None,
    ])
    dated = evidence_time(SourceId("multi"), 1, 2, ns)
    assert dated.occurred_on == "2026-07-30"
    assert dated.first == dated.last == "2026-09-20T04:00:00+00:00"
    assert dated.timed_blocks == 1
    ns.raw.meta["turns"] = [{"at": "2026-09-20T12:00:00Z"}]
    missing = evidence_time(SourceId("multi"), 1, 2, ns)
    assert missing.first == missing.last == "" and missing.timed_blocks == 0


async def test_source_metadata_cannot_cross_tenants():
    ns = source("other", "2026-09-20", ["Other tenant"])
    ns.raw.user_id = UserId("another-owner")
    with pytest.raises(ValueError, match="tenant/source"):
        await enrich_evidence([claim("a001", "other")], user_id=USER, content=Content(ns))


async def test_lookup_spans_do_not_expand_or_merge_into_a_different_scope():
    scoped = retrieval_origin("topic", "Exact project lookup", bounded=True, name="Orion")
    broad = retrieval_origin("source_search", "Relevance search", time_filter=None)
    ns = source("shared", "2026-09-20", ["Orion", "Unrelated neighbouring project", "Tail"])
    passages = await expand_and_merge([
        window("shared", 0, 0, "Orion", origins=(scoped,)),
        window("shared", 0, 1, "Orion\nUnrelated neighbouring project", origins=(broad,)),
    ], content=Content(ns), user_id=USER, forward_blocks=1)
    assert len(passages) == 2
    limited = next(p for p in passages if p.retrieval_origins == (scoped,))
    assert limited.block_end == 0 and limited.text == "Orion"
    assert limited.source_times[0].block_end == 0
    separated = await expand_and_merge([
        window("shared", 0, 0, "Orion", origins=(scoped,)),
        window("shared", 2, 2, "Tail", origins=(scoped,)),
    ], content=Content(ns), user_id=USER, merge_gap_blocks=10)
    assert [(p.block_start, p.block_end) for p in separated] == [(0, 0), (2, 2)]


def test_dedup_preserves_distinct_calls_of_one_route_and_never_labels_a_containing_span():
    first = retrieval_origin("topic", "Exact topic", bounded=True, name="Orion")
    second = retrieval_origin("topic", "Exact topic", bounded=True, name="Lyra")
    broad = retrieval_origin("source_search", "Relevance", time_filter=None)
    items = share_retrieval_origins([
        window("same", 0, 0, "shared", origins=(first,)),
        window("same", 0, 0, "shared", origins=(second,)),
        window("same", 0, 1, "larger", origins=(broad,)),
    ])
    assert items[0].retrieval_origins == items[1].retrieval_origins == (first, second)
    assert items[2].retrieval_origins == (broad,)


LOOKUPS = [
    ("timespan", {"since": "2026-09-20", "until": "2026-09-21"}, "Lookup by calendar day"),
    ("person", {"alias": "Riley"}, "Resolve an exact person alias"),
    ("topic", {"name": "Orion", "status": "active"}, "Lookup one active project"),
]


@pytest.mark.parametrize("strategy", ["ranked", "select", "all"])
@pytest.mark.parametrize("name,arguments,description", LOOKUPS)
async def test_every_strategy_retains_each_lookup_scope_and_dates(
    monkeypatch, strategy, name, arguments, description,
):
    old = source("old", "2026-07-30", ["Orion work recorded in July"])
    recent = source("new", "2026-09-20", [
        "Riley changed Orion today", "UNRELATED_NEIGHBOUR", "Orion testing today",
    ], clocks=["2026-09-20T12:00:00+08:00"] * 3)
    content = Content(old, recent)
    old_claim = claim("a001", "old", text="Orion had a July prototype")
    current_claim = claim("a002", "new", start=2, end=2, text="Orion testing progressed")
    old_window = replace(window("old", 0, 0, old.blocks[0].text),
                         episode_summaries=(EpisodeSummarySignal(SourceId("old"), 0, 0,
                                                               "Orion July episode"),))
    args_schema = create_model("LookupArgs", **{key: (str, ...) for key in arguments})

    class Lookup:
        cap = 12

        async def run(self, user_id, args, **kwargs):
            assert user_id == USER and args.model_dump() == arguments
            return PathResult(claims=(current_claim,), windows=(window("new", 0, 0, recent.blocks[0].text),))

    path = Lookup()
    path.name, path.description, path.args_schema = name, description, args_schema
    model = _Model(route_calls=[{"name": name, "args": arguments, "id": "route-1", "type": "tool_call"}])
    selector_contexts = []

    async def retrieve(*args, **kwargs):
        return [old_window]

    async def select(*args, **kwargs):
        assert WHEN.isoformat() in args[1]
        assert "subject_timezone: UTC" in args[1]
        selector_contexts.extend(fast.selection_candidate_texts(
            claims=kwargs["claims"], episode_summaries=kwargs["episode_summaries"],
            windows=kwargs["windows"], components=kwargs["components"],
        ))
        return SelectedEvidence((0,), (0,), (0,), tuple(range(len(kwargs["components"])))), fast.zero_usage(), None

    monkeypatch.setattr(fast, "retrieve_windows", retrieve)
    monkeypatch.setattr(fast, "select_evidence", select)
    index = FakeClaimIndex([ClaimStub(str(old_claim.anchor), old_claim.document_path,
                                    old_claim.text, citations=[c.model_dump() for c in old_claim.citations])])
    result = await fast.fast_recall(
        USER, "What changed in Orion?", as_of=WHEN, model=model,
        claim_lexical=index, claim_vectors=None, lexical=object(), vectors=None,
        embeddings=FakeEmbeddings(), content=content, fast_paths=[path],
        evidence_strategy=strategy, evidence_only=True,
    )
    text = result.content
    assert isinstance(text, str)
    assert '<retrieval>' in text and '</retrieval>' in text
    assert '"time_filter": null' in text
    assert f"route: {name}" in text and f"method: {description}" in text
    for key, value in arguments.items():
        assert f'"{key}": "{value}"' in text
    assert "source occurred_on=2026-07-30" in text
    assert "source occurred_on=2026-09-20" in text
    assert "2026-09-20T04:00:00+00:00" in text
    assert "UNRELATED_NEIGHBOUR" not in text
    assert set(result.handles.values()) == {"old", "new"}
    assert content.reads.count("old") == content.reads.count("new") == 1
    # The source dates and lookup descriptions remain in the Human payload only (I5).
    assert result.system == fast.selector_contract()
    if strategy == "select":
        assert any(f"route: {name}" in item for item in selector_contexts)
        assert any("2026-07-30" in item for item in selector_contexts)


@pytest.mark.parametrize("strategy", ["ranked", "select", "all"])
@pytest.mark.parametrize("failed", [False, True])
async def test_empty_or_failed_lookup_scope_remains_visible_after_composition(monkeypatch, strategy, failed):
    args_schema = create_model("InventoryArgs", project=(str, ...))

    class Lookup:
        name = "inventory"
        description = "Enumerate inventory for one project"
        cap = 4

        async def run(self, user_id, args, **kwargs):
            if failed:
                raise RuntimeError("synthetic lookup failure")
            return PathResult()

    path = Lookup()
    path.args_schema = args_schema
    model = _Model(route_calls=[{
        "name": "inventory", "args": {"project": "Orion"}, "id": "inventory-1", "type": "tool_call",
    }])

    async def select(*args, **kwargs):
        return SelectedEvidence((), (), ()), fast.zero_usage(), None

    monkeypatch.setattr(fast, "select_evidence", select)
    result = await fast.fast_recall(
        USER, "What inventory does Orion have?", as_of=WHEN,
        claim_lexical=FakeClaimIndex([]), claim_vectors=None, embeddings=None,
        model=model, fast_paths=[path], evidence_strategy=strategy, evidence_only=True,
    )
    assert 'inventory(project="Orion")' in result.content
    assert "Enumerate inventory for one project" in result.content
    if failed:
        assert "lookup did not deliver: error" in result.content
    elif strategy != "ranked":
        assert "0 lookup items are shown in other evidence sections" in result.content


async def test_annotated_dates_add_no_unshown_citations_to_the_manifest():
    from pneuma_knowledge_core.domain.canonical import iter_canonical_citations

    row = replace(claim("a001", "first"), citations=(
        *claim("a001", "first").citations, *claim("a002", "second").citations,
    ))
    [dated] = await enrich_evidence([row], user_id=USER, content=Content(
        source("first", "2026-07-30", ["First note"]),
        source("second", "2026-09-20", ["Second note"]),
    ))
    rendered = fast.render_window_notes([dated])
    assert "2026-07-30" in rendered and "2026-09-20" in rendered
    assert not list(iter_canonical_citations(rendered))


async def test_full_page_dates_are_ephemeral_and_only_name_its_existing_citations():
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument, iter_canonical_citations

    doc = CanonicalDocument(doc_id="doc-orion", path="projects/orion.md", frontmatter={"type": "project"},
                            body="Orion progress. [cite: old ¶0-0]")
    before = doc.model_dump()
    [dated] = await enrich_evidence([fast.DatedDocument(doc)], user_id=USER,
                                   content=Content(source("old", "2026-07-30", ["Orion"])))
    rendered = fast.render_full_documents([dated])
    assert "2026-07-30" in rendered
    assert {(c.source_id, c.block_start, c.block_end) for c in iter_canonical_citations(rendered)} == {
        ("old", 0, 0),
    }
    assert doc.model_dump() == before


def test_component_budget_reallocates_metadata_space_instead_of_erasing_the_lookup():
    from pneuma_knowledge_core.recall.paths import ComponentEvidence, merge_component_evidence, render_component_evidence

    origin = retrieval_origin("inventory", "Structured lookup", bounded=True, project="Orion")
    windows = []
    for i in range(12):
        sid = SourceId(f"synthetic-inventory-{i}")
        ns = source(sid, "2026-09-20", ["Inventory entry " * 150],
                    clocks=["2026-09-20T12:00:00Z"])
        windows.append(replace(window(sid, 0, 0, ns.blocks[0].text, origins=(origin,)),
                               source_times=(evidence_time(sid, 0, 0, ns),)))
    row = ComponentEvidence(path="inventory", args={"project": "Orion"}, windows=tuple(windows),
                            cap=12, method="Enumerate project inventory")
    [kept], _ = merge_component_evidence([row], claims=[], windows=[], budget_chars=2000)
    assert 0 < len(kept.windows) < len(windows)
    assert kept.dropped == len(windows) - len(kept.windows)
    assert len(render_component_evidence([kept])) <= 2000
