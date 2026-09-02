/**
 * Which caveat a spend line is owed.
 *
 * The property under test is that "nobody declared a price" and "some of these calls
 * reported nothing" are told apart. They both end in a line with tokens and no money, and a
 * reader who is handed the wrong one goes and declares rates — and still gets no number.
 *
 * The module is transpiled standalone (its only import is a type, which esbuild strips), so
 * this needs no DOM and no store.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/views/consultations/spendNote.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { spendNote, unmeasuredCount } = await import(moduleUrl);

const MONEY = { amount: 0.0421, currency: "USD" };

test("a window where every call reported its counters, and is priced, says nothing", () => {
  const spend = { consultations: 4, with_usage: 4, incomplete: false, cost: MONEY };
  assert.equal(spendNote(spend), null);
  assert.equal(unmeasuredCount(spend), 0);
});

test("measured but unpriced is the deployment's missing rate card", () => {
  assert.equal(
    spendNote({ consultations: 4, with_usage: 4, incomplete: false, cost: null }),
    "unpriced",
  );
});

test("a call that reported no usage marks the window incomplete, and says so instead", () => {
  // The tokens are a floor and the money withdrew; saying "no prices declared" here would
  // send the reader off to declare rates that still could not produce a number.
  const spend = { consultations: 4, with_usage: 3, incomplete: true, cost: null };
  assert.equal(spendNote(spend), "incomplete");
  assert.equal(unmeasuredCount(spend), 1);
  // …and it still wins over a priced deployment, because the gap is in the data.
  assert.equal(
    spendNote({ consultations: 4, with_usage: 3, incomplete: true, cost: MONEY }),
    "incomplete",
  );
});
