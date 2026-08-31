"""The AI-suggestion session policy, exercised with zero I/O and zero sleeps.

Every temporal property here — the quiet period, the single-in-flight coalescing, the
reconnect — is asserted at an exact injected clock value. That is only possible because
`LiveContextSession` never reads a clock of its own; a state machine calling `time.monotonic()`
internally could only be tested by sleeping past its own boundaries, which is slow, flaky,
and cannot express "at exactly the boundary" at all.

These are synchronous functions on purpose. The session is pure, so making the tests
coroutines would suggest it awaits something.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.suggestion import label_turns
from pneuma_knowledge_service.live_context.session import (
    SHOWN_MEMORY,
    LiveContextPolicy,
    LiveContextSession,
)

T0 = 1000.0


def turn(text: str, role: str = "owner", speaker_id: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker_id or role, text=text, role=role, speaker_id=speaker_id
    )


def suggestion(title: str, kind: str = "concept", **extra) -> dict:
    return {
        "kind": kind,
        "title": title,
        "body": "b",
        "trigger": "t",
        "confidence": 9,
        **extra,
    }


def shown(title: str, kind: str = "concept", body: str = "b", subject: str = "") -> dict:
    return {
        "kind": kind,
        "title": title,
        "body": body,
        "subject": subject,
        "subject_label": subject,
    }


# ------------------------------------------------------------- the pending window


def test_a_tick_consumes_the_pending_run_exactly_once():
    """The window is PENDING, not a sliding tail. A tick reads everything said since the
    last one and processes it; the next tick starts from what came after. Re-reading would
    make the lane decide the same stretch was small talk over and over, and pay each time."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    for i in range(3):
        s.add_turn(turn(f"t{i}"))
    first = s.begin(now=T0)
    assert [t.text for t in first.turns] == ["t0", "t1", "t2"]
    assert s.turns == (), "the run it read is processed"
    s.complete(first.seq, [], now=T0)
    assert s.begin(now=T0) is None, "nothing new to read"

    s.add_turn(turn("t3"))
    second = s.begin(now=T0)
    assert [t.text for t in second.turns] == ["t3"]


def test_a_skip_consumes_its_turns_the_same_way_a_delivery_does():
    """A skip is a DECISION about those turns, not a failure to process them."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("中午吃什么"))
    plan = s.begin(now=T0)
    s.complete(plan.seq, [], now=T0)  # the lane skipped; zero cards
    assert s.turns == ()
    assert s.begin(now=T0) is None


def test_a_failed_evaluation_gives_its_turns_back():
    """A crash processed nothing. The turns go back at the FRONT of the pending run, so a
    provider hiccup does not silently swallow a stretch of the conversation."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.add_turn(turn("b"))
    s.abandon(plan.seq, now=T0, turns=plan.turns)
    assert [t.text for t in s.turns] == ["a", "b"]


def test_a_failure_does_not_re_arm_itself_into_a_hot_loop():
    """Restoring the turns must NOT mark the session dirty. With `quiet_period=0` a
    self-re-arming failure is a busy loop against a broken backend — and it is a busy loop
    that consumes no turns, so nothing ever breaks it."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.abandon(plan.seq, now=T0, turns=plan.turns)
    assert [t.text for t in s.turns] == ["a"]
    assert s.due_in(now=T0) is None, "the failed run waits for the next real turn"
    s.add_turn(turn("b"))
    assert s.due_in(now=T0) == 0.0


def test_the_pending_bound_is_policy_and_reaches_the_plan():
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.configure(max_pending_turns=4)
    s.add_turn(turn("a"))
    assert s.begin(now=T0).max_pending_turns == 4


def test_the_old_wire_names_are_tolerated_not_rejected():
    """`turn_window` was renamed and `max_suggestions` stopped meaning anything. An older
    client sending either must keep working — a 422 on a dead field helps nobody."""
    s = LiveContextSession()
    s.configure(max_pending_turns=7)
    assert s.policy.max_pending_turns == 7
    assert not hasattr(s.policy, "max_suggestions")


# --------------------------------------------------------------- the quiet period


def test_the_first_evaluation_is_not_held_by_the_quiet_period():
    """Nothing has run yet, so there is no quiet period to be inside of. A owner whose
    conversation just started should not wait out a cooldown for a round that never was."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=6.0))
    s.add_turn(turn("hello"))
    assert s.due_in(now=T0) == 0.0
    assert s.begin(now=T0) is not None


