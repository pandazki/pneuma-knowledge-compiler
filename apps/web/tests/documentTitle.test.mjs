/**
 * The name a document is called by when ANOTHER page names it: the frontmatter title the
 * compile wrote, and the file stem only when there is none. The projection's `title` field
 * is the stem, which is why a connection row used to read "orbit-flow" beside a claim that
 * read "Orbit Flow".
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/model.ts", import.meta.url);
const transformed = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { documentDisplayTitle } = await import(moduleUrl);

test("a written frontmatter title wins over the file stem", () => {
  assert.equal(
    documentDisplayTitle({ title: "orbit-flow", frontmatter: { title: "Orbit Flow" } }),
    "Orbit Flow",
  );
});

test("an absent, blank or non-string frontmatter title falls back to the stem", () => {
  assert.equal(documentDisplayTitle({ title: "orbit-flow", frontmatter: {} }), "orbit-flow");
  assert.equal(documentDisplayTitle({ title: "orbit-flow", frontmatter: { title: "  " } }), "orbit-flow");
  assert.equal(documentDisplayTitle({ title: "a01", frontmatter: { title: 7 } }), "a01");
});
