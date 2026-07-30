/**
 * Evolve's derivation logic (pure functions) — the data transforms shared by the three
 * surfaces: the evolution timeline, the task detail, and the schema axis. The views only
 * present; every judgement and derivation happens here, which is what makes `node --test`
 * cover it directly.
 *
 * There are only two endpoints behind all of it (no new persistence):
 *   `GET /v1/users/{u}/evolve` (task summaries) and `GET /v1/users/{u}/skill` (current skill).
 * The schema axis is not a third store — it is what you get from "the adopted task sequence
 * × the current skill". Whatever cannot be derived (a family some adopted task added but the
 * current skill no longer declares, say) is reported as drift: never invented, never
 * swallowed.
 *
 * Every import must be `import type`: the test esbuilds this file on its own into a data: URL
 * module, where no runtime import would resolve. That is also why the wording lives in the
 * dictionary and this module returns message KEYS — see `EVOLVE_STATUS_LABEL_KEY`,
 * `ttlRemainingMessage`, `SchemaStation.labelKey`.
 */
import type {
  EvolveStatus,
  EvolveSummary,
  EvolveTaskSummary,
  SkillInfo,
  SkillPack,
} from "./api";
import type { MessageKey, MessageParams } from "./i18n";

/**
 * A piece of copy this module picks but does not render: a declared dictionary key plus its
 * placeholder values. The caller does `t(msg.key, msg.params)`.
 */
export interface EvolveMessage {
  key: MessageKey;
  params?: MessageParams;
}

/* --------------------------------------------------------------- status semantics */

/** Terminal: settled for good, so no polling needed. */
const TERMINAL_STATUSES: readonly string[] = [
  "adopted",
  "dropped",
  "expired",
  "aborted",
  "no_change",
];

/** The closed status vocabulary, as dictionary keys. */
export const EVOLVE_STATUS_LABEL_KEY: Record<string, MessageKey> = {
  draft: "evolve.status.draft",
  adopted: "evolve.status.adopted",
  dropped: "evolve.status.dropped",
  expired: "evolve.status.expired",
  aborted: "evolve.status.aborted",
  no_change: "evolve.status.no_change",
};

export type EvolveStatusTone = "neutral" | "accent" | "ok" | "warn" | "danger";

/** Semantic colour only for real states (DESIGN.md §6.4): awaiting review = warn, adopted = ok, aborted = danger, everything else neutral. */
export function evolveStatusTone(status: string): EvolveStatusTone {
  switch (status) {
    case "draft":
      return "warn";
    case "adopted":
      return "ok";
    case "aborted":
      return "danger";
    default:
      return "neutral";
  }
}

/**
 * The dictionary key for a status. A status the client does not know yet yields an
 * undeclared key on purpose, so `tOr(key, status)` renders the raw status rather than a
 * blank — the same graceful degradation the backend's other closed vocabularies get.
 */
export function evolveStatusLabelKey(status: string): string {
  return EVOLVE_STATUS_LABEL_KEY[status] ?? `evolve.status.${status}`;
}

export function isTerminalEvolveStatus(status: string): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/**
 * Milliseconds left in a draft's review window (created_at + TTL − now). Purely advisory:
 * the service's lazy expiry sweep is the authority. `null` means there is nothing to compute
 * from (no created_at, or an unparseable timestamp).
 */
export function ttlRemainingMs(
  createdAt: string | null | undefined,
  ttlHours: number,
  now: number = Date.now(),
): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt).getTime();
  if (Number.isNaN(created)) return null;
  return created + ttlHours * 3600_000 - now;
}

/** The countdown as a message the view renders; the hour part is dropped below one hour. */
export function ttlRemainingMessage(ms: number): EvolveMessage {
  if (ms <= 0) return { key: "evolve.ttl.expired" };
  const h = Math.floor(ms / 3600_000);
  const m = Math.floor((ms % 3600_000) / 60_000);
  return h > 0
    ? { key: "evolve.ttl.hoursMinutes", params: { h, m } }
    : { key: "evolve.ttl.minutes", params: { m } };
}

/* --------------------------------------------------- path template → family */

/**
 * The archive family name: the last non-placeholder segment of a path template.
 * `memory/people/{slug}.md` → `people`; `memory/profile.md` → `profile`;
 * `materials/{slug}.md` → `materials`. When nothing can be taken, fall back to the whole
 * template (no guessing).
 */