def test_the_quiet_period_runs_from_the_END_of_the_previous_evaluation():
    """Exact boundary assertions, which is the entire payoff of injecting the clock.

    Measured from the end, not the start: an evaluation that itself took 5s must still be
    followed by a full quiet period, or a slow backend would be hammered continuously."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=6.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.complete(plan.seq, [], now=T0 + 5.0)  # the evaluation itself took 5s

    s.add_turn(turn("b"))
    assert s.due_in(now=T0 + 5.0) == 6.0
    assert s.due_in(now=T0 + 8.0) == 3.0
    assert s.begin(now=T0 + 10.999) is None  # still inside, by 1ms
    assert s.due_in(now=T0 + 11.0) == 0.0  # 5.0 + 6.0, to the microsecond
    assert s.begin(now=T0 + 11.0) is not None


def test_a_session_with_no_new_turns_is_never_due():
    """Silence is the steady state: an idle connection must not schedule anything, so
    `due_in` returns None (nothing pending) rather than 0.0 (run right now)."""
    s = LiveContextSession()
    assert s.due_in(now=T0) is None
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.complete(plan.seq, [], now=T0)
    assert s.due_in(now=T0 + 999.0) is None


# ------------------------------------------------------- single in-flight + dirty


def test_turns_arriving_mid_evaluation_coalesce_into_exactly_one_rerun():
    """Three turns land while one evaluation runs. That must produce ONE more evaluation,
    not three — coalescing at the source rather than starting work we would discard."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    first = s.begin(now=T0)

    for text in ("b", "c", "d"):
        s.add_turn(turn(text))
        assert s.begin(now=T0 + 1.0) is None  # single in-flight holds the line
    assert s.dirty is True

    s.complete(first.seq, [], now=T0 + 2.0)
    second = s.begin(now=T0 + 2.0)
    assert second is not None and second.seq == first.seq + 1
    # ...and only one. The rerun consumed the dirty flag for all three turns.
    s.complete(second.seq, [], now=T0 + 3.0)
    assert s.begin(now=T0 + 3.0) is None


def test_a_plan_snapshots_the_window_it_was_built_from():
    """Turns that arrive mid-evaluation must not join the running plan's window — if they
    did, `dirty` would be describing work that had already been done. With a consuming
    window that is also what makes the boundary exact: `a` belongs to the running tick, `b`
    to the next one, and neither is read twice."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.add_turn(turn("b"))
    assert [t.text for t in plan.turns] == ["a"]
    assert [t.text for t in s.turns] == ["b"]


def test_flush_skips_the_quiet_period_but_not_the_single_in_flight_rule():
    s = LiveContextSession(LiveContextPolicy(quiet_period=60.0))
    s.add_turn(turn("a"))
    first = s.begin(now=T0)
    s.complete(first.seq, [], now=T0)

    s.add_turn(turn("b"))
    assert s.begin(now=T0 + 1.0) is None  # deep inside the quiet period
    s.flush()
    assert s.due_in(now=T0 + 1.0) == 0.0
    running = s.begin(now=T0 + 1.0)
    assert running is not None

    s.flush()  # a flush during an evaluation still coalesces
    assert s.begin(now=T0 + 1.0) is None


def test_a_stale_completion_cannot_free_the_slot_or_register_cards():
    s = LiveContextSession()
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    assert s.complete(plan.seq + 7, [suggestion("Ghost")], now=T0) == []
    assert s.in_flight == plan.seq
    assert s.already_shown == ()


def test_abandon_frees_the_slot_and_still_starts_the_quiet_period():
    """A failing evaluation must not become a retry loop against a broken backend."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=6.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.abandon(plan.seq, now=T0)
    assert s.in_flight is None
    s.add_turn(turn("b"))
    assert s.due_in(now=T0) == 6.0


