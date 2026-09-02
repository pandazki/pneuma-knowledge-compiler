/**
 * A recall already in flight when the lens changes does not land in the cleared sitting.
 *
 * Clearing `recallCache` / `sessionAsks` on a lens change settles what is on SCREEN. It does
 * not settle what may still be written to them: `fetch` cannot be un-sent, so the request
 * the previous person started still resolves, and its completion handler wrote their
 * question, answer and citations back in — under the new identity's name, a second after the
 * reset that existed to prevent exactly that.
 *
 * So the request opens a SITTING and writes only through it, and the store bumps an identity
 * epoch in the same breath as it clears the fields. These tests drive the real store — the
 * whole import graph compiled to a temp directory, as `lensIdentityReset.test.mjs` does — and
 * resolve the request AFTER the lens change, which is the interleaving that mattered.
 *
 * The last tests run the same interleaving against a sitting that never went stale, and pin
 * that it does write: what stops the leak is the epoch check and nothing else.
 *
 * And it is not only the settled answer. A streaming lane writes the whole time it runs —
 * stages as they open, the answer as it is written, one trail row per tool call — so those
 * three go through the same handle. Guarding the completion alone left the live picture
 * leaking: the previous person's stages and half-written answer redrew themselves into the
 * next sitting on the very next frame, which is the same leak arriving a moment earlier.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const ZUSTAND = fileURLToPath(new URL("../node_modules/zustand/esm/index.mjs", import.meta.url));
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "pkc-web-sitting-"));
process.on("exit", () => fs.rmSync(OUT, { recursive: true, force: true }));
const compiled = new Map();

function resolveSpec(spec, fromFile) {
  let base;
  if (spec.startsWith("@/")) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null; // a package: only zustand is reached, and it is mapped by name
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts")]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`cannot resolve ${spec} from ${fromFile}`);
}

/** One source file (and, recursively, everything it imports), compiled and importable. */
async function load(file) {
  const cached = compiled.get(file);
  if (cached) return cached;
  const url = pathToFileURL(
    path.join(OUT, `${createHash("sha1").update(file).digest("hex").slice(0, 16)}.mjs`),
  ).href;
  compiled.set(file, url); // registered before the walk, so a cycle of types terminates
  let code = (await readFile(file, "utf8")).split("import.meta.env").join("globalThis.__VITE_ENV__");
  for (const spec of new Set([...code.matchAll(/from\s+"([^"]+)"/g)].map((m) => m[1]))) {
    const target = spec === "zustand" ? ZUSTAND : resolveSpec(spec, file);
    if (target === null) continue;
    const resolved = target === ZUSTAND ? pathToFileURL(ZUSTAND).href : await load(target);
    code = code.split(`from "${spec}"`).join(`from "${resolved}"`);
  }
  const out = await transformWithEsbuild(code, file, {
    loader: file.endsWith(".tsx") ? "tsx" : "ts",
    format: "esm",
    target: "es2022",
  });
  await writeFile(fileURLToPath(url), out.code, "utf8");
  return url;
}

globalThis.__VITE_ENV__ = {};
globalThis.localStorage = {
  _: new Map(),
  getItem(key) {
    return this._.has(key) ? this._.get(key) : null;
  },
  setItem(key, value) {
    this._.set(key, String(value));
  },
  removeItem(key) {
    this._.delete(key);
  },
};
globalThis.window = {
  location: { hash: "" },
  addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.document = {
  documentElement: { dataset: {}, setAttribute() {}, classList: { add() {}, remove() {} } },
  addEventListener() {},
};

const { useApp } = await import(await load(path.join(SRC, "lib/store.ts")));
const { openSitting } = await import(await load(path.join(SRC, "views/recall/sitting.ts")));

const ANSWER = {
  answer: "他在三月接手。",
  citations: [{ kind: "claim", ref: "c:aa11", path: "memory/people/abao.md" }],
};

function seat(lens) {
  useApp.setState({
    lens,
    recallCache: { query: "", mode: "fast", rag: null, answer: null, error: null },
    sessionAsks: [],
  });
}

/**
 * Every write a recall makes: the two settled ones bound to the real store, and the three
 * the streaming lanes make while they run, collected into `seen` the way the view collects
 * them into its live lane and its trail.
 */
function writes(seen = { stages: [], tokens: [], steps: [] }) {
  const s = useApp.getState();
  return {
    setRecallCache: s.setRecallCache,
    pushSessionAsk: s.pushSessionAsk,
    onStage: (event) => seen.stages.push(event),
    onToken: (delta) => seen.tokens.push(delta),
    onStep: (step) => seen.steps.push(step),
  };
}

/** A recall opened now, resolved by the caller — that is the whole point. */
function startRecall(seen) {
  return openSitting(() => useApp.getState().identityEpoch, writes(seen));
}

function finish(sitting) {
  sitting.setRecallCache({ answer: ANSWER });
  sitting.pushSessionAsk({ question: "阿宝的离职补偿谈到哪一步了？", mode: "fast", answer: ANSWER });
}

function sitting() {
  const s = useApp.getState();
  return { answer: s.recallCache.answer, asks: s.sessionAsks };
}

test("a recall that resolves after the lens changed writes nothing into the new sitting", () => {
  seat("owner");
  const inFlight = startRecall();

  useApp.getState().setLens("visitor");
  finish(inFlight);

  assert.deepEqual(sitting(), { answer: null, asks: [] });
});

test("the same holds on the way back — a visitor's answer does not land in the owner's room", () => {
  seat("visitor");
  const inFlight = startRecall();

  useApp.getState().setLens("owner");
  finish(inFlight);

  assert.deepEqual(sitting(), { answer: null, asks: [] });
});

test("an error frame is a write too, and is dropped on the same terms", () => {
  seat("owner");
  const inFlight = startRecall();

  useApp.getState().setLens("silent");
  inFlight.setRecallCache({ error: "boom" });

  assert.equal(useApp.getState().recallCache.error, null);
});

test("a library change ends the sitting as surely as a person change", () => {
  seat("owner");
  useApp.setState({ currentUser: "u-one" });
  const inFlight = startRecall();

  useApp.getState().setUser("u-two");
  finish(inFlight);

  assert.deepEqual(sitting(), { answer: null, asks: [] });
});

test("re-choosing the same lens is not a change, so an answer still in flight lands", () => {
  seat("owner");
  const inFlight = startRecall();

  useApp.getState().setLens("owner");
  finish(inFlight);

  const kept = sitting();
  assert.equal(kept.answer, ANSWER);
  assert.equal(kept.asks.length, 1);
});

/* ------------------------------------------------------- the lane while it is running */

//: One frame of each kind a streaming lane sends, in the shapes the view is handed them.
const STAGE = { name: "retrieve", key: "retrieve", phase: "start", at_ms: 0 };
const STEP = { tool: "search_knowledge", query: "阿宝的补偿", hits: 3, ms: 42 };

function stream(sitting) {
  sitting.onStage(STAGE);
  sitting.onToken("他在三月");
  sitting.onStep(STEP);
}

test("a stage, a token and a trail step from the ended sitting land nowhere either", () => {
  seat("owner");
  const seen = { stages: [], tokens: [], steps: [] };
  const inFlight = startRecall(seen);

  useApp.getState().setLens("visitor");
  stream(inFlight);

  // Not "the answer eventually gets dropped": the previous person's stage diagram and their
  // half-written answer never appear in the new sitting at all.
  assert.deepEqual(seen, { stages: [], tokens: [], steps: [] });
});

test("unguarded, those same three frames draw the previous person's answer into the new room", () => {
  seat("owner");
  const seen = { stages: [], tokens: [], steps: [] };
  const unguarded = openSitting(() => 0, writes(seen)); // an epoch that never moves

  useApp.getState().setLens("visitor");
  stream(unguarded);

  assert.deepEqual(seen, { stages: [STAGE], tokens: ["他在三月"], steps: [STEP] });
});

test("and without the epoch check the very same interleaving leaks — that is what it stops", () => {
  seat("owner");
  const unguarded = openSitting(() => 0, writes()); // an epoch that never moves

  useApp.getState().setLens("visitor");
  finish(unguarded);

  assert.equal(useApp.getState().recallCache.answer, ANSWER);
  assert.equal(useApp.getState().sessionAsks.length, 1);
});
