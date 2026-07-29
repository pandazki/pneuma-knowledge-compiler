from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "validate_opc_84d_v2.py"
SCHEMA = ROOT / "docs" / "experiments" / "opc-84d-v2" / "group-content.schema.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location("opc_84d_v2_validator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authored(authored_id: str, kind: str = "signal") -> dict:
    return {"authored_id": authored_id, "occurred_at": "2026-01-02T09:00:00+00:00", "author_role": "engineering", "content_class": kind, "links": {"story_beat_ids": ["beat-01"], "fact_ids": [], "continuity_ids": []}}


def _words(prefix: str, count: int = 75) -> str:
    return " ".join(f"{prefix}word{index}" for index in range(count))


def _group(group_id: str = "group-01") -> dict:
    start = date(2026, 1, 2)
    utterances = [{"utterance_id": f"utterance-{i:02d}", "speaker_id": ("person-alex", "person-bo", "person-cy")[i % 3], "started_at": "2026-01-02T09:00:00+00:00", "ended_at": "2026-01-02T09:01:00+00:00", "text": _words(f"meeting{i}"), "interruption_of_utterance_id": None, "authorship": _authored(f"auth-meeting-{i:02d}", "noise" if i in {2, 7} else "signal")} for i in range(12)]
    blocks = [{"block_id": f"block-{i:02d}", "kind": "paragraph", "markdown": _words(f"document{i}", 50), "authorship": _authored(f"auth-doc-{i:02d}", "noise" if i == 1 else "signal")} for i in range(8)]
    documents = []
    for i in range(2):
        own = blocks[i * 4 : (i + 1) * 4]
        documents.append({"document_id": f"document-{i:02d}", "path": f"notes/document-{i:02d}.md", "title": f"Synthetic document {i}", "frontmatter": {"status": "draft"}, "full_markdown": "\n\n".join(block["markdown"] for block in own), "tags": ["synthetic"], "links": [], "created_at": "2026-01-02T09:00:00+00:00", "modified_at": "2026-01-02T10:00:00+00:00", "visible_blocks": own, "authorship": _authored(f"auth-document-{i:02d}")})
    return {"schema": "pneuma.experiment.opc-84d-v2.group-content/v1", "group_id": group_id, "group_window": {"starts_on": start.isoformat(), "ends_on": (start + timedelta(days=2)).isoformat(), "day_count": 3, "timezone": "UTC"}, "story_scope": {"allowed_story_beat_ids": ["beat-01"], "known_fact_ids": [], "open_continuity_ids": [], "new_continuity_ids": []}, "research_context": [{"research_ref_id": "research-01", "topic_query": "protocol record fields", "url": "https://www.ietf.org/", "title": "Protocol reference", "accessed_on": "2026-01-01", "credibility": {"tier": "official", "rationale": "Public standards source."}, "applicability_scope": "Message and record structure only.", "author_fact_summaries": ["Protocols use explicit fields."], "fictionalization_boundary": "Do not reuse names, examples, or prose.", "applied_authored_ids": ["auth-meeting-00"]}, {"research_ref_id": "research-02", "topic_query": "operations timestamp conventions", "url": "https://www.nist.gov/", "title": "Operations reference", "accessed_on": "2026-01-01", "credibility": {"tier": "official", "rationale": "Public agency source."}, "applicability_scope": "Timestamp conventions only.", "author_fact_summaries": ["Operational records retain timestamps."], "fictionalization_boundary": "Do not reuse agency wording or scenarios.", "applied_authored_ids": ["auth-doc-00"]}], "sources": {"meetings": [{"source_id": "source-meeting-01", "authorship": _authored("auth-source-meeting"), "schema": "pneuma.source.meeting/v1", "provider": "mock", "meeting_id": "meeting-01", "title": "Synthetic check-in", "started_at": "2026-01-02T09:00:00+00:00", "ended_at": "2026-01-02T10:00:00+00:00", "timezone": "UTC", "owner_participant_ids": ["person-alex"], "participants": [{"participant_id": "person-alex", "display_name": "Alex", "role": "engineering", "synthetic_address": "alex@example.test"}, {"participant_id": "person-bo", "display_name": "Bo", "role": "product", "synthetic_address": "bo@example.test"}, {"participant_id": "person-cy", "display_name": "Cy", "role": "design", "synthetic_address": "cy@example.test"}], "agenda": [{"agenda_id": "agenda-01", "text": "Review the synthetic constraint", "authorship": _authored("auth-agenda-01")}], "utterances": utterances}], "document_library": [{"source_id": "source-docs-01", "authorship": _authored("auth-source-docs"), "schema": "pneuma.source.document-library/v1", "provider": "mock", "library_id": "library-01", "title": "Synthetic vault", "documents": documents}], "im": [], "email": []}}


