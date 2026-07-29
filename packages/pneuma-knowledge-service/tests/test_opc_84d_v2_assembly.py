from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_service.experiments import opc_84d_v2 as assembly
from pneuma_knowledge_service.experiments.opc_84d_v2 import (
    EXPECTED_GROUP_IDS,
    Opc84dV2AssemblyError,
    build_accepted_opc_84d_v2_dataset,
    convert_authored_group,
    load_accepted_source_contracts,
)


ROOT = Path(__file__).resolve().parents[3]
ACCEPTED = ROOT / "docs/experiments/opc-84d-v2/accepted"
AUTHORING_SCHEMA = ROOT / "docs/experiments/opc-84d-v2/group-content.schema.json"


def _accepted_group(group_id: str) -> dict[str, Any]:
    return json.loads((ACCEPTED / f"{group_id}.json").read_text(encoding="utf-8"))


def _payload(contract: Any) -> dict[str, Any]:
    return contract.model_dump(mode="json", by_alias=True)


def _contract_for_source(
    contracts: tuple[Any, ...], source_id: str
) -> Any:
    return next(
        contract
        for contract in contracts
        if contract.metadata["source_id"] == source_id
    )


def test_real_accepted_corpus_assembles_as_28_ordered_incremental_batches() -> None:
    dataset = build_accepted_opc_84d_v2_dataset(project_root=ROOT)

    assert [batch.batch_id for batch in dataset.batches] == list(
        EXPECTED_GROUP_IDS
    )
    assert len(dataset.batches) == 28
    assert sum(len(batch.contracts) for batch in dataset.batches) == 104
    assert all(batch.contracts for batch in dataset.batches)
    assert all(
        parse_source_contract(_payload(contract)) == contract
        for batch in dataset.batches
        for contract in batch.contracts
    )
    assert all(
        contract.metadata["group_id"] == batch.batch_id
        for batch in dataset.batches
        for contract in batch.contracts
    )
    assert all(
        previous.ends_on < current.starts_on
        for previous, current in zip(dataset.batches, dataset.batches[1:])
    )


def test_global_qa_hash_binding_rejects_tampered_acceptance_evidence(
    tmp_path: Path,
) -> None:
    source_root = ROOT / "docs" / "experiments" / "opc-84d-v2"
    experiment_root = tmp_path / "opc-84d-v2"
    shutil.copytree(source_root / "accepted", experiment_root / "accepted")
    shutil.copytree(
        source_root / "qa" / "accepted",
        experiment_root / "qa" / "accepted",
    )
    shutil.copy2(
        source_root / "qa" / "global.json",
        experiment_root / "qa" / "global.json",
    )
    shutil.copy2(source_root / "daily-beats.json", experiment_root)
    evidence_path = experiment_root / "qa" / "accepted" / "G01.json"
    evidence_path.write_bytes(evidence_path.read_bytes() + b" ")

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"global QA evidence is stale: acceptance_evidence\.G01 hash mismatch",
    ):
        assembly._validate_global_qa_evidence(experiment_root)


def test_existing_accepted_meeting_converts_without_losing_units_or_identity() -> None:
    group = _accepted_group("G02")
    authored = group["sources"]["meetings"][0]

    contract = _contract_for_source(
        convert_authored_group(group), authored["source_id"]
    )
    payload = _payload(contract)

    assert parse_source_contract(payload) == contract
    assert payload["schema"] == "pneuma.source.meeting/v1"
    assert payload["meeting_id"] == authored["meeting_id"]
    assert payload["agenda"] == [item["text"] for item in authored["agenda"]]
    assert [item["text"] for item in payload["segments"]] == [
        item["text"] for item in authored["utterances"]
    ]
    assert [item["segment_id"] for item in payload["segments"]] == [
        item["utterance_id"] for item in authored["utterances"]
    ]
    assert [item["email"] for item in payload["participants"]] == [
        item["synthetic_address"] for item in authored["participants"]
    ]
    assert payload["metadata"]["source_id"] == authored["source_id"]
    assert payload["metadata"]["authorship"] == authored["authorship"]
    assert payload["metadata"]["story_links"] == authored["authorship"]["links"]
    assert len(payload["metadata"]["agenda_items"]) == len(authored["agenda"])
    assert len(payload["metadata"]["segment_metadata"]) == len(
        authored["utterances"]
    )


