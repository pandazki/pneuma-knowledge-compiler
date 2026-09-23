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

test("Steward source ids retain their complete Unicode-dash block ranges", () => {
  for (const dash of ["-", "–", "—"]) {
    const result = prepareCitedMarkdown(`A result [cite: demo-source ¶12${dash}35]`);
    assert.deepEqual(result.citations, [{ sourceId: "demo-source", blockStart: 12, blockEnd: 35 }]);
  }
});

test("citation examples inside code stay literal and do not consume footnote numbers", () => {
  for (const code of ["`[cite: sample ¶0-2]`", "```md\n[cite: sample ¶0-2]\n```", "~~~md\n[cite: sample ¶0-2]\n~~~"]) {
    const result = prepareCitedMarkdown(`${code}\n\nFact [cite: real-source ¶3-4]`);
    assert.equal(result.markdown, `${code}\n\nFact [citation](cite-ref:0)`);
    assert.deepEqual(result.citations, [{ sourceId: "real-source", blockStart: 3, blockEnd: 4 }]);
  }
});

test("incomplete and reversed citations do not become misleading source links", () => {
  for (const text of ["Fact [cite: demo ¶2-", "Fact [cite: demo ¶9-2]"]) {
    assert.deepEqual(prepareCitedMarkdown(text), { markdown: text, citations: [] });
  }
});