def _validate(tmp_path: Path, group: dict, accepted: list[dict] | None = None, beats: dict | None = None) -> dict:
    group_path = tmp_path / "group.json"
    group_path.write_text(json.dumps(group), encoding="utf-8")
    accepted_path = tmp_path / "accepted"
    accepted_path.mkdir()
    for index, item in enumerate(accepted or []):
        (accepted_path / f"accepted-{index}.json").write_text(json.dumps(item), encoding="utf-8")
    beats_path = None
    if beats is not None:
        beats_path = tmp_path / "daily-beats.json"
        beats_path.write_text(json.dumps(beats), encoding="utf-8")
    return _load_validator().validate_inputs([group_path], SCHEMA, accepted_path, tmp_path / "qa.json", beats_path)


def test_repeated_template_paragraph_is_rejected(tmp_path: Path) -> None:
    group = _group()
    repeated = "A copied paragraph has enough body text to trip deterministic duplicate detection. " * 2
    for document in group["sources"]["document_library"][0]["documents"]:
        block = document["visible_blocks"][0]
        document["full_markdown"] = document["full_markdown"].replace(
            block["markdown"],
            repeated,
            1,
        )
        block["markdown"] = repeated
    report = _validate(tmp_path, group)
    assert report["status"] == "draft"
    assert any(item["code"] == "duplicate_exact" for item in report["findings"])


def test_repeated_structural_headings_are_not_body_duplicates(tmp_path: Path) -> None:
    group = _group()
    for document in group["sources"]["document_library"][0]["documents"]:
        document["visible_blocks"].append({"block_id": f"heading-{document['document_id']}", "kind": "heading", "markdown": "## Status", "authorship": _authored(f"auth-heading-{document['document_id']}")})
        document["full_markdown"] += "\n\n## Status"
    report = _validate(tmp_path, group)
    assert not any(item["code"] == "duplicate_exact" and item["source_family"] == "document_library" for item in report["findings"])


def test_cross_group_copy_is_rejected(tmp_path: Path) -> None:
    previous = _group("group-prev")
    current = _group("group-current")
    current["sources"]["meetings"][0]["utterances"][0]["text"] = previous["sources"]["meetings"][0]["utterances"][0]["text"]
    report = _validate(tmp_path, current, [previous])
    assert report["status"] == "draft"
    assert any(item["code"] == "duplicate_cross_group" for item in report["findings"])


def test_research_decoration_or_unknown_authored_id_is_rejected(tmp_path: Path) -> None:
    group = _group()
    group["research_context"][0]["applied_authored_ids"] = ["authored-missing"]
    report = _validate(tmp_path, group)
    assert report["status"] == "draft"
    assert any(item["code"] == "research_applied_id_missing" for item in report["findings"])


def test_research_summary_copied_into_authored_prose_is_rejected(tmp_path: Path) -> None:
    group = _group()
    group["research_context"][0]["author_fact_summaries"] = [group["sources"]["meetings"][0]["utterances"][0]["text"][:220]]
    report = _validate(tmp_path, group)
    assert report["status"] == "draft"
    assert any(item["code"] == "research_summary_overlap_contiguous" for item in report["findings"])


def test_four_source_uniformity_is_left_for_global_review(tmp_path: Path) -> None:
    report = _validate(tmp_path, _group())
    assert report["status"] == "structural_pass"
    assert report["global_hooks"]["uniform_source_density_review"] == "pending"


