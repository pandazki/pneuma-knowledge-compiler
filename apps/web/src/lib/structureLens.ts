/**
 * The structure lens: what the canonical ledger says about the SHAPE of a base.
 *
 * The relationship graph used to be a destination — a canvas you explored. At real scale that
 * canvas is a grey explosion and its right rail is a wall of ids, so nothing about the
 * structure is legible from it. This module supplies the replacement: the same edges and the
 * same claims, read as measurements (how concentrated, how connected, how balanced) and as a
 * per-document neighbourhood index.
 *
 * Two rules run through everything here:
 *
 * 1. AN EDGE IS A SENTENCE. Every link is created by one claim, and that claim is in the
 *    projection, so no edge is ever reported as a bare pair of ids — the sentence that made it
 *    travels with it.
 * 2. A ROLLOVER VOLUME IS NOT A DOCUMENT. An archive volume (`<document>/aNN.md`) is a real
 *    canonical file, but to a reader it is the back half of its owner. Claims, characters and
 *    edges are merged onto the owner; the volume is only named when a sentence physically
 *    lives in one.
 *
 * Calibration is deliberately borrowed rather than invented: template ownership mirrors
 * `compile/patch.py::path_allowed`, volume ownership mirrors
 * `compile/patch.py::history_volume_owner`, and the connectivity vocabulary
 * (arrival-blind / dead-end / isolated / orphan claim) is the eval suite's group D
 * (`pneuma_knowledge_eval/metrics/navigability.py::reachability`) so the UI and the scorecard
 * can never drift into two definitions of the same word.
 *
 * Import-free by design (the type imports are erased), so it transpiles standalone for its
 * test. Language-free too: it returns numbers and paths, the view owns every word.
 */

import type { DocumentRecord } from "./types";

/* ------------------------------------------------------------------ input shape */

/**
 * The slice of a document this module reads. A `DocumentRecord` satisfies it, and so does a
 * hand-built fixture — the lens never needs frontmatter, citations or flags.
 */
export interface LensDocument {
  document_id: string | null;
  path: string;
  title: string;
  body: string;
  claims: { anchor: string | null; text: string }[];
}

/** Widen a projection's documents to what the lens reads. */
export function lensDocuments(docs: readonly DocumentRecord[]): LensDocument[] {
  return docs.map((d) => ({
    document_id: d.document_id,
    path: d.path,
    title: d.title,
    body: d.body ?? "",
    claims: (d.claims ?? []).map((c) => ({ anchor: c.anchor, text: c.text ?? "" })),
  }));
}

/* ------------------------------------------------------- path ownership (families) */

/**
 * A slug in a path template. Character for character the grammar of
 * `compile/patch.py::_SLUG`; a looser one here would file documents into families the write
 * gate would have rejected.
 */
const SLUG = "[a-z0-9]+(?:-[a-z0-9]+)*";

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** `memory/topics/{slug}.md` → /^memory\/topics\/[a-z0-9](?:…)\.md$/ (patch.py::_template_regex). */
export function templateRegex(template: string): RegExp {
  const body = template
    .split(/(\{slug\})/)
    .map((part) => (part === "{slug}" ? SLUG : escapeRe(part)))
    .join("");
  return new RegExp(`^${body}$`);
}

/** Write ownership: does the skill declare a template this path could have been written to? */
export function pathAllowed(path: string, templates: readonly string[]): boolean {
  return templates.some((template) => templateRegex(template).test(path));
}

/** The declared family (template) owning `path`, or null — canonical_glance.py::family_of. */
export function familyOf(path: string, templates: readonly string[]): string | null {
  for (const template of templates) {
    if (templateRegex(template).test(path)) return template;
  }
  return null;
}

/* -------------------------------------------------------------- rollover volumes */

/** `a01.md`, `a02.md`, … — patch.py::_VOLUME_FILE_RE. */
const VOLUME_FILE_RE = /^a(\d{2,})\.md$/;

