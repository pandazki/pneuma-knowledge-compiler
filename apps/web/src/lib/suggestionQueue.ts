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
 * A **provisional** card is the one card that CAN change after it arrives. The glance
 * short-circuit delivers a subject's own definition the moment the plan names it — true,
 * verbatim, cited, and a retrieval earlier than anything else — while the tick behind it is
 * still running. When that tick settles, `upgrade` either replaces the card in place or
 * simply clears the provisional mark. In place is the whole point: the reader is looking at
 * one bubble that is filling in, not at two bubbles about one subject, and that holds even
 * when the card is pinned or sitting in the queue.
 *
 * Fate is recorded, not inferred. A suggestion leaves the bubble in one of three ways —
 * expired, dismissed, pinned-then-dismissed — and the history tab shows which, because "why
 * did I not see that one" and "why did that one stay" are different questions.
 *
 * No runtime imports: the node test harness transpiles this file standalone.
 */

import type { ContextSuggestion, SuggestionShown } from "./api";

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
 * A provisional card settled. `full` present ⇒ it becomes that card, IN PLACE; `null` ⇒ it
 * stays exactly what it is, minus the provisional mark.
 *
 * In place means in place, wherever it is — on screen, pinned, or still in the queue. A
 * pinned card upgrades without unpinning, because pinning is the reader saying "hold this
 * one" and the upgrade is that same one arriving in full. And a card whose countdown has
 * been running keeps its own `shownAt`: the upgrade is what the reader was already waiting
 * for, not a new thirty seconds.
 *
 * An `upgrade` naming a card that is already gone (expired, dismissed) does nothing at all.
 * History records the final form, and a settled card that left the bubble before its tick
 * finished is exactly what the reader saw.
 */
export function upgrade(
  state: QueueState,
  seq: number | null,
  full: ContextSuggestion | null,
): QueueState {
  const settle = (card: ContextSuggestion): ContextSuggestion => ({
    ...(full ?? card),
    provisional: false,
  });
  const matches = (card: QueuedSuggestion) =>
    card.seq === seq && card.suggestion.provisional === true;
  const current =
    state.current && matches(state.current)
      ? { ...state.current, suggestion: settle(state.current.suggestion) }
      : state.current;
  const queue = state.queue.map((card) =>
    matches(card) ? { ...card, suggestion: settle(card.suggestion) } : card,
  );
  return { ...state, current, queue };
}

/**
 * How long a provisional card waits for its settling frame before settling itself.
 *
 * The client-side belt under the server's `upgrade`. The server now settles a provisional
 * card on EVERY ending of the tick that delivered it — including a raise, which is the
 * ending that used to emit nothing — but "the frame is always sent" and "the frame always
 * arrives" are different claims, and only the first is something the server can hold. A
 * dropped socket frame, a queue overflow, a client that reconnected between the card and
 * its upgrade: any of those leaves a badge reading 「细节补充中…」 about a tick that finished
 * long ago.
 *
 * Longer than the thirty-second TTL on purpose: an unpinned card on screen leaves before
 * this can fire, so the timer is not a second expiry racing the first. What it actually
 * covers is the two cards a TTL never reaches — one the reader pinned, and one still
 * waiting its turn in the queue.
 */
export const PROVISIONAL_SETTLE_MS = 45_000;

/**
 * The provisional cards that have waited past `PROVISIONAL_SETTLE_MS` without a settling
 * frame. Returned rather than settled so the caller can say so in the wire log — a card
 * that settled itself is a LOST FRAME, and a surface that showed the same result either way
 * would hide the one fact worth knowing.
 */
export function staleProvisional(
  state: QueueState,
  now: number,
  timeout: number = PROVISIONAL_SETTLE_MS,
): QueuedSuggestion[] {
  const stale = (card: QueuedSuggestion) =>
    card.suggestion.provisional === true && now - card.arrivedAt >= timeout;
  return [...(state.current && stale(state.current) ? [state.current] : []), ...state.queue.filter(stale)];
}

