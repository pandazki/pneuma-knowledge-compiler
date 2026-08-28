/**
 * The stage strip, as the viewer prepares it (`lib/stages.ts`) — for both answering lanes.
 *
 * The fast lane sends one flat, complete list every time and encodes the retrieval lanes as
 * dotted names. What is pinned here is the contract the strip depends on: the order the wire
 * chose survives, children nest under their parent, a skipped stage stays visibly skipped
 * rather than collapsing into `0ms`, and a child whose parent is missing is still shown
 * rather than silently dropped.
 *
 * The deep lane sends a DIFFERENT vocabulary — `turn:N` / `tool:<name>` / `finalize` — whose
 * membership is decided by the run, not by a fixed list. So the second half pins the property
 * that makes one helper serve both: the strip knows no vocabulary at all. It reads only the
 * two structural conventions (a dot nests, `total` wraps) and lays out anything else as it
 * arrives, colons and all.
 *
 * The ask page is the proof of that claim rather than a repeat of it: a briefing BUILD sends a
 * third fixed vocabulary this module has never heard of (`expand`, `pack`, `retrieve.passages`)
 * and a briefing ASK sends the agentic shape with its own tool names. Both lay out with no
 * change here — and the strip that paints them is the same component both views import.
 *
 * The rag lane is the fourth vocabulary and the proof once more: `embed` / `retrieve` with
 * `lexical` and `vector` children / `fuse` / `expand` / `total`, laid out by the same helper,
 * with one difference the layout is deliberately blind to — those children ran SEQUENTIALLY,
 * so they sum to their parent instead of exceeding it. The diagram draws the nesting either
 * way; the caption that says which it was is the caller's, which is why it is a prop.
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

const {
  stageTree,
  formatStageMs,
  stageStripText,
  slowestStage,
  laneOrdered,
  FAST_LANE_ORDER,
} = await import(
  await tsModuleUrl(new URL("../src/lib/stages.ts", import.meta.url))
);

const stage = (name, ms, status = "ran", detail = null) => ({ name, ms, status, detail });

/** A realistic payload: one routed path, a timed-out rerank, three stages that never ran. */
const WIRE = [
  stage("plan", 0, "skipped"),
  stage("retrieve", 812),
  stage("retrieve.claims", 640),
  stage("retrieve.windows", 806),
  stage("retrieve.glance", 0, "skipped"),
  stage("retrieve.path:person", 122),
  stage("route", 210),
  stage("rerank", 90, "degraded", "timeout"),
  stage("select", 0, "skipped"),
  stage("assemble", 31),
  stage("answer", 3120),
  stage("total", 4001),
];

test("the retrieval lanes nest under retrieve and everything else stays top level", () => {
  const roots = stageTree(WIRE);
  assert.deepEqual(
    roots.map((r) => r.name),
    ["plan", "retrieve", "route", "rerank", "select", "assemble", "answer", "total"],
  );
  const retrieve = roots.find((r) => r.name === "retrieve");
  assert.deepEqual(
    retrieve.children.map((c) => c.name),
    ["retrieve.claims", "retrieve.windows", "retrieve.glance", "retrieve.path:person"],
  );
  // A child prints its leaf, not its wire name — the parent is already on screen beside it.
  assert.deepEqual(
    retrieve.children.map((c) => c.leaf),
    ["claims", "windows", "glance", "path:person"],
  );
});

test("children keep their own durations even when they exceed their parent's", () => {
  const retrieve = stageTree(WIRE).find((r) => r.name === "retrieve");
  const windows = retrieve.children.find((c) => c.leaf === "windows");
  // 806 > 812 is impossible, but 806 close to 812 is the whole point: the parent is the
  // gather's wall-clock, and the slowest arm is what set it. Nothing rescales.
  assert.equal(windows.ms, 806);
  assert.equal(retrieve.ms, 812);
});

test("a child whose parent is absent is still shown rather than dropped", () => {
  const roots = stageTree([stage("answer", 10), stage("retrieve.claims", 5)]);
  assert.deepEqual(
    roots.map((r) => r.name),
    ["answer", "retrieve.claims"],
  );
});

