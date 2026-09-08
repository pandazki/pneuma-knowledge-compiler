"""Source navigation must not mistake overlapping addresses for complete reading."""

from dataclasses import replace
from datetime import datetime

import pytest

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.recall.assembly import Passage, expand_and_merge
from pneuma_knowledge_core.recall.fast import (
    EpisodeSummary,
    EvidenceSelection,
    RetrievedClaim,
    StructuredRecallAnswer,
    expand_claim_provenance,
    expand_episode_provenance,
)
from pneuma_knowledge_core.recall.rag import RecallHit

from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings
from test_quality_context_selection import StructuredModel

UID = UserId("source-following-user")
SID = SourceId("release-notes")
TEXTS = [
    "The valve passed the pressure test.",
    "Approval applies only to the indoor prototype.",
    "Outdoor use still requires a corrosion assessment.",
    "The next review is scheduled for the following quarter.",
]


class Content:
    def __init__(self, *, omitted=()):
        self.calls = []
        self.source = NormalizedSource.model_validate({
            "raw": {
                "source_id": SID, "user_id": UID, "kind": "im", "origin": "mock",
                "title": "Prototype review", "mime": "application/json",
                "checksum": "synthetic", "created_at": "2026-01-14T00:00:00Z",
            },
            "blocks": [{"index": i, "text": t} for i, t in enumerate(TEXTS) if i not in omitted],
            "structure": {"sections": []},
        })

    async def get(self, user_id, source_id):
        assert user_id == UID
        assert source_id == SID
        self.calls.append((user_id, source_id))
        return self.source


def window(start, end, **changes):
    return Passage(
        source_id=changes.pop("source_id", SID), block_start=start, block_end=end,
        text=changes.pop("text", "\n".join(TEXTS[start:end + 1])), paths=("raw",),
        score=1.0, **changes,
    )


def claim(start=0, end=2, *, anchor="ab12"):
    return RetrievedClaim(
        anchor=AnchorId(anchor), document_path="subjects/valve.md", section_path=(),
        text="The indoor prototype passed; outdoor approval is pending.",
        citations=(Citation(source_id=SID, block_start=start, block_end=end),), score=1.0,
    )


async def follow(kind, content, existing=(), start=0, end=2, **kwargs):
    if kind == "claim":
        return await expand_claim_provenance(UID, [claim(start, end)], content=content, existing=existing, **kwargs)
    return await expand_episode_provenance(UID, [EpisodeSummary(
        source_id=SID, block_start=start, block_end=end,
        text="Prototype approval and pending review", score=1.0,
    )], content=content, existing=existing, **kwargs)


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("existing", [
    [window(0, 0)],
    [window(2, 3)],
    [window(0, 0), window(2, 2)],
    [window(0, 2, source_id=SourceId("another-tenant-source"))],
    [window(0, 2, text=TEXTS[0] + "…")],
    [window(0, 2, text="Derived summary: approval granted.")],
])
async def test_unseen_qualifier_is_fetched_despite_overlapping_addresses(kind, existing):
    content = Content()
    passages = await follow(kind, content, existing)
    assert len(passages) == 1
    assert passages[0].text == "\n".join(TEXTS[:3])
    assert (passages[0].block_start, passages[0].block_end) == (0, 2)
    assert content.calls == [(UID, SID)]


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("existing", [
    [window(0, 2)], [window(0, 3)],
    [window(0, 0), window(1, 2)],
    [window(0, 1), window(1, 3)],
    [window(2, 2), window(0, 1)],
])
async def test_fully_read_contiguous_coverage_does_not_duplicate_passages(kind, existing):
    assert await follow(kind, Content(), existing) == []


@pytest.mark.parametrize("kind", ["claim", "episode"])
async def test_native_assembly_truncation_does_not_discharge_source_reading(kind):
    content = Content()
    hit = RecallHit(source_id=SID, block_start=0, block_end=2,
                    text="\n".join(TEXTS[:3]), paths=("vector",), score=1.0)
    windows = await expand_and_merge(
        [hit], user_id=UID, content=content, forward_blocks=0,
        max_passage_chars=len(TEXTS[0]),
    )
    assert windows[0].block_end == 2
    assert TEXTS[1] not in windows[0].text
    passages = await follow(kind, content, windows)
    assert TEXTS[1] in passages[0].text


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("start,end,omitted", [(0, 5, ()), (0, 2, (1,)), (4, 4, ())])
async def test_invalid_or_gapped_source_span_cannot_be_silently_clamped(kind, start, end, omitted):
    with pytest.raises(ValueError, match="complete L0 interval"):
        await follow(kind, Content(omitted=omitted), start=start, end=end)


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("report_invalid", [False, True])
async def test_custom_store_cannot_supply_ambiguous_block_indices(kind, report_invalid):
    content = Content()
    content.source.blocks.append(content.source.blocks[0].model_copy(update={"text": "Contradiction"}))
    with pytest.raises(ValueError, match="duplicate block indices"):
        await follow(kind, content, invalid_citations=[] if report_invalid else None)


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("field,value", [("user_id", "another-user"), ("source_id", "another-source")])
@pytest.mark.parametrize("report_invalid", [False, True])
async def test_custom_store_cannot_substitute_a_different_source_or_tenant(kind, field, value, report_invalid):
    content = Content()
    content.source.raw = content.source.raw.model_copy(update={field: value})
    with pytest.raises(ValueError, match="requested tenant/source"):
        await follow(kind, content, invalid_citations=[] if report_invalid else None)


