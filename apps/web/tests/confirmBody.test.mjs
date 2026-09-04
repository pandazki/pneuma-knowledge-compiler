// The confirm body is decided in one pure place: the three-valued `note` must survive the
// client. `null` omits (the plan's note stands); any string replaces; "" clears. The first
// version of the client collapsed "" into "omit", which made clearing a note impossible
// from the console — this test pins the serializer that fixed it.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/archive.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { confirmRequestBody } = await import(moduleUrl);

const ITEMS = [{ kind: "document", ref: "work/x.md", selected: true }];

test("an emptied note is sent as an empty string, never dropped", () => {
  assert.deepEqual(confirmRequestBody(undefined, ""), { note: "" });
  assert.deepEqual(confirmRequestBody(ITEMS, "   "), { items: ITEMS, note: "" });
});

test("an untouched note is omitted so the plan's note stands", () => {
  assert.deepEqual(confirmRequestBody(undefined, null), {});
  assert.deepEqual(confirmRequestBody(ITEMS, undefined), { items: ITEMS });
});

test("a typed note replaces, trimmed", () => {
  assert.deepEqual(confirmRequestBody(undefined, "  shipped in June  "), {
    note: "shipped in June",
  });
});
