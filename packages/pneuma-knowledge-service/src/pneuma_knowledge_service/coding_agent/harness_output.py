"""Reading a harness's own report of what one round cost, and which session ran it.

The unattended posture is the one place where an agent-executed compile CAN say what it
spent: the harness prints a structured result, and the launcher captured it. So the rule
step 2 wrote for the interactive posture — usage is absent rather than zero, because the
Owner's subscription is not this process's to count — narrows to exactly what it was always
about: **absent when nothing measured it**, not "absent because an agent ran it". A parse
that finds nothing returns `None` here too, for the same reason.

The two readers are data on the manifest (`backends.py`), not a branch anywhere: a third
harness ships a third reader in its own row. Both are deliberately tolerant — an unknown
protocol surface degrades to "no usage" and is logged, never raised (§8, "an unknown
protocol surface degrades and is logged; a version number is never compared").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

#: The token-count shape every job record in this system carries (the langchain round's own
#: `usage` dict). A harness that reports a different vocabulary is normalized onto it here,
#: so `token_usage` on a job row means one thing whoever produced it.
USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


@dataclass(frozen=True)
class HarnessReport:
    """What one finished harness process said about itself.

    Every field is optional in the honest sense: `usage is None` means nothing in the output
    reported tokens, and `cost_usd is None` means the harness does not price its own round
    (Codex, under a subscription, does not).
    """

    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    session_id: str = ""
    last_message: str = ""
    #: The harness said, in its own protocol, that the turn did not complete. Read because
    #: an exit code is not always the statement: `codex exec` can print
    #: `{"type":"turn.failed", … "Selected model is at capacity …"}` and still leave a
    #: process return code that a launcher would read as success. Without this, "the harness
    #: never ran the round" is invisible and the worker finishes an empty draft over it.
    failed: bool = False
    #: What the harness said about that failure — the provider's own sentence, which is what
    #: the marker scan and the deadline parser read.
    failure_message: str = ""


def _json_objects(text: str) -> Iterator[dict[str, Any]]:
    """Every JSON object in `text`, whether it is one document or one per line.

    Both shapes occur: Claude's `--output-format json` prints a single object (or, on some
    versions, an array of them), Codex's `--json` prints JSON Lines. Reading both here is
    what keeps the callers free of a format question.
    """
    stripped = text.strip()
    if not stripped:
        return
    try:
        whole = json.loads(stripped)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        yield whole
        return
    if isinstance(whole, list):
        for item in whole:
            if isinstance(item, dict):
                yield item
        return
    for line in stripped.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    """Every dict inside `node`, itself included — one tolerant descent, no path guessing."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize(
    raw: dict[str, Any],
    *,
    input_extra: tuple[str, ...] = (),
    output_extra: tuple[str, ...] = (),
) -> dict[str, int] | None:
    """A harness's token dict onto `USAGE_FIELDS`, or None when it counted nothing.

    `input_extra` / `output_extra` are the fields THIS harness reports BESIDE its totals
    rather than inside them, and they differ by provider — which is exactly why they are an
    argument and not a fixed list. Anthropic reports cache reads and cache writes as separate
    counts, so they are added to the input; OpenAI reports `cached_input_tokens` as the
    portion of `input_tokens` that was cached and `reasoning_output_tokens` as the portion of
    `output_tokens` that was reasoning, so adding either would count it twice. A total the
    harness stated is trusted; one it did not is derived, never left at zero beside two
    non-zero halves.
    """
    inputs = _int(raw.get("input_tokens")) + sum(_int(raw.get(f)) for f in input_extra)
    outputs = _int(raw.get("output_tokens")) + sum(_int(raw.get(f)) for f in output_extra)
    total = _int(raw.get("total_tokens")) or (inputs + outputs)
    if not (inputs or outputs or total):
        return None
    return {"input_tokens": inputs, "output_tokens": outputs, "total_tokens": total}


#: Anthropic reports these beside `input_tokens`, not inside it.
CLAUDE_INPUT_EXTRA = ("cache_creation_input_tokens", "cache_read_input_tokens")


