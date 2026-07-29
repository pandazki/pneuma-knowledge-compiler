import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/citations.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { buildCitationNumbers, citationKey, presentCitationSource } = await import(moduleUrl);

test("citationKey identifies a document-level source span", () => {
  assert.equal(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    "source-a:3-4",
  );
  assert.equal(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
  );
  assert.notEqual(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    citationKey({ sourceId: "source-a", blockStart: 4, blockEnd: 4 }),
  );
});

test("buildCitationNumbers keeps one document-wide ledger across claims", () => {
  const citations = [
    { sourceId: "source-a", blockStart: 0, blockEnd: 0 },
    { sourceId: "source-a", blockStart: 1, blockEnd: 1 },
    { sourceId: "source-b", blockStart: 3, blockEnd: 4 },
  ];
  const numbers = buildCitationNumbers(citations);

  assert.equal(numbers.get(citationKey(citations[0])), 1);
  assert.equal(numbers.get(citationKey(citations[1])), 2);
  assert.equal(numbers.get(citationKey(citations[2])), 3);
});

test("presentCitationSource prefers a real title and preserves readable metadata", () => {
  const result = presentCitationSource({
    sourceId: "f3d9d7ae05b6bf12accc4f4e095ceec1",
    title: "报价边界确认",
    kind: "email",
    capturedAt: "2026-07-29T10:50:55+00:00",
  });

  assert.equal(result.title, "报价边界确认");
  assert.match(result.description, /^邮件 · /);
  assert.match(result.description, /2026/);
});

test("presentCitationSource synthesizes a readable fallback instead of exposing an id", () => {
  const sourceId = "f3d9d7ae05b6bf12accc4f4e095ceec1";
  const result = presentCitationSource({
    sourceId,
    title: sourceId,
    kind: "email",
    capturedAt: "2026-07-29T10:50:55+00:00",
  });

  assert.doesNotMatch(result.title, new RegExp(sourceId));
  assert.match(result.title, /2026.*邮件/);
  assert.equal(result.description, "原始标题缺失");
});
