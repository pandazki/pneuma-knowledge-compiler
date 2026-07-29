from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_service.experiments.opc_84d import build_opc_84d_dataset


def _stable_bytes(dataset) -> bytes:
    return json.dumps(
        dataset.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _normalized_visible_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _template_shape(text: str) -> str:
    """Mask incidental coordinates while retaining the actual language shape."""

    normalized = _normalized_visible_text(text).lower()
    normalized = re.sub(r"https?://\S+", "<url>", normalized)
    normalized = re.sub(r"[\w.+-]+@[\w.-]+", "<email>", normalized)
    normalized = re.sub(r"「[^」]*」", "「<topic>」", normalized)
    normalized = re.sub(
        r"\b(?:b|week|evt|doc|rf|im|mail)[-_]?\d[\w.-]*\b",
        "<id>",
        normalized,
    )
    return re.sub(r"\d+(?:[.:/-]\d+)*", "<n>", normalized)


def _visible_fragments(dataset) -> dict[str, list[str]]:
    fragments: dict[str, list[str]] = defaultdict(list)
    for batch in dataset.batches:
        for contract in batch.contracts:
            schema = contract["schema"]
            if schema == "pneuma.source.meeting/v1":
                fragments["meeting"].extend(
                    segment["text"] for segment in contract["segments"]
                )
            elif schema == "pneuma.source.document-library/v1":
                for document in contract["documents"]:
                    fragments["document_library"].extend(
                        paragraph
                        for paragraph in re.split(
                            r"\n\s*\n", document["content"]
                        )
                        if _normalized_visible_text(paragraph)
                    )
            elif schema == "pneuma.source.im/v1":
                for conversation in contract["conversations"]:
                    fragments["im"].extend(
                        message["text"] for message in conversation["messages"]
                    )
            elif schema == "pneuma.source.email/v1":
                for thread in contract["threads"]:
                    for message in thread["messages"]:
                        paragraphs = [
                            paragraph
                            for paragraph in re.split(r"\n\s*\n", message["text"])
                            if _normalized_visible_text(paragraph)
                        ]
                        assert len(paragraphs) == len(
                            {_normalized_visible_text(item) for item in paragraphs}
                        ), (
                            "one synthetic email repeats a paragraph byte-for-byte; "
                            f"message_id={message['message_id']}"
                        )
                        fragments["email"].extend(paragraphs)
    return fragments


def _duplicate_excess_ratio(
    values: list[str], *, normalizer=_normalized_visible_text
) -> float:
    counts = Counter(normalizer(value) for value in values)
    return sum(count - 1 for count in counts.values()) / len(values)


def test_opc_84d_dataset_is_deterministic_and_contract_valid() -> None:
    left = build_opc_84d_dataset(seed=20260729)
    right = build_opc_84d_dataset(seed=20260729)

    assert hashlib.sha256(_stable_bytes(left)).digest() == hashlib.sha256(
        _stable_bytes(right)
    ).digest()
    assert len(left.batches) == 12
    for batch in left.batches:
        assert len({item["schema"] for item in batch.contracts}) >= 2
        for contract in batch.contracts:
            parse_source_contract(contract)

    schemas = [
        item["schema"]
        for batch in left.batches
        for item in batch.contracts
    ]
    assert set(schemas) == {
        "pneuma.source.meeting/v1",
        "pneuma.source.document-library/v1",
        "pneuma.source.im/v1",
        "pneuma.source.email/v1",
    }
    for first, second in zip(left.batches, left.batches[1:]):
        assert {
            item["schema"] for batch in (first, second) for item in batch.contracts
        } == set(schemas)


def test_opc_84d_manifest_meets_scale_and_story_contract() -> None:
    dataset = build_opc_84d_dataset()
    manifest = dataset.manifest
    stats = manifest["stats"]

    started = datetime.fromisoformat(manifest["started_at"])
    ended = datetime.fromisoformat(manifest["ended_at"])
    assert (ended.date() - started.date()).days + 1 >= 84
    assert stats["event_count"] >= 144
    assert stats["normalized_source_units"] >= 80
    assert 200_000 <= stats["source_chars"] <= 700_000

    events = manifest["events"]
    assert len(events) == stats["event_count"]
    assert len({item["event_id"] for item in events}) == len(events)
    assert {"main", "open_source", "growth", "operations", "personal"} <= {
        item["thread"] for item in events
    }
    assert all(item["batch_id"] in {batch.batch_id for batch in dataset.batches} for item in events)


def test_opc_84d_has_long_meetings_and_rich_four_source_volume() -> None:
    dataset = build_opc_84d_dataset()
    meetings: list[dict] = []
    documents: list[dict] = []
    conversations: list[dict] = []
    threads: list[dict] = []

    for batch in dataset.batches:
        for contract in batch.contracts:
            if contract["schema"] == "pneuma.source.meeting/v1":
                meetings.append(contract)
            elif contract["schema"] == "pneuma.source.document-library/v1":
                documents.extend(contract["documents"])
            elif contract["schema"] == "pneuma.source.im/v1":
                conversations.extend(contract["conversations"])
            elif contract["schema"] == "pneuma.source.email/v1":
                threads.extend(contract["threads"])

    assert len(meetings) >= 14
    assert sum(len(item["segments"]) >= 60 for item in meetings) >= 8
    assert max(len(item["segments"]) for item in meetings) >= 120
    assert len(documents) >= 32
    assert len(conversations) >= 16
    assert sum(len(item["messages"]) for item in conversations) >= 700
    assert len(threads) >= 16
    assert sum(len(item["messages"]) for item in threads) >= 90


def test_opc_84d_noise_is_natural_and_dominant_in_every_source() -> None:
    manifest = build_opc_84d_dataset().manifest
    atoms = manifest["atoms"]
    assert atoms
    assert sum(item["is_noise"] for item in atoms) / len(atoms) >= 0.60
    assert (
        sum(item["char_count"] for item in atoms if item["is_noise"])
        / sum(item["char_count"] for item in atoms)
        >= 0.52
    )

    per_source: dict[str, list[dict]] = defaultdict(list)
    for item in atoms:
        per_source[item["source_type"]].append(item)
    assert set(per_source) == {"meeting", "document_library", "im", "email"}
    for source_atoms in per_source.values():
        assert sum(item["is_noise"] for item in source_atoms) / len(source_atoms) >= 0.45

    noise_types = Counter(
        item["noise_type"] for item in atoms if item["is_noise"]
    )
    assert len(noise_types) >= 16
    assert all(count >= 2 for count in noise_types.values())
    assert all(item["char_count"] > 0 for item in atoms)


def test_opc_84d_visible_sources_do_not_use_repetition_as_volume() -> None:
    dataset = build_opc_84d_dataset()
    fragments = _visible_fragments(dataset)
    assert set(fragments) == {"meeting", "document_library", "im", "email"}
    reported = dataset.manifest["stats"]["visible_repetition"]
    assert set(reported) == set(fragments)

    exact_limits = {
        "meeting": 0.08,
        "document_library": 0.18,
        "im": 0.08,
        "email": 0.25,
    }
    template_limits = {
        "meeting": 0.20,
        "document_library": 0.30,
        "im": 0.20,
        "email": 0.40,
    }
    for source_type, values in fragments.items():
        exact_ratio = _duplicate_excess_ratio(values)
        template_ratio = _duplicate_excess_ratio(
            values, normalizer=_template_shape
        )
        prose_values = (
            [
                value
                for value in values
                if not _normalized_visible_text(value).startswith("#")
                and not _normalized_visible_text(value).lower().startswith("tags:")
            ]
            if source_type == "document_library"
            else values
        )
        prose_exact_ratio = _duplicate_excess_ratio(prose_values)
        prose_template_ratio = _duplicate_excess_ratio(
            prose_values, normalizer=_template_shape
        )
        assert reported[source_type]["fragments"] == len(values)
        assert reported[source_type]["prose_fragments"] == len(prose_values)
        assert (
            reported[source_type]["exact_duplicate_excess_ratio"]
            == exact_ratio
        )
        assert (
            reported[source_type]["template_duplicate_excess_ratio"]
            == template_ratio
        )
        assert (
            reported[source_type]["prose_exact_duplicate_excess_ratio"]
            == prose_exact_ratio
        )
        assert (
            reported[source_type]["prose_template_duplicate_excess_ratio"]
            == prose_template_ratio
        )
        assert prose_exact_ratio <= 0.03
        assert prose_template_ratio <= 0.05
        assert exact_ratio <= exact_limits[source_type], (
            f"{source_type} exact duplicate excess {exact_ratio:.2%} exceeds "
            f"{exact_limits[source_type]:.0%}"
        )
        assert template_ratio <= template_limits[source_type], (
            f"{source_type} template duplicate excess {template_ratio:.2%} exceeds "
            f"{template_limits[source_type]:.0%}"
        )


def test_opc_84d_truth_set_exercises_cross_source_and_time() -> None:
    truth = build_opc_84d_dataset().manifest["truth"]
    assert len(truth["durable_facts"]) >= 30
    assert len(truth["decisions"]) >= 24
    assert len(truth["commitments"]) >= 24
    assert len(truth["constraints"]) >= 16
    assert len(truth["supersessions"]) >= 12
    assert len(truth["negative_controls"]) >= 30
    assert len(truth["retrieval_cases"]) >= 36
    assert sum(item.get("as_of") is not None for item in truth["retrieval_cases"]) >= 12

    signals = [
        *truth["durable_facts"],
        *truth["decisions"],
        *truth["commitments"],
        *truth["constraints"],
    ]
    assert sum(len(set(item["source_types"])) >= 2 for item in signals) >= 24
    signal_ids = {item["truth_id"] for item in signals}
    for item in truth["supersessions"]:
        assert item["before_truth_id"] in signal_ids
        assert item["after_truth_id"] in signal_ids


def test_every_manifest_atom_points_to_real_contract_content() -> None:
    dataset = build_opc_84d_dataset()
    actual_refs: dict[str, int] = {}
    for batch in dataset.batches:
        for contract in batch.contracts:
            schema = contract["schema"]
            if schema == "pneuma.source.meeting/v1":
                for segment in contract["segments"]:
                    actual_refs[f"meeting:{segment['segment_id']}"] = len(segment["text"])
            elif schema == "pneuma.source.document-library/v1":
                for document in contract["documents"]:
                    actual_refs[f"document_library:{document['document_id']}"] = len(
                        document["content"]
                    )
            elif schema == "pneuma.source.im/v1":
                for conversation in contract["conversations"]:
                    for message in conversation["messages"]:
                        actual_refs[f"im:{message['message_id']}"] = len(message["text"])
            elif schema == "pneuma.source.email/v1":
                for thread in contract["threads"]:
                    for message in thread["messages"]:
                        actual_refs[f"email:{message['message_id']}"] = len(message["text"])

    atoms = dataset.manifest["atoms"]
    assert len(atoms) == len(actual_refs)
    assert {item["source_ref"] for item in atoms} == set(actual_refs)
    for item in atoms:
        assert item["char_count"] == actual_refs[item["source_ref"]]
