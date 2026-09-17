/**
 * The voice call with the library, as pure data.
 *
 * Three streams arrive at once and they are not the same kind of thing: the voice provider's
 * own data channel (transcript fragments of both speakers, the session's life), the engine's
 * socket (what the LIBRARY was asked and what it answered), and the browser's local
 * lifecycle (a gesture, a microphone, a hang-up). `reduce` folds all three into one state, and
 * it is a pure function over plain data so the node tests can assert a whole call — captions,
 * cards, provenance marks — without a browser, a microphone or a peer connection.
 *
 * Four rules are the design's and are worth naming, because each of them exists to keep the
 * reader able to tell the LIBRARY's words from the voice model's own:
 *
 * 1. **Text is preserved.** A fragment's `delta` is concatenated exactly as received — never
 *    trimmed, never joined with an invented space. The provider's segmentation is the truth.
 * 2. **Rows are stable and grouped on the session timeline.** Row ids are assigned here and
 *    never reordered; a fragment joins the speaker's current row when it starts within
 *    `CAPTION_GAP_MS` of that row's last end, and opens a new one otherwise. The two speakers
 *    are independent and their rows may overlap in time.
 * 3. **A hand-over to the voice breaks the row.** The first assistant fragment at or after a
 *    delivery the current row began BEFORE starts a new row, so "let me check…" and the
 *    spoken result never share a row and never share a provenance mark.
 * 4. **A row is linked to a delegation, or it is the voice's own.** `captionMarks` links an
 *    assistant row to the latest delivery at or before its first fragment; a row with no such
 *    delivery and more than `UNLINKED_MARK_CHARS` characters is marked as not from the
 *    library. Short unlinked rows — acknowledgements, small talk — are left alone.
 *
 * No runtime imports: the node test harness transpiles this file standalone.
 */

/* --------------------------------------------------------------------------- the wire */

/** What the library is doing with one question the voice handed it. */
export type DelegationState =
  | "hearing"
  | "searching"
  | "answering"
  | "done"
  | "unclear"
  | "failed";

/** One acknowledged hand-over of text to the voice, on the session timeline. */
export interface Delivery {
  start_ms: number;
  end_ms: number;
}

/**
 * One question the voice delegated to the library, as the engine states it. Every frame
 * carries the delegation WHOLE, so the card is upserted by `id` and never patched field by
 * field.
 */
export interface Delegation {
  id: string;
  state: DelegationState;
  /** False once a newer ask superseded it: the card still completes, the voice stays quiet. */
  spoken: boolean;
  /** The question as the library understood it; "" while the ask is still being heard. */
  ask: string;
  /** Plain text handed to the voice so far. */
  said: string;
  /** When done: exactly the payload `POST /recall` returns in fast mode. */
  answer: unknown | null;
  /** Failure / unclear message, already written by the engine; may be "". */
  detail: string;
  offset_ms: number;
  deliveries: Delivery[];
  /** Delegation event → first hand-over; null until one happened. */
  elapsed_ms: number | null;
  /**
   * Where that wait went, in ms since the delegation event: the transcript settled, the
   * question was written, retrieval finished, the first words went out. The engine measures
   * these on its own clock rather than leaving a reader to time them from arrival gaps, and
   * the card hangs them off its duration so a slow call can be read instead of guessed at.
   * Keys are the engine's and may grow; the surface renders whatever it is given.
   */
  timings: Record<string, number>;
}

