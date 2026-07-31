"""Real provider ACLs and canonical-JSON mock adapter share one contract boundary."""

import json
import mailbox
import zipfile
from email.message import EmailMessage as StdEmailMessage
from pathlib import Path

from pneuma_knowledge_core.ingest.source_contracts import (
    DocumentLibrarySource,
    EmailSource,
    ImSource,
    MeetingSource,
)
from pneuma_knowledge_service.adapters.source_imports import (
    CanonicalJsonSourceAdapter,
    ObsidianVaultAdapter,
    Rfc822EmailAdapter,
    SlackExportAdapter,
    ZoomVttAdapter,
)


def test_canonical_json_mock_adapter_validates_official_contract():
    payload = {
        "schema": "pneuma.source.meeting/v1",
        "provider": "mock",
        "meeting_id": "m1",
        "title": "演示会议",
        "started_at": "2026-07-28T09:00:00+08:00",
        "participants": [{"participant_id": "p1", "display_name": "测试用户"}],
        "owner_participant_ids": ["p1"],
        "segments": [
            {
                "segment_id": "s1",
                "speaker_id": "p1",
                "started_at": "2026-07-28T09:00:01+08:00",
                "text": "开始。",
            }
        ],
    }
    source = CanonicalJsonSourceAdapter().load(json.dumps(payload, ensure_ascii=False))
    assert isinstance(source, MeetingSource)


def test_zoom_vtt_adapter_maps_speakers_and_offsets():
    metadata = {
        "id": "987654321",
        "topic": "Acme 客户发现会议",
        "start_time": "2026-07-28T09:00:00+08:00",
        "duration": 30,
        "timezone": "Asia/Shanghai",
        "participants": [
            {"id": "p1", "name": "测试用户", "email": "owner@example.test"},
            {"id": "p2", "name": "陈澄", "email": "client@example.com"},
        ],
    }
    vtt = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
测试用户: 我周四发方案。

2
00:00:05.000 --> 00:00:07.000
陈澄: 收到。
"""
    source = ZoomVttAdapter().load(
        metadata, vtt, owner_emails={"owner@example.test"}
    )
    assert isinstance(source, MeetingSource)
    assert source.provider == "zoom"
    assert source.owner_participant_ids == ["p1"]
    assert source.segments[1].speaker_id == "p2"
    assert source.segments[1].started_at.isoformat() == "2026-07-28T09:00:05+08:00"


def test_obsidian_adapter_preserves_hierarchy_metadata_and_ignores_config(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    (vault / "Clients").mkdir(parents=True)
    (vault / ".obsidian" / "plugins" / "x").mkdir(parents=True)
    (vault / "Clients" / "Acme.md").write_text(
        """---
status: active
tags:
  - client/acme
aliases: [Acme]
---
# Acme