/**
 * The document that owns `path` as one of its rollover volumes, or null.
 *
 * `compile/patch.py::history_volume_owner` is the authority: `<owned document>/aNN.md` belongs
 * to `<owned document>.md`. There the owner is confirmed against the skill's write templates;
 * here it is confirmed against the documents the projection actually carries, which is the
 * same set in practice and is all a client holds — a volume whose owner is absent stays a
 * document of its own rather than being merged into a page nobody can open.
 */
export function volumeOwner(path: string, documentPaths: ReadonlySet<string>): string | null {
  const cut = path.lastIndexOf("/");
  if (cut <= 0) return null;
  const filename = path.slice(cut + 1);
  if (!VOLUME_FILE_RE.test(filename)) return null;
  const owner = `${path.slice(0, cut)}.md`;
  return documentPaths.has(owner) ? owner : null;
}

/* --------------------------------------------------------------------- the units */

/**
 * One SUBJECT: an owned document plus every archive volume filed under it. This — not the
 * file — is the thing a reader means by "a page", so every share below is a share of these.
 */
export interface StructureUnit {
  /** the owner document's path */
  path: string;
  documentId: string | null;
  title: string;
  /** claims on the page and in all of its volumes */
  claims: number;
  /** characters of prose on the page and in all of its volumes */
  chars: number;
  /** volume paths merged in, in path order; empty for a page that never rolled over */
  volumes: string[];
}

/** Fold each document's rollover volumes into it; everything else stands as its own unit. */
export function mergeVolumes(docs: readonly LensDocument[]): StructureUnit[] {
  const paths = new Set(docs.map((d) => d.path));
  const byPath = new Map<string, StructureUnit>();
  const order: string[] = [];
  const ensure = (doc: LensDocument, ownerPath: string): StructureUnit => {
    let unit = byPath.get(ownerPath);
    if (!unit) {
      unit = {
        path: ownerPath,
        documentId: ownerPath === doc.path ? doc.document_id : null,
        title: ownerPath === doc.path ? doc.title : ownerPath,
        claims: 0,
        chars: 0,
        volumes: [],
      };
      byPath.set(ownerPath, unit);
      order.push(ownerPath);
    }
    return unit;
  };
  // Owners first, so a unit always carries its owner's id and title even when a volume was
  // seen earlier in the list.
  for (const doc of docs) {
    if (volumeOwner(doc.path, paths)) continue;
    const unit = ensure(doc, doc.path);
    unit.claims += doc.claims.length;
    unit.chars += doc.body.length;
  }
  for (const doc of docs) {
    const owner = volumeOwner(doc.path, paths);
    if (!owner) continue;
    const unit = ensure(doc, owner);
    unit.claims += doc.claims.length;
    unit.chars += doc.body.length;
    unit.volumes.push(doc.path);
  }
  for (const unit of byPath.values()) unit.volumes.sort();
  return order.map((path) => byPath.get(path)!);
}

/* ---------------------------------------------------------------------- the links */

/** Inline markdown link. */
const MD_LINK_RE = /\[([^\]]*)\]\(([^)\s]+)\)/g;

