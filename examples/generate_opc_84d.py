#!/usr/bin/env python
"""Materialize the reproducible OPC 84-day corpus as inspectable JSON files."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_service.experiments.opc_84d import build_opc_84d_dataset

DEFAULT_OUTPUT = Path("examples/data/opc-84d")


def _slug(contract: dict, index: int) -> str:
    schema = contract["schema"].removeprefix("pneuma.source.").removesuffix("/v1")
    identity = (
        contract.get("meeting_id")
        or contract.get("library_id")
        or contract.get("archive_id")
        or f"contract-{index:02d}"
    )
    return f"{index:02d}-{schema}-{identity}.json"


def write_dataset(output: Path, *, seed: int, force: bool) -> dict:
    output = output.resolve()
    if output.exists():
        if not force:
            raise FileExistsError(f"{output} exists; pass --force to replace it")
        if output == Path("/") or output == Path.home() or output.name in {"", ".", ".."}:
            raise RuntimeError(f"refusing unsafe output target: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    dataset = build_opc_84d_dataset(seed)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(dataset.manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    index: list[dict] = []
    for batch in dataset.batches:
        batch_dir = output / "batches" / batch.batch_id
        batch_dir.mkdir(parents=True)
        contract_paths: list[str] = []
        for number, contract in enumerate(batch.contracts, start=1):
            parse_source_contract(contract)
            path = batch_dir / _slug(contract, number)
            path.write_text(
                json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            contract_paths.append(path.relative_to(output).as_posix())
        index.append(
            {
                "batch_id": batch.batch_id,
                "started_at": batch.started_at,
                "ended_at": batch.ended_at,
                "contracts": contract_paths,
            }
        )
    (output / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dataset.manifest["stats"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    stats = write_dataset(args.output, seed=args.seed, force=args.force)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"OK: materialized OPC 84-day corpus → {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
