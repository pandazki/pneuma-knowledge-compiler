/**
 * The canonical link index: volume merging, the sentence-carrying edges, and the
 * neighbourhood a document is read with.
 *
 * The dimensions, the bands and the check's findings are NOT here: both readings are derived
 * in core and read over `GET /v1/users/{uid}/lens` and `GET /review`, so there is nothing
 * client-side left to assert about them (docs/design/structure-lens.md §5).
 *
 * The fixture is a six-subject synthetic base built out of the framework's own reference
 * vocabulary (profile / people / topics / products / experiments) — no project, no product, no
 * person. It is shaped to contain one of everything the index has to get right: a subject that
 * rolled over into a closed volume, a pair of documents nothing links to, a repeated link
 * between the same two subjects, and one link pointing at a file that is not there.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/structureLens.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  buildLinkIndex,
  deriveLinks,
  legacyNodeTarget,
  mergeVolumes,
  neighborhoodOf,
  resolvePath,
  volumeFamily,
  volumeOwner,
} = await import(moduleUrl);

/* ------------------------------------------------------------------- the fixture */

/** A document: claims are given as bare strings, anchors minted from the index. */
function doc(path, title, claims, body = "body") {
  return {
    document_id: `id-${path.replace(/[^a-z0-9]/g, "")}`,
    path,
    title,
    body,
    claims: claims.map((text, i) => ({ anchor: `c-${i}`, text })),
  };
}

const PROFILE = doc("memory/profile.md", "Profile", [
  "The owner keeps a workbook, filed under [Atlas](../work/products/atlas.md).",
  "A second claim with no link at all.",
]);
const ATLAS = doc("work/products/atlas.md", "Atlas", [
  "Atlas is maintained together with [Ada](../../memory/people/ada.md).",
  "A claim that links nowhere.",
]);
const ATLAS_V1 = doc("work/products/atlas/a01.md", "Atlas · a01", [
  "Older round: [Ada](../../../memory/people/ada.md) took the first pass.",
  "Older round: [Ada](../../../memory/people/ada.md) reviewed it again on the second.",
  "The tiling question moved to [Tiling](../../../memory/topics/tiling.md).",
  "Filler one.",
  "Filler two.",
  "Filler three.",
]);
const ADA = doc("memory/people/ada.md", "Ada", [
  "Ada owns [Atlas](../../work/products/atlas.md).",
]);
const TILING = doc("memory/topics/tiling.md", "Tiling", ["A topic nobody links out of."]);
const BO = doc("memory/people/bo.md", "Bo", ["A page with no thread either way."]);
const VOID = doc("memory/topics/void.md", "Void", [
  "Points at [Missing](./missing.md), which was never written.",
]);

const DOCS = [PROFILE, ATLAS, ATLAS_V1, ADA, TILING, BO, VOID];

/* -------------------------------------------------------------- rollover volumes */

test("a closed volume belongs to the page it sits under, and only if that page exists", () => {
  const present = new Set(DOCS.map((d) => d.path));
  assert.equal(volumeOwner("work/products/atlas/a01.md", present), "work/products/atlas.md");
  assert.equal(volumeOwner("work/products/atlas/a17.md", present), "work/products/atlas.md");
  assert.equal(volumeOwner("work/products/atlas.md", present), null);
  assert.equal(volumeOwner("work/products/atlas/notes.md", present), null, "aNN.md or nothing");
  assert.equal(
    volumeOwner("work/products/ghost/a01.md", present),
    null,
    "an orphaned volume stays a subject of its own rather than folding into a page nobody can open",
  );
});

test("merging volumes turns seven files into six subjects, claims and prose folded in", () => {
  const units = mergeVolumes(DOCS);
  assert.equal(units.length, 6);
  const atlas = units.find((u) => u.path === "work/products/atlas.md");
  assert.equal(atlas.claims, 8, "2 on the page + 6 in the volume");
  assert.deepEqual(atlas.volumes, ["work/products/atlas/a01.md"]);
  assert.equal(atlas.title, "Atlas", "the unit is named by its owner, never by a volume");
  assert.equal(atlas.documentId, ATLAS.document_id);
  assert.equal(atlas.chars, ATLAS.body.length + ATLAS_V1.body.length);
  assert.deepEqual(
    units.find((u) => u.path === "memory/people/ada.md").volumes,
    [],
    "a page that never rolled over carries no volumes",
  );
});

/* ------------------------------------------------------------------- link grammar */

