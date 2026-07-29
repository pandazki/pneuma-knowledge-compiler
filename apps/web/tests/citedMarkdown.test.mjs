import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/citedMarkdown.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { prepareCitedMarkdown } = await import(moduleUrl);

test("cited markdown preserves structure and resolves multi-span handles", () => {
  const result = prepareCitedMarkdown(
    "## 决定\n\n> 原文 [cite: s01 ¶2-4, s02 ¶7]",
    { s01: "source-a", s02: "source-b" },
  );
  assert.match(result.markdown, /^## 决定/);
  assert.match(result.markdown, /^> 原文/m);
  assert.equal(
    result.markdown,
    "## 决定\n\n> 原文 [citation](cite-ref:0)[citation](cite-ref:1)",
  );
  assert.deepEqual(result.citations, [
    { sourceId: "source-a", blockStart: 2, blockEnd: 4 },
    { sourceId: "source-b", blockStart: 7, blockEnd: 7 },
  ]);
});

test("dead local handles remain visible instead of becoming clickable provenance", () => {
  const result = prepareCitedMarkdown("未解析 [cite: s99 ¶1]");
  assert.equal(result.markdown, "未解析 [cite: s99 ¶1]");
  assert.deepEqual(result.citations, []);
});
