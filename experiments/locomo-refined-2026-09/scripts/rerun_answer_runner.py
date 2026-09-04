#!/usr/bin/env python3
"""Answer one conversation concurrently into crash-safe follow-up records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from answer_runner import ParsedResult, parse_result, projected_questions


WORKERS = {
    "01": 4,
    "02": 4,
    "03": 3,
    "04": 3,
    "05": 3,
    "06": 3,
    "07": 3,
    "08": 3,
    "09": 3,
    "10": 3,
}
MAX_ATTEMPTS = 5
BACKOFF_START = 15
ASK_TIMEOUT_SECONDS = 900
TEMPLATE_SHA256 = "67f43f2ef0d71dba9d6499071b134b5b44ad60449a4ad6d2c938cb27fd5e1f92"
TOKEN_KEYS = {"input_tokens", "output_tokens", "total_tokens"}
RECORD_KEYS = {"qa_id", "predicted_answer", "token_usage"}


class AskError(RuntimeError):
    """A classified ask failure safe to expose in control logs."""


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_ask_command(question: str) -> list[str]:
    return [
        "./app.py",
        "ask",
        question,
        "--style",
        "concise",
        "--evidence-strategy",
        "select",
        "--answer-format",
        "structured",
    ]


def assert_scope(app_dir: Path, app_number: str) -> None:
    env_lines = (app_dir / ".env").read_text(encoding="utf-8").splitlines()
    prefix = f"PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-{app_number}-"
    if sum(line.startswith(prefix) for line in env_lines) != 1:
        raise ValueError(f"project compose scope check failed: app-{app_number}")
    if sum(
        line == "PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai"
        for line in env_lines
    ) != 1:
        raise ValueError(f"project provider scope check failed: app-{app_number}")
    if sha256_path(app_dir / "app.py") != TEMPLATE_SHA256:
        raise ValueError(f"project driver is not the measured template: app-{app_number}")


def ask_once(app_dir: Path, question: str) -> ParsedResult:
    process = subprocess.run(
        build_ask_command(question),
        cwd=app_dir,
        capture_output=True,
        text=True,
        timeout=ASK_TIMEOUT_SECONDS,
        check=False,
    )
    if process.returncode != 0:
        diagnostic = (process.stderr + "\n" + process.stdout).lower()
        kind = "rate_limit" if "429" in diagnostic or "rate limit" in diagnostic else "command"
        raise AskError(kind)
    try:
        return parse_result(process.stdout)
    except (SyntaxError, ValueError) as exc:
        raise AskError("invalid_output") from exc


def _failure_kind(exc: BaseException) -> str:
    if isinstance(exc, AskError):
        return str(exc) or "ask"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "timeout"
    return type(exc).__name__


def answer_with_retry(
    qa_id: str,
    question: str,
    *,
    ask_fn: Callable[[str], ParsedResult],
    sleep_fn: Callable[[int], object] = time.sleep,
) -> dict[str, object]:
    delay = BACKOFF_START
    last_kind = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            parsed = ask_fn(question)
            return {
                "qa_id": qa_id,
                "predicted_answer": parsed.answer,
                "token_usage": parsed.token_usage,
            }
        except (AskError, OSError, subprocess.TimeoutExpired) as exc:
            last_kind = _failure_kind(exc)
            print(
                f"qa_id={qa_id} attempt={attempt} failed={last_kind}",
                file=sys.stderr,
                flush=True,
            )
        if attempt < MAX_ATTEMPTS:
            sleep_fn(delay)
            delay *= 2
    raise AskError(f"exhausted_{last_kind}")


def _validate_record(record: object, allowed_ids: set[str]) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise ValueError("answer record has unexpected fields")
    qa_id = str(record.get("qa_id") or "")
    if qa_id not in allowed_ids:
        raise ValueError(f"answer record has out-of-scope qa_id: {qa_id}")
    if not str(record.get("predicted_answer") or "").strip():
        raise ValueError(f"answer record has empty prediction: {qa_id}")
    usage = record.get("token_usage")
    if not isinstance(usage, dict) or set(usage) != TOKEN_KEYS:
        raise ValueError(f"answer record has invalid token usage: {qa_id}")
    for key in TOKEN_KEYS:
        value = usage[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"answer record has invalid {key}: {qa_id}")
    return record


def _record_path(record_dir: Path, qa_id: str) -> Path:
    name = hashlib.sha256(qa_id.encode("utf-8")).hexdigest() + ".json"
    return record_dir / name


def write_record_atomic(record_dir: Path, record: dict[str, object]) -> Path:
    qa_id = str(record.get("qa_id") or "")
    _validate_record(record, {qa_id})
    record_dir.mkdir(parents=True, exist_ok=True)
    destination = _record_path(record_dir, qa_id)
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != record:
            raise ValueError(f"refusing to overwrite a different record: {qa_id}")
        return destination
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=record_dir, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, destination)
    return destination


def load_records(record_dir: Path, allowed_ids: set[str]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    if not record_dir.exists():
        return records
    for path in sorted(record_dir.glob("*.json")):
        record = _validate_record(json.loads(path.read_text(encoding="utf-8")), allowed_ids)
        qa_id = str(record["qa_id"])
        if _record_path(record_dir, qa_id) != path:
            raise ValueError(f"answer record filename does not match qa_id: {qa_id}")
        if qa_id in records:
            raise ValueError(f"duplicate answer record: {qa_id}")
        records[qa_id] = record
    return records


def assemble_app_answers(
    rows: list[tuple[str, str]],
    records: dict[str, dict[str, object]],
    output_path: Path,
) -> None:
    ordered_ids = [qa_id for qa_id, _question in rows]
    missing = [qa_id for qa_id in ordered_ids if qa_id not in records]
    if missing or len(records) != len(ordered_ids):
        raise ValueError(
            f"app answer set incomplete: records={len(records)} missing={len(missing)}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output_path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            for qa_id in ordered_ids:
                handle.write(
                    json.dumps(records[qa_id], ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, output_path)


def run(
    app_number: str,
    conversation_idx: int,
    projection: Path,
    answers_root: Path,
    workers: int,
) -> int:
    if workers != WORKERS[app_number]:
        raise ValueError(f"worker allocation drift for app-{app_number}")
    app_dir = ROOT / f"app-{app_number}"
    assert_scope(app_dir, app_number)
    rows = projected_questions(projection, conversation_idx)
    allowed_ids = {qa_id for qa_id, _question in rows}
    record_dir = answers_root / "records" / f"app-{app_number}"
    records = load_records(record_dir, allowed_ids)
    todo = [(qa_id, question) for qa_id, question in rows if qa_id not in records]
    print(
        f"app-{app_number}: questions={len(rows)} complete={len(records)} "
        f"remaining={len(todo)} workers={workers}",
        flush=True,
    )
    failures: list[str] = []
    if todo:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"app-{app_number}") as pool:
            futures = {
                pool.submit(
                    answer_with_retry,
                    qa_id,
                    question,
                    ask_fn=lambda value, app=app_dir: ask_once(app, value),
                ): qa_id
                for qa_id, question in todo
            }
            completed = 0
            for future in as_completed(futures):
                qa_id = futures[future]
                try:
                    write_record_atomic(record_dir, future.result())
                    completed += 1
                    if completed % 10 == 0 or completed == len(todo):
                        print(
                            f"app-{app_number}: newly_completed={completed}/{len(todo)}",
                            flush=True,
                        )
                except (AskError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                    failures.append(qa_id)
                    print(
                        f"app-{app_number}: qa_id={qa_id} final_failure={_failure_kind(exc)}",
                        file=sys.stderr,
                        flush=True,
                    )
    records = load_records(record_dir, allowed_ids)
    if failures or len(records) != len(rows):
        print(
            f"app-{app_number}: failures={len(failures)} records={len(records)}/{len(rows)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    assemble_app_answers(rows, records, answers_root / f"app-{app_number}.jsonl")
    print(f"app-{app_number}: COMPLETE records={len(records)}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_number")
    parser.add_argument("conversation_idx", type=int)
    parser.add_argument("projection", type=Path)
    parser.add_argument("answers_root", type=Path)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.app_number not in WORKERS:
            raise ValueError("app_number must be 01 through 10")
        return run(
            args.app_number,
            args.conversation_idx,
            args.projection,
            args.answers_root,
            args.workers,
        )
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: rerun answer runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