test("stageTree tolerates a missing list", () => {
  assert.deepEqual(stageTree(undefined), []);
  assert.deepEqual(stageTree(null), []);
});

test("a duration reads as milliseconds until it is worth reading as seconds", () => {
  assert.equal(formatStageMs(0), "0ms");
  assert.equal(formatStageMs(812), "812ms");
  assert.equal(formatStageMs(999), "999ms");
  assert.equal(formatStageMs(1000), "1.0s");
  assert.equal(formatStageMs(4001), "4.0s");
});

test("the one-line strip marks skipped and degraded stages instead of printing 0ms", () => {
  assert.equal(
    stageStripText(WIRE),
    "plan – · retrieve 812ms (claims 640ms · windows 806ms · glance – · path:person 122ms)" +
      " · route 210ms · rerank 90ms!timeout · select – · assemble 31ms · answer 3.1s · total 4.0s",
  );
  // The placeholder is caller-supplied so the view can pass a translated "not run".
  assert.match(stageStripText([stage("plan", 0, "skipped")], "not run"), /^plan not run$/);
});

test("the slowest stage ignores total and can be a retrieval lane", () => {
  assert.equal(slowestStage(WIRE).name, "answer");
  const retrievalBound = WIRE.filter((s) => s.name !== "answer");
  assert.equal(slowestStage(retrievalBound).name, "retrieve");
  assert.equal(slowestStage([stage("plan", 0, "skipped")]), null);
  assert.equal(slowestStage([]), null);
});


/* ------------------------------------------------------------------ the deep lane */

/** One agentic run: two turns around two tool calls, a budget-forced finalize, total last. */
const DEEP_WIRE = [
  stage("turn:1", 1204),
  stage("tool:search_claims", 340),
  stage("tool:read_document", 12),
  stage("turn:2", 902),
  stage("finalize", 1100, "degraded", "budget"),
  stage("total", 3620),
];

test("the deep vocabulary is laid out as it arrives, colons and all", () => {
  const roots = stageTree(DEEP_WIRE);
  assert.deepEqual(
    roots.map((r) => r.name),
    ["turn:1", "tool:search_claims", "tool:read_document", "turn:2", "finalize", "total"],
  );
  // Nothing nests: a colon is not the dot, so `tool:x` is a stage, not a child of `tool`.
  assert.ok(roots.every((r) => r.children.length === 0));
  // And the label is the whole name — the leaf split is the dot's, not the colon's.
  assert.deepEqual(
    roots.map((r) => r.leaf),
    ["turn:1", "tool:search_claims", "tool:read_document", "turn:2", "finalize", "total"],
  );
});

test("total is shown last however the wire ordered it", () => {
  // A lane that reported its total first would otherwise read as one step among the steps.
  const shuffled = [DEEP_WIRE[5], ...DEEP_WIRE.slice(0, 5)];
  assert.deepEqual(
    stageTree(shuffled).map((r) => r.name),
    ["turn:1", "tool:search_claims", "tool:read_document", "turn:2", "finalize", "total"],
  );
});

test("the slowest deep stage is a real step, never the total that wraps them", () => {
  assert.equal(slowestStage(DEEP_WIRE).name, "turn:1");
});

test("the one-line deep strip reads as the run's own sequence", () => {
  assert.equal(
    stageStripText(DEEP_WIRE),
    "turn:1 1.2s · tool:search_claims 340ms · tool:read_document 12ms · turn:2 902ms" +
      " · finalize 1.1s!budget · total 3.6s",
  );
});


/* ------------------------------------------------------- the ask page's two vocabularies */

/** A briefing build: query half ran, no anchored sources, so `expand` is only the windows.
 * Unlike the fast lane's gather, the two lookups here run in SEQUENCE and sum to `retrieve`. */
const BUILD_WIRE = [
  stage("retrieve", 340),
  stage("expand", 480),
  stage("pack", 12),
  stage("total", 840),
  stage("retrieve.claims", 210),
  stage("retrieve.passages", 130),
];

/** The same build with no `scope.query` at all: the query half never happened, and says so. */
const SOURCES_ONLY_WIRE = [
  stage("retrieve", 0, "skipped"),
  stage("expand", 480),
  stage("pack", 12),
  stage("total", 495),
  stage("retrieve.claims", 0, "skipped"),
  stage("retrieve.passages", 0, "skipped"),
];

