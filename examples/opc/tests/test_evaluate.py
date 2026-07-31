from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from examples.opc import evaluate


def test_truth_manifest_is_frozen_and_covers_all_source_families() -> None:
    manifest = evaluate.load_v2_manifest()
    truth = manifest["truth"]

    assert manifest["experiment_id"] == "opc-84d-v2"
    assert hashlib.sha256(evaluate.V2_TRUTH.read_bytes()).hexdigest() == (
        evaluate.EXPECTED_V2_TRUTH_SHA256
    )
    assert all(
        truth[key]
        for key in (
            "durable_facts",
            "decisions",
            "commitments",
            "constraints",
            "negative_controls",
            "retrieval_cases",
        )
    )
    assert {
        family
        for case in truth["retrieval_cases"]
        for family in case["source_families"]
    } == {"meetings", "document_library", "im", "email"}


def test_truth_evidence_resolves_into_final_group_assets() -> None:
    truth = evaluate.load_v2_manifest()["truth"]
    for category in (
        "durable_facts",
        "decisions",
        "commitments",
        "constraints",
        "negative_controls",
    ):
        for row in truth[category]:
            for evidence in row["evidence"]:
                group = json.loads(
                    (
                        evaluate.V2_ROOT
                        / "groups"
                        / f"{evidence['group_id']}.json"
                    ).read_text(encoding="utf-8")
                )
                source = next(
                    item
                    for item in group["sources"][evidence["source_family"]]
                    if item["source_id"] == evidence["source_id"]
                )
                serialized = json.dumps(source, ensure_ascii=False)
                assert evidence["quote"] in serialized


def test_truth_hash_rejects_unreviewed_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = tmp_path / "evaluation-truth.json"
    changed.write_bytes(evaluate.V2_TRUTH.read_bytes() + b"\n")
    monkeypatch.setattr(evaluate, "V2_TRUTH", changed)

    with pytest.raises(RuntimeError, match="reviewed frozen snapshot"):
        evaluate.load_v2_manifest()
