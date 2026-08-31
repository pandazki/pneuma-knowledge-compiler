/**
 * What a suggestion card affords, and the live defect that made it a module.
 *
 * A `glance` card carries four LIBRARY citations — source spans that open in the app — and
 * while its tick is still running it cannot be expanded yet. The bubble expressed "cannot
 * expand" with a single boolean, and the one else-branch behind it printed the web card's
 * sentence: 「这张卡出自互联网搜索，展开请直接点下面的来源链接。」 under four footnote rows
 * pointing at the owner's own meeting minutes.
 *
 * So two questions are asked separately, and the first is asked of the CITATIONS rather
 * than of the kind name. Every test below is a shape that reached a real reader.
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

const { cardSources, expandState } = await import(
  await tsModuleUrl(new URL("../src/lib/suggestionCard.ts", import.meta.url))
);

/** A library citation exactly as `_suggestion_out` puts it on the wire. */
const span = (sid = "src-1", a = 3, b = 5) => ({ source_id: sid, block_start: a, block_end: b });

const base = {
  title: "Lumen Lab",
  body: "一句话定义。",
  trigger: "谁适合来分享 Lumen Lab 相关的技术？",
  confidence: 10,
  citations: [],
  web_citations: [],
};

const glance = (over = {}) => ({
  ...base,
  kind: "glance",
  provisional: true,
  citations: [span("src-1"), span("src-2", 8, 9)],
  ...over,
});

const library = (over = {}) => ({ ...base, kind: "concept", citations: [span()], ...over });

const web = (over = {}) => ({
  ...base,
  kind: "web",
  citations: [],
  web_citations: [{ title: "A page", url: "https://example.invalid/a" }],
  ...over,
});

/* --------------------------------------------------------------- which citation shape */

test("a glance card carries LIBRARY citations, whatever its kind is called", () => {
  assert.equal(cardSources(glance()), "library");
  assert.equal(cardSources(glance({ provisional: false })), "library");
});

test("an ordinary library card carries library citations", () => {
  assert.equal(cardSources(library()), "library");
});

test("a web card is the one that carries URL citations", () => {
  assert.equal(cardSources(web()), "web");
});

test("citations decide it; the kind only breaks a tie construction never produces", () => {
  // Delivery refuses a card carrying neither shape, so this branch is unreachable from the
  // server — but a card that somehow arrived bare must not be offered an expansion that
  // would fail, and `kind` is all that is left to go on.
  assert.equal(cardSources({ ...base, kind: "web" }), "web");
  assert.equal(cardSources({ ...base, kind: "concept" }), "none");
});

test("a field the wire always sends may still be absent from an older client's card", () => {
  const { web_citations: _gone, ...noField } = library();
  assert.equal(cardSources(noField), "library");
});

/* -------------------------------------------------------------------- what it affords */

test("a settled glance card expands like any other library card", () => {
  // Its citations are real source spans; `want_more` reads them verbatim out of the store.
  assert.equal(expandState(glance({ provisional: false })), "expandable");
  assert.equal(expandState(library()), "expandable");
});

test("a provisional glance card says it is FILLING IN, never that it came from the internet", () => {
  // The live defect, as an assertion: this is the branch that printed the web sentence.
  assert.equal(expandState(glance()), "filling");
});

test("a web card says it came from the internet", () => {
  assert.equal(expandState(web()), "web");
});

test("the two reasons cannot be confused, because one of them is unreachable", () => {
  // A provisional card is a library card by construction — the glance short-circuit reads
  // the canonical overview and nothing else. Were a web card ever marked provisional, `web`
  // still wins: the pages are the honest surface either way.
  assert.equal(expandState(web({ provisional: true })), "web");
});
