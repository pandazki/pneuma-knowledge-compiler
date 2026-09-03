/**
 * The structure lens: volume merging, the sentence-carrying link index, the health readings
 * and the snapshot difference.
 *
 * The fixture is a six-subject synthetic base built out of the framework's own reference
 * vocabulary (profile / people / topics / products / experiments) — no project, no product, no
 * person. It is shaped to contain one of everything the lens is supposed to notice: a subject
 * that rolled over into a closed volume and swallowed the base, a declared family that never
 * took a page, a pair of documents nothing links to, a repeated link between the same two
 * subjects, and one link pointing at a file that is not there.
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
  concentration,
  connectivity,
  deltaRows,
  deriveLinks,
  diffUnits,
  familyBalance,
  familyOf,
  legacyNodeTarget,
  mergeVolumes,
  neighborhoodOf,
  newEdges,
  pathAllowed,
  resolvePath,
  structureHealth,
  summarize,
  templateRegex,
  volumeFamily,
  volumeOwner,
} = await import(moduleUrl);

/* ------------------------------------------------------------------- the fixture */

const TEMPLATES = [
  "memory/profile.md",
  "memory/people/{slug}.md",
  "memory/topics/{slug}.md",
  "work/products/{slug}.md",
  "work/experiments/{slug}.md",
];

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

/* ----------------------------------------------------------------- path ownership */

test("a path template matches exactly what the write gate would accept", () => {
  assert.equal(templateRegex("memory/people/{slug}.md").test("memory/people/ada.md"), true);
  assert.equal(
    templateRegex("memory/people/{slug}.md").test("memory/people/two-part-slug.md"),
    true,
  );
  // A slug is lowercase and hyphen-joined: an uppercase or nested path is not this family.
  assert.equal(templateRegex("memory/people/{slug}.md").test("memory/people/Ada.md"), false);
  assert.equal(templateRegex("memory/people/{slug}.md").test("memory/people/a/b.md"), false);
  assert.equal(pathAllowed("memory/profile.md", TEMPLATES), true);
  assert.equal(pathAllowed("scratch/note.md", TEMPLATES), false);
  assert.equal(familyOf("work/products/atlas.md", TEMPLATES), "work/products/{slug}.md");
  assert.equal(familyOf("work/products/atlas/a01.md", TEMPLATES), null, "a volume is not a family member");
});

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

/* --------------------------------------------------------------------- the health */

test("concentration ranks subjects by claim share and keeps the long tail as one line", () => {
  const conc = concentration(mergeVolumes(DOCS), 3);
  assert.equal(conc.totalClaims, 14);
  assert.deepEqual(
    conc.rows.map((r) => r.path),
    ["work/products/atlas.md", "memory/profile.md", "memory/people/ada.md"],
  );
  assert.equal(conc.rows[0].claims, 8);
  assert.ok(Math.abs(conc.leadShare - 8 / 14) < 1e-9);
  assert.equal(conc.leadRatio, 4, "8 claims against the second subject's 2");
  assert.equal(conc.rows[0].overThreshold, true);
  assert.equal(conc.rows[1].overThreshold, false);
  assert.deepEqual(conc.tail, { units: 3, claims: 3, share: 3 / 14 });
  assert.equal(concentration([], 3).tail, null);
});

test("family balance counts declared slots, including the ones that took nothing", () => {
  const balance = familyBalance(mergeVolumes(DOCS), TEMPLATES);
  assert.equal(balance.declared, 5);
  assert.deepEqual(balance.zeroPage, ["work/experiments/{slug}.md"]);
  assert.deepEqual(balance.unowned, []);
  const products = balance.rows.find((r) => r.template === "work/products/{slug}.md");
  assert.equal(products.pages, 1);
  assert.equal(products.claims, 8);
  assert.ok(Math.abs(products.imbalance - (8 / 14) / (1 / 6)) < 1e-9);
  assert.equal(products.imbalanced, true, "one page carrying four sevenths of the base");
  const people = balance.rows.find((r) => r.template === "memory/people/{slug}.md");
  assert.equal(people.imbalanced, false, "two pages, two claims — proportionate");
  assert.equal(balance.rows.find((r) => r.template === "work/experiments/{slug}.md").imbalance, null);
});

test("a subject outside every declared template is reported rather than filed anyway", () => {
  const balance = familyBalance(mergeVolumes([doc("scratch/loose.md", "Loose", ["x"])]), TEMPLATES);
  assert.deepEqual(
    balance.unowned.map((u) => u.path),
    ["scratch/loose.md"],
  );
});

