#!/usr/bin/env python
"""Evaluate one live OPC example tenant against the frozen 84-day truth set."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from examples import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.wiring import build_context

from examples.opc.dataset import (
    DATA_ROOT,
    load_frozen_manifest,
    load_accepted_source_contracts,
)
from examples.opc.evaluation import evaluate_opc_84d
from examples.opc.run import (
    _json_text,
    _new_report_path,
    _settings,
    _user_id,
    _write_report,
)


V2_ROOT = DATA_ROOT
V2_TRUTH = V2_ROOT / "spec" / "evaluation-truth.json"
EXPECTED_V2_TRUTH_SHA256 = (
    "f02ad87f550d836058294c8e2985069e5fcc9696f4b125b747145e636847f960"
)


def load_v2_manifest() -> dict[str, Any]:
    """Load frozen probes after mechanically validating every runtime asset."""
    if not V2_TRUTH.is_file():
        raise RuntimeError(f"missing v2 evaluation truth: {V2_TRUTH}")
    frozen = load_frozen_manifest(V2_ROOT)
    load_accepted_source_contracts(V2_ROOT)
    truth_bytes = V2_TRUTH.read_bytes()
    truth_hash = hashlib.sha256(truth_bytes).hexdigest()
    if (
        truth_hash != EXPECTED_V2_TRUTH_SHA256
        or truth_hash != frozen.get("truth_sha256")
    ):
        raise RuntimeError("v2 truth asset hash is not the reviewed frozen snapshot")
    manifest = json.loads(truth_bytes)
    if manifest.get("experiment_id") != "opc-84d-v2":
        raise RuntimeError("v2 truth asset has an unexpected experiment_id")
    truth = manifest.get("truth")
    if not isinstance(truth, dict):
        raise RuntimeError("v2 truth asset has no truth object")
    truth_ids = {
        row["truth_id"]
        for category in ("durable_facts", "decisions", "commitments", "constraints")
        for row in truth.get(category, [])
    }
    retrieval_cases = truth.get("retrieval_cases")
    if not isinstance(retrieval_cases, list) or not retrieval_cases:
        raise RuntimeError("v2 truth asset has no retrieval cases")
    for case in retrieval_cases:
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise RuntimeError("v2 retrieval case has no question")
        expected = case.get("expected_truth_ids")
        if (
            not isinstance(expected, list)
            or not expected
            or any(truth_id not in truth_ids for truth_id in expected)
        ):
            raise RuntimeError("v2 retrieval case references unknown truth")
    return manifest


async def run(user_id: UserId, report_path: Path, *, mode: str, manifest: dict[str, Any]) -> dict:
    ctx = await build_context(_settings(mode))
    try:
        report = await evaluate_opc_84d(
            ctx,
            user_id,
            manifest,
        )
        _write_report(report_path, report)
        return report
    finally:
        await ctx.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("keyless", "real"), required=True)
    parser.add_argument(
        "--user",
        required=True,
        help="the exact user tenant produced by `python -m examples.opc run`",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="defaults to a user-scoped evaluation report",
    )
    args = parser.parse_args()
    try:
        user_id = _user_id(args.user)
    except ValueError as exc:
        parser.error(str(exc))
    report_path = args.report or _new_report_path(user_id, kind="evaluation")
    report = asyncio.run(run(user_id, report_path, mode=args.mode, manifest=load_v2_manifest()))
    summary = {
        "projection_consistent": report["projection_consistency"]["consistent"],
        "truth_recall": report["truth_recall"]["recall"],
        "precision_proxy": report["truth_set_precision_proxy"]["precision"],
        "negative_leak_rate": report["negative_controls"]["leak_rate"],
        "supersession_accuracy": report["supersessions"]["accuracy"],
        "citation_replay_rate": report["citations"]["locator_replay_rate"],
        "retrieval_expected_truth_recall": report["retrieval"][
            "expected_truth_recall"
        ],
    }
    print(_json_text(summary), end="")
    print(f"OK: evaluation report → {report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
