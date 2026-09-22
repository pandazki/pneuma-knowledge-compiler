"""Query-local retrieval provenance, retained through evidence composition.

An origin describes a lookup, not a global interpretation of the question. A component's
arguments cannot silently become another route's filters. Dates belong to cited source
spans, never to a claim's authored meaning or to the time the source was ingested.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import groupby
from typing import TypeVar

from ..domain.ids import SourceId, UserId
from ..domain.source import NormalizedSource
from ..domain.source_time import block_instants
from ..domain.time_context import load_zone
from ..ports.content_store import ContentStore
from ..prompts import prompt
from .timespan import local_day, parse_iso_day, relative_label


class CachedSources:
    """A single recall's read-through L0 cache; all other port operations stay delegated."""

    def __init__(self, content: ContentStore, user_id: UserId) -> None:
        self._content = content
        self._user_id = user_id
        self._sources: dict[SourceId, asyncio.Task] = {}

    def __getattr__(self, name):
        return getattr(self._content, name)

    async def get(self, user_id: UserId, source_id: SourceId) -> NormalizedSource:
        if user_id != self._user_id:
            raise ValueError("source cache cannot cross tenants")
        if source_id not in self._sources:
            self._sources[source_id] = asyncio.create_task(self._content.get(user_id, source_id))
        return await self._sources[source_id]


@dataclass(frozen=True)
class RetrievalOrigin:
    route: str
    method: str
    arguments: str
    # A structured lookup's exact span must not grow past its own scope at assembly.
    bounded: bool = False


def retrieval_origin(
    route: str, method: str, *, bounded: bool = False,
    arguments: Mapping[str, object] | None = None, **scope: object,
) -> RetrievalOrigin:
    return RetrievalOrigin(
        route, method,
        json.dumps({**(arguments or {}), **scope}, ensure_ascii=False, sort_keys=True), bounded,
    )


@dataclass(frozen=True)
class EvidenceTime:
    source_id: SourceId
    block_start: int
    block_end: int
    occurred_on: str = ""
    first: str = ""
    last: str = ""
    timed_blocks: int = 0


def evidence_time(
    source_id: SourceId, start: int, end: int, source: NormalizedSource | None,
) -> EvidenceTime:
    """Attach only aligned source clocks, including the coverage of a partial clock."""
    if source is None:
        return EvidenceTime(source_id, start, end)
    instants, _ = block_instants(source.raw, len(source.blocks))
    # The envelope is indexed by block index, not by the order a store happened to return.
    aligned = {b.index for b in source.blocks} == set(range(len(source.blocks)))
    times = [instants[i] for i in range(max(start, 0), min(end + 1, len(instants)))
             if aligned and instants[i] is not None]
    return EvidenceTime(
        source_id, start, end, source.raw.occurred_on(),
        min(times).isoformat() if times else "",
        max(times).isoformat() if times else "", len(times),
    )


_T = TypeVar("_T")


def share_retrieval_origins(items: Sequence[_T]) -> list[_T]:
    """An exact duplicate keeps every lookup's scope before dedup hides its other copies.

    A containing or overlapping span is not the same evidence, so it inherits nothing.
    Claim identity alone is insufficient if a stale index returned different text/locators.
    """
    def key(item):
        if hasattr(item, "citations"):
            return ("claim", item.document_path, item.anchor, item.text, tuple(
                (c.source_id, c.block_start, c.block_end) for c in item.citations
            ))
        return ("span", item.source_id, item.block_start, item.block_end)

    origins: dict[tuple, list[RetrievalOrigin]] = {}
    for item in items:
        shared = origins.setdefault(key(item), [])
        for origin in item.retrieval_origins:
            if origin not in shared:
                shared.append(origin)
    return [replace(item, retrieval_origins=tuple(origins[key(item)])) for item in items]


async def enrich_evidence(
    items: Sequence[_T], *, user_id: UserId, content: ContentStore | None,
) -> list[_T]:
    """One tenant-scoped L0 read per distinct source, with bounded concurrency.

    Missing sources/clocks are visible unknowns. Store failures and identity mismatches
    are errors, never substituted dates. Nothing is persisted or written to canonical.
    """
    def spans(item):
        if hasattr(item, "citations"):
            return [(c.source_id, c.block_start, c.block_end) for c in item.citations]
        return [(item.source_id, item.block_start, item.block_end)]

    source_ids = dict.fromkeys(sid for item in items for sid, _, _ in spans(item))
    semaphore = asyncio.Semaphore(8)

    async def load(sid):
        if content is None:
            return None
        async with semaphore:
            try:
                source = await content.get(user_id, sid)
            except KeyError:
                return None
        if source.raw.user_id != user_id or source.raw.source_id != sid:
            raise ValueError("evidence source identity does not match the requested tenant/source")
        return source

    sources = dict(zip(source_ids, await asyncio.gather(*(load(sid) for sid in source_ids))))
    return [replace(item, source_times=tuple(
        evidence_time(sid, start, end, sources[sid]) for sid, start, end in spans(item)
    )) for item in items]