const ASK_WIRE = [
  stage("turn:1", 1180),
  stage("tool:search_knowledge", 340),
  stage("tool:fetch_verbatim", 12),
  stage("turn:2", 640),
  stage("finalize", 1120, "degraded", "budget"),
  stage("total", 3300),
];

test("a build vocabulary this module has never seen nests and orders itself", () => {
  const roots = stageTree(BUILD_WIRE);
  assert.deepEqual(
    roots.map((r) => r.name),
    ["retrieve", "expand", "pack", "total"],
    "total last, the rest in the order the build sent them",
  );
  assert.deepEqual(
    roots[0].children.map((c) => c.leaf),
    ["claims", "passages"],
    "the dot nests, whatever the leaves are called",
  );
  // Sequential children: they sum to their parent here, where the fast lane's overshoot it.
  // Nothing in the strip enforces either — it reports what the lane measured.
  assert.equal(
    roots[0].children.reduce((sum, c) => sum + c.ms, 0),
    roots[0].ms,
  );
});

test("a build half that never ran is shown as not run, never as 0ms", () => {
  assert.equal(
    stageStripText(SOURCES_ONLY_WIRE, "not run"),
    "retrieve not run (claims not run · passages not run) · expand 480ms · pack 12ms" +
      " · total 495ms",
  );
  // And it is not the slowest anything: a skipped stage is not a fast stage.
  assert.equal(slowestStage(SOURCES_ONLY_WIRE).name, "expand");
});

test("an ask reads as the round's own sequence, tool names and all", () => {
  assert.equal(
    stageStripText(ASK_WIRE),
    "turn:1 1.2s · tool:search_knowledge 340ms · tool:fetch_verbatim 12ms · turn:2 640ms" +
      " · finalize 1.1s!budget · total 3.3s",
  );
  assert.equal(slowestStage(ASK_WIRE).name, "turn:1");
});

/* ------------------------------------------------------------------ the rag vocabulary */

/** The rag lane, complete: a fan-out for a search that reaches no model at all. */
const RAG_WIRE = [
  stage("embed", 41),
  stage("retrieve", 210),
  stage("retrieve.lexical", 60),
  stage("retrieve.vector", 149),
  stage("fuse", 2),
  stage("expand", 1),
  stage("total", 255),
];

test("the rag vocabulary nests and orders with no change to the layout helper", () => {
  const tree = stageTree(RAG_WIRE);
  assert.deepEqual(
    tree.map((n) => n.name),
    ["embed", "retrieve", "fuse", "expand", "total"],
  );
  assert.deepEqual(
    tree[1].children.map((n) => n.leaf),
    ["lexical", "vector"],
  );
  assert.equal(tree.at(-1).name, "total");
});

test("rag children SUM to their parent — a sequential chain, not a gather", () => {
  // The fast lane's children exceed theirs; nothing in the strip cares either way, which is
  // exactly why one helper serves both. This pins the arithmetic the caption promises.
  const tree = stageTree(RAG_WIRE);
  const children = tree[1].children.reduce((n, c) => n + c.ms, 0);
  assert.ok(children <= tree[1].ms, "lexical + vector fit inside retrieve");
  assert.equal(slowestStage(RAG_WIRE).leaf, "retrieve");
});

test("a rag embed a caller supplied the vector for reads as not-run, never as free", () => {
  const skipped = RAG_WIRE.map((s) =>
    s.name === "embed" ? stage("embed", 0, "skipped") : s,
  );
  assert.equal(
    stageStripText(skipped),
    "embed – · retrieve 210ms (lexical 60ms · vector 149ms) · fuse 2ms · expand 1ms · total 255ms",
  );
});

/* --------------------------------------------------- one strip, imported by both surfaces */

const [stripSource, recallSource, askSource, askMessages, recallMessages] = await Promise.all([
  readFile(new URL("../src/views/_shared/StageStrip.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/views/recall/RecallView.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/views/ask/AskView.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/i18n/ask.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/i18n/recall.ts", import.meta.url), "utf8"),
]);