/** Resolve `href` written inside `fromPath` against the projection's flat path space. */
export function resolvePath(fromPath: string, href: string): string {
  const base = fromPath.split("/").slice(0, -1);
  const out: string[] = href.startsWith("/") ? [] : [...base];
  for (const part of href.replace(/^\//, "").split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") out.pop();
    else out.push(part);
  }
  return out.join("/");
}

/** One claim that carries a link out of the document it sits in. */
export interface LinkSentence {
  /** the file the claim physically lives in */
  fromFile: string;
  /** the href's resolved path (may name no document — then it is a dead link) */
  toFile: string;
  anchor: string | null;
  /** the claim, as written: the whole information content of the edge */
  sentence: string;
}

/**
 * Every inter-document link in the base, each paired with the claim that wrote it.
 *
 * The grammar is the gate's (`navigability.py::_edges`): a relative `.md` href, no scheme, no
 * self-link. Reading them off `claim.text` rather than `document.body` is what makes the
 * sentence available; the two agree exactly, because a link only reaches canonical inside a
 * claim.
 */
export function deriveLinks(docs: readonly LensDocument[]): LinkSentence[] {
  const out: LinkSentence[] = [];
  for (const doc of docs) {
    for (const claim of doc.claims) {
      MD_LINK_RE.lastIndex = 0;
      let match = MD_LINK_RE.exec(claim.text);
      while (match) {
        const href = match[2];
        if (href.endsWith(".md") && !href.includes("://")) {
          const target = resolvePath(doc.path, href);
          if (target && target !== doc.path) {
            out.push({
              fromFile: doc.path,
              toFile: target,
              anchor: claim.anchor,
              sentence: claim.text,
            });
          }
        }
        match = MD_LINK_RE.exec(claim.text);
      }
    }
  }
  return out;
}

/** One line of a neighbourhood: who, and the sentence that put them there. */
export interface NeighborRow {
  /** the other unit */
  path: string;
  documentId: string | null;
  title: string;
  /** the claim that created this edge, as written */
  sentence: string;
  anchor: string | null;
  /** the archive volume the sentence lives in, when it is not the unit's own page */
  volume: string | null;
  /** further sentences joining the same pair, beyond the one shown */
  more: number;
}

export interface LinkIndex {
  units: StructureUnit[];
  unitByPath: Map<string, StructureUnit>;
  /** unit path → the subjects it links out to */
  outgoing: Map<string, NeighborRow[]>;
  /** unit path → the subjects that link in to it */
  incoming: Map<string, NeighborRow[]>;
  /** distinct unit→unit edges */
  edgeCount: number;
  /** links whose href resolves to no document in this projection (the gate should keep it 0) */
  deadLinks: LinkSentence[];
}

/**
 * The two-way neighbourhood index, built once per projection.
 *
 * Edges are merged onto units, so a link written in an archive volume counts for its owner and
 * a link between two volumes of the same subject disappears (it is one subject talking to
 * itself). Repeated links between the same pair collapse to one row: the first sentence in
 * document order, plus how many more say the same thing.
 */
export function buildLinkIndex(docs: readonly LensDocument[]): LinkIndex {
  const units = mergeVolumes(docs);
  const unitByPath = new Map(units.map((u) => [u.path, u]));
  const documentPaths = new Set(docs.map((d) => d.path));
  const ownerOf = (file: string): string | null => {
    const owner = volumeOwner(file, documentPaths);
    if (owner) return owner;
    return unitByPath.has(file) ? file : null;
  };

  const outgoing = new Map<string, NeighborRow[]>();
  const incoming = new Map<string, NeighborRow[]>();
  const deadLinks: LinkSentence[] = [];
  const seen = new Set<string>();

  for (const link of deriveLinks(docs)) {
    const fromUnit = ownerOf(link.fromFile);
    const toUnit = ownerOf(link.toFile);
    if (!toUnit || !documentPaths.has(link.toFile)) {
      deadLinks.push(link);
      continue;
    }
    if (!fromUnit || fromUnit === toUnit) continue;
    const key = `${fromUnit} ${toUnit}`;
    const source = unitByPath.get(fromUnit)!;
    const target = unitByPath.get(toUnit)!;
    if (seen.has(key)) {
      const outRows = outgoing.get(fromUnit)!;
      outRows[outRows.findIndex((r) => r.path === toUnit)].more += 1;
      const inRows = incoming.get(toUnit)!;
      inRows[inRows.findIndex((r) => r.path === fromUnit)].more += 1;
      continue;
    }
    seen.add(key);
    const volume = link.fromFile === fromUnit ? null : link.fromFile;
    push(outgoing, fromUnit, {
      path: toUnit,
      documentId: target.documentId,
      title: target.title,
      sentence: link.sentence,
      anchor: link.anchor,
      volume,
      more: 0,
    });
    push(incoming, toUnit, {
      path: fromUnit,
      documentId: source.documentId,
      title: source.title,
      sentence: link.sentence,
      anchor: link.anchor,
      volume,
      more: 0,
    });
  }

  return { units, unitByPath, outgoing, incoming, edgeCount: seen.size, deadLinks };
}

function push<T>(map: Map<string, T[]>, key: string, value: T): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

export interface Neighborhood {
  unit: StructureUnit | null;
  outgoing: NeighborRow[];
  incoming: NeighborRow[];
}

/**
 * One subject's neighbourhood. `path` may name an archive volume — a reader who opened a
 * volume still means the subject — and both directions come back sorted by title so the card
 * reads as an index rather than as insertion order.
 */
export function neighborhoodOf(index: LinkIndex, path: string): Neighborhood {
  const unit =
    index.unitByPath.get(path) ??
    index.unitByPath.get(path.slice(0, path.lastIndexOf("/")) + ".md") ??
    null;
  if (!unit) return { unit: null, outgoing: [], incoming: [] };
  const byTitle = (a: NeighborRow, b: NeighborRow) =>
    a.title.localeCompare(b.title) || a.path.localeCompare(b.path);
  return {
    unit,
    outgoing: [...(index.outgoing.get(unit.path) ?? [])].sort(byTitle),
    incoming: [...(index.incoming.get(unit.path) ?? [])].sort(byTitle),
  };
}

/* ------------------------------------------------------------------ concentration */

/** A single subject holding more than this share of all claims is worth naming. */
export const UNIT_SHARE_WARN = 0.2;
/**
 * …but only if it is also this many times an EVEN share. In a base of three subjects one of
 * them holding a third is arithmetic, not concentration; the absolute threshold alone would
 * report every young base as pathological on its first day.
 */
export const EVEN_SHARE_FACTOR = 3;
/** The biggest subject being this many times the second is worth naming. */
export const LEAD_RATIO_WARN = 4;
/** Below this many subjects, "first over second" is a coin toss rather than a cliff. */
export const MIN_SUBJECTS_FOR_RATIO = 5;

export interface ShareRow {
  path: string;
  documentId: string | null;
  title: string;
  claims: number;
  share: number;
  volumes: string[];
  overThreshold: boolean;
}

export interface Concentration {
  totalClaims: number;
  /** the heaviest subjects, largest first */
  rows: ShareRow[];
  /** everything the rows leave out, as one line; null when nothing is left out */
  tail: { units: number; claims: number; share: number } | null;
  leadShare: number;
  /** #1 ÷ #2; null when there is no second subject */
  leadRatio: number | null;
  overThreshold: boolean;
}

/** Claim share per subject, heaviest first, with the long tail kept as one honest line. */
export function concentration(units: readonly StructureUnit[], topN = 10): Concentration {
  const totalClaims = units.reduce((n, u) => n + u.claims, 0);
  const sorted = [...units].sort((a, b) => b.claims - a.claims || a.path.localeCompare(b.path));
  const share = (n: number) => (totalClaims > 0 ? n / totalClaims : 0);
  const evenShare = units.length > 0 ? 1 / units.length : 1;
  const heavy = (n: number) =>
    share(n) > UNIT_SHARE_WARN && share(n) > EVEN_SHARE_FACTOR * evenShare;
  const rows = sorted.slice(0, topN).map((u) => ({
    path: u.path,
    documentId: u.documentId,
    title: u.title,
    claims: u.claims,
    share: share(u.claims),
    volumes: u.volumes,
    overThreshold: heavy(u.claims),
  }));
  const rest = sorted.slice(topN);
  const restClaims = rest.reduce((n, u) => n + u.claims, 0);
  const leadShare = sorted.length ? share(sorted[0].claims) : 0;
  const leadRatio =
    sorted.length > 1 && sorted[1].claims > 0 ? sorted[0].claims / sorted[1].claims : null;
  return {
    totalClaims,
    rows,
    tail: rest.length ? { units: rest.length, claims: restClaims, share: share(restClaims) } : null,
    leadShare,
    leadRatio,
    overThreshold:
      (sorted.length > 0 && heavy(sorted[0].claims)) ||
      (units.length >= MIN_SUBJECTS_FOR_RATIO && (leadRatio ?? 0) > LEAD_RATIO_WARN),
  };
}

/* ------------------------------------------------------------------ family balance */

/** A family carrying this many times its page share in claims is lopsided. */
export const FAMILY_IMBALANCE_WARN = 2;

export interface FamilyRow {
  template: string;
  pages: number;
  pageShare: number;
  claims: number;
  claimShare: number;
  chars: number;
  charShare: number;
  /** claim share ÷ page share; null for a family with no pages */
  imbalance: number | null;
  imbalanced: boolean;
}

export interface FamilyBalance {
  rows: FamilyRow[];
  /** declared families that have never taken a page */
  zeroPage: string[];
  /** subjects matching no declared template (a write-gate violation, or older history) */
  unowned: StructureUnit[];
  declared: number;
}

/**
 * Pages, claims and prose per declared family. A family is a filing slot the skill declares,
 * so a slot that took nothing is a fact about the structure and gets named rather than being
 * dropped from a table of what happens to exist.
 */
export function familyBalance(
  units: readonly StructureUnit[],
  templates: readonly string[],
): FamilyBalance {
  const pages = new Map<string, number>();
  const claims = new Map<string, number>();
  const chars = new Map<string, number>();
  const unowned: StructureUnit[] = [];
  for (const template of templates) {
    pages.set(template, 0);
    claims.set(template, 0);
    chars.set(template, 0);
  }
  for (const unit of units) {
    const template = familyOf(unit.path, templates);
    if (!template) {
      unowned.push(unit);
      continue;
    }
    pages.set(template, pages.get(template)! + 1);
    claims.set(template, claims.get(template)! + unit.claims);
    chars.set(template, chars.get(template)! + unit.chars);
  }
  const totalPages = units.length;
  const totalClaims = units.reduce((n, u) => n + u.claims, 0);
  const totalChars = units.reduce((n, u) => n + u.chars, 0);
  const rate = (n: number, total: number) => (total > 0 ? n / total : 0);
  const rows = templates.map((template): FamilyRow => {
    const p = pages.get(template)!;
    const c = claims.get(template)!;
    const pageShare = rate(p, totalPages);
    const claimShare = rate(c, totalClaims);
    const imbalance = pageShare > 0 ? claimShare / pageShare : null;
    return {
      template,
      pages: p,
      pageShare,
      claims: c,
      claimShare,
      chars: chars.get(template)!,
      charShare: rate(chars.get(template)!, totalChars),
      imbalance,
      imbalanced:
        imbalance !== null && imbalance >= FAMILY_IMBALANCE_WARN && claimShare > UNIT_SHARE_WARN,
    };
  });
  return {
    rows,
    zeroPage: rows.filter((r) => r.pages === 0).map((r) => r.template),
    unowned,
    declared: templates.length,
  };
}

/* -------------------------------------------------------------------- connectivity */

/** Past this share of documents, "some pages cannot be arrived at" becomes a structural fact. */
export const ARRIVAL_BLIND_RATE_WARN = 0.05;
/** Same, for pages the thread stops at. */
export const DEAD_END_RATE_WARN = 0.05;
/** Same, for claims sitting behind a document nothing links to. */
export const ORPHAN_CLAIM_RATE_WARN = 0.02;
/** Any declared family this share of the roster left empty is worth naming. */
export const ZERO_PAGE_FAMILY_RATE_WARN = 0.1;

export interface Connectivity {
  units: number;
  edges: number;
  /** nothing links in: findable only by already knowing the name */
  arrivalBlind: StructureUnit[];
  /** nothing links out: the thread stops here */
  deadEnd: StructureUnit[];
  /** both at once */
  isolated: StructureUnit[];
  /** claims whose subject nothing links to */
  orphanClaims: number;
  /** links resolving to no document — 0 unless the gate let one through */
  deadLinks: LinkSentence[];
}

/**
 * The eval suite's group D vocabulary, computed over the same edge set the gate validates —
 * see `navigability.py::reachability`, whose definitions this mirrors exactly:
 *
 * - arrival-blind = in-degree 0 (the discovery failure);
 * - dead-end = out-degree 0 (the navigation failure; there, "nothing reachable within k hops",
 *   which for a graph whose edges only ever point at existing documents is the same set);
 * - isolated = both;
 * - orphan claim = a claim in an arrival-blind subject.
 *
 * Read over merged subjects rather than over files, because a volume has no links of its own
 * to speak of and would otherwise report the whole archive as arrival-blind.
 */
export function connectivity(index: LinkIndex): Connectivity {
  const arrivalBlind: StructureUnit[] = [];
  const deadEnd: StructureUnit[] = [];
  const isolated: StructureUnit[] = [];
  let orphanClaims = 0;
  for (const unit of index.units) {
    const blind = (index.incoming.get(unit.path) ?? []).length === 0;
    const stops = (index.outgoing.get(unit.path) ?? []).length === 0;
    if (blind) {
      arrivalBlind.push(unit);
      orphanClaims += unit.claims;
    }
    if (stops) deadEnd.push(unit);
    if (blind && stops) isolated.push(unit);
  }
  const byPath = (a: StructureUnit, b: StructureUnit) => a.path.localeCompare(b.path);
  return {
    units: index.units.length,
    edges: index.edgeCount,
    arrivalBlind: arrivalBlind.sort(byPath),
    deadEnd: deadEnd.sort(byPath),
    isolated: isolated.sort(byPath),
    orphanClaims,
    deadLinks: index.deadLinks,
  };
}

/* ----------------------------------------------------------------------- anomalies */

export type AnomalyKind =
  | "deadLink"
  | "concentration"
  | "familyImbalance"
  | "zeroPageFamilies"
  | "arrivalBlind"
  | "deadEnd"
  | "orphanClaims";

export interface Anomaly {
  kind: AnomalyKind;
  /** semantic colour is only ever spent on a real state: warn, or danger for a broken link */
  tone: "warn" | "danger";
  /**
   * The share of the base this covers (claims, documents or declared families, whichever the
   * anomaly is about). Counts are not comparable across kinds; shares are, so this is what
   * orders the list.
   */
  weight: number;
  /** the headline number, in the unit the kind implies */
  value: number;
  /** the headline count, where the kind has one */
  count: number;
  /** a second number the sentence needs (the lead ratio, the imbalance factor) */
  extra: number | null;
  /** the family template, when the anomaly is about one */
  template: string | null;
  /** where a click lands, when the anomaly points at one subject */
  target: { path: string; documentId: string | null; title: string } | null;
}

const KIND_ORDER: AnomalyKind[] = [
  "deadLink",
  "concentration",
  "familyImbalance",
  "zeroPageFamilies",
  "arrivalBlind",
  "deadEnd",
  "orphanClaims",
];

/**
 * Everything about this structure that is out of line, worst first — the answer to "what are
 * the three most abnormal things about this base?" without reading a single chart.
 *
 * Eligibility is a threshold; ORDER is the share of the base affected, so a family holding 40%
 * of the claims outranks eleven unreachable pages out of ninety-three whatever their raw
 * counts look like. A danger always precedes a warning: a dead link is a broken structure, not
 * a lopsided one.
 */
export function anomalies(
  conc: Concentration,
  families: FamilyBalance,
  conn: Connectivity,
): Anomaly[] {
  const out: Anomaly[] = [];
  const lead = conc.rows[0];

  if (conn.deadLinks.length > 0) {
    out.push({
      kind: "deadLink",
      tone: "danger",
      weight: conn.edges > 0 ? conn.deadLinks.length / (conn.edges + conn.deadLinks.length) : 1,
      value: conn.deadLinks.length,
      count: conn.deadLinks.length,
      extra: null,
      template: null,
      target: null,
    });
  }
  if (lead && conc.overThreshold) {
    out.push({
      kind: "concentration",
      tone: "warn",
      weight: conc.leadShare,
      value: conc.leadShare,
      count: lead.claims,
      extra: conc.leadRatio,
      template: null,
      target: { path: lead.path, documentId: lead.documentId, title: lead.title },
    });
  }
  for (const row of families.rows) {
    if (!row.imbalanced) continue;
    out.push({
      kind: "familyImbalance",
      tone: "warn",
      weight: row.claimShare,
      value: row.claimShare,
      count: row.pages,
      extra: row.imbalance,
      template: row.template,
      target: null,
    });
  }
  if (
    families.declared > 0 &&
    families.zeroPage.length / families.declared > ZERO_PAGE_FAMILY_RATE_WARN
  ) {
    out.push({
      kind: "zeroPageFamilies",
      tone: "warn",
      weight: families.zeroPage.length / families.declared,
      value: families.zeroPage.length,
      count: families.declared,
      extra: null,
      template: null,
      target: null,
    });
  }
  const rate = (n: number, total: number) => (total > 0 ? n / total : 0);
  const blindRate = rate(conn.arrivalBlind.length, conn.units);
  if (blindRate > ARRIVAL_BLIND_RATE_WARN) {
    out.push({
      kind: "arrivalBlind",
      tone: "warn",
      weight: blindRate,
      value: blindRate,
      count: conn.arrivalBlind.length,
      extra: null,
      template: null,
      target: null,
    });
  }
  const deadEndRate = rate(conn.deadEnd.length, conn.units);
  if (deadEndRate > DEAD_END_RATE_WARN) {
    out.push({
      kind: "deadEnd",
      tone: "warn",
      weight: deadEndRate,
      value: deadEndRate,
      count: conn.deadEnd.length,
      extra: null,
      template: null,
      target: null,
    });
  }
  const orphanRate = rate(conn.orphanClaims, conc.totalClaims);
  if (orphanRate > ORPHAN_CLAIM_RATE_WARN) {
    out.push({
      kind: "orphanClaims",
      tone: "warn",
      weight: orphanRate,
      value: orphanRate,
      count: conn.orphanClaims,
      extra: null,
      template: null,
      target: null,
    });
  }

  return out.sort(
    (a, b) =>
      (a.tone === b.tone ? 0 : a.tone === "danger" ? -1 : 1) ||
      b.weight - a.weight ||
      KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) ||
      (a.template ?? "").localeCompare(b.template ?? ""),
  );
}

