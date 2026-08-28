/**
 * Claim supersession, read client-side off the canonical projection.
 *
 * A superseding claim carries a second HTML comment after its own anchor comment:
 *
 *     - X 自 2026-05 起任采购总监 [cite: s02 ¶3] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->
 *
 * Semantics (`compile/supersession.py`): the new claim REPLACES `a1f3` as the current state
 * of that fact; `a1f3` stays in the document byte-for-byte as frozen history. The marker is
 * deliberately not an anchor variant — `<!-- c:… -->` remains the one anchor syntax — so the
 * two regexes here can never match each other's comment.
 *
 * The projection ships no supersession field, and it needs none: the relation is in the body
 * the exporter already sends. Two facts are repository-wide rather than per-document, so the
 * index is built over ALL documents:
 *
 * - whether a claim is superseded (its successor may live in another document — an active
 *   page superseding a state archived in a frozen volume);
 * - where the successor is, so a chip can jump to it.
 *
 * Pure and dependency-free: this module imports nothing at runtime, so it is transpiled and
 * tested standalone.
 */

import type { Claim, DocumentRecord } from "./types";

/** The supersession marker. One spelling, declared once; claim.ts strips prose with it. */
export const SUPERSEDES_COMMENT_RE = /<!--\s*supersedes:\s*c:([0-9a-f]{4,})\s*-->/i;

/** Where one claim lives — enough to select it across views. */
export interface ClaimSite {
  path: string;
  documentId: string | null;
  anchor: string;
}

export interface SupersessionIndex {
  /** superseding anchor → the anchor it replaces */
  supersedes: Map<string, string>;
  /** superseded anchor → where its successor lives */
  successorOf: Map<string, ClaimSite>;
  /** anchor → where that claim lives (both ends of every chip resolve through this) */
  siteOf: Map<string, ClaimSite>;
}

/** The audit text of a claim: `raw_text` when the exporter ships one, else `text`. */
function claimSource(claim: Claim): string {
  return claim.raw_text ?? claim.text ?? "";
}

/** The anchor a claim block replaces, or null. */
export function supersededAnchor(text: string): string | null {
  const m = SUPERSEDES_COMMENT_RE.exec(text);
  return m ? m[1].toLowerCase() : null;
}

export function emptySupersessionIndex(): SupersessionIndex {
  return { supersedes: new Map(), successorOf: new Map(), siteOf: new Map() };
}

/**
 * Build the repository-wide index. A claim naming several predecessors (which the compile
 * gate rejects, so committed canonical never holds one) is read by its first marker, and a
 * second successor for the same predecessor is ignored — chains stay linear here even if a
 * hand-edited repository is not.
 */
export function buildSupersessionIndex(docs: DocumentRecord[]): SupersessionIndex {
  const index = emptySupersessionIndex();
  for (const doc of docs ?? []) {
    for (const claim of doc.claims ?? []) {
      const anchor = claim.anchor?.toLowerCase();
      if (!anchor) continue;
      const site: ClaimSite = {
        path: doc.path,
        documentId: doc.document_id ?? null,
        anchor,
      };
      if (!index.siteOf.has(anchor)) index.siteOf.set(anchor, site);
      const old = supersededAnchor(claimSource(claim));
      // A claim superseding itself is a broken write, not a chain of one.
      if (!old || old === anchor) continue;
      if (!index.supersedes.has(anchor)) index.supersedes.set(anchor, old);
      if (!index.successorOf.has(old)) index.successorOf.set(old, site);
    }
  }
  return index;
}

/** True when some other claim has replaced this one as the current state. */
export function isSuperseded(index: SupersessionIndex, anchor: string | null): boolean {
  return !!anchor && index.successorOf.has(anchor.toLowerCase());
}

/** The claim this one replaced, if any. */
export function supersededBy(
  index: SupersessionIndex,
  anchor: string | null,
): string | null {
  return (anchor && index.supersedes.get(anchor.toLowerCase())) || null;
}

/** How many of a document's claims are frozen history. */
export function supersededCount(doc: DocumentRecord, index: SupersessionIndex): number {
  let n = 0;
  for (const claim of doc.claims ?? []) if (isSuperseded(index, claim.anchor)) n += 1;
  return n;
}

/** True when this document takes part in a chain at all — as history or as a successor. */
export function documentHasSupersession(
  doc: DocumentRecord,
  index: SupersessionIndex,
): boolean {
  for (const claim of doc.claims ?? []) {
    const anchor = claim.anchor?.toLowerCase();
    if (!anchor) continue;
    if (index.successorOf.has(anchor) || index.supersedes.has(anchor)) return true;
  }
  return false;
}

/** The claims of a document that hold NOW: those nothing has replaced. */
export function currentClaims(doc: DocumentRecord, index: SupersessionIndex): Claim[] {
  return (doc.claims ?? []).filter((c) => !isSuperseded(index, c.anchor));
}

/**
 * The whole chain one anchor belongs to, oldest first. The walk refuses to loop, so a
 * hand-edited repository with a cycle cannot hang a reader.
 */
export function supersessionChain(
  index: SupersessionIndex,
  anchor: string | null,
): string[] {
  if (!anchor) return [];
  const start = anchor.toLowerCase();
  const back: string[] = [start];
  const seen = new Set([start]);
  let cursor = start;
  for (;;) {
    const older = index.supersedes.get(cursor);
    if (!older || seen.has(older)) break;
    back.unshift(older);
    seen.add(older);
    cursor = older;
  }
  cursor = start;
  for (;;) {
    const newer = index.successorOf.get(cursor)?.anchor;
    if (!newer || seen.has(newer)) break;
    back.push(newer);
    seen.add(newer);
    cursor = newer;
  }
  return back;
}
