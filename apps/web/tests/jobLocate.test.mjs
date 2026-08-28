/**
 * The deep-link walk through the job ledger. The case that matters most is the one that hung
 * in production: opening the link while the FIRST page is what is loaded must step forward,
 * not "restart" onto the page it is already reading.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/jobLocate.ts", import.meta.url);
const transformed = await transformWithEsbuild(
  await readFile(sourceUrl, "utf8"),
  sourceUrl.pathname,
  { loader: "ts", format: "esm", target: "es2022" },
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { locateStep } = await import(moduleUrl);

const page = (ids, loadedCursor, nextCursor) => ({ ids, loadedCursor, nextCursor });

test("a job on the loaded page is found, whatever the walk state", () => {
  const step = locateStep(null, "j2", page(["j1", "j2"], null, "c1"), 8);
  assert.deepEqual(step, { kind: "found", walk: { id: "j2", pagesWalked: -1 } });
});

test("a fresh link opened on the first page advances from it instead of re-requesting it", () => {
  const step = locateStep(null, "j9", page(["j1", "j2"], null, "c1"), 8);
  assert.deepEqual(step, { kind: "advance", walk: { id: "j9", pagesWalked: 1 }, cursor: "c1" });
});

test("a fresh link opened on a later page restarts from the top", () => {
  const step = locateStep(null, "j9", page(["j5", "j6"], "c2", "c3"), 8);
  assert.deepEqual(step, { kind: "restart", walk: { id: "j9", pagesWalked: 0 } });
});

test("a walk in progress keeps stepping until the bound, then gives up", () => {
  const walking = { id: "j9", pagesWalked: 3 };
  assert.deepEqual(locateStep(walking, "j9", page(["j7"], "c3", "c4"), 8), {
    kind: "advance",
    walk: { id: "j9", pagesWalked: 4 },
    cursor: "c4",
  });
  const atBound = { id: "j9", pagesWalked: 8 };
  assert.deepEqual(locateStep(atBound, "j9", page(["j7"], "c8", "c9"), 8), {
    kind: "give-up",
    walk: { id: "j9", pagesWalked: -1 },
  });
  assert.deepEqual(locateStep(walking, "j9", page(["j7"], "c3", null), 8), {
    kind: "give-up",
    walk: { id: "j9", pagesWalked: -1 },
  });
});

test("a finished search stays finished when a poll lands a new page", () => {
  const done = { id: "j9", pagesWalked: -1 };
  assert.deepEqual(locateStep(done, "j9", page(["j1"], null, "c1"), 8), { kind: "settled" });
});

test("a different job id starts its own walk", () => {
  const done = { id: "j9", pagesWalked: -1 };
  const step = locateStep(done, "j3", page(["j1"], null, "c1"), 8);
  assert.equal(step.kind, "advance");
  assert.deepEqual(step.walk, { id: "j3", pagesWalked: 1 });
});
