#!/usr/bin/env python3
"""Answer one conversation from the allowlisted question projection."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
MAX_ATTEMPTS = 5
BACKOFF_START = 15
ASK_TIMEOUT_SECONDS = 900
CITATION_RE = re.compile(r"\s*\[cite:\s*[^\]]*\]", re.IGNORECASE)
STATS_RE = re.compile(r"^\s*\([^\n]*tokens\s+(\{.*\})\)\s*$")


class ParsedResult(NamedTuple):
    answer: str
    token_usage: dict[str, int]


def strip_citations(text: str) -> str:
    output = CITATION_RE.sub("", text)
    output = re.sub(r"[ \t]{2,}", " ", output)
    output = re.sub(r"[ \t]+(?=[,.;)])", "", output)
    return "\n".join(line.rstrip() for line in output.split("\n")).strip()


def parse_result(stdout: str) -> ParsedResult:
    lines = stdout.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("A: ")), None)
    if start is None:
        raise ValueError("answer marker missing")
    answer_lines = [lines[start][3:]]
    usage_payload: str | None = None
    for line in lines[start + 1 :]:
        stats = STATS_RE.match(line)
        if stats:
            usage_payload = stats.group(1)
            break
        answer_lines.append(line)
    if usage_payload is None:
        raise ValueError("token usage marker missing")
    raw_usage = ast.literal_eval(usage_payload)
    if not isinstance(raw_usage, dict):
        raise ValueError("token usage is not an object")
    usage: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw_usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid token usage field: {key}")
        usage[key] = value
    answer = strip_citations("\n".join(answer_lines))
    if not answer:
        raise ValueError("semantic answer is empty")
    return ParsedResult(answer=answer, token_usage=usage)


def projected_questions(path: Path, conversation_idx: int) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if set(record) != {"qa_id", "conversation_idx", "question"}:
            raise ValueError("projected question record has unexpected fields")
        if int(record["conversation_idx"]) != conversation_idx:
            continue
        qa_id = str(record["qa_id"])
        if qa_id in seen:
            raise ValueError(f"duplicate projected qa_id: {qa_id}")
        seen.add(qa_id)
        rows.append((qa_id, str(record["question"])))
    if not rows:
        raise ValueError(f"no projected questions for conversation {conversation_idx}")
    return rows


def completed_ids(path: Path, allowed_ids: set[str]) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        qa_id = str(record.get("qa_id") or "")
        if qa_id not in allowed_ids:
            raise ValueError(f"answer file has out-of-scope qa_id at line {line_number}")
        if qa_id in completed:
            raise ValueError(f"answer file has duplicate qa_id: {qa_id}")
        if not str(record.get("predicted_answer") or "").strip():
            raise ValueError(f"answer file has empty prediction: {qa_id}")
        completed.add(qa_id)
    return completed


def assert_scope(app_dir: Path, app_number: str) -> None:
    env_lines = (app_dir / ".env").read_text(encoding="utf-8").splitlines()
    compose_prefix = f"PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-{app_number}-"
    if sum(1 for line in env_lines if line.startswith(compose_prefix)) != 1:
        raise ValueError(f"project compose scope check failed: app-{app_number}")
    if sum(
        1
        for line in env_lines
        if line == "PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai"
    ) != 1:
        raise ValueError(f"project provider scope check failed: app-{app_number}")
    app_source = (app_dir / "app.py").read_text(encoding="utf-8")
    if app_source.count("LCR2609 byte-exact blank-continuation compatibility") != 1:
        raise ValueError(f"project parser scope check failed: app-{app_number}")


def ask(
    app_dir: Path,
    question: str,
    *,
    style: str,
    evidence_strategy: str,
    answer_format: str,
) -> ParsedResult:
    process = subprocess.run(
        [
            "./app.py",
            "ask",
            question,
            "--style",
            style,
            "--evidence-strategy",
            evidence_strategy,
            "--answer-format",
            answer_format,
        ],
        cwd=app_dir,
        capture_output=True,
        text=True,
        timeout=ASK_TIMEOUT_SECONDS,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"ask exited with code {process.returncode}")
    return parse_result(process.stdout)


def budget_check(app_number: str) -> int:
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "budget.py"),
            "--compile-root",
            str(ROOT / "build-record" / "logs" / "compile"),
            "--answers-root",
            str(ROOT / "outputs" / "answers"),
            "--completed",
            "1382",
            "--total",
            "1382",
            "--out",
            str(ROOT / "build-record" / f"cost-answer-app-{app_number}.json"),
            "--enforce-hard",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return process.returncode


def run(
    app_number: str,
    conversation_idx: int,
    projection: Path,
    *,
    style: str,
    evidence_strategy: str,
    answer_format: str,
) -> int:
    app_dir = ROOT / f"app-{app_number}"
    output_dir = ROOT / "outputs" / "answers"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"app-{app_number}.jsonl"
    assert_scope(app_dir, app_number)
    rows = projected_questions(projection, conversation_idx)
    allowed_ids = {qa_id for qa_id, _question in rows}
    done = completed_ids(output_path, allowed_ids)
    todo = [(qa_id, question) for qa_id, question in rows if qa_id not in done]
    print(
        f"app-{app_number}: questions={len(rows)} complete={len(done)} remaining={len(todo)}",
        flush=True,
    )
    failures = 0
    with output_path.open("a", encoding="utf-8") as sink:
        for index, (qa_id, question) in enumerate(todo, start=1):
            parsed: ParsedResult | None = None
            delay = BACKOFF_START
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    parsed = ask(
                        app_dir,
                        question,
                        style=style,
                        evidence_strategy=evidence_strategy,
                        answer_format=answer_format,
                    )
                except (OSError, RuntimeError, SyntaxError, ValueError, subprocess.TimeoutExpired) as exc:
                    print(
                        f"app-{app_number}: qa_id={qa_id} attempt={attempt} failed={type(exc).__name__}",
                        file=sys.stderr,
                        flush=True,
                    )
                if parsed is not None:
                    break
                if attempt < MAX_ATTEMPTS:
                    time.sleep(delay)
                    delay *= 2
            if parsed is None:
                failures += 1
                continue
            record = {
                "qa_id": qa_id,
                "predicted_answer": parsed.answer,
                "token_usage": parsed.token_usage,
            }
            sink.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            sink.flush()
            os.fsync(sink.fileno())
            budget_rc = budget_check(app_number)
            if budget_rc == 60:
                (ROOT / "build-record" / "state" / "HARD-BUDGET-STOP").touch()
                print("hard budget ceiling reached", file=sys.stderr)
                return 60
            if budget_rc != 0:
                print("budget accounting failed", file=sys.stderr)
                return 1
            if index % 25 == 0 or index == len(todo):
                print(f"app-{app_number}: answered={index}/{len(todo)}", flush=True)
    print(f"app-{app_number}: failures={failures}", flush=True)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_number")
    parser.add_argument("conversation_idx", type=int)
    parser.add_argument("projection", type=Path)
    parser.add_argument("--style", choices=("concise",), default="concise")
    parser.add_argument("--evidence-strategy", choices=("select",), default="select")
    parser.add_argument("--answer-format", choices=("structured",), default="structured")
    args = parser.parse_args()
    try:
        if args.app_number not in {f"{number:02d}" for number in range(1, 11)}:
            raise ValueError("app_number must be 01 through 10")
        return run(
            args.app_number,
            args.conversation_idx,
            args.projection,
            style=args.style,
            evidence_strategy=args.evidence_strategy,
            answer_format=args.answer_format,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: answer runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
