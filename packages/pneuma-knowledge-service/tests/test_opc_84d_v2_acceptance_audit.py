from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "audit_opc_84d_v2_acceptance.py"


def _load_auditor():
    spec = importlib.util.spec_from_file_location(
        "opc_84d_v2_acceptance_auditor",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "group": tmp_path / "groups" / "G01.json",
        "accepted": tmp_path / "accepted" / "G01.json",
        "deterministic": tmp_path / "qa" / "deterministic" / "G01.json",
        "review": tmp_path / "qa" / "reviews" / "G01.md",
        "beats": tmp_path / "daily-beats.json",
        "schema": tmp_path / "group-content.schema.json",
        "rubric": tmp_path / "qa-rubric.md",
        "story": tmp_path / "story-bible.md",
        "evidence_dir": tmp_path / "qa" / "accepted",
        "evidence": tmp_path / "qa" / "accepted" / "G01.json",
        "output": tmp_path / "qa" / "acceptance-audit.json",
    }
    for key in (
        "group",
        "accepted",
        "deterministic",
        "review",
        "evidence",
    ):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    group_bytes = b'{\n  "group_id": "G01",\n  "body": "accepted bytes"\n}\n'
    paths["group"].write_bytes(group_bytes)
    paths["accepted"].write_bytes(group_bytes)
    paths["review"].write_text("# independent review\n", encoding="utf-8")
    paths["beats"].write_text('{"days":[]}\n', encoding="utf-8")
    paths["schema"].write_text('{"type":"object"}\n', encoding="utf-8")
    paths["rubric"].write_text("# rubric v1\n", encoding="utf-8")
    paths["story"].write_text("# story v1\n", encoding="utf-8")
    paths["deterministic"].write_text(
        json.dumps(
            {
                "status": "structural_pass",
                "findings": [],
                "detector": {
                    "version": "opc-84d-v2-deterministic/3",
                },
                "groups": [{"group_id": "G01", "findings": []}],
            }
        ),
        encoding="utf-8",
    )
    group_sha = _sha(paths["group"])
    inputs = {
        "group": paths["group"],
        "deterministic_report": paths["deterministic"],
        "independent_review": paths["review"],
        "daily_beats": paths["beats"],
        "schema": paths["schema"],
        "qa_rubric": paths["rubric"],
        "story_bible": paths["story"],
    }
    evidence = {
        "schema": "pneuma.experiment.opc-84d-v2.acceptance/v1",
        "status": "accepted",
        "group_id": "G01",
        "group_sha256": group_sha,
        "accepted_copy": {
            "path": str(paths["accepted"]),
            "sha256": group_sha,
            "byte_identical": True,
        },
        "deterministic": {
            "path": str(paths["deterministic"]),
            "sha256": _sha(paths["deterministic"]),
            "detector_version": "opc-84d-v2-deterministic/3",
            "status": "structural_pass",
            "finding_count": 0,
        },
        "review": {
            "path": str(paths["review"]),
            "sha256": _sha(paths["review"]),
            "verdict": "PASS",
            "non_author_attested": True,
            "recorded_group_sha256": group_sha,
        },
        "inputs": {
            label: {"path": str(path), "sha256": _sha(path)}
            for label, path in inputs.items()
        },
    }
    paths["evidence"].write_text(
        json.dumps(evidence),
        encoding="utf-8",
    )
    return paths


def _source_bytes(paths: dict[str, Path]) -> dict[str, bytes]:
    return {
        key: paths[key].read_bytes()
        for key in (
            "group",
            "accepted",
            "deterministic",
            "review",
            "beats",
            "schema",
            "rubric",
            "story",
            "evidence",
        )
    }


def test_audit_reports_current_and_does_not_modify_acceptance_inputs(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    before = _source_bytes(paths)
    module = _load_auditor()

    report = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=tmp_path,
    )

    assert report["status"] == "current"
    assert report["summary"] == {"total": 1, "current": 1, "stale": 0}
    assert report["entries"][0]["status"] == "current"
    assert report["entries"][0]["findings"] == []
    assert report["entries"][0]["checks"]["accepted_copy"]["byte_identical"] is True
    assert json.loads(paths["output"].read_text(encoding="utf-8")) == report
    assert _source_bytes(paths) == before


def test_audit_reports_specific_hash_and_byte_drift_and_cli_exits_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _fixture(tmp_path)
    paths["rubric"].write_text("# rubric v2\n", encoding="utf-8")
    paths["story"].write_text("# story v2\n", encoding="utf-8")
    paths["accepted"].write_bytes(paths["accepted"].read_bytes() + b"\n")
    before = _source_bytes(paths)
    module = _load_auditor()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--evidence-dir",
            str(paths["evidence_dir"]),
            "--output",
            str(paths["output"]),
            "--root",
            str(tmp_path),
        ],
    )

    assert module.main() == 1

    report = json.loads(paths["output"].read_text(encoding="utf-8"))
    assert report["status"] == "stale"
    fields = {finding["field"] for finding in report["entries"][0]["findings"]}
    assert {
        "inputs.qa_rubric.sha256",
        "inputs.story_bible.sha256",
        "accepted_copy.sha256",
        "accepted_copy.byte_identical",
    } <= fields
    assert _source_bytes(paths) == before


