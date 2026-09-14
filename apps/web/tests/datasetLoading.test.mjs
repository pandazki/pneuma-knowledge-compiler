import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/datasetLoading.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { needsCanonicalDataset } = await import(moduleUrl);

test("only canonical readers trigger the expensive dataset projection", () => {
  assert.equal(needsCanonicalDataset("library"), true);
  // The structure lens reads a report the service derives, not the projection (§5.1).
  assert.equal(needsCanonicalDataset("lens"), false);

  for (const view of [
    "overview",
    "sources",
    "ingest",
    "process",
    "recall",
    "ask",
    "live_context",
    "history",
    "evolve",
    "profile",
    "components",
  ]) {
    assert.equal(needsCanonicalDataset(view), false, view);
  }
});
