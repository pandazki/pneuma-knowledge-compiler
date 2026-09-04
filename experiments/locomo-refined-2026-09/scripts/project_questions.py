#!/usr/bin/env python3
"""Selectively project only qa_id, conversation_idx, and question from JSONL objects."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ALLOWED_FIELDS = ("qa_id", "conversation_idx", "question")
DECODER = json.JSONDecoder()


def _whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _skip_string(text: str, position: int) -> int:
    if position >= len(text) or text[position] != '"':
        raise ValueError("expected JSON string")
    position += 1
    escaped = False
    while position < len(text):
        char = text[position]
        position += 1
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return position
    raise ValueError("unterminated JSON string")


def _skip_value(text: str, position: int) -> int:
    position = _whitespace(text, position)
    if position >= len(text):
        raise ValueError("missing JSON value")
    if text[position] == '"':
        return _skip_string(text, position)
    if text[position] in "[{":
        opening = text[position]
        closing = "]" if opening == "[" else "}"
        stack = [closing]
        position += 1
        while position < len(text) and stack:
            char = text[position]
            if char == '"':
                position = _skip_string(text, position)
                continue
            if char == "[":
                stack.append("]")
            elif char == "{":
                stack.append("}")
            elif char in "]}":
                if char != stack[-1]:
                    raise ValueError("mismatched JSON container")
                stack.pop()
            position += 1
        if stack:
            raise ValueError("unterminated JSON container")
        return position
    start = position
    while position < len(text) and text[position] not in ",}":
        position += 1
    if not text[start:position].strip():
        raise ValueError("empty JSON primitive")
    return position


def project_record(raw: str) -> dict[str, object]:
    """Decode only the three allowlisted values; lexically skip every other value."""
    text = raw.strip()
    position = _whitespace(text, 0)
    if position >= len(text) or text[position] != "{":
        raise ValueError("question record must be a JSON object")
    position += 1
    projected: dict[str, object] = {}
    while True:
        position = _whitespace(text, position)
        if position < len(text) and text[position] == "}":
            position += 1
            break
        key, position = DECODER.raw_decode(text, position)
        if not isinstance(key, str):
            raise ValueError("JSON object key must be a string")
        position = _whitespace(text, position)
        if position >= len(text) or text[position] != ":":
            raise ValueError("missing colon after JSON key")
        position = _whitespace(text, position + 1)
        if key in ALLOWED_FIELDS:
            if key in projected:
                raise ValueError(f"duplicate allowlisted field: {key}")
            projected[key], position = DECODER.raw_decode(text, position)
        else:
            position = _skip_value(text, position)
        position = _whitespace(text, position)
        if position < len(text) and text[position] == ",":
            position += 1
            continue
        if position < len(text) and text[position] == "}":
            position += 1
            break
        raise ValueError("expected comma or object terminator")
    if _whitespace(text, position) != len(text):
        raise ValueError("trailing bytes after question object")
    if set(projected) != set(ALLOWED_FIELDS):
        raise ValueError("question record lacks an allowlisted field")
    if not isinstance(projected["qa_id"], str) or not projected["qa_id"]:
        raise ValueError("qa_id must be a non-empty string")
    if isinstance(projected["conversation_idx"], bool) or not isinstance(
        projected["conversation_idx"], int
    ):
        raise ValueError("conversation_idx must be an integer")
    if not isinstance(projected["question"], str) or not projected["question"].strip():
        raise ValueError("question must be a non-empty string")
    return projected


def project_file(source: Path, destination: Path, *, expected: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    per_conversation: dict[int, int] = {}
    count = 0
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False
    ) as sink:
        temporary = Path(sink.name)
        try:
            with source.open("r", encoding="utf-8") as handle:
                for line_number, raw in enumerate(handle, start=1):
                    if not raw.strip():
                        continue
                    record = project_record(raw)
                    qa_id = str(record["qa_id"])
                    if qa_id in seen:
                        raise ValueError(f"duplicate qa_id at line {line_number}")
                    seen.add(qa_id)
                    conversation_idx = int(record["conversation_idx"])
                    if conversation_idx not in range(10):
                        raise ValueError(f"conversation_idx out of range at line {line_number}")
                    per_conversation[conversation_idx] = per_conversation.get(conversation_idx, 0) + 1
                    sink.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    count += 1
            sink.flush()
            os.fsync(sink.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    if count != expected or len(per_conversation) != 10:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            f"projected question set is incomplete: records={count}, conversations={len(per_conversation)}"
        )
    os.replace(temporary, destination)
    return {"records": count, "unique_ids": len(seen), "per_conversation": per_conversation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--expected", type=int, default=1382)
    args = parser.parse_args()
    try:
        summary = project_file(args.source, args.destination, expected=args.expected)
        counts = summary["per_conversation"]
        print(
            f"projected_questions={summary['records']} unique_ids={summary['unique_ids']} "
            f"conversations={len(counts)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: question projection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
