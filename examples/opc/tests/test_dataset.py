from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from examples.opc import dataset


def test_frozen_corpus_is_28_ordered_batches_and_104_contracts() -> None:
    assembled = dataset.build_accepted_opc_84d_v2_dataset()

    assert [batch.batch_id for batch in assembled.batches] == list(
        dataset.EXPECTED_GROUP_IDS
    )
    assert len(assembled.batches) == 28
    assert sum(len(batch.contracts) for batch in assembled.batches) == 104
    assert all(
        previous.ends_on < current.starts_on
        for previous, current in zip(
            assembled.batches,
            assembled.batches[1:],
            strict=False,
        )
    )
    assert {
        contract.contract_schema
        for batch in assembled.batches
        for contract in batch.contracts
    } == {
        "pneuma.source.meeting/v1",
        "pneuma.source.document-library/v1",
        "pneuma.source.im/v1",
        "pneuma.source.email/v1",
    }


def test_frozen_manifest_binds_final_groups_schema_and_truth() -> None:
    manifest = dataset.load_frozen_manifest()

    assert manifest["group_count"] == 28
    assert manifest["source_count"] == 104
    assert manifest["source_counts"] == {
        "meeting": 18,
        "document_library": 35,
        "im": 30,
        "email": 21,
    }
    assert all(len(manifest[key]) == 64 for key in (
        "groups_sha256",
        "truth_sha256",
        "group_schema_sha256",
    ))


def test_loader_rejects_tampered_group_bytes(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "84-day"
    shutil.copytree(dataset.DATA_ROOT, copied)
    group = copied / "groups" / "G01.json"
    payload = json.loads(group.read_text(encoding="utf-8"))
    payload["group_window"]["starts_on"] = "2026-03-01"
    group.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        dataset.Opc84dV2AssemblyError,
        match="groups hash mismatch",
    ):
        dataset.load_accepted_source_contracts(copied)


def test_loader_rejects_missing_or_extra_groups(tmp_path: Path) -> None:
    copied = tmp_path / "84-day"
    shutil.copytree(dataset.DATA_ROOT, copied)
    (copied / "groups" / "G28.json").unlink()

    with pytest.raises(
        dataset.Opc84dV2AssemblyError,
        match="group set mismatch",
    ):
        dataset.load_frozen_manifest(copied)
