#!/usr/bin/env python3
"""Rebuild fail-closed global QA evidence for the OPC 84-day v2 corpus."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Iterator


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = ROOT / "docs" / "experiments" / "opc-84d-v2"
EXPECTED_GROUP_IDS = tuple(f"G{index:02d}" for index in range(1, 29))
FAMILY_KEYS = {
    "meetings": "meeting",
    "document_library": "document_library",
    "im": "im",
    "email": "email",
}
FAMILY_ORDER = ("meeting", "document_library", "im", "email")
FAMILY_FLOORS = {
    "meeting": {"body_chars": 1_200, "units": 12},
    "document_library": {"body_chars": 1_800, "units": 8},
    "im": {"body_chars": 1_000, "units": 18},
    "email": {"body_chars": 1_200, "units": 4},
}
TARGET_SOURCE_COUNTS = {
    "meeting": 18,
    "document_library": 35,
    "im": 30,
    "email": 21,
}
TARGET_SOURCE_TOTAL = 104
EXACT_NORMALIZED_MIN_CHARS = 80
NGRAM_SIZE = 5
NGRAM_JACCARD = 0.18
SCHEMA = "pneuma.experiment.opc-84d-v2.global-qa/v1"
VERSION = "opc-84d-v2-global/1"
def _load_sibling(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load required validator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ACCEPTANCE_AUDIT = _load_sibling(
    "audit_opc_84d_v2_acceptance.py",
    "_opc_84d_v2_acceptance_audit_for_global",
)
_GROUP_VALIDATOR = _load_sibling(
    "validate_opc_84d_v2.py",
    "_opc_84d_v2_group_validator_for_global",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finding(code: str, message: str, **evidence: Any) -> dict[str, Any]:
    result = {
        "code": code,
        "severity": "error",
        "message": message,
    }
    result.update(evidence)
    return result


def _resolve_within(path: Path, root: Path) -> Path:
    try:
        return _ACCEPTANCE_AUDIT._resolve_path(str(path), root)
    except ValueError as error:
        raise ValueError(
            f"{path} is outside explicit global-validation root {root.resolve()}"
        ) from error


def _json_files(
    directory: Path,
    *,
    label: str,
    findings: list[dict[str, Any]],
) -> dict[str, Path]:
    if not directory.is_dir():
        findings.append(
            _finding(
                f"{label}_directory_missing",
                f"{label} directory is missing",
                path=str(directory),
            )
        )
        return {}
    return {
        path.stem: path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix == ".json"
    }


def _set_evidence(
    *,
    code: str,
    label: str,
    found: Iterable[str],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = set(EXPECTED_GROUP_IDS)
    actual = set(found)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        findings.append(
            _finding(
                code,
                f"{label} must contain exactly G01 through G28",
                missing=missing,
                unexpected=unexpected,
            )
        )
    return {
        "group_ids": sorted(actual),
        "missing": missing,
        "unexpected": unexpected,
    }


def _read_json_object(
    path: Path,
    *,
    code: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        findings.append(
            _finding(
                code,
                "JSON input is missing, unreadable, or invalid",
                path=str(path),
                reason=str(error),
            )
        )
        return None
    if not isinstance(value, dict):
        findings.append(
            _finding(
                code,
                "JSON input must contain an object",
                path=str(path),
            )
        )
        return None
    return value


def _ledger_model(
    beats: dict[str, Any] | None,
    *,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    days = beats.get("days") if isinstance(beats, dict) else None
    if not isinstance(days, list):
        findings.append(
            _finding(
                "daily_beats_invalid",
                "daily-beats must contain a days array",
            )
        )
        days = []

    parsed_days: list[tuple[int, date, str, list[dict[str, Any]]]] = []
    for position, item in enumerate(days):
        try:
            if not isinstance(item, dict):
                raise TypeError("day is not an object")
            day_index = item["day_index"]
            parsed_date = date.fromisoformat(item["date"])
            group_id = item["group_id"]
            source_plan = item["source_plan"]
            if (
                not isinstance(day_index, int)
                or not isinstance(group_id, str)
                or not isinstance(source_plan, list)
            ):
                raise TypeError("day fields have invalid types")
        except (KeyError, TypeError, ValueError) as error:
            findings.append(
                _finding(
                    "daily_beats_invalid",
                    "daily-beats day cannot be parsed",
                    position=position,
                    reason=str(error),
                )
            )
            continue
        parsed_days.append(
            (day_index, parsed_date, group_id, source_plan)
        )

    parsed_days.sort(key=lambda item: item[0])
    actual_indices = [item[0] for item in parsed_days]
    actual_dates = [item[1] for item in parsed_days]
    expected_indices = list(range(1, 85))
    expected_dates: list[date] = []
    if parsed_days:
        expected_dates = [
            parsed_days[0][1] + timedelta(days=index)
            for index in range(84)
        ]
    if (
        len(parsed_days) != 84
        or actual_indices != expected_indices
        or actual_dates != expected_dates
    ):
        findings.append(
            _finding(
                "daily_beats_timeline",
                "daily-beats must define D01-D84 as consecutive dates",
                day_count=len(parsed_days),
                day_indices=actual_indices,
                dates=[item.isoformat() for item in actual_dates],
            )
        )

    by_group: dict[str, list[tuple[int, date, list[dict[str, Any]]]]] = (
        defaultdict(list)
    )
    ledger_counts = Counter({family: 0 for family in FAMILY_ORDER})
    unknown_families: list[dict[str, Any]] = []
    for day_index, parsed_date, group_id, source_plan in parsed_days:
        by_group[group_id].append((day_index, parsed_date, source_plan))
        for source in source_plan:
            family = (
                str(source.get("type", "")).casefold()
                if isinstance(source, dict)
                else ""
            )
            if family not in FAMILY_ORDER:
                unknown_families.append(
                    {
                        "day_index": day_index,
                        "source_type": family,
                    }
                )
                continue
            ledger_counts[family] += 1
    if unknown_families:
        findings.append(
            _finding(
                "daily_beats_source_family",
                "daily-beats contains unknown source families",
                entries=unknown_families,
            )
        )

    group_windows: dict[str, dict[str, Any]] = {}
    expected_group_set = set(EXPECTED_GROUP_IDS)
    if set(by_group) != expected_group_set:
        findings.append(
            _finding(
                "daily_beats_group_plan",
                "daily-beats must assign exactly three days to G01-G28",
                missing=sorted(expected_group_set - set(by_group)),
                unexpected=sorted(set(by_group) - expected_group_set),
            )
        )
    for group_id in EXPECTED_GROUP_IDS:
        entries = sorted(by_group.get(group_id, []))
        if len(entries) != 3:
            findings.append(
                _finding(
                    "daily_beats_group_plan",
                    f"{group_id} must own exactly three daily-beats rows",
                    group_id=group_id,
                    day_count=len(entries),
                )
            )
            continue
        group_windows[group_id] = {
            "starts_on": entries[0][1],
            "ends_on": entries[-1][1],
            "dates": [entry[1] for entry in entries],
            "source_counts": dict(
                Counter(
                    str(source.get("type", "")).casefold()
                    for _, _, source_plan in entries
                    for source in source_plan
                    if isinstance(source, dict)
                    and str(source.get("type", "")).casefold()
                    in FAMILY_ORDER
                )
            ),
        }

    ledger_count_dict = {
        family: ledger_counts[family] for family in FAMILY_ORDER
    }
    if (
        ledger_count_dict != TARGET_SOURCE_COUNTS
        or sum(ledger_count_dict.values()) != TARGET_SOURCE_TOTAL
    ):
        findings.append(
            _finding(
                "ledger_source_target_mismatch",
                "daily-beats source totals differ from the approved 104-source target",
                expected=TARGET_SOURCE_COUNTS,
                actual=ledger_count_dict,
            )
        )
    return {
        "days": parsed_days,
        "dates": actual_dates,
        "groups": group_windows,
        "source_counts": ledger_count_dict,
    }


def _parse_groups(
    paths: dict[str, Path],
    *,
    findings: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    groups: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for filename_group_id, path in sorted(paths.items()):
        group = _read_json_object(
            path,
            code="accepted_group_invalid",
            findings=findings,
        )
        if group is None:
            continue
        group_id = group.get("group_id")
        if group_id != filename_group_id:
            findings.append(
                _finding(
                    "accepted_group_filename_mismatch",
                    "accepted group_id differs from its filename",
                    filename_group_id=filename_group_id,
                    group_id=group_id,
                )
            )
            continue
        groups[filename_group_id] = group
        hashes[filename_group_id] = _sha(path)
    return groups, hashes


def _timeline_evidence(
    groups: dict[str, dict[str, Any]],
    ledger: dict[str, Any],
    *,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    date_owners: dict[date, list[str]] = defaultdict(list)
    windows: list[dict[str, Any]] = []
    for group_id in EXPECTED_GROUP_IDS:
        group = groups.get(group_id)
        if group is None:
            continue
        try:
            window = group["group_window"]
            starts_on = date.fromisoformat(window["starts_on"])
            ends_on = date.fromisoformat(window["ends_on"])
            day_count = window["day_count"]
            if not isinstance(day_count, int):
                raise TypeError("day_count is not an integer")
        except (KeyError, TypeError, ValueError) as error:
            findings.append(
                _finding(
                    "group_window_invalid",
                    f"{group_id} group window cannot be parsed",
                    group_id=group_id,
                    reason=str(error),
                )
            )
            continue
        actual_dates = [
            starts_on + timedelta(days=index)
            for index in range(max(0, (ends_on - starts_on).days + 1))
        ]
        for parsed_date in actual_dates:
            date_owners[parsed_date].append(group_id)
        expected = ledger["groups"].get(group_id)
        expected_dates = expected["dates"] if expected else []
        if (
            day_count != len(actual_dates)
            or actual_dates != expected_dates
        ):
            findings.append(
                _finding(
                    "group_window_mismatch",
                    f"{group_id} window differs from its three daily-beats dates",
                    group_id=group_id,
                    expected=[
                        value.isoformat() for value in expected_dates
                    ],
                    actual=[value.isoformat() for value in actual_dates],
                    declared_day_count=day_count,
                )
            )
        windows.append(
            {
                "group_id": group_id,
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat(),
                "day_count": day_count,
                "dates": [value.isoformat() for value in actual_dates],
            }
        )

    expected_dates = set(ledger["dates"])
    actual_dates = set(date_owners)
    gaps = sorted(expected_dates - actual_dates)
    overlaps = sorted(
        parsed_date
        for parsed_date, owners in date_owners.items()
        if len(owners) > 1
    )
    outside = sorted(actual_dates - expected_dates)
    if gaps:
        findings.append(
            _finding(
                "timeline_gap",
                "accepted group windows leave daily-beats dates uncovered",
                dates=[value.isoformat() for value in gaps],
            )
        )
    if overlaps:
        findings.append(
            _finding(
                "timeline_overlap",
                "accepted group windows overlap",
                dates=[
                    {
                        "date": value.isoformat(),
                        "group_ids": date_owners[value],
                    }
                    for value in overlaps
                ],
            )
        )
    if outside:
        findings.append(
            _finding(
                "timeline_outside_ledger",
                "accepted group windows include dates outside daily-beats",
                dates=[value.isoformat() for value in outside],
            )
        )
    return {
        "expected_start": (
            min(expected_dates).isoformat() if expected_dates else None
        ),
        "expected_end": (
            max(expected_dates).isoformat() if expected_dates else None
        ),
        "expected_days": len(expected_dates),
        "covered_days": len(actual_dates & expected_dates),
        "gaps": [value.isoformat() for value in gaps],
        "overlaps": [
            {
                "date": value.isoformat(),
                "group_ids": date_owners[value],
            }
            for value in overlaps
        ],
        "outside_dates": [value.isoformat() for value in outside],
        "windows": windows,
    }


def _source_items(
    group: dict[str, Any],
) -> Iterable[tuple[str, dict[str, Any]]]:
    sources = group.get("sources", {})
    if not isinstance(sources, dict):
        return
    for source_key, family in FAMILY_KEYS.items():
        items = sources.get(source_key, [])
        if not isinstance(items, list):
            continue
        for source in items:
            if isinstance(source, dict):
                yield family, source


def _source_counts(
    groups: dict[str, dict[str, Any]],
    ledger: dict[str, Any],
    *,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    actual = Counter({family: 0 for family in FAMILY_ORDER})
    per_group: list[dict[str, Any]] = []
    for group_id in EXPECTED_GROUP_IDS:
        group = groups.get(group_id)
        actual_group = Counter({family: 0 for family in FAMILY_ORDER})
        if group is not None:
            for family, _ in _source_items(group):
                actual_group[family] += 1
                actual[family] += 1
        expected_group = Counter(
            ledger["groups"].get(group_id, {}).get("source_counts", {})
        )
        expected_dict = {
            family: expected_group[family] for family in FAMILY_ORDER
        }
        actual_dict = {
            family: actual_group[family] for family in FAMILY_ORDER
        }
        if actual_dict != expected_dict:
            findings.append(
                _finding(
                    "source_count_mismatch",
                    f"{group_id} source counts differ from daily-beats",
                    group_id=group_id,
                    expected=expected_dict,
                    actual=actual_dict,
                )
            )
        per_group.append(
            {
                "group_id": group_id,
                "expected": expected_dict,
                "actual": actual_dict,
            }
        )
    actual_dict = {family: actual[family] for family in FAMILY_ORDER}
    if actual_dict != ledger["source_counts"]:
        findings.append(
            _finding(
                "source_count_mismatch",
                "accepted corpus source counts differ from daily-beats",
                expected=ledger["source_counts"],
                actual=actual_dict,
            )
        )
    return {
        "target": dict(TARGET_SOURCE_COUNTS),
        "target_total": TARGET_SOURCE_TOTAL,
        "ledger": ledger["source_counts"],
        "actual": actual_dict,
        "total": sum(actual_dict.values()),
        "per_group": per_group,
    }


def _story_ledgers(
    beats: dict[str, Any] | None,
    groups: dict[str, dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canonical = (
        beats.get("canonical_ledger", {})
        if isinstance(beats, dict)
        else {}
    )
    canonical_facts = canonical.get("facts", [])
    canonical_continuities = canonical.get("continuities", [])
    days = beats.get("days", []) if isinstance(beats, dict) else []
    if not isinstance(canonical_facts, list):
        canonical_facts = []
    if not isinstance(canonical_continuities, list):
        canonical_continuities = []
    if not isinstance(days, list):
        days = []

    fact_appearances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    continuity_appearances: dict[str, list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for day in days:
        if not isinstance(day, dict):
            continue
        appearance = {
            "day_index": day.get("day_index"),
            "date": day.get("date"),
            "group_id": day.get("group_id"),
        }
        for fact_id in day.get("fact_ids", []):
            if isinstance(fact_id, str):
                fact_appearances[fact_id].append(appearance)
        for continuity_id in day.get("continuity_ids", []):
            if isinstance(continuity_id, str):
                continuity_appearances[continuity_id].append(appearance)

    fact_references: dict[str, set[str]] = defaultdict(set)
    continuity_references: dict[str, set[str]] = defaultdict(set)
    for group_id, group in groups.items():
        scope = group.get("story_scope", {})
        if isinstance(scope, dict):
            for fact_id in scope.get("known_fact_ids", []):
                if isinstance(fact_id, str):
                    fact_references[fact_id].add(group_id)
            for field in ("open_continuity_ids", "new_continuity_ids"):
                for continuity_id in scope.get(field, []):
                    if isinstance(continuity_id, str):
                        continuity_references[continuity_id].add(group_id)
        for _, node in _walk_with_path(group):
            links = node.get("links")
            if not isinstance(links, dict):
                continue
            for fact_id in links.get("fact_ids", []):
                if isinstance(fact_id, str):
                    fact_references[fact_id].add(group_id)
            for continuity_id in links.get("continuity_ids", []):
                if isinstance(continuity_id, str):
                    continuity_references[continuity_id].add(group_id)

    fact_ids = [
        item.get("id")
        for item in canonical_facts
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    continuity_ids = [
        item.get("id")
        for item in canonical_continuities
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    if (
        len(fact_ids) != len(set(fact_ids))
        or set(fact_ids) != set(fact_appearances)
        or set(fact_references) - set(fact_ids)
    ):
        findings.append(
            _finding(
                "fact_ledger_mismatch",
                "canonical fact ledger differs from daily or accepted references",
                canonical_ids=sorted(set(fact_ids)),
                daily_ids=sorted(fact_appearances),
                unknown_accepted_references=sorted(
                    set(fact_references) - set(fact_ids)
                ),
            )
        )
    if (
        len(continuity_ids) != len(set(continuity_ids))
        or set(continuity_ids) != set(continuity_appearances)
        or set(continuity_references) - set(continuity_ids)
    ):
        findings.append(
            _finding(
                "continuity_ledger_mismatch",
                "canonical continuity ledger differs from daily or accepted references",
                canonical_ids=sorted(set(continuity_ids)),
                daily_ids=sorted(continuity_appearances),
                unknown_accepted_references=sorted(
                    set(continuity_references) - set(continuity_ids)
                ),
            )
        )

    fact_ledger = []
    for item in canonical_facts:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        fact_id = item["id"]
        appearances = fact_appearances.get(fact_id, [])
        fact_ledger.append(
            {
                **item,
                "daily_appearances": appearances,
                "daily_group_ids": sorted(
                    {
                        appearance["group_id"]
                        for appearance in appearances
                        if isinstance(appearance.get("group_id"), str)
                    }
                ),
                "accepted_reference_group_ids": sorted(
                    fact_references.get(fact_id, set())
                ),
            }
        )
    continuity_ledger = []
    for item in canonical_continuities:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        continuity_id = item["id"]
        appearances = continuity_appearances.get(continuity_id, [])
        continuity_ledger.append(
            {
                **item,
                "daily_appearances": appearances,
                "daily_group_ids": sorted(
                    {
                        appearance["group_id"]
                        for appearance in appearances
                        if isinstance(appearance.get("group_id"), str)
                    }
                ),
                "accepted_reference_group_ids": sorted(
                    continuity_references.get(continuity_id, set())
                ),
            }
        )
    unresolved = [
        item for item in continuity_ledger if item.get("closed_day") is None
    ]
    return fact_ledger, unresolved


def _walk_with_path(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterable[tuple[tuple[str, ...], dict[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_with_path(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_with_path(child, (*path, str(index)))


def _duplicates(
    occurrences: dict[Any, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        {
            "value": (
                list(value) if isinstance(value, tuple) else value
            ),
            "occurrences": entries,
        }
        for value, entries in sorted(
            occurrences.items(),
            key=lambda item: str(item[0]),
        )
        if len(entries) > 1
    ]


def _normalized_provider_ids(
    family: str,
    source: dict[str, Any],
) -> Iterator[str]:
    """Match the provider identity boundary used by canonical normalizers."""

    if family == "meeting":
        meeting_id = source.get("meeting_id")
        if isinstance(meeting_id, str):
            yield meeting_id
    elif family == "document_library":
        library_id = source.get("library_id")
        if isinstance(library_id, str):
            for document in source.get("documents", []):
                document_id = document.get("document_id")
                if isinstance(document_id, str):
                    yield f"{library_id}:{document_id}"
    elif family == "im":
        archive_id = source.get("archive_id")
        if isinstance(archive_id, str):
            for conversation in source.get("conversations", []):
                conversation_id = conversation.get("conversation_id")
                if isinstance(conversation_id, str):
                    yield f"{archive_id}:{conversation_id}"
    elif family == "email":
        archive_id = source.get("archive_id")
        if isinstance(archive_id, str):
            for thread in source.get("threads", []):
                thread_id = thread.get("thread_id")
                if isinstance(thread_id, str):
                    yield f"{archive_id}:{thread_id}"


def _uniqueness_evidence(
    groups: dict[str, dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    authored: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    provider_ids: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for group_id, group in sorted(groups.items()):
        for path, node in _walk_with_path(group):
            authored_id = node.get("authored_id")
            if isinstance(authored_id, str):
                authored[authored_id].append(
                    {
                        "group_id": group_id,
                        "path": ".".join(path),
                    }
                )
        for family, source in _source_items(group):
            source_id = source.get("source_id")
            if isinstance(source_id, str):
                source_ids[source_id].append(
                    {"group_id": group_id, "family": family}
                )
            provider = source.get("provider")
            if isinstance(provider, str):
                for provider_id in _normalized_provider_ids(family, source):
                    provider_ids[(family, provider, provider_id)].append(
                        {
                            "group_id": group_id,
                            "source_id": source_id,
                        }
                    )
    duplicates = {
        "authored_id": _duplicates(authored),
        "source_id": _duplicates(source_ids),
        "provider_id": _duplicates(provider_ids),
    }
    for kind, entries in duplicates.items():
        if entries:
            findings.append(
                _finding(
                    f"duplicate_{kind}",
                    f"global {kind} index contains collisions",
                    duplicates=entries,
                )
            )
    return {
        "counts": {
            "authored_id": len(authored),
            "source_id": len(source_ids),
            "provider_id": len(provider_ids),
        },
        "duplicates": duplicates,
        "provider_id_namespace": [
            "source_family",
            "provider",
            "normalized_unit_provider_id",
        ],
    }


def _family_specifics(
    group: dict[str, Any],
    family: str,
) -> dict[str, Any]:
    sources = group.get("sources", {})
    if family == "meeting":
        items = sources.get("meetings", [])
        speakers = {
            utterance.get("speaker_id")
            for source in items
            for utterance in source.get("utterances", [])
        }
        return {
            "speakers": len(speakers),
            "specific_pass": len(speakers) >= 2,
        }
    if family == "document_library":
        items = sources.get("document_library", [])
        documents = [
            document
            for source in items
            for document in source.get("documents", [])
        ]
        paths = {
            document.get("path")
            for document in documents
            if isinstance(document.get("path"), str)
        }
        return {
            "documents": len(documents),
            "paths": len(paths),
            "specific_pass": len(documents) >= 2 and len(paths) >= 2,
        }
    if family == "im":
        items = sources.get("im", [])
        conversations = [
            conversation
            for source in items
            for conversation in source.get("conversations", [])
        ]
        senders = {
            message.get("sender_id")
            for conversation in conversations
            for message in conversation.get("messages", [])
        }
        return {
            "conversations": len(conversations),
            "senders": len(senders),
            "specific_pass": (
                len(conversations) >= 2 and len(senders) >= 3
            ),
        }
    items = sources.get("email", [])
    threads = [
        thread
        for source in items
        for thread in source.get("threads", [])
    ]
    addresses: set[str] = set()

    def add_address(value: Any) -> None:
        if isinstance(value, str):
            addresses.add(value)
        elif isinstance(value, dict):
            address = value.get("address")
            if isinstance(address, str):
                addresses.add(address)

    for thread in threads:
        for message in thread.get("messages", []):
            add_address(message.get("from"))
            for field in ("to", "cc"):
                values = message.get(field, [])
                if isinstance(values, list):
                    for value in values:
                        add_address(value)
    return {
        "threads": len(threads),
        "addresses": len(addresses),
        "specific_pass": len(threads) >= 2 and len(addresses) >= 3,
    }


def _group_metrics(
    groups: dict[str, dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    detection_units: list[dict[str, Any]] = []
    for group_id in EXPECTED_GROUP_IDS:
        group = groups.get(group_id)
        if group is None:
            continue
        document_records = _GROUP_VALIDATOR._document_block_records(group)
        rows = _GROUP_VALIDATOR._units(group, document_records)
        families: dict[str, dict[str, Any]] = {}
        present_floors = 0
        for family in FAMILY_ORDER:
            sources = [
                source
                for source_family, source in _source_items(group)
                if source_family == family
            ]
            selected = [
                row for row in rows if row["source_family"] == family
            ]
            body_chars = sum(len(row["text"]) for row in selected)
            class_chars = {
                content_class: sum(
                    len(row["text"])
                    for row in selected
                    if row["content_class"] == content_class
                )
                for content_class in ("signal", "noise", "ambiguous")
            }
            present = bool(sources)
            floor = FAMILY_FLOORS[family]
            specifics = (
                _family_specifics(group, family) if present else {}
            )
            floor_pass = (
                not present
                or (
                    body_chars >= floor["body_chars"]
                    and len(selected) >= floor["units"]
                    and specifics.get("specific_pass") is True
                )
            )
            if present:
                present_floors += floor["body_chars"]
                if not floor_pass:
                    findings.append(
                        _finding(
                            "family_floor",
                            f"{group_id} {family} is below a local family floor",
                            group_id=group_id,
                            family=family,
                            body_chars=body_chars,
                            units=len(selected),
                            required=floor,
                            specifics=specifics,
                        )
                    )
            families[family] = {
                "present": present,
                "sources": len(sources),
                "units": len(selected),
                "body_chars": body_chars,
                "class_chars": class_chars,
                "floor": floor,
                "floor_pass": floor_pass,
                "specifics": specifics,
            }
            for row in selected:
                detection_units.append(
                    {
                        "group_id": group_id,
                        "source_family": family,
                        "artifact_id": row["artifact_id"],
                        "authored_ids": [row["authored_id"]],
                        "text": row["text"],
                        "raw_text": row["raw_text"],
                        "window_size": 1,
                    }
                )
        body_chars = sum(len(row["text"]) for row in rows)
        noise_chars = sum(
            len(row["text"])
            for row in rows
            if row["content_class"] in {"noise", "ambiguous"}
        )
        noise_ratio = noise_chars / body_chars if body_chars else 0.0
        required_group_chars = max(
            2_400,
            math.ceil(0.85 * present_floors),
        )
        group_floor_pass = body_chars >= required_group_chars
        if not group_floor_pass:
            findings.append(
                _finding(
                    "group_floor",
                    f"{group_id} is below its whole-group floor",
                    group_id=group_id,
                    body_chars=body_chars,
                    required_body_chars=required_group_chars,
                )
            )
        if not 0.15 <= noise_ratio <= 0.40:
            findings.append(
                _finding(
                    "noise_ratio",
                    f"{group_id} noise ratio is outside 15%-40%",
                    group_id=group_id,
                    noise_chars=noise_chars,
                    body_chars=body_chars,
                    noise_ratio=noise_ratio,
                )
            )
        reports.append(
            {
                "group_id": group_id,
                "window": group.get("group_window"),
                "body_chars": body_chars,
                "noise_chars": noise_chars,
                "noise_ratio": noise_ratio,
                "source_count": sum(
                    family["sources"] for family in families.values()
                ),
                "unit_count": sum(
                    family["units"] for family in families.values()
                ),
                "required_group_body_chars": required_group_chars,
                "group_floor_pass": group_floor_pass,
                "families": families,
            }
        )
    return reports, detection_units


def _short_windows(
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = list(units)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for unit in units:
        grouped[
            (
                unit["group_id"],
                unit["source_family"],
                unit["artifact_id"],
            )
        ].append(unit)
    for artifact_units in grouped.values():
        for start in range(len(artifact_units)):
            for window_size in (2, 3):
                window = artifact_units[start : start + window_size]
                if len(window) != window_size:
                    continue
                if all(
                    len(_GROUP_VALIDATOR._normal(item["text"]))
                    >= EXACT_NORMALIZED_MIN_CHARS
                    for item in window
                ):
                    continue
                text = "\n".join(item["text"] for item in window)
                if (
                    len(_GROUP_VALIDATOR._normal(text))
                    < EXACT_NORMALIZED_MIN_CHARS
                ):
                    continue
                records.append(
                    {
                        "group_id": window[0]["group_id"],
                        "source_family": window[0]["source_family"],
                        "artifact_id": window[0]["artifact_id"],
                        "authored_ids": [
                            authored_id
                            for item in window
                            for authored_id in item["authored_ids"]
                        ],
                        "text": text,
                        "raw_text": "\n".join(
                            item["raw_text"] for item in window
                        ),
                        "window_size": window_size,
                    }
                )
    return records


def _candidate_side(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": record["group_id"],
        "source_family": record["source_family"],
        "artifact_id": record["artifact_id"],
        "authored_ids": record["authored_ids"],
        "window_size": record["window_size"],
        "raw_text": record["raw_text"],
    }


def _cross_group_candidates(
    units: list[dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    records = _short_windows(units)
    normalized = [
        _GROUP_VALIDATOR._normal(record["text"]) for record in records
    ]
    grams = [_GROUP_VALIDATOR._grams(record["text"]) for record in records]
    exact_index: dict[
        tuple[str, str],
        list[int],
    ] = defaultdict(list)
    exact_pairs: set[tuple[int, int]] = set()
    for index, text in enumerate(normalized):
        if len(text) < EXACT_NORMALIZED_MIN_CHARS:
            continue
        seen_spans = {
            text[offset : offset + EXACT_NORMALIZED_MIN_CHARS]
            for offset in range(
                len(text) - EXACT_NORMALIZED_MIN_CHARS + 1
            )
        }
        for span in seen_spans:
            key = (records[index]["source_family"], span)
            for prior in exact_index[key]:
                if records[prior]["group_id"] != records[index]["group_id"]:
                    exact_pairs.add((prior, index))
            exact_index[key].append(index)

    exact_candidates: list[dict[str, Any]] = []
    for left_index, right_index in sorted(exact_pairs):
        match = SequenceMatcher(
            None,
            normalized[left_index],
            normalized[right_index],
            autojunk=False,
        ).find_longest_match()
        if match.size < EXACT_NORMALIZED_MIN_CHARS:
            continue
        exact_candidates.append(
            {
                "match_type": "normalized_exact_span",
                "matched_normalized_text": normalized[left_index][
                    match.a : match.a + match.size
                ],
                "normalized_spans": {
                    "left": {
                        "start": match.a,
                        "end": match.a + match.size,
                    },
                    "right": {
                        "start": match.b,
                        "end": match.b + match.size,
                    },
                },
                "left": _candidate_side(records[left_index]),
                "right": _candidate_side(records[right_index]),
            }
        )

    ngram_candidates: list[dict[str, Any]] = []
    for left_index, left in enumerate(records):
        left_grams = grams[left_index]
        if not left_grams:
            continue
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            if (
                left["group_id"] == right["group_id"]
                or left["source_family"] != right["source_family"]
            ):
                continue
            right_grams = grams[right_index]
            if not right_grams:
                continue
            intersection = left_grams & right_grams
            if not intersection:
                continue
            score = len(intersection) / len(left_grams | right_grams)
            if score <= NGRAM_JACCARD:
                continue
            ngram_candidates.append(
                {
                    "match_type": "word_5gram_jaccard",
                    "score": score,
                    "threshold": NGRAM_JACCARD,
                    "shared_ngrams": [
                        list(ngram) for ngram in sorted(intersection)
                    ],
                    "left": _candidate_side(left),
                    "right": _candidate_side(right),
                }
            )
    if exact_candidates:
        findings.append(
            _finding(
                "cross_group_exact",
                "cross-group normalized exact candidates require return",
                candidate_count=len(exact_candidates),
            )
        )
    if ngram_candidates:
        findings.append(
            _finding(
                "cross_group_ngram",
                "cross-group word 5-gram candidates exceed the v2 threshold",
                candidate_count=len(ngram_candidates),
            )
        )
    return {
        "exact": exact_candidates,
        "ngram": ngram_candidates,
    }


def _uniform_density(
    group_reports: list[dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {report["group_id"]: report for report in group_reports}
    source_counts = [
        {
            "group_id": group_id,
            "source_count": by_id.get(group_id, {}).get(
                "source_count",
                0,
            ),
        }
        for group_id in EXPECTED_GROUP_IDS
    ]
    presence = [
        {
            "group_id": group_id,
            "families": [
                family
                for family in FAMILY_ORDER
                if by_id.get(group_id, {})
                .get("families", {})
                .get(family, {})
                .get("present")
            ],
        }
        for group_id in EXPECTED_GROUP_IDS
    ]
    pattern_counts = Counter(
        "+".join(item["families"]) if item["families"] else "(none)"
        for item in presence
    )
    rolling_gaps: list[dict[str, Any]] = []
    for index in range(len(presence) - 2):
        window = presence[index : index + 3]
        present = {
            family for item in window for family in item["families"]
        }
        missing = sorted(set(FAMILY_ORDER) - present)
        if missing:
            rolling_gaps.append(
                {
                    "group_ids": [
                        item["group_id"] for item in window
                    ],
                    "missing_families": missing,
                }
            )
    if rolling_gaps:
        findings.append(
            _finding(
                "rolling_family_coverage",
                "a consecutive three-group window lacks a source family",
                windows=rolling_gaps,
            )
        )
    distinct_totals = sorted(
        {item["source_count"] for item in source_counts}
    )
    if len(group_reports) == len(EXPECTED_GROUP_IDS) and len(
        distinct_totals
    ) <= 1:
        findings.append(
            _finding(
                "uniform_source_density",
                "all groups use the same source count",
                source_count=distinct_totals[0] if distinct_totals else 0,
            )
        )
    body_char_ranges: dict[str, dict[str, int | None]] = {}
    for family in FAMILY_ORDER:
        values = [
            report["families"][family]["body_chars"]
            for report in group_reports
            if report["families"][family]["present"]
        ]
        body_char_ranges[family] = {
            "minimum_nonzero": min(values) if values else None,
            "maximum": max(values) if values else None,
        }
    return {
        "source_counts_by_group": source_counts,
        "family_presence_by_group": presence,
        "distinct_source_totals": distinct_totals,
        "presence_pattern_counts": dict(sorted(pattern_counts.items())),
        "body_char_ranges": body_char_ranges,
        "rolling_three_group_gaps": rolling_gaps,
        "groups_below_family_floor": [
            {
                "group_id": report["group_id"],
                "family": family,
            }
            for report in group_reports
            for family, metrics in report["families"].items()
            if metrics["present"] and not metrics["floor_pass"]
        ],
    }


def validate_global(
    *,
    accepted_dir: Path,
    evidence_dir: Path,
    beats_path: Path,
    output_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Validate all accepted OPC v2 groups and atomically write global QA."""

    root = root.resolve()
    accepted_dir = _resolve_within(accepted_dir, root)
    evidence_dir = _resolve_within(evidence_dir, root)
    beats_path = _resolve_within(beats_path, root)
    output_path = _resolve_within(output_path, root)
    findings: list[dict[str, Any]] = []

    accepted_paths = _json_files(
        accepted_dir,
        label="accepted",
        findings=findings,
    )
    evidence_paths = _json_files(
        evidence_dir,
        label="acceptance_evidence",
        findings=findings,
    )
    accepted_set = _set_evidence(
        code="accepted_group_set",
        label="accepted",
        found=accepted_paths,
        findings=findings,
    )
    evidence_set = _set_evidence(
        code="acceptance_evidence_set",
        label="acceptance evidence",
        found=evidence_paths,
        findings=findings,
    )
    groups, accepted_hashes = _parse_groups(
        accepted_paths,
        findings=findings,
    )

    beats = _read_json_object(
        beats_path,
        code="daily_beats_invalid",
        findings=findings,
    )
    ledger = _ledger_model(beats, findings=findings)

    freshness_entries = [
        _ACCEPTANCE_AUDIT._audit_evidence(path, root=root)
        for _, path in sorted(evidence_paths.items())
    ]
    stale_entries = [
        entry
        for entry in freshness_entries
        if entry.get("status") != "current"
    ]
    if stale_entries:
        findings.append(
            _finding(
                "acceptance_evidence_stale",
                "one or more acceptance evidence records are stale",
                groups=[
                    {
                        "group_id": entry.get("group_id"),
                        "findings": entry.get("findings", []),
                    }
                    for entry in stale_entries
                ],
            )
        )

    timeline = _timeline_evidence(
        groups,
        ledger,
        findings=findings,
    )
    source_counts = _source_counts(
        groups,
        ledger,
        findings=findings,
    )
    fact_ledger, unresolved_continuity_ledger = _story_ledgers(
        beats,
        groups,
        findings=findings,
    )
    uniqueness = _uniqueness_evidence(groups, findings=findings)
    group_reports, detection_units = _group_metrics(
        groups,
        findings=findings,
    )
    cross_group = _cross_group_candidates(
        detection_units,
        findings=findings,
    )
    uniform_density = _uniform_density(
        group_reports,
        findings=findings,
    )

    evidence_hashes = {
        group_id: _sha(path)
        for group_id, path in sorted(evidence_paths.items())
    }
    report = {
        "schema": SCHEMA,
        "status": "draft" if findings else "global_pass",
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "validator": {
            "version": VERSION,
            "detector": {
                "normalization": "opc-84d-v2-deterministic/2",
                "exact_normalized_min_chars": (
                    EXACT_NORMALIZED_MIN_CHARS
                ),
                "ngram_size": NGRAM_SIZE,
                "ngram_jaccard": NGRAM_JACCARD,
                "candidate_scope": (
                    "same-family cross-group mapped body units and "
                    "short adjacent windows up to 3 units"
                ),
            },
            "character_count_policy": "mapped-visible-body/v2",
            "provider_id_namespace": [
                "source_family",
                "provider",
                "normalized_unit_provider_id",
            ],
        },
        "input_hashes": {
            "daily_beats": _sha(beats_path) if beats_path.is_file() else None,
            "accepted_groups": accepted_hashes,
            "acceptance_evidence": evidence_hashes,
        },
        "completeness": {
            "expected_group_ids": list(EXPECTED_GROUP_IDS),
            "accepted_group_ids": accepted_set["group_ids"],
            "evidence_group_ids": evidence_set["group_ids"],
            "missing_accepted": accepted_set["missing"],
            "unexpected_accepted": accepted_set["unexpected"],
            "missing_evidence": evidence_set["missing"],
            "unexpected_evidence": evidence_set["unexpected"],
        },
        "acceptance_freshness": {
            "summary": {
                "total": len(freshness_entries),
                "current": len(freshness_entries) - len(stale_entries),
                "stale": len(stale_entries),
            },
            "entries": freshness_entries,
        },
        "timeline": timeline,
        "source_counts": source_counts,
        "fact_ledger": fact_ledger,
        "unresolved_continuity_ledger": unresolved_continuity_ledger,
        "uniqueness": uniqueness,
        "cross_group_candidates": cross_group,
        "groups": group_reports,
        "uniform_density": uniform_density,
        "findings": findings,
    }
    _ACCEPTANCE_AUDIT._atomic_write(
        output_path,
        (
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accepted-dir",
        type=Path,
        default=EXPERIMENT_ROOT / "accepted",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EXPERIMENT_ROOT / "qa" / "accepted",
    )
    parser.add_argument(
        "--beats",
        type=Path,
        default=EXPERIMENT_ROOT / "daily-beats.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EXPERIMENT_ROOT / "qa" / "global.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Explicit trust root for every input, evidence path, and output.",
    )
    args = parser.parse_args()
    try:
        report = validate_global(
            accepted_dir=args.accepted_dir,
            evidence_dir=args.evidence_dir,
            beats_path=args.beats,
            output_path=args.output,
            root=args.root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {"status": "error", "reason": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "finding_count": len(report["findings"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "global_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