/** Every event the reducer takes: the engine's frames, the data channel's, and the tab's own. */
export type CallEvent =
  /* the browser's own lifecycle — a gesture, a microphone, a hang-up */
  | { type: "start" }
  | { type: "connecting" }
  | { type: "connected"; call_id: string; session_id: string }
  | { type: "ending" }
  | { type: "ended"; reason?: string; seconds?: number | null }
  | { type: "failed"; code: string; detail: string }
  | { type: "reset" }
  /* the voice provider's data channel */
  | { type: "session.started" }
  | { type: "session.input_transcript.delta"; delta: string; start_ms: number; end_ms: number }
  | { type: "session.output_transcript.delta"; delta: string; start_ms: number; end_ms: number }
  | { type: "session.closed"; reason?: string; usage?: { seconds?: number } | null }
  | { type: "session.input_audio.muted" }
  | { type: "session.input_audio.unmuted" }
  /* the engine's socket */
  | { type: "attached" }
  | { type: "delegation"; delegation: Delegation }
  | { type: "usage"; seconds: number; context_ratio: number | null }
  | { type: "closed"; reason: string; seconds: number | null }
  | { type: "ping" }
  /**
   * A failure, from either side. The engine says `{code, detail}` and the provider's data
   * channel says `{error: {code, message}}`; both are the same event to a reader, so one
   * member takes both shapes rather than the console inventing a third spelling.
   */
  | {
      type: "error";
      code?: string;
      detail?: string;
      error?: { code?: string; message?: string } | null;
    };

/* -------------------------------------------------------------------------- the state */

export type CallPhase =
  | "idle"
  | "asking-mic"
  | "connecting"
  | "live"
  | "ending"
  | "ended"
  | "failed";

export type CallSpeaker = "owner" | "voice";

/** One caption row: application-assigned id, one speaker, text as it was received. */
export interface CaptionRow {
  id: string;
  speaker: CallSpeaker;
  text: string;
  /** The first fragment's `start_ms` — the row's place on the session timeline. */
  startMs: number;
  /** The last fragment's `end_ms`, which is what the grouping gap is measured against. */
  endMs: number;
}

export interface CallState {
  status: CallPhase;
  rows: CaptionRow[];
  /** In arrival order, which is also the order their ordinals are read in. */
  delegations: Delegation[];
  /** Billed seconds as the engine reports them; 0 until it says. */
  seconds: number;
  /** The voice session's context pressure, null when the engine has not said. */
  contextRatio: number | null;
  /** The microphone, as the SESSION reports it — never as the click hoped. */
  muted: boolean;
  /** The engine's own sentence for a failure, and its machine code beside it. */
  error: string;
  errorCode: string;
  /** Why the session closed, in the provider's or the engine's own word. */
  closedReason: string;
  callId: string;
  sessionId: string;
  /** The engine is on the voice session: delegation works from here. */
  attached: boolean;
  rowSeq: number;
}

export function emptyCall(): CallState {
  return {
    status: "idle",
    rows: [],
    delegations: [],
    seconds: 0,
    contextRatio: null,
    muted: false,
    error: "",
    errorCode: "",
    closedReason: "",
    callId: "",
    sessionId: "",
    attached: false,
    rowSeq: 0,
  };
}

/** Same speaker, and this close on the session timeline: one row. */
export const CAPTION_GAP_MS = 1200;

/** An unlinked assistant row longer than this is marked as the voice model's own words. */
export const UNLINKED_MARK_CHARS = 24;

/** What a minute of the voice session costs, in USD. */
export const COST_PER_MINUTE_USD = 0.05;

/* ------------------------------------------------------------------------ the reducer */

