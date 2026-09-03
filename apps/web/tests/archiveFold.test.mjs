/**
 * The archive's fold in the contents tree.
 *
 * The property under test is the one the design fixes: THE PATH IS THE STATE. Nothing here
 * reads a flag — an archived document is one filed under `archive/`, and the console's tree
 * is split on that prefix and on nothing else. The fixture is shaped around the two things
 * that would go wrong quietly: a document whose live twin exists (the shadowing case), and
 * an archived page that took its rollover volumes with it.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/archive.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  ARCHIVE_DIR,
  ARCHIVE_PREFIX,
  ARCHIVE_OF_KEY,
  ARCHIVE_RECORD_TYPE,
  archiveHiddenCount,
  archiveRecordFullPath,
  archiveRecordFullTarget,
  archiveRecordPaths,
  documentAddress,
  documentByPath,
  archivedPath,
  foldArchive,
  isArchiveRecord,
  isArchivedPath,
  livePath,
  sameSubject,
  splitArchived,
} = await import(moduleUrl);

/* ------------------------------------------------------------------- the fixture */

/** The same shape `lib/model.buildTree` produces: dirs carry their own path, files carry
 *  the document's. */
function file(path) {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return { name, path, isDir: false, children: [], doc: { path, title: name } };
}

function dir(path, children) {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return { name, path, isDir: true, children };
}

/**
 * A library with two live families, one archived page that took two rollover volumes with
 * it, and one archived page whose live twin is gone.
 */
const TREE = dir("", [
  dir("archive", [
    dir("archive/work", [
      file("archive/work/aurora.md"),
      dir("archive/work/aurora", [
        file("archive/work/aurora/a01.md"),
        file("archive/work/aurora/a02.md"),
      ]),
    ]),
    file("archive/notes/vendor.md"),
  ]),
  dir("memory", [file("memory/topics/retrieval.md"), file("memory/topics/gate.md")]),
  dir("work", [file("work/products/orbit.md")]),
]);

/* --------------------------------------------------------------------- the prefix */

test("the archive is one prefix, stated once", () => {
  assert.equal(ARCHIVE_PREFIX, "archive/");
  assert.equal(ARCHIVE_DIR, "archive");
  assert.equal(isArchivedPath("archive/work/aurora.md"), true);
  assert.equal(isArchivedPath("work/aurora.md"), false);
  // Neither a directory that merely CONTAINS the word nor one that starts with the letters
  // is the archive: the prefix includes its slash for exactly this reason.
  assert.equal(isArchivedPath("work/archive/aurora.md"), false);
  assert.equal(isArchivedPath("archives/aurora.md"), false);
});

test("both spellings of a subject convert into each other, and neither doubles up", () => {
  assert.equal(livePath("archive/work/aurora.md"), "work/aurora.md");
  assert.equal(livePath("work/aurora.md"), "work/aurora.md");
  assert.equal(archivedPath("work/aurora.md"), "archive/work/aurora.md");
  assert.equal(archivedPath("archive/work/aurora.md"), "archive/work/aurora.md");
  // The seed a console reads off the tree and the one read off `GET /archive` name the same
  // subject — which is what the service promises about both spellings.
  assert.equal(sameSubject("archive/work/aurora.md", "work/aurora.md"), true);
  assert.equal(sameSubject("archive/work/aurora.md", "work/orbit.md"), false);
});

/* ----------------------------------------------------------------------- the fold */

test("the archive branch comes out of the contents and stands on its own", () => {
  const fold = foldArchive(TREE);
  assert.deepEqual(
    fold.live.children.map((child) => child.path),
    ["memory", "work"],
    "the contents must not open with an `archive` folder among the families",
  );
  assert.deepEqual(
    fold.archived.map((child) => child.path),
    ["archive/work", "archive/notes/vendor.md"],
  );
  // Volumes travel with their page and are counted with it: one page + two volumes + one
  // page = four files under the section's own heading.
  assert.equal(fold.archivedFiles, 4);
});

test("the live subtrees are handed on by reference, so folding state survives the split", () => {
  const fold = foldArchive(TREE);
  assert.equal(fold.live.children[0], TREE.children[1]);
  assert.equal(fold.live.children[1], TREE.children[2]);
  // And the input is not mutated: the same tree folds the same way twice.
  assert.equal(TREE.children.length, 3);
  assert.equal(foldArchive(TREE).archivedFiles, 4);
});