test("the strip lives in _shared and both views import it rather than owning one", () => {
  for (const [name, source] of [
    ["RecallView", recallSource],
    ["AskView", askSource],
  ]) {
    assert.match(
      source,
      /import \{ StageStrip \} from "\.\.\/_shared\/StageStrip";/,
      `${name} imports the shared strip`,
    );
    assert.doesNotMatch(source, /function StageStrip\(/, `${name} defines no strip of its own`);
  }
});

test("the strip takes its sentence from the caller, because the caveat is the lane's", () => {
  // The concurrency note under a fast strip is false under a sequential build, so the
  // description cannot live in the shared component — it is a prop, and every caller passes
  // one that is true of its own lane.
  assert.match(stripSource, /description: string;/);
  assert.doesNotMatch(stripSource, /descriptionDeep/);
  for (const key of ["ask.stages.buildDescription", "ask.stages.askDescription"]) {
    assert.ok(askSource.includes(key), `AskView passes ${key}`);
    assert.equal(
      askMessages.split(`"${key}"`).length - 1,
      2,
      `${key} is written in both languages`,
    );
  }
  // rag's caption is its own for the same reason: its children are sequential, so the fast
  // lane's "they add up to more than retrieve" would be a lie above a rag diagram.
  for (const key of [
    "recall.stages.description",
    "recall.stages.descriptionDeep",
    "recall.stages.descriptionRag",
  ]) {
    assert.ok(recallSource.includes(key), `RecallView passes ${key}`);
    assert.equal(
      recallMessages.split(`"${key}"`).length - 1,
      2,
      `${key} is written in both languages`,
    );
  }
});

test("the rag lane streams, and the finished panel redraws the same measurement", () => {
  // The whole point of one clock: what the reader watched and what lands must be one list.
  assert.match(recallSource, /ragStream\(/, "rag runs over the stream client");
  assert.doesNotMatch(recallSource, /await recall\(currentUser/, "no plain-POST rag path left");
  assert.match(recallSource, /<StageStrip stages=\{rag\.stages\}/, "the finished panel redraws it");
});

/* -------------------------------------------------- a mechanical lane's fixed order */

const live = (name, ms, status = "ran") => ({
  key: name,
  name,
  ms,
  status,
  detail: null,
  preview: null,
  running: false,
});

test("a mechanical lane is drawn in ITS order, not in the order events happened to arrive", () => {
  // `assemble` is measured before `select` is reached, so arrival order put it first and the
  // finished answer then put it back — the strip visibly rearranged itself as the answer
  // landed. Place belongs to the lane; only duration belongs to the run.
  const arrived = [live("retrieve", 812), live("assemble", 40), live("select", 300)];
  assert.deepEqual(
    laneOrdered(arrived, FAST_LANE_ORDER)
      .filter((row) => row.status !== "pending")
      .map((row) => row.name),
    ["retrieve", "select", "assemble"],
  );
});

test("stages the lane has not reached stand as pending placeholders, never as skipped", () => {
  const rows = laneOrdered([live("retrieve", 812)], FAST_LANE_ORDER);
  assert.deepEqual(rows.map((row) => row.name), [...FAST_LANE_ORDER]);
  const plan = rows.find((row) => row.name === "plan");
  // "has not happened YET" is not "did not happen": a pending node carries no measurement.
  assert.equal(plan.status, "pending");
  assert.equal(plan.ms, 0);
  assert.equal(plan.running, false);
  // Nothing is filled in before the lane has said anything.
  assert.deepEqual(laneOrdered([], FAST_LANE_ORDER), []);
});

test("a name the order has never heard of keeps its place beside its parent", () => {
  const rows = laneOrdered(
    [live("retrieve", 812), live("retrieve.path:person", 122), live("plan", 90)],
    FAST_LANE_ORDER,
  );
  const names = rows.map((row) => row.name);
  assert.deepEqual(names.slice(0, 3), ["plan", "retrieve", "retrieve.path:person"]);
});

test("a pending placeholder is never the slowest stage", () => {
  const rows = laneOrdered([live("retrieve", 812)], FAST_LANE_ORDER);
  assert.equal(slowestStage(rows).name, "retrieve");
});
