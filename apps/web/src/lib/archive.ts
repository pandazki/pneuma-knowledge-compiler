/**
 * The archive, as the console reads it: one path prefix, and the fold it produces in the
 * contents tree.
 *
 * THE PATH IS THE STATE (docs/design/archive.md §2.1). Archiving a document is a `git mv`
 * under one reserved root, so the client derives "is this archived" from the prefix and from
 * nothing else — no flag to trust, no side table to join. That is also why the fold below is
 * a pure function over the tree the projection already ships: a rebuild that moved a document
 * moves its row, with no client release.
 *
 * It is folded rather than hidden for the same reason a rollover volume is folded onto its
 * owner (`lib/structureLens.ts`): the archive is still the library's knowledge — cited,
 * anchored, addressable — it has simply stopped being the answer. A reader who goes looking
 * finds it at the bottom, collapsed, under its own heading; a reader who does not is never
 * shown the past among the present.
 *
 * Import-free by design (the `DirNode` import is type-only), so it transpiles standalone for
 * its test.
 */

import type { DirNode } from "./model";

/** The library's one reserved directory — core `domain/archive.py` states it once. */
export const ARCHIVE_PREFIX = "archive/";

/** The tree's first-level directory name for the archive (the prefix without its slash). */
export const ARCHIVE_DIR = "archive";

/** Is this canonical path in the archive? The prefix, and nothing else. */
export function isArchivedPath(path: string): boolean {
  return path.startsWith(ARCHIVE_PREFIX);
}

/**
 * The live path an archived one would come back to — `archive/work/x.md` → `work/x.md`. A
 * path that is already live is returned unchanged, so callers can normalise either spelling
 * of a subject without asking which one they hold.
 */
export function livePath(path: string): string {
  return isArchivedPath(path) ? path.slice(ARCHIVE_PREFIX.length) : path;
}

/** The archived spelling of a live path. Already-archived paths are returned unchanged. */
export function archivedPath(path: string): string {
  return isArchivedPath(path) ? path : `${ARCHIVE_PREFIX}${path}`;
}

/** Both spellings name one subject: `archive/work/x.md` and `work/x.md` are the same page. */
export function sameSubject(left: string, right: string): boolean {
  return livePath(left) === livePath(right);
}

/** What the contents rail draws: the live tree, and the archive as its own folded section. */
export interface ArchiveFold {
  /** The tree with its `archive/` branch taken out — the contents proper. */
  live: DirNode;
  /**
   * The rows under `archive/`, at the depth they had inside it, so the section renders with
   * the same `TreeRow` the contents use. Empty when nothing has been archived — which is
   * every library until an owner archives something, and which must render exactly as it did
   * before the archive existed.
   */
  archived: DirNode[];
  /** How many archived FILES the section holds, at any depth (volumes included). */
  archivedFiles: number;
}

/** Every file below a node, at any depth. (`documentTree.dirFileCount` for a whole tree.) */
function fileCount(node: DirNode): number {
  if (!node.isDir) return 1;
  let n = 0;
  for (const child of node.children) n += fileCount(child);
  return n;
}

/**
 * Split the contents tree in two.
 *
 * The archive is one first-level directory, so the fold is a shallow copy of the root with
 * that child removed — the live subtrees are shared by reference, which keeps the folding
 * state (`documentTree.defaultCollapsedDirs`, keyed by path) valid across the split.
 *
 * A projection with no archive answers `{live: root, archived: [], archivedFiles: 0}` — the
 * same object it was handed, so nothing downstream re-renders because this function exists.
 */
export function foldArchive(root: DirNode): ArchiveFold {
  const branch = root.children.find((child) => child.isDir && child.path === ARCHIVE_DIR);
  if (!branch) return { live: root, archived: [], archivedFiles: 0 };
  return {
    live: { ...root, children: root.children.filter((child) => child !== branch) },
    archived: branch.children,
    archivedFiles: fileCount(branch),
  };
}

