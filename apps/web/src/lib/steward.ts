/**
 * The Steward conversation, as pure data.
 *
 * The socket delivers one flat stream of events — a turn started, text written a fragment at
 * a time, a step begun, that step's result, the turn's end. What the page renders is a list
 * of ITEMS: the Steward's prose as one growing block, and each command as a row with its
 * result folded under it. `reduce` is the whole of that translation, and it is a pure
 * function over plain data so the node tests can assert a rendered conversation without a
 * browser, a socket or a harness.
 *
 * Two rules are worth naming because they are the design's, not React's:
 *
 * 1. **A step is the agent's own command.** Nothing here invents, renames or prettifies what
 *    the Steward ran; `command` arrives from the harness and is shown as it came. The console
 *    adds nothing the agent did not do, and hides nothing it did (§5.6).
 * 2. **A step that changes the library moves the other views.** `INVALIDATING` is that rule,
 *    stated once: when one of those commands finishes, the history, process and sources
 *    stores refetch, and the history view gains its commit while the Steward is still
 *    typing. It is matched on the command's TEXT because the command text is what the bridge
 *    reports — there is no structured "this wrote canonical" signal, and inventing one would
 *    mean the console claiming to know what a step did.
 *
 * No runtime imports: the node test harness transpiles this file standalone.
 */

/** Every frame the socket can deliver. `type` is the discriminator, as on the wire. */
export type StewardFrame =
  | { type: "snapshot"; configured: boolean; backend: string; label: string; protocol: string; spec: string; live: boolean; exited: boolean; exit_code: number | null; agent_session_id: string; project_dir: string; session_id: string; events: StewardFrame[] }
  | { type: "not_configured"; detail: string }
  | { type: "session_started"; agent_session_id: string; model: string }
  | { type: "turn_started"; turn_id: string }
  | { type: "text_delta"; text: string }
  | { type: "step_started"; step_id: string; command: string; tool: string }
  | { type: "step_finished"; step_id: string; exit_code: number | null; output_preview: string; duration_ms: number; failed: boolean }
  | { type: "permission_request"; request_id: string; method: string; detail: string; declined: boolean }
  | { type: "turn_finished"; usage: Record<string, number> | null; cost_usd: number | null; duration_ms: number; error: string }
  | { type: "session_exited"; exit_code: number; detail: string }
  | { type: "notice"; code: string; detail: string }
  | { type: "error"; detail: string }
  | { type: "ping" };

export interface OwnerItem {
  kind: "owner";
  id: string;
  text: string;
  /** Held behind a turn in flight, and told so. Never steered, never resent. */
  queued: boolean;
}

export interface TextItem {
  kind: "text";
  id: string;
  text: string;
}

export interface StepItem {
  kind: "step";
  id: string;
  command: string;
  tool: string;
  running: boolean;
  exitCode: number | null;
  output: string;
  durationMs: number;
  failed: boolean;
  /** A permission request renders as a step that STOPPED, because that is what it is. */
  stopped: boolean;
}

export interface UsageItem {
  kind: "usage";
  id: string;
  usage: Record<string, number> | null;
  costUsd: number | null;
  durationMs: number;
  error: string;
}

export interface NoticeItem {
  kind: "notice";
  id: string;
  code: string;
  detail: string;
}

export type StewardItem = OwnerItem | TextItem | StepItem | UsageItem | NoticeItem;

export interface StewardState {
  items: StewardItem[];
  /** A turn is in flight: the composer says so, and a message sent now is queued. */
  busy: boolean;
  /** The harness's own session id, once it names one (Claude only says after the first turn). */
  agentSessionId: string;
  exited: boolean;
  exitCode: number | null;
  /** Set when the deployment compiles with a model: the view's empty state. */
  notConfigured: string;
  /** Commands whose finish should move the other views, in arrival order. */
  invalidations: string[];
  seq: number;
}

export function emptyConversation(): StewardState {
  return {
    items: [],
    busy: false,
    agentSessionId: "",
    exited: false,
    exitCode: null,
    notConfigured: "",
    invalidations: [],
    seq: 0,
  };
}

/**
 * The commands that change the library, and therefore the other views.
 *
 * Matched as substrings of the command the harness reported, because that string is all
 * there is: `pkc draft finish` commits, `pkc owner say` files a source, `pkc ingest` imports
 * one, `pkc draft abandon` releases a job, `pkc source archive` retires material. A read
 * command (`pkc jobs`, `pkc recall`) changes nothing and moves nothing.
 */
export const INVALIDATING: readonly string[] = [
  "pkc draft finish",
  "pkc owner say",
  "pkc ingest",
  "pkc draft abandon",
  "pkc source archive",
];

/** Does this finished step mean the library moved? */
export function invalidates(command: string): boolean {
  const text = (command || "").replace(/\s+/g, " ").trim();
  return INVALIDATING.some((c) => text.includes(c));
}