/* ------------------------------------------------------------------ the whole lens */

export interface StructureHealth {
  index: LinkIndex;
  units: StructureUnit[];
  concentration: Concentration;
  families: FamilyBalance;
  connectivity: Connectivity;
  anomalies: Anomaly[];
}

/** Everything the health surface reads, from one pass over the projection. */
export function structureHealth(
  docs: readonly LensDocument[],
  templates: readonly string[],
  topN = 10,
): StructureHealth {
  const index = buildLinkIndex(docs);
  const conc = concentration(index.units, topN);
  const families = familyBalance(index.units, templates);
  const conn = connectivity(index);
  return {
    index,
    units: index.units,
    concentration: conc,
    families,
    connectivity: conn,
    anomalies: anomalies(conc, families, conn),
  };
}

/* -------------------------------------------------------- comparing two snapshots */

/** The scalar reading of one structure — the row set a comparison subtracts. */
export interface HealthSummary {
  subjects: number;
  files: number;
  claims: number;
  edges: number;
  deadLinks: number;
  arrivalBlind: number;
  deadEnd: number;
  orphanClaims: number;
  /** the biggest subject's claim share, as a percentage point value (0–100) */
  leadShare: number;
  leadRatio: number;
}

export function summarize(health: StructureHealth, files: number): HealthSummary {
  return {
    subjects: health.units.length,
    files,
    claims: health.concentration.totalClaims,
    edges: health.connectivity.edges,
    deadLinks: health.connectivity.deadLinks.length,
    arrivalBlind: health.connectivity.arrivalBlind.length,
    deadEnd: health.connectivity.deadEnd.length,
    orphanClaims: health.connectivity.orphanClaims,
    leadShare: health.concentration.leadShare * 100,
    leadRatio: health.concentration.leadRatio ?? 0,
  };
}

