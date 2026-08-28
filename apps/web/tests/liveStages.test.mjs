/**
 * The live fold (`liveStages` in `lib/stages.ts`) — stage events into the rows the diagram
 * draws, while the lane is still running.
 *
 * What makes this worth pinning is that the reducer knows NO VOCABULARY and no lane. It reads
 * three structural things only: a `start` opens a node under its key, an `end` settles it, and
 * `total` is the one that wraps the rest. Everything else — how many turns an agentic run
 * took, whether two retrieval lanes overlapped, whether a stage was measured four times — is
 * the lane's business and arrives as data.
 *
 * The clock is an ARGUMENT, never something the fold reads, which is the only reason a
 * ticking counter can be tested at all: `liveStages(events, now)` is pure, so "the counter
 * advanced 500ms" is an assertion about a return value rather than about a wall clock.
 *
 * The counter measures the STAGE, not the lane. `at_ms` places an event on the lane's
 * timeline and is deliberately not what ticks: a stage that opened three seconds into a lane
 * has been running for zero, and a counter that started at three would jump backwards to the
 * real measurement the moment the stage settled — which would make the measured number look
 * wrong too.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const { liveStages, stageFlow, finishedStages, previewRows, stampReceived, slowestStage } =
  await import(
  await tsModuleUrl(new URL("../src/lib/stages.ts", import.meta.url))
);

const T0 = 1_700_000_000_000;

const start = (name, at_ms, key = name, received = T0) => ({
  name,
  key,
  phase: "start",
  at_ms,
  received,
});
const end = (name, at_ms, ms, extra = {}) => ({
  name,
  key: extra.key ?? name,
  phase: "end",
  at_ms,
  ms,
  status: extra.status ?? "ran",
  detail: extra.detail ?? null,
  preview: extra.preview ?? null,
});

const byName = (rows) => Object.fromEntries(rows.map((r) => [r.name, r]));

test("a stage that has started and not ended is running, and its counter ticks", () => {
  // The server said "plan opened 200ms into the lane"; half a second of client time has
  // passed since that frame arrived. The stage has therefore been running 500ms — the lane's
  // 200ms offset belongs to whatever ran BEFORE plan and is not plan's to claim.
  const rows = liveStages([start("plan", 200)], T0 + 500);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].running, true);
  assert.equal(rows[0].ms, 500);
});

test("a settling stage never jumps backwards — the counter and the measurement agree", () => {
  // The one failure mode a live counter has: showing a bigger number than the truth, then
  // shrinking. Pinned as the two readings around a single `end`.
  const events = [start("answer", 3000), end("answer", 5000, 2000)];
  const running = liveStages(events.slice(0, 1), T0 + 1900)[0];
  const settled = liveStages(events, T0 + 2000)[0];
  assert.equal(running.ms, 1900);
  assert.equal(settled.ms, 2000);
  assert.ok(settled.ms >= running.ms, "settling may round up, never down");
});

test("an end freezes the stage at the duration the server measured", () => {
  const rows = liveStages([start("plan", 200), end("plan", 900, 640)], T0 + 5000);
  // Not 5200: a settled stage reports the measurement, and the client clock stops mattering.
  assert.deepEqual(
    { running: rows[0].running, ms: rows[0].ms, status: rows[0].status },
    { running: false, ms: 640, status: "ran" },
  );
});

test("a degraded end carries the lane's own reason, not one invented here", () => {
  const rows = liveStages([
    start("rerank", 10),
    end("rerank", 90, 80, { status: "degraded", detail: "timeout" }),
  ]);
  assert.equal(rows[0].status, "degraded");
  assert.equal(rows[0].detail, "timeout");
});

test("a stage that ends without ever starting is still shown", () => {
  // A dropped frame, or a lane that only records after the fact, must never be able to make
  // a measured stage vanish from the diagram.
  const rows = liveStages([end("total", 4001, 4001)]);
  assert.deepEqual(byName(rows).total, {
    key: "total",
    name: "total",
    ms: 4001,
    status: "ran",
    detail: null,
    preview: null,
    running: false,
  });
});

test("a stage measured again reopens the same node instead of forking a second one", () => {
  // fast's `assemble` is measured several times across the lane and is ONE stage: the server
  // sends the running total on every end, so the node grows rather than resetting.
  const events = [
    start("assemble", 100),
    end("assemble", 130, 30),
    start("assemble", 900),
    end("assemble", 950, 80),
  ];
  const mid = liveStages(events.slice(0, 3), T0 + 200);
  assert.equal(mid.length, 1);
  assert.equal(mid[0].running, true);
  // 30ms already measured, 200ms of client time since the reopen: the counter continues
  // from what the stage had rather than restarting at zero.
  assert.equal(mid[0].ms, 230);

  const done = liveStages(events, T0 + 9999);
  assert.equal(done.length, 1);
  assert.equal(done[0].ms, 80);
  assert.equal(done[0].running, false);
});

test("concurrent children are all running at once and fan out under their parent", () => {
  const rows = liveStages(
    [
      start("retrieve", 0),
      start("retrieve.claims", 5),
      start("retrieve.windows", 6),
      start("retrieve.glance", 7),
      end("retrieve.claims", 640, 635),
    ],
    T0 + 900,
  );
  const named = byName(rows);
  assert.equal(named["retrieve.claims"].running, false);
  assert.equal(named["retrieve.windows"].running, true);
  assert.equal(named["retrieve.glance"].running, true);
  assert.equal(named.retrieve.running, true);

  const { nodes } = stageFlow(rows);
  assert.deepEqual(
    nodes.map((n) => n.name),
    ["retrieve"],
    "the children hang off the gather rather than sitting beside it",
  );
  assert.deepEqual(
    nodes[0].children.map((c) => c.leaf),
    ["claims", "windows", "glance"],
  );
});

test("an agentic lane keys on the step, so one tool called twice is two nodes", () => {
  const rows = liveStages([
    start("turn:1", 0, "turn:1#1"),
    end("turn:1", 800, 800, { key: "turn:1#1" }),
    start("tool:search_claims", 800, "tool:search_claims#2"),
    end("tool:search_claims", 950, 150, { key: "tool:search_claims#2" }),
    start("tool:search_claims", 950, "tool:search_claims#3"),
    end("tool:search_claims", 1100, 150, { key: "tool:search_claims#3" }),
  ]);
  assert.equal(rows.length, 3);
  assert.deepEqual(
    rows.map((r) => r.name),
    ["turn:1", "tool:search_claims", "tool:search_claims"],
  );
  assert.equal(new Set(rows.map((r) => r.key)).size, 3);
});

test("total is moved last however the events ordered it", () => {
  const rows = liveStages([
    end("total", 4001, 4001),
    start("answer", 900),
    end("answer", 4000, 3100),
  ]);
  assert.deepEqual(
    rows.map((r) => r.name),
    ["answer", "total"],
  );
});

test("the slowest stage ignores anything still running — a counter is not a measurement", () => {
  const rows = liveStages(
    [start("answer", 0), start("plan", 0, "plan"), end("plan", 90, 90)],
    T0 + 60_000,
  );
  assert.equal(slowestStage(rows).name, "plan");
});

test("no events is no diagram, and a finished answer folds into the same rows", () => {
  assert.deepEqual(liveStages([]), []);
  assert.deepEqual(liveStages(null), []);
  const finished = finishedStages([
    { name: "plan", ms: 0, status: "skipped", detail: null },
    { name: "answer", ms: 3120, status: "ran", detail: null },
  ]);
  assert.deepEqual(
    finished.map((r) => [r.name, r.ms, r.running]),
    [
      ["plan", 0, false],
      ["answer", 3120, false],
    ],
  );
});

test("arrival time is stamped at the edge so the fold itself stays pure", () => {
  const stamped = stampReceived({ name: "plan", key: "plan", phase: "start", at_ms: 12 }, T0);
  assert.equal(stamped.received, T0);
  // Unstamped, a running stage falls back to `now`, so its counter reads zero and does not
  // advance — never a wrong number, just one that stands still.
  assert.equal(liveStages([start("plan", 250, "plan", undefined)], T0)[0].ms, 0);
});

/* ------------------------------------------------- the strip, and who drives it */

