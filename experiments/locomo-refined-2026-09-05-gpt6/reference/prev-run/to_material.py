#!/usr/bin/env python3
"""LoCoMo_refined conversation session -> one scaffold conversation material file.

The rendering follows the dataset's own multimodal rendering: `Speaker: text`, with
indented `[images]` / `[caption]` / `[query]` lines attached to the message above them.
Continuation lines are indented by two spaces so they can never be mistaken for a
speaker turn.

Every emitted file is verified by a round trip: the file is parsed back with the
framework's *actual* `parse_conversation_turns` (lifted verbatim out of the project's
app.py, so the check cannot drift from the parser that will read it), and the recovered
(speaker, text) sequence must equal the sequence built from the source JSON byte for
byte. A mismatch is a hard failure — nothing is ingested.

    python3 to_material.py count <conversation_idx>
    python3 to_material.py emit  <conversation_idx> <session_no> <out_dir>
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/data/qiwei/lcr-final")
DATASET = ROOT / "data/data/public/conversations.jsonl"
APP_PY = ROOT / "app-01/app.py"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


def _framework_parser():
    """Lift `parse_conversation_turns` and `split_frontmatter` out of the generated app.py
    verbatim, so the round trip is checked against the parser that actually runs."""
    src = APP_PY.read_text(encoding="utf-8")
    ns: dict = {"re": re}
    for name in ("split_frontmatter", "parse_conversation_turns"):
        match = re.search(rf"^def {name}\(.*?(?=^def |\Z)", src, re.S | re.M)
        if not match:
            raise SystemExit(f"error: could not lift {name}() from {APP_PY}")
        exec(compile(match.group(0), str(APP_PY), "exec"), ns)
    return ns["split_frontmatter"], ns["parse_conversation_turns"]


SPLIT_FRONTMATTER, PARSE_TURNS = _framework_parser()


def load_conversation(idx: int) -> dict:
    with DATASET.open(encoding="utf-8") as handle:
        for line in handle:
            conv = json.loads(line)
            if conv["conversation_idx"] == idx:
                return conv
    raise SystemExit(f"error: no conversation with idx {idx}")


def parse_date(date_time: str) -> str:
    """'1:56 pm on 8 May, 2023' -> '2023-05-08'."""
    match = re.match(r"^(\d{1,2}):(\d{2}) (am|pm) on (\d{1,2}) (\w+), (\d{4})$", date_time)
    if not match:
        raise SystemExit(f"error: unparseable session date_time {date_time!r}")
    day, month, year = int(match.group(4)), MONTHS[match.group(5)], int(match.group(6))
    return datetime(year, month, day).date().isoformat()


def message_lines(msg: dict) -> list[str]:
    """The lines this message contributes, first line included, continuations indented."""
    lines = []
    text_parts = [seg.strip() for seg in re.split(r"[\r\n]+", msg["text"])]
    lines.append(f"{msg['speaker']}: {text_parts[0]}")
    lines.extend(f"  {part}" for part in text_parts[1:])
    for url in msg.get("images") or []:
        lines.append(f"  [images] {url}")
    if msg.get("blip_caption"):
        lines.append(f"  [caption] {msg['blip_caption']}")
    if msg.get("query"):
        lines.append(f"  [query] {msg['query']}")
    return lines


def expected_turn(msg: dict) -> tuple[str, str]:
    """What the framework's parser must recover for this message."""
    lines = message_lines(msg)
    head = lines[0].split(":", 1)[1].lstrip()
    tail = [line.strip() for line in lines[1:]]
    return msg["speaker"], "\n".join([head, *tail])


def render(conv: dict, session: dict) -> str:
    a, b = conv["speaker_a"], conv["speaker_b"]
    idx = session["session_index"]
    total = conv["session_count"]
    when = session["date_time"]
    date = parse_date(when)
    body_lines = [
        f"Context: Session {idx} of {total} between {a} and {b}, recorded at {when}."
    ]
    for msg in session["messages"]:
        body_lines.extend(message_lines(msg))
    front = (
        "---\n"
        f"date: {date}\n"
        "type: conversation\n"
        f'title: "{a} & {b} — session {idx} of {total}, {when}"\n'
        "---\n\n"
    )
    return front + "\n".join(body_lines) + "\n"


def verify(text: str, conv: dict, session: dict) -> None:
    _front, body = SPLIT_FRONTMATTER(text)
    turns = PARSE_TURNS(body)
    if not turns or turns[0][0] != "Context":
        raise SystemExit("round-trip failure: context turn missing")
    recovered = turns[1:]
    expected = [expected_turn(m) for m in session["messages"]]
    if len(recovered) != len(expected):
        raise SystemExit(
            f"round-trip failure: {len(recovered)} turns recovered, {len(expected)} expected"
        )
    for i, (got, want) in enumerate(zip(recovered, expected)):
        if got != want:
            raise SystemExit(
                f"round-trip failure at message {i}: speaker {got[0]!r} vs {want[0]!r}; "
                f"text lengths {len(got[1])} vs {len(want[1])}"
            )


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    conv = load_conversation(int(sys.argv[2]))
    if cmd == "count":
        print(conv["session_count"])
        return 0
    if cmd == "emit":
        session_no = int(sys.argv[3])
        out_dir = Path(sys.argv[4])
        session = next(
            (s for s in conv["sessions"] if s["session_index"] == session_no), None
        )
        if session is None:
            raise SystemExit(f"error: no session {session_no} in {conv['sample_id']}")
        text = render(conv, session)
        verify(text, conv, session)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"session-{session_no:03d}.md"
        path.write_text(text, encoding="utf-8")
        print(
            f"{conv['sample_id']} session {session_no}/{conv['session_count']} -> {path} "
            f"({len(session['messages'])} messages, round trip verified)"
        )
        return 0
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