test("connectivity uses the eval suite's group D words for the same three failures", () => {
  const conn = connectivity(buildLinkIndex(DOCS));
  assert.equal(conn.units, 6);
  assert.equal(conn.edges, 4);
  assert.deepEqual(
    conn.arrivalBlind.map((u) => u.path),
    ["memory/people/bo.md", "memory/profile.md", "memory/topics/void.md"],
  );
  assert.deepEqual(
    conn.deadEnd.map((u) => u.path),
    ["memory/people/bo.md", "memory/topics/tiling.md", "memory/topics/void.md"],
  );
  assert.deepEqual(
    conn.isolated.map((u) => u.path),
    ["memory/people/bo.md", "memory/topics/void.md"],
  );
  assert.equal(conn.orphanClaims, 4, "the claims of the three arrival-blind subjects");
  assert.equal(conn.deadLinks.length, 1);
});

test("anomalies come back worst first: a broken link before any imbalance, then by reach", () => {
  const health = structureHealth(DOCS, TEMPLATES, 3);
  assert.deepEqual(
    health.anomalies.map((a) => a.kind),
    [
      "deadLink",
      "concentration",
      "familyImbalance",
      "arrivalBlind",
      "deadEnd",
      "orphanClaims",
      "zeroPageFamilies",
    ],
  );
  assert.equal(health.anomalies[0].tone, "danger");
  assert.ok(health.anomalies.slice(1).every((a) => a.tone === "warn"));
  const lead = health.anomalies[1];
  assert.equal(lead.target.path, "work/products/atlas.md");
  assert.equal(lead.extra, 4, "the first-over-second ratio rides along");
  assert.equal(health.anomalies[2].template, "work/products/{slug}.md");
  // Ordering is by share of the base, so counts of different things stay comparable.
  const weights = health.anomalies.slice(1).map((a) => a.weight);
  assert.deepEqual(weights, [...weights].sort((a, b) => b - a));
});

test("a structure with nothing out of line reports nothing out of line", () => {
  const clean = [
    doc("memory/people/ada.md", "Ada", ["Works with [Bo](./bo.md)."]),
    doc("memory/people/bo.md", "Bo", ["Works with [Ada](./ada.md)."]),
  ];
  const health = structureHealth(clean, ["memory/people/{slug}.md"]);
  assert.deepEqual(health.anomalies, []);
  assert.equal(health.connectivity.arrivalBlind.length, 0);
  assert.equal(health.connectivity.deadEnd.length, 0);
});

/* ------------------------------------------------------------------- the compare */

test("two snapshots subtract into a difference table, a subject diff and new threads", () => {
  const before = [PROFILE, ATLAS, ADA];
  const after = DOCS;
  const beforeHealth = structureHealth(before, TEMPLATES);
  const afterHealth = structureHealth(after, TEMPLATES);

  const rows = deltaRows(
    summarize(beforeHealth, before.length),
    summarize(afterHealth, after.length),
  );
  const by = (metric) => rows.find((r) => r.metric === metric);
  assert.equal(by("files").delta, 4);
  assert.equal(by("subjects").delta, 3);
  assert.equal(by("claims").delta, 9);
  assert.equal(by("edges").delta, 1, "only the volume's link to the topic is new");
  assert.equal(by("deadLinks").delta, 1);
  assert.equal(by("arrivalBlind").before, 1, "the profile was already unreachable");
  assert.equal(by("arrivalBlind").delta, 2);
  assert.equal(by("arrivalBlind").lowerIsBetter, true);
  assert.equal(by("claims").lowerIsBetter, false);

  const units = diffUnits(beforeHealth.units, afterHealth.units);
  assert.deepEqual(
    units.added.map((u) => u.path),
    ["memory/people/bo.md", "memory/topics/tiling.md", "memory/topics/void.md"],
  );
  assert.deepEqual(units.removed, []);

  const edges = newEdges(beforeHealth.index, afterHealth.index);
  assert.equal(edges.length, 1);
  assert.equal(edges[0].fromPath, "work/products/atlas.md");
  assert.equal(edges[0].toPath, "memory/topics/tiling.md");
  assert.match(edges[0].sentence, /tiling question/, "a new edge without its claim says nothing");
});

test("a snapshot that lost a subject reports it lost, and no new edges either way", () => {
  const beforeHealth = structureHealth(DOCS, TEMPLATES);
  const afterHealth = structureHealth([PROFILE, ATLAS, ATLAS_V1, ADA], TEMPLATES);
  const units = diffUnits(beforeHealth.units, afterHealth.units);
  assert.deepEqual(units.added, []);
  assert.deepEqual(
    units.removed.map((u) => u.path),
    ["memory/people/bo.md", "memory/topics/tiling.md", "memory/topics/void.md"],
  );
  assert.deepEqual(newEdges(beforeHealth.index, afterHealth.index), []);
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
