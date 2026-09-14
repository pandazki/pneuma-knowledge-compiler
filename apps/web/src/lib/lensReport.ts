/**
 * The two model-free readings the service derives over the whole canonical library, as the
 * console receives them (docs/design/structure-lens.md §5).
 *
 * They are different instruments and the design keeps them apart, so this module keeps them
 * apart too. **The check** (`GET /review`, §3) is the insider's list: page-level findings a
 * Steward can repair in a round of its own, each with its evidence, what it costs and the
 * verb that fixes it. **The lens** (`GET /lens`, §4) is the god's-eye: six dimensions, each
 * with a band, a statement, a direction and a few metrics carrying their movement since the
 * previous reading. A finding belongs to the lowest tier that can see it, so the lens lists
 * no findings at all and the check reads no dimension.
 *
 * Three things this module is careful about, because both readings cross a wire:
 *
 * 1. EVERY FIELD DEGRADES. A report missing `findings`, a finding missing `evidence`, a band
 *    or dimension id the client has never heard of — none of those may blank the page.
 *    Unknown strings survive as themselves and are rendered as themselves.
 * 2. THE SENTENCES ARE THE CATALOGUE'S, not the console's. The service sends each `impact`,
 *    `action`, `statement` and `direction` already rendered in both packs (`text.en`,
 *    `text.zh`, §5.2) beside the key and fields it came from. The console picks its locale's
 *    and keeps NO copy: one wording, every face — so an application that rewords a key
 *    through the overlay seam changes what the console shows too, without a release.
 * 3. NOTHING IS RE-DERIVED HERE. No band, no threshold, no score (the score of the old view
 *    is gone, §4.3). The console parses, orders and renders; the numbers are the numbers
 *    `pkc lens` and `pkc library review` print.
 *
 * Runtime-import-free by design, so it transpiles standalone for its test, and — apart from
 * the reader's locale — language-free: it returns keys and numbers, the view owns the words.
 */
import type { Locale } from "./i18n";

/* ------------------------------------------------------------------ shared shapes */

/**
 * One sentence from the prompt catalogue: the key and fields it was rendered from, and the
 * rendering itself in both packs. `text` is what a reader sees; `key` and `fields` are what
 * a degraded reading still has to say something with.
 */
export interface CatalogText {
  key: string;
  fields: Record<string, string | number>;
  text: { en: string; zh: string };
}

/**
 * A catalogue sentence, in the reader's language.
 *
 * Two fallbacks, in order, so a reading from an older or degraded service never renders a
 * blank line: the other language, then the key with its fields spelled out.
 */
export function catalogText(locale: Locale, sentence: CatalogText): string {
  const { en, zh } = sentence.text;
  const mine = locale === "zh" ? zh : en;
  const other = locale === "zh" ? en : zh;
  if (mine) return mine;
  if (other) return other;
  if (!sentence.key) return "";
  const fields = Object.entries(sentence.fields)
    .map(([name, value]) => `${name}=${value}`)
    .join(" · ");
  return fields ? `${sentence.key} · ${fields}` : sentence.key;
}

/* --------------------------------------------------------------- tier two: the check */

/**
 * What kind of fault a finding is. `legacy` is an instance of a tier-one fault written
 * before the hook that now refuses it; `judgement` is a contract expectation no hook can
 * decide (§3.1). Widened, so a kind this build has never heard of renders rather than
 * disappears.
 */
export type CheckKind = "judgement" | "legacy" | string;

export interface CheckFinding {
  /** stable id: `<id>:<path or scope>:<evidence hash>` — same evidence, same key */
  key: string;
  /** the check id (§3.1), e.g. `nav.hub_incomplete`, or the legacy id of a tier-one fault */
  id: string;
  kind: CheckKind;
  /** the pages it is about (open-page paths; a volume is named by its page) */
  paths: string[];
  /** the other paths involved: missing link targets, the twin page, … */
  targets: string[];
  /** verbatim strings from the library only — a path, a title, a heading, a date, an href */
  evidence: string[];
  impact: CatalogText;
  /** names the repairing verb when there is one */
  action: CatalogText;
}

