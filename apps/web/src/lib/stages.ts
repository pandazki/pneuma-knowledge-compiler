/**
 * Per-stage wall-clock, prepared for display — for every lane that reports one.
 *
 * The fast lane sends the whole fixed vocabulary as a FLAT list every time (a stage that did
 * not run is present with `status: "skipped"` and `ms: 0`) with children of the retrieval
 * gather under a dotted name (`retrieve.claims`, `retrieve.path:person`). The deep lane has
 * no fixed vocabulary to send — how many turns the agentic loop took and which tools it
 * reached for is the measurement — so it sends the run's own sequence: `turn:1`,
 * `tool:search_claims`, `turn:2`, an optional `finalize`, then `total`.
 *
 * NOTHING HERE KNOWS EITHER VOCABULARY. The only conventions this module reads are structural
 * and shared: a dot nests a child under the parent that precedes it, and `total` is the stage
 * that wraps the rest. A name it has never seen is laid out and labelled like any other,
 * which is what lets a lane grow a stage — or a new lane arrive — without a viewer release.
 *
 * Children report their OWN durations and ran concurrently, so they sum to more than the
 * parent, which is the gather's wall-clock. That is a fact to show, not an error to correct —
 * a strip that "fixed" it by scaling children would hide which lane was the slow one.
 *
 * TWO SOURCES, ONE SHAPE. A finished answer carries `StageTiming[]`; a stream carries
 * `StageEvent[]` arriving as the lane runs. Both are folded into `FlowStage[]` — the same
 * row shape, with `running` set on the ones that have begun and not yet settled — so the
 * diagram is written once and does not know whether it is watching or reading.
 */

export type StageStatus = "ran" | "skipped" | "degraded";

/**
 * A BOUNDED glance at what a stage was handed and what it produced — the queries a plan
 * wrote, how many hits a face returned and what the first few of them SAY, the calls a
 * routing turn chose, the characters each assembled section carries.
 *
 * The keys belong to the STAGE, not to this module, exactly as the stage names do: a lane
 * that grows a stage or renames a key must not need a viewer release. So it is an open record
 * and everything here treats it as opaque data to carry and to print, never to interpret.
 * The service caps it at ~1 KB serialized, so it is always small enough to render whole.
 */
export type StagePreview = Record<string, unknown>;

/** One stage exactly as the API sends it with a finished answer. */
export interface StageTiming {
  name: string;
  ms: number;
  status: StageStatus;
  /** The lane's own fall-back reason ("timeout", "error", "invalid_args", …) when degraded. */
  detail?: string | null;
  /** What went in and what came out. Absent from an older service, or from a stage with
   * nothing worth previewing — both of which mean "nothing to open", never an empty panel. */
  preview?: StagePreview | null;
}

/**
 * One stage crossing a boundary, as the stream routes send it while the lane runs.
 *
 * `key` identifies a NODE and belongs to the lane, not to us: a fixed vocabulary accumulates
 * by name (`key === name`, and a later `end` supersedes the earlier one), while an agentic
 * lane appends — two calls to one tool are two steps — and mints a fresh key each time. Key
 * on `key`, print `name`, and both lanes are handled without knowing which one is running.
 *
 * `at_ms` is elapsed milliseconds since the lane began, on the SERVER's clock — it places the
 * event on the lane's timeline, and is NOT what a counter ticks from (a stage that opens three
 * seconds into the lane has been running for zero, not three). `received` is stamped by the
 * client when the frame arrived (see `stampReceived`), and a running node's counter is the
 * stage's own elapsed measured from there. The reducer stays pure because the clock is an
 * argument rather than something it reads.
 */
export interface StageEvent {
  name: string;
  key: string;
  phase: "start" | "end";
  at_ms: number;
  ms?: number | null;
  status?: StageStatus;
  detail?: string | null;
  /** The stage's preview, on `end` frames only — it arrives the moment the node settles. */
  preview?: StagePreview | null;
  /** Client arrival time (`Date.now()`), stamped on receipt. Absent = never ticks. */
  received?: number;
}

