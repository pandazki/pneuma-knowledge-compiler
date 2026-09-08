"""Source meaning must survive the normalization → compiler boundary."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.compile.runner import _render_task
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.ingest.adapters import MarkdownDocumentAdapter, PlainDocumentInput
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.evidence_context import block_evidence_context
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from test_source_contracts import _email, _im, _meeting


def normalized(payload):
    return normalize_source_contract(
        parse_source_contract(payload), UserId("synthetic-context"),
        imported_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )[0]


def task(source):
    # Production assigns short source aliases: a checksum must not hide lost evidence.
    source = source.model_copy(update={
        "raw": source.raw.model_copy(update={"source_id": SourceId("s01")})
    })
    return _render_task([source], [])


@pytest.mark.parametrize("heading", ["Approved", "已批准"])
def test_heading_changes_meaning_without_changing_text_or_citation(heading):
    raw = normalized(_im()).raw.model_copy(update={"meta": {}, "kind": "document"})
    def document(title):
        return MarkdownDocumentAdapter().normalize(PlainDocumentInput(
            raw=raw, text=f"# {title}\n\nProject Atlas launch.\n"
        ))
    approved, rejected = document(heading), document("Rejected")
    assert approved.blocks[0].text == rejected.blocks[0].text
    assert task(approved) != task(rejected)
    assert heading in task(approved)
    assert "¶0 Project Atlas launch." in task(approved)


def threaded_payload():
    payload = _im()
    messages = payload["conversations"][0]["messages"]
    messages[:] = [
        {"message_id": f"m{i}", "sender_id": "U2", "sent_at": at,
         "text": text, "thread_id": thread}
        for i, (at, text, thread) in enumerate([
            ("2026-07-01T09:00:00Z", "Approve Atlas?", "atlas"),
            ("2026-07-01T09:01:00Z", "Approve Birch?", "birch"),
            ("2026-07-02T09:00:00Z", "Approved. Launch tomorrow.", "atlas"),
            ("2026-07-04T09:00:00Z", "Reporting period ends.", "atlas"),
        ])
    ]
    return payload


@pytest.mark.parametrize("field,new", [
    ("sent_at", "2026-07-03T09:00:00Z"), ("thread_id", "birch"),
])
def test_middle_message_time_and_thread_reach_compiler(field, new):
    payload = threaded_payload()
    changed = deepcopy(payload)
    changed["conversations"][0]["messages"][2][field] = new
    original, other = normalized(payload), normalized(changed)
    before = original.model_dump(mode="json")
    rendered = task(original)
    assert rendered != task(other)
    assert "2026-07-01 — 2026-07-04" in rendered
    assert "2026-07-02T09:00:00+00:00" in rendered
    assert '"thread_id": "atlas"' in rendered
    assert original.model_dump(mode="json") == before  # no L0/address mutation
    for block in original.blocks:
        assert f"¶{block.index} {block.text}" in rendered


def test_email_reply_and_cc_are_preserved_without_arbitrary_metadata():
    source = normalized(_email())
    row = source.raw.meta["messages"][0]
    row.update(in_reply_to="external-message", references=["earlier-message"],
               cc=[{"address": "ada@example.test", "display_name": "Ada",
                    "private_cache": "DO-NOT-PROMOTE"}], private_cache="DO-NOT-PROMOTE")
    source.raw.meta["metadata"] = {"instructions": "DO-NOT-PROMOTE"}
    rendered = task(source)
    assert "external-message" in rendered and "earlier-message" in rendered
    assert "ada@example.test" in rendered
    assert '"display_name": "Ada"' in rendered
    assert "DO-NOT-PROMOTE" not in rendered


def test_meeting_segment_clock_is_not_replaced_by_meeting_start():
    source = normalized(_meeting())
    context = block_evidence_context(source).blocks[0]
    assert context["started_at"] == "2026-07-28T09:00:04+08:00"
    assert context["ended_at"] == "2026-07-28T09:00:11+08:00"
    assert context["speaker_id"] == "u-client"
    assert context["started_at"] in task(source)


@pytest.mark.parametrize("damage", ["short", "long", "ids", "duplicate", "indices"])
def test_damaged_parallel_metadata_is_omitted_without_guessing_alignment(damage):
    source = normalized(threaded_payload())
    if damage == "short":
        source.raw.meta["messages"].pop()
    elif damage == "long":
        source.raw.meta["messages"].append(source.raw.meta["messages"][0])
    elif damage == "ids":
        source.raw.meta["message_ids"].reverse()
    elif damage == "duplicate":
        source.raw.meta["message_ids"][1] = source.raw.meta["message_ids"][0]
    else:
        source.blocks[0].index = 20
    context = block_evidence_context(source)
    assert context.misaligned and not context.blocks
    rendered = task(source)
    assert "could not be aligned" in rendered
    assert "Approved. Launch tomorrow." in rendered
    assert '"thread_id"' not in rendered


def test_unstructured_source_has_no_invented_context_and_sections_can_end():
    source = normalized(_im())
    source.raw.meta = {}
    source.blocks[0].section_path = []
    assert not block_evidence_context(source).blocks
    assert "Source context for" not in task(source)
    assert "Source section path" not in task(source)
    first = source.blocks[0].model_copy(update={"section_path": ["Scope"]})
    second = source.blocks[0].model_copy(update={"index": 1, "section_path": []})
    source.blocks = [first, second]
    rendered = task(source)
    assert "next section: []" in rendered
