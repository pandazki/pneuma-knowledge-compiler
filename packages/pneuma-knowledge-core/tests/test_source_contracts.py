"""Provider-neutral source contracts: invariant and identity tests."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from pneuma_knowledge_core.ingest.source_contracts import (
    DocumentLibrarySource,
    EmailSource,
    ImSource,
    MeetingSource,
    parse_source_contract,
)


def _meeting() -> dict:
    return {
        "schema": "pneuma.source.meeting/v1",
        "provider": "mock",
        "meeting_id": "mtg-1",
        "title": "客户发现会议",
        "started_at": "2026-07-28T09:00:00+08:00",
        "ended_at": "2026-07-28T09:30:00+08:00",
        "timezone": "Asia/Shanghai",
        "owner_participant_ids": ["u-owner"],
        "participants": [
            {"participant_id": "u-owner", "display_name": "测试用户"},
            {"participant_id": "u-client", "display_name": "陈澄"},
        ],
        "agenda": ["确认试点范围"],
        "segments": [
            {
                "segment_id": "seg-1",
                "speaker_id": "u-client",
                "started_at": "2026-07-28T09:00:04+08:00",
                "ended_at": "2026-07-28T09:00:11+08:00",
                "text": "先覆盖华东区的三个项目组。",
            }
        ],
        "metadata": {},
    }


def _library() -> dict:
    return {
        "schema": "pneuma.source.document-library/v1",
        "provider": "mock",
        "library_id": "vault-1",
        "title": "Lin 的工作库",
        "documents": [
            {
                "document_id": "note-1",
                "path": "Clients/Acme/试点.md",
                "title": "Acme 试点",
                "content": "# 决策\n\n先做三个项目组。",
                "frontmatter": {"status": "active"},
                "tags": ["client/acme"],
                "links": [{"target": "Projects/知识编译器", "embedded": False}],
                "modified_at": "2026-07-28T10:00:00+08:00",
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _im() -> dict:
    return {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": "slack-1",
        "owner_user_ids": ["U1"],
        "users": [
            {"user_id": "U1", "display_name": "测试用户"},
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
                        "message_id": "1722132000.000001",
                        "sender_id": "U2",
                        "sent_at": "2026-07-28T11:00:00+08:00",
                        "text": "周四前给你字段清单。",
                        "thread_id": None,
                        "reactions": [],
                        "metadata": {},
                    }
                ],
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _email() -> dict:
    return {
        "schema": "pneuma.source.email/v1",
        "provider": "mock",
        "archive_id": "mail-1",
        "owner_addresses": ["lin@example.dev"],
        "threads": [
            {
                "thread_id": "<m1@example.com>",
                "subject": "Re: Acme 试点范围",
                "messages": [
                    {
                        "message_id": "<m1@example.com>",
                        "sent_at": "2026-07-28T12:00:00+08:00",
                        "from": {
                            "address": "client@example.com",
                            "display_name": "陈澄",
                        },
                        "to": [
                            {
                                "address": "owner@example.test",
                                "display_name": "测试用户",
                            }
                        ],
                        "cc": [],
                        "subject": "Re: Acme 试点范围",
                        "text": "确认先做三个项目组。",
                        "references": [],
                        "attachments": [],
                        "metadata": {},
                    }
                ],
                "metadata": {},
            }
        ],
        "metadata": {},
    }


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (_meeting(), MeetingSource),
        (_library(), DocumentLibrarySource),
        (_im(), ImSource),
        (_email(), EmailSource),
    ],
)
def test_discriminated_parser_accepts_all_official_contracts(payload, expected_type):
    parsed = parse_source_contract(payload)
    assert isinstance(parsed, expected_type)


def test_contracts_reject_unknown_top_level_fields():
    payload = _meeting()
    payload["provider_payload"] = {"secret": "must not leak"}
    with pytest.raises(ValidationError, match="provider_payload"):
        MeetingSource.model_validate(payload)


def test_meeting_rejects_unknown_speaker_and_naive_time():
    payload = _meeting()
    payload["segments"][0]["speaker_id"] = "ghost"
    with pytest.raises(ValidationError, match="speaker"):
        MeetingSource.model_validate(payload)

    payload = _meeting()
    payload["started_at"] = "2026-07-28T09:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        MeetingSource.model_validate(payload)


def test_meeting_rejects_duplicate_ids_and_end_before_start():
    payload = _meeting()
    payload["participants"].append(payload["participants"][0])
    with pytest.raises(ValidationError, match="participant"):
        MeetingSource.model_validate(payload)

    payload = _meeting()
    payload["ended_at"] = "2026-07-28T08:59:00+08:00"
    with pytest.raises(ValidationError, match="ended_at"):
        MeetingSource.model_validate(payload)


@pytest.mark.parametrize("path", ["../outside.md", "/tmp/outside.md", ".obsidian/app.json"])
def test_document_library_rejects_unsafe_or_hidden_paths(path):
    payload = _library()
    payload["documents"][0]["path"] = path
    with pytest.raises(ValidationError, match="path"):
        DocumentLibrarySource.model_validate(payload)


def test_document_library_rejects_duplicate_document_identity():
    payload = _library()
    payload["documents"].append(payload["documents"][0])
    with pytest.raises(ValidationError, match="document"):
        DocumentLibrarySource.model_validate(payload)


def test_im_rejects_unknown_owner_member_or_sender():
    for location, value in [
        (("owner_user_ids", 0), "UNKNOWN"),
        (("conversations", 0, "member_ids", 0), "UNKNOWN"),
        (("conversations", 0, "messages", 0, "sender_id"), "UNKNOWN"),
    ]:
        payload = _im()
        cursor = payload
        for key in location[:-1]:
            cursor = cursor[key]
        cursor[location[-1]] = value
        with pytest.raises(ValidationError, match="user|member|sender"):
            ImSource.model_validate(payload)


def test_email_normalizes_owner_addresses_and_requires_aware_dates():
    payload = _email()
    payload["owner_addresses"] = [" Lin@Example.DEV "]
    parsed = EmailSource.model_validate(payload)
    assert parsed.owner_addresses == ["lin@example.dev"]

    payload = _email()
    payload["threads"][0]["messages"][0]["sent_at"] = datetime(2026, 7, 28, 12, 0)
    with pytest.raises(ValidationError, match="timezone"):
        EmailSource.model_validate(payload)
