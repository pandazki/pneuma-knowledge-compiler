/**
 * The structure lens's report, as the console receives it.
 *
 * `GET /v1/users/{uid}/lens?at=<ref>` returns a reading of the whole canonical library taken
 * from OUTSIDE it (docs/design/structure-lens.md §3): base counts, a score, and findings —
 * each one addressed to somebody, carrying its evidence, what it costs and what to do. The
 * console computes nothing of its own here; it parses, groups and renders.
 *
 * Three things this module is careful about, because the report crosses a wire:
 *
 * 1. EVERY FIELD DEGRADES. A report missing `families`, a finding missing `evidence`, a level
 *    or actor the client has never heard of — none of those may blank the page. Unknown level
 *    and actor strings survive as themselves and are rendered as themselves.
 * 2. IMPACT AND ACTION ARE CATALOGUE KEYS, not sentences. The service sends
 *    `{key, fields}` (`lens.<lens id>.impact`), and the console renders the SAME keys through
 *    its own bilingual table — §3.2's "keyed identically". So the fields arrive as data and
 *    the wording stays the console's.
 * 3. `decision` IS RESERVED. This version's lens is a pure reading face: nothing in the
 *    console pushes a finding at the Steward and no decline exists to record, so the field is
 *    typed and always null (§9). The one defensive branch that renders it costs a line.
 *
 * Import-free by design, so it transpiles standalone for its test, and language-free: it
 * returns keys and numbers, the view owns every word.
 */

/** §3.1 — the three levels, widened so an unknown one renders rather than disappears. */
export type LensLevel = "principle" | "drift" | "shape" | string;

/** Who the finding is addressed to. Same widening, same reason. */
export type LensActor = "steward" | "owner" | "mechanism" | string;

/** The order the levels are read in: §3.4, principle before drift before shape. */
export const LENS_LEVELS: readonly LensLevel[] = ["principle", "drift", "shape"];

/** One rendered sentence: a prompt-catalogue key plus the fields it interpolates. */
export interface LensText {
  key: string;
  fields: Record<string, string | number>;
}

/** A kept decline, when the mechanism that records one exists (§9). Always null in v1. */
export interface LensDecision {
  reason: string;
  decided_at: string;
  ref: string;
}

export interface LensFinding {
  /** stable id: `<lens>:<path or family>:<evidence hash>` — same evidence, same key */
  key: string;
  /** the lens id (§4), e.g. `nav.dead_end` */
  lens: string;
  level: LensLevel;
  actor: LensActor;
  /** the subjects it is about (open-page paths; a volume is named by its page) */
  paths: string[];
  /** the other paths involved: missing link targets, the twin page, … */
  targets: string[];
  /** short verbatim strings or counts */
  evidence: string[];
  impact: LensText;
  action: LensText;
  /** 0–1, the share of the base it touches */
  weight: number;
  decision: LensDecision | null;
}

/** One row of the balance table (§3). */
export interface LensFamilyRow {
  name: string;
  pages: number;
  claims: number;
  share: number;
}

export interface LensReport {
  /** the canonical ref the report was read at */
  ref: string;
  read_at: string;
  subjects: number;
  files: number;
  claims: number;
  edges: number;
  /** 0–100 (§3.3): one number to watch between snapshots, not a grade */
  score: number;
  findings: LensFinding[];
  families: LensFamilyRow[];
}

/* ------------------------------------------------------------------------ parsing */

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * A catalogue reference. A field that is neither a string nor a finite number (an array of
 * paths, say) is flattened rather than dropped — the console interpolates it into a sentence,
 * and `[object Object]` in the middle of one is worse than the list spelled out.
 */
function text(value: unknown): LensText {
  const raw = (value ?? {}) as { key?: unknown; fields?: unknown };
  const fields: Record<string, string | number> = {};
  const given = (raw.fields ?? {}) as Record<string, unknown>;
  for (const [name, field] of Object.entries(given)) {
    if (typeof field === "string" || (typeof field === "number" && Number.isFinite(field))) {
      fields[name] = field;
    } else if (Array.isArray(field)) {
      fields[name] = field.map((item) => String(item)).join(", ");
    } else if (field != null) {
      fields[name] = String(field);
    }
  }
  return { key: str(raw.key), fields };
}