/** One event folded in. Returns a NEW state; never mutates the old one. */
export function reduce(state: CallState, event: CallEvent): CallState {
  switch (event.type) {
    case "start":
      // A new call starts from nothing: the previous one's captions and cards are its own.
      return { ...emptyCall(), status: "asking-mic" };
    case "connecting":
      return { ...state, status: "connecting" };
    case "connected":
      return {
        ...state,
        status: "live",
        callId: event.call_id,
        sessionId: event.session_id,
      };
    case "session.started":
      return state.status === "live" ? state : { ...state, status: "live" };
    case "attached":
      return { ...state, attached: true };
    case "ending":
      return { ...state, status: "ending" };
    case "ended":
      return settled(state, event.reason ?? "", event.seconds ?? null);
    case "closed":
      return settled(state, event.reason, event.seconds);
    case "session.closed":
      return settled(state, event.reason ?? "", event.usage?.seconds ?? null);
    case "failed":
      return { ...state, status: "failed", errorCode: event.code, error: event.detail };
    case "reset":
      return emptyCall();
    case "session.input_transcript.delta":
      return append(state, "owner", event.delta, event.start_ms, event.end_ms);
    case "session.output_transcript.delta":
      return append(state, "voice", event.delta, event.start_ms, event.end_ms);
    case "session.input_audio.muted":
      return { ...state, muted: true };
    case "session.input_audio.unmuted":
      return { ...state, muted: false };
    case "delegation": {
      const next = normalize(event.delegation);
      if (next.id === "") return state;
      const delegations = state.delegations.slice();
      const at = delegations.findIndex((d) => d.id === next.id);
      // UPSERT: every frame carries the delegation whole, so the newer one replaces the
      // older outright — and a card never moves from the place it first took.
      if (at < 0) delegations.push(next);
      else delegations[at] = next;
      return { ...state, delegations };
    }
    case "usage":
      return {
        ...state,
        seconds: Number.isFinite(event.seconds) ? event.seconds : state.seconds,
        contextRatio: event.context_ratio ?? null,
      };
    case "error": {
      const code = event.code ?? event.error?.code ?? "error";
      const detail = event.detail ?? event.error?.message ?? "";
      return {
        ...state,
        errorCode: code,
        error: detail,
        // A call that never got up has failed; one already running keeps running and says
        // what went wrong — the session decides when it is over, not an error frame.
        status: reached(state.status) ? state.status : "failed",
      };
    }
    default:
      return state;
  }
}

/** Has the call actually got as far as a live session? */
function reached(status: CallPhase): boolean {
  return status === "live" || status === "ending" || status === "ended";
}

/** The session is over. A failure keeps its name: it is the more informative truth. */
function settled(state: CallState, reason: string, seconds: number | null): CallState {
  return {
    ...state,
    status: state.status === "failed" ? "failed" : "ended",
    closedReason: reason || state.closedReason,
    seconds: seconds != null && Number.isFinite(seconds) ? seconds : state.seconds,
  };
}

/** Whatever the engine left out, stated as the empty value rather than as `undefined`. */
function normalize(delegation: Delegation): Delegation {
  return {
    id: delegation?.id ?? "",
    state: delegation?.state ?? "hearing",
    spoken: delegation?.spoken !== false,
    ask: delegation?.ask ?? "",
    said: delegation?.said ?? "",
    answer: delegation?.answer ?? null,
    detail: delegation?.detail ?? "",
    offset_ms: delegation?.offset_ms ?? 0,
    deliveries: (delegation?.deliveries ?? []).map((d) => ({
      start_ms: d?.start_ms ?? 0,
      end_ms: d?.end_ms ?? 0,
    })),
    elapsed_ms: delegation?.elapsed_ms ?? null,
    timings: Object.fromEntries(
      Object.entries(delegation?.timings ?? {}).filter(
        ([, ms]) => typeof ms === "number" && Number.isFinite(ms),
      ),
    ) as Record<string, number>,
  };
}

/**
 * One transcript fragment, appended to the speaker's current row or opening a new one.
 *
 * The text is concatenated exactly as it arrived (rule 1). The two speakers are tracked
 * independently (rule 2), so an interruption leaves the earlier assistant row on the page and
 * the resumed speech starts its own.
 */
