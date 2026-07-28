#!/usr/bin/env python
"""Evaluate the live 84-day experiment against manifest truth and all indexes."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.experiments.opc_84d import build_opc_84d_dataset
from pneuma_knowledge_service.experiments.opc_84d_evaluation import evaluate_opc_84d
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context

DEFAULT_USER = "u-opc-ninghe"
DEFAULT_REPORT = Path("docs/experiments/results/opc-84d-evaluation.json")


async def run(user_id: str, report_path: Path) -> dict:
    ctx = await build_context(Settings(evolve_auto_trigger=False))
    try:
        report = await evaluate_opc_84d(
            ctx,
            UserId(user_id),
            build_opc_84d_dataset().manifest,
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
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = asyncio.run(run(args.user, args.report))
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
    print(f"OK: evaluation report → {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
