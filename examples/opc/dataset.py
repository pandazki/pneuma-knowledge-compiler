"""Pure OPC 84-day v2 authoring-to-SourceContract assembly.

It is an anti-corruption layer from accepted ``group-content/v1`` JSON to the four
official provider-neutral source contracts. The experiment runner consumes only the
globally validated accepted snapshot assembled here.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
    SchemaError as JsonSchemaSchemaError,
    ValidationError as JsonSchemaValidationError,
)

from pneuma_knowledge_core.ingest.source_contracts import (
    SourceContract,
    parse_source_contract,
)


EXPECTED_GROUP_IDS: tuple[str, ...] = tuple(
    f"G{number:02d}" for number in range(1, 29)
)
_FAMILY_ORDER: tuple[str, ...] = (
    "meetings",
    "document_library",
    "im",
    "email",
)
EXPECTED_SOURCE_CONTRACT_COUNT = 104
DATA_ROOT = Path(__file__).resolve().parent / "data" / "84-day"


@dataclass(frozen=True)
class AcceptedOpc84dV2Batch:
    """One accepted group, imported as one chronological increment."""

    batch_id: str
    starts_on: date
    ends_on: date
    contracts: tuple[SourceContract, ...]


@dataclass(frozen=True)
class AcceptedOpc84dV2Dataset:
    """The immutable, evidence-bound v2 corpus used by the experiment runner."""

    batches: tuple[AcceptedOpc84dV2Batch, ...]


class Opc84dV2AssemblyError(ValueError):
    """The accepted v2 corpus cannot be assembled without violating its contract."""


class _EvidencePathOutsideRootError(ValueError):
    """An acceptance record points outside its caller-supplied trust root."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _authorship_metadata(authored: dict[str, Any]) -> dict[str, Any]:
    authorship = deepcopy(authored["authorship"])
    return {
        "authorship": authorship,
        "story_links": deepcopy(authorship["links"]),
    }


