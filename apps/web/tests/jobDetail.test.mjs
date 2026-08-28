/**
 * A gate rejection is several findings joined with `; `. The ledger shows them as the lines
 * they were, because "how many things went wrong" is the first question a failed job raises.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/jobDetail.ts", import.meta.url);
const transformed = await transformWithEsbuild(
  await readFile(sourceUrl, "utf8"),
  sourceUrl.pathname,
  { loader: "ts", format: "esm", target: "es2022" },
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { splitGateDetail } = await import(moduleUrl);

test("a joined gate rejection becomes one line per finding", () => {
  assert.deepEqual(
    splitGateDetail(
      "citation names a source not in this round: 430784c5; overview block rests on no claim; people.alias_undecided",
    ),
    [
      "citation names a source not in this round: 430784c5",
      "overview block rests on no claim",
      "people.alias_undecided",
    ],
  );
});

test("a single-sentence detail stays one line, and an empty one is nothing", () => {
  assert.deepEqual(splitGateDetail("worker restarted mid-compile"), [
    "worker restarted mid-compile",
  ]);
  assert.deepEqual(splitGateDetail(""), []);
  assert.deepEqual(splitGateDetail(null), []);
  assert.deepEqual(splitGateDetail(undefined), []);
});

test("a semicolon with no space after it is inside a sentence, not between two", () => {
  // The gate joins on "; ". `a;b` is one finding that happens to contain a semicolon.
  assert.deepEqual(splitGateDetail("expected a;b, got c"), ["expected a;b, got c"]);
  assert.deepEqual(splitGateDetail("  spaced  ;   out  "), ["spaced", "out"]);
});
