"""Derived spelling activity: source occurrence clocks, never compile or ingest clocks."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timezone
from math import fsum

from ..domain.source import NormalizedSource
from ..domain.source_time import block_instants
from .speech_lexicon import key, occurs, render

HALF_LIFE_DAYS = 60
DAILY_CAP = 3
MIN_SCORE = 0.25


def source_mentions(source: NormalizedSource, terms: list[str], spans: list[tuple[int, int]]) -> dict[str, list[str]]:
    """Actual spelling occurrence days per term/source inside its cited spans.

    An undated occurrence stays unknown. Repeated claims and overlapping spans cannot
    multiply a source's vote. Unrelated text in a cited source cannot renew a name.
    """
    if source.raw.archived_at is not None:
        return {}
    clocks, _ = block_instants(source.raw, len(source.blocks))
    aligned = {b.index for b in source.blocks} == set(range(len(source.blocks)))
    try:
        source_day = date.fromisoformat(source.raw.occurred_on()).isoformat()
    except ValueError:
        source_day = None
    found: dict[str, list[str]] = {}
    identities = sorted({key(term) for term in terms})
    for block in source.blocks:
        if not any(start <= block.index <= end for start, end in spans):
            continue
        instant = clocks[block.index] if aligned else None
        day = instant.astimezone(timezone.utc).date().isoformat() if instant else source_day
        text = key(block.text)
        for identity in identities:
            if occurs(identity, text):
                days = found.setdefault(identity, [])
                if day and day not in days:
                    days.append(day)
    return {term: sorted(days) for term, days in found.items()}


def activity_score(mentions: dict[str, list[str]], *, today: date) -> float:
    """One vote per source, at most three per UTC day, with a real exit threshold.

    Missing dates retain a low-priority floor only when no dated vote is available;
    unknown evidence never props up an already dated, expired term. Future dates do
    not vote. No observation uses the time the projection was built.
    """
    days: Counter[date] = Counter()
    dated = False
    for values in mentions.values():
        source_days = []
        for value in values:
            try:
                day = date.fromisoformat(value)
            except (ValueError, TypeError):
                continue
            dated = True
            if day <= today:
                source_days.append(day)
        if source_days:
            days[max(source_days)] += 1
    if not dated:
        return MIN_SCORE
    return fsum(min(DAILY_CAP, count) * 2 ** (-(today - day).days / HALF_LIFE_DAYS)
                for day, count in sorted(days.items()))


def rank(rows: list[dict], mentions: dict[str, dict[str, list[str]]], *, today: date) -> list[dict]:
    """Rank admitted spellings; legacy cache cannot introduce previously omitted hints.

    Compilation owns admission for maintained metadata. The transitional cache keeps
    its pre-decay budgeted selection: fading a word must not backfill its slot with an
    old, previously omitted hint that can interfere with an unrelated spoken name.
    """
    legacy_selection = {key(row['term']) for row in json.loads(render(rows) or '[]')}
    rows = [row for row in rows if row.get('reason') == 'maintained'
            or key(row['term']) in legacy_selection]
    scores = {key(row['term']): activity_score(mentions.get(key(row['term']), {}), today=today)
              for row in rows}
    return sorted((row for row in rows if scores[key(row['term'])] >= MIN_SCORE),
                  key=lambda row: (-scores[key(row['term'])], key(row['term']),
                                   row.get('reason') != 'maintained'))
