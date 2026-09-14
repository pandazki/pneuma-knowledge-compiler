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
* **the sandbox grants network access, and says so twice in two spellings.** A
  workspace-write sandbox is network-RESTRICTED by default, and the Steward's one hand is
  `pkc`, which opens Postgres, Qdrant and Meilisearch — so a thread without network access
  answers every question with a sandbox error. `thread/start` takes only the `SandboxMode`
  ENUM (`"workspace-write"`), so network access reaches it through the `config` override map
  the same way `-c` reaches the CLI; `turn/start` takes the whole `SandboxPolicy` OBJECT and
  states `networkAccess` in it. Both spellings are derived from `NETWORK_ACCESS` here, so
  there is one place to be wrong in.
* **the same prose arrives twice.** Codex 0.154 streams `item/agentMessage/delta` AND then
  sends `item/completed` carrying the whole message text. The completed item is authoritative
  only for an item id no delta ever arrived for; where deltas did arrive, only the tail the
  deltas did not cover is emitted. Tracking "any delta ever seen" cannot work — the session
  drains events after every read, so by the time the completed item lands the deltas are
  gone from this adapter's buffer and every answer renders twice.
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
from typing import Any, Sequence

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

#: The sandbox a Steward session runs under, and the one place the two spellings come from.
#: Verified against `codex app-server generate-json-schema` (Codex 0.154): `ThreadStartParams.
#: sandbox` is the `SandboxMode` enum and carries no network field, while `TurnStartParams.
#: sandboxPolicy` is a `SandboxPolicy` whose `workspaceWrite` variant has `networkAccess`.
#: A live `thread/start` echoes the resulting policy back in its response, which is how the
#: config spelling below was checked rather than guessed.
SANDBOX_MODE = "workspace-write"

#: Whether the sandbox may open a socket. True because `pkc` — the Steward's one hand —
#: reaches Postgres, Qdrant and Meilisearch, and a sandbox that refused those would refuse
#: the whole conversation rather than protect anything.
NETWORK_ACCESS = True


def sandbox_config() -> dict[str, Any]:
    """Network access as `thread/start` accepts it: a config override, exactly as `-c
    sandbox_workspace_write.network_access=true` reaches the CLI."""
    return {"sandbox_workspace_write": {"network_access": NETWORK_ACCESS}}


