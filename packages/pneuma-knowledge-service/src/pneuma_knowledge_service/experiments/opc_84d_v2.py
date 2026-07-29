"""Pure OPC 84-day v2 authoring-to-SourceContract assembly.

It is an anti-corruption layer from accepted ``group-content/v1`` JSON to the four
official provider-neutral source contracts. The experiment runner consumes only the
globally validated accepted snapshot assembled here.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator, NoReturn

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
    SchemaError as JsonSchemaSchemaError,
    ValidationError as JsonSchemaValidationError,
)
from pydantic import ValidationError as PydanticValidationError

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
_ACCEPTANCE_INPUTS: tuple[str, ...] = (
    "group",
    "deterministic_report",
    "independent_review",
    "daily_beats",
    "schema",
    "qa_rubric",
    "story_bible",
)
EXPECTED_DETECTOR_VERSION = "opc-84d-v2-deterministic/3"
EXPECTED_SOURCE_CONTRACT_COUNT = 104
_GLOBAL_QA_SCHEMA = "pneuma.experiment.opc-84d-v2.global-qa/v1"


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


def _require_directory(path: Path, label: str) -> None:
    if path.is_dir():
        return
    error = FileNotFoundError(f"{label} directory does not exist: {path}")
    raise Opc84dV2AssemblyError(str(error)) from error


def _exact_group_files(directory: Path, label: str) -> dict[str, Path]:
    expected_names = {f"{group_id}.json" for group_id in EXPECTED_GROUP_IDS}
    found = {
        path.name: path
        for path in directory.iterdir()
        if path.is_file() and path.suffix == ".json"
    }
    found_names = set(found)
    if found_names != expected_names:
        missing = sorted(expected_names - found_names)
        unexpected = sorted(found_names - expected_names)
        raise Opc84dV2AssemblyError(
            f"{label} group set mismatch: "
            f"missing={missing}; unexpected={unexpected}"
        )
    return found


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    value = path.read_bytes()
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{label} must contain a JSON object")
    return decoded, value


def _resolve_evidence_path(raw_path: str, root: Path) -> Path:
    resolved_root = root.resolve()
    path = Path(raw_path)
    resolved = (
        path.resolve()
        if path.is_absolute()
        else (resolved_root / path).resolve()
    )
    if not resolved.is_relative_to(resolved_root):
        raise _EvidencePathOutsideRootError(
            f"{raw_path!r} resolves outside explicit root {resolved_root}"
        )
    return resolved


def _same_path(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve()


def _stale(group_id: str, field: str, detail: str) -> NoReturn:
    raise Opc84dV2AssemblyError(
        f"{group_id} acceptance evidence is stale: {field} {detail}"
    )


def _resolve_snapshot_path(
    raw_path: str,
    *,
    group_id: str,
    field: str,
    root: Path,
) -> Path:
    try:
        return _resolve_evidence_path(raw_path, root)
    except _EvidencePathOutsideRootError:
        _stale(group_id, field, "path is outside explicit root")


def _is_canonical_input_path(
    path: Path,
    *,
    accepted_path: Path,
    group_id: str,
    label: str,
) -> bool:
    experiment_root = accepted_path.parent.parent
    expected: dict[str, Path] = {
        "group": experiment_root / "groups" / f"{group_id}.json",
        "deterministic_report": (
            experiment_root / "qa" / "deterministic" / f"{group_id}.json"
        ),
        "daily_beats": experiment_root / "daily-beats.json",
        "schema": experiment_root / "group-content.schema.json",
        "qa_rubric": experiment_root / "qa-rubric.md",
        "story_bible": experiment_root / "story-bible.md",
    }
    if label == "independent_review":
        review_dir = (experiment_root / "qa" / "reviews").resolve()
        return (
            path.parent == review_dir
            and path.suffix == ".md"
            and (
                path.name == f"{group_id}.md"
                or path.name.startswith(f"{group_id}-")
            )
        )
    return _same_path(path, expected[label])


def _acceptance_snapshot(
    evidence: dict[str, Any],
    *,
    group_id: str,
    label: str,
    accepted_path: Path,
    root: Path,
) -> tuple[Path, bytes, str]:
    snapshot = evidence["inputs"][label]
    raw_path = snapshot["path"]
    recorded_sha = snapshot["sha256"]
    if not isinstance(raw_path, str) or not isinstance(recorded_sha, str):
        raise TypeError(f"acceptance input {label} path/hash must be strings")
    path = _resolve_snapshot_path(
        raw_path,
        group_id=group_id,
        field=f"{label}.path",
        root=root,
    )
    if not _is_canonical_input_path(
        path,
        accepted_path=accepted_path,
        group_id=group_id,
        label=label,
    ):
        _stale(group_id, f"{label}.path", "is not the canonical input location")
    value = path.read_bytes()
    current_sha = _sha256(value)
    if recorded_sha.lower() != current_sha:
        _stale(group_id, label, "hash mismatch")
    return path, value, current_sha


def _require_mirrored_snapshot(
    evidence: dict[str, Any],
    *,
    group_id: str,
    section: str,
    expected_path: Path,
    expected_sha: str,
    root: Path,
) -> dict[str, Any]:
    snapshot = evidence[section]
    raw_path = snapshot["path"]
    recorded_sha = snapshot["sha256"]
    if not isinstance(raw_path, str) or not isinstance(recorded_sha, str):
        raise TypeError(f"acceptance {section} path/hash must be strings")
    resolved_path = _resolve_snapshot_path(
        raw_path,
        group_id=group_id,
        field=f"{section}.path",
        root=root,
    )
    if not _same_path(resolved_path, expected_path):
        _stale(group_id, f"{section}.path", "does not mirror its input")
    if recorded_sha.lower() != expected_sha:
        _stale(group_id, f"{section}.sha256", "does not mirror its input")
    return snapshot


def _validate_acceptance_evidence(
    evidence: dict[str, Any],
    *,
    group_id: str,
    accepted_path: Path,
    accepted_bytes: bytes,
    root: Path,
) -> tuple[bytes, str]:
    if evidence["schema"] != "pneuma.experiment.opc-84d-v2.acceptance/v1":
        _stale(group_id, "schema", "is not the acceptance/v1 contract")
    if evidence["status"] != "accepted":
        _stale(group_id, "status", "is not accepted")
    if evidence["group_id"] != group_id:
        _stale(group_id, "group_id", "does not match its filename")

    inputs = evidence["inputs"]
    if not isinstance(inputs, dict):
        raise TypeError("acceptance inputs must be an object")
    missing_inputs = sorted(set(_ACCEPTANCE_INPUTS) - set(inputs))
    if missing_inputs:
        raise KeyError(f"acceptance inputs missing {missing_inputs}")

    accepted_sha = _sha256(accepted_bytes)
    accepted_copy = evidence["accepted_copy"]
    accepted_copy_path = _resolve_snapshot_path(
        accepted_copy["path"],
        group_id=group_id,
        field="accepted_copy.path",
        root=root,
    )
    if not _same_path(accepted_copy_path, accepted_path):
        _stale(group_id, "accepted_copy.path", "does not name the loaded copy")
    if accepted_copy["sha256"].lower() != accepted_sha:
        _stale(group_id, "accepted_copy.sha256", "hash mismatch")
    if accepted_copy["byte_identical"] is not True:
        _stale(group_id, "accepted_copy.byte_identical", "is not true")
    if evidence["group_sha256"].lower() != accepted_sha:
        _stale(group_id, "group_sha256", "hash mismatch")

    resolved: dict[str, tuple[Path, bytes, str]] = {
        label: _acceptance_snapshot(
            evidence,
            group_id=group_id,
            label=label,
            accepted_path=accepted_path,
            root=root,
        )
        for label in _ACCEPTANCE_INPUTS
    }
    _, group_bytes, group_sha = resolved["group"]
    if group_bytes != accepted_bytes:
        _stale(group_id, "accepted_copy", "is not byte-identical to group input")
    if group_sha != accepted_sha:
        _stale(group_id, "inputs.group.sha256", "does not bind accepted copy")

    deterministic_path, deterministic_bytes, deterministic_sha = resolved[
        "deterministic_report"
    ]
    deterministic = _require_mirrored_snapshot(
        evidence,
        group_id=group_id,
        section="deterministic",
        expected_path=deterministic_path,
        expected_sha=deterministic_sha,
        root=root,
    )
    if deterministic.get("detector_version") != EXPECTED_DETECTOR_VERSION:
        _stale(
            group_id,
            "deterministic.detector_version",
            f"is not {EXPECTED_DETECTOR_VERSION}",
        )
    if (
        deterministic["status"] != "structural_pass"
        or deterministic["finding_count"] != 0
    ):
        _stale(group_id, "deterministic", "does not record a clean pass")
    deterministic_report = json.loads(deterministic_bytes)
    if not isinstance(deterministic_report, dict):
        raise TypeError("deterministic report must contain a JSON object")
    detector = deterministic_report.get("detector")
    detector_version = (
        detector.get("version") if isinstance(detector, dict) else None
    )
    if detector_version != EXPECTED_DETECTOR_VERSION:
        _stale(
            group_id,
            "deterministic.detector.version",
            f"is not {EXPECTED_DETECTOR_VERSION}",
        )
    if deterministic_report.get("status") != "structural_pass":
        _stale(group_id, "deterministic.status", "is not structural_pass")
    findings = deterministic_report.get("findings")
    if not isinstance(findings, list) or findings:
        _stale(group_id, "deterministic.findings", "is missing or non-empty")
    group_reports = deterministic_report.get("groups")
    if (
        not isinstance(group_reports, list)
        or not group_reports
        or any(
            not isinstance(item, dict)
            or item.get("group_id") != group_id
            or not isinstance(item.get("findings"), list)
            or item["findings"]
            for item in group_reports
        )
    ):
        _stale(
            group_id,
            "deterministic.groups",
            "does not contain a clean report for the group",
        )

    review_path, _, review_sha = resolved["independent_review"]
    review = _require_mirrored_snapshot(
        evidence,
        group_id=group_id,
        section="review",
        expected_path=review_path,
        expected_sha=review_sha,
        root=root,
    )
    if review["verdict"] != "PASS" or review["non_author_attested"] is not True:
        _stale(group_id, "review", "does not record an independent PASS")
    if review["recorded_group_sha256"].lower() != accepted_sha:
        _stale(group_id, "review.recorded_group_sha256", "hash mismatch")

    schema_bytes = resolved["schema"][1]
    return schema_bytes, resolved["schema"][2]


def _validate_globally_bound_acceptance_evidence(
    evidence: dict[str, Any],
    *,
    group_id: str,
    accepted_path: Path,
    accepted_bytes: bytes,
) -> tuple[bytes, str]:
    """Validate an accepted snapshot whose freshness is pinned by global QA.

    The strict loader above additionally requires every mutable authoring input to
    remain byte-identical after acceptance. The real importer instead relies on the
    global QA snapshot, which binds the acceptance record and accepted copy together.
    It still checks the acceptance record's declared pass conditions and the current
    source-contract schema before conversion.
    """

    if evidence.get("schema") != "pneuma.experiment.opc-84d-v2.acceptance/v1":
        _stale(group_id, "schema", "is not the acceptance/v1 contract")
    if evidence.get("status") != "accepted":
        _stale(group_id, "status", "is not accepted")
    if evidence.get("group_id") != group_id:
        _stale(group_id, "group_id", "does not match its filename")

    accepted_sha = _sha256(accepted_bytes)
    if evidence.get("group_sha256", "").lower() != accepted_sha:
        _stale(group_id, "group_sha256", "hash mismatch")
    accepted_copy = evidence.get("accepted_copy")
    if not isinstance(accepted_copy, dict):
        _stale(group_id, "accepted_copy", "is missing")
    if (
        accepted_copy.get("sha256", "").lower() != accepted_sha
        or accepted_copy.get("byte_identical") is not True
    ):
        _stale(group_id, "accepted_copy", "does not bind the accepted copy")

    inputs = evidence.get("inputs")
    if not isinstance(inputs, dict) or set(_ACCEPTANCE_INPUTS) - set(inputs):
        _stale(group_id, "inputs", "is missing required acceptance inputs")
    group_input = inputs["group"]
    if (
        not isinstance(group_input, dict)
        or group_input.get("sha256", "").lower() != accepted_sha
    ):
        _stale(group_id, "inputs.group", "does not bind the accepted copy")

    deterministic = evidence.get("deterministic")
    if not isinstance(deterministic, dict) or (
        deterministic.get("detector_version") != EXPECTED_DETECTOR_VERSION
        or deterministic.get("status") != "structural_pass"
        or deterministic.get("finding_count") != 0
    ):
        _stale(group_id, "deterministic", "does not record a clean pass")
    review = evidence.get("review")
    if not isinstance(review, dict) or (
        review.get("verdict") != "PASS"
        or review.get("non_author_attested") is not True
        or review.get("recorded_group_sha256", "").lower() != accepted_sha
    ):
        _stale(group_id, "review", "does not record an independent PASS")

    schema_path = accepted_path.parent.parent / "group-content.schema.json"
    schema_bytes = schema_path.read_bytes()
    return schema_bytes, _sha256(schema_bytes)


def _authoring_validator(
    schema_bytes: bytes,
) -> Draft202012Validator:
    schema = json.loads(schema_bytes)
    if not isinstance(schema, dict):
        raise TypeError("authoring schema must contain a JSON object")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_accepted_source_contracts(
    accepted_dir: Path,
    *,
    evidence_dir: Path,
    root: Path,
    verify_current_inputs: bool = True,
) -> tuple[SourceContract, ...]:
    """Load accepted G01..G28 contracts and fail closed otherwise.

    ``verify_current_inputs`` is deliberately strict by default for authoring QA.
    The real importer disables it only after a current global QA snapshot has bound
    every acceptance record and accepted copy by hash.
    """

    resolved_root = root.resolve()
    try:
        accepted_dir = _resolve_evidence_path(str(accepted_dir), resolved_root)
    except _EvidencePathOutsideRootError as error:
        raise Opc84dV2AssemblyError(
            f"accepted directory is outside explicit root: {accepted_dir}"
        ) from error
    try:
        evidence_dir = _resolve_evidence_path(str(evidence_dir), resolved_root)
    except _EvidencePathOutsideRootError as error:
        raise Opc84dV2AssemblyError(
            f"acceptance evidence directory is outside explicit root: {evidence_dir}"
        ) from error
    expected_evidence_dir = (accepted_dir.parent / "qa" / "accepted").resolve()
    if evidence_dir != expected_evidence_dir:
        raise Opc84dV2AssemblyError(
            "acceptance evidence directory is not the canonical "
            f"location: expected {expected_evidence_dir}, got {evidence_dir}"
        )

    _require_directory(accepted_dir, "accepted")
    _require_directory(evidence_dir, "acceptance evidence")
    try:
        paths = _exact_group_files(accepted_dir, "accepted")
        evidence_paths = _exact_group_files(
            evidence_dir,
            "acceptance evidence",
        )
    except OSError as error:
        raise Opc84dV2AssemblyError(
            f"cannot enumerate accepted corpus: {error}"
        ) from error

    seen_source_ids: dict[str, str] = {}
    seen_provider_ids: dict[tuple[str, str, str], str] = {}
    contracts: list[SourceContract] = []
    validators: dict[str, Draft202012Validator] = {}

    for group_id in EXPECTED_GROUP_IDS:
        try:
            path = _resolve_evidence_path(
                str(paths[f"{group_id}.json"]),
                resolved_root,
            )
            evidence_path = _resolve_evidence_path(
                str(evidence_paths[f"{group_id}.json"]),
                resolved_root,
            )
        except _EvidencePathOutsideRootError as error:
            raise Opc84dV2AssemblyError(
                f"accepted group {group_id} resolves outside explicit root"
            ) from error
        try:
            group, group_bytes = _read_json_object(
                path,
                f"accepted group {group_id}",
            )
            evidence, _ = _read_json_object(
                evidence_path,
                f"acceptance evidence {group_id}",
            )
            if verify_current_inputs:
                schema_bytes, schema_sha = _validate_acceptance_evidence(
                    evidence,
                    group_id=group_id,
                    accepted_path=path,
                    accepted_bytes=group_bytes,
                    root=resolved_root,
                )
            else:
                schema_bytes, schema_sha = _validate_globally_bound_acceptance_evidence(
                    evidence,
                    group_id=group_id,
                    accepted_path=path,
                    accepted_bytes=group_bytes,
                )
            validator = validators.get(schema_sha)
            if validator is None:
                validator = _authoring_validator(schema_bytes)
                validators[schema_sha] = validator
            try:
                validator.validate(group)
            except JsonSchemaValidationError as error:
                raise Opc84dV2AssemblyError(
                    f"{path.name} failed authoring schema validation: "
                    f"{error.message}"
                ) from error
        except Opc84dV2AssemblyError:
            raise
        except (
            AttributeError,
            IndexError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            JsonSchemaSchemaError,
            KeyError,
            TypeError,
        ) as error:
            raise Opc84dV2AssemblyError(
                f"cannot load accepted group {group_id}: {error}"
            ) from error

        try:
            declared_group_id = group["group_id"]
            if declared_group_id != group_id:
                raise Opc84dV2AssemblyError(
                    f"{path.name} declares group_id {declared_group_id}, "
                    f"expected {group_id}"
                )

            for family, source in _iter_authored_sources(group):
                source_id = source["source_id"]
                if previous := seen_source_ids.get(source_id):
                    raise Opc84dV2AssemblyError(
                        f"duplicate source_id {source_id!r}: "
                        f"{previous} and {group_id}"
                    )
                seen_source_ids[source_id] = group_id

                for provider_id in _iter_normalized_provider_ids(family, source):
                    provider_key = (family, source["provider"], provider_id)
                    if previous := seen_provider_ids.get(provider_key):
                        raise Opc84dV2AssemblyError(
                            "duplicate provider id "
                            f"{provider_id!r} for {family}/{source['provider']}: "
                            f"{previous} and {group_id}"
                        )
                    seen_provider_ids[provider_key] = group_id

            converted = convert_authored_group(group)
            for contract in converted:
                json.dumps(contract.metadata, ensure_ascii=False)
        except Opc84dV2AssemblyError:
            raise
        except (
            AttributeError,
            IndexError,
            KeyError,
            PydanticValidationError,
            TypeError,
            ValueError,
        ) as error:
            raise Opc84dV2AssemblyError(
                f"cannot convert accepted group {group_id}: {error}"
            ) from error
        contracts.extend(converted)

    return tuple(contracts)


def _validate_global_qa_evidence(experiment_root: Path) -> None:
    """Fail closed when the corpus-level acceptance snapshot is no longer current."""

    global_path = experiment_root / "qa" / "global.json"
    try:
        evidence, _ = _read_json_object(global_path, "global QA evidence")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
    ) as error:
        raise Opc84dV2AssemblyError(
            f"cannot load global QA evidence: {error}"
        ) from error

    if evidence.get("schema") != _GLOBAL_QA_SCHEMA:
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: schema is not the global-qa/v1 contract"
        )
    if evidence.get("status") != "global_pass":
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: status is not global_pass"
        )
    findings = evidence.get("findings")
    if not isinstance(findings, list) or findings:
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: findings is missing or non-empty"
        )

    input_hashes = evidence.get("input_hashes")
    if not isinstance(input_hashes, dict):
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: input_hashes is not an object"
        )
    acceptance_hashes = input_hashes.get("acceptance_evidence")
    group_hashes = input_hashes.get("accepted_groups")
    if not isinstance(acceptance_hashes, dict) or not isinstance(group_hashes, dict):
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: accepted hash inventories are missing"
        )
    expected = set(EXPECTED_GROUP_IDS)
    if set(acceptance_hashes) != expected or set(group_hashes) != expected:
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: accepted hash inventories do not cover "
            "exactly G01 through G28"
        )

    daily_beats = experiment_root / "daily-beats.json"
    recorded_daily_sha = input_hashes.get("daily_beats")
    if not isinstance(recorded_daily_sha, str) or recorded_daily_sha.lower() != _sha256(
        daily_beats.read_bytes()
    ):
        raise Opc84dV2AssemblyError(
            "global QA evidence is stale: daily_beats hash mismatch"
        )

    for group_id in EXPECTED_GROUP_IDS:
        expected_group_sha = group_hashes[group_id]
        expected_acceptance_sha = acceptance_hashes[group_id]
        if not isinstance(expected_group_sha, str) or not isinstance(
            expected_acceptance_sha, str
        ):
            raise Opc84dV2AssemblyError(
                f"global QA evidence is stale: {group_id} hash is not a string"
            )
        current_group_sha = _sha256(
            (experiment_root / "accepted" / f"{group_id}.json").read_bytes()
        )
        current_acceptance_sha = _sha256(
            (experiment_root / "qa" / "accepted" / f"{group_id}.json").read_bytes()
        )
        if expected_group_sha.lower() != current_group_sha:
            raise Opc84dV2AssemblyError(
                f"global QA evidence is stale: accepted_groups.{group_id} hash mismatch"
            )
        if expected_acceptance_sha.lower() != current_acceptance_sha:
            raise Opc84dV2AssemblyError(
                "global QA evidence is stale: "
                f"acceptance_evidence.{group_id} hash mismatch"
            )


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
            f"accepted group {group_id} does not have one shared group window"
        )
    try:
        window = json.loads(windows.pop())
        starts_on = date.fromisoformat(window["starts_on"])
        ends_on = date.fromisoformat(window["ends_on"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise Opc84dV2AssemblyError(
            f"accepted group {group_id} has an invalid group window"
        ) from error
    if ends_on < starts_on:
        raise Opc84dV2AssemblyError(
            f"accepted group {group_id} ends before it starts"
        )
    return starts_on, ends_on


def build_accepted_opc_84d_v2_dataset(
    *,
    project_root: Path,
) -> AcceptedOpc84dV2Dataset:
    """Assemble the real accepted corpus into 28 evidence-gated import batches."""

    project_root = project_root.resolve()
    experiment_root = project_root / "docs" / "experiments" / "opc-84d-v2"
    _validate_global_qa_evidence(experiment_root)
    contracts = load_accepted_source_contracts(
        experiment_root / "accepted",
        evidence_dir=experiment_root / "qa" / "accepted",
        root=project_root,
        verify_current_inputs=True,
    )
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
                f"accepted group {group_id} produced no source contracts"
            )
        starts_on, ends_on = _batch_window(group_id, group_contracts)
        if previous_end is not None and starts_on <= previous_end:
            raise Opc84dV2AssemblyError(
                f"accepted group {group_id} does not follow the prior batch in time"
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