test("relative hrefs resolve against the document that wrote them", () => {
  assert.equal(resolvePath("memory/profile.md", "../work/products/atlas.md"), "work/products/atlas.md");
  assert.equal(resolvePath("memory/topics/void.md", "./missing.md"), "memory/topics/missing.md");
  assert.equal(resolvePath("a/b/c.md", "../../d.md"), "d.md");
  assert.equal(resolvePath("a/b.md", "/root.md"), "root.md");
});

test("every link is read off the claim that wrote it, so the sentence travels with the edge", () => {
  const links = deriveLinks(DOCS);
  assert.equal(links.length, 7, "six links between documents plus one at a missing file");
  const first = links[0];
  assert.equal(first.fromFile, "memory/profile.md");
  assert.equal(first.toFile, "work/products/atlas.md");
  assert.match(first.sentence, /workbook/, "the whole claim, not a label");
  assert.equal(first.anchor, "c-0");
  // An external URL and a non-markdown target are not inter-document links.
  const noise = deriveLinks([
    doc("memory/topics/x.md", "X", [
      "See [somewhere](https://example.invalid/page.md) and [a file](./data.json).",
    ]),
  ]);
  assert.deepEqual(noise, []);
});

/* ----------------------------------------------------------------- the link index */

test("edges are merged onto subjects, repeats collapse, and a broken href is not an edge", () => {
  const index = buildLinkIndex(DOCS);
  assert.equal(index.edgeCount, 4);
  assert.equal(index.deadLinks.length, 1);
  assert.equal(index.deadLinks[0].toFile, "memory/topics/missing.md");

  const out = index.outgoing.get("work/products/atlas.md");
  assert.deepEqual(
    out.map((r) => r.path),
    ["memory/people/ada.md", "memory/topics/tiling.md"],
  );
  const toAda = out[0];
  assert.equal(toAda.more, 2, "two further sentences in the volume say the same thing");
  assert.equal(toAda.volume, null, "the first sentence is on the page itself");
  const toTiling = out[1];
  assert.equal(
    toTiling.volume,
    "work/products/atlas/a01.md",
    "a sentence that lives in a closed volume says so",
  );
  assert.match(toTiling.sentence, /tiling question/);
});

test("a link between two volumes of one subject is the subject talking to itself", () => {
  const selfLinking = [
    doc("work/products/atlas.md", "Atlas", ["Nothing here."]),
    doc("work/products/atlas/a01.md", "a01", [
      "Continues in [the page](../atlas.md).",
    ]),
  ];
  assert.equal(buildLinkIndex(selfLinking).edgeCount, 0);
});

test("a neighbourhood reads both ways, sorted, and a volume address lands on its subject", () => {
  const index = buildLinkIndex(DOCS);
  const atlas = neighborhoodOf(index, "work/products/atlas.md");
  assert.equal(atlas.unit.path, "work/products/atlas.md");
  assert.deepEqual(
    atlas.outgoing.map((r) => r.title),
    ["Ada", "Tiling"],
  );
  assert.deepEqual(
    atlas.incoming.map((r) => r.title),
    ["Ada", "Profile"],
  );
  // Every incoming row carries the sentence its author wrote, not this document's.
  assert.match(atlas.incoming[1].sentence, /workbook/);

  const viaVolume = neighborhoodOf(index, "work/products/atlas/a01.md");
  assert.equal(viaVolume.unit.path, "work/products/atlas.md");
  assert.equal(neighborhoodOf(index, "nowhere.md").unit, null);
});

/* ------------------------------------------------------------------- deep links */

test("an old graph node address still resolves — to a document, or to a source", () => {
  assert.deepEqual(legacyNodeTarget("doc-a11c"), { kind: "document", id: "doc-a11c" });
  assert.deepEqual(legacyNodeTarget("src:c7a3f0"), { kind: "source", id: "c7a3f0" });
});

test("a rolled-over subject knows every page it is spread across, in reading order", () => {
  const index = buildLinkIndex(DOCS);
  // From the closed volume: the door back to the open volume, which the page did not have.
  const fromVolume = volumeFamily(index, "work/products/atlas/a01.md");
  assert.deepEqual(
    fromVolume.map((page) => [page.label, page.main, page.current]),
    [
      ["Atlas", true, false],
      ["a01", false, true],
    ],
  );
  // …and from the open volume, the same family with the other page marked.
  const fromMain = volumeFamily(index, "work/products/atlas.md");
  assert.deepEqual(
    fromMain.map((page) => [page.path, page.current]),
    [
      ["work/products/atlas.md", true],
      ["work/products/atlas/a01.md", false],
    ],
  );
});

test("a page that never rolled over has no family, and renders as it always did", () => {
  const index = buildLinkIndex(DOCS);
  assert.equal(volumeFamily(index, "memory/people/ada.md"), null);
  assert.equal(volumeFamily(index, "nothing/here.md"), null);
});
