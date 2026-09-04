#!/usr/bin/env python3
"""Render LoCoMo-Refined sessions and verify them through the real app parser."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "data" / "public" / "conversations.jsonl"
DEFAULT_APP = ROOT / "app-01" / "app.py"
MONTHS = {
    month: index
    for index, month in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
Parser = Callable[[str], object]


def framework_parser(app_path: Path) -> tuple[Parser, Parser]:
    if not app_path.is_file():
        raise ValueError(f"generated app parser not found: {app_path}")
    namespace = runpy.run_path(str(app_path), run_name="pneuma_material_parser")
    split_frontmatter = namespace.get("split_frontmatter")
    parse_turns = namespace.get("parse_conversation_turns")
    if not callable(split_frontmatter) or not callable(parse_turns):
        raise ValueError(f"required parser functions missing from {app_path}")
    return split_frontmatter, parse_turns


def load_conversations() -> list[dict]:
    if not DATASET.is_file():
        raise ValueError(f"dataset not found: {DATASET}")
    conversations = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    indexes = [int(conversation["conversation_idx"]) for conversation in conversations]
    if len(indexes) != len(set(indexes)):
        raise ValueError("duplicate conversation_idx in dataset")
    return conversations


def load_conversation(index: int) -> dict:
    for conversation in load_conversations():
        if int(conversation["conversation_idx"]) == index:
            return conversation
    raise ValueError(f"conversation_idx not found: {index}")


def parse_date(value: str) -> str:
    match = re.fullmatch(
        r"(\d{1,2}):(\d{2}) (am|pm) on (\d{1,2}) ([A-Za-z]+), (\d{4})", value
    )
    if not match or match.group(5) not in MONTHS:
        raise ValueError(f"unparseable session date_time: {value!r}")
    return datetime(
        int(match.group(6)), MONTHS[match.group(5)], int(match.group(4))
    ).date().isoformat()


def _single_line(value: object, *, field: str) -> str:
    text = str(value or "")
    if "\r" in text or "\n" in text:
        raise ValueError(f"{field} contains a line break and cannot round-trip byte-exactly")
    if text != text.strip():
        raise ValueError(f"{field} has edge whitespace and cannot round-trip byte-exactly")
    return text


def media_fields(message: dict) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for image in message.get("images") or []:
        fields.append(("image", _single_line(image, field="image")))
    caption = _single_line(message.get("blip_caption"), field="blip_caption")
    query = _single_line(message.get("query"), field="query")
    if caption:
        fields.append(("caption", caption))
    if query:
        fields.append(("query", query))
    return fields


def message_lines(message: dict) -> list[str]:
    text = str(message.get("text") or "")
    if "\r" in text:
        raise ValueError("text contains carriage returns and cannot round-trip byte-exactly")
    parts = text.split("\n")
    if any(part != part.strip() for part in parts):
        raise ValueError("text line has edge whitespace and cannot round-trip byte-exactly")
    lines = [f"{message['speaker']}: {parts[0]}"]
    lines.extend(f"  {part}" for part in parts[1:])
    return lines


def expected_turn(message: dict) -> tuple[str, str]:
    return str(message["speaker"]), str(message.get("text") or "")


def media_lines(messages: list[dict]) -> list[str]:
    lines: list[str] = []
    for ordinal, message in enumerate(messages, start=1):
        speaker = json.dumps(str(message["speaker"]), ensure_ascii=False)
        for kind, value in media_fields(message):
            lines.append(
                f"  [media message={ordinal:03d} speaker={speaker} kind={kind}] {value}"
            )
    return lines


def field_digest(fields: object) -> str:
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def render(conversation: dict, session: dict) -> str:
    speaker_a = str(conversation["speaker_a"])
    speaker_b = str(conversation["speaker_b"])
    session_index = int(session["session_index"])
    total = len(conversation["sessions"])
    when = str(session["date_time"])
    title = json.dumps(
        f"{speaker_a} & {speaker_b} — session {session_index} of {total}, {when}",
        ensure_ascii=False,
    )
    lines = [f"Context: {context_head(conversation, session)}"]
    lines.extend(media_lines(session["messages"]))
    for message in session["messages"]:
        lines.extend(message_lines(message))
    return (
        "---\n"
        f"date: {parse_date(when)}\n"
        "type: conversation\n"
        f"title: {title}\n"
        "---\n\n"
        + "\n".join(lines)
        + "\n"
    )


def context_head(conversation: dict, session: dict) -> str:
    return (
        f"Session {int(session['session_index'])} of {len(conversation['sessions'])} "
        f"between {conversation['speaker_a']} and {conversation['speaker_b']}, "
        f"recorded at {session['date_time']}."
    )


def expected_context(conversation: dict, session: dict) -> str:
    return "\n".join(
        [context_head(conversation, session), *[line.strip() for line in media_lines(session["messages"])]]
    )


def verify(
    text: str,
    conversation: dict,
    session: dict,
    split_frontmatter: Parser,
    parse_turns: Parser,
) -> None:
    _frontmatter, body = split_frontmatter(text)
    turns = parse_turns(body)
    if not turns or turns[0] != ("Context", expected_context(conversation, session)):
        raise ValueError("round-trip context turn is missing")
    recovered = turns[1:]
    expected = [expected_turn(message) for message in session["messages"]]
    if recovered != expected:
        raise ValueError(
            f"round-trip tuple mismatch in conversation {conversation['conversation_idx']} "
            f"session {session['session_index']}"
        )
    if field_digest(recovered) != field_digest(expected):
        raise ValueError(
            f"round-trip sequence digest mismatch in conversation {conversation['conversation_idx']} "
            f"session {session['session_index']}"
        )


def session_by_number(conversation: dict, session_number: int) -> dict:
    for session in conversation["sessions"]:
        if int(session["session_index"]) == session_number:
            return session
    raise ValueError(
        f"session {session_number} not found in conversation {conversation['conversation_idx']}"
    )


def emit_session(
    conversation: dict,
    session: dict,
    output_dir: Path,
    split_frontmatter: Parser,
    parse_turns: Parser,
) -> tuple[Path, int]:
    text = render(conversation, session)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"session-{int(session['session_index']):03d}.md"
    path.write_text(text, encoding="utf-8")
    written = path.read_text(encoding="utf-8")
    verify(written, conversation, session, split_frontmatter, parse_turns)
    return path, len(session["messages"])


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    subcommands = cli.add_subparsers(dest="command", required=True)
    count = subcommands.add_parser("count")
    count.add_argument("conversation_idx", type=int)
    emit = subcommands.add_parser("emit")
    emit.add_argument("conversation_idx", type=int)
    emit.add_argument("session_no", type=int)
    emit.add_argument("output_dir", type=Path)
    emit.add_argument("--parser-app", type=Path, default=DEFAULT_APP)
    verify_all = subcommands.add_parser("verify-all")
    verify_all.add_argument("output_root", type=Path)
    verify_all.add_argument("--parser-app", type=Path, default=DEFAULT_APP)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "count":
            print(len(load_conversation(args.conversation_idx)["sessions"]))
            return 0
        split_frontmatter, parse_turns = framework_parser(args.parser_app)
        if args.command == "emit":
            conversation = load_conversation(args.conversation_idx)
            session = session_by_number(conversation, args.session_no)
            path, messages = emit_session(
                conversation, session, args.output_dir, split_frontmatter, parse_turns
            )
            print(f"verified_sessions=1 messages={messages} output={path}")
            return 0
        conversations = load_conversations()
        sessions_total = 0
        messages_total = 0
        for conversation in conversations:
            app_number = int(conversation["conversation_idx"]) + 1
            for session in conversation["sessions"]:
                output = args.output_root / f"app-{app_number:02d}" / f"s{int(session['session_index']):03d}"
                _path, messages = emit_session(
                    conversation, session, output, split_frontmatter, parse_turns
                )
                sessions_total += 1
                messages_total += messages
        print(
            f"verified_conversations={len(conversations)} verified_sessions={sessions_total} "
            f"verified_messages={messages_total}"
        )
        return 0
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
