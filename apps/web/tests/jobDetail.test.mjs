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
const {
  countWaitingForSteward,
  detailLines,
  isPausedDetail,
  isWaitingDetail,
  parseJobsSummary,
  splitGateDetail,
} = await import(moduleUrl);

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

test("only queued jobs addressed to the Steward are counted as waiting for one", () => {
  assert.equal(
    countWaitingForSteward([
      { waiting_for: "steward" },
      { waiting_for: "worker" },
      { waiting_for: "steward" },
      { waiting_for: null },
      {},
    ]),
    2,
  );
  assert.equal(countWaitingForSteward(null), 0);
  assert.equal(countWaitingForSteward([]), 0);
});

/* ------------------------------------------------------------------ waiting jobs */

test("a parked job's note is one line, not two findings", () => {
  const detail = "waiting: provider_unavailable; retry at 2026-09-15T10:04:00Z (attempt 2)";
  assert.equal(isWaitingDetail(detail), true);
  assert.deepEqual(detailLines(detail), [detail]);
  // Everything else still reads as the findings it is.
  assert.equal(isWaitingDetail("gate refused; two reasons"), false);
  assert.deepEqual(detailLines("gate refused; two reasons"), ["gate refused", "two reasons"]);
  assert.deepEqual(detailLines(null), []);
});

test("the queue summary parses, and drops reasons nothing is waiting for", () => {
  const summary = parseJobsSummary({
    queued: 4,
    waiting: {
      count: 3,
      reasons: [
        { reason: "provider_unavailable", count: 2, next_retry_at: "2026-09-15T10:04:00Z" },
        { reason: "harness_dead", count: 1, next_retry_at: null },
        { reason: "", count: 5, next_retry_at: null },
        { reason: "drained", count: 0, next_retry_at: null },
        "not an object",
      ],
    },
    paused: {
      count: 2,
      reasons: [{ reason: "retries_exhausted", count: 2, since: "2026-09-15T08:00:00Z" }],
    },
    claimed: 1,
    failed: 2,
    succeeded: 59,
  });
  assert.deepEqual(summary, {
    queued: 4,
    waiting: {
      count: 3,
      reasons: [
        { reason: "provider_unavailable", count: 2, next_retry_at: "2026-09-15T10:04:00Z" },
        { reason: "harness_dead", count: 1, next_retry_at: null },
      ],
    },
    paused: {
      count: 2,
      reasons: [{ reason: "retries_exhausted", count: 2, since: "2026-09-15T08:00:00Z" }],
    },
    claimed: 1,
    failed: 2,
    succeeded: 59,
  });
});

test("a summary from an engine that has no paused state yet reads as zero paused", () => {
  const summary = parseJobsSummary({
    queued: 1,
    waiting: { count: 1, reasons: [{ reason: "provider_unavailable", count: 1 }] },
    claimed: 0,
    failed: 0,
    succeeded: 3,
  });
  assert.deepEqual(summary.paused, { count: 0, reasons: [] });
  // A waiting reason with no stamp is still a reason; only the stamp is missing.
  assert.deepEqual(summary.waiting.reasons, [
    { reason: "provider_unavailable", count: 1, next_retry_at: null },
  ]);
});

test("a paused note is one line too, and the two parked states are told apart", () => {
  const detail =
    "paused: provider_unavailable; 5 attempts over 42m; resume with pkc jobs resume";
  assert.equal(isPausedDetail(detail), true);
  assert.equal(isWaitingDetail(detail), false);
  assert.deepEqual(detailLines(detail), [detail]);
  assert.equal(isPausedDetail("waiting: provider_unavailable; retry at X (attempt 1)"), false);
  assert.equal(isPausedDetail(null), false);
});

test("an empty queue says nothing is waiting, and a non-document is not a summary", () => {
  assert.deepEqual(parseJobsSummary({ queued: 0, claimed: 0, failed: 0, succeeded: 0 }), {
    queued: 0,
    waiting: { count: 0, reasons: [] },
    paused: { count: 0, reasons: [] },
    claimed: 0,
    failed: 0,
    succeeded: 0,
  });
  // A 404 body is not a summary; neither is an array or a bare value.
  assert.equal(parseJobsSummary({ detail: "Not Found" })?.waiting.count, 0);
  assert.equal(parseJobsSummary({ detail: "Not Found" })?.paused.count, 0);
  assert.equal(parseJobsSummary([]), null);
  assert.equal(parseJobsSummary(null), null);
  assert.equal(parseJobsSummary("waiting"), null);
});