def _source_metadata(
    group: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    return {
        "group_id": group["group_id"],
        "group_window": deepcopy(group["group_window"]),
        "source_id": source["source_id"],
        **_authorship_metadata(source),
    }


def _convert_meeting(
    group: dict[str, Any], source: dict[str, Any]
) -> SourceContract:
    segment_metadata: dict[str, dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    for utterance in source["utterances"]:
        segment_id = utterance["utterance_id"]
        metadata = _authorship_metadata(utterance)
        if "interruption_of_utterance_id" in utterance:
            metadata["interruption_of_utterance_id"] = utterance[
                "interruption_of_utterance_id"
            ]
        segment_metadata[segment_id] = metadata
        segments.append(
            {
                "segment_id": segment_id,
                "speaker_id": utterance["speaker_id"],
                "started_at": utterance["started_at"],
                "ended_at": utterance["ended_at"],
                "text": utterance["text"],
            }
        )

    metadata = _source_metadata(group, source)
    metadata.update(
        {
            "participant_roles": {
                participant["participant_id"]: participant["role"]
                for participant in source["participants"]
            },
            "agenda_items": [
                {
                    "agenda_id": item["agenda_id"],
                    **_authorship_metadata(item),
                }
                for item in source["agenda"]
            ],
            "segment_metadata": segment_metadata,
        }
    )
    payload = {
        "schema": source["schema"],
        "provider": source["provider"],
        "meeting_id": source["meeting_id"],
        "title": source["title"],
        "started_at": source["started_at"],
        "ended_at": source["ended_at"],
        "timezone": source["timezone"],
        "owner_participant_ids": list(source["owner_participant_ids"]),
        "participants": [
            {
                "participant_id": participant["participant_id"],
                "display_name": participant["display_name"],
                "email": participant["synthetic_address"],
            }
            for participant in source["participants"]
        ],
        "agenda": [item["text"] for item in source["agenda"]],
        "segments": segments,
        "metadata": metadata,
    }
    return parse_source_contract(payload)


def _convert_document_library(
    group: dict[str, Any], source: dict[str, Any]
) -> SourceContract:
    documents: list[dict[str, Any]] = []
    for document in source["documents"]:
        metadata = _authorship_metadata(document)
        metadata.update(
            {
                "visible_blocks": deepcopy(document["visible_blocks"]),
                "authored_links": deepcopy(document["links"]),
            }
        )
        documents.append(
            {
                "document_id": document["document_id"],
                "path": document["path"],
                "title": document["title"],
                "content": document["full_markdown"],
                "frontmatter": deepcopy(document["frontmatter"]),
                "tags": list(document["tags"]),
                "links": [
                    {
                        "target": link["target"],
                        "label": link["label"],
                        "embedded": link["embedded"],
                    }
                    for link in document["links"]
                ],
                "created_at": document["created_at"],
                "modified_at": document["modified_at"],
                "metadata": metadata,
            }
        )

    payload = {
        "schema": source["schema"],
        "provider": source["provider"],
        "library_id": source["library_id"],
        "title": source["title"],
        "documents": documents,
        "metadata": _source_metadata(group, source),
    }
    return parse_source_contract(payload)


def _convert_im(
    group: dict[str, Any], source: dict[str, Any]
) -> SourceContract:
    conversations: list[dict[str, Any]] = []
    for conversation in source["conversations"]:
        messages: list[dict[str, Any]] = []
        for message in conversation["messages"]:
            metadata = _authorship_metadata(message)
            metadata["authored_reactions"] = deepcopy(message["reactions"])
            messages.append(
                {
                    "message_id": message["message_id"],
                    "sender_id": message["sender_id"],
                    "sent_at": message["sent_at"],
                    "text": message["full_text"],
                    "thread_id": message["thread_id"],
                    "edited_at": message["edited_at"],
                    "reactions": [
                        {
                            "name": reaction["name"],
                            "count": len(reaction["reactor_ids"]),
                        }
                        for reaction in message["reactions"]
                    ],
                    "metadata": metadata,
                }
            )
        conversations.append(
            {
                "conversation_id": conversation["conversation_id"],
                "conversation_type": conversation["conversation_type"],
                "title": conversation["title"],
                "member_ids": list(conversation["member_ids"]),
                "messages": messages,
                "metadata": _authorship_metadata(conversation),
            }
        )

    metadata = _source_metadata(group, source)
    metadata["user_roles"] = {
        user["user_id"]: user["role"] for user in source["users"]
    }
    payload = {
        "schema": source["schema"],
        "provider": source["provider"],
        "archive_id": source["archive_id"],
        "owner_user_ids": list(source["owner_user_ids"]),
        "users": [
            {
                "user_id": user["user_id"],
                "display_name": user["display_name"],
                "email": user["synthetic_address"],
                "is_bot": user["is_bot"],
            }
            for user in source["users"]
        ],
        "conversations": conversations,
        "metadata": metadata,
    }
    return parse_source_contract(payload)


def _email_address(address: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": address["address"],
        "display_name": address["display_name"],
    }


def _convert_email(
    group: dict[str, Any], source: dict[str, Any]
) -> SourceContract:
    threads: list[dict[str, Any]] = []
    for thread in source["threads"]:
        messages: list[dict[str, Any]] = []
        for message in thread["messages"]:
            metadata = _authorship_metadata(message)
            metadata.update(
                {
                    "headers": deepcopy(message["headers"]),
                    "address_roles": {
                        "from": message["from"]["role"],
                        "to": [address["role"] for address in message["to"]],
                        "cc": [address["role"] for address in message["cc"]],
                    },
                    "authored_attachments": deepcopy(message["attachments"]),
                }
            )
            messages.append(
                {
                    "message_id": message["message_id"],
                    "sent_at": message["sent_at"],
                    "from": _email_address(message["from"]),
                    "to": [_email_address(address) for address in message["to"]],
                    "cc": [_email_address(address) for address in message["cc"]],
                    "subject": message["subject"],
                    "text": message["full_text"],
                    "in_reply_to": message["in_reply_to"],
                    "references": list(message["references"]),
                    "attachments": [
                        {
                            "filename": attachment["filename"],
                            "content_type": attachment["content_type"],
                            "size_bytes": attachment["size_bytes"],
                            "content_id": attachment.get("content_id"),
                        }
                        for attachment in message["attachments"]
                    ],
                    "metadata": metadata,
                }
            )
        threads.append(
            {
                "thread_id": thread["thread_id"],
                "subject": thread["subject"],
                "messages": messages,
                "metadata": _authorship_metadata(thread),
            }
        )

    payload = {
        "schema": source["schema"],
        "provider": source["provider"],
        "archive_id": source["archive_id"],
        "owner_addresses": list(source["owner_addresses"]),
        "threads": threads,
        "metadata": _source_metadata(group, source),
    }
    return parse_source_contract(payload)


_CONVERTERS = {
    "meetings": _convert_meeting,
    "document_library": _convert_document_library,
    "im": _convert_im,
    "email": _convert_email,
}


def _iter_authored_sources(
    group: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    for family in _FAMILY_ORDER:
        for source in group["sources"][family]:
            yield family, source


def _iter_normalized_provider_ids(
    family: str,
    source: dict[str, Any],
) -> Iterator[str]:
    """Yield the provider identities used by the official normalizers.

    Document, IM, and email contracts are containers. Reusing one vault/archive
    identifier across disjoint contracts is valid; the normalized source identity
    adds the document, conversation, or thread identifier respectively.
    """

    if family == "meetings":
        yield source["meeting_id"]
    elif family == "document_library":
        for document in source["documents"]:
            yield f"{source['library_id']}:{document['document_id']}"
    elif family == "im":
        for conversation in source["conversations"]:
            yield f"{source['archive_id']}:{conversation['conversation_id']}"
    elif family == "email":
        for thread in source["threads"]:
            yield f"{source['archive_id']}:{thread['thread_id']}"
    else:
        raise KeyError(f"unknown source family {family!r}")


def convert_authored_group(group: dict[str, Any]) -> tuple[SourceContract, ...]:
    """Convert one accepted authored group in stable family/source order.

    Every payload crosses ``parse_source_contract`` before it is returned.
    """

    return tuple(
        _CONVERTERS[family](group, source)
        for family, source in _iter_authored_sources(group)
    )


def _read_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Opc84dV2AssemblyError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise Opc84dV2AssemblyError(f"{label} must contain one JSON object")
    return value, raw


def _group_paths(groups_dir: Path) -> dict[str, Path]:
    if not groups_dir.is_dir():
        raise Opc84dV2AssemblyError(f"groups directory does not exist: {groups_dir}")
    expected = {f"{group_id}.json" for group_id in EXPECTED_GROUP_IDS}
    found = {
        path.name: path
        for path in groups_dir.iterdir()
        if path.is_file() and path.suffix == ".json"
    }
    if set(found) != expected:
        raise Opc84dV2AssemblyError(
            "frozen group set mismatch: "
            f"missing={sorted(expected - set(found))}; "
            f"unexpected={sorted(set(found) - expected)}"
        )
    return found


def _groups_digest(paths: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for name in sorted(paths):
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(paths[name].read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _validator(schema_path: Path, expected_sha: str) -> Draft202012Validator:
    schema, raw = _read_object(schema_path, "group schema")
    if _sha256(raw) != expected_sha:
        raise Opc84dV2AssemblyError("frozen group schema hash mismatch")
    try:
        Draft202012Validator.check_schema(schema)
    except JsonSchemaSchemaError as error:
        raise Opc84dV2AssemblyError(
            f"invalid frozen group schema: {error.message}"
        ) from error
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_frozen_manifest(data_root: Path = DATA_ROOT) -> dict[str, Any]:
    """Load and mechanically verify the compact final-asset manifest."""
    data_root = data_root.resolve()
    manifest, _ = _read_object(data_root / "manifest.json", "84-day manifest")
    if manifest.get("schema") != "pneuma.example.opc-84-day/v1":
        raise Opc84dV2AssemblyError("unexpected 84-day manifest schema")
    if manifest.get("experiment_id") != "opc-84d-v2":
        raise Opc84dV2AssemblyError("unexpected 84-day experiment id")
    paths = _group_paths(data_root / "groups")
    if _groups_digest(paths) != manifest.get("groups_sha256"):
        raise Opc84dV2AssemblyError("frozen accepted groups hash mismatch")
    truth_path = data_root / "spec" / "evaluation-truth.json"
    if _sha256(truth_path.read_bytes()) != manifest.get("truth_sha256"):
        raise Opc84dV2AssemblyError("frozen evaluation truth hash mismatch")
    return manifest


def load_accepted_source_contracts(
    data_root: Path = DATA_ROOT,
) -> tuple[SourceContract, ...]:
    """Validate and convert the 28 final groups, with no authoring-process baggage."""
    data_root = data_root.resolve()
    manifest = load_frozen_manifest(data_root)
    paths = _group_paths(data_root / "groups")
    validator = _validator(
        data_root / "spec" / "group-content.schema.json",
        str(manifest.get("group_schema_sha256") or ""),
    )

    seen_source_ids: dict[str, str] = {}
    seen_provider_ids: dict[tuple[str, str, str], str] = {}
    family_counts: Counter[str] = Counter()
    contracts: list[SourceContract] = []

    for group_id in EXPECTED_GROUP_IDS:
        path = paths[f"{group_id}.json"]
        group, _ = _read_object(path, f"frozen group {group_id}")
        try:
            validator.validate(group)
        except JsonSchemaValidationError as error:
            raise Opc84dV2AssemblyError(
                f"{path.name} failed group schema validation: {error.message}"
            ) from error
        if group.get("group_id") != group_id:
            raise Opc84dV2AssemblyError(
                f"{path.name} declares group_id {group.get('group_id')!r}"
            )

        for family, source in _iter_authored_sources(group):
            family_counts[family] += 1
            source_id = source["source_id"]
            if previous := seen_source_ids.get(source_id):
                raise Opc84dV2AssemblyError(
                    f"duplicate source_id {source_id!r}: {previous} and {group_id}"
                )
            seen_source_ids[source_id] = group_id
            for provider_id in _iter_normalized_provider_ids(family, source):
                key = (family, source["provider"], provider_id)
                if previous := seen_provider_ids.get(key):
                    raise Opc84dV2AssemblyError(
                        f"duplicate provider id {provider_id!r}: "
                        f"{previous} and {group_id}"
                    )
                seen_provider_ids[key] = group_id

        try:
            converted = convert_authored_group(group)
            for contract in converted:
                json.dumps(contract.metadata, ensure_ascii=False)
        except (KeyError, TypeError, ValueError) as error:
            raise Opc84dV2AssemblyError(
                f"cannot convert frozen group {group_id}: {error}"
            ) from error
        contracts.extend(converted)

    expected_counts = {
        "meetings": manifest["source_counts"]["meeting"],
        "document_library": manifest["source_counts"]["document_library"],
        "im": manifest["source_counts"]["im"],
        "email": manifest["source_counts"]["email"],
    }
    if dict(family_counts) != expected_counts:
        raise Opc84dV2AssemblyError(
            f"source family count mismatch: {dict(family_counts)} != {expected_counts}"
        )
    if len(contracts) != manifest.get("source_count"):
        raise Opc84dV2AssemblyError(
            f"source-contract count mismatch: {len(contracts)}"
        )
    return tuple(contracts)


def _batch_window(
    group_id: str,
    contracts: tuple[SourceContract, ...],
) -> tuple[date, date]:
    windows = {
        json.dumps(contract.metadata.get("group_window"), sort_keys=True)
        for contract in contracts
    }
    if len(windows) != 1:
        raise Opc84dV2AssemblyError(
            f"frozen group {group_id} does not have one shared window"
        )
    try:
        window = json.loads(windows.pop())
        starts_on = date.fromisoformat(window["starts_on"])
        ends_on = date.fromisoformat(window["ends_on"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise Opc84dV2AssemblyError(
            f"frozen group {group_id} has an invalid window"
        ) from error
    if ends_on < starts_on:
        raise Opc84dV2AssemblyError(
            f"frozen group {group_id} ends before it starts"
        )
    return starts_on, ends_on


def build_accepted_opc_84d_v2_dataset(
    *,
    data_root: Path = DATA_ROOT,
) -> AcceptedOpc84dV2Dataset:
    """Assemble the frozen corpus into 28 chronological import increments."""
    contracts = load_accepted_source_contracts(data_root)
    if len(contracts) != EXPECTED_SOURCE_CONTRACT_COUNT:
        raise Opc84dV2AssemblyError(
            "accepted corpus source-contract count mismatch: "
            f"expected {EXPECTED_SOURCE_CONTRACT_COUNT}, got {len(contracts)}"
        )

    batches: list[AcceptedOpc84dV2Batch] = []
    previous_end: date | None = None
    for group_id in EXPECTED_GROUP_IDS:
        group_contracts = tuple(
            contract
            for contract in contracts
            if contract.metadata.get("group_id") == group_id
        )
        if not group_contracts:
            raise Opc84dV2AssemblyError(
                f"frozen group {group_id} produced no source contracts"
            )
        starts_on, ends_on = _batch_window(group_id, group_contracts)
        if previous_end is not None and starts_on <= previous_end:
            raise Opc84dV2AssemblyError(
                f"frozen group {group_id} overlaps the prior group"
            )
        batches.append(
            AcceptedOpc84dV2Batch(
                batch_id=group_id,
                starts_on=starts_on,
                ends_on=ends_on,
                contracts=group_contracts,
            )
        )
        previous_end = ends_on
    return AcceptedOpc84dV2Dataset(batches=tuple(batches))
