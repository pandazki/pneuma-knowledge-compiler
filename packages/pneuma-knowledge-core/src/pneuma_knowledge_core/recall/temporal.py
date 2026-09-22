"""Query-owned source-time admission. Dates are computed here, never compared by a model.

This scope is independent of component lookup arguments and never interprets a claim's
event time. Only admitted source-clock requests use it; other questions are unchanged.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Sequence

from ..domain.source_time import block_instants
from ..domain.time_context import TimezoneChange, load_zone
from ..ports.evidence_scorer import SourceClockDecision, SourceClockPolicy
from ..prompts import prompt
from .evidence_context import evidence_time, retrieval_origin
from .timespan import day_range_to_utc, local_day


@dataclass(frozen=True)
class SourceTimeScope:
    status: Literal["resolved", "unresolved", "unavailable"]
    zone: str
    start_day: str = ""
    end_day: str = ""
    start: datetime | None = None
    end: datetime | None = None

    def preview(self) -> dict:
        return {"status": self.status, "basis": "source_occurrence", "zone": self.zone,
                "start_day": self.start_day, "end_day": self.end_day}


async def prepare_source_clock(scorer, question: str) -> SourceClockDecision:
    if not isinstance(scorer, SourceClockPolicy):
        return SourceClockDecision()
    try:
        result = await asyncio.wait_for(scorer.source_clock_policy(question), 2.0)
        if not isinstance(result, SourceClockDecision):
            return SourceClockDecision(policy_id="unavailable")
        if result.probability is None and result.policy_id is None:
            return replace(result, policy_id="unavailable")
        return result
    except Exception:  # noqa: BLE001 — the optional policy cannot invent a scope on failure
        return SourceClockDecision(policy_id="unavailable")


def resolve_source_time_scope(
    decision: SourceClockDecision, *, question: str, as_of: datetime, zone: str = "UTC",
    history: Sequence[TimezoneChange] = (),
) -> SourceTimeScope | None:
    if decision.probability is None and decision.policy_id is not None:
        return SourceTimeScope("unavailable", zone)
    if not decision.use_source_clocks:
        return None
    unresolved = SourceTimeScope("unresolved", zone)
    tz = load_zone(zone)
    if tz is None or decision.period_confidence is None or not 0.7 <= decision.period_confidence <= 1:
        return unresolved
    today = local_day(as_of, tz)
    period = decision.period
    first = last = today
    if period == "today":
        pass
    elif period == "yesterday":
        first = last = today - timedelta(days=1)
    elif period == "day_before_yesterday":
        first = last = today - timedelta(days=2)
    elif period in {"last_two_days", "last_three_days", "last_seven_days", "last_fourteen_days", "last_thirty_days"}:
        count = {"last_two_days": 2, "last_three_days": 3, "last_seven_days": 7,
                 "last_fourteen_days": 14, "last_thirty_days": 30}[period]
        first = today - timedelta(days=count - 1)
    elif period in {"this_week", "last_week"}:
        first = today - timedelta(days=today.weekday())
        if period == "last_week":
            last, first = first - timedelta(days=1), first - timedelta(days=7)
    elif period in {"this_month", "last_month"}:
        first = today.replace(day=1)
        if period == "last_month":
            last = first - timedelta(days=1)
            first = last.replace(day=1)
    elif period in {"this_year", "last_year"}:
        first = today.replace(month=1, day=1)
        if period == "last_year":
            first, last = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif period == "explicit_dates":
        # Extract literal, fully specified dates only. No missing year or implied range
        # is guessed. The decision model chooses the meaning; code owns all arithmetic.
        literals = re.findall(r"(?<!\d)(\d{4})(?:-|年)(\d{1,2})(?:-|月)(\d{1,2})(?:日)?(?!\d)", question)
        try:
            days = sorted({date(*map(int, parts)) for parts in literals})
        except ValueError:
            return unresolved
        if not 1 <= len(days) <= 2:
            return unresolved
        first, last = days[0], days[-1]
    else:
        return unresolved
    try:
        start, end = day_range_to_utc(first, last, zone=tz, history=history)
    except (ValueError, OverflowError):
        return unresolved
    return SourceTimeScope("resolved", zone, first.isoformat(), last.isoformat(), start, end)


def temporal_status(item, scope: SourceTimeScope) -> str:
    if scope.status != "resolved":
        return "unknown"
    times = getattr(item, "source_times", ())
    if hasattr(item, "citations"):
        spans = {(str(c.source_id), c.block_start, c.block_end) for c in item.citations}
    else:
        spans = {(str(item.source_id), item.block_start, item.block_end)}
    if not spans or {(str(t.source_id), t.block_start, t.block_end) for t in times} != spans:
        return "unknown"
    states = []
    for t in times:
        if t.timed_blocks != t.block_end - t.block_start + 1 or t.timed_blocks <= 0:
            return "unknown"
        try:
            first, last = datetime.fromisoformat(t.first), datetime.fromisoformat(t.last)
            first = first.replace(tzinfo=timezone.utc) if first.tzinfo is None else first
            last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
            if last < first:
                return "unknown"
        except (ValueError, TypeError):
            return "unknown"
        states.append("within" if scope.start <= first <= last < scope.end else
                      "outside" if last < scope.start or first >= scope.end else "mixed")
    return states[0] if len(set(states)) == 1 else "mixed"


def temporal_items(items, scope: SourceTimeScope):
    states = [temporal_status(item, scope) for item in items]
    return [item for item, state in zip(items, states) if state == "within"], Counter(states)


async def temporal_windows(windows, scope: SourceTimeScope, *, user_id, content):
    """Retain exact in-period runs, never expand through unknown or out-of-period blocks."""
    kept, counts = [], Counter()
    origin = retrieval_origin("question.source_time", "source occurrence window", bounded=True,
                              start_day=scope.start_day, end_day=scope.end_day, zone=scope.zone)
    for window in windows:
        state = temporal_status(window, scope)
        counts[state] += 1
        if state == "within":
            kept.append(replace(window, retrieval_origins=tuple(dict.fromkeys((*window.retrieval_origins, origin)))))
            continue
        if scope.status != "resolved" or state == "outside" or content is None:
            continue
        try:
            source = await content.get(user_id, window.source_id)
        except KeyError:
            continue
        if source.raw.user_id != user_id or source.raw.source_id != window.source_id:
            raise ValueError("temporal source identity does not match the requested tenant/source")
        indexes = [b.index for b in source.blocks]
        if len(indexes) != len(set(indexes)):
            raise ValueError("temporal source contains duplicate block indices")
        if set(indexes) != set(range(len(source.blocks))):
            continue
        instants, _ = block_instants(source.raw, len(source.blocks))
        runs = []
        for block in sorted(source.blocks, key=lambda b: b.index):
            if not window.block_start <= block.index <= window.block_end:
                continue
            instant = instants[block.index]
            if instant is None or not scope.start <= instant < scope.end:
                continue
            if not runs or runs[-1][-1].index + 1 != block.index:
                runs.append([])
            runs[-1].append(block)
        for blocks in runs:
            start, end = blocks[0].index, blocks[-1].index
            kept.append(replace(window, block_start=start, block_end=end, text="\n".join(b.text for b in blocks),
                                retrieval_origins=tuple(dict.fromkeys((*window.retrieval_origins, origin))),
                                source_times=(evidence_time(window.source_id, start, end, source),)))
        counts["split_runs"] += len(runs)
    return kept, counts


def temporal_notice(scope: SourceTimeScope | None, *, has_evidence: bool) -> str | None:
    if scope is None:
        return None
    if scope.status == "unavailable":
        return prompt("recall.temporal.unavailable")
    if scope.status != "resolved":
        return prompt("recall.temporal.unresolved")
    if not has_evidence:
        return prompt("recall.temporal.empty", since=scope.start_day, until=scope.end_day, zone=scope.zone)
    return None