/** One stage ready to be laid out: finished or still running, from either source. */
export interface FlowStage {
  /** Stable identity for React and for matching a start to its end. */
  key: string;
  name: string;
  ms: number;
  status: StageStatus;
  detail: string | null;
  /** What the stage was handed and produced, or null when it offered nothing. */
  preview: StagePreview | null;
  /** True between this stage's `start` and its `end`. Always false for a finished answer. */
  running: boolean;
}

/** A laid-out stage: leaf label resolved, concurrent children attached. */
export interface FlowNode extends FlowStage {
  /** What to print: the part after the dot for a child, the whole name for a parent. */
  leaf: string;
  children: FlowNode[];
}

const SEPARATOR = ".";

/** The stage that wraps all the others. Always shown last, whatever order it arrived in. */
export const TOTAL = "total";

function leafOf(name: string): string {
  const cut = name.indexOf(SEPARATOR);
  return cut === -1 ? name : name.slice(cut + 1);
}

/**
 * Stamp client arrival on an event. Called once, where the frame lands — the reducer must
 * stay pure, so the only clock it ever sees is one that was handed to it.
 */
export function stampReceived(event: StageEvent, now = Date.now()): StageEvent {
  return { ...event, received: now };
}

/**
 * Fold the stream's events into the rows to draw, at client time `now`.
 *
 * The rules, all structural and none of them vocabulary-aware:
 *
 * - a `start` opens a node under its key, or REOPENS one that already ended (fast's
 *   `assemble` is measured several times across the lane and is one stage, not four);
 * - an `end` settles that key with the ms/status/reason the server measured;
 * - an `end` whose `start` was never seen still opens a node — an event lost to a dropped
 *   frame or a lane that only records after the fact must never make a measured stage vanish;
 * - a running node's `ms` is ITS OWN elapsed — whatever it had already accumulated, plus the
 *   time since its `start` frame arrived. Not the lane's `at_ms`: a counter running on the
 *   lane's clock would show 3.0s for a stage that had been going for 200ms, and then jump
 *   BACKWARDS to the real measurement when the `end` landed. A number that shrinks when it
 *   settles is worse than no number, because it makes the measured one look wrong too;
 * - order is first-appearance order, except `total`, which wraps everything and is moved last.
 */
export function liveStages(
  events: readonly StageEvent[] | null | undefined,
  now: number = Date.now(),
): FlowStage[] {
  const byKey = new Map<string, FlowStage>();
  const ticking = new Map<string, { received: number }>();
  for (const event of events ?? []) {
    const existing = byKey.get(event.key);
    if (event.phase === "start") {
      ticking.set(event.key, { received: event.received ?? now });
      byKey.set(event.key, {
        key: event.key,
        name: event.name,
        // A reopened stage keeps what it had already accumulated: the server sends the
        // running total on every end, so showing 0 while it runs again would read as a reset.
        ms: existing?.ms ?? 0,
        status: existing?.status ?? "ran",
        detail: existing?.detail ?? null,
        // A reopened stage keeps the preview it already had, for the same reason it keeps
        // its accumulated ms: the server sends the whole thing again on the next `end`, and
        // blanking the panel a reader has open would read as the fact being withdrawn.
        preview: existing?.preview ?? null,
        running: true,
      });
      continue;
    }
    ticking.delete(event.key);
    byKey.set(event.key, {
      key: event.key,
      name: event.name,
      ms: event.ms ?? existing?.ms ?? 0,
      status: event.status ?? "ran",
      detail: event.detail ?? null,
      preview: event.preview ?? existing?.preview ?? null,
      running: false,
    });
  }
  const rows = [...byKey.values()].map((row) => {
    const clock = ticking.get(row.key);
    if (!clock) return row;
    // `row.ms` is what this stage had already accumulated (0 on a first start, the running
    // total on a reopen), so the counter continues rather than restarting.
    return { ...row, ms: row.ms + Math.max(now - clock.received, 0) };
  });
  const totals = rows.filter((r) => r.name === TOTAL);
  return totals.length === 0
    ? rows
    : [...rows.filter((r) => r.name !== TOTAL), ...totals];
}

