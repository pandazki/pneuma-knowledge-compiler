import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/pagination.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { buildPageQuery, firstPage, nextPage, previousPage, visibleRange } =
  await import(moduleUrl);

test("page query encodes cursor and omits empty filters", () => {
  assert.equal(
    buildPageQuery({
      limit: 25,
      cursor: "cursor + slash/",
      query: "alpha beta",
      kind: null,
    }),
    "?limit=25&cursor=cursor+%2B+slash%2F&query=alpha+beta",
  );
});

test("cursor history moves forward and backward without guessing cursors", () => {
  const initial = firstPage();
  const second = nextPage(initial, "cursor-2");
  const third = nextPage(second, "cursor-3");

  assert.deepEqual(second, { cursor: "cursor-2", previous: [null] });
  assert.deepEqual(third, {
    cursor: "cursor-3",
    previous: [null, "cursor-2"],
  });
  assert.deepEqual(previousPage(third), {
    cursor: "cursor-2",
    previous: [null],
  });
  assert.deepEqual(previousPage(initial), initial);
});

test("visible range reports the current bounded page against the total", () => {
  assert.deepEqual(visibleRange(0, 25, 25, 98), { from: 1, to: 25, total: 98 });
  assert.deepEqual(visibleRange(3, 25, 23, 98), { from: 76, to: 98, total: 98 });
  assert.deepEqual(visibleRange(0, 25, 0, 0), { from: 0, to: 0, total: 0 });
});