test("a library that has archived nothing renders exactly as it did before", () => {
  const plain = dir("", [dir("memory", [file("memory/topics/retrieval.md")])]);
  const fold = foldArchive(plain);
  assert.equal(fold.live, plain, "the untouched tree is handed straight back");
  assert.deepEqual(fold.archived, []);
  assert.equal(fold.archivedFiles, 0);
});

test("an archived page whose live twin still exists is folded, not shown twice", () => {
  // The gate refuses a live document shadowed by an archived one, but a client may hold a
  // projection from either side of such a move. The rail must never show both under the
  // contents.
  const shadowed = dir("", [
    dir("archive", [dir("archive/work", [file("archive/work/aurora.md")])]),
    dir("work", [file("work/aurora.md")]),
  ]);
  const fold = foldArchive(shadowed);
  assert.deepEqual(fold.live.children.map((c) => c.path), ["work"]);
  assert.equal(fold.archivedFiles, 1);
});

/* -------------------------------------------------------------------- the counting */

test("the document list splits the same way the tree does", () => {
  const docs = [
    { path: "memory/topics/retrieval.md" },
    { path: "archive/work/aurora.md" },
    { path: "archive/work/aurora/a01.md" },
    { path: "work/products/orbit.md" },
  ];
  const { live, archived } = splitArchived(docs);
  assert.deepEqual(live.map((d) => d.path), [
    "memory/topics/retrieval.md",
    "work/products/orbit.md",
  ]);
  assert.deepEqual(archived.map((d) => d.path), [
    "archive/work/aurora.md",
    "archive/work/aurora/a01.md",
  ]);
});

/* --------------------------------------------------- what the filter left unshown */

/**
 * `archive_hidden` is the count a lane keeps of the evidence its archive filter dropped, and
 * the fixtures below are the three shapes the wire actually sends it in: a fast stage's
 * preview, a rag stage's preview, and — the one a stage-only reader would lose — a deep
 * trail record, which carries it on itself because it has no preview to put it in.
 */

/** The fast lane, finished: the fixed vocabulary, `retrieve` carrying its running total. */
const FAST_STAGES = [
  { name: "plan", ms: 12, status: "ran", preview: { queries: ["aurora gate"] } },
  { name: "retrieve", ms: 240, status: "ran", preview: { claims: 8, archive_hidden: 5 } },
  { name: "retrieve.claims", ms: 200, status: "ran", preview: { hits: 8 } },
  { name: "assemble", ms: 4, status: "ran", preview: { chars: 4102 } },
  { name: "answer", ms: 1800, status: "ran", preview: null },
  { name: "total", ms: 2100, status: "ran" },
];

test("the count is what the lanes measured, summed over the rows that report it", () => {
  assert.equal(archiveHiddenCount(FAST_STAGES), 5);
  // rag says it on `expand`, after the fuse and before the cap.
  assert.equal(
    archiveHiddenCount([
      { name: "embed", ms: 30, status: "ran", preview: null },
      { name: "fuse", ms: 2, status: "ran", preview: { rankings: 20 } },
      { name: "expand", ms: 3, status: "ran", preview: { fused: 20, archive_hidden: 2 } },
      { name: "total", ms: 40, status: "ran" },
    ]),
    2,
  );
});

test("a deep run's trail records are counted too — they carry the key on themselves", () => {
  const trail = [
    { tool: "search_claims", query: "aurora", hits: 3, archive_hidden: 4 },
    { tool: "search_content", query: "aurora gate", hits: 0, archive_hidden: 2 },
    { tool: "fetch_verbatim", source_id: "src_1", chars: 900 },
  ];
  assert.equal(archiveHiddenCount(trail), 6);
  // Stages and trail in one list is what the answer panel passes: one number over the run.
  assert.equal(archiveHiddenCount([...FAST_STAGES, ...trail]), 11);
});

test("no key is the same answer as zero, and nothing is ever inferred from a lane's silence", () => {
  // An `include_archived: true` run hides nothing, so no lane writes the key at all.
  assert.equal(archiveHiddenCount(FAST_STAGES.map((s) => ({ ...s, preview: null }))), 0);
  assert.equal(archiveHiddenCount([]), 0);
  assert.equal(archiveHiddenCount(null), 0);
  assert.equal(archiveHiddenCount(undefined), 0);
  // An older service sends stages with no preview field at all.
  assert.equal(archiveHiddenCount([{ name: "retrieve", ms: 1, status: "ran" }]), 0);
});