def _message_of(node: dict[str, Any]) -> str:
    """The human sentence on a failure node, wherever this protocol hangs it."""
    for key in ("message", "error", "reason", "result"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _message_of(value)
            if nested:
                return nested
    return ""


def _session_id(node: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "thread_id", "conversation_id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def read_claude_output(stdout: str, last_message: str = "") -> HarnessReport:
    """Claude Code's `--output-format json`: the final `result` object.

    `usage` and `total_cost_usd` are read off the LAST object that carries them — with
    `--output-format json` there is one, and with a stream there is one at the end; either
    way the final statement is the round's own total rather than a turn's.
    """
    usage: dict[str, int] | None = None
    cost: float | None = None
    session = ""
    failed, failure = False, ""
    for document in _json_objects(stdout):
        for node in _walk(document):
            if isinstance(node.get("usage"), dict):
                found = _normalize(node["usage"], input_extra=CLAUDE_INPUT_EXTRA)
                if found is not None:
                    usage = found
            if isinstance(node.get("total_cost_usd"), (int, float)):
                cost = float(node["total_cost_usd"])
            session = _session_id(node) or session
            if node.get("type") == "result" and isinstance(node.get("result"), str):
                last_message = node["result"]
            if node.get("is_error") is True:
                failed, failure = True, (_message_of(node) or failure)
    return HarnessReport(
        usage=usage, cost_usd=cost, session_id=session, last_message=last_message,
        failed=failed, failure_message=failure,
    )


#: Where Codex states what a round spent. `turn.completed` carries THIS turn's counts;
#: `total_token_usage`, where a version emits it, carries the thread's running total. Two
#: names for the same fact, so both are read and neither is guessed at.
CODEX_TURN_EVENT = "turn.completed"

#: The event types Codex uses to say a turn did not happen. `turn.failed` is the turn's own
#: verdict and `error` is the stream-level one; both were observed on the same launch when a
#: model had no capacity, and either alone is enough.
CODEX_FAILURE_EVENTS = ("turn.failed", "error")


def read_codex_output(stdout: str, last_message: str = "") -> HarnessReport:
    """Codex's `--json` event stream: the token counts it emits, and no cost.

    Two shapes, because two exist. A `total_token_usage` is CUMULATIVE, so the last one is
    the round's total and summing them would multiply it. A `turn.completed` carries one
    turn's counts, so those are summed — an `exec` run is usually one turn, and a run that
    took several spent all of them. There is no cost either way: the round ran under the
    Owner's subscription and the harness prices nothing, so `cost_usd` stays None rather than
    becoming a zero that would read as "this compile was free".
    """
    cumulative: dict[str, int] | None = None
    summed = {field: 0 for field in USAGE_FIELDS}
    turns = 0
    session = ""
    failed, failure = False, ""
    for event in _json_objects(stdout):
        kind = str(event.get("type") or "")
        if kind in CODEX_FAILURE_EVENTS:
            failed = True
            failure = _message_of(event) or failure
        item = event.get("item") or {}
        if (kind == "item.completed" and isinstance(item, dict)
                and item.get("type") == "agent_message" and isinstance(item.get("text"), str)):
            last_message = item["text"]
        for node in _walk(event):
            session = _session_id(node) or session
            total = node.get("total_token_usage")
            if isinstance(total, dict):
                found = _normalize(total)
                if found is not None:
                    cumulative = found
                continue
            per_turn = node.get("usage")
            if kind == CODEX_TURN_EVENT and isinstance(per_turn, dict):
                found = _normalize(per_turn)
                if found is not None:
                    turns += 1
                    for field in USAGE_FIELDS:
                        summed[field] += found[field]
    counts = cumulative if cumulative is not None else (summed if turns else None)
    return HarnessReport(
        usage=counts, cost_usd=None, session_id=session, last_message=last_message,
        failed=failed, failure_message=failure,
    )


def read_no_output(stdout: str, last_message: str = "") -> HarnessReport:
    """The default for a manifest that declares no reader: nothing is claimed."""
    return HarnessReport()


__all__ = [
    "USAGE_FIELDS",
    "HarnessReport",
    "read_claude_output",
    "read_codex_output",
    "read_no_output",
]
