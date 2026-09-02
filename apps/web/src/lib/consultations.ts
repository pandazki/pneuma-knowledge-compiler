/**
 * Reading a consultation record: what each address IS, and which of them the answer cited.
 *
 * Pure, and deliberately so — the view renders what these return and decides nothing about
 * addresses on its own. An address is dispatched on its SHAPE, exactly as the service's own
 * ledger does: `kind` says how a lane REACHED an item (`component` covers both a routed
 * claim lookup and a routed span), while the grammar says what it is. `c:xxxx` is a claim,
 * `<source_id> ¶a-b` is a span, and an address that is neither is a canonical page path.
 *
 * No imports: the node tests transpile this file on its own, and the wording it needs is
 * injected by the caller rather than looked up here.
 */

export interface EvidenceAddress {
  kind: string;
  ref: string;
  path: string;
}

export type ParsedAddress =
  | { shape: "claim"; anchor: string; path: string }
  | { shape: "span"; sourceId: string; start: number; end: number }
  | { shape: "document"; path: string };

/**
 * `<source_id> ¶a-b` → its parts; `¶a` alone means the one-block span `a-a`.
 *
 * The inverse of the one citation grammar (I4), and the only place a record's addresses are
 * read back on the client. A malformed interval returns null and the address falls through
 * to being a page path — which is the honest reading: it is not a span, whatever it looked
 * like.
 */
export function parseSpan(
  ref: string,
): { sourceId: string; start: number; end: number } | null {
  const at = ref.indexOf(" ¶");
  if (at <= 0) return null;
  const sourceId = ref.slice(0, at).trim();
  if (!sourceId) return null;
  const span = ref.slice(at + 2);
  const dash = span.indexOf("-");
  const first = Number(dash === -1 ? span : span.slice(0, dash));
  const last = dash === -1 ? first : Number(span.slice(dash + 1));
  if (!Number.isInteger(first) || !Number.isInteger(last)) return null;
  return { sourceId, start: first, end: last };
}

/** One address, read for what it is rather than for how the lane reached it. */
export function parseAddress(item: EvidenceAddress): ParsedAddress {
  const ref = (item.ref ?? "").trim();
  if (ref.startsWith("c:")) {
    return { shape: "claim", anchor: ref.slice(2), path: item.path ?? "" };
  }
  const span = parseSpan(ref);
  if (span) return { shape: "span", ...span };
  return { shape: "document", path: ref };
}

export interface EvidenceRow extends EvidenceAddress {
  parsed: ParsedAddress;
  /** The answer went on to cite this address, not merely have it in front of it. */
  cited: boolean;
}

/**
 * The manifest, with the citations marked inside it rather than listed twice.
 *
 * `citations` is a SUBSET of `evidence_handed` by construction — the lane admits a marker
 * only when its resolved address is in the manifest — so showing them as two lists would
 * print most addresses twice and hide the one relationship that matters: which of the things
 * put in front of the model actually reached the answer. A citation that is somehow NOT in
 * the manifest is still shown, at the end, rather than dropped: the record is what happened,
 * and quietly discarding a row would make the page disagree with the record it is showing.
 *
 * Keyed on `(ref, path)`, the same key the record's own de-duplication uses, and NOT on
 * `kind` — the same claim arrives as `claim` from a ranked face and as `component` from a
 * routed lookup, and keying on it would show one address as two rows.
 */
export function evidenceRows(
  handed: EvidenceAddress[],
  citations: EvidenceAddress[],
): EvidenceRow[] {
  // `JSON.stringify` rather than a joined string: both halves are free text in
  // principle — a span address carries a space, a path could — so any separator
  // chosen by hand is one that two different pairs can collide on.
  const key = (item: EvidenceAddress) =>
    JSON.stringify([item.ref, item.path ?? ""]);
  const cited = new Set(citations.map(key));
  const seen = new Set<string>();
  const rows: EvidenceRow[] = [];
  for (const item of handed) {
    const k = key(item);
    if (seen.has(k)) continue;
    seen.add(k);
    rows.push({ ...item, parsed: parseAddress(item), cited: cited.has(k) });
  }
  for (const item of citations) {
    const k = key(item);
    if (seen.has(k)) continue;
    seen.add(k);
    rows.push({ ...item, parsed: parseAddress(item), cited: true });
  }
  return rows;
}

/** Cited first, then the rest, each half keeping the order the lane published it in. */
export function citedFirst(rows: EvidenceRow[]): EvidenceRow[] {
  return [...rows.filter((r) => r.cited), ...rows.filter((r) => !r.cited)];
}

/**
 * A short, stable label for an address — what a reader scans a manifest with.
 *
 * A page is shown by its LAST segment: the manifest is a column, the full path is on the row
 * as its title, and `memory/people/…` repeated forty times tells a reader nothing they did
 * not already know about their own library.
 */
export function addressLabel(parsed: ParsedAddress): string {
  if (parsed.shape === "claim") return `c:${parsed.anchor}`;
  if (parsed.shape === "span") {
    return parsed.start === parsed.end
      ? `${parsed.sourceId} ¶${parsed.start}`
      : `${parsed.sourceId} ¶${parsed.start}-${parsed.end}`;
  }
  const cut = parsed.path.lastIndexOf("/");
  return cut === -1 ? parsed.path : parsed.path.slice(cut + 1);
}
