"""Canonical/L0-derived speech activity, prepared on projection writes, read at dialing."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.recall.projection import project_snapshot_claims
from pneuma_knowledge_core.recall.speech_activity import rank, source_mentions
from pneuma_knowledge_core.recall.speech_lexicon import digest, live_documents

from .speech_lexicon import cache_path, candidates, read, write

ACTIVITY_VERSION = 1


def activity_path(settings, user_id: str) -> Path:
    return cache_path(settings, user_id).with_suffix('.activity.json')


def read_activity(settings, user_id: str) -> dict:
    try:
        data = json.loads(activity_path(settings, user_id).read_text())
        if data.get('version') == ACTIVITY_VERSION and data.get('user_id') == user_id:
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {'version': ACTIVITY_VERSION, 'user_id': user_id, 'documents': {}}


def ranked_candidates(settings, user_id: str, documents, rows: list[dict], *, today: date) -> list[dict]:
    data = read_activity(settings, user_id)
    # Before the first projection refresh, preserve the existing vocabulary exactly.
    if not data['documents']:
        # Ranking is absent, so keep the old maintained/risk priority as well as its ties.
        return sorted(rows, key=lambda r: (r.get('reason') != 'maintained', -r.get('risk', 1)))
    mentions: dict[str, dict[str, list[str]]] = defaultdict(dict)
    stale_paths = set()
    for document in live_documents(documents):
        entry = data['documents'].get(document.path, {})
        if entry.get('digest') != digest(document):
            if entry:
                stale_paths.add(document.path)
            continue
        for term, observations in entry.get('mentions', {}).items():
            for source_id, days in observations.items():
                mentions[term][source_id] = sorted(set(mentions[term].get(source_id, ())) | set(days))
    return rank([row for row in rows if row['path'] not in stale_paths], mentions, today=today)


async def refresh_activity(settings, user_id: str, documents, content, *, force=False) -> None:
    """One atomic derived snapshot; unchanged page/evidence dependencies reuse their dates.

    Source text is read only while preparing changed pages, never at call startup. Failed
    reads leave the previous complete file intact and the projection job retryable.
    """
    documents = live_documents(documents)
    old = await asyncio.to_thread(read_activity, settings, user_id)
    lexicon = await asyncio.to_thread(read, cache_path(settings, user_id), user_id)
    rows = candidates(documents, lexicon)
    if not rows and not old['documents']:
        return
    terms: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row['term'] not in terms[row['path']]:
            terms[row['path']].append(row['term'])
    citations = defaultdict(set)
    for claim in project_snapshot_claims(documents):
        if claim.document_path in terms:
            citations[claim.document_path].update(
                (str(c.source_id), c.block_start, c.block_end) for c in claim.citations)
    user = UserId(user_id)
    archived = await content.archived_source_ids(user) if any(citations.values()) else frozenset()
    entries = {}; pending = []
    for document in documents:
        if document.path not in terms:
            continue
        spans = sorted(citations[document.path])
        fingerprint = digest(document)
        dependencies = [fingerprint, terms[document.path], spans,
                        sorted(sid for sid, _, _ in spans if sid in archived)]
        recipe = hashlib.sha256(json.dumps(dependencies, ensure_ascii=False).encode()).hexdigest()
        previous = old['documents'].get(document.path, {})
        if not force and previous.get('complete') and previous.get('recipe') == recipe:
            entries[document.path] = previous
        else:
            entry = {'digest': fingerprint, 'recipe': recipe, 'mentions': {}, 'complete': True}
            entries[document.path] = entry
            pending.append((document.path, spans, entry))
    source_ids = sorted({sid for _, spans, _ in pending for sid, _, _ in spans if sid not in archived})
    semaphore = asyncio.Semaphore(8)

    async def load(sid):
        async with semaphore:
            try:
                source = await content.get(user, SourceId(sid))
            except KeyError:
                # Historical unresolved citations do not acquire a fabricated clock.
                return None
        if source.raw.user_id != user or source.raw.source_id != sid:
            raise ValueError('speech activity source identity does not match the requested tenant/source')
        return source

    # Keep only dated name observations in the projection, not private source text.
    sources = dict(zip(source_ids, await asyncio.gather(*(load(sid) for sid in source_ids))))
    for path, spans, entry in pending:
        by_source = defaultdict(list)
        for sid, start, end in spans:
            if sources.get(sid) is not None:
                by_source[sid].append((start, end))
            elif sid not in archived:
                entry['complete'] = False
        for sid, locations in by_source.items():
            for term, days in source_mentions(sources[sid], terms[path], locations).items():
                entry['mentions'].setdefault(term, {})[sid] = days
    data = {'version': ACTIVITY_VERSION, 'user_id': user_id, 'documents': entries}
    await asyncio.to_thread(write, activity_path(settings, user_id), data)