export function familyFromTemplate(template: string): string {
  const segs = template
    .split("/")
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.includes("{slug}"));
  const last = segs[segs.length - 1];
  if (!last) return template.trim();
  return last.replace(/\.md$/i, "");
}

/** The archive area: the template's first segment (`memory` / `work` / `materials` / a new top-level directory a pack brings). */
export function areaFromTemplate(template: string): string {
  const first = template.split("/")[0]?.trim();
  return first && !first.includes("{slug}") ? first.replace(/\.md$/i, "") : "—";
}

/* ------------------------------------------------------------------- timeline */

export interface EvolveScale {
  newDocuments: number;
  movedClaims: number;
  mergedClaims: number;
  /** How many documents took claims in (the key count of summary.adopted_by_document). */
  adoptedDocuments: number;
  /** Total scale: moved + merged — one number for "how many claims this touched". */
  touchedClaims: number;
}

export const EMPTY_SCALE: EvolveScale = {
  newDocuments: 0,
  movedClaims: 0,
  mergedClaims: 0,
  adoptedDocuments: 0,
  touchedClaims: 0,
};

function int(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** The mechanical scale summary (a task without a summary reads all zeros — nothing faked). */
export function evolveScale(summary: EvolveSummary | null | undefined): EvolveScale {
  if (!summary) return { ...EMPTY_SCALE };
  const moved = int(summary.moved_claims);
  const merged = int(summary.merged_claims);
  return {
    newDocuments: int(summary.new_documents),
    movedClaims: moved,
    mergedClaims: merged,
    adoptedDocuments: Object.keys(summary.adopted_by_document ?? {}).length,
    touchedClaims: moved + merged,
  };
}

export interface EvolveTimelineEntry {
  task: EvolveTaskSummary;
  taskId: string;
  status: EvolveStatus;
  /** Chronological index (earliest = 1): the "nth evolution". */
  ordinal: number;
  createdAt: string | null;
  decidedAt: string | null;
  /** Epoch ms for sorting; null when the timestamp is missing or unparseable (those entries sort last). */
  sortKey: number | null;
  /** The archive families this proposal adds. */
  families: string[];
  /** The path templates this proposal adds. */
  pathTemplates: string[];
  scale: EvolveScale;
  /** Non-terminal: still running, or parked at the gate waiting for a person. */
  pending: boolean;
  /** Parked at the gate awaiting a human decision (adoptable / droppable). */
  awaitingReview: boolean;
}

/**
 * The families a proposal adds. Prefer the service's derived `families` field; fall back to
 * reverse-deriving them from `path_templates` for an older service that does not send it;
 * with neither, the answer is empty (degrade gracefully, never guess).
 */
export function proposedFamilies(task: EvolveTaskSummary): string[] {
  const declared = Array.isArray(task.families) ? task.families : null;
  if (declared && declared.length > 0) {
    return dedupe(declared.map((f) => String(f).trim()).filter(Boolean));
  }
  return dedupe(proposedTemplates(task).map(familyFromTemplate));
}

export function proposedTemplates(task: EvolveTaskSummary): string[] {
  const declared = Array.isArray(task.path_templates) ? task.path_templates : null;
  if (!declared) return [];
  return dedupe(declared.map((t) => String(t).trim()).filter(Boolean));
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    if (v && !seen.has(v)) {
      seen.add(v);
      out.push(v);
    }
  }
  return out;
}

