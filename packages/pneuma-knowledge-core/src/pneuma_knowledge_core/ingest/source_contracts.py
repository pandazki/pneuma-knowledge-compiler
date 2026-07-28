"""Versioned, provider-neutral contracts for official Pneuma source adapters.

The matching JSON Schemas under ``docs/specs/source-contracts`` are the public wire
contracts. These strict Pydantic models enforce the cross-record invariants that JSON
Schema cannot express conveniently (identity references, timezone awareness and safe
vault paths).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


def _require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an explicit timezone offset")
    return value


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MeetingParticipant(ContractModel):
    participant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str | None = None


class MeetingSegment(ContractModel):
    segment_id: str = Field(min_length=1)
    speaker_id: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    text: str = Field(min_length=1)

    _aware_started = field_validator("started_at")(_require_aware)
    _aware_ended = field_validator("ended_at")(_require_aware)

    @model_validator(mode="after")
    def end_follows_start(self) -> "MeetingSegment":
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("segment ended_at must not precede started_at")
        return self


class MeetingSource(ContractModel):
    contract_schema: Literal["pneuma.source.meeting/v1"] = Field(alias="schema")
    provider: Literal["zoom", "mock"]
    meeting_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    timezone: str | None = None
    owner_participant_ids: list[str] = Field(default_factory=list)
    participants: list[MeetingParticipant]
    agenda: list[str] = Field(default_factory=list)
    segments: list[MeetingSegment] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware_started = field_validator("started_at")(_require_aware)
    _aware_ended = field_validator("ended_at")(_require_aware)

    @model_validator(mode="after")
    def validate_identity_graph(self) -> "MeetingSource":
        participant_ids = [item.participant_id for item in self.participants]
        if duplicates := _duplicates(participant_ids):
            raise ValueError(f"duplicate participant ids: {sorted(duplicates)}")
        known = set(participant_ids)
        if unknown := set(self.owner_participant_ids) - known:
            raise ValueError(f"owner participant ids are unknown: {sorted(unknown)}")
        segment_ids = [item.segment_id for item in self.segments]
        if duplicates := _duplicates(segment_ids):
            raise ValueError(f"duplicate segment ids: {sorted(duplicates)}")
        if unknown := {item.speaker_id for item in self.segments} - known:
            raise ValueError(f"segment speaker ids are unknown: {sorted(unknown)}")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("meeting ended_at must not precede started_at")
        return self


class LibraryLink(ContractModel):
    target: str = Field(min_length=1)
    label: str | None = None
    embedded: bool = False


class LibraryDocument(ContractModel):
    document_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str
    frontmatter: dict[str, Any]
    tags: list[str]
    links: list[LibraryLink]
    created_at: datetime | None = None
    modified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware_created = field_validator("created_at")(_require_aware)
    _aware_modified = field_validator("modified_at")(_require_aware)

    @field_validator("path")
    @classmethod
    def safe_relative_vault_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or ".." in path.parts
            or any(part.startswith(".") for part in path.parts)
        ):
            raise ValueError("path must be a visible file inside the vault")
        return path.as_posix()

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, value: list[str]) -> list[str]:
        if duplicates := _duplicates(value):
            raise ValueError(f"duplicate tags: {sorted(duplicates)}")
        return value


class DocumentLibrarySource(ContractModel):
    contract_schema: Literal["pneuma.source.document-library/v1"] = Field(alias="schema")
    provider: Literal["obsidian", "mock"]
    library_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    documents: list[LibraryDocument] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_documents(self) -> "DocumentLibrarySource":
        ids = [item.document_id for item in self.documents]
        paths = [item.path.casefold() for item in self.documents]
        if duplicates := _duplicates(ids):
            raise ValueError(f"duplicate document ids: {sorted(duplicates)}")
        if duplicates := _duplicates(paths):
            raise ValueError(f"duplicate document paths: {sorted(duplicates)}")
        return self


class ImUser(ContractModel):
    user_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str | None = None
    is_bot: bool = False


class ImReaction(ContractModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=1)


class ImMessage(ContractModel):
    message_id: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    sent_at: datetime
    text: str
    thread_id: str | None = None
    edited_at: datetime | None = None
    reactions: list[ImReaction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware_sent = field_validator("sent_at")(_require_aware)
    _aware_edited = field_validator("edited_at")(_require_aware)


class ImConversation(ContractModel):
    conversation_id: str = Field(min_length=1)
    conversation_type: Literal["channel", "dm", "group_dm"]
    title: str = Field(min_length=1)
    member_ids: list[str]
    messages: list[ImMessage] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_messages(self) -> "ImConversation":
        ids = [item.message_id for item in self.messages]
        if duplicates := _duplicates(ids):
            raise ValueError(f"duplicate message ids: {sorted(duplicates)}")
        return self


class ImSource(ContractModel):
    contract_schema: Literal["pneuma.source.im/v1"] = Field(alias="schema")
    provider: Literal["slack", "mock"]
    archive_id: str = Field(min_length=1)
    owner_user_ids: list[str]
    users: list[ImUser]
    conversations: list[ImConversation] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_graph(self) -> "ImSource":
        user_ids = [item.user_id for item in self.users]
        if duplicates := _duplicates(user_ids):
            raise ValueError(f"duplicate user ids: {sorted(duplicates)}")
        known = set(user_ids)
        if unknown := set(self.owner_user_ids) - known:
            raise ValueError(f"owner user ids are unknown: {sorted(unknown)}")
        conversation_ids = [item.conversation_id for item in self.conversations]
        if duplicates := _duplicates(conversation_ids):
            raise ValueError(f"duplicate conversation ids: {sorted(duplicates)}")
        for conversation in self.conversations:
            if unknown := set(conversation.member_ids) - known:
                raise ValueError(
                    f"conversation {conversation.conversation_id} has unknown member ids: "
                    f"{sorted(unknown)}"
                )
            if unknown := {item.sender_id for item in conversation.messages} - known:
                raise ValueError(
                    f"conversation {conversation.conversation_id} has unknown sender ids: "
                    f"{sorted(unknown)}"
                )
        return self


class EmailAddress(ContractModel):
    address: str = Field(min_length=3)
    display_name: str | None = None

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        return value.strip().casefold()


class EmailAttachment(ContractModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    content_id: str | None = None


class EmailMessage(ContractModel):
    message_id: str = Field(min_length=1)
    sent_at: datetime
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress]
    cc: list[EmailAddress]
    subject: str
    text: str
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    attachments: list[EmailAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware_sent = field_validator("sent_at")(_require_aware)


class EmailThread(ContractModel):
    thread_id: str = Field(min_length=1)
    subject: str
    messages: list[EmailMessage] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_messages(self) -> "EmailThread":
        ids = [item.message_id for item in self.messages]
        if duplicates := _duplicates(ids):
            raise ValueError(f"duplicate message ids: {sorted(duplicates)}")
        return self


class EmailSource(ContractModel):
    contract_schema: Literal["pneuma.source.email/v1"] = Field(alias="schema")
    provider: Literal["rfc822", "mock"]
    archive_id: str = Field(min_length=1)
    owner_addresses: list[str]
    threads: list[EmailThread] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("owner_addresses")
    @classmethod
    def normalize_owners(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().casefold() for item in value]
        if duplicates := _duplicates(normalized):
            raise ValueError(f"duplicate owner addresses: {sorted(duplicates)}")
        return normalized

    @model_validator(mode="after")
    def unique_threads_and_messages(self) -> "EmailSource":
        thread_ids = [item.thread_id for item in self.threads]
        if duplicates := _duplicates(thread_ids):
            raise ValueError(f"duplicate thread ids: {sorted(duplicates)}")
        message_ids = [
            message.message_id for thread in self.threads for message in thread.messages
        ]
        if duplicates := _duplicates(message_ids):
            raise ValueError(f"duplicate message ids across threads: {sorted(duplicates)}")
        return self


SourceContract = Annotated[
    MeetingSource | DocumentLibrarySource | ImSource | EmailSource,
    Field(discriminator="contract_schema"),
]
_SOURCE_CONTRACT_ADAPTER = TypeAdapter(SourceContract)


def parse_source_contract(payload: object) -> SourceContract:
    """Validate a Python/JSON-compatible payload against one official v1 contract."""

    return _SOURCE_CONTRACT_ADAPTER.validate_python(payload)
