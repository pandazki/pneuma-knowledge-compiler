"""Block authorship from the normalized identity envelope, never from prose or extras.

Parallel metadata follows normalized block order. Older sources need no rewrite: their
declared owner identity sets determine the same roles as today's normalizers stamp.
"""

from .source import RawSource


def block_authorship(raw: RawSource) -> list[dict]:
    """One role/kind row per conversational block; unknown material supplies no roles."""
    meta = raw.meta
    if raw.kind in {"agent_session", "owner_dialogue"}:
        return [
            {
                "index": index,
                "role": turn.get("role", "unknown"),
                **({"kind": turn["kind"]} if "kind" in turn else {}),
            }
            for index, turn in enumerate(meta.get("turns", []))
        ]
    if raw.kind == "meeting":
        owners = set(meta.get("owner_participant_ids", []))
        roles = [item.get("speaker_id") in owners for item in meta.get("segments", [])]
    elif raw.kind == "im":
        owners = set(meta.get("owner_user_ids", []))
        roles = [item.get("sender_id") in owners for item in meta.get("messages", [])]
    elif raw.kind == "email":
        owners = set(meta.get("owner_addresses", []))
        roles = [
            (item.get("from") or {}).get("address") in owners
            for item in meta.get("messages", [])
        ]
    else:
        return []
    return [
        {"index": index, "role": "owner" if owner else "other"}
        for index, owner in enumerate(roles)
    ]


def owner_authored_blocks(raw: RawSource) -> list[int]:
    """Exact indices whose declared author is the Owner."""
    return [row["index"] for row in block_authorship(raw) if row["role"] == "owner"]
