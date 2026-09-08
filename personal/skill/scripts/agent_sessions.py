#!/usr/bin/env python3
"""Convert selected coding-agent sessions to agent-session/v1, using only the stdlib."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

SCHEMA = "pneuma.source.agent-session/v1"
CONVERTER_VERSION = 1
ACKNOWLEDGEMENTS = frozenset({
    "ok", "okay", "yes", "no", "yep", "nope", "sure", "thanks", "thank you", "continue",
    "proceed", "done", "agreed", "approved", "go", "great", "fine", "ack", "acknowledged",
    "\u597d", "\u597d\u7684", "\u884c", "\u53ef\u4ee5", "\u7ee7\u7eed", "\u662f", "\u5426",
    "\u786e\u8ba4", "\u8c22\u8c22", "\u540c\u610f",
})
CONTEXT_PREFIXES = (
    "# AGENTS.md instructions", "<environment_context>", "<user_instructions>",
    "<permissions instructions>", "<turn_aborted>", "<system-reminder>",
    "<local-command-caveat>", "<local-command-stdout>",
)


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("timestamp must be ISO 8601 with a timezone") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def jsonl(path: Path, data: bytes | None = None):
    import io

    with (path.open(encoding="utf-8") if data is None else io.StringIO(data.decode("utf-8"))) as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError(f"invalid JSON at line {number}") from None
            if not isinstance(row, dict):
                raise ValueError(f"expected an object at line {number}")
            yield row


def subagent(value) -> bool:
    return (isinstance(value, dict) and "subagent" in value) or (
        isinstance(value, str) and value.lower().startswith("subagent")
    )


def text_content(content, *, owner: bool = False) -> str:
    """Keep text blocks in order; join distinct blocks with one newline, never strip them."""
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [block["text"] for block in content if isinstance(block, dict)
                 and block.get("type") in {"text", "input_text", "output_text"}
                 and isinstance(block.get("text"), str)]
    else:
        texts = []
    if owner:
        texts = [text for text in texts if not text.lstrip().startswith(CONTEXT_PREFIXES)]
    return "\n".join(texts)


def action_stub(name, arguments=None) -> str:
    """Expose only the tool name and a path or executable; never copy command arguments."""
    tool = re.sub(r"[^a-zA-Z0-9_.:-]", "_", str(name or "tool"))[:64]
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = None
    detail = ""
    if isinstance(arguments, dict):
        for key in ("file_path", "path", "target_file"):
            if isinstance(arguments.get(key), str):
                detail = " ".join(arguments[key].split())
                break
        if not detail:
            command = arguments.get("command", arguments.get("cmd"))
            if isinstance(command, str):
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = []
                # Assignments, shell fragments and inline programs are not a stub.
                if words and re.fullmatch(r"[a-zA-Z0-9_./-]+", words[0]):
                    detail = words[0]
    return f"{tool}{': ' + detail if detail else ''}"[:200]


@dataclass
class Session:
    provider: str
    session_id: str
    path: Path
    project: Path | None
    model: str | None = None
    is_subagent: bool = False
    project_conflict: bool = False
    turns: list[dict] = field(default_factory=list)
    last_at: datetime | None = None
    timestamp_repairs: int = 0

    def observe_time(self, value) -> None:
        if value is not None:
            self.last_at = timestamp(value)

    def add(self, role: str, kind: str, text: str) -> None:
        if not text.strip():
            return
        if self.last_at is None:
            raise ValueError("a retained turn has no recorded timestamp")
        self.turns.append({"role": role, "kind": kind, "at": self.last_at.isoformat(), "text": text})

    def finish(self) -> Session:
        # Stable chronological order handles delayed writes without inventing timestamps.
        ordered = sorted(self.turns, key=lambda turn: timestamp(turn["at"]))
        self.timestamp_repairs = sum(a is not b for a, b in zip(self.turns, ordered))
        self.turns = [{"turn_id": f"t{index}", **turn} for index, turn in enumerate(ordered, 1)]
        return self

    def payload(self, owner_id: str, verdict: dict) -> dict:
        if not owner_id.strip():
            raise ValueError("owner-id must be non-blank")
        if not any(turn["role"] == "owner" for turn in self.turns):
            raise ValueError("a session needs at least one owner turn")
        agent = {"name": self.provider}
        if self.model:
            agent["model"] = self.model
        result = {
            "schema": SCHEMA, "provider": self.provider, "session_id": self.session_id,
            "owner_id": owner_id, "agent": agent,
            "started_at": self.turns[0]["at"], "ended_at": self.turns[-1]["at"],
            "turns": self.turns,
            "metadata": {"converter_version": CONVERTER_VERSION, "triage": verdict,
                         "timestamp_reordered_turns": self.timestamp_repairs},
        }
        if self.project is not None:
            result["project"] = {"path": str(self.project), "name": self.project.name or str(self.project)}
        return result


def read_claude(path: Path, project: Path, data: bytes | None = None) -> Session:
    session = Session("claude-code", path.stem, path, project,
                      is_subagent="subagents" in path.parts or path.name.startswith("agent-"))
    seen = set()
    saw_sidechain = False
    saw_primary = False
    for row in jsonl(path, data):
        session.observe_time(row.get("timestamp"))
        if row.get("type") not in {"user", "assistant"}:
            continue
        if row.get("isSidechain") or row.get("isSubagent"):
            saw_sidechain = True
            continue
        if session.is_subagent or row.get("isCompactSummary") or row.get("isMeta"):
            continue
        saw_primary = True
        if row.get("cwd") and Path(row["cwd"]).expanduser().resolve() != project:
            # Encoded directory names can collide. Never assign the wrong project.
            session.project = None
            session.project_conflict = True
        identity = row.get("uuid")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        if row.get("sessionId"):
            session.session_id = str(row["sessionId"])
        message = row.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if row["type"] == "user":
            session.add("owner", "say", text_content(content, owner=True))
        else:
            if message.get("model"):
                session.model = str(message["model"])
            if isinstance(content, str):
                session.add("agent", "narrative", content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        session.add("agent", "narrative", block["text"])
                    elif block.get("type") == "tool_use":
                        session.add("agent", "action", action_stub(block.get("name"), block.get("input")))
    session.is_subagent = session.is_subagent or (saw_sidechain and not saw_primary)
    return session.finish()


def read_codex(path: Path, project: Path, data: bytes | None = None) -> Session:
    session = Session("codex", path.stem, path, project)
    events = []
    seen = set()
    for row in jsonl(path, data):
        session.observe_time(row.get("timestamp"))
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        kind = row.get("type")
        if kind == "session_meta":
            session.session_id = str(payload.get("id") or payload.get("session_id") or path.stem)
            session.is_subagent = subagent(payload.get("source")) or subagent(payload.get("thread_source"))
            if payload.get("cwd") and Path(payload["cwd"]).expanduser().resolve() != project:
                session.project = None
                session.project_conflict = True
            if session.last_at is None:
                session.observe_time(payload.get("timestamp"))
        if session.is_subagent:
            continue
        if kind == "turn_context":
            if payload.get("model"):
                session.model = str(payload["model"])
        elif kind == "response_item":
            item_type = payload.get("type")
            identity = payload.get("id") or payload.get("call_id")
            key = (item_type, identity)
            if identity and key in seen:
                continue
            if identity:
                seen.add(key)
            if item_type == "message" and payload.get("role") in {"user", "assistant"}:
                owner = payload["role"] == "user"
                session.add("owner" if owner else "agent", "say" if owner else "narrative",
                            text_content(payload.get("content"), owner=owner))
            elif item_type in {"function_call", "custom_tool_call", "tool_call"}:
                session.add("agent", "action", action_stub(payload.get("name"), payload.get("arguments")))
        elif kind == "event_msg" and payload.get("type") in {"user_message", "agent_message"}:
            owner = payload["type"] == "user_message"
            text = text_content(payload.get("message"), owner=owner)
            if text.strip() and session.last_at is not None:
                events.append({"role": "owner" if owner else "agent", "kind": "say" if owner else "narrative",
                               "at": session.last_at.isoformat(), "text": text})
    # Older rollouts may have event messages only. Prefer response items per role:
    # modern rollouts repeat those exact messages in event_msg (including final answers).
    roles = {turn["role"] for turn in session.turns if turn["kind"] != "action"}
    session.turns.extend(turn for turn in events if turn["role"] not in roles)
    return session.finish()


def low_signal(text: str, ack_max_words: int) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and all(re.match(r"^/[a-zA-Z][\w:-]*(?:\s|$)", line) for line in lines):
        return True
    if text.lstrip().startswith("<command-name>"):
        return True
    normalized = text.strip().casefold().strip(".!?,;:\u3002\uff01\uff1f")
    return len(normalized.split()) <= ack_max_words and normalized in ACKNOWLEDGEMENTS


def triage(session: Session, *, min_owner_turns: int = 3, min_owner_chars: int = 200,
           ack_max_words: int = 1, purpose: str = "project") -> dict:
    if min_owner_turns < 3 or min_owner_chars < 0 or ack_max_words < 1:
        raise ValueError("thresholds require min-owner-turns >= 3, min-owner-chars >= 0, ack-max-words >= 1")
    owners = [turn["text"] for turn in session.turns if turn["role"] == "owner"]
    chars = sum(len(text) for text in owners)
    reasons = []
    if not owners:
        reasons.append("no_owner_turns")
    if chars < min_owner_chars:
        reasons.append("owner_text_below_threshold")
    if session.is_subagent:
        reasons.append("subagent")
    if session.project is None:
        reasons.append("project_not_matched")
    if session.project_conflict:
        reasons.append("project_directory_conflict")
    if len(owners) < min_owner_turns:
        reasons.append("too_few_owner_turns")
    if owners and all(low_signal(text, ack_max_words) for text in owners):
        reasons.append("commands_or_acknowledgements_only")
    if purpose != "project":
        reasons.append(f"{purpose}_session")
    verdict = ("skip" if not owners or chars < min_owner_chars or session.project_conflict
               else "index" if reasons else "compile")
    return {"verdict": verdict, "canonical_treatment": "full" if verdict == "compile" else "none",
            "reasons": reasons, "owner_turns": len(owners), "owner_chars": chars, "purpose": purpose,
            "thresholds": {"min_owner_turns": min_owner_turns, "min_owner_chars": min_owner_chars,
                           "ack_max_words": ack_max_words}}


def discover(project: Path, claude_root: Path, codex_root: Path):
    # A project selection is exact, never a recursive import of adjacent projects.
    encodings = {str(project).replace("/", "-"), re.sub(r"[^a-zA-Z0-9]", "-", str(project))}
    for encoded in sorted(encodings):
        directory = claude_root / encoded
        paths = set(directory.glob("*.jsonl")) | set(directory.glob("*/subagents/*.jsonl"))
        for path in sorted(paths):
            if not path.is_symlink():
                yield "claude-code", path
    for path in sorted(codex_root.glob("*/*/*/rollout-*.jsonl")):
        if path.is_symlink():
            continue
        try:
            first = next(jsonl(path), {})
        except (OSError, ValueError):
            continue
        payload = first.get("payload", {})
        if first.get("type") != "session_meta" or not isinstance(payload, dict):
            continue
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and Path(cwd).expanduser().resolve() == project:
            yield "codex", path


def scan(args):
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError("--project must name an existing directory")
    since = timestamp(args.since) if args.since else None
    for provider, path in discover(project, args.claude_root.expanduser(), args.codex_root.expanduser()):
        try:
            session = read_claude(path, project) if provider == "claude-code" else read_codex(path, project)
            if args.session_id and session.session_id not in args.session_id:
                continue
            ended = timestamp(session.turns[-1]["at"]) if session.turns else session.last_at
            if since and (ended is None or ended < since):
                continue
            verdict = triage(session, min_owner_turns=args.min_owner_turns,
                             min_owner_chars=args.min_owner_chars, ack_max_words=args.ack_max_words,
                             purpose=args.purpose)
            yield session, verdict, None
        except (OSError, ValueError) as exc:
            yield None, {"provider": provider, "file": str(path)}, str(exc)


def encoded_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def session_key(session: Session) -> str:
    return hashlib.sha256(encoded_json([session.provider, session.session_id,
                                       str(session.project) if session.project else None]).encode()).hexdigest()


def export_session(session: Session, verdict: dict, owner_id: str, directory: Path):
    payload = session.payload(owner_id, verdict)
    path = directory / f"{session.provider}-{session_key(session)}.json"
    atomic_json(path, payload)
    return path, payload


def read_record(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "sessions": {}}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ValueError("ingested-sessions.json is invalid; repair edition state before retrying") from None
    if (not isinstance(record, dict) or record.get("version") != 1
            or not isinstance(record.get("sessions"), dict)
            or not all(isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
                       for entry in record["sessions"].values())):
        raise ValueError("unsupported ingested-sessions.json shape")
    return record


def selected_library(name: str | None) -> dict:
    command = ["pkchome"]
    if name:
        command += ["--library", name]
    result = subprocess.run([*command, "library", "show"], capture_output=True, text=True, check=True)
    library = json.loads(result.stdout)
    if (not isinstance(library, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", library.get("name", ""))
            or not isinstance(library.get("path"), str) or not isinstance(library.get("tenant"), str)):
        raise ValueError("pkchome library show returned no library identity")
    return library


SYNC_COUNTS = ("scanned", "new", "increments", "held", "unchanged", "rewritten", "ingested", "skipped")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_sync_state(path: Path) -> dict:
    if not path.exists():
        legacy = read_record(path.with_name("ingested-sessions.json"))
        return {"version": 1, "sessions": {}, "legacy": legacy["sessions"],
                "last_run_at": None, "last_result": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (state["version"] != 1 or not isinstance(state["sessions"], dict)
                or not isinstance(state.get("legacy", {}), dict)):
            raise ValueError()
        for entry in state["sessions"].values():
            if (not isinstance(entry["exported_turns"], int) or entry["exported_turns"] < 0
                    or not isinstance(entry["source_ids"], list)
                    or not isinstance(entry["prefix_hash"], str)):
                raise ValueError()
        return state
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid sync-state.json; repair edition state before retrying") from None


@contextmanager
def sync_lock(path: Path, *, dry_run: bool = False):
    import fcntl

    # A dry pass creates no directory, lock or state. It may observe the previous atomic
    # snapshot if the first writer starts concurrently, but never competes as a writer.
    if dry_run and not path.exists():
        yield
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("r" if dry_run else "a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another sync is running for this library") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def sync_running(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sync_lock(path, dry_run=True):
            return False
    except ValueError:
        return True


def read_session(provider: str, path: Path, project: Path, data: bytes) -> Session:
    return (read_claude if provider == "claude-code" else read_codex)(path, project, data)


def complete_jsonl(data: bytes) -> bytes:
    """Keep a valid final record even without a newline; defer a partial write."""
    boundary = data.rfind(b"\n") + 1
    if boundary < len(data):
        try:
            json.loads(data[boundary:])
        except ValueError:
            return data[:boundary]
    return data


def empty_cursor(session: Session) -> dict:
    return {"provider": session.provider, "session_id": session.session_id,
            "file": str(session.path), "source_ids": [], "exported_turns": 0,
            "last_turn_id": None, "last_at": None, "prefix_hash": digest(b""),
            "file_size": 0, "exported_bytes": 0, "held": None}


def pending_turns(session: Session, earlier: Session, exported: int) -> Session:
    # Readers sort delayed writes by timestamp. Subtract a multiset of retained turns,
    # not a position in that reordered list, then number ONLY the new turns. Equal real
    # utterances remain distinct; event mirrors are already removed by the reader.
    def identity(turn):
        return encoded_json({k: v for k, v in turn.items() if k != "turn_id"})

    seen = Counter(identity(turn) for turn in earlier.turns)
    turns = []
    for turn in session.turns:
        key = identity(turn)
        if seen[key]:
            seen[key] -= 1
        else:
            turns.append({**turn, "turn_id": f"t{exported + len(turns) + 1}"})
    if any(seen.values()):
        raise ValueError("rewritten: previously retained turns changed")
    return replace(session, turns=turns)


def legacy_prefix(session: Session, data: bytes, entry: dict, owner_id: str, options: dict):
    # v1 kept only a payload hash, not its source ID or byte boundary. Recover an EXACT
    # historical payload, including the converter's timestamp-repair metadata. Never
    # assume today's end was the old end. This one-time search may be expensive.
    ends = [index + 1 for index, byte in enumerate(data) if byte == 10]
    if data and (not ends or ends[-1] != len(data)):
        ends.append(len(data))
    for end in reversed(ends):
        old = read_session(session.provider, session.path, session.project, data[:end])
        if not old.turns or not any(t["role"] == "owner" for t in old.turns):
            continue
        for purpose in dict.fromkeys([options.get("purpose", "project"), "project", "research", "chat"]):
            verdict = triage(old, **{**options, "purpose": purpose})
            payload = old.payload(owner_id, verdict)
            if digest(encoded_json(payload).encode()) == entry["sha256"]:
                cursor = empty_cursor(old)
                cursor.update(exported_turns=len(old.turns), last_turn_id=old.turns[-1]["turn_id"],
                              last_at=old.turns[-1]["at"], exported_bytes=end,
                              file_size=end, prefix_hash=digest(data[:end]))
                return payload, cursor
    return None


def sync_pass(library: dict, watches: list[dict], *, dry_run: bool = False,
              rewritten: str = "report", claude_root: Path | None = None,
              codex_root: Path | None = None, options: dict | None = None,
              owner_id: str | None = None, session_ids: list[str] | None = None,
              pkchome: str = "pkchome") -> dict:
    """One edition-owned pass. Ingest is its only library write door."""
    directory = Path(library["path"])
    state_path = directory / "sync-state.json"
    lock = directory.parents[1] / "run" / f"{library['name']}.sync.lock"
    with sync_lock(lock, dry_run=dry_run):
        return _sync_pass(library, watches, state_path, dry_run=dry_run, rewritten=rewritten,
                          claude_root=claude_root or Path.home() / ".claude/projects",
                          codex_root=codex_root or Path.home() / ".codex/sessions",
                          options=options or {}, owner_id=owner_id or library["tenant"],
                          session_ids=session_ids, pkchome=pkchome)


def _sync_pass(library, watches, state_path, *, dry_run, rewritten, claude_root, codex_root,
               options, owner_id, session_ids, pkchome):
    state = read_sync_state(state_path)
    report = {**dict.fromkeys(SYNC_COUNTS, 0), "sessions": [], "dry_run": dry_run}
    state.setdefault("legacy", {})

    def save():
        if not dry_run:
            atomic_json(state_path, state)

    def ingest(key, payload, cursor, line, *, migration=False):
        # Journal the exact payload before the external call. A crash after ingest but
        # before cursor persistence replays those same bytes through library deduplication,
        # even if the live transcript grows meanwhile. No transcript enters sync-state.
        path = state_path.parent / "sync-pending" / f"{key}.json"
        prior = state["sessions"].get(key, empty_cursor_from(cursor))
        pending = prior.get("pending")
        if pending is None:
            atomic_json(path, payload)
            pending = {"cursor": cursor, "sha256": digest(encoded_json(payload).encode()),
                       "migration": migration}
            state["sessions"][key] = {**prior, "pending": pending}
            save()
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if digest(encoded_json(payload).encode()) != pending["sha256"]:
                raise ValueError("pending sync payload changed; repair edition state before retrying")
            cursor = pending["cursor"]
            migration = pending["migration"]
        command = [pkchome, "exec", "--library", library["name"], "--", "pkc", "ingest",
                   "--contract", "agent-session/v1", "--file", str(path), "--json"]
        if payload["metadata"]["triage"]["canonical_treatment"] == "none":
            command += ["--intake", "searchable"]
        env = {**os.environ, "PKC_HOME": str(state_path.parent.parents[1])}
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        if result.returncode:
            raise ValueError(f"ingest failed (exit {result.returncode}); exact payload retained for retry")
        try:
            body = json.loads(result.stdout)
            source = body["sources"][0]
            source_id = source["source_id"]
            if len(body["sources"]) != 1 or not isinstance(source_id, str) or not source_id:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise ValueError("ingest returned no single source ID; exact payload retained for retry") from None
        cursor["source_ids"] = [*cursor["source_ids"], source_id]
        state["sessions"][key] = cursor
        state["legacy"].pop(key, None)
        save()
        path.unlink(missing_ok=True)
        line.update(source_id=source_id, compile_jobs=body.get("compile_jobs", []),
                    deduplicated=source.get("deduplicated", False))
        if not migration:
            report["ingested"] += 1
        else:
            line["migrated"] = True

    # Finish uncertain ingests even when a watch or its transcript was removed. The bytes
    # were already authorized and may already be in L0; abandoning them loses the cursor.
    recovered = set()
    for key, entry in list(state["sessions"].items()):
        if "pending" not in entry:
            continue
        line = {"provider": entry["provider"], "session_id": entry["session_id"],
                "file": entry["file"], "status": "retry"}
        recovered.add((entry["provider"], entry["file"]))
        report["scanned"] += 1
        try:
            if not dry_run:
                ingest(key, None, entry, line)
        except (OSError, ValueError) as exc:
            line.update(status="error", error=str(exc))
            report["skipped"] += 1
        report["sessions"].append(line)

    seen = set(recovered)
    by_file = {(entry["provider"], entry["file"]): (key, entry)
               for key, entry in state["sessions"].items()}
    for watch in watches:
        project = Path(watch["path"]).expanduser().resolve()
        if not project.is_dir():
            report["skipped"] += 1
            report["sessions"].append({"file": str(project), "status": "error", "error": "watched directory missing"})
            continue
        since = timestamp(watch["since"]) if watch.get("since") else None
        for provider, path in discover(project, claude_root.expanduser(), codex_root.expanduser()):
            if provider not in watch.get("harnesses", ["claude-code", "codex"]):
                continue
            if (provider, str(path)) in seen:
                continue
            seen.add((provider, str(path)))
            line = {"provider": provider, "file": str(path)}
            report["scanned"] += 1
            try:
                # Read one byte snapshot, deferring an in-flight final JSONL record.
                # Neither selection nor progress uses mtime.
                data = complete_jsonl(path.read_bytes())
                previous = by_file.get((provider, str(path)))
                if previous:
                    _, observed = previous
                    line["session_id"] = observed["session_id"]
                    if session_ids and observed["session_id"] not in session_ids:
                        report["scanned"] -= 1
                        continue
                    intact = (len(data) >= observed["file_size"]
                              and digest(data[:observed["file_size"]]) == observed["prefix_hash"])
                    # A rewritten prefix is a rewrite even when it no longer parses.
                    if not intact and rewritten != "reingest":
                        report["rewritten"] += 1
                        line["status"] = "rewritten"
                        report["sessions"].append(line)
                        continue
                    if intact and len(data) == observed["file_size"]:
                        report["unchanged"] += 1
                        line["status"] = "unchanged"
                        if observed["held"]:
                            report["held"] += 1
                            line["held"] = observed["held"]
                        report["sessions"].append(line)
                        continue
                session = read_session(provider, path, project, data)
                if session_ids and session.session_id not in session_ids:
                    report["scanned"] -= 1
                    continue
                line["session_id"] = session.session_id
                key = session_key(session)
                entry = state["sessions"].get(key)
                # Locate rewrites that changed provider identity/project attribution too.
                if entry is None:
                    if previous:
                        key, entry = previous
                legacy = state["legacy"].get(key)
                forced_rewrite = False
                if legacy and entry is None:
                    recovered_prefix = legacy_prefix(session, data, legacy, owner_id, options)
                    if recovered_prefix is None:
                        forced_rewrite = True
                    elif dry_run:
                        _, entry = recovered_prefix
                        line["migration_due"] = True
                    else:
                        payload, entry = recovered_prefix
                        ingest(key, payload, entry, line, migration=True)
                        entry = state["sessions"][key]
                was_rewritten = forced_rewrite or bool(entry and (
                    len(data) < entry["file_size"]
                    or digest(data[:entry["file_size"]]) != entry["prefix_hash"]
                    or session.session_id != entry["session_id"]))
                if was_rewritten:
                    report["rewritten"] += 1
                    line["status"] = "rewritten"
                    if rewritten != "reingest":
                        report["sessions"].append(line)
                        continue
                    # Preserve the source history, but this replacement starts afresh and
                    # has no 'continues' assertion. Publish the reset only after success.
                    old_ids = entry["source_ids"] if entry else []
                    entry = empty_cursor(session)
                    entry["source_ids"] = old_ids
                if entry and not was_rewritten and len(data) == entry["file_size"]:
                    report["unchanged"] += 1
                    line["status"] = "unchanged"
                    if entry["held"]:
                        report["held"] += 1
                        line["held"] = entry["held"]
                    report["sessions"].append(line)
                    continue
                entry = entry or empty_cursor(session)
                earlier = read_session(provider, path, project, data[:entry["exported_bytes"]])
                try:
                    increment = pending_turns(session, earlier, entry["exported_turns"])
                except ValueError:
                    if rewritten != "reingest":
                        raise
                    report["rewritten"] += 1
                    was_rewritten = True
                    old_ids = entry["source_ids"]
                    entry = empty_cursor(session)
                    entry["source_ids"] = old_ids
                    increment = session
                verdict = triage(increment, **options)
                cursor = {**entry, "file": str(path), "file_size": len(data), "prefix_hash": digest(data)}
                line["triage"] = verdict
                if session.is_subagent or session.project_conflict or (
                    since and not entry["exported_turns"] and (
                        not session.turns or timestamp(session.turns[-1]["at"]) < since)):
                    line["status"] = "skipped"
                    report["skipped"] += 1
                elif not increment.turns:
                    line["status"] = "unchanged"
                    report["unchanged"] += 1
                elif (verdict["owner_turns"] < verdict["thresholds"]["min_owner_turns"]
                      or verdict["owner_chars"] < verdict["thresholds"]["min_owner_chars"]):
                    cursor["held"] = {"owner_turns": verdict["owner_turns"], "chars": verdict["owner_chars"]}
                    line.update(status="held", held=cursor["held"])
                    report["held"] += 1
                else:
                    kind = "increments" if entry["exported_turns"] else "new"
                    report[kind] += 1
                    if dry_run:
                        line["status"] = "would_ingest"
                        report["sessions"].append(line)
                        continue
                    payload = increment.payload(owner_id, verdict)
                    part = len(entry["source_ids"]) + 1
                    payload["metadata"].update(from_turn=increment.turns[0]["turn_id"], part=part)
                    if entry["exported_turns"]:
                        payload["metadata"]["continues"] = entry["source_ids"][-1]
                    if was_rewritten:
                        payload["metadata"]["rewritten"] = True
                    cursor.update(exported_turns=entry["exported_turns"] + len(increment.turns),
                                  last_turn_id=increment.turns[-1]["turn_id"], last_at=increment.turns[-1]["at"],
                                  exported_bytes=len(data), held=None)
                    line["status"] = "ingested"
                    ingest(key, payload, cursor, line)
                    report["sessions"].append(line)
                    continue
                # Observation advances the file fingerprint, never the export cursor.
                if not was_rewritten:
                    state["sessions"][key] = cursor
                    save()
            except (OSError, ValueError) as exc:
                if str(exc).startswith("rewritten:"):
                    report["rewritten"] += 1
                    line.update(status="rewritten", error=str(exc))
                else:
                    report["skipped"] += 1
                    line.update(status="error", error=str(exc))
            report["sessions"].append(line)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_result"] = report
    save()
    return report


def empty_cursor_from(cursor: dict) -> dict:
    return {**cursor, "source_ids": [], "exported_turns": 0, "exported_bytes": 0,
            "file_size": 0, "prefix_hash": digest(b""), "held": None,
            "last_turn_id": None, "last_at": None}


def render_sync(report: dict) -> str:
    lines = []
    for row in report["sessions"]:
        detail = f" {row['held']['owner_turns']} owner turns / {row['held']['chars']} chars" if row.get("held") else ""
        if row.get("source_id"):
            detail += f" source {row['source_id']} · {len(row.get('compile_jobs', []))} compile jobs enqueued"
        if row.get("migration_due"):
            detail += " · migration due"
        lines.append(f"{row['status']}: {row.get('provider', '')} {row.get('session_id', row['file'])}{detail}"
                     + (f" · {row['error']}" if row.get("error") else ""))
    lines.append(" · ".join(f"{key}: {report[key]}" for key in SYNC_COUNTS))
    lines.append("Dry run; nothing written." if report["dry_run"] else
                 f"Ingested {report['ingested']} parts; the engine worker or Steward drains the enqueued jobs.")
    return "\n".join(lines)


def ingest_sessions(args, library: dict, *, dry_run: bool) -> int:
    # Keep the manual converter entry, with exactly the same cursor and lock as the tray.
    report = sync_pass(library, [{"path": str(args.project), "since": args.since}],
                       dry_run=dry_run, rewritten=args.rewritten,
                       claude_root=args.claude_root, codex_root=args.codex_root,
                       options={key: getattr(args, key) for key in
                                ("min_owner_turns", "min_owner_chars", "ack_max_words", "purpose")},
                       owner_id=args.owner_id, session_ids=args.session_id)
    for row in report["sessions"]:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    print(json.dumps({"summary": {key: report[key] for key in SYNC_COUNTS}, "dry_run": dry_run}))
    return int(any(row["status"] == "error" for row in report["sessions"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for verb in ("list", "export", "ingest"):
        command = commands.add_parser(verb)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--since", help="include sessions with retained activity at/after this timezone-aware ISO timestamp")
        command.add_argument("--session-id", action="append", help="restrict to a listed session; repeat for several")
        command.add_argument("--claude-root", type=Path, default=Path.home() / ".claude/projects")
        command.add_argument("--codex-root", type=Path, default=Path.home() / ".codex/sessions")
        command.add_argument("--min-owner-turns", type=int, default=3)
        command.add_argument("--min-owner-chars", type=int, default=200,
                             help="skip sessions below this owner-text length; 0 disables the length filter")
        command.add_argument("--ack-max-words", type=int, default=1)
        command.add_argument("--purpose", choices=("project", "research", "chat"), default="project",
                             help="research/chat sessions are index-only")
        if verb in {"export", "ingest"}:
            command.add_argument("--owner-id", help="export default: owner; ingest default: selected library tenant")
        if verb == "export":
            command.add_argument("--out", type=Path, required=True)
        if verb == "ingest":
            command.add_argument("--library", help="otherwise use pkchome's existing selection")
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--rewritten", choices=("report", "reingest"), default="report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.min_owner_turns < 3 or args.min_owner_chars < 0 or args.ack_max_words < 1:
            raise ValueError("thresholds require min-owner-turns >= 3, min-owner-chars >= 0, ack-max-words >= 1")
        if args.command == "ingest":
            library = selected_library(args.library)
            return ingest_sessions(args, library, dry_run=args.dry_run)
        failed = False
        for session, verdict, error in scan(args):
            if error:
                report = {**verdict, "verdict": "error", "error": error}
                failed = True
            else:
                report = {"provider": session.provider, "session_id": session.session_id,
                          "file": str(session.path), **verdict}
                if args.command == "export" and verdict["verdict"] != "skip":
                    path, _ = export_session(session, verdict, args.owner_id or "owner", args.out.expanduser())
                    report["exported"] = str(path)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return int(failed)
    except subprocess.CalledProcessError as exc:
        print(f"pkchome refused library selection (exit {exc.returncode})", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
