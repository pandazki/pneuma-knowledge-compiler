"""Occurrence clocks from aligned L0 envelopes, shared by indexing and recall.

These describe when source material was recorded, not when the events it discusses
happened. Ingestion time is never a substitute for missing occurrence metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .source import RawSource

_log = logging.getLogger(__name__)
_INSTANT_META = {
    "meeting": ("segments", "started_at"),
    "im": ("messages", "sent_at"),
    "email": ("messages", "sent_at"),
    "owner_dialogue": ("turns", "said_at"),
    "agent_session": ("turns", "at"),
}


def _instant(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def block_instants(raw: RawSource, block_count: int) -> tuple[list[datetime | None], str | None]:
    """Read the contract's index-aligned clocks; misalignment yields no block clock."""
    source_zone = str(raw.meta.get("timezone") or "").strip() or None
    spec = _INSTANT_META.get(raw.kind)
    if spec is None:
        return [None] * block_count, source_zone
    list_key, field = spec
    entries = raw.meta.get(list_key) or []
    if not isinstance(entries, list) or len(entries) != block_count:
        _log.warning("source %s: misaligned %s metadata; dropping per-block instants",
                     raw.source_id, list_key)
        return [None] * block_count, source_zone
    return [
        _instant(entry.get(field)) if isinstance(entry, dict) else None
        for entry in entries
    ], source_zone
