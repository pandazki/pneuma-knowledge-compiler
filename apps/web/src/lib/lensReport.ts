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
 * 2. THE SENTENCES ARE THE CATALOG'S, not the console's. The service sends each `impact` and
 *    `action` already rendered in both packs (`text.en`, `text.zh`) beside the key and fields
 *    it came from (§3.2). The console picks its locale's and keeps NO copy: one catalog, one
 *    wording, every face — so an application that rewords a key through the overlay seam
 *    changes what the console shows too, without a release.
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

/**
 * One sentence from the prompt catalog: the key and fields it was rendered from, and the
 * rendering itself in both packs. `text` is what a reader sees; `key` and `fields` are what
 * a degraded report still has to say something with.
 */
export interface LensText {
  key: string;
  fields: Record<string, string | number>;
  text: { en: string; zh: string };
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
 * A catalog sentence. A field that is neither a string nor a finite number (an array of
 * paths, say) is flattened rather than dropped: the fields are what the last-resort rendering
 * has to work with, and `[object Object]` in it is worse than the list spelled out.
 */
function text(value: unknown): LensText {
  const raw = (value ?? {}) as { key?: unknown; fields?: unknown; text?: unknown };
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
  const rendered = (raw.text ?? {}) as Record<string, unknown>;
  return {
    key: str(raw.key),
    fields,
    text: { en: str(rendered.en), zh: str(rendered.zh) },
  };
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

/**
 * The headline: the first finding of each of the `count` highest-ranked LENSES (§3.4).
 *
 * One per lens id, in report order. The first three findings outright would be the wrong
 * three whenever one lens fires repeatedly — a library with three islands led with three
 * identical island sentences and pushed the duplicated subject and the malformed page off
 * the list entirely. "Three things to do first" has to mean three different things.
 */
export function headline(findings: readonly LensFinding[], count = 3): LensFinding[] {
  const seen = new Set<string>();
  const out: LensFinding[] = [];
  for (const finding of findings) {
    if (seen.has(finding.lens)) continue;
    seen.add(finding.lens);
    out.push(finding);
    if (out.length === count) break;
  }
  return out;
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
