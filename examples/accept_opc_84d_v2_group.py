#!/usr/bin/env python3
"""Fail-closed acceptance for one reviewed OPC 84-day v2 group."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
EXPECTED_DETECTOR_VERSION = "opc-84d-v2-deterministic/3"
REVIEW_METADATA_ALIASES = {
    "verdict": "verdict",
    "decision": "verdict",
    "结论": "verdict",
    "最终结论": "verdict",
    "reviewer": "reviewer",
    "复审者": "reviewer",
    "审稿人": "reviewer",
    "independence": "independence",
    "reviewer role": "independence",
    "独立性": "independence",
    "reviewed at": "reviewed_at",
    "reviewed at (utc)": "reviewed_at",
    "reviewed_at": "reviewed_at",
    "复审时间": "reviewed_at",
    "审稿时间": "reviewed_at",
    "审稿时间（utc）": "reviewed_at",
}
REVIEW_VERDICT_LABELS = {
    label
    for label, canonical in REVIEW_METADATA_ALIASES.items()
    if canonical == "verdict"
}
REVIEW_LIST_METADATA_RE = re.compile(
    r"^\s*-\s*(?P<label>"
    + "|".join(
        re.escape(label)
        for label in sorted(REVIEW_METADATA_ALIASES, key=len, reverse=True)
    )
    + r")\s*[:：]\s*(?P<value>\S.*?)\s*$",
    re.IGNORECASE,
)
REVIEW_VERDICT_HEADER_RE = re.compile(
    r"^\s*##\s+(?P<label>"
    + "|".join(
        re.escape(label)
        for label in sorted(REVIEW_VERDICT_LABELS, key=len, reverse=True)
    )
    + r")\s*[:：]\s*(?P<value>\S.*?)\s*$",
    re.IGNORECASE,
)


class AcceptanceError(RuntimeError):
    """The candidate lacks current, independent acceptance evidence."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_path(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise AcceptanceError(f"{label} is missing or is not a file: {path}")