function epoch(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = new Date(ts).getTime();
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Task summaries → timeline entries, **newest first** (the service already returns created_at
 * DESC; sorting explicitly here keeps the order independent of the endpoint). `ordinal` counts
 * forward in time, so one evolution carries the same number on the timeline and on the schema
 * axis. Entries without a timestamp sort last and take the largest ordinal — they are not
 * pretended to be the oldest.
 */
export function buildEvolveTimeline(
  tasks: readonly EvolveTaskSummary[],
): EvolveTimelineEntry[] {
  const rows = tasks.map((task) => ({
    task,
    sortKey: epoch(task.created_at),
  }));
  // Chronological (undated last), then by task_id, so rendering is stable.
  const ascending = [...rows].sort((a, b) => {
    if (a.sortKey == null && b.sortKey == null)
      return a.task.task_id.localeCompare(b.task.task_id);
    if (a.sortKey == null) return 1;
    if (b.sortKey == null) return -1;
    if (a.sortKey !== b.sortKey) return a.sortKey - b.sortKey;
    return a.task.task_id.localeCompare(b.task.task_id);
  });

  const entries = ascending.map((row, index): EvolveTimelineEntry => {
    const status = row.task.status;
    return {
      task: row.task,
      taskId: row.task.task_id,
      status,
      ordinal: index + 1,
      createdAt: row.task.created_at ?? null,
      decidedAt: row.task.decided_at ?? null,
      sortKey: row.sortKey,
      families: proposedFamilies(row.task),
      pathTemplates: proposedTemplates(row.task),
      scale: evolveScale(row.task.summary),
      pending: !isTerminalEvolveStatus(status),
      awaitingReview: status === "draft",
    };
  });

  return entries.reverse();
}

export interface EvolveTimelineCounts {
  total: number;
  awaitingReview: number;
  adopted: number;
  /** Dropped + expired + aborted: turned down by a person or by the system. */
  declined: number;
  noChange: number;
}

export function evolveTimelineCounts(
  entries: readonly EvolveTimelineEntry[],
): EvolveTimelineCounts {
  let awaitingReview = 0;
  let adopted = 0;
  let declined = 0;
  let noChange = 0;
  for (const e of entries) {
    if (e.awaitingReview) awaitingReview += 1;
    else if (e.status === "adopted") adopted += 1;
    else if (e.status === "no_change") noChange += 1;
    else if (e.status === "dropped" || e.status === "expired" || e.status === "aborted")
      declined += 1;
  }
  return { total: entries.length, awaitingReview, adopted, declined, noChange };
}

/** Resolve the selection: an id absent from the current list falls back to null (never point at a task that is not there). */
export function selectedTimelineEntry(
  entries: readonly EvolveTimelineEntry[],
  taskId: string | null | undefined,
): EvolveTimelineEntry | null {
  if (!taskId) return null;
  return entries.find((e) => e.taskId === taskId) ?? null;
}

/* --------------------------------------------------------------- pack drafts */

export interface EvolvePackDraft {
  packId: string | null;
  /** The family name: pack_id minus its `evolved-` prefix, or reverse-derived from the template. */
  family: string;
  origin: string | null;
  /** The instructions the pack appends, in full — the body a person reviews. */
  instructions: string;
  pathTemplates: string[];
  contractRules: string[];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => str(v).trim()).filter(Boolean);
}

/**
 * The stored proposal (`EvolveProposal.model_dump()`: `{packs, rationale}`) → a list of pack
 * drafts. Tolerant about shape: a malformed structure degrades to an empty list, never throws.
 */
export function buildPackDrafts(
  proposal: Record<string, unknown> | null | undefined,
): EvolvePackDraft[] {
  if (!proposal || typeof proposal !== "object") return [];
  const packs = (proposal as { packs?: unknown }).packs;
  if (!Array.isArray(packs)) return [];
  return packs
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
    .map((p) => {
      const packId = str(p.pack_id).trim() || null;
      const templates = strList(p.extra_path_templates);
      const fromId = packId ? packId.replace(/^evolved-/, "") : "";
      return {
        packId,
        family: fromId || (templates[0] ? familyFromTemplate(templates[0]) : "—"),
        origin: str(p.origin).trim() || null,
        instructions: str(p.extra_instructions).trim(),
        pathTemplates: templates,
        contractRules: strList(p.extra_contract_rules),
      };
    });
}

export interface EvolveRationale {
  /** The proposal's own statement (the overall reasoning the strong model gave). */
  lead: string;
  /** Evidence lines: in phase 1 each family appends one line pointing at a concrete cluster in the increment. */
  evidence: string[];
}

/**
 * Split the rationale text block. propose.py assembles it as
 * `rationale + "\n\n" + one evidence line per family`, so at most the last `packCount`
 * non-empty lines are evidence and the rest is the overall reasoning. A mis-cut loses nothing:
 * both halves render.
 */
export function parseRationale(
  rationale: string | null | undefined,
  packCount: number,
): EvolveRationale {
  const lines = str(rationale)
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length === 0) return { lead: "", evidence: [] };
  if (packCount <= 0) return { lead: lines.join("\n"), evidence: [] };
  const take = Math.min(packCount, lines.length);
  const evidence = lines.slice(lines.length - take);
  const lead = lines.slice(0, lines.length - take).join("\n");
  return { lead, evidence };
}

/* --------------------------------------------------------------- inline diff */

export type DiffRowType = "same" | "add" | "del";
export interface DiffRow {
  type: DiffRowType;
  text: string;
}