def sandbox_policy() -> dict[str, Any]:
    """Network access as `turn/start` accepts it: inside the sandbox policy object."""
    return {"type": "workspaceWrite", "networkAccess": NETWORK_ACCESS}


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

    #: Codex takes images on a turn as `localImage` input items naming a path on disk.
    accepts_images = True

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
        #: Turns the console sent before the thread existed — text and its image paths.
        #: Held, never dropped.
        self._held: list[tuple[str, tuple[Any, ...]]] = []
        #: The last `thread/tokenUsage/updated` snapshot: this turn's window and the session's.
        self._last_usage: dict[str, int] | None = None
        self._total_usage: dict[str, int] | None = None
        #: item id → what it ran, so a completion can be folded under the right step.
        self._steps: dict[str, str] = {}
        #: message item id → the prose its deltas already delivered. The completed item's
        #: text is authoritative only for an id absent from here; for one present, only the
        #: tail the deltas did not cover is emitted. Per id, because this adapter's event
        #: buffer is drained after every read and cannot remember "a delta arrived once".
        self._streamed: dict[str, str] = {}
        #: The last `agentMessage` item that started, for a version whose deltas name no id.
        self._message_id = ""

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
            # and the indexes, which is why network access is on. `thread/start` has no
            # sandbox POLICY, only the mode enum, so network access rides the config
            # override the CLI's `-c` writes.
            "approvalPolicy": "never",
            "sandbox": SANDBOX_MODE,
            "config": sandbox_config(),
        }
        if self._model:
            params["model"] = self._model
        self._start_id = self._request("thread/start", params)

    def user_turn(self, text: str, images: Sequence[Any] = ()) -> None:
        """Start a turn, or hold it until the thread this session needs exists.

        `images` are the session's decoded attachments, already written into the scratch
        directory it owns; this adapter only names the paths they landed on.
        """
        held = tuple(images)
        if not self._thread_id:
            self._held.append((text, held))
            return
        self._start_turn(text, held)

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

    def _start_turn(self, text: str, images: Sequence[Any] = ()) -> None:
        # Images first, then the text — the order the CLI itself sends a pasted screenshot in.
        # `localImage` names a path the app-server reads; the bytes never ride the wire.
        payload: list[dict[str, Any]] = [
            {"type": "localImage", "path": str(image.path)} for image in images
        ]
        if text:
            payload.append({"type": "text", "text": text})
        params: dict[str, Any] = {
            "threadId": self._thread_id,
            "input": payload,
            "cwd": self._cwd,
            "approvalPolicy": "never",
            # camelCase per turn, kebab-case at boot — the app-server's own asymmetry. This
            # is the only request that takes the whole policy, so it is the only one that can
            # state `networkAccess` directly.
            "sandboxPolicy": sandbox_policy(),
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
            for text, images in held:
                self._start_turn(text, images)
            return
        if isinstance(frame.get("error"), dict) and not self._thread_id:
            detail = str(frame["error"].get("message") or "")
            self._events.append(Notice(code="rpc_error", detail=detail[:PREVIEW_CHARS]))

    def _notification(self, method: str, params: Any) -> None:
        params = params if isinstance(params, dict) else {}
        if method == "item/agentMessage/delta":
            self._message_delta(params)
        elif method == "item/started":
            self._item_started(params.get("item"))
        elif method in ("item/completed", "item/updated"):
            # 0.154 has no `item/updated`; a version that grows one carries the same item, so
            # it goes through the same rule rather than through a second one.
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

    def _message_delta(self, params: dict[str, Any]) -> None:
        """One fragment of the Steward's prose, remembered under the item it belongs to."""
        text = str(params.get("delta") or "")
        if not text:
            return
        item_id = str(params.get("itemId") or self._message_id or "")
        self._streamed[item_id] = self._streamed.get(item_id, "") + text
        self._events.append(TextDelta(text=text))

    def _item_started(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        itype = str(item.get("type") or "")
        if itype == "agentMessage":
            # Named here so a version whose deltas carry no `itemId` still has an id to
            # attribute them to.
            self._message_id = str(item.get("id") or "")
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
                self._message_completed(step_id, str(item.get("text") or ""))
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

    def _message_completed(self, item_id: str, text: str) -> None:
        """The completed message: authoritative only where its deltas were not.

        Codex 0.154 sends BOTH — every delta, then the whole text again on `item/completed`.
        So what is emitted here is the DIFFERENCE: nothing when the deltas already delivered
        this text, the tail when the completed item runs past them, and the whole of it only
        when no delta for this item id ever arrived (an older version, or a message that was
        never streamed). It cannot be decided by looking at the events already produced —
        they are drained after every read — so it is decided per item id.
        """
        seen = self._streamed.pop(item_id, "")
        if not seen:
            # A version whose deltas name no id at all, before any item started, banked them
            # under the empty key. Only that key is a fallback: reaching for another item's
            # deltas would let one message swallow the next one's.
            seen = self._streamed.pop("", "")
        if seen:
            text = text[len(seen) :] if text.startswith(seen) else ""
        if text:
            self._events.append(TextDelta(text=text))

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
        # A message whose completion never arrived would otherwise hold its prose forever.
        self._streamed.clear()
        self._message_id = ""
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


__all__ = [
    "NETWORK_ACCESS",
    "PREVIEW_CHARS",
    "SANDBOX_MODE",
    "CodexJsonRpcAdapter",
    "describe_item",
    "sandbox_config",
    "sandbox_policy",
]
