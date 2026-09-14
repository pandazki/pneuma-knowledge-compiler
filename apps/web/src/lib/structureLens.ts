/**
 * The canonical link index: who points at whom, and the sentence that says why.
 *
 * The STRUCTURE LENS itself — the findings, the score, the levels — is derived in core and
 * read over `GET /v1/users/{uid}/lens` (docs/design/structure-lens.md §3): the console
 * computes none of it, so the number the Owner sees is the number a Steward running
 * `pkc lens` sees. What stays here is the one thing a report cannot carry: the per-document
 * NEIGHBOURHOOD the Canonical view reads, whose rows are claim sentences rather than ids.
 *
 * Two rules run through everything here:
 *
 * 1. AN EDGE IS A SENTENCE. Every link is created by one claim, and that claim is in the
 *    projection, so no edge is ever reported as a bare pair of ids — the sentence that made it
 *    travels with it.
 * 2. A CLOSED VOLUME IS NOT A DOCUMENT. A closed volume (`<document>/aNN.md`) is a real
 *    canonical file, but to a reader it is the back half of its owner. Claims, characters and
 *    edges are merged onto the owner; the volume is only named when a sentence physically
 *    lives in one.
 *
 * Calibration is deliberately borrowed rather than invented: volume ownership mirrors
 * `compile/patch.py::history_volume_owner`, and the link grammar is the gate's
 * (`compile/links.py`), so the card and the lens can never drift into two definitions of
 * the same edge.
 *
 * Import-free by design (the type imports are erased), so it transpiles standalone for its
 * test. Language-free too: it returns paths and sentences, the view owns every word.
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
 * One SUBJECT: an owned page plus every closed volume filed under it. This — not the
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
  /** the closed volume the sentence lives in, when it is not the unit's own page */
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
 * Edges are merged onto units, so a link written in a closed volume counts for its owner and
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
    const key = `${fromUnit}\u0000${toUnit}`;
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
 * One subject's neighbourhood. `path` may name a closed volume — a reader who opened a
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

/** One page of a subject that has rolled over: the open volume, or one closed volume. */
export interface VolumePage {
  path: string;
  documentId: string | null;
  /** The open volume's own title, or the volume's file stem (`a01`) for a closed volume. */
  label: string;
  main: boolean;
  current: boolean;
}

/**
 * The pages a rolled-over subject is spread across, in reading order: the open volume first,
 * then its closed volumes.
 *
 * A reader who lands on `projects/x/a01` sees a page headed `archived_from … rollover_volume
 * 01` and no way back: the volume knows its owner, and said so in words, but offered no door.
 * The family is already in the link index (`mergeVolumes` folds volumes onto their owner), so
 * this is a lookup rather than a new derivation.
 *
 * Null when the subject has no volumes at all — which is almost every page, and which must
 * render exactly as it did before rollover existed.
 */
export function volumeFamily(index: LinkIndex, path: string): VolumePage[] | null {
  const unit =
    index.unitByPath.get(path) ??
    index.units.find((candidate) => candidate.volumes.includes(path)) ??
    null;
  if (!unit || unit.volumes.length === 0) return null;
  return [
    {
      path: unit.path,
      documentId: unit.documentId,
      label: unit.title,
      main: true,
      current: unit.path === path,
    },
    ...unit.volumes.map((volume) => ({
      path: volume,
      documentId: null,
      label: volume.slice(volume.lastIndexOf("/") + 1).replace(/\.md$/, ""),
      main: false,
      current: volume === path,
    })),
  ];
}

/* ---------------------------- what a groom actually added, between two snapshots */

/**
 * The one reading the Compare tab still computes on the client, and the reason it does:
 * a new edge without the claim that wrote it says nothing, and only the canonical
 * projection carries that sentence. The lens report counts edges; this names them.
 */
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
    for (const row of rows) had.add(`${from}\u0000${row.path}`);
  }
  const out: EdgeDiffRow[] = [];
  for (const [from, rows] of after.outgoing) {
    for (const row of rows) {
      if (had.has(`${from}\u0000${row.path}`)) continue;
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
