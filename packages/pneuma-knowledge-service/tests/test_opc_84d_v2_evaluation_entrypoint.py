import importlib.util
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "evaluate_opc_84d_experiment.py"
ACCEPTED = ROOT / "docs" / "experiments" / "opc-84d-v2" / "accepted"


def _module():
    sys.path.insert(0, str(ROOT / "examples"))
    spec = importlib.util.spec_from_file_location("opc84_eval_v2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_manifest_is_frozen_and_has_required_probe_classes():
    module = _module()
    manifest = module.load_v2_manifest()
    truth = manifest["truth"]
    assert manifest["experiment_id"] == "opc-84d-v2"
    required = (
        "durable_facts",
        "decisions",
        "commitments",
        "constraints",
        "negative_controls",
        "retrieval_cases",
    )
    assert all(truth[key] for key in required)
    assert any(case.get("as_of") for case in truth["retrieval_cases"])
    assert all(case.get("question") for case in truth["retrieval_cases"])
    assert (
        hashlib.sha256(module.V2_TRUTH.read_bytes()).hexdigest()
        == module.EXPECTED_V2_TRUTH_SHA256
    )


def test_v2_manifest_rejects_an_unreviewed_truth_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    changed = tmp_path / "evaluation-v2-truth.json"
    changed.write_bytes(module.V2_TRUTH.read_bytes() + b"\n")
    monkeypatch.setattr(module, "V2_TRUTH", changed)

    with pytest.raises(RuntimeError, match="reviewed frozen snapshot"):
        module.load_v2_manifest()


def test_v2_truth_evidence_is_accepted_anchored_and_retrieval_spans_all_families():
    manifest = _module().load_v2_manifest()
    truth = manifest["truth"]
    categories = ("durable_facts", "decisions", "commitments", "constraints")
    truth_ids = {
        row["truth_id"]
        for category in categories
        for row in truth[category]
    }
    evidence_families_by_truth_id = {
        row["truth_id"]: {
            evidence["source_family"] for evidence in row["evidence"]
        }
        for category in categories
        for row in truth[category]
    }
    source_families = set()

    for category in (*categories, "negative_controls"):
        for row in truth[category]:
            assert row["evidence"]
            for evidence in row["evidence"]:
                group = json.loads(
                    (ACCEPTED / f"{evidence['group_id']}.json").read_text(
                        encoding="utf-8"
                    )
                )
                source = next(
                    item
                    for item in group["sources"][evidence["source_family"]]
                    if item["source_id"] == evidence["source_id"]
                )
                serialized = json.dumps(source, ensure_ascii=False)
                assert evidence["quote"] in serialized
                for authored_id in evidence["authored_ids"]:
                    assert f'"authored_id": "{authored_id}"' in serialized
                source_families.add(evidence["source_family"])

    assert source_families == {"meetings", "document_library", "im", "email"}
    assert {
        family
        for case in truth["retrieval_cases"]
        for family in case["source_families"]
    } == {"meetings", "document_library", "im", "email"}
    assert all(
        case["question"].strip()
        and case["expected_truth_ids"]
        and set(case["expected_truth_ids"]) <= truth_ids
        and set(case["source_families"])
        == set().union(
            *(evidence_families_by_truth_id[truth_id]
              for truth_id in case["expected_truth_ids"])
        )
        for case in truth["retrieval_cases"]
    )
    assert any(
        len(case["source_families"]) > 1
        for case in truth["retrieval_cases"]
    )
    assert any(
        case["as_of"] == "2026-03-30"
        and case["expected_truth_ids"] == ["v2-f-d29-start"]
        for case in truth["retrieval_cases"]
    )
