#!/usr/bin/env python3
"""Read-only freshness audit for OPC 84-day v2 acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_INPUTS = (
    "group",
    "deterministic_report",
    "independent_review",
    "daily_beats",
    "schema",
    "qa_rubric",
    "story_bible",
)
ACCEPTANCE_SCHEMA = "pneuma.experiment.opc-84d-v2.acceptance/v1"
EXPECTED_DETECTOR_VERSION = "opc-84d-v2-deterministic/3"


class _EvidencePathOutsideRootError(ValueError):
    """An acceptance record points outside its caller-supplied trust root."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resolve_path(raw_path: str, root: Path) -> Path:
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


def _portable_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _finding(
    field: str,
    code: str,
    *,
    path: str | None = None,
    recorded: Any = None,
    current: Any = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {"field": field, "code": code}
    if path is not None:
        finding["path"] = path
    if recorded is not None:
        finding["recorded"] = recorded
    if current is not None:
        finding["current"] = current
    return finding


def _is_canonical_input_path(
    path: Path,
    *,
    experiment_root: Path,
    group_id: str,
    label: str,
) -> bool:
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
    return path == expected[label].resolve()


def _audit_snapshot(
    *,
    evidence: dict[str, Any],
    label: str,
    experiment_root: Path,
    group_id: str,
    root: Path,
    findings: list[dict[str, Any]],
) -> tuple[dict[str, Any], Path | None, bytes | None]:
    field = f"inputs.{label}"
    inputs = evidence.get("inputs")
    snapshot = inputs.get(label) if isinstance(inputs, dict) else None
    if not isinstance(snapshot, dict):
        findings.append(_finding(field, "metadata_missing"))
        return {"status": "stale"}, None, None
    raw_path = snapshot.get("path")
    recorded_sha = snapshot.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        findings.append(_finding(f"{field}.path", "metadata_missing"))
        return {"status": "stale"}, None, None
    check: dict[str, Any] = {
        "path": raw_path,
        "recorded_sha256": recorded_sha,
    }
    try:
        path = _resolve_path(raw_path, root)
    except _EvidencePathOutsideRootError:
        findings.append(
            _finding(
                f"{field}.path",
                "path_outside_root",
                path=raw_path,
            )
        )
        check["status"] = "stale"
        return check, None, None
    canonical = _is_canonical_input_path(
        path,
        experiment_root=experiment_root,
        group_id=group_id,
        label=label,
    )
    if not canonical:
        findings.append(
            _finding(
                f"{field}.path",
                "path_mismatch",
                recorded=raw_path,
            )
        )
    if not path.is_file():
        findings.append(
            _finding(
                f"{field}.path",
                "file_missing",
                path=raw_path,
            )
        )
        check["status"] = "stale"
        return check, path, None
    value = path.read_bytes()
    current_sha = _sha_bytes(value)
    check["current_sha256"] = current_sha
    if not isinstance(recorded_sha, str):
        findings.append(
            _finding(
                f"{field}.sha256",
                "metadata_missing",
                path=raw_path,
                current=current_sha,
            )
        )
    elif recorded_sha.lower() != current_sha:
        findings.append(
            _finding(
                f"{field}.sha256",
                "hash_mismatch",
                path=raw_path,
                recorded=recorded_sha,
                current=current_sha,
            )
        )
    check["status"] = (
        "current"
        if canonical
        and isinstance(recorded_sha, str)
        and recorded_sha.lower() == current_sha
        else "stale"
    )
    return check, path, value


def _audit_mirrored_snapshot(
    *,
    evidence: dict[str, Any],
    section: str,
    current_path: Path | None,
    current_bytes: bytes | None,
    root: Path,
    findings: list[dict[str, Any]],
) -> None:
    snapshot = evidence.get(section)
    if not isinstance(snapshot, dict):
        findings.append(_finding(section, "metadata_missing"))
        return
    raw_path = snapshot.get("path")
    recorded_sha = snapshot.get("sha256")
    if not isinstance(raw_path, str):
        findings.append(_finding(f"{section}.path", "metadata_missing"))
    else:
        try:
            resolved_path = _resolve_path(raw_path, root)
        except _EvidencePathOutsideRootError:
            findings.append(
                _finding(
                    f"{section}.path",
                    "path_outside_root",
                    path=raw_path,
                )
            )
        else:
            if current_path is not None and resolved_path != current_path:
                findings.append(
                    _finding(
                        f"{section}.path",
                        "path_mismatch",
                        recorded=raw_path,
                        current=str(current_path),
                    )
                )
    current_sha = _sha_bytes(current_bytes) if current_bytes is not None else None
    if not isinstance(recorded_sha, str):
        findings.append(
            _finding(
                f"{section}.sha256",
                "metadata_missing",
                current=current_sha,
            )
        )
    elif current_sha is not None and recorded_sha.lower() != current_sha:
        findings.append(
            _finding(
                f"{section}.sha256",
                "hash_mismatch",
                path=raw_path if isinstance(raw_path, str) else None,
                recorded=recorded_sha,
                current=current_sha,
            )
        )


def _audit_deterministic(
    *,
    value: bytes | None,
    group_id: str,
    findings: list[dict[str, Any]],
) -> None:
    if value is None:
        return
    try:
        report = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        findings.append(_finding("deterministic.json", "invalid_json"))
        return
    if not isinstance(report, dict):
        findings.append(_finding("deterministic.json", "invalid_shape"))
        return
    detector = report.get("detector")
    detector_version = (
        detector.get("version") if isinstance(detector, dict) else None
    )
    if detector_version != EXPECTED_DETECTOR_VERSION:
        findings.append(
            _finding(
                "deterministic.detector.version",
                "obsolete_detector",
                recorded=EXPECTED_DETECTOR_VERSION,
                current=detector_version,
            )
        )
    status = report.get("status")
    if status != "structural_pass":
        findings.append(
            _finding(
                "deterministic.status",
                "invalid_status",
                recorded="structural_pass",
                current=status,
            )
        )
    report_findings = report.get("findings")
    if not isinstance(report_findings, list) or report_findings:
        findings.append(
            _finding(
                "deterministic.findings",
                "not_empty",
                recorded=[],
                current=report_findings,
            )
        )
    groups = report.get("groups")
    if (
        not isinstance(groups, list)
        or not groups
        or any(
            not isinstance(group, dict)
            or group.get("group_id") != group_id
            or not isinstance(group.get("findings"), list)
            or group["findings"]
            for group in groups
        )
    ):
        findings.append(
            _finding(
                "deterministic.groups.findings",
                "not_empty_or_missing",
                current=groups,
            )
        )


def _audit_evidence(
    evidence_path: Path,
    *,
    root: Path,
) -> dict[str, Any]:
    try:
        resolved_evidence_path = _resolve_path(str(evidence_path), root)
    except _EvidencePathOutsideRootError:
        finding = _finding(
            "evidence_path",
            "path_outside_root",
            path=str(evidence_path),
        )
        return {
            "group_id": evidence_path.stem,
            "evidence_path": _portable_path(evidence_path, root),
            "status": "stale",
            "checks": {},
            "findings": [finding],
        }
    try:
        evidence = json.loads(resolved_evidence_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        finding = _finding("evidence", "invalid_or_unreadable_json")
        return {
            "group_id": evidence_path.stem,
            "evidence_path": _portable_path(evidence_path, root),
            "status": "stale",
            "checks": {},
            "findings": [finding],
        }
    if not isinstance(evidence, dict):
        finding = _finding("evidence", "invalid_shape")
        return {
            "group_id": evidence_path.stem,
            "evidence_path": _portable_path(evidence_path, root),
            "status": "stale",
            "checks": {},
            "findings": [finding],
        }

    group_id = evidence_path.stem
    experiment_root = evidence_path.parents[2].resolve()
    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    if evidence.get("schema") != ACCEPTANCE_SCHEMA:
        findings.append(
            _finding(
                "schema",
                "invalid_schema",
                recorded=ACCEPTANCE_SCHEMA,
                current=evidence.get("schema"),
            )
        )
    if evidence.get("status") != "accepted":
        findings.append(
            _finding(
                "status",
                "invalid_status",
                recorded="accepted",
                current=evidence.get("status"),
            )
        )
    if evidence.get("group_id") != group_id:
        findings.append(
            _finding(
                "group_id",
                "filename_mismatch",
                recorded=group_id,
                current=evidence.get("group_id"),
            )
        )

    resolved: dict[str, Path | None] = {}
    contents: dict[str, bytes | None] = {}
    for label in REQUIRED_INPUTS:
        check, path, value = _audit_snapshot(
            evidence=evidence,
            label=label,
            experiment_root=experiment_root,
            group_id=group_id,
            root=root,
            findings=findings,
        )
        checks[label] = check
        resolved[label] = path
        contents[label] = value

    _audit_mirrored_snapshot(
        evidence=evidence,
        section="deterministic",
        current_path=resolved["deterministic_report"],
        current_bytes=contents["deterministic_report"],
        root=root,
        findings=findings,
    )
    _audit_mirrored_snapshot(
        evidence=evidence,
        section="review",
        current_path=resolved["independent_review"],
        current_bytes=contents["independent_review"],
        root=root,
        findings=findings,
    )

    group_bytes = contents["group"]
    current_group_sha = _sha_bytes(group_bytes) if group_bytes is not None else None
    recorded_group_sha = evidence.get("group_sha256")
    if not isinstance(recorded_group_sha, str):
        findings.append(
            _finding(
                "group_sha256",
                "metadata_missing",
                current=current_group_sha,
            )
        )
    elif (
        current_group_sha is not None
        and recorded_group_sha.lower() != current_group_sha
    ):
        findings.append(
            _finding(
                "group_sha256",
                "hash_mismatch",
                recorded=recorded_group_sha,
                current=current_group_sha,
            )
        )

    review = evidence.get("review")
    if not isinstance(review, dict):
        findings.append(_finding("review", "metadata_missing"))
    else:
        if review.get("verdict") != "PASS":
            findings.append(
                _finding(
                    "review.verdict",
                    "invalid_verdict",
                    recorded="PASS",
                    current=review.get("verdict"),
                )
            )
        if review.get("non_author_attested") is not True:
            findings.append(
                _finding(
                    "review.non_author_attested",
                    "not_attested",
                    recorded=True,
                    current=review.get("non_author_attested"),
                )
            )
    review_group_sha = (
        review.get("recorded_group_sha256")
        if isinstance(review, dict)
        else None
    )
    if not isinstance(review_group_sha, str):
        findings.append(
            _finding(
                "review.recorded_group_sha256",
                "metadata_missing",
                current=current_group_sha,
            )
        )
    elif current_group_sha is not None and review_group_sha.lower() != current_group_sha:
        findings.append(
            _finding(
                "review.recorded_group_sha256",
                "hash_mismatch",
                recorded=review_group_sha,
                current=current_group_sha,
            )
        )

    accepted = evidence.get("accepted_copy")
    accepted_check: dict[str, Any] = {"status": "stale"}
    accepted_bytes: bytes | None = None
    accepted_path_canonical = False
    if not isinstance(accepted, dict):
        findings.append(_finding("accepted_copy", "metadata_missing"))
    else:
        raw_path = accepted.get("path")
        recorded_sha = accepted.get("sha256")
        accepted_check.update(
            {
                "path": raw_path,
                "recorded_sha256": recorded_sha,
            }
        )
        if not isinstance(raw_path, str) or not raw_path:
            findings.append(_finding("accepted_copy.path", "metadata_missing"))
        else:
            try:
                accepted_path = _resolve_path(raw_path, root)
            except _EvidencePathOutsideRootError:
                findings.append(
                    _finding(
                        "accepted_copy.path",
                        "path_outside_root",
                        path=raw_path,
                    )
                )
            else:
                expected_accepted_path = (
                    experiment_root / "accepted" / f"{group_id}.json"
                ).resolve()
                accepted_path_canonical = accepted_path == expected_accepted_path
                if not accepted_path_canonical:
                    findings.append(
                        _finding(
                            "accepted_copy.path",
                            "path_mismatch",
                            recorded=raw_path,
                            current=str(expected_accepted_path),
                        )
                    )
                if not accepted_path.is_file():
                    findings.append(
                        _finding(
                            "accepted_copy.path",
                            "file_missing",
                            path=raw_path,
                        )
                    )
                else:
                    accepted_bytes = accepted_path.read_bytes()
                    current_sha = _sha_bytes(accepted_bytes)
                    accepted_check["current_sha256"] = current_sha
                    if not isinstance(recorded_sha, str):
                        findings.append(
                            _finding(
                                "accepted_copy.sha256",
                                "metadata_missing",
                                path=raw_path,
                                current=current_sha,
                            )
                        )
                    elif recorded_sha.lower() != current_sha:
                        findings.append(
                            _finding(
                                "accepted_copy.sha256",
                                "hash_mismatch",
                                path=raw_path,
                                recorded=recorded_sha,
                                current=current_sha,
                            )
                        )
        if accepted.get("byte_identical") is not True:
            findings.append(
                _finding(
                    "accepted_copy.byte_identical",
                    "not_attested",
                    recorded=True,
                    current=accepted.get("byte_identical"),
                )
            )
        byte_identical = (
            group_bytes is not None
            and accepted_bytes is not None
            and group_bytes == accepted_bytes
        )
        accepted_check["byte_identical"] = byte_identical
        if not byte_identical:
            findings.append(
                _finding(
                    "accepted_copy.byte_identical",
                    "byte_mismatch",
                    recorded=True,
                    current=byte_identical,
                )
            )
        accepted_check["status"] = (
            "current"
            if accepted_path_canonical
            and byte_identical
            and isinstance(recorded_sha, str)
            and accepted_bytes is not None
            and recorded_sha.lower() == _sha_bytes(accepted_bytes)
            else "stale"
        )
    checks["accepted_copy"] = accepted_check

    deterministic = evidence.get("deterministic")
    if not isinstance(deterministic, dict):
        findings.append(_finding("deterministic", "metadata_missing"))
    else:
        detector_version = deterministic.get("detector_version")
        if detector_version != EXPECTED_DETECTOR_VERSION:
            findings.append(
                _finding(
                    "deterministic.detector_version",
                    "obsolete_detector",
                    recorded=EXPECTED_DETECTOR_VERSION,
                    current=detector_version,
                )
            )
        if deterministic.get("status") != "structural_pass":
            findings.append(
                _finding(
                    "deterministic.status",
                    "invalid_status",
                    recorded="structural_pass",
                    current=deterministic.get("status"),
                )
            )
        if deterministic.get("finding_count") != 0:
            findings.append(
                _finding(
                    "deterministic.finding_count",
                    "not_zero",
                    recorded=0,
                    current=deterministic.get("finding_count"),
                )
            )
    _audit_deterministic(
        value=contents["deterministic_report"],
        group_id=group_id,
        findings=findings,
    )
    return {
        "group_id": group_id,
        "evidence_path": _portable_path(evidence_path, root),
        "status": "stale" if findings else "current",
        "checks": checks,
        "findings": findings,
    }


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


def audit_acceptances(
    *,
    evidence_dir: Path,
    output_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    top_findings: list[dict[str, Any]] = []
    try:
        evidence_dir = _resolve_path(str(evidence_dir), root)
    except _EvidencePathOutsideRootError:
        evidence_paths: list[Path] = []
        top_findings.append(
            _finding(
                "evidence_dir",
                "path_outside_root",
                path=str(evidence_dir),
            )
        )
    else:
        if not evidence_dir.is_dir():
            evidence_paths = []
            top_findings.append(
                _finding(
                    "evidence_dir",
                    "directory_missing",
                    path=str(evidence_dir),
                )
            )
        else:
            evidence_paths = sorted(evidence_dir.glob("*.json"))
            if not evidence_paths:
                top_findings.append(
                    _finding(
                        "evidence_dir",
                        "no_acceptance_evidence",
                        path=str(evidence_dir),
                    )
                )
    entries = [
        _audit_evidence(evidence_path, root=root)
        for evidence_path in evidence_paths
    ]
    stale_count = sum(entry["status"] == "stale" for entry in entries)
    status = "stale" if top_findings or stale_count else "current"
    report = {
        "schema": "pneuma.experiment.opc-84d-v2.acceptance-audit/v1",
        "status": status,
        "audited_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "evidence_dir": _portable_path(evidence_dir, root),
        "summary": {
            "total": len(entries),
            "current": len(entries) - stale_count,
            "stale": stale_count,
        },
        "findings": top_findings,
        "entries": entries,
    }
    _atomic_write(
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
    base = ROOT / "docs/experiments/opc-84d-v2"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=base / "qa/accepted",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base / "qa/acceptance-audit.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Explicit trust root for all acceptance evidence paths.",
    )
    args = parser.parse_args()
    try:
        report = audit_acceptances(
            evidence_dir=args.evidence_dir,
            output_path=args.output,
            root=args.root,
        )
    except OSError as error:
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
                "summary": report["summary"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
