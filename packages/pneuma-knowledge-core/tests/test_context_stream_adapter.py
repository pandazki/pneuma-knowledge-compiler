"""First-party context_stream adapter: diarized role → owner/other block rendering.

The whole Layer-1 intervention is that a diarized `role` renders in the compile skill's
vocabulary (Owner / ParticipantN), so the compiler sees who owns each turn instead of guessing
opaque `self/3` / `others/2` codes. These assert that rendering + graceful fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn, RawSource
from pneuma_knowledge_core.ingest.adapters import (
    ContextStreamAdapter,
    PlainConversationAdapter,
    PlainConversationInput,
)


def _raw(origin="context_stream") -> RawSource:
    return RawSource(
        source_id=SourceId("s1"),
        user_id=UserId("u1"),
        kind="conversation",
        origin=origin,
        title="meeting",
        mime="application/vnd.pneuma.context-stream+json",
        checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )


def _norm(turns):
    return ContextStreamAdapter().normalize(PlainConversationInput(raw=_raw(), turns=turns))


def test_owner_and_others_render_in_skill_vocabulary():
    turns = [
        ConversationTurn(speaker="self/3", text="我明天完成许可证扫描", role="owner", speaker_id="self/3"),
        ConversationTurn(speaker="others/2", text="生产构建已经通过", role="other", speaker_id="others/2"),
        ConversationTurn(speaker="others/1", text="README 还缺恢复路径", role="other", speaker_id="others/1"),
        ConversationTurn(speaker="others/2", text="对，构建结果已记录", role="other", speaker_id="others/2"),
    ]
    blocks = _norm(turns).blocks
    assert blocks[0].text == "Owner: 我明天完成许可证扫描"
    # distinct others get a stable ParticipantN in first-appearance order, with the raw channel alias
    assert blocks[1].text == "Participant1 (others/2): 生产构建已经通过"
    assert blocks[2].text == "Participant2 (others/1): README 还缺恢复路径"
    # same speaker_id reuses its label across the transcript (identity continuity)
    assert blocks[3].text == "Participant1 (others/2): 对，构建结果已记录"


def test_unknown_role_falls_back_to_raw_speaker():
    # A partially/un-diarized transcript must not fabricate a owner/other label.
    turns = [
        ConversationTurn(speaker="审阅 agent", text="hi", role="unknown"),
        ConversationTurn(speaker="self/1", text="ok", role="owner", speaker_id="self/1"),
    ]
    blocks = _norm(turns).blocks
    assert blocks[0].text == "审阅 agent: hi"
    assert blocks[1].text == "Owner: ok"


def test_multiple_self_channels_all_collapse_to_owner():
    # self/1 and self/3 are the same owner (diarization sub-channels), never two people.
    turns = [
        ConversationTurn(speaker="self/1", text="a", role="owner", speaker_id="self/1"),
        ConversationTurn(speaker="self/3", text="b", role="owner", speaker_id="self/3"),
    ]
    blocks = _norm(turns).blocks
    assert blocks[0].text == "Owner: a"
    assert blocks[1].text == "Owner: b"


def test_date_sections_match_plain_adapter():
    # Sectioning is unchanged from the plain adapter — only the block text differs.
    turns = [
        ConversationTurn(speaker="self/1", text="a", role="owner", at=datetime(2026, 6, 30, 9, tzinfo=timezone.utc)),
        ConversationTurn(speaker="others/1", text="b", role="other", speaker_id="others/1", at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc)),
    ]
    conv = _norm(turns)
    plain = PlainConversationAdapter().normalize(PlainConversationInput(raw=_raw("upload"), turns=turns))
    assert [s.model_dump() for s in conv.structure.sections] == [
        s.model_dump() for s in plain.structure.sections
    ]
    assert len(conv.structure.sections) == 2  # two calendar dates