def test_audit_reports_deterministic_status_and_findings_drift(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    paths["deterministic"].write_text(
        json.dumps(
            {
                "status": "draft",
                "findings": [{"code": "new-failure"}],
                "groups": [
                    {
                        "group_id": "G01",
                        "findings": [{"code": "new-failure"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = _load_auditor()

    report = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=tmp_path,
    )

    assert report["status"] == "stale"
    fields = {finding["field"] for finding in report["entries"][0]["findings"]}
    assert {
        "inputs.deterministic_report.sha256",
        "deterministic.status",
        "deterministic.findings",
        "deterministic.groups.findings",
    } <= fields


def test_audit_rejects_acceptance_bound_to_an_obsolete_detector(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    report = json.loads(paths["deterministic"].read_text(encoding="utf-8"))
    report["detector"]["version"] = "opc-84d-v2-deterministic/2"
    paths["deterministic"].write_text(json.dumps(report), encoding="utf-8")
    evidence = _read_evidence(paths)
    evidence["inputs"]["deterministic_report"]["sha256"] = _sha(
        paths["deterministic"]
    )
    evidence["deterministic"]["sha256"] = _sha(paths["deterministic"])
    evidence["deterministic"]["detector_version"] = (
        "opc-84d-v2-deterministic/2"
    )
    _write_evidence(paths, evidence)
    module = _load_auditor()

    audit = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=tmp_path,
    )

    assert audit["status"] == "stale"
    assert {
        (finding["field"], finding["code"])
        for finding in audit["entries"][0]["findings"]
    } >= {
        ("deterministic.detector_version", "obsolete_detector"),
        ("deterministic.detector.version", "obsolete_detector"),
    }


def _read_evidence(paths: dict[str, Path]) -> dict:
    return json.loads(paths["evidence"].read_text(encoding="utf-8"))


def _write_evidence(paths: dict[str, Path], evidence: dict) -> None:
    paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")


@pytest.mark.parametrize(
    ("path_kind", "expected_code"),
    [
        ("absolute", "path_outside_root"),
        ("parent_relative", "path_outside_root"),
        ("symlink", "path_outside_root"),
        ("wrong_internal_location", "path_mismatch"),
    ],
)
def test_audit_rejects_untrusted_or_noncanonical_evidence_input_paths(
    tmp_path: Path,
    path_kind: str,
    expected_code: str,
) -> None:
    experiment_root = tmp_path / "experiment"
    paths = _fixture(experiment_root)
    canonical_schema = paths["schema"]

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

    evidence = _read_evidence(paths)
    evidence["inputs"]["schema"] = {
        "path": raw_path,
        "sha256": _sha(substitute),
    }
    _write_evidence(paths, evidence)
    module = _load_auditor()

    report = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=experiment_root,
    )

    assert report["status"] == "stale"
    assert {
        (finding["field"], finding["code"])
        for finding in report["entries"][0]["findings"]
    } >= {("inputs.schema.path", expected_code)}


def test_audit_rejects_an_accepted_copy_outside_the_explicit_root(
    tmp_path: Path,
) -> None:
    experiment_root = tmp_path / "experiment"
    paths = _fixture(experiment_root)
    outside_copy = tmp_path / "G01.json"
    outside_copy.write_bytes(paths["accepted"].read_bytes())
    evidence = _read_evidence(paths)
    evidence["accepted_copy"]["path"] = str(outside_copy)
    _write_evidence(paths, evidence)
    module = _load_auditor()

    report = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=experiment_root,
    )

    assert report["status"] == "stale"
    assert {
        (finding["field"], finding["code"])
        for finding in report["entries"][0]["findings"]
    } >= {("accepted_copy.path", "path_outside_root")}


@pytest.mark.parametrize(
    ("mutation", "expected_field"),
    [
        (("schema", "wrong/v1"), "schema"),
        (("status", "draft"), "status"),
        (("group_id", "G02"), "group_id"),
        (("review.verdict", "RETURN"), "review.verdict"),
        (("review.non_author_attested", None), "review.non_author_attested"),
        (("deterministic.status", "draft"), "deterministic.status"),
        (("deterministic.finding_count", 1), "deterministic.finding_count"),
    ],
)
def test_audit_rejects_nonaccepted_or_nonindependent_evidence_metadata(
    tmp_path: Path,
    mutation: tuple[str, object],
    expected_field: str,
) -> None:
    paths = _fixture(tmp_path)
    evidence = _read_evidence(paths)
    field, value = mutation
    if "." in field:
        section, nested = field.split(".", maxsplit=1)
        if value is None:
            del evidence[section][nested]
        else:
            evidence[section][nested] = value
    else:
        evidence[field] = value
    _write_evidence(paths, evidence)
    module = _load_auditor()

    report = module.audit_acceptances(
        evidence_dir=paths["evidence_dir"],
        output_path=paths["output"],
        root=tmp_path,
    )

    assert report["status"] == "stale"
    assert expected_field in {
        finding["field"] for finding in report["entries"][0]["findings"]
    }