test("a value the wire could not have meant contributes nothing rather than NaN", () => {
  const junk = [
    null,
    undefined,
    { preview: { archive_hidden: "5" } },
    { preview: { archive_hidden: -3 } },
    { preview: { archive_hidden: null } },
    { archive_hidden: Number.NaN },
    { archive_hidden: Number.POSITIVE_INFINITY },
    { preview: { archive_hidden: 1.7 } },
  ];
  assert.equal(archiveHiddenCount(junk), 1, "only the finite positive one counts, truncated");
});

test("a row that states it both ways states it twice — the lanes never do, and both are read", () => {
  // Neither shape is privileged: a future lane that put the count on a stage row itself
  // must not be silently ignored because the row also has a preview.
  assert.equal(archiveHiddenCount([{ archive_hidden: 3, preview: { archive_hidden: 4 } }]), 7);
});

/* --------------------------------------------------- the record left at the live path */

/**
 * The other half of the move. Archiving `work/products/aurora.md` files the full page under
 * `archive/` AND leaves a short record standing at the live path, so the pages that link to
 * the subject still land somewhere. The record is LIVE knowledge — the fold above leaves it
 * exactly where it is — and only its frontmatter says which of the two a page is.
 *
 * The trap this pins is one letter wide: a closed rollover volume carries the legacy
 * fallback `type: archive`, and a volume is live knowledge in several volumes, not a record
 * of something that left.
 */

const RECORD = {
  path: "work/products/aurora.md",
  title: "Aurora",
  archived: false,
  frontmatter: {
    type: "archived",
    archive_of: "archive/work/products/aurora.md",
    archived_on: "2026-09-04",
    archive_claims: 42,
  },
};

const FULL_COPY = {
  path: "archive/work/products/aurora.md",
  title: "Aurora",
  archived: true,
  frontmatter: { title: "Aurora" },
};

const VOLUME = {
  path: "work/products/aurora/a01.md",
  title: "Aurora a01",
  frontmatter: { type: "archive", archived_from: "work/products/aurora.md" },
};

test("a record is named by its frontmatter, and a closed volume is not one", () => {
  assert.equal(ARCHIVE_RECORD_TYPE, "archived");
  assert.equal(ARCHIVE_OF_KEY, "archive_of");
  assert.equal(isArchiveRecord(RECORD), true);
  // Two agreeing signals, exactly as core `domain/archive.py` reads them: either alone is
  // enough, so a hand-edited `type` cannot turn a record back into an ordinary page.
  assert.equal(isArchiveRecord({ frontmatter: { archive_of: "archive/work/x.md" } }), true);
  assert.equal(isArchiveRecord({ frontmatter: { type: "archived" } }), true);
  // One letter apart, and the whole concept apart: `type: archive` is a closed VOLUME, live
  // knowledge every lane reads.
  assert.equal(isArchiveRecord(VOLUME), false);
  assert.equal(isArchiveRecord(FULL_COPY), false);
  assert.equal(isArchiveRecord({ path: "work/x.md" }), false);
  assert.equal(isArchiveRecord({ path: "work/x.md", frontmatter: {} }), false);
  assert.equal(isArchiveRecord({ frontmatter: { type: 3 } }), false);
  assert.equal(isArchiveRecord(null), false);
  assert.equal(isArchiveRecord(undefined), false);
});

test("the record stands at a LIVE path — the prefix rule must not see it", () => {
  // Both halves of one move: the record is live, the full copy is archived. A client that
  // derived "archived" from the record's own path would hide the one page still standing.
  assert.equal(isArchivedPath(RECORD.path), false);
  assert.equal(isArchivedPath(FULL_COPY.path), true);
  assert.equal(sameSubject(RECORD.path, FULL_COPY.path), true);
  const split = splitArchived([RECORD, FULL_COPY]);
  assert.deepEqual(split.live.map((d) => d.path), [RECORD.path]);
  assert.deepEqual(split.archived.map((d) => d.path), [FULL_COPY.path]);
});

test("a record names where the full page went; anything else names nowhere", () => {
  assert.equal(archiveRecordFullPath(RECORD), "archive/work/products/aurora.md");
  // Not a record: no door, rather than a door built out of a field that means something else.
  assert.equal(archiveRecordFullPath(VOLUME), null);
  assert.equal(archiveRecordFullPath(FULL_COPY), null);
  assert.equal(archiveRecordFullPath({ frontmatter: { type: "archived" } }), null);
  // The second signal alone still names the door.
  assert.equal(
    archiveRecordFullPath({ frontmatter: { archive_of: "archive/work/x.md" } }),
    "archive/work/x.md",
  );
  assert.equal(archiveRecordFullPath({ frontmatter: { type: "archived", archive_of: "  " } }), null);
  assert.equal(archiveRecordFullPath(null), null);
});

