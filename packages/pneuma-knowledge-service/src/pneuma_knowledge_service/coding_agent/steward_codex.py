"""Codex's app-server JSON-RPC wire, turned into the one event vocabulary (§5.6).

`codex app-server` is not a stream of envelopes but a request/response + notification
protocol: one `\\n`-delimited JSON object per frame, `method`/`params` going out, `id`/`result`
coming back. What this module knows that nothing else has to:

* **there is a handshake.** `initialize` → `initialized` → `thread/start`, and only then may a
  turn be started. A user turn that arrives before the thread exists is HELD, not dropped —
  the console's first message routinely beats the handshake.
* **there is no native turn end.** `turn/completed` is the last thing a turn says, and the
  turn's cost is whatever the last `thread/tokenUsage/updated` reported. This adapter
  synthesises the `turn_finished` the vocabulary has, exactly as the reference bridge does.
* **`last` is the turn, `total` is the session.** `total` is cumulative — it re-counts the
  whole prompt on every request and climbs into the millions over a long thread. A turn's
  usage is `last`; `total` is reported beside it and never in its place.
* **an approval request has seven shapes and two answer vocabularies** (`accept`/`decline`
  and `approved`/`denied`). Under `approvalPolicy: never` none of them should arrive; if one
  does it is DECLINED in the shape its method asks for, and surfaced. And an unknown REQUEST
  — anything with an id this adapter does not recognise — is declined too, never ignored:
  ignoring it hangs the harness, and approving it would approve a future version's operation
  nobody here has seen. Unknown NOTIFICATIONS are dropped, because nothing is waiting.

Pure, like the Claude adapter: buffers, turn state, frames to write and events to broadcast.
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

PREVIEW_CHARS = 2000

#: The approval methods that answer `approved`/`denied` rather than `accept`/`decline`.
#: Flipping this mapping silently rejects every approval, so it is stated rather than guessed.
_APPROVED_DENIED: frozenset[str] = frozenset(
    {"applyPatchApproval", "execCommandApproval"}
)

#: Requests the CLI makes of its client that are not approvals and are answered with an empty
#: object — the auth refresh in particular, which fails loudly for the Owner if it is declined.
_ACKNOWLEDGED: frozenset[str] = frozenset({"account/chatgptAuthTokens/refresh"})

#: The item types that are STEPS — something the Steward ran, with a result to fold under it.
#: An item type absent from this set produces no step, and the reasoning/message items below
#: are read as text instead.
_STEP_ITEMS: frozenset[str] = frozenset(
    {"commandExecution", "fileChange", "mcpToolCall", "webSearch"}
)


def describe_item(item: dict[str, Any]) -> str:
    """What one item ran, in the agent's own words.

    A `commandExecution` states its command — a list of argv parts on some versions, one
    string on others. Anything else states whatever field names it.
    """
    command = item.get("command")
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    if isinstance(command, str) and command.strip():
        return command
    for key in ("path", "query", "tool", "name", "server"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return str(item.get("type") or "")


def _counts(usage: Any) -> dict[str, int] | None:
    """One token-usage scope as flat integers, or None when nothing measured it."""
    if not isinstance(usage, dict):
        return None
    out = {k: int(v) for k, v in usage.items() if isinstance(v, (int, float))}
    return out or None


class CodexJsonRpcAdapter:
    """One `codex app-server` session's wire."""

    protocol = "jsonrpc"

    def __init__(self, *, project_dir: str = "", model: str = "", **_: Any) -> None:
        self._cwd = project_dir
        self._model = model
        self._buffer = ""
        self._events: list[StewardEvent] = []
        self._writes: list[bytes] = []
        self._next_id = 1
        self._thread_id = ""
        self._turn_id = ""
        self._busy = False
        #: The id of the `thread/start` request, so its response is recognisable.
        self._start_id = 0
        #: Turns the console sent before the thread existed. Held, never dropped.
        self._held: list[str] = []
        #: The last `thread/tokenUsage/updated` snapshot: this turn's window and the session's.
        self._last_usage: dict[str, int] | None = None
        self._total_usage: dict[str, int] | None = None
        #: item id → what it ran, so a completion can be folded under the right step.
        self._steps: dict[str, str] = {}

    # ── what the session asks of every adapter ───────────────────────────────────────────

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def agent_session_id(self) -> str:
        return self._thread_id

    def start(self) -> None:
        """The handshake, written the moment the process is up."""
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "pneuma-knowledge-compiler",
                    "title": "Pneuma Knowledge Compiler",
                    "version": "1",
                },
                "capabilities": {},
            },
        )
        self._notify("initialized", {})
        params: dict[str, Any] = {
            "cwd": self._cwd,
            # Nobody is at this terminal, so nothing can answer an approval: the policy says
            # so rather than leaving a prompt to hang on. The sandbox is `workspace-write`
            # over the PROJECT — the Steward's one hand is `pkc`, and `pkc` reaches Postgres
            # and the indexes, which is why network access is on.
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
        }
        if self._model:
            params["model"] = self._model
        self._start_id = self._request("thread/start", params)

    def user_turn(self, text: str) -> None:
        """Start a turn, or hold the text until the thread this session needs exists."""
        if not self._thread_id:
            self._held.append(text)
            return
        self._start_turn(text)

    def take_events(self) -> list[StewardEvent]:
        events, self._events = self._events, []
        return events

    def take_writes(self) -> list[bytes]:
        writes, self._writes = self._writes, []
        return writes

    def feed(self, data: str) -> None:
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
                log.debug("codex wrote a line that is not JSON: %s", line[:200])
                continue
            if isinstance(frame, dict):
                self._frame(frame)

    def eof(self) -> None:
        self._buffer = ""

    # ── writing ──────────────────────────────────────────────────────────────────────────

    def _write(self, frame: dict[str, Any]) -> None:
        self._writes.append((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))

    def _request(self, method: str, params: dict[str, Any]) -> int:
        request_id = self._next_id
        self._next_id += 1
        self._write({"method": method, "id": request_id, "params": params})
        return request_id

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    def _respond(self, request_id: Any, result: dict[str, Any]) -> None:
        self._write({"id": request_id, "result": result})

    def _start_turn(self, text: str) -> None:
        params: dict[str, Any] = {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": text}],
            "cwd": self._cwd,
            "approvalPolicy": "never",
            # camelCase per turn, kebab-case at boot — the app-server's own asymmetry.
            "sandboxPolicy": {"type": "workspaceWrite"},
        }
        if self._model:
            params["model"] = self._model
        self._request("turn/start", params)
        self._busy = True
        self._events.append(TurnStarted(turn_id=self._turn_id))

    # ── the protocol ─────────────────────────────────────────────────────────────────────

    def _frame(self, frame: dict[str, Any]) -> None:
        if "method" in frame and "id" in frame:
            self._server_request(frame)
        elif "method" in frame:
            self._notification(str(frame.get("method") or ""), frame.get("params") or {})
        elif "id" in frame:
            self._response(frame)

    def _response(self, frame: dict[str, Any]) -> None:
        result = frame.get("result")
        if frame.get("id") == self._start_id and isinstance(result, dict):
            thread = result.get("thread")
            self._thread_id = str(
                (thread or {}).get("id") if isinstance(thread, dict) else result.get("threadId") or ""
            )
            self._events.append(
                SessionStarted(
                    agent_session_id=self._thread_id,
                    model=str(result.get("model") or self._model),
                )
            )
            held, self._held = self._held, []
            for text in held:
                self._start_turn(text)
            return
        if isinstance(frame.get("error"), dict) and not self._thread_id:
            detail = str(frame["error"].get("message") or "")
            self._events.append(Notice(code="rpc_error", detail=detail[:PREVIEW_CHARS]))

    def _notification(self, method: str, params: Any) -> None:
        params = params if isinstance(params, dict) else {}
        if method == "item/agentMessage/delta":
            text = str(params.get("delta") or "")
            if text:
                self._events.append(TextDelta(text=text))
        elif method == "item/started":
            self._item_started(params.get("item"))
        elif method in ("item/completed", "item/updated"):
            if method == "item/completed":
                self._item_completed(params.get("item"))
        elif method == "thread/tokenUsage/updated":
            self._token_usage(params)
        elif method == "turn/started":
            turn = params.get("turn")
            self._turn_id = str((turn or {}).get("id") or "") if isinstance(turn, dict) else ""
        elif method == "turn/completed":
            self._turn_completed(params)
        elif method == "turn/failed":
            self._turn_completed(params, error=str(params.get("error") or "turn failed"))
        # Everything else is upstream surface nothing here consumes. Dropped rather than
        # surfaced: a notification has nobody waiting on it, so silence costs nothing.

    def _item_started(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        itype = str(item.get("type") or "")
        if itype not in _STEP_ITEMS:
            return
        step_id = str(item.get("id") or "")
        command = describe_item(item)
        self._steps[step_id] = command
        self._events.append(StepStarted(step_id=step_id, command=command, tool=itype))

    def _item_completed(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        itype = str(item.get("type") or "")
        step_id = str(item.get("id") or "")
        if itype not in _STEP_ITEMS:
            if itype == "agentMessage":
                # Some versions deliver the message only here, with no deltas at all.
                text = str(item.get("text") or "")
                if text and not any(isinstance(e, TextDelta) for e in self._events):
                    self._events.append(TextDelta(text=text))
            return
        exit_code = item.get("exitCode")
        output = item.get("aggregatedOutput") or item.get("output") or ""
        status = str(item.get("status") or "")
        self._steps.pop(step_id, None)
        self._events.append(
            StepFinished(
                step_id=step_id,
                exit_code=int(exit_code) if isinstance(exit_code, (int, float)) else None,
                output_preview=str(output)[:PREVIEW_CHARS],
                duration_ms=int(item.get("durationMs") or 0),
                failed=status == "failed" or bool(exit_code),
            )
        )

    def _token_usage(self, params: dict[str, Any]) -> None:
        """`tokenUsage.last` is this turn; `tokenUsage.total` is the session (0.114+ nesting,
        with the flat legacy shape accepted beside it)."""
        usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else params
        self._last_usage = _counts(usage.get("last")) or self._last_usage
        self._total_usage = _counts(usage.get("total")) or self._total_usage

    def _turn_completed(self, params: dict[str, Any], *, error: str = "") -> None:
        """The turn end this protocol does not have, synthesised where the reference bridge
        synthesises it."""
        self._busy = False
        self._turn_id = ""
        usage = _counts(params.get("usage")) or self._last_usage
        self._events.append(
            TurnFinished(
                usage=dict(usage) if usage else None,
                cost_usd=None,  # the app-server never pushes one; a 0.0 would be a claim
                error=error,
            )
        )

    def _server_request(self, frame: dict[str, Any]) -> None:
        """A JSON-RPC REQUEST from the harness — something is waiting for an answer."""
        method = str(frame.get("method") or "")
        request_id = frame.get("id")
        params = frame.get("params") if isinstance(frame.get("params"), dict) else {}
        if method in _ACKNOWLEDGED:
            self._respond(request_id, {})
            return
        decision = "denied" if method in _APPROVED_DENIED else "decline"
        self._respond(request_id, {"decision": decision})
        detail = json.dumps(params, ensure_ascii=False)[:PREVIEW_CHARS]
        if method.endswith("requestApproval") or method in _APPROVED_DENIED or "Approval" in method:
            self._events.append(
                PermissionRequest(request_id=str(request_id), method=method, detail=detail)
            )
        else:
            # A request shape this version has never seen. Declined for the same reason an
            # approval is, and surfaced as the framework's own notice rather than as the
            # Steward's word.
            self._events.append(
                PermissionRequest(
                    request_id=str(request_id),
                    method=method,
                    detail=detail,
                )
            )
            self._events.append(Notice(code=UNKNOWN_FRAME, detail=method))


__all__ = ["PREVIEW_CHARS", "CodexJsonRpcAdapter", "describe_item"]
