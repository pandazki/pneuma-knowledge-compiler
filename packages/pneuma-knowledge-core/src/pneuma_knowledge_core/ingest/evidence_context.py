"""Read-only block context from the envelopes preserved by official source adapters.

Text, paragraph addresses and L0 are unchanged. Only declared semantic fields cross this
boundary; arbitrary provider metadata is never promoted into compiler context. A damaged
parallel envelope is omitted in full rather than attached to the wrong source paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.source import NormalizedSource


@dataclass(frozen=True)
class EvidenceContext:
    blocks: dict[int, dict]
    misaligned: bool = False


# These are the parallel envelopes written by canonical_sources, not kind-name guesses.
_ENVELOPES = {
    "pneuma.source.im/v1": (
        "messages", "message_ids", "message_id",
        ("message_id", "sender_id", "sent_at", "thread_id", "edited_at"),
    ),
    "pneuma.source.email/v1": (
        "messages", "message_ids", "message_id",
        ("message_id", "sent_at", "cc", "in_reply_to", "references"),
    ),
    "pneuma.source.meeting/v1": (
        "segments", "segment_ids", "segment_id",
        ("segment_id", "speaker_id", "started_at", "ended_at"),
    ),
}


def aligned_envelope(
    source: NormalizedSource, rows_key: str, ids_key: str, id_key: str,
) -> list[dict] | None:
    """Validate a parallel envelope before attaching any of its fields to L0 blocks."""
    meta = source.raw.meta or {}
    rows, ids = meta.get(rows_key), meta.get(ids_key)
    if (
        not isinstance(rows, list)
        or not isinstance(ids, list)
        or len(rows) != len(source.blocks)
        or len(ids) != len(rows)
        or any(not isinstance(i, str) or not i for i in ids)
        or len(set(ids)) != len(ids)
        or any(not isinstance(row, dict) or row.get(id_key) != i
               for row, i in zip(rows, ids))
        or [block.index for block in source.blocks] != list(range(len(rows)))
    ):
        return None
    return rows


def block_evidence_context(source: NormalizedSource) -> EvidenceContext:
    """Recover only an exactly aligned official envelope. Missing fields stay missing.

IM thread identifiers group messages; they do not necessarily identify a parent message.
Email reply identifiers retain their literal meaning, including targets outside this source.
The compiler renders these values as source data, never as instructions or new citations.
"""
    meta = source.raw.meta or {}
    schema = meta.get("contract_schema")
    spec = _ENVELOPES.get(schema) if isinstance(schema, str) else None
    if spec is None:
        return EvidenceContext({})
    rows_key, ids_key, id_key, fields = spec
    rows = aligned_envelope(source, rows_key, ids_key, id_key)
    if rows is None:
        return EvidenceContext({}, misaligned=True)
    contexts: dict[int, dict] = {}
    for block, row in zip(source.blocks, rows):
        context = {}
        for field in fields:
            value = row.get(field)
            if isinstance(value, str) and value:
                context[field] = value
            elif field == "references" and isinstance(value, list):
                context[field] = [item for item in value if isinstance(item, str)]
            elif field == "cc" and isinstance(value, list):
                # From/To/Subject are already in each normalized email block's text.
                context[field] = [
                    {key: item[key] for key in ("address", "display_name")
                     if isinstance(item.get(key), str) and item[key]}
                    for item in value if isinstance(item, dict)
                ]
        contexts[block.index] = {k: v for k, v in context.items() if v}
    return EvidenceContext(contexts)
