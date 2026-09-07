"""Claude Code's stream-json wire, turned into the one event vocabulary (§5.6).

`claude --print --input-format stream-json --output-format stream-json
--include-partial-messages --verbose --permission-mode bypassPermissions` is a long-lived
process speaking NDJSON in both directions. What this module knows that nothing else has to:

* **stdout is chunked, not line-aligned.** A large `tool_use` payload lands mid-line, so the
  buffer keeps everything after the last newline and dispatches only whole lines.
* **`system.init` fires AFTER the first user prompt.** Nothing here waits for it; the session
  id arrives when it arrives and is reported as `session_started` then.
* **there is no turn id.** A user turn written while another is in flight would race it, so
  the SESSION queues instead (`steward_session.py`), and this adapter simply refuses to
  arm a second turn: `busy` is the whole of what it can offer.
* **an approval request should not arrive at all** under `bypassPermissions`. If one does it
  is declined — explicitly, in the protocol's own `control_response` shape — and surfaced, so
  the Owner sees a stopped step instead of a hang.

Pure: it holds a buffer and some turn state, and answers in `bytes` to write and events to
broadcast. No I/O, no asyncio — which is what lets the adapter tests replay a recorded wire.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .steward_events import (
    UNKNOWN_FRAME,
    Notice,
    PermissionRequest,
    SessionStarted,
    StepFinished,
    StepStarted,
    StewardEvent,
    TextDelta,
    TurnFinished,
    TurnStarted,
)

log = logging.getLogger(__name__)

#: How much of a tool result reaches the browser. The whole of it lives in the harness's own
#: transcript; a frame is a glance, not an archive.
PREVIEW_CHARS = 2000

#: The tools whose argument IS the step, in the shape a person reads it. Anything else is
#: rendered from its input as JSON, so a tool this framework has never heard of still shows
#: what it was asked to do.
_COMMAND_FIELDS: dict[str, tuple[str, ...]] = {
    "Bash": ("command",),
    "BashOutput": ("bash_id",),
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "Glob": ("pattern",),
    "Grep": ("pattern",),
}


def describe_tool_use(name: str, payload: Any) -> str:
    """What one `tool_use` block ran, as the agent itself stated it.

    The framework adds no words of its own: for `Bash` this is the command line the Steward
    typed, for `Read` the path it opened. A tool with no field this module knows renders its
    whole input as compact JSON — unfamiliar, but never invented.
    """
    if not isinstance(payload, dict):
        return str(payload or "")
    for field_name in _COMMAND_FIELDS.get(name, ()):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    if not payload:
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:PREVIEW_CHARS]
    except (TypeError, ValueError):
        return str(payload)[:PREVIEW_CHARS]


def _text_of(content: Any) -> str:
    """A `tool_result`'s content, whatever shape this version wraps it in."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return "" if content is None else str(content)