export type SummaryMetric = keyof HealthSummary;

export interface DeltaRow {
  metric: SummaryMetric;
  before: number;
  after: number;
  delta: number;
  /** true for metrics where more is worse, so the view can read a rise as a regression */
  lowerIsBetter: boolean;
}

const LOWER_IS_BETTER: SummaryMetric[] = [
  "deadLinks",
  "arrivalBlind",
  "deadEnd",
  "orphanClaims",
  "leadShare",
  "leadRatio",
];

const METRIC_ORDER: SummaryMetric[] = [
  "files",
  "subjects",
  "claims",
  "edges",
  "arrivalBlind",
  "deadEnd",
  "orphanClaims",
  "deadLinks",
  "leadShare",
  "leadRatio",
];

/** The difference table: every scalar, both readings, the signed change. */
export function deltaRows(before: HealthSummary, after: HealthSummary): DeltaRow[] {
  return METRIC_ORDER.map((metric) => ({
    metric,
    before: before[metric],
    after: after[metric],
    delta: after[metric] - before[metric],
    lowerIsBetter: LOWER_IS_BETTER.includes(metric),
  }));
}

export interface UnitDiff {
  added: StructureUnit[];
  removed: StructureUnit[];
}

/** Which subjects appeared and which went away, by path. */
export function diffUnits(
  before: readonly StructureUnit[],
  after: readonly StructureUnit[],
): UnitDiff {
  const beforePaths = new Set(before.map((u) => u.path));
  const afterPaths = new Set(after.map((u) => u.path));
  const byPath = (a: StructureUnit, b: StructureUnit) => a.path.localeCompare(b.path);
  return {
    added: after.filter((u) => !beforePaths.has(u.path)).sort(byPath),
    removed: before.filter((u) => !afterPaths.has(u.path)).sort(byPath),
  };
}