function last(state: StewardState): StewardItem | undefined {
  return state.items[state.items.length - 1];
}

/**
 * One frame folded into the conversation. Returns a NEW state; never mutates the old one.
 *
 * `snapshot` replays: a reconnecting tab is repainted by feeding its events through this same
 * function, so what a reconnect draws and what a live session drew cannot differ.
 */
export function reduce(state: StewardState, frame: StewardFrame): StewardState {
  const next: StewardState = { ...state, items: state.items.slice(), seq: state.seq + 1 };
  switch (frame.type) {
    case "snapshot": {
      let replayed = { ...emptyConversation(), notConfigured: "" };
      for (const event of frame.events ?? []) replayed = reduce(replayed, event);
      return {
        ...replayed,
        agentSessionId: frame.agent_session_id || replayed.agentSessionId,
        exited: frame.exited || replayed.exited,
        exitCode: frame.exit_code ?? replayed.exitCode,
        // A repaint is not a change to the library: the invalidations of a conversation
        // already on the screen were acted on when they happened.
        invalidations: [],
      };
    }
    case "not_configured":
      return { ...next, notConfigured: frame.detail || "not configured" };
    case "session_started":
      return { ...next, agentSessionId: frame.agent_session_id };
    case "turn_started":
      return { ...next, busy: true };
    case "text_delta": {
      const tail = last(next);
      if (tail && tail.kind === "text") {
        next.items[next.items.length - 1] = { ...tail, text: tail.text + frame.text };
      } else {
        next.items.push({ kind: "text", id: `t${next.seq}`, text: frame.text });
      }
      return next;
    }
    case "step_started":
      next.items.push({
        kind: "step",
        id: frame.step_id || `s${next.seq}`,
        command: frame.command,
        tool: frame.tool,
        running: true,
        exitCode: null,
        output: "",
        durationMs: 0,
        failed: false,
        stopped: false,
      });
      return next;
    case "step_finished": {
      const index = findStep(next.items, frame.step_id);
      if (index < 0) return next;
      const step = next.items[index] as StepItem;
      next.items[index] = {
        ...step,
        running: false,
        exitCode: frame.exit_code,
        output: frame.output_preview,
        durationMs: frame.duration_ms,
        failed: frame.failed || (frame.exit_code != null && frame.exit_code !== 0),
      };
      if (invalidates(step.command)) next.invalidations = [...next.invalidations, step.command];
      return next;
    }
    case "permission_request":
      next.items.push({
        kind: "step",
        id: frame.request_id || `p${next.seq}`,
        command: frame.method,
        tool: "permission",
        running: false,
        exitCode: null,
        output: frame.detail,
        durationMs: 0,
        failed: true,
        stopped: true,
      });
      return next;
    case "turn_finished":
      next.busy = false;
      next.items.push({
        kind: "usage",
        id: `u${next.seq}`,
        usage: frame.usage,
        costUsd: frame.cost_usd,
        durationMs: frame.duration_ms,
        error: frame.error,
      });
      return next;
    case "session_exited":
      return {
        ...next,
        busy: false,
        exited: true,
        exitCode: frame.exit_code,
      };
    case "notice": {
      // A queued message is not a new item: it marks the owner turn that is waiting.
      if (frame.code === "queued") {
        for (let i = next.items.length - 1; i >= 0; i -= 1) {
          const item = next.items[i];
          if (item.kind === "owner" && !item.queued) {
            next.items[i] = { ...item, queued: true };
            return next;
          }
        }
        return next;
      }
      next.items.push({ kind: "notice", id: `n${next.seq}`, code: frame.code, detail: frame.detail });
      return next;
    }
    case "error":
      next.items.push({ kind: "notice", id: `e${next.seq}`, code: "error", detail: frame.detail });
      return next;
    default:
      return state;
  }
}

function findStep(items: StewardItem[], stepId: string): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i];
    if (item.kind === "step" && item.id === stepId) return i;
  }
  return -1;
}

/** The Owner's own turn, appended locally the moment it is sent (the socket never echoes it). */
export function ownerSaid(state: StewardState, text: string): StewardState {
  return {
    ...state,
    seq: state.seq + 1,
    items: [...state.items, { kind: "owner", id: `o${state.seq + 1}`, text, queued: false }],
  };
}

/** Acknowledge the invalidations the caller has acted on. */
export function clearInvalidations(state: StewardState): StewardState {
  return state.invalidations.length ? { ...state, invalidations: [] } : state;
}

/** `1.2s`, `340ms` — a step's duration, in the unit a person reads it in. */
export function formatDuration(ms: number): string {
  if (!ms || ms < 0) return "";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** The usage line's numbers, in a stable order, dropping what the harness did not report. */
export function usageEntries(usage: Record<string, number> | null): [string, number][] {
  if (!usage) return [];
  return Object.entries(usage)
    .filter(([, value]) => typeof value === "number")
    .sort(([a], [b]) => a.localeCompare(b));
}
