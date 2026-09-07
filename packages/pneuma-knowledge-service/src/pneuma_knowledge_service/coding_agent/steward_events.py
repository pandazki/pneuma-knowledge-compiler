"""One event vocabulary for two harnesses (§5.6).

Claude Code speaks NDJSON envelopes over stdio; Codex speaks JSON-RPC. Neither shape reaches
the browser: the console renders a conversation, and a conversation has turns, text, steps,
and an end that says what the turn cost. Everything a protocol says that does not answer one
of those questions is dropped in the adapter, and everything that does answer one arrives
here in the same shape whichever harness produced it.

Nine events, frozen and JSON-serializable. The wire-level differences the two protocols do
NOT share — Claude announcing its session only after the first prompt, Codex synthesising no
turn end and reporting cumulative as well as last-request tokens, an approval request in
seven flavours — live in the adapters and stop there.

`kind` is the JSON discriminator and it is the class's own name in snake_case, stated once in
`payload()` so the wire form and the dataclass cannot drift apart.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StewardEvent:
    """The base every event shares. `kind` names the frame on the wire."""

    kind: str = field(init=False, default="")

    def payload(self) -> dict[str, Any]:
        """The JSON frame: every field of this event, under its `kind`."""
        body = {k: v for k, v in asdict(self).items() if k != "kind"}
        return {"type": self.kind, **body}


@dataclass(frozen=True)
class SessionStarted(StewardEvent):
    """The harness named the session it is running — Claude's `system.init`, Codex's
    `thread/start` response. It arrives AFTER the first user turn on Claude, which is why
    nothing in the session waits for it."""

    kind: str = field(init=False, default="session_started")
    agent_session_id: str = ""
    model: str = ""


@dataclass(frozen=True)
class TurnStarted(StewardEvent):
    """A user turn was handed to the harness and is now in flight."""

    kind: str = field(init=False, default="turn_started")
    turn_id: str = ""


@dataclass(frozen=True)
class TextDelta(StewardEvent):
    """A fragment of the Steward's own prose, in the order it was written."""

    kind: str = field(init=False, default="text_delta")
    text: str = ""


@dataclass(frozen=True)
class StepStarted(StewardEvent):
    """The Steward ran something. `command` is the agent's OWN words — the Bash command it
    typed, the path it read — never a rendering this framework invented for it."""

    kind: str = field(init=False, default="step_started")
    step_id: str = ""
    command: str = ""
    tool: str = ""


@dataclass(frozen=True)
class StepFinished(StewardEvent):
    """That step's result. `exit_code` is None where the harness reports none (a `Read` has
    no exit code); `output_preview` is bounded, because a step's whole output belongs to the
    harness's own transcript and not to a browser frame."""

    kind: str = field(init=False, default="step_finished")
    step_id: str = ""
    exit_code: int | None = None
    output_preview: str = ""
    duration_ms: int = 0
    failed: bool = False


@dataclass(frozen=True)
class PermissionRequest(StewardEvent):
    """The harness asked for permission — which, under the bypass/never policies these
    sessions launch with, should never happen. When it does it is DECLINED and surfaced, so
    the Owner sees why the Steward stopped instead of watching it hang."""

    kind: str = field(init=False, default="permission_request")
    request_id: str = ""
    method: str = ""
    detail: str = ""
    declined: bool = True


@dataclass(frozen=True)
class TurnFinished(StewardEvent):
    """The turn ended. `usage` is the harness's own counters for THIS turn and is None when
    it reported none — never a zero, which would be a claim that the turn was free."""

    kind: str = field(init=False, default="turn_finished")
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    duration_ms: int = 0
    error: str = ""


@dataclass(frozen=True)
class SessionExited(StewardEvent):
    """The harness process is gone. Never followed by a silent restart (§5.6)."""

    kind: str = field(init=False, default="session_exited")
    exit_code: int = 0
    detail: str = ""


@dataclass(frozen=True)
class Notice(StewardEvent):
    """Something the BRIDGE has to say in its own name: a message queued behind a turn in
    flight, a protocol frame nothing here knows. Kept apart from `text_delta` because the
    Steward did not say it."""

    kind: str = field(init=False, default="notice")
    code: str = ""
    detail: str = ""


#: What the console is told when a message arrives while a turn is still running. Claude's
#: streaming input carries no turn id, so a second turn written mid-flight would race the
#: first; the bridge holds it and says so, rather than interrupting and resending (the
#: invariant `steer-in.md` names: a protocol race fails explicitly).
QUEUED = "queued"
#: A frame the adapter did not recognise. Logged, surfaced, never fatal.
UNKNOWN_FRAME = "unknown_frame"


__all__ = [
    "Notice",
    "PermissionRequest",
    "QUEUED",
    "SessionExited",
    "SessionStarted",
    "StepFinished",
    "StepStarted",
    "StewardEvent",
    "TextDelta",
    "TurnFinished",
    "TurnStarted",
    "UNKNOWN_FRAME",
]
