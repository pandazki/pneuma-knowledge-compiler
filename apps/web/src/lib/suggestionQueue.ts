/**
 * The suggestion bubble's queue and its countdown — a pure state machine with the clock as an
 * argument.
 *
 * The product shape: ONE suggestion is on screen at a time, as a bubble with a thirty-second
 * countdown ring. When it expires or is dismissed the next one takes its place. Suggestions
 * that arrive while a bubble is up **queue** rather than replace it — that is the rule the
 * whole module exists to hold. A live evaluation can deliver two cards a second apart, and a
 * bubble that silently overwrote itself would mean the operator saw a flash of something they
 * can never get back. Queued instead, the flash becomes a "+N" badge and a turn to be taken.
 *
 * Nothing here reads `Date.now()`. `now` is passed in, which is the only reason a
 * thirty-second countdown is testable at all: "the bubble expired" is an assertion about a
 * return value, not a thing to sit and wait for.
 *
 * Fate is recorded, not inferred. A suggestion leaves the bubble in one of three ways —
 * expired, dismissed, pinned-then-dismissed — and the history tab shows which, because "why
 * did I not see that one" and "why did that one stay" are different questions.
 *
 * No runtime imports: the node test harness transpiles this file standalone.
 */

import type { ContextSuggestion } from "./api";

/** The bubble's lifetime. Long enough to read a card, short enough that a stale one leaves. */
export const SUGGESTION_TTL_MS = 30_000;

export interface QueuedSuggestion {
  id: string;
  suggestion: ContextSuggestion;
  /** The evaluation that produced it; `null` for the one-shot transport, which has no seq. */
  seq: number | null;
  /** epoch ms of arrival — history orders by this, so a queued card keeps its real time. */
  arrivedAt: number;
}

export interface ActiveSuggestion extends QueuedSuggestion {
  /** When it reached the bubble. The countdown measures from here, not from arrival: a card
   * that waited in the queue gets its own full thirty seconds once it is finally shown. */
  shownAt: number;
  /** Pinned by `want more`: the countdown stops and only a dismissal can move it on. */
  pinned: boolean;
}

export type SuggestionFate = "expired" | "dismissed" | "pinned";

export interface HistoryEntry extends QueuedSuggestion {
  fate: SuggestionFate;
  /** epoch ms it left the bubble. */
  retiredAt: number;
}

export interface QueueState {
  current: ActiveSuggestion | null;
  /** Waiting their turn, oldest first. */
  queue: QueuedSuggestion[];
  /** Newest first — the history tab reads top-down. */
  history: HistoryEntry[];
}

export const emptyQueue: QueueState = { current: null, queue: [], history: [] };

/** Promote the head of the queue into an empty bubble. Internal; every mutation ends here. */
function promote(state: QueueState, now: number): QueueState {
  if (state.current || state.queue.length === 0) return state;
  const [next, ...rest] = state.queue;
  return { ...state, current: { ...next, shownAt: now, pinned: false }, queue: rest };
}

function retire(state: QueueState, fate: SuggestionFate, now: number): QueueState {
  if (!state.current) return state;
  const { shownAt: _shownAt, pinned: _pinned, ...card } = state.current;
  const entry: HistoryEntry = { ...card, fate, retiredAt: now };
  return promote(
    { current: null, queue: state.queue, history: [entry, ...state.history] },
    now,
  );
}

/**
 * A suggestion arrived. It takes the bubble if the bubble is free, and queues otherwise —
 * never, under any condition, replacing what is on screen.
 */
export function arrive(state: QueueState, card: QueuedSuggestion, now: number): QueueState {
  if (state.current) return { ...state, queue: [...state.queue, card] };
  return { ...state, current: { ...card, shownAt: now, pinned: false } };
}

/**
 * Advance the clock. Expires the current bubble if its thirty seconds are up and it is not
 * pinned, then promotes whatever is next.
 *
 * Idempotent and safe to call at any interval: it compares timestamps rather than counting
 * ticks, so a backgrounded tab that missed a hundred frames catches up in one call instead of
 * showing a bubble thirty seconds past its own death.
 */
export function tick(state: QueueState, now: number): QueueState {
  if (!state.current) return promote(state, now);
  if (state.current.pinned) return state;
  if (now - state.current.shownAt < SUGGESTION_TTL_MS) return state;
  return retire(state, "expired", now);
}

/** The operator closed it. Straight to history, next one up. */
export function dismiss(state: QueueState, now: number): QueueState {
  if (!state.current) return state;
  return retire(state, state.current.pinned ? "pinned" : "dismissed", now);
}

/**
 * `want more`: stop the countdown and hold this card until it is dismissed.
 *
 * Pinning is what makes the expansion usable at all — the detail arrives over the socket some
 * seconds later, and a bubble that expired while its own answer was in flight would deliver
 * the answer to nobody.
 */
export function pin(state: QueueState): QueueState {
  if (!state.current || state.current.pinned) return state;
  return { ...state, current: { ...state.current, pinned: true } };
}

/** Milliseconds left on the ring. A pinned bubble reads full and frozen, never draining. */
export function remainingMs(state: QueueState, now: number): number {
  if (!state.current) return 0;
  if (state.current.pinned) return SUGGESTION_TTL_MS;
  const left = SUGGESTION_TTL_MS - (now - state.current.shownAt);
  return Math.max(0, Math.min(SUGGESTION_TTL_MS, left));
}

/** 1 → full ring, 0 → empty. What the countdown arc is drawn from. */
export function remainingFraction(state: QueueState, now: number): number {
  return remainingMs(state, now) / SUGGESTION_TTL_MS;
}

/** Whole seconds shown in the ring; rounds UP so a live bubble never reads "0". */
export function remainingSeconds(state: QueueState, now: number): number {
  return Math.ceil(remainingMs(state, now) / 1000);
}

/** The "+N" badge. Zero means no badge — the caller does not have to special-case it. */
export function pendingCount(state: QueueState): number {
  return state.queue.length;
}
