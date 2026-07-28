"""Canonical contracts normalize to replayable compiler evidence."""

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract


NOW = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


def _normalize(payload):
    return normalize_source_contract(
        parse_source_contract(payload), UserId("opc-lin"), imported_at=NOW
    )


def test_meeting_normalizes_one_block_per_segment_with_declared_owner():
    result = _normalize(
        {
            "schema": "pneuma.source.meeting/v1",
            "provider": "mock",
            "meeting_id": "m1",
            "title": "客户发现会议",
            "started_at": "2026-07-28T09:00:00+08:00",
            "owner_participant_ids": ["p1"],
            "participants": [
                {"participant_id": "p1", "display_name": "林知远"},
                {"participant_id": "p2", "display_name": "陈澄"},
            ],
            "segments": [
                {
                    "segment_id": "s1",
                    "speaker_id": "p1",
                    "started_at": "2026-07-28T09:00:01+08:00",
                    "text": "我周四发方案。",
                },
                {
                    "segment_id": "s2",
                    "speaker_id": "p2",
                    "started_at": "2026-07-28T09:00:05+08:00",
                    "text": "收到。",
                },
            ],
        }
    )
    assert len(result) == 1
    source = result[0]
    assert source.raw.kind == "meeting"
    assert source.raw.origin == "mock"
    assert [b.text for b in source.blocks] == ["本人（林知远）：我周四发方案。", "陈澄：收到。"]
    assert source.raw.meta["meeting_id"] == "m1"
    assert source.raw.meta["segment_ids"] == ["s1", "s2"]


def test_document_library_expands_to_one_citable_source_per_note():
    result = _normalize(
        {
            "schema": "pneuma.source.document-library/v1",
            "provider": "mock",
            "library_id": "v1",
            "title": "工作库",
            "documents": [
                {
                    "document_id": "d1",
                    "path": "Clients/Acme.md",
                    "title": "Acme",
                    "content": "# 决策\n\n先做三组。",
                    "frontmatter": {"status": "active"},
                    "tags": ["client"],
                    "links": [{"target": "Projects/Pneuma", "embedded": False}],
                },
                {
                    "document_id": "d2",
                    "path": "Projects/Pneuma.md",
                    "title": "Pneuma",
                    "content": "## 下一步\n\n周四交方案。",
                    "frontmatter": {},
                    "tags": [],
                    "links": [],
                },
            ],
        }
    )
    assert len(result) == 2
    assert {s.raw.kind for s in result} == {"document_library"}
    acme = next(s for s in result if s.raw.meta["path"] == "Clients/Acme.md")
    assert acme.raw.meta["frontmatter"] == {"status": "active"}
    assert acme.raw.meta["links"][0]["target"] == "Projects/Pneuma"
    assert acme.blocks[0].section_path == ["决策"]


def test_im_expands_by_conversation_and_preserves_message_ids():
    result = _normalize(
        {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "a1",
            "owner_user_ids": ["U1"],
            "users": [
                {"user_id": "U1", "display_name": "林知远"},
                {"user_id": "U2", "display_name": "陈澄"},
            ],
            "conversations": [
                {
                    "conversation_id": "C1",
                    "conversation_type": "dm",
                    "title": "陈澄",
                    "member_ids": ["U1", "U2"],
                    "messages": [
                        {
                            "message_id": "1.1",
                            "sender_id": "U2",
                            "sent_at": "2026-07-28T11:00:00+08:00",
                            "text": "字段表发你了。",
                        }
                    ],
                }
            ],
        }
    )
    assert len(result) == 1
    assert result[0].raw.kind == "im"
    assert result[0].blocks[0].text == "陈澄：字段表发你了。"
    assert result[0].raw.meta["message_ids"] == ["1.1"]


def test_email_expands_by_thread_and_marks_owner_side_without_inference():
    result = _normalize(
        {
            "schema": "pneuma.source.email/v1",
            "provider": "mock",
            "archive_id": "mail-1",
            "owner_addresses": ["lin@example.dev"],
            "threads": [
                {
                    "thread_id": "t1",
                    "subject": "试点",
                    "messages": [
                        {
                            "message_id": "<m1@example.com>",
                            "sent_at": "2026-07-28T12:00:00+08:00",
                            "from": {"address": "lin@example.dev", "display_name": "林知远"},
                            "to": [{"address": "client@example.com", "display_name": "陈澄"}],
                            "cc": [],
                            "subject": "试点",
                            "text": "方案见附件。",
                            "references": [],
                            "attachments": [
                                {
                                    "filename": "proposal.pdf",
                                    "content_type": "application/pdf",
                                    "size_bytes": 1024,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    assert len(result) == 1
    source = result[0]
    assert source.raw.kind == "email"
    assert source.blocks[0].text.startswith("本人（林知远 <lin@example.dev>）")
    assert "附件：proposal.pdf" in source.blocks[0].text
    assert source.raw.meta["message_ids"] == ["<m1@example.com>"]