/** A minimal LCS line diff: one unified +/− stream (rendered in ink tones — no coloured diff). */
export function lineDiff(oldStr: string, newStr: string): DiffRow[] {
  const A = oldStr.split("\n");
  const B = newStr.split("\n");
  const n = A.length;
  const m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      rows.push({ type: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "del", text: A[i++] });
    } else {
      rows.push({ type: "add", text: B[j++] });
    }
  }
  while (i < n) rows.push({ type: "del", text: A[i++] });
  while (j < m) rows.push({ type: "add", text: B[j++] });
  return rows;
}

export interface DiffStat {
  adds: number;
  dels: number;
}

export function diffStat(rows: readonly DiffRow[]): DiffStat {
  let adds = 0;
  let dels = 0;
  for (const r of rows) {
    if (r.type === "add") adds += 1;
    else if (r.type === "del") dels += 1;
  }
  return { adds, dels };
}

/** The kind of a file-level change (an empty old/new body means created/deleted — that is how the service expresses it). */
export type ChangedFileKind = "created" | "deleted" | "modified";

export function changedFileKind(oldBody: string, newBody: string): ChangedFileKind {
  if (oldBody === "" && newBody !== "") return "created";
  if (newBody === "" && oldBody !== "") return "deleted";
  return "modified";
}

/* ------------------------------------------------------------- schema axis */

export type FamilyOrigin = "base" | "pack" | "evolved";

export interface SchemaFamily {
  family: string;
  area: string;
  template: string;
  origin: FamilyOrigin;
  /** Which adopted evolution added it (only possible when origin === "evolved"). */
  addedByTask: string | null;
  addedAtOrdinal: number | null;
  addedAt: string | null;
  /** The registration-time pack it came with (matrix / derived). */
  packId: string | null;
}

export type SchemaStationKind = "base" | "pack" | "adopted" | "pending";

export interface SchemaStation {
  kind: SchemaStationKind;
  /** base → base_version; pack → "packs"; adopted / pending → task_id. */
  id: string;
  /** The station's caption, as a dictionary key the view renders with `labelParams`. */
  labelKey: MessageKey;
  labelParams?: MessageParams;
  /** The number shared with the timeline; null for the base / pack stations. */
  ordinal: number | null;
  at: string | null;
  families: string[];
  templates: string[];
  /** Adopted stations: the families still declared by the current skill. */
  liveFamilies: string[];
  /** Adopted stations: the families the current skill no longer declares (drift, shown as it is). */
  driftedFamilies: string[];
  status: EvolveStatus | null;
}

export interface SchemaAxis {
  stations: SchemaStation[];
  /** The full current family roster (every path_template of the current skill, parsed). */
  families: SchemaFamily[];
  baseVersion: string | null;
  skillVersion: string | null;
  contentHash: string | null;
  /** Families that were adopted once but are no longer in the current skill. */
  drifted: string[];
  /** Families still at the gate, not yet part of the schema. */
  proposed: string[];
}

function packTemplates(packs: readonly SkillPack[], evolved: boolean): Map<string, string> {
  const out = new Map<string, string>();
  for (const pack of packs) {
    const isEvolved = pack.origin === "evolved";
    if (isEvolved !== evolved) continue;
    for (const template of pack.extra_path_templates ?? []) {
      const t = String(template).trim();
      if (t) out.set(t, pack.pack_id ?? "");
    }
  }
  return out;
}

/**
 * "The adopted task sequence × the current skill" → the schema axis.
 *
 * - Station order: the baseline skill → the registration-time packs (only when there are any)
 *   → every adopted evolution (chronologically) → the drafts still at the gate (not part of
 *   the schema yet, marked out separately).
 * - The family roster comes entirely from the current skill's path_templates; origin
 *   attribution (base / pack / evolved + which task) falls out of comparing template sets.
 * - A family an adopted station claimed but the current skill does not declare is recorded as
 *   drift rather than silently dropped.
 */
