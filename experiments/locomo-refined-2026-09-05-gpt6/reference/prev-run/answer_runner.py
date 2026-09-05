#!/usr/bin/env python3
"""Answer one conversation's questions through its own project's ./app.py ask.

Only two fields are ever read out of questions.jsonl: `qa_id` and `question`, plus
`conversation_idx` for routing. `answer`, `evidence`, `evidence_messages` and `category`
are never loaded, never printed and never reach the model — the projection below is the
mechanical guarantee of that.

Resumable: qa_ids already present in the output file are skipped, so a restart costs
nothing. Retryable failures back off inside this process rather than aborting the run.

    python3 answer_runner.py <NN> <conversation_idx> <style>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/data/qiwei/lcr-final")
QUESTIONS = ROOT / "data/data/public/questions.jsonl"
OUT_DIR = ROOT / "outputs/answers"

MAX_ATTEMPTS = 5
BACKOFF_START = 15
# The trailing stats line ./app.py ask prints after the answer, e.g.
#   (3.1s, 0 claims / 0 source windows hit, tokens {...})
STATS_RE = re.compile(r"^\s*\(\d+(?:\.\d+)?s,")


def projected_questions(conversation_idx: int) -> list[tuple[str, str]]:
    """The question-side projection: (qa_id, question) and nothing else."""
    rows: list[tuple[str, str]] = []
    with QUESTIONS.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if int(record["conversation_idx"]) != conversation_idx:
                continue
            rows.append((str(record["qa_id"]), str(record["question"])))
    return rows


def parse_answer(stdout: str) -> str | None:
    """Everything between the `A: ` line and the trailing stats line."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("A: ")), None)
    if start is None:
        return None
    collected = [lines[start][len("A: "):]]
    for line in lines[start + 1:]:
        if STATS_RE.match(line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def ask(app_dir: Path, question: str, style: str) -> str | None:
    proc = subprocess.run(
        ["./app.py", "ask", question, "--style", style],
        cwd=app_dir, capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        print(f"    ask rc={proc.returncode}: {proc.stderr.strip()[-300:]}", file=sys.stderr)
        return None
    return parse_answer(proc.stdout)


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    nn, conversation_idx, style = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    app_dir = ROOT / f"app-{nn}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"app-{nn}.jsonl"

    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                done.add(str(json.loads(line)["qa_id"]))
            except (json.JSONDecodeError, KeyError):
                continue

    rows = projected_questions(conversation_idx)
    todo = [row for row in rows if row[0] not in done]
    print(f"app-{nn}: {len(rows)} questions, {len(done)} already answered, {len(todo)} to go",
          flush=True)

    failures = 0
    with out_path.open("a", encoding="utf-8") as sink:
        for index, (qa_id, question) in enumerate(todo, start=1):
            answer = None
            delay = BACKOFF_START
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    answer = ask(app_dir, question, style)
                except subprocess.TimeoutExpired:
                    print(f"    {qa_id}: timeout on attempt {attempt}", file=sys.stderr)
                    answer = None
                if answer:
                    break
                if attempt < MAX_ATTEMPTS:
                    print(f"    {qa_id}: retry {attempt} in {delay}s", file=sys.stderr, flush=True)
                    time.sleep(delay)
                    delay *= 2
            if not answer:
                failures += 1
                answer = ""
                print(f"    {qa_id}: GIVE-UP, recording an empty answer", file=sys.stderr, flush=True)
            sink.write(json.dumps({"qa_id": qa_id, "predicted_answer": answer},
                                  ensure_ascii=False) + "\n")
            sink.flush()
            if index % 25 == 0 or index == len(todo):
                print(f"app-{nn}: {index}/{len(todo)} answered", flush=True)
    print(f"app-{nn}: finished, {failures} give-ups", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
