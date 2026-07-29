from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "validate_opc_84d_v2_global.py"
BEATS = ROOT / "docs" / "experiments" / "opc-84d-v2" / "daily-beats.json"
EXPECTED_GROUP_IDS = tuple(f"G{index:02d}" for index in range(1, 29))
EXPECTED_SOURCE_COUNTS = {
    "meeting": 18,
    "document_library": 35,
    "im": 30,
    "email": 21,
}


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "opc_84d_v2_global_validator",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(prefix: str, minimum: int) -> str:
    words: list[str] = []
    index = 0
    while len(" ".join(words)) < minimum:
        words.append(f"{prefix}word{index:03d}")
        index += 1
    return " ".join(words)


def _authored(
    identity: str,
    occurred_at: str,
    content_class: str = "signal",
) -> dict:
    return {
        "authored_id": identity,
        "occurred_at": occurred_at,
        "author_role": "product",
        "content_class": content_class,
        "links": {
            "story_beat_ids": [],
            "fact_ids": [],
            "continuity_ids": [],
        },
    }


def _meeting_sources(
    group_id: str,
    count: int,
    occurred_at: str,
) -> list[dict]:
    sources = []
    for source_index in range(count):
        utterances = []
        for unit_index in range(source_index, 15, count):
            prefix = f"{group_id}meeting{unit_index:02d}"
            utterances.append(
                {
                    "utterance_id": f"{prefix}-utterance",
                    "speaker_id": (
                        f"{group_id}-speaker-a"
                        if unit_index % 2
                        else f"{group_id}-speaker-b"
                    ),
                    "started_at": occurred_at,
                    "ended_at": occurred_at,
                    "text": _text(prefix, 110),
                    "overlap": False,
                    "authorship": _authored(
                        f"{prefix}-auth",
                        occurred_at,
                        "noise" if unit_index % 5 == 4 else "signal",
                    ),
                }
            )
        source_prefix = f"{group_id}-meeting-source-{source_index:02d}"
        sources.append(
            {
                "source_id": source_prefix,
                "schema": "pneuma.source.meeting/v1",
                "provider": "mock",
                "meeting_id": f"{source_prefix}-provider",
                "title": source_prefix,
                "started_at": occurred_at,
                "ended_at": occurred_at,
                "timezone": "Asia/Shanghai",
                "owner_participant_ids": [f"{group_id}-speaker-a"],
                "participants": [
                    {
                        "participant_id": f"{group_id}-speaker-a",
                        "display_name": "A",
                        "role": "product",
                        "synthetic_address": f"{group_id.lower()}-a@example.test",
                    },
                    {
                        "participant_id": f"{group_id}-speaker-b",
                        "display_name": "B",
                        "role": "operations",
                        "synthetic_address": f"{group_id.lower()}-b@example.test",
                    },
                ],
                "agenda": [],
                "utterances": utterances,
                "authorship": _authored(
                    f"{source_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    return sources


def _document_sources(
    group_id: str,
    count: int,
    occurred_at: str,
) -> list[dict]:
    document_count = max(2, count)
    documents: list[dict] = []
    for document_index in range(document_count):
        blocks = []
        for unit_index in range(document_index, 10, document_count):
            prefix = f"{group_id}document{unit_index:02d}"
            markdown = _text(prefix, 230)
            blocks.append(
                {
                    "block_id": f"{prefix}-block",
                    "kind": "paragraph",
                    "markdown": markdown,
                    "authorship": _authored(
                        f"{prefix}-auth",
                        occurred_at,
                        "noise" if unit_index % 5 == 4 else "signal",
                    ),
                }
            )
        document_prefix = f"{group_id}-document-{document_index:02d}"
        documents.append(
            {
                "document_id": document_prefix,
                "path": f"{group_id.lower()}/{document_index:02d}.md",
                "title": document_prefix,
                "frontmatter": {},
                "tags": [],
                "links": [],
                "created_at": occurred_at,
                "modified_at": occurred_at,
                "full_markdown": "\n\n".join(
                    ["# Fixture", *(block["markdown"] for block in blocks)]
                ),
                "visible_blocks": blocks,
                "authorship": _authored(
                    f"{document_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    sources = []
    for source_index in range(count):
        source_prefix = f"{group_id}-document-source-{source_index:02d}"
        sources.append(
            {
                "source_id": source_prefix,
                "schema": "pneuma.source.document-library/v1",
                "provider": "mock",
                "library_id": f"{source_prefix}-provider",
                "title": source_prefix,
                "documents": documents[source_index::count],
                "authorship": _authored(
                    f"{source_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    return sources


def _im_sources(
    group_id: str,
    count: int,
    occurred_at: str,
) -> list[dict]:
    conversation_count = max(2, count)
    conversations: list[dict] = []
    users = [
        {
            "user_id": f"{group_id}-im-user-{index}",
            "display_name": f"User {index}",
            "role": "product",
            "synthetic_address": (
                f"{group_id.lower()}-im-{index}@example.test"
            ),
            "is_bot": False,
        }
        for index in range(3)
    ]
    for conversation_index in range(conversation_count):
        messages = []
        for unit_index in range(conversation_index, 20, conversation_count):
            prefix = f"{group_id}im{unit_index:02d}"
            messages.append(
                {
                    "message_id": f"{prefix}-message",
                    "sender_id": users[unit_index % 3]["user_id"],
                    "sent_at": occurred_at,
                    "full_text": _text(prefix, 110),
                    "thread_id": None,
                    "edited_at": None,
                    "reactions": [],
                    "authorship": _authored(
                        f"{prefix}-auth",
                        occurred_at,
                        "noise" if unit_index % 5 == 4 else "signal",
                    ),
                }
            )
        conversation_prefix = (
            f"{group_id}-conversation-{conversation_index:02d}"
        )
        conversations.append(
            {
                "conversation_id": conversation_prefix,
                "conversation_type": "channel",
                "title": conversation_prefix,
                "member_ids": [user["user_id"] for user in users],
                "messages": messages,
                "authorship": _authored(
                    f"{conversation_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    sources = []
    for source_index in range(count):
        source_prefix = f"{group_id}-im-source-{source_index:02d}"
        sources.append(
            {
                "source_id": source_prefix,
                "schema": "pneuma.source.im/v1",
                "provider": "mock",
                "archive_id": f"{source_prefix}-provider",
                "owner_user_ids": [users[0]["user_id"]],
                "users": users,
                "conversations": conversations[source_index::count],
                "authorship": _authored(
                    f"{source_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    return sources


def _email_sources(
    group_id: str,
    count: int,
    occurred_at: str,
) -> list[dict]:
    thread_count = max(2, count)
    threads: list[dict] = []
    for thread_index in range(thread_count):
        messages = []
        for unit_index in range(thread_index, 5, thread_count):
            prefix = f"{group_id}email{unit_index:02d}"
            messages.append(
                {
                    "message_id": f"{prefix}-message",
                    "sent_at": occurred_at,
                    "from": f"{group_id.lower()}-from@example.test",
                    "to": [f"{group_id.lower()}-to@example.test"],
                    "cc": [f"{group_id.lower()}-cc@example.test"],
                    "subject": prefix,
                    "headers": {},
                    "full_text": _text(prefix, 260),
                    "in_reply_to": None,
                    "references": [],
                    "attachments": [],
                    "authorship": _authored(
                        f"{prefix}-auth",
                        occurred_at,
                        "noise" if unit_index % 5 == 4 else "signal",
                    ),
                }
            )
        thread_prefix = f"{group_id}-email-thread-{thread_index:02d}"
        threads.append(
            {
                "thread_id": thread_prefix,
                "subject": thread_prefix,
                "messages": messages,
                "authorship": _authored(
                    f"{thread_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    sources = []
    for source_index in range(count):
        source_prefix = f"{group_id}-email-source-{source_index:02d}"
        sources.append(
            {
                "source_id": source_prefix,
                "schema": "pneuma.source.email/v1",
                "provider": "mock",
                "archive_id": f"{source_prefix}-provider",
                "owner_addresses": [
                    f"{group_id.lower()}-from@example.test"
                ],
                "threads": threads[source_index::count],
                "authorship": _authored(
                    f"{source_prefix}-auth",
                    occurred_at,
                ),
            }
        )
    return sources


def _group(group_id: str, days: list[dict]) -> dict:
    counts = Counter(
        str(source["type"]).casefold()
        for day in days
        for source in day["source_plan"]
    )
    starts_on = days[0]["date"]
    ends_on = days[-1]["date"]
    occurred_at = f"{starts_on}T09:00:00+08:00"
    return {
        "schema": "pneuma.experiment.opc-84d-v2.group-content/v1",
        "group_id": group_id,
        "group_window": {
            "starts_on": starts_on,
            "ends_on": ends_on,
            "day_count": len(days),
            "timezone": "Asia/Shanghai",
        },
        "story_scope": {
            "allowed_story_beat_ids": [],
            "known_fact_ids": [],
            "open_continuity_ids": [],
            "new_continuity_ids": [],
        },
        "research_context": [],
        "sources": {
            "meetings": _meeting_sources(
                group_id,
                counts["meeting"],
                occurred_at,
            ),
            "document_library": _document_sources(
                group_id,
                counts["document_library"],
                occurred_at,
            ),
            "im": _im_sources(
                group_id,
                counts["im"],
                occurred_at,
            ),
            "email": _email_sources(
                group_id,
                counts["email"],
                occurred_at,
            ),
        },
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    experiment = tmp_path / "experiment"
    paths = {
        "experiment": experiment,
        "accepted": experiment / "accepted",
        "evidence": experiment / "qa" / "accepted",
        "beats": experiment / "daily-beats.json",
        "schema": experiment / "group-content.schema.json",
        "rubric": experiment / "qa-rubric.md",
        "story": experiment / "story-bible.md",
        "output": experiment / "qa" / "global.json",
    }
    beats = json.loads(BEATS.read_text(encoding="utf-8"))
    _write_json(paths["beats"], beats)
    _write_json(paths["schema"], {"type": "object"})
    paths["rubric"].write_text("# fixture rubric\n", encoding="utf-8")
    paths["story"].write_text("# fixture story\n", encoding="utf-8")
    days_by_group = {
        group_id: [
            day for day in beats["days"] if day["group_id"] == group_id
        ]
        for group_id in EXPECTED_GROUP_IDS
    }
    for group_id in EXPECTED_GROUP_IDS:
        group = _group(group_id, days_by_group[group_id])
        group_path = experiment / "groups" / f"{group_id}.json"
        accepted_path = paths["accepted"] / f"{group_id}.json"
        deterministic_path = (
            experiment / "qa" / "deterministic" / f"{group_id}.json"
        )
        review_path = experiment / "qa" / "reviews" / f"{group_id}.md"
        evidence_path = paths["evidence"] / f"{group_id}.json"
        _write_json(group_path, group)
        accepted_path.parent.mkdir(parents=True, exist_ok=True)
        accepted_path.write_bytes(group_path.read_bytes())
        _write_json(
            deterministic_path,
            {
                "status": "structural_pass",
                "findings": [],
                "groups": [{"group_id": group_id, "findings": []}],
                "detector": {
                    "version": "opc-84d-v2-deterministic/3"
                },
            },
        )
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            f"# {group_id} independent review\n",
            encoding="utf-8",
        )
        inputs = {
            "group": group_path,
            "deterministic_report": deterministic_path,
            "independent_review": review_path,
            "daily_beats": paths["beats"],
            "schema": paths["schema"],
            "qa_rubric": paths["rubric"],
            "story_bible": paths["story"],
        }
        group_sha = _sha(group_path)
        evidence = {
            "schema": "pneuma.experiment.opc-84d-v2.acceptance/v1",
            "status": "accepted",
            "group_id": group_id,
            "group_sha256": group_sha,
            "accepted_copy": {
                "path": str(accepted_path),
                "sha256": group_sha,
                "byte_identical": True,
            },
            "deterministic": {
                "path": str(deterministic_path),
                "sha256": _sha(deterministic_path),
                "status": "structural_pass",
                "finding_count": 0,
                "detector_version": "opc-84d-v2-deterministic/3",
            },
            "review": {
                "path": str(review_path),
                "sha256": _sha(review_path),
                "verdict": "PASS",
                "non_author_attested": True,
                "recorded_group_sha256": group_sha,
            },
            "inputs": {
                label: {"path": str(path), "sha256": _sha(path)}
                for label, path in inputs.items()
            },
        }
        _write_json(evidence_path, evidence)
    return paths


def _read_group(paths: dict[str, Path], group_id: str) -> dict:
    return json.loads(
        (paths["accepted"] / f"{group_id}.json").read_text(
            encoding="utf-8"
        )
    )


def _refresh_group(
    paths: dict[str, Path],
    group_id: str,
    group: dict,
) -> None:
    group_path = paths["experiment"] / "groups" / f"{group_id}.json"
    accepted_path = paths["accepted"] / f"{group_id}.json"
    evidence_path = paths["evidence"] / f"{group_id}.json"
    _write_json(group_path, group)
    accepted_path.write_bytes(group_path.read_bytes())
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    group_sha = _sha(group_path)
    evidence["group_sha256"] = group_sha
    evidence["accepted_copy"]["sha256"] = group_sha
    evidence["inputs"]["group"]["sha256"] = group_sha
    evidence["review"]["recorded_group_sha256"] = group_sha
    _write_json(evidence_path, evidence)


def _validate(paths: dict[str, Path]) -> dict:
    module = _load_validator()
    return module.validate_global(
        accepted_dir=paths["accepted"],
        evidence_dir=paths["evidence"],
        beats_path=paths["beats"],
        output_path=paths["output"],
        root=paths["experiment"].parent,
    )


def _finding_codes(report: dict) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_complete_current_corpus_emits_global_pass_and_raw_metrics(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)

    report = _validate(paths)

    assert report["status"] == "global_pass"
    assert report["findings"] == []
    assert report["completeness"]["accepted_group_ids"] == list(
        EXPECTED_GROUP_IDS
    )
    assert report["completeness"]["evidence_group_ids"] == list(
        EXPECTED_GROUP_IDS
    )
    assert report["source_counts"]["target"] == EXPECTED_SOURCE_COUNTS
    assert report["source_counts"]["ledger"] == EXPECTED_SOURCE_COUNTS
    assert report["source_counts"]["actual"] == EXPECTED_SOURCE_COUNTS
    assert report["source_counts"]["total"] == 104
    assert len(report["groups"]) == 28
    assert all(
        family["floor_pass"]
        for group in report["groups"]
        for family in group["families"].values()
        if family["present"]
    )
    assert all(
        0.15 <= group["noise_ratio"] <= 0.40
        for group in report["groups"]
    )
    assert report["cross_group_candidates"] == {
        "exact": [],
        "ngram": [],
    }
    assert len(report["fact_ledger"]) == 14
    assert {
        item["id"] for item in report["unresolved_continuity_ledger"]
    } == {"C02", "C03", "C04", "C05", "C06"}
    assert report["uniform_density"]["rolling_three_group_gaps"] == []
    assert json.loads(paths["output"].read_text(encoding="utf-8")) == report


def test_missing_accepted_group_and_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    (paths["accepted"] / "G28.json").unlink()
    (paths["evidence"] / "G28.json").unlink()

    report = _validate(paths)

    assert report["status"] == "draft"
    assert {"accepted_group_set", "acceptance_evidence_set"} <= (
        _finding_codes(report)
    )
    assert report["completeness"]["missing_accepted"] == ["G28"]
    assert report["completeness"]["missing_evidence"] == ["G28"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("gap", "timeline_gap"),
        ("overlap", "timeline_overlap"),
    ],
)
def test_group_window_gap_or_overlap_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    paths = _fixture(tmp_path)
    group = _read_group(paths, "G02")
    window = group["group_window"]
    if mutation == "gap":
        window["starts_on"] = (
            date.fromisoformat(window["starts_on"]) + timedelta(days=1)
        ).isoformat()
        window["day_count"] = 2
    else:
        window["starts_on"] = (
            date.fromisoformat(window["starts_on"]) - timedelta(days=1)
        ).isoformat()
        window["day_count"] = 4
    _refresh_group(paths, "G02", group)

    report = _validate(paths)

    assert report["status"] == "draft"
    assert expected_code in _finding_codes(report)
    assert "group_window_mismatch" in _finding_codes(report)


def test_actual_source_count_must_match_daily_ledger_and_target(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    group = _read_group(paths, "G01")
    group["sources"]["document_library"].pop()
    _refresh_group(paths, "G01", group)

    report = _validate(paths)

    assert report["status"] == "draft"
    assert "source_count_mismatch" in _finding_codes(report)
    assert report["source_counts"]["actual"]["document_library"] == 34
    assert report["source_counts"]["ledger"]["document_library"] == 35


@pytest.mark.parametrize(
    ("duplicate_kind", "expected_code"),
    [
        ("authored_id", "duplicate_authored_id"),
        ("source_id", "duplicate_source_id"),
        ("provider_id", "duplicate_provider_id"),
    ],
)
def test_global_identifier_collisions_fail_closed(
    tmp_path: Path,
    duplicate_kind: str,
    expected_code: str,
) -> None:
    paths = _fixture(tmp_path)
    first = _read_group(paths, "G01")["sources"]["document_library"][0]
    second_group = _read_group(paths, "G02")
    second = second_group["sources"]["document_library"][0]
    if duplicate_kind == "authored_id":
        second["authorship"]["authored_id"] = first["authorship"][
            "authored_id"
        ]
    elif duplicate_kind == "source_id":
        second["source_id"] = first["source_id"]
    else:
        second["library_id"] = first["library_id"]
        second["documents"][0]["document_id"] = first["documents"][0][
            "document_id"
        ]
    _refresh_group(paths, "G02", second_group)

    report = _validate(paths)

    assert report["status"] == "draft"
    assert expected_code in _finding_codes(report)
    assert report["uniqueness"]["duplicates"][duplicate_kind]


def test_global_provider_identity_allows_one_library_across_disjoint_contracts(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    first = _read_group(paths, "G01")["sources"]["document_library"][0]
    second_group = _read_group(paths, "G02")
    second_group["sources"]["document_library"][0]["library_id"] = first[
        "library_id"
    ]
    _refresh_group(paths, "G02", second_group)

    report = _validate(paths)

    assert report["status"] == "global_pass"
    assert report["uniqueness"]["duplicates"]["provider_id"] == []


@pytest.mark.parametrize(
    ("family", "source", "expected"),
    [
        ("meeting", {"meeting_id": "meeting-1"}, ["meeting-1"]),
        (
            "document_library",
            {
                "library_id": "vault-1",
                "documents": [{"document_id": "note-1"}],
            },
            ["vault-1:note-1"],
        ),
        (
            "im",
            {
                "archive_id": "chat-1",
                "conversations": [{"conversation_id": "channel-1"}],
            },
            ["chat-1:channel-1"],
        ),
        (
            "email",
            {
                "archive_id": "mail-1",
                "threads": [{"thread_id": "thread-1"}],
            },
            ["mail-1:thread-1"],
        ),
    ],
)
def test_global_provider_identity_matches_official_normalizer_units(
    family: str,
    source: dict,
    expected: list[str],
) -> None:
    module = _load_validator()

    assert list(module._normalized_provider_ids(family, source)) == expected


def test_cross_group_exact_duplicate_emits_raw_candidate_and_fails(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    first_group = _read_group(paths, "G02")
    copied_text = first_group["sources"]["meetings"][0]["utterances"][0][
        "text"
    ]
    second_group = _read_group(paths, "G03")
    second_group["sources"]["meetings"][0]["utterances"][0][
        "text"
    ] = copied_text
    _refresh_group(paths, "G03", second_group)

    report = _validate(paths)

    assert report["status"] == "draft"
    assert "cross_group_exact" in _finding_codes(report)
    candidate = report["cross_group_candidates"]["exact"][0]
    assert candidate["left"]["raw_text"] == copied_text
    assert candidate["right"]["raw_text"] == copied_text
    assert candidate["left"]["group_id"] != candidate["right"]["group_id"]
    assert len(candidate["matched_normalized_text"]) >= 80


def test_cross_group_ngram_duplicate_emits_raw_candidate_and_fails(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    first_text = (
        "leftzero alpha bravo charlie delta echo foxtrot golf "
        "leftone lefttwo leftthree"
    )
    second_text = (
        "rightzero alpha bravo charlie delta echo foxtrot golf "
        "rightone righttwo rightthree"
    )
    first_group = _read_group(paths, "G02")
    first_group["sources"]["meetings"][0]["utterances"][0][
        "text"
    ] = first_text
    _refresh_group(paths, "G02", first_group)
    second_group = _read_group(paths, "G03")
    second_group["sources"]["meetings"][0]["utterances"][0][
        "text"
    ] = second_text
    _refresh_group(paths, "G03", second_group)

    report = _validate(paths)

    assert report["status"] == "draft"
    assert "cross_group_ngram" in _finding_codes(report)
    candidate = report["cross_group_candidates"]["ngram"][0]
    assert candidate["left"]["raw_text"] == first_text
    assert candidate["right"]["raw_text"] == second_text
    assert candidate["score"] > candidate["threshold"] == 0.18


def test_stale_acceptance_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    accepted_path = paths["accepted"] / "G01.json"
    accepted_path.write_bytes(accepted_path.read_bytes() + b"\n")

    report = _validate(paths)

    assert report["status"] == "draft"
    assert "acceptance_evidence_stale" in _finding_codes(report)
    stale = report["acceptance_freshness"]["entries"][0]
    assert stale["group_id"] == "G01"
    assert stale["status"] == "stale"