/**
 * The same rows, from a finished answer. Nothing is running, and the key carries the index
 * because an agentic lane may report two steps with one name (`tool:search_claims` twice)
 * and two rows keyed alike would collapse into one in the diagram.
 */
export function finishedStages(
  stages: readonly StageTiming[] | null | undefined,
): FlowStage[] {
  return (stages ?? []).map((stage, index) => ({
    key: `${stage.name}#${index}`,
    name: stage.name,
    ms: stage.ms,
    status: stage.status,
    detail: stage.detail ?? null,
    preview: stage.preview ?? null,
    running: false,
  }));
}

/**
 * Accept either shape. A finished answer's `StageTiming` is a `FlowStage` missing only the
 * two fields streaming introduced, so the tolerant read is a default, not a conversion —
 * every caller that has one list or the other keeps working with no branch of its own.
 */
export function asFlow(
  rows: readonly (FlowStage | StageTiming)[] | null | undefined,
): FlowStage[] {
  return (rows ?? []).map((row, index) => ({
    key: (row as FlowStage).key ?? `${row.name}#${index}`,
    name: row.name,
    ms: row.ms,
    status: row.status,
    detail: row.detail ?? null,
    preview: row.preview ?? null,
    running: (row as FlowStage).running ?? false,
  }));
}

/**
 * Lay the rows out as a flow: sequential nodes, with the concurrent children of a gather
 * hanging off the parent that precedes them, and `total` pulled out as the wrapper it is.
 *
 * A child whose parent is absent is kept as a top-level node rather than dropped — an older
 * or newer service must never be able to make a measured stage vanish from the diagram.
 */
export function stageFlow(rows: readonly FlowStage[]): {
  nodes: FlowNode[];
  total: FlowNode | null;
} {
  const nodes: FlowNode[] = [];
  const byName = new Map<string, FlowNode>();
  let total: FlowNode | null = null;
  for (const row of rows) {
    const node: FlowNode = { ...row, leaf: leafOf(row.name), children: [] };
    if (row.name === TOTAL) {
      total = node;
      continue;
    }
    const cut = row.name.indexOf(SEPARATOR);
    const parent = cut === -1 ? undefined : byName.get(row.name.slice(0, cut));
    if (parent) {
      parent.children.push(node);
      continue;
    }
    nodes.push(node);
    byName.set(row.name, node);
  }
  return { nodes, total };
}

/** Nest a finished answer's flat wire list — kept for callers that only have `StageTiming[]`. */
export function stageTree(stages: StageTiming[] | null | undefined): FlowNode[] {
  const { nodes, total } = stageFlow(finishedStages(stages));
  return total ? [...nodes, total] : nodes;
}

/**
 * One entry in a preview list: what the item SAYS, where it is, and its id.
 *
 * The three field names (`text`, then any other field as location, and `id`) are the only
 * vocabulary this module knows, and it knows them because they are shared by every lane — a
 * claim, a passage, an episode and a chosen page all answer the same three questions. Any
 * other key of an entry joins the location, so a lane can add one without a viewer release.
 */
export interface PreviewItem {
  /** A bounded head of the item's own words. Empty when the lane had none to give. */
  text: string;
  /** Where it lives — a document title, a source and a block span. Empty when unknown. */
  where: string;
  /** The id, as a trailing tag. Empty when the bound dropped it to keep the words. */
  id: string;
}

/** One row of a preview panel: a label, a printable value, and — for a list of entries —
 * the entries themselves, so the panel can lay them out as lines rather than as one string. */
export interface PreviewRow {
  key: string;
  value: string;
  items?: PreviewItem[];
}