export interface CheckReport {
  /** the canonical ref the report was read at */
  ref: string;
  read_at: string;
  subjects: number;
  files: number;
  claims: number;
  edges: number;
  findings: CheckFinding[];
}

/* ------------------------------------------------------------- tier three: the lens */

/** The six dimensions of §4.2, widened for the same reason every other id is. */
export type LensDimensionId =
  | "walkability"
  | "shape"
  | "knowledge_vs_log"
  | "liveness"
  | "type_structure"
  | "demand_supply"
  | string;

/** The order the lens is read in — §4.2's table, top to bottom. */
export const LENS_DIMENSIONS: readonly LensDimensionId[] = [
  "walkability",
  "shape",
  "knowledge_vs_log",
  "liveness",
  "type_structure",
  "demand_supply",
];

/**
 * One metric and its movement. `previous` and `delta` are null when the reading has no
 * previous reading to stand against — which is the ordinary state of a library's first
 * lens, not an error.
 */
export interface LensMetric {
  name: string;
  value: number | null;
  previous: number | null;
  delta: number | null;
}

export interface LensDimension {
  id: LensDimensionId;
  /** the band id chosen by the lens's own named thresholds; never recomputed here */
  band: string;
  statement: CatalogText;
  direction: CatalogText;
  metrics: LensMetric[];
  /** verbatim strings: the lead subject's path, an island's directory, … */
  evidence: string[];
}

export interface LensReading {
  ref: string;
  read_at: string;
  /** the ref the movement is measured against; null when there was none to read */
  previous_ref: string | null;
  subjects: number;
  files: number;
  claims: number;
  edges: number;
  dimensions: LensDimension[];
}

/* ------------------------------------------------------------------------ parsing */

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** A number that is allowed to be absent — a metric with no previous reading behind it. */
function numOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * A catalogue sentence. A field that is neither a string nor a finite number (an array of
 * paths, say) is flattened rather than dropped: the fields are what the last-resort rendering
 * has to work with, and `[object Object]` in it is worse than the list spelled out.
 */
