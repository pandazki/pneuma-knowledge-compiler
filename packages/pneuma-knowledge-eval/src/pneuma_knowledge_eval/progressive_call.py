"""Synthetic first-finding/refinement scenarios, kept outside production inputs.

No audio, production library or retrieval latency is simulated. These calls measure backend
judgment and output timing on fixed evidence, separately from deterministic lifecycle tests.
"""
from datetime import datetime, timezone
import time

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim, selector_messages, _alias_human_content
from pneuma_knowledge_core.recall.progressive import first_finding, refine

CASES = (
    ("count", "渡口检查还有多少项待办？",
     "昨日的渡口检查记录只覆盖入口区，列出三项待办。",
     "今天的渡口完整检查清单包括入口区三项、泊位区两项，共五项待办。这份清单覆盖了本次检查的两个区域。",
     ("correct", "extend"), ("五", "5")),
    ("changed_date", "渡口什么时候开通？",
     "九月十六日的计划记录写明渡口将在本周五开通。",
     "九月十八日的更新撤销了周五开通计划：由于水位测试未通过，渡口开通延期至下周二。",
     ("correct",), ("下周二",)),
    ("more_detail", "渡口坡道更新做了些什么？",
     "渡口坡道更新采用了防滑面层。",
     "渡口坡道采用防滑面层，同时增加双侧扶手、降低坡度，并安排每周检查排水沟。",
     ("extend",), ("扶手", "坡度", "排水")),
)


def pool(question, text):
    as_of = datetime(2026, 9, 18, tzinfo=timezone.utc)
    claim = RetrievedClaim(AnchorId("c:abcd"), "projects/synthetic-ferry.md", (), text,
        (Citation(source_id=SourceId("synthetic-ferry-record"), block_start=0, block_end=0),))
    system, human = selector_messages(question, [claim], as_of=as_of, answer_style="spoken")
    content, handles = _alias_human_content(human.content)
    return FastEvidence(question=question, as_of=as_of, system=system.content,
                        content=content, handles=handles, used_claims=(claim,))


async def compare(model, *, repeats=2, on_result=None):
    results = []
    for repeat in range(repeats):
        for name, question, narrow, broad, relations, expected in CASES:
            start = time.perf_counter()
            first = await first_finding(model, question, pool(question, narrow))
            first_ms = round((time.perf_counter() - start) * 1000)
            result = await refine(model, pool(question, broad), first.text)
            total_ms = round((time.perf_counter() - start) * 1000)
            baseline_start = time.perf_counter()
            baseline = await refine(model, pool(question, broad), "")
            baseline_ms = round((time.perf_counter() - baseline_start) * 1000)
            row = dict(case=name, repeat=repeat, first_ms=first_ms if first.text else None, first_attempt_ms=first_ms,
                total_ms=total_ms, baseline_ms=baseline_ms, baseline_answer=baseline.answer,
                preliminary=first.text, refinement=result.speech, answer=result.answer,
                relation=result.relation, relation_matches=(result.relation in relations if first.text else result.relation == "answer"),
                expected_detail_present=any(word in result.speech for word in expected),
                first_was_verbatim=bool(first.text and narrow in first.text),
                first_usage=first.usage, refinement_usage=result.usage)
            results.append(row)
            if on_result:
                on_result(row)
    return results
