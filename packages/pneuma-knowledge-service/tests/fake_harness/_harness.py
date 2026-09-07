"""A coding-agent harness that is not one — the `scripted:` idea, one process out.

The unattended launcher's whole job is what happens AROUND a harness: the argv it builds,
the file the prompt travels in, the wall clock, the reaping, the backoff, and reading the
harness's own report of what it spent. None of that needs a subscription to test — it needs
a program on `PATH` called `codex` or `claude` that accepts our flags, reads stdin, and
prints the right shape. This is that program.

It is driven entirely by environment variables, so one executable covers every case a test
needs:

    PKC_FAKE_LOG          append one JSON line per invocation: argv, cwd, env, stdin
    PKC_FAKE_MODE         ok (default) · rate-limit · hang · fail · silent
    PKC_FAKE_LIVE_AFTER   under `rate-limit`, the attempt number that finally succeeds
    PKC_FAKE_COUNTER      a file the attempt number is counted in (shared across processes)
    PKC_FAKE_SCRIPT       a JSON list of argv lists to RUN — the `pkc draft …` sequence a
                          real harness would type. Each is run in turn; a non-zero exit stops
                          the sequence, exactly as a Steward reading an exit code would stop.
    PKC_FAKE_EXIT         the exit code to end with (default 0, or 1 under `fail`)

`silent` prints no usage at all: the case where a harness's protocol surface is not one this
version knows, which must degrade to "usage unknown" rather than to a zero.

**Two postures, one executable.** The round above is the unattended one. The same program
also speaks the INTERACTIVE wire the console's Steward bridge reads — Claude Code's
stream-json NDJSON in both directions, Codex's `app-server` JSON-RPC — and which one it is
running is read off the ARGV the bridge itself built, exactly as the real binaries do:
`codex app-server`, or a `claude` invoked with `--input-format`. Two more variables steer it:

    PKC_FAKE_COMMAND      the command the fake's one step reports having run
    PKC_FAKE_APPROVAL     ask for approval before the step, to exercise the decline path
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: The token counts the fakes report, chosen to be recognizable in an assertion.
CLAUDE_USAGE = {
    "input_tokens": 1200,
    "output_tokens": 300,
    "cache_read_input_tokens": 100,
}
CLAUDE_COST_USD = 0.0421
CLAUDE_SESSION = "sess-fake-claude"

#: What `codex exec --json` really prints on `turn.completed`: `cached_input_tokens` is the
#: cached PORTION of `input_tokens`, not a number beside it.
CODEX_USAGE = {
    "input_tokens": 900,
    "cached_input_tokens": 100,
    "cache_write_input_tokens": 0,
    "output_tokens": 250,
    "reasoning_output_tokens": 0,
}
CODEX_THREAD = "th-fake-codex"

RATE_LIMIT_MESSAGE = "stream error: 429 Too Many Requests (rate limit reached); retry later"


def _attempt() -> int:
    """Which invocation of this fake we are, counted in a file the launcher cannot see."""
    counter = os.environ.get("PKC_FAKE_COUNTER", "")
    if not counter:
        return 1
    path = Path(counter)
    n = int(path.read_text().strip() or "0") if path.is_file() else 0
    path.write_text(str(n + 1))
    return n + 1


def _log(argv: list[str], stdin_text: str) -> None:
    target = os.environ.get("PKC_FAKE_LOG", "")
    if not target:
        return
    record = {
        "argv": argv,
        "cwd": os.getcwd(),
        "stdin": stdin_text,
        "env": {
            key: os.environ.get(key, "")
            for key in (
                "CODEX_HOME",
                "CLAUDE_CONFIG_DIR",
                "CLAUDECODE",
                "PNEUMA_KNOWLEDGE_EXECUTOR_BACKEND",
                "PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH",
            )
            if key in os.environ
        },
        "workdir_entries": sorted(p.name for p in Path.cwd().iterdir()),
    }
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _output_file(argv: list[str]) -> Path | None:
    for flag in ("--output-last-message", "-o"):
        if flag in argv:
            return Path(argv[argv.index(flag) + 1])
    return None


def _run_script() -> int:
    """Replay the `pkc draft …` sequence a real Steward would type. 0 when all of them did."""
    script = os.environ.get("PKC_FAKE_SCRIPT", "")
    if not script:
        return 0
    for command in json.loads(Path(script).read_text(encoding="utf-8")):
        completed = subprocess.run([str(part) for part in command])
        if completed.returncode != 0:
            print(
                f"fake harness: `{' '.join(str(p) for p in command)}` exited "
                f"{completed.returncode}; stopping the sequence",
                file=sys.stderr,
            )
            return completed.returncode
    return 0


#: What the interactive fakes report their one step as having run. A `pkc` command by
#: default, because that is what a Steward's step IS.
def _step_command() -> str:
    return os.environ.get("PKC_FAKE_COMMAND", "pkc jobs --limit 5")


def _emit(frame: dict) -> None:
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()


def _interactive_claude() -> int:
    """Claude Code's stream-json wire: NDJSON in, NDJSON out, one process for many turns.

    `system.init` is written only AFTER the first user prompt, which is what the real CLI
    does and what the bridge must not wait for.
    """
    started = False
    turn = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        if frame.get("type") != "user":
            continue  # a control_response; nothing to answer
        turn += 1
        if not started:
            started = True
            _emit(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": CLAUDE_SESSION,
                    "model": "claude-fake",
                    "tools": ["Bash", "Read"],
                    "permissionMode": "bypassPermissions",
                }
            )
        if os.environ.get("PKC_FAKE_APPROVAL"):
            _emit(
                {
                    "type": "control_request",
                    "request_id": f"req-{turn}",
                    "request": {"subtype": "can_use_tool", "tool_name": "Bash"},
                }
            )
        tool_id = f"toolu-{turn}"
        _emit(
            {
                "type": "stream_event",
                "event": {"delta": {"type": "text_delta", "text": "looking"}},
            }
        )
        _emit(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "looking now"},
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": "Bash",
                            "input": {"command": _step_command()},
                        },
                    ],
                },
            }
        )
        _emit(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": "2 jobs",
                        }
                    ],
                },
            }
        )
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": CLAUDE_SESSION,
            "duration_ms": 12,
            "result": "done",
        }
        if os.environ.get("PKC_FAKE_MODE", "ok") != "silent":
            payload["usage"] = dict(CLAUDE_USAGE)
            payload["total_cost_usd"] = CLAUDE_COST_USD
        _emit(payload)
    return 0


def _interactive_codex() -> int:
    """`codex app-server`: JSON-RPC over stdio, and no native turn end.

    Reports BOTH token scopes on `thread/tokenUsage/updated` — `total` cumulative and `last`
    for this request — because telling them apart is the adapter's job and this is where it
    is given something to tell apart.
    """
    turns = 0
    total = {"inputTokens": 0, "outputTokens": 0}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        method = frame.get("method")
        request_id = frame.get("id")
        if method == "initialize":
            _emit({"id": request_id, "result": {"userAgent": "codex-fake"}})
        elif method == "thread/start":
            _emit(
                {
                    "id": request_id,
                    "result": {"thread": {"id": CODEX_THREAD}, "model": "gpt-fake"},
                }
            )
        elif method == "turn/start":
            turns += 1
            item = f"itm-{turns}"
            _emit({"method": "turn/started", "params": {"turn": {"id": f"trn-{turns}"}}})
            if os.environ.get("PKC_FAKE_APPROVAL"):
                _emit(
                    {
                        "method": "item/commandExecution/requestApproval",
                        "id": 900 + turns,
                        "params": {"itemId": item, "command": _step_command()},
                    }
                )
            _emit(
                {
                    "method": "item/started",
                    "params": {
                        "item": {
                            "type": "commandExecution",
                            "id": item,
                            "command": [_step_command()],
                        }
                    },
                }
            )
            _emit(
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "commandExecution",
                            "id": item,
                            "exitCode": 0,
                            "status": "completed",
                            "aggregatedOutput": "2 jobs",
                            "durationMs": 7,
                        }
                    },
                }
            )
            _emit({"method": "item/agentMessage/delta", "params": {"delta": "two jobs"}})
            last = {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150}
            total = {
                "inputTokens": total["inputTokens"] + last["inputTokens"],
                "outputTokens": total["outputTokens"] + last["outputTokens"],
            }
            _emit(
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "tokenUsage": {
                            "total": dict(total),
                            "last": dict(last),
                            "modelContextWindow": 258400,
                        }
                    },
                }
            )
            _emit({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
            _emit({"id": request_id, "result": {}})
        elif request_id is not None and method:
            _emit({"id": request_id, "result": {}})
    return 0


def _is_interactive(family: str, argv: list[str]) -> bool:
    """Which posture this invocation is, read off the argv the caller built."""
    if family == "codex":
        return "app-server" in argv
    return "--input-format" in argv


def main(family: str) -> int:
    argv = sys.argv[1:]
    mode = os.environ.get("PKC_FAKE_MODE", "ok")

    # The interactive posture reads stdin a LINE at a time for the life of the process, so
    # the round's `read()` of the whole of it must not happen first.
    if _is_interactive(family, argv):
        _log(argv, "")
        if mode == "fail":
            # A harness that dies on its own. The bridge must report it, never restart it.
            print("fake harness: refusing to start", file=sys.stderr)
            return int(os.environ.get("PKC_FAKE_EXIT", "1"))
        if mode == "hang":
            while True:
                time.sleep(3600)
        return _interactive_claude() if family == "claude" else _interactive_codex()

    stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
    _log(argv, stdin_text)
    attempt = _attempt()

    if mode == "hang":
        # Never answers. The launcher's wall clock is the only thing that ends this.
        while True:
            time.sleep(3600)

    live_after = int(os.environ.get("PKC_FAKE_LIVE_AFTER") or 10**9)
    if mode == "rate-limit" and attempt < live_after:
        print(RATE_LIMIT_MESSAGE, file=sys.stderr)
        return 1

    script_code = _run_script()

    if family == "claude":
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": CLAUDE_SESSION,
            "result": "the round is done",
        }
        if mode != "silent":
            payload["usage"] = dict(CLAUDE_USAGE)
            payload["total_cost_usd"] = CLAUDE_COST_USD
        print(json.dumps(payload))
    else:
        events = [
            {"type": "thread.started", "thread_id": CODEX_THREAD},
            {"type": "turn.started"},
            {
                "type": "turn.completed",
                **({} if mode == "silent" else {"usage": dict(CODEX_USAGE)}),
            },
        ]
        for event in events:
            print(json.dumps(event))
        target = _output_file(argv)
        if target is not None:
            target.write_text("the round is done", encoding="utf-8")

    if mode == "fail":
        return int(os.environ.get("PKC_FAKE_EXIT", "1"))
    return script_code or int(os.environ.get("PKC_FAKE_EXIT", "0"))
