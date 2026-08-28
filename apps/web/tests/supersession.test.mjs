/**
 * Claim supersession as the viewer derives it: the relation lives in the body the exporter
 * already ships, so the index is a pure read over the projection — no new API, no new field.
 *
 * The fixture mirrors the shape `compile/supersession.py` writes: an anchor comment, then a
 * separate `<!-- supersedes: c:… -->` comment naming the predecessor. It deliberately holds a
 * three-link chain, a successor living in ANOTHER document, a claim taking part in nothing,
 * and (in one test) a hand-made cycle — the one thing committed canonical can never contain
 * but a hand-edited repository can.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

/** Transpile one TS module to a data: URL — the standalone-module pattern the other tests use. */
async function tsModuleUrl(url, rewrite = (code) => code) {
  const text = rewrite(await readFile(url, "utf8"));
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const supersessionUrl = await tsModuleUrl(new URL("../src/lib/supersession.ts", import.meta.url));
const {
  buildSupersessionIndex,
  currentClaims,
  documentHasSupersession,
  isSuperseded,
  supersededAnchor,
  supersededBy,
  supersededCount,
  supersessionChain,
} = await import(supersessionUrl);

// claim.ts imports the dictionary (stubbed here, as in the other standalone tests) and the
// supersession module (pointed at the module just loaded, so both share ONE marker regex —
// which is the point of declaring it in one place).
const { cleanClaimText, displayClaim } = await import(
  await tsModuleUrl(new URL("../src/lib/claim.ts", import.meta.url), (code) =>
    code
      .replace(/^import \{ tx \} from "\.\/i18n";$/m, "const tx = (key) => key;")
      .replace(/"\.\/supersession"/, JSON.stringify(supersessionUrl)),
  )
);

/* --------------------------------------------------------------------- fixture */

const claim = (anchor, text) => ({ anchor, kind: "list_item", text, citations: [], flags: [] });

const PEOPLE = {
  document_id: "d-people",
  path: "memory/people/jianing.md",
  title: "jianing",
  frontmatter: { identities: "mailto:j@example.com, im:u_8812", aliases: "贾宁, 老贾" },
  body: "",
  claims: [
    claim("a1f3", "- 对接人是恒印印刷 [cite: s01 ¶8-9] <!-- c:a1f3 -->"),
    claim(
      "c07e",
      "- 自 2026-05 起任新华印务采购总监 [cite: s02 ¶3] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->",
    ),
    claim("9d20", "- 常驻上海 [cite: s03 ¶1] <!-- c:9d20 -->"),
  ],
};

// The head of the chain lives in another document: the current state of a fact can be written
// on a different page from the state it replaced.
const TOPICS = {
  document_id: "d-topics",
  path: "memory/topics/supply.md",
  title: "supply",
  frontmatter: {},
  body: "",
  claims: [
    claim(
      "f4b1",
      "- 自 2026-08 起改任供应链副总 [cite: s04 ¶2] <!-- c:f4b1 --> <!-- supersedes: c:c07e -->",
    ),
  ],
};

const DOCS = [PEOPLE, TOPICS];

/* ----------------------------------------------------------------------- tests */

test("a supersedes marker is read off the block, and an anchor comment is not one", () => {
  assert.equal(supersededAnchor("- x <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"), "a1f3");
  assert.equal(supersededAnchor("- x <!-- c:a1f3 -->"), null);
  assert.equal(supersededAnchor("- x <!--supersedes:c:A1F3-->"), "a1f3", "case and spacing");
  assert.equal(supersededAnchor("- x"), null);
});

test("the index resolves both directions, across documents", () => {
  const index = buildSupersessionIndex(DOCS);
  assert.equal(supersededBy(index, "c07e"), "a1f3");
  assert.equal(supersededBy(index, "f4b1"), "c07e");
  assert.equal(supersededBy(index, "a1f3"), null, "a chain root replaces nothing");

  assert.equal(isSuperseded(index, "a1f3"), true);
  assert.equal(isSuperseded(index, "c07e"), true, "superseded by a claim in another document");
  assert.equal(isSuperseded(index, "f4b1"), false, "the head of the chain holds now");
  assert.equal(isSuperseded(index, "9d20"), false);
  assert.equal(isSuperseded(index, null), false);

  const successor = index.successorOf.get("c07e");
  assert.equal(successor.anchor, "f4b1");
  assert.equal(successor.path, "memory/topics/supply.md");
  assert.equal(successor.documentId, "d-topics", "the chip needs the id to jump cross-page");
});

test("the current view of a page hides only what a successor replaced", () => {
  const index = buildSupersessionIndex(DOCS);
  assert.deepEqual(
    currentClaims(PEOPLE, index).map((c) => c.anchor),
    ["9d20"],
    "both of the chain's earlier states are history; the unrelated claim stays",
  );
  assert.equal(supersededCount(PEOPLE, index), 2);
  assert.equal(supersededCount(TOPICS, index), 0);
  assert.equal(documentHasSupersession(PEOPLE, index), true);
  assert.equal(
    documentHasSupersession(TOPICS, index),
    true,
    "a page holding only a successor still takes part in a chain",
  );
  assert.equal(
    documentHasSupersession({ path: "x", document_id: "x", claims: [claim("ab12", "- x")] }, index),
    false,
  );
});

test("a chain reads root first, from any member", () => {
  const index = buildSupersessionIndex(DOCS);
  assert.deepEqual(supersessionChain(index, "a1f3"), ["a1f3", "c07e", "f4b1"]);
  assert.deepEqual(supersessionChain(index, "c07e"), ["a1f3", "c07e", "f4b1"]);
  assert.deepEqual(supersessionChain(index, "f4b1"), ["a1f3", "c07e", "f4b1"]);
  assert.deepEqual(supersessionChain(index, "9d20"), ["9d20"], "a claim in no chain is its own");
  assert.deepEqual(supersessionChain(index, null), []);
});

test("a cycle in a hand-edited repository is walked once, not forever", () => {
  const cyclic = [
    {
      document_id: "d",
      path: "d.md",
      frontmatter: {},
      body: "",
      claims: [
        claim("aaaa", "- a <!-- c:aaaa --> <!-- supersedes: c:bbbb -->"),
        claim("bbbb", "- b <!-- c:bbbb --> <!-- supersedes: c:aaaa -->"),
        claim("cccc", "- c <!-- c:cccc --> <!-- supersedes: c:cccc -->"),
      ],
    },
  ];
  const index = buildSupersessionIndex(cyclic);
  assert.deepEqual(supersessionChain(index, "aaaa").sort(), ["aaaa", "bbbb"]);
  assert.equal(index.supersedes.has("cccc"), false, "a claim cannot supersede itself");
});

test("the raw supersedes comment never reaches the reader's prose", () => {
  const block = "- 自 2026-05 起任采购总监 [cite: s02 ¶3] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->";
  const cleaned = cleanClaimText(block, "list_item");
  assert.equal(cleaned.md, "自 2026-05 起任采购总监");
  assert.equal(cleaned.supersedes, "a1f3", "stripped, but captured rather than lost");

  const shown = displayClaim({ anchor: "c07e", kind: "list_item", text: block, citations: [], flags: [] });
  assert.equal(shown.md, "自 2026-05 起任采购总监");
  assert.equal(shown.supersedes, "a1f3");

  // A machinery comment this build does not know yet is still a comment, not prose.
  assert.equal(
    cleanClaimText("- x <!-- c:aaaa --> <!-- some-future-mark: 1 -->", "list_item").md,
    "x",
  );
});
