/**
 * The document OVERVIEW, read client-side off the body the exporter already ships.
 *
 * A canonical document has two parts (`compile/documents.py`). The LEDGER is the anchored,
 * cited claims — appended, edited, superseded, never deleted. The OVERVIEW is a bounded head
 * above it, which a compile may rewrite WHOLE: the current picture of the subject in four
 * slots. It is delimited by HTML comments the system writes and the model never types:
 *
 *     <!-- overview -->
 *     <!-- overview:definition -->
 *     ### Definition
 *
 *     Mei Lin leads supplier qualification for Aurora. c:11aa22bb <!-- c:9150080f -->
 *     …
 *     <!-- /overview -->
 *
 * Parsing keys on those markers and never on the headings, for the same reason the Python
 * side does: the heading is catalog prose a deployment may translate, the marker is not.
 *
 * The projection ships no overview field and needs none — the region is in the body. What
 * the viewer needs on top of the text is the region's ANCHOR SET, so the ledger below can be
 * rendered without its head repeated inside it: the overview is shown once, as a card, and
 * the claim list stays the claim list.
 *
 * Pure and dependency-free (types only), so it is transpiled and tested standalone.
 */

import type { Claim, DocumentRecord } from "./types";

/** The four slots, in the order the region renders them. */
export const OVERVIEW_SLOTS = ["definition", "summary", "introduction", "connections"] as const;

export type OverviewSlot = (typeof OVERVIEW_SLOTS)[number];

const OPEN_RE = /^[ \t]*<!--[ \t]*overview[ \t]*-->[ \t]*$/;
const CLOSE_RE = /^[ \t]*<!--[ \t]*\/overview[ \t]*-->[ \t]*$/;
const SLOT_RE = /^[ \t]*<!--[ \t]*overview:([a-z_]+)[ \t]*-->[ \t]*$/;
const HEADING_RE = /^[ \t]*#{1,6}[ \t]+\S/;
const ANCHOR_RE = /<!--\s*c:([0-9a-f]{4,})\s*-->/g;
/** An anchor REFERENCE in prose — the overview's pointer at the claim it restates. */
const ANCHOR_REF_RE = /c:[0-9a-f]{4,}/g;
const CITE_RE = /\[cite:[^\]]*\]/g;
const CONNECTION_RE =
  /^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[([^\]]*)\]\(([^)]*)\)[ \t]*(?:[—–-][ \t]*)?(.*)$/;

/** One relation to another subject page. `path` is repo-relative; `href` is as written. */
export interface OverviewConnection {
  path: string;
  href: string;
  relation: string;
}

export interface DocumentOverview {
  definition: string;
  summary: string;
  introduction: string;
  connections: OverviewConnection[];
  /** The anchors living inside the region — the claims the ledger view must not repeat. */
  anchors: Set<string>;
}

function displayText(text: string): string {
  return text.replace(CITE_RE, "").replace(ANCHOR_RE, "").replace(ANCHOR_REF_RE, "").trim();
}

/** Resolve a relative href against the linking document's directory (mirrors the gate). */
export function resolveHref(fromPath: string, href: string): string {
  const stack = fromPath.split("/").slice(0, -1);
  for (const part of href.split("#")[0].split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") stack.pop();
    else stack.push(part);
  }
  return stack.join("/");
}

/**
 * The overview of one document, or null when it has none (every document written before the
 * region existed, and every document whose compile never had a picture to state).
 */
export function parseOverview(doc: DocumentRecord): DocumentOverview | null {
  const body = doc.body ?? "";
  const lines = body.split("\n");
  const start = lines.findIndex((line) => OPEN_RE.test(line));
  if (start < 0) return null;
  let end = -1;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (CLOSE_RE.test(lines[i])) {
      end = i;
      break;
    }
  }
  if (end < 0) return null;

  const slots = new Map<string, string[]>();
  const anchors = new Set<string>();
  let slot: string | null = null;
  for (let i = start; i <= end; i += 1) {
    const line = lines[i];
    for (const match of line.matchAll(ANCHOR_RE)) anchors.add(match[1].toLowerCase());
    const opener = SLOT_RE.exec(line);
    if (opener) {
      slot = opener[1];
      if (!slots.has(slot)) slots.set(slot, []);
      continue;
    }
    if (OPEN_RE.test(line) || CLOSE_RE.test(line)) {
      slot = null;
      continue;
    }
    if (slot) slots.get(slot)!.push(line);
  }

  const prose = (name: OverviewSlot): string => {
    const kept = [...(slots.get(name) ?? [])];
    while (kept.length && !kept[0].trim()) kept.shift();
    if (kept.length && HEADING_RE.test(kept[0])) kept.shift();
    return displayText(kept.join("\n").trim());
  };

  const connections: OverviewConnection[] = [];
  for (const line of slots.get("connections") ?? []) {
    const match = CONNECTION_RE.exec(line.replace(ANCHOR_RE, ""));
    if (!match) continue;
    const label = match[1].trim();
    const href = match[2].trim();
    connections.push({
      path: label.endsWith(".md") ? label : resolveHref(doc.path, href),
      href,
      relation: displayText(match[3]),
    });
  }

  return {
    definition: prose("definition"),
    summary: prose("summary"),
    introduction: prose("introduction"),
    connections,
    anchors,
  };
}

/** True when the region says something — an empty region is not worth a card. */
export function hasOverviewContent(overview: DocumentOverview | null): boolean {
  return (
    !!overview &&
    (!!overview.definition ||
      !!overview.summary ||
      !!overview.introduction ||
      overview.connections.length > 0)
  );
}

/** The document's LEDGER claims: everything the overview region does not hold. */
export function ledgerClaims(
  claims: Claim[],
  overview: DocumentOverview | null,
): Claim[] {
  if (!overview || overview.anchors.size === 0) return claims;
  return claims.filter((c) => !c.anchor || !overview.anchors.has(c.anchor.toLowerCase()));
}
