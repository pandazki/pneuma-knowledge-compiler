from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "refresh_opc_84d_v2_deterministic.py"


def _load_refresher():
    spec = importlib.util.spec_from_file_location(
        "opc_84d_v2_deterministic_refresher",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path, bodies: dict[str, str]) -> dict[str, Path]:
    paths = {
        "groups": tmp_path / "groups",
        "accepted": tmp_path / "accepted",
        "deterministic": tmp_path / "qa" / "deterministic",
        "schema": tmp_path / "group-content.schema.json",
        "beats": tmp_path / "daily-beats.json",
    }
    paths["groups"].mkdir()
    paths["accepted"].mkdir()
    for group_id, body in bodies.items():
        value = json.dumps(
            {"group_id": group_id, "body": body},
            sort_keys=True,
        ).encode()
        (paths["groups"] / f"{group_id}.json").write_bytes(value)
        (paths["accepted"] / f"{group_id}.json").write_bytes(value)
    paths["schema"].write_text('{"type":"object"}\n', encoding="utf-8")
    paths["beats"].write_text('{"days":[]}\n', encoding="utf-8")
    return paths


def _fake_validator(calls: list[dict]):
    def validate_inputs(
        group_paths: list[Path],
        schema_path: Path,
        accepted_dir: Path,
        output_path: Path,
        beats_path: Path,
    ) -> dict:
        current = json.loads(group_paths[0].read_text(encoding="utf-8"))
        priors = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(accepted_dir.glob("G*.json"))
        ]
        calls.append(
            {
                "group_id": current["group_id"],
                "prior_ids": [prior["group_id"] for prior in priors],
            }
        )
        duplicate = next(
            (
                prior
                for prior in priors
                if prior["body"] == current["body"]
            ),
            None,
        )
        findings = (
            [
                {
                    "code": "duplicate_cross_group",
                    "severity": "error",
                    "message": (
                        f"{current['group_id']} duplicates "
                        f"{duplicate['group_id']}"
                    ),
                }
            ]
            if duplicate
            else []
        )
        report = {
            "status": "draft" if findings else "structural_pass",
            "input_hashes": {
                str(group_paths[0]): hashlib.sha256(
                    group_paths[0].read_bytes()
                ).hexdigest(),
                str(beats_path): hashlib.sha256(
                    beats_path.read_bytes()
                ).hexdigest(),
            },
            "schema_hash": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            "findings": findings,
            "groups": [
                {
                    "group_id": current["group_id"],
                    "findings": findings,
                }
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report), encoding="utf-8")
        return report

    return validate_inputs


def test_refresh_excludes_self_and_uses_every_other_accepted_group(
    tmp_path: Path,
) -> None:
    paths = _fixture(
        tmp_path,
        {"G01": "one", "G02": "two", "G03": "three"},
    )
    calls: list[dict] = []
    module = _load_refresher()

    summary = module.refresh_deterministic_reports(
        accepted_dir=paths["accepted"],
        groups_dir=paths["groups"],
        output_dir=paths["deterministic"],
        schema_path=paths["schema"],
        beats_path=paths["beats"],
        validate_inputs=_fake_validator(calls),
    )

    assert summary["status"] == "structural_pass"
    assert summary["summary"] == {"total": 3, "passed": 3, "failed": 0}
    assert calls == [
        {"group_id": "G01", "prior_ids": ["G02", "G03"]},
        {"group_id": "G02", "prior_ids": ["G01", "G03"]},
        {"group_id": "G03", "prior_ids": ["G01", "G02"]},
    ]


def test_refresh_preserves_cross_group_duplicate_findings(
    tmp_path: Path,
) -> None:
    paths = _fixture(
        tmp_path,
        {"G01": "same body", "G02": "same body"},
    )
    module = _load_refresher()

    summary = module.refresh_deterministic_reports(
        accepted_dir=paths["accepted"],
        groups_dir=paths["groups"],
        output_dir=paths["deterministic"],
        schema_path=paths["schema"],
        beats_path=paths["beats"],
        validate_inputs=_fake_validator([]),
    )

    assert summary["status"] == "draft"
    assert summary["summary"] == {"total": 2, "passed": 0, "failed": 2}
    for group_id in ("G01", "G02"):
        report = json.loads(
            (paths["deterministic"] / f"{group_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert report["status"] == "draft"
        assert report["findings"][0]["code"] == "duplicate_cross_group"


def test_refresh_cli_exits_zero_when_all_groups_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _fixture(tmp_path, {"G01": "one", "G02": "two"})
    module = _load_refresher()
    monkeypatch.setattr(
        module,
        "_load_validate_inputs",
        lambda _: _fake_validator([]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--accepted-dir",
            str(paths["accepted"]),
            "--groups-dir",
            str(paths["groups"]),
            "--output-dir",
            str(paths["deterministic"]),
            "--schema",
            str(paths["schema"]),
            "--beats",
            str(paths["beats"]),
        ],
    )

    assert module.main() == 0
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["status"]
        == "structural_pass"
        for path in paths["deterministic"].glob("G*.json")
    )
