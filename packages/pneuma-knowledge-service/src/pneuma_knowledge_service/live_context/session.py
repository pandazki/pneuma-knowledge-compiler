"""The Live Context WebSocket session policy — a pure, clock-injected state machine.

Everything a long-lived suggestion connection decides lives here: what the sliding window
currently holds, whether an evaluation is allowed to start, which suggestions survive the
session's own dedup, and how a reconnect restores all of it. Nothing here awaits, opens a
socket, or reads a clock — `now` is a parameter on every method that needs one.

That is not stylistic. The interesting properties of this feature are *temporal*
(a quiet period elapsed; a turn arrived while an evaluation was in flight; a client
reconnected mid-conversation), and a state machine that reads `time.monotonic()`
internally can only be tested with sleeps — slow, flaky, and unable to express "exactly at
the boundary" at all. With the clock injected, every one of those becomes an ordinary
assertion at an exact float. `recall/assembly.py` is the precedent for this cut: the
deterministic half factored out, the I/O half kept thin.

Two policies here are deliberately mechanical rather than persuasive
(architecture.md:14-17):

- **Single in-flight + dirty, never cancel.** At most one evaluation runs per connection.
  A turn arriving mid-evaluation sets `dirty` and does nothing else; when the evaluation
  ends and the quiet period has passed, one more runs. Cancelling the previous round is
  not actually available — an in-flight LLM/retrieval call cannot be recalled, only its
  result discarded — so coalescing at the source is both the honest option and the simpler
  one.
- **The client is the dedup authority.** The session's `already_shown` is an optimization;
  a `config` message replaces it wholesale. The server pod restarts on every deploy
  (`replicas:1` + `Recreate`), which drops every connection and every scrap of server-side
  memory with it; if the server were authoritative, each release would replay cards the
  owner already read. This also keeps the service honestly stateless
  (architecture.md:136) instead of quietly not.

This dedup layers ON TOP of core's `already_shown` gate rather than replacing it: core
drops a repeat inside one evaluation's emission, this drops a repeat across evaluations,
and each is blind to the other's scope.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pneuma_knowledge_core.domain.suggestion import ContextFocus, focus_option
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.suggestion import (
    DEFAULT_MAX_SUGGESTIONS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_TURN_WINDOW,
)

# Seconds between the END of one evaluation and the earliest start of the next. Measured
# from the end, not the start: a slow evaluation should not be immediately followed by
# another, and this is the knob that turns a burst of transcript turns into one round.
DEFAULT_QUIET_PERIOD = 6.0

# How many (kind, title) pairs the server-side dedup remembers. Bounded because a long
# conversation would otherwise grow it without limit for no benefit — the client holds the
# authoritative list and re-sends it on reconnect, and cards that old are not what a
# repeat looks like.
SHOWN_MEMORY = 40


@dataclass(frozen=True)
class LiveContextPolicy:
    """The tunable half of a session. Every field is live-adjustable via `config`.

    `min_confidence` in particular is re-adjustable at zero cost mid-conversation: the
    model always scores each suggestion, so raising or lowering the bar changes which cards pass
    the gate without re-running any retrieval or any LLM call."""

    focus: ContextFocus = "general"
    min_confidence: int = DEFAULT_MIN_CONFIDENCE
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS
    turn_window: int = DEFAULT_TURN_WINDOW
    quiet_period: float = DEFAULT_QUIET_PERIOD
    # When set, evaluations run in briefing scope over this stored briefing (zero
    # retrieval, zero embedding). None = full scope.
    briefing_id: str | None = None


@dataclass(frozen=True)
class EvaluationPlan:
    """Everything one evaluation needs, snapshotted at the moment it was allowed to start.

    A snapshot, not a live view: turns that arrive while this runs must NOT silently join
    the window it was built from, or the `dirty` flag would be describing work that had
    already happened."""

    seq: int
    turns: tuple[ConversationTurn, ...]
    focus: ContextFocus
    min_confidence: int
    max_suggestions: int
    turn_window: int
    briefing_id: str | None
    already_shown: tuple[dict[str, str], ...]
    started_at: float


def _shown_entry(item: Any) -> dict[str, str] | None:
    """`{kind, title}` for one already-shown card, or None when it has no title.

    Accepts a `ResolvedSuggestion`, a `ContextSuggestion`, or a plain mapping (a reconnecting client replays
    JSON it has been holding). Nothing else off the card is kept: `body` may still carry
    `[cite: sNN]` handles from an evaluation whose alias epoch is long gone, and a handle
    that outlived its evaluation points at a different source."""
    if isinstance(item, Mapping):
        kind = str(item.get("kind") or "").strip()
        title = str(item.get("title") or "").strip()
    else:
        kind = str(getattr(item, "kind", "") or "").strip()
        title = str(getattr(item, "title", "") or "").strip()
    if not title:
        return None
    return {"kind": kind, "title": title}


class LiveContextSession:
    """One WebSocket connection's policy state. Pure: no clock, no I/O, no awaits."""

    def __init__(self, policy: LiveContextPolicy | None = None) -> None:
        self.policy = policy or LiveContextPolicy()
        focus_option(self.policy.focus)  # closed vocabulary; unknown raises, never defaults
        self._turns: deque[ConversationTurn] = deque(maxlen=max(1, self.policy.turn_window))
        self._shown: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
        # Held for the life of the connection so a participant number keeps meaning the same
        # person as
        # the window rolls. See core's `label_turns`.
        self.label_map: dict[str, str] = {}
        self._dirty = False
        self._force = False
        self._in_flight: int | None = None
        self._seq = 0
        self._last_end: float | None = None

    # ------------------------------------------------------------------ configuration

    def configure(
        self,
        *,
        focus: str | None = None,
        min_confidence: int | None = None,
        max_suggestions: int | None = None,
        turn_window: int | None = None,
        quiet_period: float | None = None,
        briefing_id: str | None = None,
        turns: Sequence[ConversationTurn] | None = None,
        already_shown: Sequence[Any] | None = None,
    ) -> LiveContextPolicy:
        """Apply a `config` message. Every argument is optional; None means "unchanged".

        `turns` and `already_shown` are the reconnect path: a client that lost its socket
        (a deploy, a tunnel drop, a walk through a lift) re-sends the recent window and the
        cards it has already displayed, and the session picks up where it left off rather
        than starting the conversation over and replaying read cards.

        Passing an EMPTY `already_shown` list therefore clears the server's memory — that
        is the client exercising its authority, not a degenerate case to guard against."""
        changes: dict[str, Any] = {}
        if focus is not None:
            focus_option(focus)  # raises on an unknown value
            changes["focus"] = focus
        if min_confidence is not None:
            changes["min_confidence"] = int(min_confidence)
        if max_suggestions is not None:
            changes["max_suggestions"] = int(max_suggestions)
        if turn_window is not None:
            changes["turn_window"] = max(1, int(turn_window))
        if quiet_period is not None:
            changes["quiet_period"] = max(0.0, float(quiet_period))
        if briefing_id is not None:
            # "" is how a client turns briefing scope back OFF (JSON null means unchanged).
            changes["briefing_id"] = briefing_id or None
        if changes:
            self.policy = replace(self.policy, **changes)
        if "turn_window" in changes:
            # Re-bound the window in place, keeping the newest turns.
            self._turns = deque(self._turns, maxlen=self.policy.turn_window)

        if already_shown is not None:
            self._shown.clear()
            for item in already_shown:
                self._remember(item)
        if turns is not None:
            self._turns.clear()
            self._turns.extend(turns)
            if self._turns:
                self._dirty = True
        return self.policy

    # -------------------------------------------------------------------- transcript

    def add_turn(self, turn: ConversationTurn) -> None:
        """A new transcript turn. Always accepted — never dropped for being mid-evaluation.

        The window is what the NEXT evaluation reads; `dirty` is the note that it has
        something new to read. An in-flight evaluation is not disturbed."""
        self._turns.append(turn)
        self._dirty = True

    def flush(self) -> None:
        """Client asked for an evaluation now — skips the quiet period, not the
        single-in-flight rule. A flush during an evaluation coalesces like any turn."""
        if self._turns:
            self._dirty = True
            self._force = True

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    @property
    def already_shown(self) -> tuple[dict[str, str], ...]:
        return tuple(self._shown.values())

    @property
    def in_flight(self) -> int | None:
        return self._in_flight

    @property
    def dirty(self) -> bool:
        return self._dirty

    # -------------------------------------------------------------------- scheduling

    def due_in(self, *, now: float) -> float | None:
        """Seconds until `begin` would hand back a plan, or None if it never would.

        None means "nothing pending": no new turns, or an evaluation is already running.
        A caller waits on this instead of polling, which is also why it must be exact at
        the boundary rather than approximately right."""
        if self._in_flight is not None or not self._dirty or not self._turns:
            return None
        if self._force or self._last_end is None:
            return 0.0
        return max(0.0, self.policy.quiet_period - (now - self._last_end))

    def begin(self, *, now: float) -> EvaluationPlan | None:
        """Start an evaluation if one is due, else None. Snapshots the window."""
        due = self.due_in(now=now)
        if due is None or due > 0.0:
            return None
        self._seq += 1
        self._in_flight = self._seq
        self._dirty = False
        self._force = False
        return EvaluationPlan(
            seq=self._seq,
            turns=tuple(self._turns),
            focus=self.policy.focus,
            min_confidence=self.policy.min_confidence,
            max_suggestions=self.policy.max_suggestions,
            turn_window=self.policy.turn_window,
            briefing_id=self.policy.briefing_id,
            already_shown=self.already_shown,
            started_at=now,
        )

    def complete(self, seq: int, suggestions: Sequence[Any], *, now: float) -> list[Any]:
        """Finish evaluation `seq`; return the suggestions that survive the session dedup.

        Anything but the in-flight seq is a stale result and is discarded whole — with
        single-in-flight it should not arise, but a result that outlived its evaluation
        must never be able to mark the connection idle or register cards as shown."""
        if seq != self._in_flight:
            return []
        self._in_flight = None
        self._last_end = now
        kept = []
        for suggestion in suggestions:
            entry = _shown_entry(suggestion)
            if entry is None:
                continue
            key = (entry["kind"], entry["title"])
            if key in self._shown:
                continue
            self._remember(entry)
            kept.append(suggestion)
        return kept

    def abandon(self, seq: int, *, now: float) -> None:
        """Evaluation `seq` failed. Frees the slot and starts the quiet period anyway — a
        failing backend that immediately retried would hammer it flat out."""
        if seq != self._in_flight:
            return
        self._in_flight = None
        self._last_end = now

    def _remember(self, item: Any) -> None:
        entry = _shown_entry(item)
        if entry is None:
            return
        key = (entry["kind"], entry["title"])
        self._shown.pop(key, None)
        self._shown[key] = entry
        while len(self._shown) > SHOWN_MEMORY:
            self._shown.popitem(last=False)