/**
 * Settle every provisional card that has waited too long, where it stands.
 *
 * It settles as FINAL WITH WHAT IT HAS, which is the only fail-safe this card can have and
 * costs nothing: a glance card's body is the library's own definition, verbatim and cited,
 * so the card minus its shimmer is a true card — never a placeholder left holding an
 * unfilled promise.
 */
export function settleStale(
  state: QueueState,
  now: number,
  timeout: number = PROVISIONAL_SETTLE_MS,
): QueueState {
  const stale = staleProvisional(state, now, timeout);
  if (stale.length === 0) return state;
  const ids = new Set(stale.map((card) => card.id));
  const clear = <T extends QueuedSuggestion>(card: T): T =>
    ids.has(card.id) ? { ...card, suggestion: { ...card.suggestion, provisional: false } } : card;
  return {
    ...state,
    current: state.current ? clear(state.current) : null,
    queue: state.queue.map(clear),
  };
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

/* ------------------------------------------------------------------ clearing it all */

/**
 * What the page has counted this conversation. Names the same four numbers the panel shows,
 * and lives here rather than in the panel because CLEARING them is part of the same act as
 * clearing the queue.
 */
export interface SurfaceCounts {
  turnsSent: number;
  suggestions: number;
  /** Suppressed by the client's own {kind,title} deduplication, which is the authority. */
  deduped: number;
  evaluations: number;
}

/**
 * Everything the page holds ABOUT one conversation's suggestions — every store that
 * 「清空对话」 has to empty.
 *
 * It is one type for a reason the bug taught: the clear used to empty the turn list alone,
 * and the panel beside it went on showing the cards, the counts, the tick records and the
 * dedup map of a conversation that no longer existed. Naming the whole set in one place is
 * what lets `surfaceIsEmpty` be the mechanical answer to "is anything still there" instead
 * of a hand-maintained list of conditions in a button's `disabled`.
 *
 * Generic in the three log/book element types so the view's own frame types survive a
 * round trip through here; nothing in this module reads inside them.
 */
export interface SuggestionSurface<Wire = unknown, Stats = unknown, Detail = unknown> {
  /** The bubble, the ones behind it, and the record of what has been. */
  queue: QueueState;
  /** The dedup authority: `${kind} ${title}` → what was shown, replayed to the server. */
  seen: Map<string, SuggestionShown>;
  counts: SurfaceCounts;
  /** The transport log. */
  wire: Wire[];
  /** The per-tick processing records. */
  stats: Stats[];
  /** `want_more` books: what came back, what is still out, what failed. */
  details: Record<string, Detail>;
  pending: string[];
  failures: Record<string, string>;
}

/** A surface holding nothing — what a cleared conversation looks like, and what a new one
 * starts as. A function rather than a constant: `seen` is a Map and the caller mutates it. */
export function emptySurface<Wire = unknown, Stats = unknown, Detail = unknown>(): SuggestionSurface<
  Wire,
  Stats,
  Detail
> {
  return {
    queue: emptyQueue,
    seen: new Map(),
    counts: { turnsSent: 0, suggestions: 0, deduped: 0, evaluations: 0 },
    wire: [],
    stats: [],
    details: {},
    pending: [],
    failures: {},
  };
}

/** Whether this surface still holds anything at all. Every store participates — a store
 * left out here is a store a clear could quietly forget, which is exactly the defect. */
export function surfaceIsEmpty(surface: SuggestionSurface<unknown, unknown, unknown>): boolean {
  const { queue, seen, counts, wire, stats, details, pending, failures } = surface;
  return (
    queue.current === null &&
    queue.queue.length === 0 &&
    queue.history.length === 0 &&
    seen.size === 0 &&
    counts.turnsSent === 0 &&
    counts.suggestions === 0 &&
    counts.deduped === 0 &&
    counts.evaluations === 0 &&
    wire.length === 0 &&
    stats.length === 0 &&
    Object.keys(details).length === 0 &&
    pending.length === 0 &&
    Object.keys(failures).length === 0
  );
}
