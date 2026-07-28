"""First-party source-type plugin: diarization typing + per-type compile guidance."""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.compile.runner import _render_task
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn, RawSource
from pneuma_knowledge_core.ingest.source_types import (
    ContextStreamSourceType,
    first_party_type,
    parse_diarized_turns,
)


def test_parse_diarized_turns_types_self_and_others():
    turns = [
        ConversationTurn(speaker="self/1", text="a"),
        ConversationTurn(speaker="others/2", text="b"),
        ConversationTurn(speaker="Alice", text="c"),  # not diarized → stays unknown
    ]
    out = parse_diarized_turns(turns)
    assert (out[0].role, out[0].speaker_id) == ("owner", "self/1")
    assert (out[1].role, out[1].speaker_id) == ("other", "others/2")
    assert out[2].role == "unknown"


def test_parse_preserves_caller_supplied_roles():
    # If the device already typed the role, we never re-derive it from the string.
    turns = [ConversationTurn(speaker="x", text="a", role="owner", speaker_id="x")]
    assert parse_diarized_turns(turns)[0].role == "owner"


def test_context_stream_type_bundles_all_concerns():
    ct = ContextStreamSourceType()
    assert ct.origin == "context_stream"
    assert first_party_type("context_stream") is not None
    assert first_party_type("upload") is None  # generic path has no plugin
    assert ct.indexing().chunk_strategy == "semantic"
    g = ct.compile_guidance()
    assert g is not None and "本人" in g.data_context and "context stream" in g.app_context
    # attribution is framed as provenance, not adjudication — the systemic fix for the
    # over-assertion the sharp discrimination framing caused on the strong agentic lane.
    assert "溯源" in g.app_context

    raw = RawSource(
        source_id=SourceId("s1"), user_id=UserId("u1"), kind="conversation",
        origin="context_stream", title="t", mime="application/vnd.pneuma.context-stream+json",
        checksum="c", created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    norm = ct.format(raw, ct.load([ConversationTurn(speaker="self/1", text="hi")]))
    assert norm.blocks[0].text == "本人：hi"


def test_render_task_injects_guidance_before_blocks():
    raw = RawSource(
        source_id=SourceId("s1"), user_id=UserId("u1"), kind="conversation",
        origin="context_stream", title="t", mime="text/plain", checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    ct = ContextStreamSourceType()
    norm = ct.format(raw, ct.load([ConversationTurn(speaker="self/1", text="hi")]))
    task = _render_task(
        [norm], [], source_guidance={"s1": ct.compile_guidance().render()}
    )
    # guidance appears, and before the block body it annotates
    assert "第一方数据说明" in task
    assert task.index("功能意图") < task.index("¶0 本人：hi")


def test_render_task_no_guidance_is_unchanged_generic_path():
    raw = RawSource(
        source_id=SourceId("s2"), user_id=UserId("u1"), kind="conversation",
        origin="upload", title="t", mime="text/plain", checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    from pneuma_knowledge_core.domain.source import NormalizedBlock, StructureMap

    norm = __import__("pneuma_knowledge_core.domain.source", fromlist=["NormalizedSource"]).NormalizedSource(
        raw=raw, blocks=[NormalizedBlock(index=0, text="x: hi")], structure=StructureMap()
    )
    task = _render_task([norm], [], source_guidance={})
    assert "第一方数据说明" not in task