function decision(value: unknown): LensDecision | null {
  if (value == null || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  return {
    reason: str(raw.reason),
    decided_at: str(raw.decided_at),
    ref: str(raw.ref),
  };
}

function finding(value: unknown): LensFinding {
  const raw = (value ?? {}) as Record<string, unknown>;
  return {
    key: str(raw.key),
    lens: str(raw.lens),
    level: str(raw.level),
    actor: str(raw.actor),
    paths: strings(raw.paths),
    targets: strings(raw.targets),
    evidence: strings(raw.evidence),
    impact: text(raw.impact),
    action: text(raw.action),
    weight: num(raw.weight),
    decision: decision(raw.decision),
  };
}

/** The wire shape, made safe to render. Every absent field becomes its empty reading. */
export function parseLensReport(value: unknown): LensReport {
  const raw = (value ?? {}) as Record<string, unknown>;
  const families = Array.isArray(raw.families) ? raw.families : [];
  return {
    ref: str(raw.ref),
    read_at: str(raw.read_at),
    subjects: num(raw.subjects),
    files: num(raw.files),
    claims: num(raw.claims),
    edges: num(raw.edges),
    score: num(raw.score),
    findings: Array.isArray(raw.findings) ? raw.findings.map(finding) : [],
    families: families.map((row) => {
      const family = (row ?? {}) as Record<string, unknown>;
      return {
        name: str(family.name),
        pages: num(family.pages),
        claims: num(family.claims),
        share: num(family.share),
      };
    }),
  };
}

/* ----------------------------------------------------------------------- grouping */

export interface LensGroup {
  level: LensLevel;
  findings: LensFinding[];
}

/**
 * The findings by level, in §3.4's order, with any level the client has never heard of kept
 * at the end rather than silently dropped. Order WITHIN a level is the report's own — the
 * service already sorted by weight, lens id and path, and a second opinion here would be the
 * console computing something.
 */
export function groupByLevel(findings: readonly LensFinding[]): LensGroup[] {
  const groups = new Map<LensLevel, LensFinding[]>();
  for (const level of LENS_LEVELS) groups.set(level, []);
  for (const item of findings) {
    const bucket = groups.get(item.level);
    if (bucket) bucket.push(item);
    else groups.set(item.level, [item]);
  }
  return [...groups].map(([level, list]) => ({ level, findings: list }));
}

/** The headline: the first `count` findings as the report ordered them (§3.4). */
export function headline(findings: readonly LensFinding[], count = 3): LensFinding[] {
  return findings.slice(0, count);
}

/* ------------------------------------------------------------------ two snapshots */

export interface LensCountDelta {
  metric: "score" | "subjects" | "files" | "claims" | "edges";
  before: number;
  after: number;
  delta: number;
}

const DELTA_METRICS: LensCountDelta["metric"][] = [
  "score",
  "subjects",
  "files",
  "claims",
  "edges",
];

export interface LensComparison {
  counts: LensCountDelta[];
  /** open before, gone after — the round answered them */
  resolved: LensFinding[];
  /** absent before, open after */
  added: LensFinding[];
  /** the same key on both sides: nothing moved */
  stillOpen: LensFinding[];
}

/**
 * Two reports, subtracted.
 *
 * Findings are matched by KEY, which hashes the evidence (§3): a page that still holds the
 * same fault keeps its key and reads as still open, and a page whose fault changed shape
 * reports the old key resolved and a new one added — which is the honest reading, because the
 * question being asked about it is now a different question.
 */
export function compareReports(before: LensReport, after: LensReport): LensComparison {
  const beforeKeys = new Map(before.findings.map((f) => [f.key, f]));
  const afterKeys = new Set(after.findings.map((f) => f.key));
  return {
    counts: DELTA_METRICS.map((metric) => ({
      metric,
      before: before[metric],
      after: after[metric],
      delta: after[metric] - before[metric],
    })),
    resolved: before.findings.filter((f) => !afterKeys.has(f.key)),
    added: after.findings.filter((f) => !beforeKeys.has(f.key)),
    stillOpen: after.findings.filter((f) => beforeKeys.has(f.key)),
  };
}
