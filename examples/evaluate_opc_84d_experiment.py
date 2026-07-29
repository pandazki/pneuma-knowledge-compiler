#!/usr/bin/env python
"""Evaluate the live 84-day experiment against manifest truth and all indexes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.experiments.opc_84d_evaluation import evaluate_opc_84d
from pneuma_knowledge_service.experiments.opc_84d_v2 import (
    EXPECTED_GROUP_IDS,
    load_accepted_source_contracts,
)
from pneuma_knowledge_service.wiring import build_context

from run_opc_84d_experiment import _new_report_path, _settings, _user_id


ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT / "docs" / "experiments" / "opc-84d-v2"
V2_TRUTH = V2_ROOT / "qa" / "evaluation-v2-truth.json"
EXPECTED_V2_TRUTH_SHA256 = (
    "f02ad87f550d836058294c8e2985069e5fcc9696f4b125b747145e636847f960"
)


def load_v2_manifest() -> dict[str, Any]:
    """Load frozen v2 probes only when accepted/global evidence is current."""
    if not V2_TRUTH.is_file():
        raise RuntimeError(f"missing v2 evaluation truth: {V2_TRUTH}")
    global_path = V2_ROOT / "qa" / "global.json"
    if not global_path.is_file():
        raise RuntimeError("missing v2 global QA evidence")
    global_report = json.loads(global_path.read_text(encoding="utf-8"))
    if global_report.get("status") != "global_pass":
        raise RuntimeError("v2 global QA is not global_pass")
    entries = global_report.get("acceptance_freshness", {}).get("entries", [])
    if len(entries) != len(EXPECTED_GROUP_IDS) or any(
        row.get("status") != "current" for row in entries
    ):
        raise RuntimeError("v2 acceptance freshness is incomplete or stale")
    # Do not merely trust the saved global report: revalidate every acceptance input
    # hash against the current group, detector, review, ledger, schema and rubric.
    load_accepted_source_contracts(
        V2_ROOT / "accepted",
        evidence_dir=V2_ROOT / "qa" / "accepted",
        root=ROOT,
        verify_current_inputs=True,
    )
    for group_id in EXPECTED_GROUP_IDS:
        path = V2_ROOT / "qa" / "deterministic" / f"{group_id}.json"
        if not path.is_file():
            raise RuntimeError(f"missing v2 deterministic evidence: {path.name}")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "structural_pass" or report.get("findings"):
            raise RuntimeError(f"v2 deterministic evidence is not clean: {path.name}")
    truth_bytes = V2_TRUTH.read_bytes()
    if hashlib.sha256(truth_bytes).hexdigest() != EXPECTED_V2_TRUTH_SHA256:
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
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        await ctx.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("scripted", "real"), required=True)
    parser.add_argument("--dataset", choices=("v2",), default="v2")
    parser.add_argument(
        "--user",
        required=True,
        help="the exact user tenant produced by run_opc_84d_experiment.py",
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
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OK: evaluation report → {report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