def test_two_person_depth_interview_passes_meeting_speaker_floor(
    tmp_path: Path,
) -> None:
    group = _group()
    meeting = group["sources"]["meetings"][0]
    meeting["participants"] = meeting["participants"][:2]
    for index, utterance in enumerate(meeting["utterances"]):
        utterance["speaker_id"] = ("person-alex", "person-bo")[index % 2]
    assert len(meeting["utterances"]) >= 12
    assert sum(len(utterance["text"]) for utterance in meeting["utterances"]) >= 1_200
    report = _validate(tmp_path, group)
    assert report["status"] == "structural_pass"
    assert not any(
        item["code"] == "source_substance"
        and item.get("source_family") == "meeting"
        for item in report["findings"]
    )


def test_single_speaker_monologue_fails_meeting_speaker_floor(
    tmp_path: Path,
) -> None:
    group = _group()
    meeting = group["sources"]["meetings"][0]
    for utterance in meeting["utterances"]:
        utterance["speaker_id"] = "person-alex"
    assert len(meeting["utterances"]) >= 12
    assert sum(len(utterance["text"]) for utterance in meeting["utterances"]) >= 1_200
    report = _validate(tmp_path, group)
    assert report["status"] == "draft"
    assert any(
        item["code"] == "source_substance"
        and item.get("source_family") == "meeting"
        and "fewer than two speakers" in item["message"]
        for item in report["findings"]
    )


def test_one_im_conversation_fails_even_with_message_and_sender_floors(
    tmp_path: Path,
) -> None:
    group = _group()
    users = [
        {
            "user_id": f"im-user-{name}",
            "display_name": name.title(),
            "role": "engineering",
            "synthetic_address": f"{name}@example.test",
            "is_bot": False,
        }
        for name in ("alex", "bo", "cy")
    ]
    messages = [
        {
            "message_id": f"im-message-{index:02d}",
            "sender_id": users[index % len(users)]["user_id"],
            "sent_at": "2026-01-02T09:00:00+00:00",
            "full_text": _words(f"im{index}", 75),
            "thread_id": None,
            "edited_at": None,
            "reactions": [],
            "authorship": _authored(
                f"auth-im-{index:02d}",
                "noise" if index in {2, 7, 12, 17} else "signal",
            ),
        }
        for index in range(18)
    ]
    group["sources"]["im"] = [
        {
            "source_id": "source-im-01",
            "authorship": _authored("auth-source-im"),
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "archive-01",
            "owner_user_ids": [users[0]["user_id"]],
            "users": users,
            "conversations": [
                {
                    "conversation_id": "conversation-only",
                    "conversation_type": "channel",
                    "title": "Single synthetic conversation",
                    "member_ids": [user["user_id"] for user in users],
                    "messages": messages,
                    "authorship": _authored("auth-conversation-only"),
                }
            ],
        }
    ]

    assert len(messages) == 18
    assert len({message["sender_id"] for message in messages}) == 3
    assert sum(len(message["full_text"]) for message in messages) >= 1_000
    report = _validate(tmp_path, group)

    assert report["status"] == "draft"
    assert any(
        item["code"] == "source_substance"
        and item.get("source_family") == "im"
        and "fewer than two conversations" in item["message"]
        for item in report["findings"]
    )


def test_uppercase_daily_ledger_ids_are_schema_and_validator_compatible(tmp_path: Path) -> None:
    group = _group("G01")
    group["story_scope"] = {"allowed_story_beat_ids": ["D01"], "known_fact_ids": ["F01"], "open_continuity_ids": ["C01"], "new_continuity_ids": []}
    for node in _walk(group):
        if "authored_id" in node and "links" in node:
            node["links"] = {"story_beat_ids": ["D01"], "fact_ids": ["F01"], "continuity_ids": ["C01"]}
    group["research_context"][0]["research_ref_id"] = "R01"
    report = _validate(tmp_path, group)
    assert report["status"] == "structural_pass"


def test_daily_beats_g01_is_exactly_enforced_with_evidence(tmp_path: Path) -> None:
    group = _daily_group()
    report = _validate(tmp_path, group, beats=_beats_g01())
    assert report["status"] == "structural_pass"
    evidence = report["groups"][0]["daily_beats_evidence"]
    assert evidence["expected_source_counts"] == evidence["actual_source_counts"] == {"meeting": 1, "document_library": 1, "im": 0, "email": 0}
    assert evidence["permitted_fact_ids"] == ["F01"]