def test_existing_accepted_documents_preserve_full_content_and_vault_fields() -> None:
    group = _accepted_group("G04")
    authored = group["sources"]["document_library"][0]

    contract = _contract_for_source(
        convert_authored_group(group), authored["source_id"]
    )
    payload = _payload(contract)

    assert parse_source_contract(payload) == contract
    assert payload["schema"] == "pneuma.source.document-library/v1"
    assert payload["library_id"] == authored["library_id"]
    assert len(payload["documents"]) == len(authored["documents"])
    for converted, original in zip(
        payload["documents"], authored["documents"], strict=True
    ):
        assert converted["document_id"] == original["document_id"]
        assert converted["content"] == original["full_markdown"]
        assert converted["frontmatter"] == original["frontmatter"]
        assert converted["tags"] == original["tags"]
        assert converted["created_at"] == original["created_at"]
        assert converted["modified_at"] == original["modified_at"]
        assert len(converted["links"]) == len(original["links"])
        assert converted["metadata"]["visible_blocks"] == original["visible_blocks"]
        assert converted["metadata"]["authored_links"] == original["links"]


def test_existing_accepted_im_preserves_users_messages_and_reactions() -> None:
    group = _accepted_group("G13")
    authored = group["sources"]["im"][0]

    contract = _contract_for_source(
        convert_authored_group(group), authored["source_id"]
    )
    payload = _payload(contract)

    assert parse_source_contract(payload) == contract
    assert payload["schema"] == "pneuma.source.im/v1"
    assert payload["archive_id"] == authored["archive_id"]
    assert len(payload["users"]) == len(authored["users"])
    assert len(payload["conversations"]) == len(authored["conversations"])
    assert sum(len(item["messages"]) for item in payload["conversations"]) == sum(
        len(item["messages"]) for item in authored["conversations"]
    )
    assert [
        message["text"]
        for conversation in payload["conversations"]
        for message in conversation["messages"]
    ] == [
        message["full_text"]
        for conversation in authored["conversations"]
        for message in conversation["messages"]
    ]
    assert sum(
        len(message["reactions"])
        for conversation in payload["conversations"]
        for message in conversation["messages"]
    ) == sum(
        len(message["reactions"])
        for conversation in authored["conversations"]
        for message in conversation["messages"]
    )
    assert [item["email"] for item in payload["users"]] == [
        item["synthetic_address"] for item in authored["users"]
    ]


def test_existing_accepted_email_preserves_body_headers_and_attachments() -> None:
    group = _accepted_group("G13")
    authored = group["sources"]["email"][0]

    contract = _contract_for_source(
        convert_authored_group(group), authored["source_id"]
    )
    payload = _payload(contract)

    assert parse_source_contract(payload) == contract
    assert payload["schema"] == "pneuma.source.email/v1"
    assert payload["archive_id"] == authored["archive_id"]
    assert len(payload["threads"]) == len(authored["threads"])
    assert sum(len(item["messages"]) for item in payload["threads"]) == sum(
        len(item["messages"]) for item in authored["threads"]
    )
    for converted_thread, original_thread in zip(
        payload["threads"], authored["threads"], strict=True
    ):
        for converted, original in zip(
            converted_thread["messages"], original_thread["messages"], strict=True
        ):
            assert converted["text"] == original["full_text"]
            assert converted["metadata"]["headers"] == original["headers"]
            assert len(converted["attachments"]) == len(original["attachments"])
            assert converted["metadata"]["authored_attachments"] == original[
                "attachments"
            ]


def test_group_conversion_is_one_for_one_and_stably_family_ordered() -> None:
    group = _accepted_group("G03")
    contracts = convert_authored_group(group)

    assert len(contracts) == sum(
        len(group["sources"][family])
        for family in ("meetings", "document_library", "im", "email")
    )
    assert [item.contract_schema for item in contracts] == [
        "pneuma.source.meeting/v1",
        "pneuma.source.document-library/v1",
        "pneuma.source.im/v1",
        "pneuma.source.email/v1",
    ]
    assert [item.metadata["source_id"] for item in contracts] == [
        source["source_id"]
        for family in ("meetings", "document_library", "im", "email")
        for source in group["sources"][family]
    ]