def _resolve_report_input(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _parse_review_metadata(review_text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in review_text.splitlines():
        match = REVIEW_LIST_METADATA_RE.fullmatch(line)
        if match is None:
            match = REVIEW_VERDICT_HEADER_RE.fullmatch(line)
        if match is None:
            continue
        label = re.sub(r"\s+", " ", match.group("label").strip()).casefold()
        canonical = REVIEW_METADATA_ALIASES[label]
        if canonical in metadata:
            raise AcceptanceError(f"duplicate review {canonical} metadata")
        metadata[canonical] = match.group("value").strip()
    return metadata


def _parse_review(
    review_text: str,
    *,
    group_name: str,
    group_sha256: str,
) -> dict[str, Any]:
    metadata = _parse_review_metadata(review_text)

    verdict_metadata = metadata.get("verdict")
    if verdict_metadata is None:
        raise AcceptanceError("review verdict metadata is missing")
    verdict_match = re.fullmatch(
        r"(?:\*\*(PASS|RETURN)\*\*|(PASS|RETURN))",
        verdict_metadata,
        re.IGNORECASE,
    )
    if verdict_match is None:
        raise AcceptanceError("review verdict metadata is invalid")
    verdict = (verdict_match.group(1) or verdict_match.group(2)).upper()
    if verdict != "PASS":
        raise AcceptanceError(f"review verdict must be PASS, got {verdict}")

    reviewer_metadata = metadata.get("reviewer")
    if reviewer_metadata is None:
        raise AcceptanceError("reviewer metadata is missing")
    reviewer = re.split(r"[（(]", reviewer_metadata, maxsplit=1)[0].strip()
    if not reviewer:
        raise AcceptanceError("reviewer identity is empty")

    independence_metadata = metadata.get("independence")
    attestation = re.search(
        r"(?i)(非\s*(?:G\d+\s*)?作者|未参与.{0,20}(?:创作|撰写)|"
        r"non[-\s]?author|not\s+(?:the\s+)?author|did\s+not\s+author)",
        "\n".join(
            value
            for value in (reviewer_metadata, independence_metadata)
            if value is not None
        ),
    )
    if attestation is None:
        raise AcceptanceError(
            "review metadata cannot prove reviewer is not the author"
        )
    non_author_attested = True
    non_author_evidence = attestation.group(0)

    reviewed_at_metadata = metadata.get("reviewed_at")
    if reviewed_at_metadata is None:
        raise AcceptanceError("review timestamp metadata is missing")
    reviewed_at_match = re.fullmatch(
        r"(?:`([^`\s]+)`|([^`\s]+))",
        reviewed_at_metadata,
    )
    if reviewed_at_match is None:
        raise AcceptanceError("review timestamp metadata is invalid")
    reviewed_at = reviewed_at_match.group(1) or reviewed_at_match.group(2)
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise AcceptanceError("review timestamp is not ISO-8601") from error

    group_hash_row = re.compile(
        rf"(?mi)^\s*\|\s*`groups/{re.escape(group_name)}`\s*\|\s*"
        rf"`?({SHA256_RE.pattern})`?\s*\|\s*$"
    )
    review_hashes = {
        match.group(1).lower()
        for match in group_hash_row.finditer(review_text)
    }
    if not review_hashes:
        raise AcceptanceError("review group hash metadata is missing")
    if review_hashes != {group_sha256}:
        raise AcceptanceError(
            "review group hash does not match the current group bytes"
        )
    return {
        "verdict": verdict,
        "reviewer": reviewer,
        "reviewer_metadata": reviewer_metadata,
        "independence_metadata": independence_metadata,
        "reviewed_at": reviewed_at,
        "non_author_attested": non_author_attested,
        "non_author_evidence": non_author_evidence,
        "recorded_group_sha256": group_sha256,
    }


def _validate_deterministic(
    report: dict[str, Any],
    *,
    group_path: Path,
    group_sha256: str,
    beats_path: Path,
    schema_path: Path,
) -> None:
    detector = report.get("detector")
    detector_version = (
        detector.get("version") if isinstance(detector, dict) else None
    )
    if detector_version != EXPECTED_DETECTOR_VERSION:
        raise AcceptanceError(
            "deterministic detector version must be "
            f"{EXPECTED_DETECTOR_VERSION}, got {detector_version!r}"
        )
    if report.get("status") != "structural_pass":
        raise AcceptanceError(
            "deterministic status must be structural_pass"
        )
    findings = report.get("findings")
    if not isinstance(findings, list) or findings:
        raise AcceptanceError("deterministic findings must be an empty list")
    group_reports = report.get("groups")
    if not isinstance(group_reports, list) or not group_reports:
        raise AcceptanceError("deterministic per-group evidence is missing")
    if any(item.get("findings") for item in group_reports):
        raise AcceptanceError(
            "deterministic per-group findings must all be empty"
        )

    input_hashes = report.get("input_hashes")
    if not isinstance(input_hashes, dict) or not input_hashes:
        raise AcceptanceError("deterministic input hashes are missing")
    group_seen = False
    beats_seen = False
    for raw_path, recorded_hash in input_hashes.items():
        if not isinstance(raw_path, str) or not isinstance(recorded_hash, str):
            raise AcceptanceError("deterministic input hash entry is invalid")
        current_path = _resolve_report_input(raw_path)
        _require_file(current_path, "deterministic input")
        current_hash = _sha_path(current_path)
        if current_hash != recorded_hash.lower():
            raise AcceptanceError(
                f"deterministic input hash is stale for {raw_path}"
            )
        resolved = current_path.resolve()
        group_seen = group_seen or (
            resolved == group_path.resolve() and current_hash == group_sha256
        )
        beats_seen = beats_seen or resolved == beats_path.resolve()
    if not group_seen:
        raise AcceptanceError(
            "deterministic input hashes do not bind the current group"
        )
    if not beats_seen:
        raise AcceptanceError(
            "deterministic input hashes do not bind the supplied beats ledger"
        )
    if report.get("schema_hash") != _sha_path(schema_path):
        raise AcceptanceError(
            "deterministic schema hash does not match the current schema"
        )


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def accept_group(
    *,
    group_path: Path,
    report_path: Path,
    review_path: Path,
    beats_path: Path,
    schema_path: Path,
    rubric_path: Path,
    story_path: Path,
    accepted_dir: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    inputs = {
        "group": group_path,
        "deterministic_report": report_path,
        "independent_review": review_path,
        "daily_beats": beats_path,
        "schema": schema_path,
        "qa_rubric": rubric_path,
        "story_bible": story_path,
    }
    for label, path in inputs.items():
        _require_file(path, label)

    group_bytes = group_path.read_bytes()
    report_bytes = report_path.read_bytes()
    review_bytes = review_path.read_bytes()
    try:
        group = json.loads(group_bytes)
        report = json.loads(report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError("group or deterministic report is invalid JSON") from error
    group_id = group.get("group_id")
    if not isinstance(group_id, str) or not re.fullmatch(r"G\d{2,}", group_id):
        raise AcceptanceError("group_id must be a stable Gxx identifier")
    if group_path.stem != group_id:
        raise AcceptanceError("group filename does not match group_id")

    group_sha256 = _sha_bytes(group_bytes)
    _validate_deterministic(
        report,
        group_path=group_path,
        group_sha256=group_sha256,
        beats_path=beats_path,
        schema_path=schema_path,
    )
    try:
        review_text = review_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AcceptanceError("independent review is not UTF-8") from error
    review = _parse_review(
        review_text,
        group_name=group_path.name,
        group_sha256=group_sha256,
    )

    snapshots = {
        label: {
            "path": _portable_path(path),
            "sha256": (
                group_sha256
                if label == "group"
                else _sha_bytes(report_bytes)
                if label == "deterministic_report"
                else _sha_bytes(review_bytes)
                if label == "independent_review"
                else _sha_path(path)
            ),
        }
        for label, path in inputs.items()
    }
    for label, item in snapshots.items():
        if _sha_path(inputs[label]) != item["sha256"]:
            raise AcceptanceError(
                f"{label} changed during acceptance validation"
            )

    accepted_path = accepted_dir / f"{group_id}.json"
    evidence_path = evidence_dir / f"{group_id}.json"
    if accepted_path.exists() and accepted_path.read_bytes() != group_bytes:
        raise AcceptanceError(
            "accepted destination already contains different bytes"
        )
    accepted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    evidence: dict[str, Any] = {
        "schema": "pneuma.experiment.opc-84d-v2.acceptance/v1",
        "status": "accepted",
        "group_id": group_id,
        "accepted_at": accepted_at,
        "group_sha256": group_sha256,
        "accepted_copy": {
            "path": _portable_path(accepted_path),
            "sha256": group_sha256,
            "byte_identical": True,
        },
        "deterministic": {
            "path": _portable_path(report_path),
            "sha256": snapshots["deterministic_report"]["sha256"],
            "status": report["status"],
            "finding_count": len(report["findings"]),
            "detector_version": report.get("detector", {}).get("version"),
        },
        "review": {
            "path": _portable_path(review_path),
            "sha256": snapshots["independent_review"]["sha256"],
            **review,
        },
        "inputs": snapshots,
    }
    evidence_bytes = (
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(accepted_path, group_bytes)
    if accepted_path.read_bytes() != group_bytes:
        raise AcceptanceError("accepted copy is not byte-identical")
    _atomic_write(evidence_path, evidence_bytes)
    return evidence


def main() -> int:
    base = ROOT / "docs/experiments/opc-84d-v2"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", type=Path)
    parser.add_argument("--deterministic", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--beats", type=Path, default=base / "daily-beats.json")
    parser.add_argument(
        "--schema",
        type=Path,
        default=base / "group-content.schema.json",
    )
    parser.add_argument("--rubric", type=Path, default=base / "qa-rubric.md")
    parser.add_argument("--story", type=Path, default=base / "story-bible.md")
    parser.add_argument("--accepted-dir", type=Path, default=base / "accepted")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=base / "qa/accepted",
    )
    args = parser.parse_args()
    try:
        evidence = accept_group(
            group_path=args.group,
            report_path=args.deterministic,
            review_path=args.review,
            beats_path=args.beats,
            schema_path=args.schema,
            rubric_path=args.rubric,
            story_path=args.story,
            accepted_dir=args.accepted_dir,
            evidence_dir=args.evidence_dir,
        )
    except (AcceptanceError, OSError) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "group_id": evidence["group_id"],
                "accepted_copy": evidence["accepted_copy"]["path"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