function append(
  state: CallState,
  speaker: CallSpeaker,
  delta: string,
  startMs: number,
  endMs: number,
): CallState {
  if (delta === "") return state;
  const rows = state.rows.slice();
  let at = -1;
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i].speaker === speaker) {
      at = i;
      break;
    }
  }
  const row = at < 0 ? null : rows[at];
  const apart = row != null && startMs - row.endMs > CAPTION_GAP_MS;
  const handedOver = row != null && speaker === "voice" && crossesDelivery(state, row, startMs);
  if (row == null || apart || handedOver) {
    const seq = state.rowSeq + 1;
    rows.push({ id: `r${seq}`, speaker, text: delta, startMs, endMs });
    return { ...state, rows, rowSeq: seq };
  }
  rows[at] = {
    ...row,
    text: row.text + delta,
    // A fragment that lands out of order must not pull the row's tail backwards, or the
    // next gap would be measured against a time the row already passed.
    endMs: Math.max(row.endMs, endMs),
  };
  return { ...state, rows };
}

/** Did a hand-over to the voice happen between this row's start and this fragment (rule 3)? */
function crossesDelivery(state: CallState, row: CaptionRow, startMs: number): boolean {
  for (const delegation of state.delegations) {
    for (const delivery of delegation.deliveries) {
      if (delivery.start_ms > row.startMs && delivery.start_ms <= startMs) return true;
    }
  }
  return false;
}

/* ---------------------------------------------------------------------- the selectors */

/**
 * What a caption row says about where its words came from.
 *
 * `ordinal` is the card's number as the list reads it (1-based), `delegationId` is what a
 * click on the badge scrolls to, and `unlinked` is the quiet mark on a stretch of speech the
 * library did not supply. The Owner's own rows are never marked: the rule is about the
 * voice model's words, not about theirs.
 */
export interface CallRowMark {
  rowId: string;
  delegationId: string;
  ordinal: number;
  unlinked: boolean;
}

/** Every row's mark, keyed by row id. */
export function captionMarks(state: CallState): Record<string, CallRowMark> {
  const marks: Record<string, CallRowMark> = {};
  for (const row of state.rows) {
    const mark: CallRowMark = { rowId: row.id, delegationId: "", ordinal: 0, unlinked: false };
    if (row.speaker === "voice") {
      // The LATEST hand-over at or before this row began is the one it is speaking; an
      // earlier delegation's delivery is not a better match just because it exists.
      let bestAt = -Infinity;
      state.delegations.forEach((delegation, index) => {
        for (const delivery of delegation.deliveries) {
          if (delivery.start_ms <= row.startMs && delivery.start_ms > bestAt) {
            bestAt = delivery.start_ms;
            mark.delegationId = delegation.id;
            mark.ordinal = index + 1;
          }
        }
      });
      mark.unlinked = mark.delegationId === "" && row.text.length > UNLINKED_MARK_CHARS;
    }
    marks[row.id] = mark;
  }
  return marks;
}

/** The circled ordinals, which run out at twenty and then say the number plainly. */
const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";

/** `③` — one card's number, the same glyph on the card and on the row that speaks it. */
export function ordinalBadge(ordinal: number): string {
  if (!Number.isFinite(ordinal) || ordinal < 1) return "";
  const n = Math.floor(ordinal);
  return n <= CIRCLED.length ? CIRCLED[n - 1] : `(${n})`;
}

/** A delegation's number as the card list reads it; 0 when this call has no such card. */
export function delegationOrdinal(state: CallState, id: string): number {
  const at = state.delegations.findIndex((d) => d.id === id);
  return at < 0 ? 0 : at + 1;
}

/** Is the call up — the window in which ending it means anything? */
export function isCallLive(state: CallState): boolean {
  return state.status === "live" || state.status === "ending";
}

/** `$0.05` — what the session has cost so far, at the published per-minute rate. */
export function formatCost(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  return `$${((safe / 60) * COST_PER_MINUTE_USD).toFixed(2)}`;
}

/** `07:12` — elapsed session time, in the unit a person reads a call in. */
export function formatElapsed(seconds: number): string {
  const safe = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const minutes = Math.floor(safe / 60);
  return `${String(minutes).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

/** `1.4` — a delegation's time to its first hand-over, as the one number the card prints. */
export function formatDelegationSeconds(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  return (ms / 1000).toFixed(1);
}
