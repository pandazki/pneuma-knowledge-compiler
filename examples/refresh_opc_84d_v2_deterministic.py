#!/usr/bin/env python3
"""Refresh deterministic QA for every accepted OPC 84-day v2 group."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "examples" / "validate_opc_84d_v2.py"
ValidateInputs = Callable[
    [list[Path], Path, Path, Path, Path | None],
    dict[str, Any],
]


class RefreshError(RuntimeError):
    """The deterministic refresh could not be completed."""


def _load_validate_inputs(validator_path: Path) -> ValidateInputs:
    spec = importlib.util.spec_from_file_location(
        "opc_84d_v2_validator_for_refresh",
        validator_path,
    )
    if spec is None or spec.loader is None:
        raise RefreshError(f"cannot load validator: {validator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate_inputs = getattr(module, "validate_inputs", None)
    if not callable(validate_inputs):
        raise RefreshError("validator does not expose validate_inputs")
    return validate_inputs


def refresh_deterministic_reports(
    *,
    accepted_dir: Path,
    groups_dir: Path,
    output_dir: Path,
    schema_path: Path,
    beats_path: Path,
    validate_inputs: ValidateInputs | None = None,
    validator_path: Path = VALIDATOR,
) -> dict[str, Any]:
    for path, label in (
        (accepted_dir, "accepted directory"),
        (groups_dir, "groups directory"),
        (schema_path, "schema"),
        (beats_path, "daily beats"),
    ):
        exists = path.is_dir() if "directory" in label else path.is_file()
        if not exists:
            raise RefreshError(f"{label} is missing: {path}")
    accepted_paths = sorted(accepted_dir.glob("G*.json"))
    if not accepted_paths:
        raise RefreshError(f"accepted directory has no group JSON: {accepted_dir}")
    validate = validate_inputs or _load_validate_inputs(validator_path)
    results: list[dict[str, Any]] = []

    for accepted_path in accepted_paths:
        group_id = accepted_path.stem
        group_path = groups_dir / accepted_path.name
        if not group_path.is_file():
            raise RefreshError(
                f"current authored group is missing for {group_id}: {group_path}"
            )
        output_path = output_dir / accepted_path.name
        prior_paths = [
            prior
            for prior in accepted_paths
            if prior.name != accepted_path.name
        ]
        with tempfile.TemporaryDirectory(
            prefix=f"opc-84d-v2-{group_id}-priors-"
        ) as temporary_name:
            prior_dir = Path(temporary_name) / "accepted"
            prior_dir.mkdir()
            for prior_path in prior_paths:
                (prior_dir / prior_path.name).write_bytes(prior_path.read_bytes())
            report = validate(
                [group_path],
                schema_path,
                prior_dir,
                output_path,
                beats_path,
            )
        findings = report.get("findings")
        finding_list = findings if isinstance(findings, list) else []
        passed = report.get("status") == "structural_pass" and not finding_list
        results.append(
            {
                "group_id": group_id,
                "status": "structural_pass" if passed else "draft",
                "finding_count": len(finding_list),
                "finding_codes": sorted(
                    {
                        finding.get("code", "unknown")
                        for finding in finding_list
                        if isinstance(finding, dict)
                    }
                ),
                "output": str(output_path),
                "prior_group_ids": [path.stem for path in prior_paths],
            }
        )

    failed = sum(result["status"] != "structural_pass" for result in results)
    return {
        "status": "draft" if failed else "structural_pass",
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
        },
        "groups": results,
    }


def main() -> int:
    base = ROOT / "docs/experiments/opc-84d-v2"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accepted-dir",
        type=Path,
        default=base / "accepted",
    )
    parser.add_argument(
        "--groups-dir",
        type=Path,
        default=base / "groups",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=base / "qa/deterministic",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=base / "group-content.schema.json",
    )
    parser.add_argument(
        "--beats",
        type=Path,
        default=base / "daily-beats.json",
    )
    parser.add_argument(
        "--validator",
        type=Path,
        default=VALIDATOR,
    )
    args = parser.parse_args()
    try:
        result = refresh_deterministic_reports(
            accepted_dir=args.accepted_dir,
            groups_dir=args.groups_dir,
            output_dir=args.output_dir,
            schema_path=args.schema,
            beats_path=args.beats,
            validator_path=args.validator,
        )
    except (OSError, RefreshError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "error", "reason": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "structural_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
