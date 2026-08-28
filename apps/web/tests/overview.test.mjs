/**
 * The document overview as the viewer derives it: a pure read over the body the exporter
 * already ships, keyed on the system's own markers rather than on the rendered headings.
 *
 * The fixture is the shape `compile/documents.render_overview` writes — region markers, one
 * marker per slot, a heading the deployment owns, and a system anchor on every block.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const { parseOverview, hasOverviewContent, ledgerClaims, resolveHref } = await import(
  await tsModuleUrl(new URL("../src/lib/overview.ts", import.meta.url))
);

const BODY = [
  "# Mei Lin",
  "",
  "<!-- overview -->",
  "",
  "<!-- overview:definition -->",
  "### Definition",
  "",
  "Mei Lin leads supplier qualification for Aurora. c:11aa22bb <!-- c:9150080f -->",
  "",
  "<!-- overview:summary -->",
  "### Summary",
  "",
  "She has run qualification since 2025-03. [cite: s01 ¶2-3] <!-- c:e94042c8 -->",
  "",
  "<!-- overview:connections -->",
  "### Connections",
  "",
  "- [work/products/aurora.md](../../work/products/aurora.md) — she qualifies its suppliers. c:55ee66ff <!-- c:d10c444b -->",
  "",
  "<!-- /overview -->",
  "",
  "## Role",
  "",
  "- Mei Lin has led supplier qualification since 2025-03. [cite: s01 ¶2-3] <!-- c:11aa22bb -->",
].join("\n");

const DOC = { path: "memory/people/mei-lin.md", body: BODY, claims: [] };

test("the region parses off its markers, not off the headings", () => {
  const overview = parseOverview(DOC);
  assert.equal(overview.definition, "Mei Lin leads supplier qualification for Aurora.");
  assert.equal(overview.summary, "She has run qualification since 2025-03.");
  assert.equal(overview.introduction, "");
  assert.equal(overview.connections.length, 1);
  assert.deepEqual(overview.connections[0], {
    path: "work/products/aurora.md",
    href: "../../work/products/aurora.md",
    relation: "she qualifies its suppliers.",
  });
  assert.ok(hasOverviewContent(overview));
});

test("the raw machinery never reaches the page", () => {
  const overview = parseOverview(DOC);
  for (const text of [overview.definition, overview.summary, overview.connections[0].relation]) {
    assert.ok(!text.includes("<!--"), text);
    assert.ok(!text.includes("[cite:"), text);
    assert.ok(!text.includes("c:"), text);
  }
});

test("a document without the region has no overview at all", () => {
  const plain = { path: "memory/people/x.md", body: "# X\n\n- a claim. <!-- c:aaaa1111 -->", claims: [] };
  assert.equal(parseOverview(plain), null);
  assert.equal(hasOverviewContent(null), false);
});

test("the ledger view drops exactly the region's own claims", () => {
  const overview = parseOverview(DOC);
  const claims = [
    { anchor: "9150080f", kind: "paragraph", text: "definition", citations: [], flags: [] },
    { anchor: "e94042c8", kind: "paragraph", text: "summary", citations: [], flags: [] },
    { anchor: "d10c444b", kind: "list_item", text: "connection", citations: [], flags: [] },
    { anchor: "11aa22bb", kind: "list_item", text: "a real claim", citations: [], flags: [] },
  ];
  assert.deepEqual(
    ledgerClaims(claims, overview).map((c) => c.anchor),
    ["11aa22bb"],
  );
  // no overview → the ledger is the whole claim list, untouched
  assert.equal(ledgerClaims(claims, null).length, 4);
});

test("a connection href resolves the way the gate resolves it", () => {
  assert.equal(
    resolveHref("memory/people/mei-lin.md", "../../work/products/aurora.md"),
    "work/products/aurora.md",
  );
});
