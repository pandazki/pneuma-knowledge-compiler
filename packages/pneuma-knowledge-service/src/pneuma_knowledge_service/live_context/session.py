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

**The window is PENDING, not a fixed tail.** A tick reads everything said since the last
tick and CONSUMES it — delivered or skipped, those turns are processed and the next tick
starts from what came after. A fixed last-N slice re-read the same turns every quiet period,
which is how a lane that had already decided a stretch was small talk decided it again, and
paid for it again. `max_pending_turns` bounds the run; the overflow is stated to the model
rather than dropped in silence (core `take_pending`).

**The subject ledger is the session's memory of what it has already said.** It is per
connection, it takes no model call, and it feeds two things: the digest the discover stage
reads, and the (subject × kind) backstop under the delivery gate. Both live in core; what
lives here is the instance and the discipline that only a COMPLETED evaluation writes to it.
"""

from __future__ import annotations

import re
from collections import OrderedDict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pneuma_knowledge_core.domain.suggestion import ContextFocus, focus_option
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.live_pipeline import (
    DEFAULT_MAX_PENDING_TURNS,
    SubjectLedger,
)
from pneuma_knowledge_core.recall.suggestion import DEFAULT_MIN_CONFIDENCE

# Seconds between the END of one evaluation and the earliest start of the next. Measured
# from the end, not the start: a slow evaluation should not be immediately followed by
# another, and this is the knob that turns a burst of transcript turns into one round.
DEFAULT_QUIET_PERIOD = 6.0

# How many (kind, title) pairs the server-side dedup remembers. Bounded because a long
# conversation would otherwise grow it without limit for no benefit — the client holds the
# authoritative list and re-sends it on reconnect, and cards that old are not what a
# repeat looks like.
SHOWN_MEMORY = 40

# How many pending turns the deque physically holds. Deliberately larger than any sane
# `max_pending_turns`: the bound on what one tick READS is policy, and this is only the
# ceiling on what a connection may accumulate between ticks.
PENDING_MEMORY = 200

# A `[cite: …]` marker, however malformed. Stripped from anything a client replays: handles
# are query-local and re-assigned every evaluation.
_CITE_RESIDUE_RE = re.compile(r"\[cite:[^\]]*\]?")


@dataclass(frozen=True)
class LiveContextPolicy:
    """The tunable half of a session. Every field is live-adjustable via `config`.

    `min_confidence` in particular is re-adjustable at zero cost mid-conversation: both
    stages always score, so raising or lowering the bar changes what passes without
    re-running any retrieval or any LLM call.

    There is no `max_suggestions`: the full-scope lane delivers exactly ONE card per tick by
    construction (the pick stage chooses one), and a cap on a number that is always one is
    not a knob. The wire still tolerates the field from an older client — see `configure`."""

    focus: ContextFocus = "general"
    #: ONE number, TWO doors: discover's `worth` floor (below it nothing is retrieved) and
    #: pick's `confidence` floor (below it nothing is delivered). A deployment that wants
    #: fewer interruptions wants fewer of both, which is why it is not two dials.
    min_confidence: int = DEFAULT_MIN_CONFIDENCE
    #: The ceiling on one tick's PENDING run — not a sliding tail. See the module docstring.
    max_pending_turns: int = DEFAULT_MAX_PENDING_TURNS
    quiet_period: float = DEFAULT_QUIET_PERIOD
    #: Whether this connection allows a supplementary internet search. OFF by default, and
    #: the value held here is already the EFFECTIVE one: the transport clamps the client's
    #: request against the deployment's own knob before it arrives, so the session stays
    #: settings-blind and the `ready` echo is the truth rather than the request.
    web_search: bool = False
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
    max_pending_turns: int
    web_search: bool
    briefing_id: str | None
    already_shown: tuple[dict[str, str], ...]
    started_at: float


#: How much of a delivered card's body the mined list carries. The discover stage answers
#: `already_mined` against it, and a bare title cannot tell it whether the thing the room is
#: circling has already been said. Bounded because the whole list rides every discover turn.
SHOWN_BODY_CHARS = 200


def _field(item: Any, name: str) -> str:
    value = item.get(name) if isinstance(item, Mapping) else getattr(item, name, "")
    return str(value or "").strip()


def _shown_entry(item: Any) -> dict[str, str] | None:
    """`{kind, title, body, subject}` for one already-shown card, or None without a title.

    Accepts a `ResolvedSuggestion`, a `ContextSuggestion`, or a plain mapping (a reconnecting
    client replays JSON it has been holding). The DEDUP KEY is still `(kind, title)` and
    nothing else — `body` is carried for the discover stage to read, `subject` for the
    ledger to restore on reconnect, and neither may widen or narrow what counts as a repeat.

    `body` keeps no `[cite: sNN]` handle: a handle from an evaluation whose alias epoch is
    gone points at a different source, so it is cut here rather than travelling."""
    kind, title = _field(item, "kind"), _field(item, "title")
    if not title:
        return None
    body = " ".join(_CITE_RESIDUE_RE.sub("", _field(item, "body")).split())
    return {
        "kind": kind,
        "title": title,
        "body": body[:SHOWN_BODY_CHARS],
        "subject": _field(item, "subject"),
        "subject_label": _field(item, "subject_label"),
    }


class LiveContextSession:
    """One WebSocket connection's policy state. Pure: no clock, no I/O, no awaits."""

    def __init__(self, policy: LiveContextPolicy | None = None) -> None:
        self.policy = policy or LiveContextPolicy()
        focus_option(self.policy.focus)  # closed vocabulary; unknown raises, never defaults
        # The PENDING run: everything said since the last tick. Bounded well above
        # `max_pending_turns` so a burst during a slow evaluation is still there to be
        # read (core's `take_pending` decides what fits and states what did not).
        self._turns: deque[ConversationTurn] = deque(maxlen=PENDING_MEMORY)
        self._shown: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
        # What this conversation has looked up and said, for the discover digest and the
        # (subject × kind) backstop. Per connection, no model call, core-owned type.
        self.ledger = SubjectLedger()
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
        max_pending_turns: int | None = None,
        quiet_period: float | None = None,
        web_search: bool | None = None,
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
        is the client exercising its authority, not a degenerate case to guard against.

        A replayed card that carries a `subject` also restores the ledger, so a reconnect
        does not re-introduce a subject the reader has already been introduced to."""
        changes: dict[str, Any] = {}
        if focus is not None:
            focus_option(focus)  # raises on an unknown value
            changes["focus"] = focus
        if min_confidence is not None:
            changes["min_confidence"] = int(min_confidence)
        if max_pending_turns is not None:
            changes["max_pending_turns"] = max(1, int(max_pending_turns))
        if quiet_period is not None:
            changes["quiet_period"] = max(0.0, float(quiet_period))
        if web_search is not None:
            changes["web_search"] = bool(web_search)
        if briefing_id is not None:
            # "" is how a client turns briefing scope back OFF (JSON null means unchanged).
            changes["briefing_id"] = briefing_id or None
        if changes:
            self.policy = replace(self.policy, **changes)

        if already_shown is not None:
            self._shown.clear()
            self.ledger = SubjectLedger()
            for item in already_shown:
                entry = self._remember(item)
                if entry and entry["subject"]:
                    self.ledger.deliver(
                        entry["subject"], entry["kind"], entry["subject_label"]
                    )
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
        """Start an evaluation if one is due, else None. CONSUMES the pending run.

        Consuming, not snapshotting: the turns this tick reads are processed by it, whether
        it delivers a card or skips, and the next tick starts from what came after. A tick
        that re-read them would decide the same stretch was small talk over and over and pay
        for the decision every time. A tick that FAILS puts them back (`abandon`)."""
        due = self.due_in(now=now)
        if due is None or due > 0.0:
            return None
        self._seq += 1
        self._in_flight = self._seq
        self._dirty = False
        self._force = False
        pending = tuple(self._turns)
        self._turns.clear()
        return EvaluationPlan(
            seq=self._seq,
            turns=pending,
            focus=self.policy.focus,
            min_confidence=self.policy.min_confidence,
            max_pending_turns=self.policy.max_pending_turns,
            web_search=self.policy.web_search,
            briefing_id=self.policy.briefing_id,
            already_shown=self.already_shown,
            started_at=now,
        )

    def complete(
        self,
        seq: int,
        suggestions: Sequence[Any],
        *,
        now: float,
        touched: Sequence[tuple[str, str]] = (),
        asked: bool = False,
    ) -> list[Any]:
        """Finish evaluation `seq`; return the suggestions that survive the session dedup.

        Anything but the in-flight seq is a stale result and is discarded whole — with
        single-in-flight it should not arise, but a result that outlived its evaluation
        must never be able to mark the connection idle, register cards as shown, or write
        the ledger.

        `touched` is what retrieval actually looked up this tick, and it is recorded here
        rather than inside the lane for exactly that reason: only the session knows whether
        the result it is holding is still the current one. `asked` says the pending window
        was question-shaped, which is the cheap heuristic behind the digest's "somebody
        asked about it" — it is one word in a prompt and nothing else depends on it."""
        if seq != self._in_flight:
            return []
        self._in_flight = None
        self._last_end = now
        for key, label in touched:
            self.ledger.touch(key, label, asked=asked)
        kept = []
        for suggestion in suggestions:
            entry = _shown_entry(suggestion)
            if entry is None:
                continue
            key = (entry["kind"], entry["title"])
            if key in self._shown:
                continue
            self._remember(entry)
            if entry["subject"]:
                self.ledger.deliver(entry["subject"], entry["kind"], entry["subject_label"])
            kept.append(suggestion)
        return kept

    def abandon(self, seq: int, *, now: float, turns: Sequence[ConversationTurn] = ()) -> None:
        """Evaluation `seq` failed. Frees the slot and starts the quiet period anyway — a
        failing backend that immediately retried would hammer it flat out.

        A failure processed NOTHING, so the turns it consumed go back at the front of the
        pending run. A skip is a decision and consumes its turns; a crash is not.

        Restoring them does NOT mark the session dirty, and that omission is the whole of
        the anti-retry-loop rule: an evaluation that fails the same way every time would
        otherwise re-arm itself the instant it failed, and against a quiet period of zero
        that is a hot loop. The turns wait for the next real turn (or a `flush`) to carry
        them, which is exactly the trigger that would have carried them anyway."""
        if seq != self._in_flight:
            return
        self._in_flight = None
        self._last_end = now
        if turns:
            restored = [*turns, *self._turns]
            self._turns.clear()
            self._turns.extend(restored[-PENDING_MEMORY:])

    def _remember(self, item: Any) -> dict[str, str] | None:
        entry = _shown_entry(item)
        if entry is None:
            return None
        key = (entry["kind"], entry["title"])
        self._shown.pop(key, None)
        self._shown[key] = entry
        while len(self._shown) > SHOWN_MEMORY:
            self._shown.popitem(last=False)
        return entry