def _authorship(identity: str, group_id: str) -> dict[str, Any]:
    return {
        "authored_id": identity,
        "occurred_at": "2026-03-02T09:00:00+08:00",
        "author_role": "product",
        "content_class": "signal",
        "links": {
            "story_beat_ids": [f"D{int(group_id[1:]):02d}"],
            "fact_ids": [],
            "continuity_ids": [],
        },
    }


def _schema_shaped_group(group_id: str) -> dict[str, Any]:
    prefix = group_id.casefold()
    doc_authorship = _authorship(f"{prefix}-doc-auth", group_id)
    im_authorship = _authorship(f"{prefix}-im-auth", group_id)
    return {
        "schema": "pneuma.experiment.opc-84d-v2.group-content/v1",
        "group_id": group_id,
        "group_window": {
            "starts_on": "2026-03-02",
            "ends_on": "2026-03-03",
            "day_count": 2,
            "timezone": "Asia/Shanghai",
        },
        "story_scope": {
            "allowed_story_beat_ids": [f"D{int(group_id[1:]):02d}"],
            "known_fact_ids": [],
            "open_continuity_ids": [],
            "new_continuity_ids": [],
        },
        "research_context": [
            {
                "research_ref_id": f"{prefix}-research-01",
                "topic_query": "fixture source one",
                "url": "https://example.test/one",
                "title": "Fixture one",
                "accessed_on": "2026-07-29",
                "credibility": {"tier": "primary", "rationale": "test fixture"},
                "applicability_scope": "test fixture only",
                "author_fact_summaries": ["fixture fact"],
                "fictionalization_boundary": "no copied prose",
                "applied_authored_ids": [f"{prefix}-doc-block-auth"],
            },
            {
                "research_ref_id": f"{prefix}-research-02",
                "topic_query": "fixture source two",
                "url": "https://example.test/two",
                "title": "Fixture two",
                "accessed_on": "2026-07-29",
                "credibility": {"tier": "primary", "rationale": "test fixture"},
                "applicability_scope": "test fixture only",
                "author_fact_summaries": ["fixture fact"],
                "fictionalization_boundary": "no copied prose",
                "applied_authored_ids": [f"{prefix}-im-message-auth"],
            },
        ],
        "sources": {
            "meetings": [],
            "document_library": [
                {
                    "source_id": f"{prefix}-doc-source",
                    "authorship": doc_authorship,
                    "schema": "pneuma.source.document-library/v1",
                    "provider": "mock",
                    "library_id": f"{prefix}-library",
                    "title": f"{group_id} library",
                    "documents": [
                        {
                            "document_id": f"{prefix}-document",
                            "path": f"{prefix}/note.md",
                            "title": f"{group_id} note",
                            "frontmatter": {"group": group_id},
                            "full_markdown": f"# {group_id}\n\nBody.",
                            "tags": [prefix],
                            "links": [],
                            "created_at": "2026-03-02T09:00:00+08:00",
                            "modified_at": "2026-03-02T09:05:00+08:00",
                            "visible_blocks": [
                                {
                                    "block_id": f"{prefix}-doc-block",
                                    "kind": "paragraph",
                                    "markdown": "Body.",
                                    "authorship": _authorship(
                                        f"{prefix}-doc-block-auth", group_id
                                    ),
                                }
                            ],
                            "authorship": _authorship(
                                f"{prefix}-document-auth", group_id
                            ),
                        }
                    ],
                }
            ],
            "im": [
                {
                    "source_id": f"{prefix}-im-source",
                    "authorship": im_authorship,
                    "schema": "pneuma.source.im/v1",
                    "provider": "mock",
                    "archive_id": f"{prefix}-im-archive",
                    "owner_user_ids": [f"{prefix}-user"],
                    "users": [
                        {
                            "user_id": f"{prefix}-user",
                            "display_name": group_id,
                            "role": "product",
                            "synthetic_address": f"{prefix}@example.test",
                            "is_bot": False,
                        }
                    ],
                    "conversations": [
                        {
                            "conversation_id": f"{prefix}-conversation",
                            "conversation_type": "dm",
                            "title": f"{group_id} conversation",
                            "member_ids": [f"{prefix}-user"],
                            "messages": [
                                {
                                    "message_id": f"{prefix}-message",
                                    "sender_id": f"{prefix}-user",
                                    "sent_at": "2026-03-02T09:00:00+08:00",
                                    "full_text": f"{group_id} message",
                                    "thread_id": None,
                                    "edited_at": None,
                                    "reactions": [],
                                    "authorship": _authorship(
                                        f"{prefix}-im-message-auth", group_id
                                    ),
                                }
                            ],
                            "authorship": _authorship(
                                f"{prefix}-conversation-auth", group_id
                            ),
                        }
                    ],
                }
            ],
            "email": [],
        },
    }


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_exact_groups(directory: Path) -> None:
    root = directory.parent
    evidence_dir = root / "qa" / "accepted"
    groups_dir = root / "groups"
    deterministic_dir = root / "qa" / "deterministic"
    reviews_dir = root / "qa" / "reviews"
    directory.mkdir()
    evidence_dir.mkdir(parents=True)
    groups_dir.mkdir()
    deterministic_dir.mkdir()
    reviews_dir.mkdir()

    shared_inputs = {
        "daily_beats": root / "daily-beats.json",
        "schema": root / "group-content.schema.json",
        "qa_rubric": root / "qa-rubric.md",
        "story_bible": root / "story-bible.md",
    }
    shared_inputs["daily_beats"].write_text('{"days":[]}\n', encoding="utf-8")
    shared_inputs["schema"].write_bytes(AUTHORING_SCHEMA.read_bytes())
    shared_inputs["qa_rubric"].write_text("fixture rubric\n", encoding="utf-8")
    shared_inputs["story_bible"].write_text("fixture story\n", encoding="utf-8")

    for group_id in EXPECTED_GROUP_IDS:
        group_bytes = json.dumps(
            _schema_shaped_group(group_id), sort_keys=True
        ).encode("utf-8")
        accepted_path = directory / f"{group_id}.json"
        group_path = groups_dir / f"{group_id}.json"
        accepted_path.write_bytes(group_bytes)
        group_path.write_bytes(group_bytes)

        deterministic_path = deterministic_dir / f"{group_id}.json"
        deterministic_bytes = json.dumps(
            {
                "status": "structural_pass",
                "findings": [],
                "detector": {
                    "version": "opc-84d-v2-deterministic/3",
                },
                "groups": [{"group_id": group_id, "findings": []}],
            },
            sort_keys=True,
        ).encode("utf-8")
        deterministic_path.write_bytes(deterministic_bytes)
        review_path = reviews_dir / f"{group_id}.md"
        review_bytes = (
            f"# {group_id} independent review\n\n"
            "- Decision: **PASS**\n"
            "- Independence: **non-author independent reviewer**\n"
        ).encode("utf-8")
        review_path.write_bytes(review_bytes)

        inputs = {
            "group": group_path,
            "deterministic_report": deterministic_path,
            "independent_review": review_path,
            **shared_inputs,
        }
        evidence = {
            "schema": "pneuma.experiment.opc-84d-v2.acceptance/v1",
            "status": "accepted",
            "group_id": group_id,
            "group_sha256": _sha(group_bytes),
            "accepted_copy": {
                "path": str(accepted_path.relative_to(root)),
                "sha256": _sha(group_bytes),
                "byte_identical": True,
            },
            "deterministic": {
                "path": str(deterministic_path.relative_to(root)),
                "sha256": _sha(deterministic_bytes),
                "detector_version": "opc-84d-v2-deterministic/3",
                "status": "structural_pass",
                "finding_count": 0,
            },
            "review": {
                "path": str(review_path.relative_to(root)),
                "sha256": _sha(review_bytes),
                "verdict": "PASS",
                "non_author_attested": True,
                "recorded_group_sha256": _sha(group_bytes),
            },
            "inputs": {
                label: {
                    "path": str(path.relative_to(root)),
                    "sha256": _sha(path.read_bytes()),
                }
                for label, path in inputs.items()
            },
        }
        (evidence_dir / f"{group_id}.json").write_text(
            json.dumps(evidence, sort_keys=True),
            encoding="utf-8",
        )


