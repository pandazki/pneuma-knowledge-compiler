"""Normalize official source contracts into compiler evidence.

Bundles expand at natural citation boundaries: a meeting remains one source, while a
document library expands by note, IM by conversation and email by thread. Provider
payloads never cross this module; only canonical IDs and metadata do.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from ..domain.ids import SourceId, UserId
from ..domain.source import NormalizedBlock, NormalizedSource, RawSource
from .adapters import MarkdownDocumentAdapter, PlainDocumentInput
from .source_contracts import (
    DocumentLibrarySource,
    EmailAddress,
    EmailMessage,
    EmailSource,
    ImSource,
    MeetingSource,
    SourceContract,
)


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _identity(
    kind: str, provider: str, provider_id: str, evidence_digest: str
) -> SourceId:
    digest = hashlib.sha256(
        f"{kind}\0{provider}\0{provider_id}\0{evidence_digest}".encode("utf-8")
    ).hexdigest()
    return SourceId(digest[:32])


def _raw(
    *,
    user_id: UserId,
    kind: str,
    provider: str,
    provider_id: str,
    title: str,
    mime: str,
    created_at: datetime,
    evidence: object,
    meta: dict,
) -> RawSource:
    evidence_digest = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    return RawSource(
        source_id=_identity(kind, provider, provider_id, evidence_digest),
        user_id=user_id,
        kind=kind,
        source_class="workstream",
        origin=provider,
        title=title,
        mime=mime,
        checksum=evidence_digest,
        created_at=created_at,
        meta=meta,
    )


def _spans_from_paths(blocks: list[NormalizedBlock]):
    from ..domain.source import SectionSpan, StructureMap

    sections: list[SectionSpan] = []
    run_path: list[str] | None = None
    run_start = 0
    for index, block in enumerate(blocks):
        if run_path is None:
            run_path = block.section_path
            run_start = index
        elif block.section_path != run_path:
            sections.append(
                SectionSpan(
                    path=run_path, start_block=run_start, end_block=index - 1
                )
            )
            run_path = block.section_path
            run_start = index
    if run_path is not None:
        sections.append(
            SectionSpan(
                path=run_path, start_block=run_start, end_block=len(blocks) - 1
            )
        )
    return StructureMap(sections=sections)


def _meeting(source: MeetingSource, user_id: UserId) -> list[NormalizedSource]:
    participants = {item.participant_id: item for item in source.participants}
    owners = set(source.owner_participant_ids)
    ordered = sorted(source.segments, key=lambda item: (item.started_at, item.segment_id))
    blocks = []
    for index, segment in enumerate(ordered):
        participant = participants[segment.speaker_id]
        label = participant.display_name
        if participant.participant_id in owners:
            label = f"本人（{label}）"
        blocks.append(
            NormalizedBlock(
                index=index,
                text=f"{label}：{segment.text}",
                section_path=[segment.started_at.date().isoformat()],
            )
        )
    raw = _raw(
        user_id=user_id,
        kind="meeting",
        provider=source.provider,
        provider_id=source.meeting_id,
        title=source.title,
        mime="application/vnd.pneuma.meeting+json",
        created_at=source.started_at,
        evidence=source,
        meta={
            "contract_schema": source.contract_schema,
            "meeting_id": source.meeting_id,
            "owner_participant_ids": source.owner_participant_ids,
            "participants": [
                item.model_dump(mode="json") for item in source.participants
            ],
            "agenda": source.agenda,
            "segment_ids": [item.segment_id for item in ordered],
            "timezone": source.timezone,
            "metadata": source.metadata,
        },
    )
    return [
        NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
    ]


def _library(
    source: DocumentLibrarySource, user_id: UserId, imported_at: datetime
) -> list[NormalizedSource]:
    adapter = MarkdownDocumentAdapter()
    normalized: list[NormalizedSource] = []
    for document in sorted(source.documents, key=lambda item: item.path.casefold()):
        raw = _raw(
            user_id=user_id,
            kind="document_library",
            provider=source.provider,
            provider_id=f"{source.library_id}:{document.document_id}",
            title=document.title,
            mime="text/markdown",
            created_at=document.created_at or document.modified_at or imported_at,
            evidence=document,
            meta={
                "contract_schema": source.contract_schema,
                "library_id": source.library_id,
                "library_title": source.title,
                "document_id": document.document_id,
                "path": document.path,
                "frontmatter": document.frontmatter,
                "tags": document.tags,
                "links": [
                    item.model_dump(mode="json") for item in document.links
                ],
                "metadata": document.metadata,
            },
        )
        normalized.append(
            adapter.normalize(PlainDocumentInput(raw=raw, text=document.content))
        )
    return normalized


def _im(source: ImSource, user_id: UserId) -> list[NormalizedSource]:
    users = {item.user_id: item for item in source.users}
    owners = set(source.owner_user_ids)
    normalized: list[NormalizedSource] = []
    for conversation in sorted(
        source.conversations, key=lambda item: item.conversation_id
    ):
        messages = sorted(
            conversation.messages, key=lambda item: (item.sent_at, item.message_id)
        )
        blocks = []
        for index, message in enumerate(messages):
            sender = users[message.sender_id]
            label = sender.display_name
            if sender.user_id in owners:
                label = f"本人（{label}）"
            blocks.append(
                NormalizedBlock(
                    index=index,
                    text=f"{label}：{message.text}",
                    section_path=[message.sent_at.date().isoformat()],
                )
            )
        raw = _raw(
            user_id=user_id,
            kind="im",
            provider=source.provider,
            provider_id=f"{source.archive_id}:{conversation.conversation_id}",
            title=conversation.title,
            mime="application/vnd.pneuma.im+json",
            created_at=messages[0].sent_at,
            evidence=conversation,
            meta={
                "contract_schema": source.contract_schema,
                "archive_id": source.archive_id,
                "conversation_id": conversation.conversation_id,
                "conversation_type": conversation.conversation_type,
                "member_ids": conversation.member_ids,
                "owner_user_ids": source.owner_user_ids,
                "message_ids": [item.message_id for item in messages],
                "metadata": conversation.metadata,
            },
        )
        normalized.append(
            NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
        )
    return normalized


def _address_label(address: EmailAddress) -> str:
    return (
        f"{address.display_name} <{address.address}>"
        if address.display_name
        else address.address
    )


def _email_block(message: EmailMessage, owners: set[str]) -> str:
    sender = _address_label(message.from_)
    if message.from_.address in owners:
        sender = f"本人（{sender}）"
    recipients = ", ".join(_address_label(item) for item in message.to)
    lines = [
        f"{sender} → {recipients}",
        f"主题：{message.subject}",
        message.text,
    ]
    if message.attachments:
        lines.append(
            "附件："
            + "，".join(
                f"{item.filename} ({item.content_type}, {item.size_bytes} bytes)"
                for item in message.attachments
            )
        )
    return "\n".join(lines)


def _email(source: EmailSource, user_id: UserId) -> list[NormalizedSource]:
    owners = set(source.owner_addresses)
    normalized: list[NormalizedSource] = []
    for thread in sorted(source.threads, key=lambda item: item.thread_id):
        messages = sorted(
            thread.messages, key=lambda item: (item.sent_at, item.message_id)
        )
        blocks = [
            NormalizedBlock(
                index=index,
                text=_email_block(message, owners),
                section_path=[message.sent_at.date().isoformat()],
            )
            for index, message in enumerate(messages)
        ]
        raw = _raw(
            user_id=user_id,
            kind="email",
            provider=source.provider,
            provider_id=f"{source.archive_id}:{thread.thread_id}",
            title=thread.subject,
            mime="message/rfc822",
            created_at=messages[0].sent_at,
            evidence=thread,
            meta={
                "contract_schema": source.contract_schema,
                "archive_id": source.archive_id,
                "thread_id": thread.thread_id,
                "owner_addresses": source.owner_addresses,
                "message_ids": [item.message_id for item in messages],
                "metadata": thread.metadata,
            },
        )
        normalized.append(
            NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
        )
    return normalized


def normalize_source_contract(
    source: SourceContract, user_id: UserId, *, imported_at: datetime
) -> list[NormalizedSource]:
    """Expand one official contract into immutable compiler sources."""

    if isinstance(source, MeetingSource):
        return _meeting(source, user_id)
    if isinstance(source, DocumentLibrarySource):
        return _library(source, user_id, imported_at)
    if isinstance(source, ImSource):
        return _im(source, user_id)
    if isinstance(source, EmailSource):
        return _email(source, user_id)
    raise TypeError(f"unsupported source contract: {type(source)!r}")