# ------------------------------------------------------------------------- dedup


def test_a_repeated_card_is_dropped_on_a_later_evaluation():
    """Core drops repeats WITHIN one emission; this drops them ACROSS evaluations. The
    same card surfacing two rounds later would otherwise appear twice."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    first = s.begin(now=T0)
    assert [c["title"] for c in s.complete(first.seq, [suggestion("RAG")], now=T0)] == ["RAG"]

    s.add_turn(turn("b"))
    second = s.begin(now=T0)
    kept = s.complete(second.seq, [suggestion("RAG"), suggestion("HNSW")], now=T0)
    assert [c["title"] for c in kept] == ["HNSW"]


def test_the_same_title_under_a_different_kind_is_not_a_repeat():
    """Dedup is keyed on (kind, title): an explanation of X and an answer about X are two
    different cards, and collapsing them would silently swallow the second."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    kept = s.complete(plan.seq, [suggestion("X", "concept"), suggestion("X", "fact")], now=T0)
    assert len(kept) == 2


def test_a_plan_carries_already_shown_into_the_evaluation():
    """The list has to reach core, which uses it as a mechanical gate — showing the model
    what it already said and hoping is exactly the persuasion road this repo rejected."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    first = s.begin(now=T0)
    assert first.already_shown == ()
    s.complete(first.seq, [suggestion("RAG")], now=T0)

    s.add_turn(turn("b"))
    assert s.begin(now=T0).already_shown == (shown("RAG"),)


def test_the_client_is_the_dedup_authority():
    """`config` replaces the server's copy wholesale, including with an EMPTY list.

    The pod restarts on every deploy and drops all server-side memory; the client is the
    only thing that survives, so it has to be able to both restore and clear."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.configure(already_shown=[{"kind": "fact", "title": "从客户端恢复"}])
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    assert plan.already_shown == (shown("从客户端恢复", "fact", body=""),)
    # ...and the server honours it as a gate, not as a hint.
    assert s.complete(plan.seq, [suggestion("从客户端恢复", "fact")], now=T0) == []

    s.configure(already_shown=[])
    assert s.already_shown == ()


def test_a_shown_entry_carries_the_body_but_keys_only_on_kind_and_title():
    """The body is carried now — the discover stage answers `already_mined` against it, and
    a bare title cannot tell it whether the thing the room is circling has been said. What
    the body may NOT carry is a `[cite: sNN]` handle: the alias epoch it belonged to is over
    and a stale handle points at a DIFFERENT source. The dedup key is unchanged."""
    s = LiveContextSession()
    s.configure(already_shown=[{"kind": "fact", "title": "T", "body": "x [cite: s03] y"}])
    entry = s.already_shown[0]
    assert (entry["kind"], entry["title"]) == ("fact", "T")
    assert entry["body"] == "x y"


def test_a_replayed_subject_restores_the_ledger_on_reconnect():
    """Otherwise every reconnect re-introduces a subject the reader has already met."""
    s = LiveContextSession()
    s.configure(already_shown=[shown("Lumenlab", subject="projects/lumenlab.md")])
    assert s.ledger.held_as_duplicate("projects/lumenlab.md", "concept")
    assert not s.ledger.held_as_duplicate("projects/lumenlab.md", "fact")


def test_a_completed_evaluation_writes_the_ledger_and_a_stale_one_does_not():
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    plan = s.begin(now=T0)
    s.complete(
        plan.seq,
        [shown("Lumenlab", subject="projects/lumenlab.md")],
        now=T0,
        touched=[("projects/lumenlab.md", "lumenlab")],
        asked=True,
    )
    assert s.ledger.held_as_duplicate("projects/lumenlab.md", "concept")
    assert "somebody asked" in s.ledger.digest() or "asked about it" in s.ledger.digest()

    s.add_turn(turn("b"))
    later = s.begin(now=T0)
    assert (
        s.complete(later.seq + 9, [shown("X", subject="d.md")], now=T0, touched=[("d.md", "d")])
        == []
    )
    assert not s.ledger.held_as_duplicate("d.md", "concept")