async def test_claim_budget_counts_returned_passages_and_reuses_one_source_read():
    content = Content()
    first = claim(0, 0)
    second = claim(0, 2, anchor="ab13")
    third = claim(3, 3, anchor="ab14")
    passages = await expand_claim_provenance(
        UID, [first, second, second, third], content=content,
        existing=[window(0, 0)], claim_cap=4, passage_cap=1,
    )
    assert [p.text for p in passages] == ["\n".join(TEXTS[:3])]
    assert len(content.calls) == 1


@pytest.mark.parametrize("kind", ["claim", "episode"])
async def test_disabled_navigation_does_not_read_sources(kind):
    content = Content()
    if kind == "claim":
        result = await expand_claim_provenance(UID, [claim()], content=content, passage_cap=0)
    else:
        result = await expand_episode_provenance(UID, [], content=content, episode_cap=0)
    assert result == []
    assert content.calls == []


@pytest.mark.parametrize("kind", ["claim", "episode"])
async def test_reported_bad_span_does_not_discard_valid_passages_or_stop_later_reads(kind):
    content = Content(omitted=(1,))
    invalid = []
    citations = [claim(0, 0), claim(0, 2), claim(2, 3)]
    if kind == "claim":
        # Even the next citation of the same claim must still be followed.
        claims = [replace(citations[0], citations=tuple(c.citations[0] for c in citations))]
        passages = await expand_claim_provenance(
            UID, claims, content=content, invalid_citations=invalid, passage_cap=2,
        )
    else:
        summaries = [EpisodeSummary(
            source_id=SID, block_start=c.citations[0].block_start,
            block_end=c.citations[0].block_end, text=c.text, score=1.0,
        ) for c in citations]
        passages = await expand_episode_provenance(
            UID, summaries, content=content, invalid_citations=invalid,
        )
    assert [(p.block_start, p.block_end, p.text) for p in passages] == [
        (0, 0, TEXTS[0]), (2, 3, "\n".join(TEXTS[2:])),
    ]
    assert invalid == [citations[1].citations[0]]
    assert content.calls == [(UID, SID)]


@pytest.mark.parametrize("kind", ["claim", "episode"])
@pytest.mark.parametrize("selector_failure", [False, True])
async def test_fast_select_skips_bad_evidence_and_answers_with_later_complete_source(
    monkeypatch, kind, selector_failure,
):
    from pneuma_knowledge_core.recall import fast as fast_module

    content = Content()
    bad = replace(claim(0, 9), text="Invalid historical assertion.")
    good = claim(anchor="ab13")
    rows = [] if kind == "episode" else [ClaimStub(
        c.anchor, c.document_path, c.text,
        citations=[citation.model_dump() for citation in c.citations],
    ) for c in (bad, good)]
    if kind == "episode":
        async def summaries(*args, **kwargs):
            return [EpisodeSummary(
                source_id=SID, block_start=c.citations[0].block_start,
                block_end=c.citations[0].block_end, text=c.text, score=1.0,
            ) for c in (bad, good)]
        monkeypatch.setattr(fast_module, "build_episode_summaries", summaries)
    selector = StructuredModel(
        parsed=EvidenceSelection(**{"claims" if kind == "claim" else "episode_summaries": [0, 1]}),
        error=TimeoutError() if selector_failure else None, seen=[],
    )
    answerer = StructuredModel(parsed=StructuredRecallAnswer(
        answer_kind="fact", answer="Outdoor approval is pending.", citations=["[cite: s01 ¶0-2]"],
    ), seen=[])
    result = await fast_module.fast_recall(
        UID, "Can the prototype be used outdoors?", as_of=datetime(2026, 1, 15),
        claim_lexical=FakeClaimIndex(rows), claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(), model=selector, answer_model=answerer,
        content=content, fast_paths=(), evidence_strategy="select", answer_format="structured",
    )

    assert result.answer_text == "Outdoor approval is pending."
    assert result.answer_format_degraded is None
    reason = "provenance:invalid_span"
    assert result.evidence_selection_degraded == ("timeout;" if selector_failure else "") + reason
    stages = {stage.name: stage for stage in result.stages}
    assert stages["assemble"].status == "degraded"
    assert stages["assemble"].detail == reason
    assert stages["select"].detail == ("timeout" if selector_failure else None)
    kept = result.used_claims if kind == "claim" else result.used_episode_summaries
    assert [item.text for item in kept] == [good.text]
    assert len(result.used_windows) == 1
    assert result.used_windows[0].text == "\n".join(TEXTS[:3])
    human = answerer.seen[0][1].content
    assert TEXTS[1] in human and TEXTS[2] in human
    assert bad.text not in human and "¶0-9" not in human