关联 [[Projects/Pneuma|Pneuma 项目]]，见 ![[Assets/scope.png]]。
""",
        encoding="utf-8",
    )
    (vault / ".obsidian" / "plugins" / "x" / "main.js").write_text(
        "SECRET = true", encoding="utf-8"
    )
    (vault / ".hidden.md").write_text("hidden", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("must stay outside", encoding="utf-8")
    (vault / "linked-outside.md").symlink_to(outside)

    source = ObsidianVaultAdapter().load(vault, library_id="v1", title="工作库")
    assert isinstance(source, DocumentLibrarySource)
    assert [d.path for d in source.documents] == ["Clients/Acme.md"]
    note = source.documents[0]
    assert note.frontmatter["status"] == "active"
    assert note.tags == ["client/acme"]
    assert [(link.target, link.label, link.embedded) for link in note.links] == [
        ("Projects/Pneuma", "Pneuma 项目", False),
        ("Assets/scope.png", None, True),
    ]
    assert "status:" not in note.content


def test_slack_export_adapter_reads_channel_history(tmp_path: Path):
    export = tmp_path / "slack"
    (export / "client-acme").mkdir(parents=True)
    (export / "users.json").write_text(
        json.dumps(
            [
                {
                    "id": "U1",
                    "name": "lin",
                    "real_name": "测试用户",
                    "profile": {"email": "lin@example.dev"},
                },
                {
                    "id": "U2",
                    "name": "chen",
                    "real_name": "陈澄",
                    "profile": {"email": "client@example.com"},
                },
            ]
        ),
        encoding="utf-8",
    )
    (export / "channels.json").write_text(
        json.dumps(
            [
                {
                    "id": "C1",
                    "name": "client-acme",
                    "members": ["U1", "U2"],
                    "purpose": {"value": "客户协作"},
                }
            ]
        ),
        encoding="utf-8",
    )
    (export / "client-acme" / "2026-07-28.json").write_text(
        json.dumps(
            [
                {
                    "type": "message",
                    "user": "U2",
                    "ts": "1785207600.000001",
                    "text": "字段表发你了。",
                    "reactions": [{"name": "white_check_mark", "count": 1}],
                }
            ]
        ),
        encoding="utf-8",
    )

    source = SlackExportAdapter().load(export, owner_user_ids={"U1"})
    assert isinstance(source, ImSource)
    assert source.provider == "slack"
    assert source.conversations[0].messages[0].text == "字段表发你了。"
    assert source.conversations[0].messages[0].reactions[0].count == 1

    zip_path = tmp_path / "slack-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for item in export.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(export).as_posix())
    zipped = SlackExportAdapter().load(zip_path, owner_user_ids={"U1"})
    assert zipped.conversations[0].messages[0].message_id == "1785207600.000001"


def test_rfc822_adapter_groups_reply_chain_and_lists_attachments(tmp_path: Path):
    maildir = tmp_path / "mail"
    maildir.mkdir()
    (maildir / "001.eml").write_text(
        """From: =?utf-8?b?6ZmI5r6E?= <client@example.com>
To: =?utf-8?b?5p6X55+l6L+c?= <lin@example.dev>
Subject: =?utf-8?b?QWNtZSDor5Xngrnlm7Tlm7Q=?=
Date: Tue, 28 Jul 2026 12:00:00 +0800
Message-ID: <m1@example.com>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

确认先做三个项目组。
""",
        encoding="utf-8",
    )
    (maildir / "002.eml").write_text(
        """From: =?utf-8?b?5p6X55+l6L+c?= <lin@example.dev>
To: client@example.com
Subject: Re: =?utf-8?b?QWNtZSDor5Xngrnlm7Tlm7Q=?=
Date: Tue, 28 Jul 2026 13:00:00 +0800
Message-ID: <m2@example.com>
In-Reply-To: <m1@example.com>
References: <m1@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="B"

--B
Content-Type: text/plain; charset=utf-8

方案见附件。
--B
Content-Type: application/pdf
Content-Disposition: attachment; filename="proposal.pdf"
Content-Transfer-Encoding: base64

YWJj
--B--
""",
        encoding="utf-8",
    )

    source = Rfc822EmailAdapter().load(
        maildir, owner_addresses={"lin@example.dev"}
    )
    assert isinstance(source, EmailSource)
    assert source.provider == "rfc822"
    assert len(source.threads) == 1
    assert [m.message_id for m in source.threads[0].messages] == [
        "<m1@example.com>",
        "<m2@example.com>",
    ]
    assert source.threads[0].messages[1].attachments[0].filename == "proposal.pdf"
    assert source.threads[0].messages[1].attachments[0].size_bytes == 3


def test_rfc822_adapter_reads_mbox(tmp_path: Path):
    path = tmp_path / "archive.mbox"
    message = StdEmailMessage()
    message["From"] = "Lin <lin@example.dev>"
    message["To"] = "Client <client@example.com>"
    message["Subject"] = "Weekly summary"
    message["Date"] = "Tue, 28 Jul 2026 14:00:00 +0800"
    message["Message-ID"] = "<weekly@example.dev>"
    message.set_content("The pilot walkthrough is Wednesday at 15:00.")
    box = mailbox.mbox(path)
    try:
        box.add(message)
        box.flush()
    finally:
        box.close()

    source = Rfc822EmailAdapter().load(
        path, owner_addresses={"lin@example.dev"}
    )
    assert source.threads[0].messages[0].message_id == "<weekly@example.dev>"
    assert "Wednesday at 15:00" in source.threads[0].messages[0].text