/** Split a list of documents by the same rule, for a count line or a badge. */
export function splitArchived<T extends { path: string }>(
  docs: readonly T[],
): { live: T[]; archived: T[] } {
  const live: T[] = [];
  const archived: T[] = [];
  for (const doc of docs) (isArchivedPath(doc.path) ? archived : live).push(doc);
  return { live, archived };
}

/* ------------------------------------------------- what the filter left unshown */

/**
 * One row this count will look at: a lane stage, whose `preview` may carry the key, or a
 * deep trail record, which carries it directly.
 *
 * Both shapes are read with one function because they state ONE fact — how many pieces of
 * evidence the assembly filter dropped for being archived — and a reader of an answer wants
 * the total, not a per-lane arithmetic they have to do themselves. The field is optional
 * everywhere and absent when nothing was dropped (core `recall/*`: `{"archive_hidden": n}`
 * is merged into the preview only `if hidden`), so "no key" and "zero" are the same answer.
 */
export interface ArchiveHiddenCarrier {
  /** A stage's bounded preview (`lib/stages.ts::StagePreview`), when it has one. */
  preview?: Record<string, unknown> | null;
  /** A deep trail record states it on itself — it has no preview to put it in. */
  archive_hidden?: unknown;
}

/** A count as the wire may have sent it: anything that is not a positive number is none. */
function hiddenOf(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.trunc(value)
    : 0;
}

/**
 * How many archived items this run's own measurements say were dropped — summed across the
 * rows that report it.
 *
 * The sum is over DISTINCT rows, which is the reason it is a sum and not a max: the fast
 * lane states its running total on one stage (`retrieve`, corrected by a second `end` when
 * assembly hides more), rag states its own on `expand`, and a deep run states one number per
 * tool call. Summing rows therefore never double-counts a lane and never loses a lane, and a
 * future stage that starts reporting the key is counted with no change here.
 *
 * Pass whatever the response gave: stages, trail records, or both concatenated. Rows that do
 * not carry the key contribute nothing, so an older service reads as zero rather than as an
 * error.
 */
export function archiveHiddenCount(
  rows: readonly (ArchiveHiddenCarrier | null | undefined)[] | null | undefined,
): number {
  let total = 0;
  for (const row of rows ?? []) {
    if (!row || typeof row !== "object") continue;
    total += hiddenOf(row.archive_hidden);
    total += hiddenOf(row.preview?.archive_hidden);
  }
  return total;
}

/* --------------------------------------------------- the record left at the live path */

/**
 * `frontmatter.type` on the short page an archive leaves standing where the document was.
 *
 * ONE letter apart from a legacy spelling, and the difference is the whole concept: a closed
 * rollover volume carries the fallback `type: archive` and is LIVE knowledge in several
 * volumes, while `type: archived` marks the record of a page that has left. The comparison
 * below is therefore exact rather than a prefix, and the test pins the volume case.
 */
export const ARCHIVE_RECORD_TYPE = "archived";

/** The frontmatter key naming the full copy — the record's second, independent signal. */
export const ARCHIVE_OF_KEY = "archive_of";

/** Anything the projection ships with frontmatter — a `DocumentRecord`, or a test's stub. */
export interface FrontmatterCarrier {
  frontmatter?: Record<string, unknown> | null;
}