function text(value: unknown): CatalogText {
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

function checkFinding(value: unknown): CheckFinding {
  const raw = (value ?? {}) as Record<string, unknown>;
  return {
    key: str(raw.key),
    id: str(raw.id),
    kind: str(raw.kind),
    paths: strings(raw.paths),
    targets: strings(raw.targets),
    evidence: strings(raw.evidence),
    impact: text(raw.impact),
    action: text(raw.action),
  };
}

/** The check's wire shape, made safe to render. Every absent field becomes its empty reading. */
export function parseCheckReport(value: unknown): CheckReport {
  const raw = (value ?? {}) as Record<string, unknown>;
  return {
    ref: str(raw.ref),
    read_at: str(raw.read_at),
    subjects: num(raw.subjects),
    files: num(raw.files),
    claims: num(raw.claims),
    edges: num(raw.edges),
    findings: Array.isArray(raw.findings) ? raw.findings.map(checkFinding) : [],
  };
}

/**
 * One metric. `delta` is the service's when it sent one, and otherwise the subtraction the
 * two numbers already imply — a reading that carries `previous` but no `delta` should not
 * render a movement column of dashes beside two numbers that plainly moved.
 */
function metric(value: unknown): LensMetric {
  const raw = (value ?? {}) as Record<string, unknown>;
  const current = numOrNull(raw.value);
  const previous = numOrNull(raw.previous);
  const given = numOrNull(raw.delta);
  return {
    name: str(raw.name),
    value: current,
    previous,
    delta: given ?? (current != null && previous != null ? current - previous : null),
  };
}

function dimension(value: unknown): LensDimension {
  const raw = (value ?? {}) as Record<string, unknown>;
  return {
    id: str(raw.id),
    band: str(raw.band),
    statement: text(raw.statement),
    direction: text(raw.direction),
    metrics: Array.isArray(raw.metrics) ? raw.metrics.map(metric) : [],
    evidence: strings(raw.evidence),
  };
}

/** The lens's wire shape, made safe to render. */
export function parseLensReading(value: unknown): LensReading {
  const raw = (value ?? {}) as Record<string, unknown>;
  return {
    ref: str(raw.ref),
    read_at: str(raw.read_at),
    previous_ref: typeof raw.previous_ref === "string" && raw.previous_ref ? raw.previous_ref : null,
    subjects: num(raw.subjects),
    files: num(raw.files),
    claims: num(raw.claims),
    edges: num(raw.edges),
    dimensions: Array.isArray(raw.dimensions) ? raw.dimensions.map(dimension) : [],
  };
}

/* ----------------------------------------------------------------------- ordering */

export interface CheckPage {
  /** the page the findings are about; empty when a finding names no page at all */
  path: string;
  findings: CheckFinding[];
}

/**
 * The check's findings grouped under the page they are about (§3.3).
 *
 * A finding is filed under its FIRST path, which is the page the Steward opens to repair it;
 * the rest of its paths stay on the row as the pages it also touches. A finding that names no
 * page at all — a library-wide reading — keeps a group of its own under the empty path rather
 * than being dropped.
 *
 * Order is the report's own, twice over: the pages appear in the order the report first names
 * them, and within a page the findings keep their given order — which is already legacy
 * before judgement, then by id and path (§5.1). A second opinion here would be the console
 * computing something, and the console computes nothing about this reading.
 */
export function groupByPage(findings: readonly CheckFinding[]): CheckPage[] {
  const pages = new Map<string, CheckFinding[]>();
  for (const item of findings) {
    const path = item.paths[0] ?? "";
    const bucket = pages.get(path);
    if (bucket) bucket.push(item);
    else pages.set(path, [item]);
  }
  return [...pages].map(([path, list]) => ({ path, findings: list }));
}

/** How many findings of each kind the report holds, for the header (§3.3). */
export function countByKind(findings: readonly CheckFinding[]): Record<CheckKind, number> {
  const counts: Record<string, number> = {};
  for (const item of findings) counts[item.kind] = (counts[item.kind] ?? 0) + 1;
  return counts;
}

/**
 * The six dimensions in §4.2's order, with any dimension this build has never heard of kept
 * at the end rather than silently dropped, and a dimension the service did not send simply
 * absent — the console renders what came, never a placeholder for what did not.
 */
export function orderDimensions(dimensions: readonly LensDimension[]): LensDimension[] {
  const rank = new Map(LENS_DIMENSIONS.map((id, i) => [id, i]));
  return [...dimensions].sort((a, b) => {
    const ra = rank.get(a.id) ?? LENS_DIMENSIONS.length;
    const rb = rank.get(b.id) ?? LENS_DIMENSIONS.length;
    return ra === rb ? 0 : ra - rb;
  });
}

/**
 * Whether a metric's number is a 0–1 share and should be read as a percentage.
 *
 * The suffix is the contract, not a guess about the value: the lens names every share metric
 * `*_share` or `*_coverage`, so `0.50` under "dead-end share" can be shown as the 50 % it is
 * without the console ever inferring units from a number's magnitude. A metric that is not
 * named that way stays literal, whatever its size.
 */
export function isShareMetric(name: string): boolean {
  return /_(share|coverage)$/.test(name);
}

/* -------------------------------------------------------------- the previous reading */

/**
 * The picker value that asks for no particular previous ref.
 *
 * It is not "no comparison": with the parameter omitted the service reads HEAD's parent
 * itself (§4.3). The console deliberately does not compute that parent — if it did, the
 * console and `pkc lens` could disagree about what "previous" means on a library whose HEAD
 * has two of them.
 */
export const PREVIOUS_AUTO = "__auto__";

/** What to put in `previous=`, or null to leave the parameter off and let the service choose. */
export function previousParam(choice: string): string | null {
  return choice === PREVIOUS_AUTO || !choice ? null : choice;
}