class ClaudeStreamAdapter:
    """One Claude Code session's wire. Feed it stdout; take events and frames to write."""

    #: Named on the manifest so a console can say which protocol it is watching.
    protocol = "stream-json"

    def __init__(self, **_: Any) -> None:
        # Claude needs neither the project nor the model here: the working directory and the
        # model ride the argv the manifest describes. The keywords are accepted and ignored
        # so that ONE call shape builds either adapter (`steward_session.start`).
        self._buffer = ""
        self._events: list[StewardEvent] = []
        self._writes: list[bytes] = []
        self._busy = False
        self._session_id = ""
        #: Text already delivered as a `stream_event` delta, so the consolidated `assistant`
        #: message that repeats it is not shown twice.
        self._streamed = ""
        #: tool_use id → what it ran, so the result can be folded under the right step.
        self._steps: dict[str, str] = {}

    # ── what the session asks of every adapter ───────────────────────────────────────────

    @property
    def busy(self) -> bool:
        """Is a turn in flight? Claude states no turn id, so this is the only guard there is."""
        return self._busy

    @property
    def agent_session_id(self) -> str:
        return self._session_id

    def start(self) -> None:
        """Claude needs no handshake: the process is ready when it is spawned."""

    def user_turn(self, text: str) -> None:
        """Write one user turn, as the one NDJSON line the CLI's streaming input accepts."""
        frame = {
            "type": "user",
            "message": {"role": "user", "content": text},
            "parent_tool_use_id": None,
        }
        if self._session_id:
            frame["session_id"] = self._session_id
        self._writes.append((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
        self._busy = True
        self._streamed = ""
        self._events.append(TurnStarted())

    def take_events(self) -> list[StewardEvent]:
        events, self._events = self._events, []
        return events

    def take_writes(self) -> list[bytes]:
        writes, self._writes = self._writes, []
        return writes

    def feed(self, data: str) -> None:
        """Absorb a chunk of stdout, dispatching only the lines that are whole."""
        self._buffer += data
        if "\n" not in self._buffer:
            return
        head, _, self._buffer = self._buffer.rpartition("\n")
        for line in head.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except ValueError:
                log.debug("claude wrote a line that is not JSON: %s", line[:200])
                continue
            if isinstance(frame, dict):
                self._frame(frame)

    def eof(self) -> None:
        """The process closed its stdout. Whatever is left in the buffer is a partial line."""
        self._buffer = ""

    # ── the protocol ─────────────────────────────────────────────────────────────────────

    def _frame(self, frame: dict[str, Any]) -> None:
        kind = str(frame.get("type") or "")
        if kind == "system":
            self._system(frame)
        elif kind == "assistant":
            self._assistant(frame)
        elif kind == "user":
            self._user_echo(frame)
        elif kind == "stream_event":
            self._stream_event(frame)
        elif kind == "result":
            self._result(frame)
        elif kind == "control_request":
            self._control_request(frame)
        elif kind in ("control_response", "control_cancel_request"):
            pass  # answers to our own writes; nothing to render
        else:
            self._events.append(Notice(code=UNKNOWN_FRAME, detail=kind or "?"))

    def _system(self, frame: dict[str, Any]) -> None:
        if str(frame.get("subtype") or "") != "init":
            return
        self._session_id = str(frame.get("session_id") or "")
        self._events.append(
            SessionStarted(
                agent_session_id=self._session_id, model=str(frame.get("model") or "")
            )
        )

    def _assistant(self, frame: dict[str, Any]) -> None:
        message = frame.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type") or "")
            if btype == "text":
                text = str(block.get("text") or "")
                # The consolidated message repeats what the deltas already delivered. Emit
                # only the tail, so a client that saw the stream is not shown it twice and a
                # client that saw no deltas still gets the whole thing.
                if self._streamed and text.startswith(self._streamed):
                    text = text[len(self._streamed) :]
                if text:
                    self._events.append(TextDelta(text=text))
                    self._streamed += text
            elif btype == "tool_use":
                step_id = str(block.get("id") or "")
                name = str(block.get("name") or "")
                command = describe_tool_use(name, block.get("input"))
                self._steps[step_id] = command
                self._events.append(
                    StepStarted(step_id=step_id, command=command, tool=name)
                )

    def _user_echo(self, frame: dict[str, Any]) -> None:
        """The CLI's own echo of a tool result — this is where a step finishes."""
        message = frame.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            step_id = str(block.get("tool_use_id") or "")
            text = _text_of(block.get("content"))
            failed = bool(block.get("is_error"))
            self._steps.pop(step_id, None)
            self._events.append(
                StepFinished(
                    step_id=step_id,
                    # Claude reports no exit code of its own: a tool either erred or did not.
                    exit_code=(1 if failed else 0),
                    output_preview=text[:PREVIEW_CHARS],
                    failed=failed,
                )
            )

    def _stream_event(self, frame: dict[str, Any]) -> None:
        event = frame.get("event")
        if not isinstance(event, dict):
            return
        delta = event.get("delta")
        if not isinstance(delta, dict):
            return
        if str(delta.get("type") or "") != "text_delta":
            return
        text = str(delta.get("text") or "")
        if text:
            self._streamed += text
            self._events.append(TextDelta(text=text))

    def _result(self, frame: dict[str, Any]) -> None:
        usage = frame.get("usage")
        counts = (
            {k: int(v) for k, v in usage.items() if isinstance(v, (int, float))}
            if isinstance(usage, dict)
            else None
        )
        cost = frame.get("total_cost_usd")
        self._busy = False
        self._streamed = ""
        self._events.append(
            TurnFinished(
                # Absent stays absent: a turn whose harness reported nothing reports nothing,
                # never a zero.
                usage=counts or None,
                cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
                duration_ms=int(frame.get("duration_ms") or 0),
                error=(
                    str(frame.get("subtype") or "error")
                    if frame.get("is_error")
                    else ""
                ),
            )
        )

    def _control_request(self, frame: dict[str, Any]) -> None:
        """An approval prompt under a policy that should not produce one — declined.

        Not ignored. A request left unanswered is a harness waiting forever, and a session
        that hangs tells the Owner nothing; a decline plus this event tells them exactly why
        the Steward stopped.
        """
        request_id = str(frame.get("request_id") or "")
        request = frame.get("request") if isinstance(frame.get("request"), dict) else {}
        subtype = str((request or {}).get("subtype") or "")
        self._writes.append(
            (
                json.dumps(
                    {
                        "type": "control_response",
                        "response": {
                            "subtype": subtype or "can_use_tool",
                            "request_id": request_id,
                            "behavior": "deny",
                            "message": (
                                "this session runs unattended in the console; nobody here "
                                "can answer a permission prompt"
                            ),
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
        )
        self._events.append(
            PermissionRequest(
                request_id=request_id,
                method=subtype or "control_request",
                detail=json.dumps(request or {}, ensure_ascii=False)[:PREVIEW_CHARS],
            )
        )


__all__ = ["PREVIEW_CHARS", "ClaudeStreamAdapter", "describe_tool_use"]
