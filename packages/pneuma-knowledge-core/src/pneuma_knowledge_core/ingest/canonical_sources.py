"""Normalize official source contracts into compiler evidence.

Bundles expand at natural citation boundaries: a meeting remains one source, while a
document library expands by note, IM by conversation and email by thread. An owner dialogue
is one statement and stays one source. Provider payloads never cross this module; only
canonical IDs and metadata do.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Mapping

from ..domain.ids import SourceId, UserId
from ..domain.source import BlockImage, NormalizedBlock, NormalizedSource, RawSource
from ..domain.time_context import TimeContext
from ..prompts import prompt
from .adapters import MarkdownDocumentAdapter, PlainDocumentInput, stamp_occurred_on
from .source_contracts import (
    DocumentLibrarySource,
    EmailAddress,
    EmailMessage,
    EmailSource,
    ImSource,
    MeetingSource,
    OwnerDialogueSource,
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


def _local_day(at: datetime, time: TimeContext | None) -> str:
    """An instant → the calendar day it belongs to **in the subject's timezone**.

    Official contracts carry aware timestamps (often in the provider's own offset), so a
    bare `.date()` files a message under whichever offset the provider happened to send.
    The section a message lands in has to be the subject's day, since that is the unit they
    recall by. `time=None` keeps the timestamp's own offset (the historical behaviour).
    """
    return (time.local_date(at) if time is not None else at.date()).isoformat()


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


def _meeting(
    source: MeetingSource, user_id: UserId, time: TimeContext | None = None
) -> list[NormalizedSource]:
    participants = {item.participant_id: item for item in source.participants}
    owners = set(source.owner_participant_ids)
    ordered = sorted(source.segments, key=lambda item: (item.started_at, item.segment_id))
    blocks = []
    for index, segment in enumerate(ordered):
        participant = participants[segment.speaker_id]
        label = participant.display_name
        if participant.participant_id in owners:
            label = prompt("ingest.owner_wrapped", label=label)
        blocks.append(
            NormalizedBlock(
                index=index,
                text=prompt("ingest.turn_line", label=label, text=segment.text),
                section_path=[_local_day(segment.started_at, time)],
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
            "started_at": source.started_at.isoformat(),
            "ended_at": (
                source.ended_at.isoformat() if source.ended_at is not None else None
            ),
            # Provider-neutral timeline metadata lets a source viewer reconstruct the
            # meeting without duplicating the citable transcript text held in blocks.
            "segments": [
                {
                    "segment_id": item.segment_id,
                    "speaker_id": item.speaker_id,
                    "started_at": item.started_at.isoformat(),
                    "ended_at": (
                        item.ended_at.isoformat()
                        if item.ended_at is not None
                        else None
                    ),
                }
                for item in ordered
            ],
            "timezone": source.timezone,
            "metadata": source.metadata,
        },
    )
    stamp_occurred_on(raw, [block.section_path[0] for block in blocks])
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
                "created_at": (
                    document.created_at.isoformat()
                    if document.created_at is not None
                    else None
                ),
                "modified_at": (
                    document.modified_at.isoformat()
                    if document.modified_at is not None
                    else None
                ),
                "metadata": document.metadata,
                "library_metadata": source.metadata,
            },
        )
        normalized.append(
            adapter.normalize(PlainDocumentInput(raw=raw, text=document.content))
        )
    return normalized


def _im(
    source: ImSource,
    user_id: UserId,
    time: TimeContext | None = None,
    materialized_images: Mapping[str, BlockImage] | None = None,
) -> list[NormalizedSource]:
    users = {item.user_id: item for item in source.users}
    owners = set(source.owner_user_ids)
    normalized: list[NormalizedSource] = []
    for conversation in sorted(
        source.conversations, key=lambda item: item.conversation_id
    ):
        messages = sorted(
            conversation.messages, key=lambda item: (item.sent_at, item.message_id)
        )
        # Who this conversation's envelope carries a user record for: its declared members,
        # then everyone who actually SENT a message and was not one. The contract requires
        # both to be users of the archive and neither to be a subset of the other — a
        # provider snapshot where a guest posts into a channel they are not a member of is
        # ordinary and valid — so copying member records alone dropped the user record of
        # every such sender, and nothing downstream could resolve who spoke. Ordered: members
        # in their declared order, then senders in first-seen order.
        present_ids = list(dict.fromkeys(conversation.member_ids))
        seen = set(present_ids)
        for message in messages:
            if message.sender_id not in seen:
                seen.add(message.sender_id)
                present_ids.append(message.sender_id)
        blocks = []
        for index, message in enumerate(messages):
            sender = users[message.sender_id]
            label = sender.display_name
            if sender.user_id in owners:
                label = prompt("ingest.owner_wrapped", label=label)
            images: list[BlockImage] = []
            for declared in message.images:
                if (
                    materialized_images is None
                    or declared.image_id not in materialized_images
                ):
                    raise ValueError(
                        f"image {declared.image_id!r} must be materialized before normalization"
                    )
                stored = materialized_images[declared.image_id]
                if (
                    stored.image_id != declared.image_id
                    or stored.mime_type != declared.mime_type
                    or stored.sha256 != declared.source.sha256
                ):
                    raise ValueError(
                        f"materialized image {declared.image_id!r} does not match its declaration"
                    )
                images.append(stored)
            blocks.append(
                NormalizedBlock(
                    index=index,
                    text=prompt(
                        "ingest.turn_line", label=label, text=message.text
                    ),
                    section_path=[_local_day(message.sent_at, time)],
                    images=images,
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
                "users": [
                    users[user_id].model_dump(mode="json") for user_id in present_ids
                ],
                # Text stays in normalized blocks. This parallel metadata is only the
                # provider-neutral envelope required to present channel chronology,
                # threads, edits and reactions faithfully.
                "messages": [
                    {
                        "message_id": item.message_id,
                        "sender_id": item.sender_id,
                        "sent_at": item.sent_at.isoformat(),
                        "thread_id": item.thread_id,
                        "edited_at": (
                            item.edited_at.isoformat()
                            if item.edited_at is not None
                            else None
                        ),
                        "reactions": [
                            reaction.model_dump(mode="json")
                            for reaction in item.reactions
                        ],
                        **(
                            {"image_ids": [image.image_id for image in item.images]}
                            if item.images
                            else {}
                        ),
                    }
                    for item in messages
                ],
                "metadata": conversation.metadata,
                "archive_metadata": source.metadata,
            },
        )
        stamp_occurred_on(raw, [block.section_path[0] for block in blocks])
        normalized.append(
            NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
        )
    return normalized


def _owner_dialogue(
    source: OwnerDialogueSource, user_id: UserId, time: TimeContext | None = None
) -> list[NormalizedSource]:
    """One dialogue → one source, one block per turn.

    Turns are NOT reordered: the contract already rejects a payload whose timestamps go
    backwards, so the stored order is the spoken order. A block is labelled with the ROLE
    that spoke it; `owner_id` / `steward_id` are the application's own scheme and ride the
    envelope beside the turn ids, rejoined to blocks by normalized order like every other
    contract's parallel metadata. Nothing about the source is privileged — it is L0 text at
    `[cite: <sid> ¶n]` and reaches canonical only through an ordinary compile and the gate.
    """
    labels = {
        "owner": prompt("ingest.owner_label"),
        "steward": prompt("ingest.steward_label"),
    }
    blocks = [
        NormalizedBlock(
            index=index,
            text=prompt(
                "ingest.turn_line", label=labels[turn.role], text=turn.text
            ),
            section_path=[_local_day(turn.said_at, time)],
        )
        for index, turn in enumerate(source.turns)
    ]
    raw = _raw(
        user_id=user_id,
        kind="owner_dialogue",
        provider=source.provider,
        provider_id=source.dialogue_id,
        title=prompt("ingest.owner_dialogue.title", dialogue_id=source.dialogue_id),
        mime="application/vnd.pneuma.owner-dialogue+json",
        created_at=source.turns[0].said_at,
        evidence=source,
        meta={
            "contract_schema": source.contract_schema,
            "dialogue_id": source.dialogue_id,
            "owner_id": source.owner_id,
            "steward_id": source.steward_id,
            "turn_ids": [item.turn_id for item in source.turns],
            # Text stays in the blocks. This envelope is only what a reader needs to
            # reconstruct who spoke each turn and when, without the ids ever appearing in
            # the text the compile model reads.
            "turns": [
                {
                    "turn_id": item.turn_id,
                    "role": item.role,
                    "said_at": item.said_at.isoformat(),
                }
                for item in source.turns
            ],
            "metadata": source.metadata,
        },
    )
    stamp_occurred_on(raw, [block.section_path[0] for block in blocks])
    return [
        NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
    ]


def _address_label(address: EmailAddress) -> str:
    return (
        f"{address.display_name} <{address.address}>"
        if address.display_name
        else address.address
    )


def _email_block(message: EmailMessage, owners: set[str]) -> str:
    sender = _address_label(message.from_)
    if message.from_.address in owners:
        sender = prompt("ingest.owner_wrapped", label=sender)
    recipients = ", ".join(_address_label(item) for item in message.to)
    lines = [
        f"{sender} → {recipients}",
        prompt("ingest.email.subject", subject=message.subject),
        message.text,
    ]
    if message.attachments:
        lines.append(
            prompt("ingest.email.attachments")
            + ", ".join(
                f"{item.filename} ({item.content_type}, {item.size_bytes} bytes)"
                for item in message.attachments
            )
        )
    return "\n".join(lines)


def _email(
    source: EmailSource, user_id: UserId, time: TimeContext | None = None
) -> list[NormalizedSource]:
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
                section_path=[_local_day(message.sent_at, time)],
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
                # Message bodies remain the citable block sequence. Header and
                # attachment envelopes are retained here so the UI need not reverse
                # engineer RFC-like strings from block prose.
                "messages": [
                    {
                        "message_id": item.message_id,
                        "sent_at": item.sent_at.isoformat(),
                        "from": item.from_.model_dump(mode="json"),
                        "to": [
                            address.model_dump(mode="json") for address in item.to
                        ],
                        "cc": [
                            address.model_dump(mode="json") for address in item.cc
                        ],
                        "subject": item.subject,
                        "in_reply_to": item.in_reply_to,
                        "references": item.references,
                        "attachments": [
                            attachment.model_dump(mode="json")
                            for attachment in item.attachments
                        ],
                    }
                    for item in messages
                ],
                "metadata": thread.metadata,
                "archive_metadata": source.metadata,
            },
        )
        stamp_occurred_on(raw, [block.section_path[0] for block in blocks])
        normalized.append(
            NormalizedSource(raw=raw, blocks=blocks, structure=_spans_from_paths(blocks))
        )
    return normalized


def normalize_source_contract(
    source: SourceContract,
    user_id: UserId,
    *,
    imported_at: datetime,
    time: TimeContext | None = None,
    materialized_images: Mapping[str, BlockImage] | None = None,
) -> list[NormalizedSource]:
    """Expand one official contract into immutable compiler sources.

    `time` is the knowledge subject's clock: the conversation-shaped contracts (meeting, IM,
    email, owner dialogue) cut sections by calendar day, and that day is the subject's local
    one. A document library is cut by headings, so it never needs it. Absent → each
    timestamp's own offset.
    """

    if isinstance(source, MeetingSource):
        return _meeting(source, user_id, time)
    if isinstance(source, DocumentLibrarySource):
        return _library(source, user_id, imported_at)
    if isinstance(source, ImSource):
        return _im(source, user_id, time, materialized_images)
    if isinstance(source, EmailSource):
        return _email(source, user_id, time)
    if isinstance(source, OwnerDialogueSource):
        return _owner_dialogue(source, user_id, time)
    raise TypeError(f"unsupported source contract: {type(source)!r}")