const [stripSource, recallSource, askSource, apiSource] = await Promise.all([
  readFile(new URL("../src/views/_shared/StageStrip.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/views/recall/RecallView.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/views/ask/AskView.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
]);

test("one strip draws both the live lane and the finished answer", () => {
  // If the live picture were a second component it could disagree with the final one, which
  // is exactly the drift this whole feature exists to remove.
  assert.match(stripSource, /live\?: FlowStage\[\] \| null;/);
  assert.match(stripSource, /stages\?: StageTiming\[\] \| null;/);
});

test("every lane that costs seconds is watched, and none of them skeletons instead", () => {
  assert.match(recallSource, /recallStream\(/, "recall streams both answering lanes");
  assert.doesNotMatch(recallSource, /recallAnswer\(/, "no lane falls back to the plain POST");
  assert.match(askSource, /buildBriefingStream\(/);
  assert.match(askSource, /askBriefingStream\(/);
  for (const [name, source] of [
    ["RecallView", recallSource],
    ["AskView", askSource],
  ]) {
    assert.match(source, /useLiveLane/, `${name} folds the stream's events`);
    assert.match(source, /live=\{/, `${name} hands the strip its live rows`);
  }
});

test("one SSE parser serves every stream rather than a third hand-rolled reader", () => {
  assert.equal(apiSource.split("async function readEventStream(").length - 1, 1);
  for (const client of [
    "export async function recallStream(",
    "export async function buildBriefingStream(",
    "export async function askBriefingStream(",
  ]) {
    assert.ok(apiSource.includes(client), `${client} exists`);
  }
});


/* ------------------------------------------------------------------ previews */

test("a preview arrives with the node's end and is kept when the node reopens", () => {
  // fast's `assemble` is measured several times and is ONE node. Blanking the panel a reader
  // has open, between two passes of the same stage, would read as the fact being withdrawn.
  const rows = liveStages([
    start("assemble", 100),
    end("assemble", 130, 30, { preview: { windows: 8 } }),
    start("assemble", 900),
  ]);
  assert.deepEqual(byName(rows).assemble.preview, { windows: 8 });
  // Nothing has been previewed yet on a node that has only started.
  assert.equal(liveStages([start("plan", 10)])[0].preview, null);
});

test("a stage that previewed nothing carries null, never an empty object", () => {
  // "nothing to open" has to be distinguishable from "an empty panel": the strip only makes a
  // node clickable when there is something behind it.
  assert.equal(liveStages([start("plan", 0), end("plan", 40, 40)])[0].preview, null);
  assert.equal(
    finishedStages([{ name: "plan", ms: 0, status: "skipped", detail: null }])[0].preview,
    null,
  );
});

test("a finished answer's preview reaches the diagram through the same rows", () => {
  const rows = finishedStages([
    { name: "route", ms: 900, status: "ran", detail: null, preview: { offered: 2 } },
  ]);
  const { nodes } = stageFlow(rows);
  assert.deepEqual(nodes[0].preview, { offered: 2 });
});

test("preview rows print whatever the lane sent, one level deep", () => {
  assert.deepEqual(previewRows(null), []);
  assert.deepEqual(previewRows({ hits: 60 }), [{ key: "hits", value: "60" }]);
  // Arrays of plain strings are joined — the service already truncated them and marked it.
  assert.deepEqual(previewRows({ tool_calls: ['person(alias="Wei")'] }), [
    { key: "tool_calls", value: 'person(alias="Wei")' },
  ]);
  // A nested object is its own key=value pairs on one line: a preview is a glance, and a
  // tree is not one.
  assert.deepEqual(previewRows({ chosen: { claims: 12, windows: 8 } }), [
    { key: "chosen", value: "claims=12, windows=8" },
  ]);
  assert.deepEqual(previewRows({ tool_calls: "none", detail: null }), [
    { key: "tool_calls", value: "none" },
    { key: "detail", value: "–" },
  ]);
  // A face that found nothing sends an empty list; "nothing came back" is what the
  // placeholder means, and a row printing nothing at all would read as a broken panel.
  assert.deepEqual(previewRows({ hits: 0, items: [] }), [
    { key: "hits", value: "0" },
    { key: "items", value: "–" },
  ]);
});

test("a list of entries becomes lines: what it says, where it is, then the id", () => {
  // The redesign, in the one place the viewer decides how a preview is laid out. The panel
  // prints `text` in normal type, `where` dim, `id` as a tiny mono tag — so the order here
  // IS the reading order, and an id can never again be the whole of a preview.
  const rows = previewRows({
    hits: 80,
    items: [
      { text: "The pilot ends in March.", doc: "Pilot", id: "c1a2b3c4" },
      { text: "The renewal is decided in April.", source: "Kickoff", span: "¶7-9" },
    ],
  });
  assert.deepEqual(rows[0], { key: "hits", value: "80" });
  assert.equal(rows[1].key, "items");
  assert.deepEqual(rows[1].items, [
    { text: "The pilot ends in March.", where: "Pilot", id: "c1a2b3c4" },
    { text: "The renewal is decided in April.", where: "Kickoff ¶7-9", id: "" },
  ]);
});

test("an entry stripped of its id by the bound still prints its words", () => {
  // `bound_preview` sheds `id`, then `span`, then the title before it shortens `text`. The
  // viewer must render what survives rather than depend on a field that is allowed to go.
  const [row] = previewRows({ items: [{ text: "The pilot ends in March." }] });
  assert.deepEqual(row.items, [
    { text: "The pilot ends in March.", where: "", id: "" },
  ]);
});

test("the truncation marker inside an entry list stays visible as its own line", () => {
  // The service marks a cut list with a trailing string. Dropping it because it is not an
  // object would silently turn "the first 5 of 80" into "5".
  const [row] = previewRows({
    items: [{ text: "The pilot ends in March.", id: "c1a2b3c4" }, "…+75 more"],
  });
  assert.deepEqual(row.items?.[1], { text: "…+75 more", where: "", id: "" });
});
