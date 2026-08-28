/**
 * Ask's briefing switch.
 *
 * The bug this guards: `askCache` held the briefing, the thread and the draft question, and
 * each of the three places that changed the briefing (build, rebuild, pick a past one) wrote
 * only the briefing — so the previous pack's turns stayed on screen and the next question was
 * asked against a thread that belonged to a different briefing. The fix is that the switch is
 * a single patch, computed here; `store.selectBriefing` is its only caller, and `setAskCache`
 * cannot reach `briefing` at all.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/ask.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { briefingSelection, briefingTextLines } = await import(moduleUrl);

const BRIEFING = {
  briefing_id: "b2",
  snapshot_ref: "abc123",
  claims_count: 4,
  source_count: 2,
  char_count: 900,
};

test("selecting a briefing carries no thread and no draft question over", () => {
  assert.deepEqual(briefingSelection(BRIEFING), {
    briefing: BRIEFING,
    turns: [],
    question: "",
  });
});

test("dropping back to the builder clears the thread the same way", () => {
  assert.deepEqual(briefingSelection(null), {
    briefing: null,
    turns: [],
    question: "",
  });
});

test("the patch names every field of the cache that belongs to one briefing", () => {
  // A field added to the cache and forgotten here is exactly how the bug happened.
  assert.deepEqual(Object.keys(briefingSelection(null)).sort(), [
    "briefing",
    "question",
    "turns",
  ]);
});

test("line count reads a pack the way the panel shows it", () => {
  assert.equal(briefingTextLines(""), 0);
  assert.equal(briefingTextLines("one line"), 1);
  assert.equal(briefingTextLines("a\nb\nc"), 3);
  // A trailing newline opens a last, empty line — the panel scrolls to it.
  assert.equal(briefingTextLines("a\n"), 2);
});