def _evidence_dir(accepted: Path) -> Path:
    return accepted.parent / "qa" / "accepted"


def _load(accepted: Path) -> tuple[Any, ...]:
    return load_accepted_source_contracts(
        accepted,
        evidence_dir=_evidence_dir(accepted),
        root=accepted.parent,
    )


def _refresh_group_acceptance(
    accepted: Path,
    group_id: str,
    group: dict[str, Any],
) -> None:
    group_bytes = json.dumps(group, sort_keys=True).encode("utf-8")
    accepted_path = accepted / f"{group_id}.json"
    group_path = accepted.parent / "groups" / f"{group_id}.json"
    accepted_path.write_bytes(group_bytes)
    group_path.write_bytes(group_bytes)
    evidence_path = _evidence_dir(accepted) / f"{group_id}.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    group_sha = _sha(group_bytes)
    evidence["group_sha256"] = group_sha
    evidence["accepted_copy"]["sha256"] = group_sha
    evidence["review"]["recorded_group_sha256"] = group_sha
    evidence["inputs"]["group"]["sha256"] = group_sha
    evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")


def _rewrite_evidence(
    accepted: Path,
    group_id: str,
    update: Any,
) -> None:
    evidence_path = _evidence_dir(accepted) / f"{group_id}.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    update(evidence)
    evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")