def test_a_titleless_card_is_not_remembered():
    s = LiveContextSession()
    s.configure(already_shown=[{"kind": "fact", "title": "  "}, {"kind": "fact"}])
    assert s.already_shown == ()


def test_the_shown_memory_is_bounded():
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.configure(already_shown=[suggestion(f"c{i}") for i in range(SHOWN_MEMORY + 10)])
    assert len(s.already_shown) == SHOWN_MEMORY
    # The newest survive; the oldest were evicted.
    assert s.already_shown[-1]["title"] == f"c{SHOWN_MEMORY + 9}"


# ---------------------------------------------------------------------- reconnect


def test_a_reconnect_restores_the_window_and_schedules_an_evaluation():
    s = LiveContextSession()
    s.configure(
        turns=[turn("earlier", "other", "others/1"), turn("later")],
        already_shown=[suggestion("已读")],
    )
    assert [t.text for t in s.turns] == ["earlier", "later"]
    assert s.due_in(now=T0) == 0.0
    plan = s.begin(now=T0)
    assert plan.already_shown == (shown("已读"),)


def test_speaker_numbering_stays_stable_across_ticks():
    """参与者1 must keep meaning the same person after the turns that introduced them have
    been consumed by an earlier tick. The session holds the label map for exactly this."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    alice = turn("hi", "other", "others/1")
    bob = turn("hello", "other", "others/2")

    s.add_turn(alice)
    s.add_turn(bob)
    first = label_turns(s.turns, s.label_map)
    assert first[0].startswith("Participant1") and first[1].startswith("Participant2")

    # That run is consumed by a tick; Bob speaks again, then Alice comes back.
    plan = s.begin(now=T0)
    s.complete(plan.seq, [], now=T0)
    s.add_turn(turn("still me", "other", "others/2"))
    s.add_turn(turn("me again", "other", "others/1"))
    later = label_turns(s.turns, s.label_map)
    assert later[0].startswith("Participant2")  # bob, NOT renumbered to 1
    assert later[1].startswith("Participant1")  # alice, still 1


# ------------------------------------------------------------------ live policy


def test_the_confidence_dial_applies_to_the_next_evaluation():
    """Sensitivity is re-thresholdable mid-conversation without re-running anything: the
    model always scores, so the bar is the only thing that moves."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(turn("a"))
    assert s.begin(now=T0).min_confidence == LiveContextPolicy().min_confidence
    s.complete(1, [], now=T0)

    s.configure(min_confidence=9)
    s.add_turn(turn("b"))
    assert s.begin(now=T0).min_confidence == 9


def test_briefing_scope_is_set_and_cleared_through_config():
    s = LiveContextSession()
    s.configure(briefing_id="bf-1")
    assert s.policy.briefing_id == "bf-1"
    s.configure(min_confidence=7)  # an unrelated config leaves scope alone
    assert s.policy.briefing_id == "bf-1"
    s.configure(briefing_id="")  # "" is how a client turns it back off
    assert s.policy.briefing_id is None


def test_an_unknown_focus_is_rejected_by_the_closed_vocabulary():
    """Never a silent fallback to `general`: a focus the vocabulary does not contain is a
    bug in the caller, and evaluating under the wrong attention direction hides it."""
    with pytest.raises(ValueError, match="unknown suggestion focus"):
        LiveContextSession(LiveContextPolicy(focus="everyone"))  # type: ignore[arg-type]
    s = LiveContextSession()
    with pytest.raises(ValueError, match="unknown suggestion focus"):
        s.configure(focus="everyone")
    assert s.policy.focus == "general"  # and the session is left untouched


def test_focus_reaches_the_plan():
    s = LiveContextSession()
    s.configure(focus="other")
    s.add_turn(turn("a"))
    assert s.begin(now=T0).focus == "other"