export function buildSchemaAxis(
  tasks: readonly EvolveTaskSummary[],
  skill: SkillInfo | null | undefined,
): SchemaAxis {
  const entries = buildEvolveTimeline(tasks);
  const chronological = [...entries].reverse(); // oldest first

  const skillTemplates = dedupe((skill?.path_templates ?? []).map((t) => String(t).trim()));
  const packs = skill?.packs ?? [];
  const evolvedTemplates = packTemplates(packs, true);
  const registrationTemplates = packTemplates(packs, false);

  /** family → the template in the current skill that carries it. */
  const currentByFamily = new Map<string, string>();
  for (const template of skillTemplates) {
    const family = familyFromTemplate(template);
    if (!currentByFamily.has(family)) currentByFamily.set(family, template);
  }

  const adopted = chronological.filter((e) => e.status === "adopted");
  const awaiting = chronological.filter((e) => e.awaitingReview);

  /** family → the adopted evolution that added it (a later one overrides an earlier). */
  const addedBy = new Map<string, EvolveTimelineEntry>();
  for (const entry of adopted) {
    for (const family of entry.families) addedBy.set(family, entry);
  }

  const families: SchemaFamily[] = skillTemplates.map((template) => {
    const family = familyFromTemplate(template);
    const origin: FamilyOrigin = evolvedTemplates.has(template)
      ? "evolved"
      : registrationTemplates.has(template)
        ? "pack"
        : "base";
    const owner = origin === "evolved" ? (addedBy.get(family) ?? null) : null;
    return {
      family,
      area: areaFromTemplate(template),
      template,
      origin,
      addedByTask: owner?.taskId ?? null,
      addedAtOrdinal: owner?.ordinal ?? null,
      addedAt: owner?.decidedAt ?? owner?.createdAt ?? null,
      packId:
        origin === "pack"
          ? registrationTemplates.get(template) || null
          : origin === "evolved"
            ? evolvedTemplates.get(template) || null
            : null,
    };
  });

  const stations: SchemaStation[] = [];

  const baseTemplates = families
    .filter((f) => f.origin === "base")
    .map((f) => f.template);
  stations.push({
    kind: "base",
    id: skill?.base_version ?? "base",
    labelKey: skill?.base_version
      ? "evolve.axis.station.baseVersion"
      : "evolve.axis.station.base",
    labelParams: skill?.base_version ? { version: skill.base_version } : undefined,
    ordinal: null,
    at: null,
    families: dedupe(families.filter((f) => f.origin === "base").map((f) => f.family)),
    templates: baseTemplates,
    liveFamilies: [],
    driftedFamilies: [],
    status: null,
  });

  const packFamilies = families.filter((f) => f.origin === "pack");
  if (packFamilies.length > 0) {
    stations.push({
      kind: "pack",
      id: "packs",
      labelKey: "evolve.axis.station.packs",
      ordinal: null,
      at: null,
      families: dedupe(packFamilies.map((f) => f.family)),
      templates: packFamilies.map((f) => f.template),
      liveFamilies: [],
      driftedFamilies: [],
      status: null,
    });
  }

  const drifted: string[] = [];
  for (const entry of adopted) {
    const live = entry.families.filter((f) => currentByFamily.has(f));
    const gone = entry.families.filter((f) => !currentByFamily.has(f));
    for (const f of gone) if (!drifted.includes(f)) drifted.push(f);
    stations.push({
      kind: "adopted",
      id: entry.taskId,
      labelKey: "evolve.evolutionOrdinal",
      labelParams: { n: entry.ordinal },
      ordinal: entry.ordinal,
      at: entry.decidedAt ?? entry.createdAt,
      families: entry.families,
      templates: entry.pathTemplates,
      liveFamilies: live,
      driftedFamilies: gone,
      status: entry.status,
    });
  }

  const proposed: string[] = [];
  for (const entry of awaiting) {
    for (const f of entry.families) if (!proposed.includes(f)) proposed.push(f);
    stations.push({
      kind: "pending",
      id: entry.taskId,
      labelKey: "evolve.axis.station.pending",
      labelParams: { n: entry.ordinal },
      ordinal: entry.ordinal,
      at: entry.createdAt,
      families: entry.families,
      templates: entry.pathTemplates,
      liveFamilies: [],
      driftedFamilies: [],
      status: entry.status,
    });
  }

  return {
    stations,
    families,
    baseVersion: skill?.base_version ?? null,
    skillVersion: skill?.version ?? null,
    contentHash: skill?.content_hash ?? null,
    drifted,
    proposed,
  };
}

/** The family roster grouped by archive area (for presentation; families sorted by name within an area). */
export function groupFamiliesByArea(
  families: readonly SchemaFamily[],
): { area: string; families: SchemaFamily[] }[] {
  const byArea = new Map<string, SchemaFamily[]>();
  for (const family of families) {
    const bucket = byArea.get(family.area);
    if (bucket) bucket.push(family);
    else byArea.set(family.area, [family]);
  }
  return [...byArea.entries()]
    .map(([area, list]) => ({
      area,
      families: [...list].sort((a, b) => a.family.localeCompare(b.family)),
    }))
    .sort((a, b) => a.area.localeCompare(b.area));
}