/**
 * One preview, flattened into the rows a panel prints.
 *
 * Written here rather than in the component because it is the whole of the rendering
 * DECISION and none of the rendering: a scalar is itself, a list of ENTRIES becomes items a
 * panel prints one per line, any other array is its members joined (the service already
 * truncated it and marked the truncation), and a nested object is its own `key=value` pairs
 * on one line — one level deep, because a preview is a glance and a tree is not one. Keys are
 * printed as the lane sent them, since only the lane knows what it measured; nothing here
 * maps a key to a translated name it might not have.
 */
export function previewRows(preview: StagePreview | null | undefined): PreviewRow[] {
  if (!preview) return [];
  return Object.entries(preview).map(([key, value]) => {
    const items = previewItems(value);
    return items ? { key, value: previewValue(value), items } : { key, value: previewValue(value) };
  });
}

/** An entry is an object that says something. Anything else is not a list of entries, and
 * the truncation marker the service appends (`…+7 more`) rides along as a text-only entry so
 * a reader still sees that the list was cut. */
function previewItems(value: unknown): PreviewItem[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const entries = value.filter((v) => v !== null && typeof v === "object" && !Array.isArray(v));
  if (entries.length === 0) return null;
  return value
    .map((row) => {
      if (typeof row === "string") return { text: row, where: "", id: "" };
      if (row === null || typeof row !== "object" || Array.isArray(row)) return null;
      const fields = row as Record<string, unknown>;
      const where = Object.entries(fields)
        .filter(([k]) => k !== "text" && k !== "id")
        .map(([, v]) => previewValue(v))
        .filter((v) => v !== "" && v !== "–")
        .join(" ");
      return {
        text: fields.text === undefined ? "" : previewValue(fields.text),
        where,
        id: fields.id === undefined ? "" : previewValue(fields.id),
      };
    })
    .filter((row): row is PreviewItem => row !== null);
}

function previewValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  // An empty list is "nothing came back" — the same fact the placeholder already stands for,
  // and a row that printed nothing at all would read as a rendering bug instead.
  if (Array.isArray(value)) return value.length === 0 ? "–" : value.map(previewValue).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}=${previewValue(v)}`)
      .join(", ");
  }
  return String(value);
}

/** `812` → `812ms`; `4001` → `4.0s`. Seconds past a second, because 4001ms is unreadable. */
export function formatStageMs(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/**
 * The flow as one plain-text line — the same breakdown `./app.py ask` prints, used for a
 * title attribute and for the tests that pin the shape.
 *
 * A stage that did not run prints the placeholder rather than `0ms`: "never happened" and
 * "was free" are different facts, and collapsing them is the one thing this diagram exists to
 * prevent.
 */
export function stageStripText(
  stages: StageTiming[] | null | undefined,
  skipped = "–",
): string {
  const one = (n: FlowNode): string => {
    if (n.status === "skipped") return `${n.leaf} ${skipped}`;
    const time = formatStageMs(n.ms);
    return n.status === "degraded" ? `${n.leaf} ${time}!${n.detail ?? ""}` : `${n.leaf} ${time}`;
  };
  return stageTree(stages)
    .map((root) => {
      const head = one(root);
      return root.children.length === 0
        ? head
        : `${head} (${root.children.map(one).join(" · ")})`;
    })
    .join(" · ");
}

/**
 * The stage that took longest, ignoring `total` (which wraps them all) and anything still
 * running (its number is a counter, not a measurement). Null when nothing has settled.
 */
export function slowestStage(
  rows: readonly (FlowStage | StageTiming)[] | null | undefined,
): FlowNode | null {
  const { nodes } = stageFlow(asFlow(rows));
  const flat: FlowNode[] = [];
  for (const node of nodes) {
    flat.push(node);
    flat.push(...node.children);
  }
  const settled = flat.filter((s) => s.status !== "skipped" && !s.running);
  if (settled.length === 0) return null;
  return settled.reduce((best, s) => (s.ms > best.ms ? s : best));
}