/** One frontmatter value as a non-empty string, or null. */
function fmString(doc: FrontmatterCarrier | null | undefined, key: string): string | null {
  const value = doc?.frontmatter?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * Is this document the RECORD of an archive rather than a document of its own?
 *
 * The record stands at the live path with `archived: false` — it is live knowledge, read by
 * the glance and by recall — so the path rule above cannot see it and must not: the archived
 * copy under `archive/` is the other half of the same move. Only the frontmatter the archive
 * job stamped says which of the two a page is.
 *
 * Two agreeing signals, read exactly as core `domain/archive.py::is_archive_record` reads
 * them: the declared `type`, and `archive_of` naming the full copy. Either is enough — one
 * channel writes both together, and the second exists so a hand-edited `type` cannot turn a
 * record back into an ordinary page.
 */
export function isArchiveRecord(doc: FrontmatterCarrier | null | undefined): boolean {
  return fmString(doc, "type") === ARCHIVE_RECORD_TYPE || !!fmString(doc, ARCHIVE_OF_KEY);
}

/** Where the full copy of a record's subject now stands (`archive/…`), or null. */
export function archiveRecordFullPath(
  doc: FrontmatterCarrier | null | undefined,
): string | null {
  return isArchiveRecord(doc) ? fmString(doc, ARCHIVE_OF_KEY) : null;
}

/**
 * The document standing at one path.
 *
 * THE PATH IS THE ADDRESS, and here that is a correctness rule rather than a preference. An
 * archive is the one move that leaves two documents in a library speaking for one subject —
 * the record at the live path and the full copy under `archive/` — and identity is the thing
 * they share: `frontmatter.archive_of` names the copy by PATH because that is the address
 * that stays unique across the move. A link resolved by `document_id` between those two
 * would be resolved by whichever of them a map happened to keep, which is not a resolution
 * at all. So every link that could touch a record goes through here and selects by path.
 */
export function documentByPath<T extends { path: string }>(
  docs: readonly T[] | null | undefined,
  path: string | null | undefined,
): T | null {
  if (!path) return null;
  for (const doc of docs ?? []) if (doc.path === path) return doc;
  return null;
}

/**
 * The address a click on one document carries.
 *
 * Its `document_id` — the address that survives a rename — EXCEPT for the two documents an
 * archive puts in play for one subject, where identity is precisely what is not unique
 * between them: the record standing at the live path and the full copy under `archive/`. For
 * those the path is the address, and a selection made with it can only land on the page the
 * reader clicked.
 *
 * The document itself is optional because some rows are path-keyed lens rows that never
 * carried one (`lib/structureLens.ts`); without it the prefix still names an archived copy,
 * and a caller holding a record's frontmatter should pass it.
 */
export function documentAddress(
  path: string,
  documentId?: string | null,
  doc?: FrontmatterCarrier | null,
): string {
  if (isArchivedPath(path) || isArchiveRecord(doc)) return path;
  return documentId || path;
}

/**
 * The full page a record points at, resolved by path — `{path, doc}`, where `path` is the
 * address to select by and `doc` is the copy itself when this projection carries it.
 *
 * Null for anything that is not a record, so a page without a door renders no door. A record
 * whose copy is missing from the projection keeps its `path` and loses only the link: naming
 * where the page went states more than silence, and less than a link to nowhere.
 */
export function archiveRecordFullTarget<T extends { path: string }>(
  docs: readonly T[] | null | undefined,
  record: FrontmatterCarrier | null | undefined,
): { path: string; doc: T | null } | null {
  const path = archiveRecordFullPath(record);
  return path ? { path, doc: documentByPath(docs, path) } : null;
}

/**
 * The live paths at which records stand, for a surface that holds claims rather than
 * documents — a recall answer says `document_path` and nothing else, and a claim quoted out
 * of a record is a claim about a subject that has left.
 */
export function archiveRecordPaths<T extends FrontmatterCarrier & { path: string }>(
  docs: readonly T[] | null | undefined,
): Set<string> {
  const out = new Set<string>();
  for (const doc of docs ?? []) if (isArchiveRecord(doc)) out.add(doc.path);
  return out;
}


/**
 * The body a confirm sends, decided in one place so the three-valued `note` cannot collapse
 * again: `null` / `undefined` OMITS the field and any string sends it, trimmed. The confirm
 * IS the decision, so a body with no note (and no statement named on the proposal) is
 * refused `note_required` — there is no plan-time note to fall back on, and the record
 * quotes the owner's own words or nothing happens. Items travel only when given.
 */
export function confirmRequestBody<I>(
  items: I[] | undefined,
  note: string | null | undefined,
): { items?: I[]; note?: string } {
  const body: { items?: I[]; note?: string } = {};
  if (items) body.items = items;
  if (note != null) body.note = note.trim();
  return body;
}