test("the record paths of a projection, for a surface that holds only a claim's path", () => {
  const paths = archiveRecordPaths([RECORD, FULL_COPY, VOLUME, { path: "work/b.md" }]);
  assert.deepEqual([...paths], ["work/products/aurora.md"]);
  assert.equal(paths.has("archive/work/products/aurora.md"), false);
  assert.equal(archiveRecordPaths([]).size, 0);
  assert.equal(archiveRecordPaths(null).size, 0);
  assert.equal(archiveRecordPaths(undefined).size, 0);
});

/* ------------------------------------------- the record's door, resolved by PATH */

/**
 * The pair an archive leaves behind, as a projection may carry it: the record standing at
 * the live path and the full copy under `archive/` — SHARING ONE `document_id`.
 *
 * That is the case the console must survive without depending on the service to have fixed
 * it: two documents, one subject, one identity, and only the path telling them apart.
 */
const SHARED_ID = "doc-aurora";
const ID_PAIR = [
  { ...RECORD, document_id: SHARED_ID },
  { ...FULL_COPY, document_id: SHARED_ID },
];

test("a document is found by its path, which is the address that stays unique", () => {
  assert.equal(documentByPath(ID_PAIR, "work/products/aurora.md"), ID_PAIR[0]);
  assert.equal(documentByPath(ID_PAIR, "archive/work/products/aurora.md"), ID_PAIR[1]);
  // Nothing at that path is null, not the first row that nearly matches.
  assert.equal(documentByPath(ID_PAIR, "work/products/meridian.md"), null);
  assert.equal(documentByPath(ID_PAIR, ""), null);
  assert.equal(documentByPath(ID_PAIR, null), null);
  assert.equal(documentByPath(ID_PAIR, undefined), null);
  assert.equal(documentByPath(null, "work/products/aurora.md"), null);
  assert.equal(documentByPath(undefined, "work/products/aurora.md"), null);
});

test("the record's Full page link lands on the archived copy, not back on the record", () => {
  // The bug this pins: both documents carry `doc-aurora`, so a link resolved through
  // identity picks whichever of the two an id map happened to keep — and the reader who
  // clicks "Full page" on a record is returned to the record they are already reading.
  const target = archiveRecordFullTarget(ID_PAIR, ID_PAIR[0]);
  assert.equal(target.path, "archive/work/products/aurora.md");
  assert.equal(target.doc, ID_PAIR[1]);
  assert.notEqual(target.doc, ID_PAIR[0]);
  // And the address the click carries is that path, so the selection cannot resolve back
  // through the shared id either.
  assert.equal(documentAddress(target.path, target.doc.document_id, target.doc), target.path);

  // Only a record has a door. A closed volume and the copy itself have none.
  assert.equal(archiveRecordFullTarget(ID_PAIR, FULL_COPY), null);
  assert.equal(archiveRecordFullTarget(ID_PAIR, VOLUME), null);
  assert.equal(archiveRecordFullTarget(ID_PAIR, null), null);
  // A copy this projection does not carry keeps its path and loses only the link: naming
  // where the page went states more than silence, and less than a link to nowhere.
  const missing = archiveRecordFullTarget([RECORD], RECORD);
  assert.equal(missing.path, "archive/work/products/aurora.md");
  assert.equal(missing.doc, null);
});

test("the two halves of an archive are addressed by path; every other page by its id", () => {
  // The record, at a live path — named by its frontmatter and by nothing else.
  assert.equal(
    documentAddress(RECORD.path, SHARED_ID, RECORD),
    "work/products/aurora.md",
  );
  // The copy, named by the prefix, with or without the document in hand.
  assert.equal(documentAddress(FULL_COPY.path, SHARED_ID, FULL_COPY), FULL_COPY.path);
  assert.equal(documentAddress(FULL_COPY.path, SHARED_ID), FULL_COPY.path);
  // An ordinary page — a closed volume included — keeps the id that survives a rename.
  assert.equal(documentAddress(VOLUME.path, "doc-a01", VOLUME), "doc-a01");
  assert.equal(documentAddress("work/products/meridian.md", "doc-meridian"), "doc-meridian");
  // No id to keep: the path is the address either way.
  assert.equal(documentAddress("work/products/meridian.md", null), "work/products/meridian.md");
  assert.equal(documentAddress("work/products/meridian.md"), "work/products/meridian.md");
});