def render_origins(origins: Sequence[RetrievalOrigin]) -> str:
    return "\n".join(prompt(
        "recall.retrieval.origin", route=o.route, method=o.method, arguments=o.arguments,
    ) for o in origins)


def render_times(item: object, *, citations: bool = True) -> str:
    times = getattr(item, "source_times", ())
    if not times:
        return prompt("recall.retrieval.time_unknown")
    return "\n".join(_render_source_time(t, citations=citations) for t in times)


def _render_source_time(t: EvidenceTime, *, citations: bool = True) -> str:
    return prompt(
        "recall.retrieval.source_time",
        citation=(
            f"[cite: {t.source_id} ¶{t.block_start}-{t.block_end}]" if citations else
            f"source={t.source_id}; span=¶{t.block_start}-{t.block_end};"
        ),
        source_id=t.source_id, start=t.block_start, end=t.block_end,
        occurred_on=t.occurred_on or prompt("recall.retrieval.unknown"),
        first=t.first or prompt("recall.retrieval.unknown"),
        last=t.last or prompt("recall.retrieval.unknown"),
        known=t.timed_blocks, total=t.block_end - t.block_start + 1,
    )


def render_candidate_context(item: object, *, citations: bool = True) -> str:
    """Selectors read the same origin and clocks that survive into the answer."""
    return "\n".join(filter(None, (
        render_origins(getattr(item, "retrieval_origins", ())), render_times(item, citations=citations),
    )))


def _scorer_time_facts(item: object, *, as_of: datetime, zone: str = "UTC") -> dict | None:
    """Compute source-clock relations; infer neither query ranges nor event dates.

    Local calendar dates are calculated before the decision model sees them. An occurrence
    day on the source is not a timestamp on every block, and incomplete envelopes remain
    partial. Unknown zones produce no computed facts rather than silently shifting dates.
    """
    times = getattr(item, "source_times", ())
    if not times:
        return None
    resolved_zone = load_zone(zone)
    if resolved_zone is None:
        return None
    today = local_day(as_of, resolved_zone)
    rows = []
    for time in times:
        row = {"source_id": str(time.source_id), "span": [time.block_start, time.block_end],
               "coverage": "unknown"}
        try:
            first = datetime.fromisoformat(time.first)
            last = datetime.fromisoformat(time.last)
            if last < first:
                raise ValueError("inverted source clock")
            for name, instant in (("first", first), ("last", last)):
                day = local_day(instant, resolved_zone)
                row[f"{name}_day"] = day.isoformat()
                row[f"{name}_relation"] = relative_label(day, today)
            row["coverage"] = (
                "complete" if time.timed_blocks == time.block_end - time.block_start + 1 else "partial"
            )
        except (ValueError, TypeError, OverflowError):
            try:
                day = parse_iso_day(time.occurred_on)
                row.update(source_day=day.isoformat(), source_day_relation=relative_label(day, today),
                           coverage="source_day_only")
            except ValueError:
                pass
        rows.append(row)
    return {"clock_scope": "source_occurrence_not_event_time", "zone": zone,
            "as_of_day": today.isoformat(), "source_clocks": rows}


def scorer_time_context(item: object, *, as_of: datetime, zone: str = "UTC") -> str:
    """Structured clock facts for diagnostics and paired-input evaluations."""
    facts = _scorer_time_facts(item, as_of=as_of, zone=zone)
    return json.dumps(facts, ensure_ascii=False) if facts else ""


def render_scorer_context(
    item: object, *, as_of: datetime | None = None, zone: str = "UTC",
) -> str:
    """Keep computed relations beside their source clocks, without repeating a JSON bundle.

    Render from structured metadata, never by replacing a string in source content. Unknown
    clocks add nothing to the existing explicit unknown. Exact instants and provenance stay
    intact; these relations never assert the date of the events the source discusses.
    """
    facts = _scorer_time_facts(item, as_of=as_of, zone=zone) if as_of else None
    if facts is None:
        return render_candidate_context(item)
    lines = []
    for time, row in zip(item.source_times, facts["source_clocks"]):
        line = _render_source_time(time)
        if row["coverage"] != "unknown":
            if row["coverage"] == "source_day_only":
                relation = f"source_day={row['source_day']} ({row['source_day_relation']})"
            else:
                relation = (
                    f"first_day={row['first_day']} ({row['first_relation']}), "
                    f"last_day={row['last_day']} ({row['last_relation']})"
                )
            line += f"; computed source clock, not event time: {relation}; coverage={row['coverage']}"
        lines.append(line)
    return "\n".join(filter(None, (
        render_origins(getattr(item, "retrieval_origins", ())), "\n".join(lines),
    )))


def render_groups(items: Sequence[_T], render: Callable[[list[_T]], str]) -> str:
    """Keep rank order, separating each contiguous lookup group around its own results."""
    parts = []
    for origins, group in groupby(items, key=lambda item: getattr(item, "retrieval_origins", ())):
        text = render(list(group))
        if origins:
            text = prompt("recall.retrieval.group", origins=render_origins(origins), evidence=text)
        parts.append(text)
    return "\n\n".join(parts)