export interface EdgeDiffRow {
  fromPath: string;
  fromTitle: string;
  toPath: string;
  toTitle: string;
  toDocumentId: string | null;
  /** the claim that created the edge — a new edge is only meaningful with its sentence */
  sentence: string;
}

/** Edges present after and absent before, each carrying the sentence that made it. */
export function newEdges(before: LinkIndex, after: LinkIndex): EdgeDiffRow[] {
  const had = new Set<string>();
  for (const [from, rows] of before.outgoing) {
    for (const row of rows) had.add(`${from} ${row.path}`);
  }
  const out: EdgeDiffRow[] = [];
  for (const [from, rows] of after.outgoing) {
    for (const row of rows) {
      if (had.has(`${from} ${row.path}`)) continue;
      out.push({
        fromPath: from,
        fromTitle: after.unitByPath.get(from)?.title ?? from,
        toPath: row.path,
        toTitle: row.title,
        toDocumentId: row.documentId,
        sentence: row.sentence,
      });
    }
  }
  return out.sort(
    (a, b) => a.fromPath.localeCompare(b.fromPath) || a.toPath.localeCompare(b.toPath),
  );
}

/* -------------------------------------------------- the retired canvas's deep links */

/**
 * Where an old `#/graph/node/<id>` link now goes.
 *
 * The canvas that owned those links is gone, but the links are not: a node was always either a
 * canonical document or a source, and both have a better home than a dot in a force layout.
 * The semantics are upgraded (a document, an original text) and no address breaks.
 */
export function legacyNodeTarget(
  id: string,
): { kind: "document"; id: string } | { kind: "source"; id: string } {
  return id.startsWith("src:")
    ? { kind: "source", id: id.slice("src:".length) }
    : { kind: "document", id };
}