def test_loader_requires_the_exact_g01_through_g28_file_set(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    (accepted / "G28.json").unlink()
    (accepted / "G29.json").write_text(
        json.dumps(_schema_shaped_group("G29")), encoding="utf-8"
    )

    with pytest.raises(
        Opc84dV2AssemblyError, match=r"missing=.*G28.*unexpected=.*G29"
    ):
        _load(accepted)


def test_loader_builds_complete_corpus_in_group_and_family_order(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)

    contracts = _load(accepted)

    assert len(contracts) == 56
    assert [item.metadata["source_id"] for item in contracts] == [
        source_id
        for group_id in EXPECTED_GROUP_IDS
        for source_id in (
            f"{group_id.casefold()}-doc-source",
            f"{group_id.casefold()}-im-source",
        )
    ]
    assert all(parse_source_contract(_payload(item)) == item for item in contracts)
    assert all(
        json.loads(json.dumps(item.metadata)) == item.metadata
        for item in contracts
    )


def test_loader_rejects_duplicate_global_source_ids(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    second_path = accepted / "G02.json"
    second = json.loads(second_path.read_text(encoding="utf-8"))
    first_source = _schema_shaped_group("G01")["sources"]["document_library"][0]
    second["sources"]["document_library"][0]["source_id"] = first_source[
        "source_id"
    ]
    _refresh_group_acceptance(accepted, "G02", second)

    with pytest.raises(Opc84dV2AssemblyError, match="duplicate source_id"):
        _load(accepted)


def test_loader_rejects_duplicate_normalized_provider_unit_ids(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    first_source = _schema_shaped_group("G01")["sources"]["document_library"][0]
    second = json.loads((accepted / "G02.json").read_text(encoding="utf-8"))
    second_source = second["sources"]["document_library"][0]
    second_source["library_id"] = first_source["library_id"]
    second_source["documents"][0]["document_id"] = first_source["documents"][0][
        "document_id"
    ]
    _refresh_group_acceptance(accepted, "G02", second)

    with pytest.raises(Opc84dV2AssemblyError, match="duplicate provider id"):
        _load(accepted)


def test_loader_allows_one_document_library_across_disjoint_contracts(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    first_source = _schema_shaped_group("G01")["sources"]["document_library"][0]
    second = json.loads((accepted / "G02.json").read_text(encoding="utf-8"))
    second["sources"]["document_library"][0]["library_id"] = first_source[
        "library_id"
    ]
    _refresh_group_acceptance(accepted, "G02", second)

    assert len(_load(accepted)) == 56


@pytest.mark.parametrize(
    ("family", "source", "expected"),
    [
        (
            "meetings",
            {"meeting_id": "meeting-1"},
            ["meeting-1"],
        ),
        (
            "document_library",
            {
                "library_id": "vault-1",
                "documents": [
                    {"document_id": "note-1"},
                    {"document_id": "note-2"},
                ],
            },
            ["vault-1:note-1", "vault-1:note-2"],
        ),
        (
            "im",
            {
                "archive_id": "chat-1",
                "conversations": [
                    {"conversation_id": "channel-1"},
                    {"conversation_id": "dm-1"},
                ],
            },
            ["chat-1:channel-1", "chat-1:dm-1"],
        ),
        (
            "email",
            {
                "archive_id": "mail-1",
                "threads": [
                    {"thread_id": "thread-1"},
                    {"thread_id": "thread-2"},
                ],
            },
            ["mail-1:thread-1", "mail-1:thread-2"],
        ),
    ],
)
def test_provider_identity_matches_each_official_normalizer_unit(
    family: str,
    source: dict[str, Any],
    expected: list[str],
) -> None:
    assert list(assembly._iter_normalized_provider_ids(family, source)) == expected


def test_loader_scopes_provider_ids_by_family_and_provider(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    first = json.loads((accepted / "G01.json").read_text(encoding="utf-8"))
    shared_id = first["sources"]["document_library"][0]["library_id"]
    first["sources"]["im"][0]["archive_id"] = shared_id
    _refresh_group_acceptance(accepted, "G01", first)

    second = json.loads((accepted / "G02.json").read_text(encoding="utf-8"))
    second["sources"]["document_library"][0]["provider"] = "obsidian"
    second["sources"]["document_library"][0]["library_id"] = shared_id
    _refresh_group_acceptance(accepted, "G02", second)

    assert len(_load(accepted)) == 56


def test_loader_rejects_a_group_id_that_disagrees_with_its_filename(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    path = accepted / "G02.json"
    group = deepcopy(json.loads(path.read_text(encoding="utf-8")))
    group["group_id"] = "G01"
    _refresh_group_acceptance(accepted, "G02", group)

    with pytest.raises(Opc84dV2AssemblyError, match="G02.json declares group_id G01"):
        _load(accepted)


@pytest.mark.parametrize(
    "input_label",
    [
        "group",
        "deterministic_report",
        "independent_review",
        "daily_beats",
        "schema",
        "qa_rubric",
        "story_bible",
    ],
)
def test_loader_rejects_stale_acceptance_dependency(
    tmp_path: Path,
    input_label: str,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    evidence = json.loads(
        (_evidence_dir(accepted) / "G01.json").read_text(encoding="utf-8")
    )
    dependency = tmp_path / evidence["inputs"][input_label]["path"]
    dependency.write_bytes(dependency.read_bytes() + b"\n")

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=rf"G01 acceptance evidence is stale.*{input_label}",
    ):
        _load(accepted)


def test_loader_rejects_an_accepted_copy_changed_after_acceptance(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    accepted_path = accepted / "G01.json"
    accepted_path.write_bytes(accepted_path.read_bytes() + b"\n")

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"G01 acceptance evidence is stale.*accepted_copy.sha256",
    ):
        _load(accepted)


def test_loader_rejects_acceptance_bound_to_an_obsolete_detector(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    deterministic_path = tmp_path / "qa" / "deterministic" / "G01.json"
    report = json.loads(deterministic_path.read_text(encoding="utf-8"))
    report["detector"]["version"] = "opc-84d-v2-deterministic/2"
    deterministic_path.write_text(
        json.dumps(report, sort_keys=True),
        encoding="utf-8",
    )

    def bind_obsolete_detector(evidence: dict[str, Any]) -> None:
        deterministic_sha = _sha(deterministic_path.read_bytes())
        evidence["inputs"]["deterministic_report"]["sha256"] = deterministic_sha
        evidence["deterministic"]["sha256"] = deterministic_sha
        evidence["deterministic"]["detector_version"] = (
            "opc-84d-v2-deterministic/2"
        )

    _rewrite_evidence(accepted, "G01", bind_obsolete_detector)

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"G01 acceptance evidence is stale.*detector",
    ):
        _load(accepted)


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "parent_relative", "symlink", "wrong_internal_location"],
)
def test_loader_rejects_untrusted_or_noncanonical_evidence_input_paths(
    tmp_path: Path,
    path_kind: str,
) -> None:
    experiment_root = tmp_path / "experiment"
    experiment_root.mkdir()
    accepted = experiment_root / "accepted"
    _write_exact_groups(accepted)
    canonical_schema = experiment_root / "group-content.schema.json"

    if path_kind == "wrong_internal_location":
        substitute = experiment_root / "substitute-schema.json"
        substitute.write_bytes(canonical_schema.read_bytes())
        raw_path = substitute.name
    else:
        substitute = tmp_path / "outside-schema.json"
        substitute.write_bytes(canonical_schema.read_bytes())
        if path_kind == "absolute":
            raw_path = str(substitute)
        elif path_kind == "parent_relative":
            raw_path = "../outside-schema.json"
        else:
            link = experiment_root / "schema-link.json"
            link.symlink_to(substitute)
            raw_path = link.name

    def replace_schema_snapshot(evidence: dict[str, Any]) -> None:
        evidence["inputs"]["schema"] = {
            "path": raw_path,
            "sha256": _sha(substitute.read_bytes()),
        }

    _rewrite_evidence(accepted, "G01", replace_schema_snapshot)

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"G01 acceptance evidence is stale.*schema.*path",
    ):
        _load(accepted)


def test_loader_rejects_an_accepted_copy_outside_the_explicit_root(
    tmp_path: Path,
) -> None:
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    accepted = outside_root / "accepted"
    _write_exact_groups(accepted)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    for group_id in EXPECTED_GROUP_IDS:
        evidence_path = _evidence_dir(accepted) / f"{group_id}.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        for snapshot in evidence["inputs"].values():
            path = Path(snapshot["path"])
            snapshot["path"] = str(
                path if path.is_absolute() else outside_root / path
            )
        for section in ("accepted_copy", "deterministic", "review"):
            path = Path(evidence[section]["path"])
            evidence[section]["path"] = str(
                path if path.is_absolute() else outside_root / path
            )
        evidence_path.write_text(
            json.dumps(evidence, sort_keys=True),
            encoding="utf-8",
        )

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"accepted directory.*outside explicit root",
    ):
        load_accepted_source_contracts(
            accepted,
            evidence_dir=_evidence_dir(accepted),
            root=trusted_root,
        )


def test_loader_validates_authoring_schema_before_conversion(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    group = json.loads((accepted / "G01.json").read_text(encoding="utf-8"))
    del group["research_context"]
    _refresh_group_acceptance(accepted, "G01", group)

    with pytest.raises(
        Opc84dV2AssemblyError,
        match=r"G01.json failed authoring schema validation",
    ) as raised:
        _load(accepted)

    assert isinstance(raised.value.__cause__, JsonSchemaValidationError)


@pytest.mark.parametrize(
    ("target", "cause_type"),
    [
        ("accepted_json", json.JSONDecodeError),
        ("evidence_json", json.JSONDecodeError),
        ("converter_key", KeyError),
        ("provider_contract", PydanticValidationError),
    ],
)
def test_loader_wraps_input_and_conversion_failures_with_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    cause_type: type[BaseException],
) -> None:
    accepted = tmp_path / "accepted"
    _write_exact_groups(accepted)
    if target == "accepted_json":
        (accepted / "G01.json").write_text("{", encoding="utf-8")
    elif target == "evidence_json":
        (_evidence_dir(accepted) / "G01.json").write_text("{", encoding="utf-8")
    elif target == "converter_key":
        monkeypatch.setitem(
            assembly._CONVERTERS,
            "document_library",
            lambda group, source: source["missing"],
        )
    else:
        validation_error = PydanticValidationError.from_exception_data(
            "SourceContract",
            [
                {
                    "type": "missing",
                    "loc": ("provider",),
                    "input": {},
                }
            ],
        )

        def invalid_contract(payload: dict[str, Any]) -> Any:
            raise validation_error

        monkeypatch.setattr(assembly, "parse_source_contract", invalid_contract)

    with pytest.raises(Opc84dV2AssemblyError) as raised:
        _load(accepted)

    assert isinstance(raised.value.__cause__, cause_type)


@pytest.mark.parametrize("missing", ["accepted", "evidence"])
def test_loader_wraps_missing_directories_with_cause(
    tmp_path: Path,
    missing: str,
) -> None:
    accepted = tmp_path / "accepted"
    if missing == "evidence":
        accepted.mkdir()

    with pytest.raises(Opc84dV2AssemblyError) as raised:
        load_accepted_source_contracts(
            accepted,
            evidence_dir=_evidence_dir(accepted),
            root=tmp_path,
        )

    assert isinstance(raised.value.__cause__, FileNotFoundError)
