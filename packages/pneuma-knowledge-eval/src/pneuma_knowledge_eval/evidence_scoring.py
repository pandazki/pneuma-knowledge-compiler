"""Read-only paired scoring of frozen inputs; labels never reach the scorer.

This measures eligibility at a fixed score floor, before ranked safety anchors and answer
generation. It is not an end-to-end answer-quality or voice-latency benchmark.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime

from pneuma_knowledge_core.ports.evidence_scorer import EvidenceScorer, SourceClockPolicy
from pneuma_knowledge_core.recall.temporal import prepare_source_clock, resolve_source_time_scope


async def evaluate_source_clock_policy(policy: SourceClockPolicy, cases: Sequence[dict]) -> list[dict]:
    """Question-only evaluation; unknown decisions are reported separately from matches."""
    rows = []
    for case in cases:
        start = time.perf_counter()
        decision = await policy.source_clock_policy(case["question"])
        rows.append({
            "case": case["id"], "expected": case["expected"],
            "use_source_clocks": decision.use_source_clocks,
            "probability": decision.probability,
            "matches": decision.use_source_clocks == case["expected"] if decision.probability is not None else None,
            "input_tokens": decision.input_tokens, "policy_id": decision.policy_id,
            "ms": round((time.perf_counter() - start) * 1000),
        })
    return rows


async def evaluate_source_time_scope(
    policy: SourceClockPolicy, cases: Sequence[dict], *, as_of: datetime, zone: str = "UTC",
) -> list[dict]:
    """Evaluate intent plus exact calendar resolution, with labels confined to this leaf.

    The model receives only the question; core resolves boundaries against the supplied
    clock. Failed validation is unscored, not a correctly unresolved request.
    """
    rows = []
    for case in cases:
        started = time.perf_counter()
        decision = await prepare_source_clock(policy, case["question"])
        scope = resolve_source_time_scope(decision, question=case["question"], as_of=as_of, zone=zone)
        actual = scope.preview() if scope else {"status": "not_requested"}
        matches = actual["status"] == case["status"] and (
            case["status"] != "resolved" or (
                actual["start_day"] == case["start"] and actual["end_day"] == case["end"]
            )
        )
        rows.append({
            "case": case["id"], "decision": asdict(decision), "actual": actual,
            "matches": matches if decision.probability is not None else None,
            "ms": round((time.perf_counter() - started) * 1000),
        })
    return rows


async def compare(
    scorer: EvidenceScorer, cases: Sequence[dict], *, repeats: int = 1,
    floor: float = 0.5, on_result=None,
) -> list[dict]:
    """Interleave before/after calls; report abstentions instead of treating them as zero.

    Each case carries `id`, `question`, `expected` booleans and `modes` containing frozen
    `before`/`after` candidate strings. A single scorer fixes model, rubric and batching.
    No provider or credentials are configured by this module.
    """
    for case in cases:
        count = len(case["expected"])
        if any(len(case["modes"][mode]) != count for mode in ("before", "after")):
            raise ValueError("paired candidates and labels must be index-aligned")
    rows = []
    for repeat in range(repeats):
        for index, case in enumerate(cases):
            modes = ("before", "after") if (repeat + index) % 2 == 0 else ("after", "before")
            for mode in modes:
                started = time.perf_counter()
                result = await scorer.score(case["question"], case["modes"][mode])
                counts = {name: 0 for name in ("tp", "fp", "fn", "tn", "unscored")}
                for i, expected in enumerate(case["expected"]):
                    score = result.scores[i] if i < len(result.scores) else None
                    if score is None:
                        counts["unscored"] += 1
                    else:
                        kept = score >= floor
                        counts["tp" if kept and expected else "fp" if kept else "fn" if expected else "tn"] += 1
                row = {"case": case["id"], "repeat": repeat, "mode": mode,
                       "scores": list(result.scores), "floor": floor, **counts,
                       "input_tokens": result.input_tokens,
                       "ms": round((time.perf_counter() - started) * 1000)}
                rows.append(row)
                if on_result:
                    on_result(row)
    return rows