def test_daily_beats_rejects_future_fact_reference(tmp_path: Path) -> None:
    group = _daily_group()
    group["story_scope"]["known_fact_ids"] = ["F02"]
    for node in _walk(group):
        if "authored_id" in node and "links" in node:
            node["links"]["fact_ids"] = ["F02"]
    report = _validate(tmp_path, group, beats=_beats_g01())
    assert report["status"] == "draft"
    assert any(item["code"] == "beats_scope" and "F02" in item["message"] for item in report["findings"])


def test_g01_shape_orphan_blocks_are_rejected_and_not_counted(
    tmp_path: Path,
) -> None:
    group = _group("G01")
    document = group["sources"]["document_library"][0]["documents"][0]
    mapped_raw_chars = sum(
        len(block["markdown"])
        for source in group["sources"]["document_library"]
        for item in source["documents"]
        for block in item["visible_blocks"]
        if block["kind"] != "heading"
    )
    for index in range(7):
        document["visible_blocks"].append(
            {
                "block_id": f"G01-orphan-{index}",
                "kind": "paragraph",
                "markdown": _words(f"orphan{index}", 20),
                "authorship": _authored(f"G01-orphan-{index}-auth"),
            }
        )
    report = _validate(tmp_path, group)
    mapping_findings = [
        item
        for item in report["findings"]
        if item["code"] == "document_visible_block_unmapped"
    ]
    assert report["status"] == "draft"
    assert {item["block_id"] for item in mapping_findings} == {
        f"G01-orphan-{index}" for index in range(7)
    }
    metrics = report["groups"][0]["metrics"]
    assert (
        metrics["source_families"]["document_library"]["mapped_raw_chars"]
        == mapped_raw_chars
    )
    assert metrics["source_families"]["document_library"][
        "unmapped_visible_block_chars"
    ] == sum(
        len(block["markdown"])
        for block in document["visible_blocks"]
        if block["block_id"].startswith("G01-orphan-")
    )


def test_document_character_count_excludes_markdown_structure(tmp_path: Path) -> None:
    group = _group()
    document = group["sources"]["document_library"][0]["documents"][0]
    block = document["visible_blocks"][0]
    original = block["markdown"]
    block["kind"] = "list"
    block["markdown"] = f"- [ ] {original}"
    document["full_markdown"] = document["full_markdown"].replace(
        original,
        block["markdown"],
        1,
    )
    report = _validate(tmp_path, group)
    family = report["groups"][0]["metrics"]["source_families"]["document_library"]
    assert family["mapped_raw_chars"] - family["body_chars"] >= len("- [ ] ")


def test_document_block_order_and_stable_ids_are_enforced(tmp_path: Path) -> None:
    group = _group()
    document = group["sources"]["document_library"][0]["documents"][0]
    document["visible_blocks"][0], document["visible_blocks"][1] = (
        document["visible_blocks"][1],
        document["visible_blocks"][0],
    )
    document["visible_blocks"][2]["block_id"] = document["visible_blocks"][0][
        "block_id"
    ]
    report = _validate(tmp_path, group)
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "draft"
    assert "document_visible_block_out_of_order" in codes
    assert "document_block_id_duplicate" in codes


def _daily_group() -> dict:
    group = _group("G01")
    group["story_scope"] = {"allowed_story_beat_ids": ["D01", "D02", "D03"], "known_fact_ids": ["F01"], "open_continuity_ids": ["C01"], "new_continuity_ids": ["C01"]}
    for node in _walk(group):
        if "authored_id" in node and "links" in node:
            node["links"] = {"story_beat_ids": ["D01"], "fact_ids": ["F01"], "continuity_ids": ["C01"]}
    return group


def _beats_g01() -> dict:
    return {"days": [
        {"date": "2026-01-02", "day_index": 1, "group_id": "G01", "source_plan": [{"type": "meeting"}, {"type": "document_library"}], "fact_ids": ["F01"], "continuity_ids": ["C01"]},
        {"date": "2026-01-03", "day_index": 2, "group_id": "G01", "source_plan": [], "fact_ids": ["F01"], "continuity_ids": ["C01"]},
        {"date": "2026-01-04", "day_index": 3, "group_id": "G01", "source_plan": [], "fact_ids": ["F01"], "continuity_ids": ["C01"]},
    ]}


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
