"""Synthetic, read-only comparison of voice backend candidate-selection policies.

This isolates selection and answering from ASR, retrieval, WebRTC and playback. Expected
coordinates never enter model inputs. Results diagnose evidence coverage and latency;
they are not an audio evaluation or proof of semantic answer correctness.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.recall.call import SpokenChunker
from pneuma_knowledge_core.recall.fast import RetrievedClaim, answer_with_selector, select_evidence


def candidates() -> list[RetrievedClaim]:
    """Eighty synthetic records with similar names and distinct, independently citable facts."""
    return [
        RetrievedClaim(
            anchor=AnchorId(f"c:{index:04x}"),
            document_path=f"projects/harbour-{index:02d}.md",
            section_path=("Decision",),
            text=(
                f"Harbour {index:02d}: On September 16, 2026, the team chose Option "
                f"{index + 100} because the quay can carry {index + 20} tonnes. "
                f"The rollout is blocked until Test {index + 200} passes. "
                "This record does not confirm completion or approval of deployment. "
            ),
            citations=(Citation(source_id=SourceId(f"synthetic-harbour-{index}"), block_start=0, block_end=0),),
            score=1 / (index + 1),
        )
        for index in range(80)
    ]


async def compare(model, *, repeats: int = 2, on_result=None) -> list[dict]:
    pool = candidates()
    # Include relevant evidence on both sides of proposed smaller candidate caps.
    cases = [(index, f"Why did Harbour {index:02d} choose its option, and what still blocks rollout?")
             for index in (3, 11, 23, 37, 59, 73)]
    results = []
    for repeat in range(repeats):
        for index, question in cases:
            # Rotate execution order to reduce warm-connection/cache order bias.
            modes = ["select_full", "select_32", "direct_full"]
            modes = modes[repeat % 3:] + modes[:repeat % 3]
            for mode in modes:
                started = time.perf_counter()
                available = pool[:32] if mode == "select_32" else pool
                selected = available
                degraded = None
                select_usage = {}
                if mode != "direct_full":
                    choice, select_usage, degraded = await select_evidence(
                        model, question, claims=available, episode_summaries=(), windows=(),
                        claim_cap=12, timeout=15,
                    )
                    selected = [available[i] for i in choice.claim_indexes] if choice else available[:12]
                selection_ms = (time.perf_counter() - started) * 1000
                chunker = SpokenChunker()
                first_useful_ms = None

                def token(delta):
                    nonlocal first_useful_ms
                    if chunker.feed(delta) and first_useful_ms is None:
                        first_useful_ms = (time.perf_counter() - started) * 1000

                answer, usage, _handles = await answer_with_selector(
                    model, question, list(selected), as_of=datetime(2026, 9, 18, tzinfo=timezone.utc),
                    answer_style="spoken", on_token=token,
                )
                if chunker.flush() and first_useful_ms is None:
                    first_useful_ms = (time.perf_counter() - started) * 1000
                row = {
                    "repeat": repeat, "mode": mode, "case": index,
                    "candidate_count": len(available), "selected_count": len(selected),
                    "evidence_present": pool[index].anchor in {item.anchor for item in selected},
                    "expected_values_present": all(str(value) in answer for value in (index + 100, index + 200)),
                    "selection_ms": round(selection_ms), "first_sentence_ms": round(first_useful_ms) if first_useful_ms is not None else None,
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "selection_degraded": degraded, "selection_usage": select_usage,
                    "answer_usage": usage, "answer": answer,
                }
                results.append(row)
                if on_result:
                    on_result(row)
    return results
