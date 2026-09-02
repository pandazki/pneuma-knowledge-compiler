/**
 * Changing the identity lens changes the PERSON at this console, and the sitting does not
 * carry across it.
 *
 * `recall` is the one stateful surface every lens can reach (lib/lenses `VIEW_LENSES`), and
 * its cache holds the last question, the answer and the citations behind it; `sessionAsks`
 * is the reading room's history of the same. Left alone across a lens change, the next
 * identity opened Recall and read the previous one's question and answer — so this asserts
 * they are cleared, in BOTH directions: the owner inheriting a visitor's questions is the
 * same mistake as a visitor inheriting the owner's.
 *
 * The real store is exercised rather than a re-implementation of it. `load` below compiles
 * a module and everything it imports — the same trick the route tests use for one file,
 * applied down the import graph — so `useApp` here is the store the app runs, with zustand
 * resolved out of node_modules and the browser globals it touches stubbed. The compiled
 * files land in a temp directory rather than in nested data: URLs, because nesting one
 * base64 module inside another down a graph this deep grows the text exponentially.
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
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "pkc-web-store-"));
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
  // `import.meta.env` is Vite's, and esbuild leaves it undefined; the app only reads the
  // API base out of it, and a test that makes no request wants exactly the default.
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

const ANSWER = {
  answer: "他在三月接手。",
  citations: [{ kind: "claim", ref: "c:aa11", path: "memory/people/abao.md" }],
};

function seatSomebodyWithASitting(lens) {
  useApp.setState({
    lens,
    recallCache: {
      query: "阿宝的离职补偿谈到哪一步了？",
      mode: "rag",
      rag: null,
      answer: ANSWER,
      error: null,
    },
    sessionAsks: [{ question: "阿宝的离职补偿谈到哪一步了？", mode: "rag", answer: ANSWER }],
  });
}

function sitting() {
  const s = useApp.getState();
  return { query: s.recallCache.query, answer: s.recallCache.answer, asks: s.sessionAsks };
}

test("leaving the owner lens leaves nothing of the owner's recall behind", () => {
  seatSomebodyWithASitting("owner");
  useApp.getState().setLens("visitor");
  assert.deepEqual(sitting(), { query: "", answer: null, asks: [] });
  assert.equal(useApp.getState().lens, "visitor");
});

test("the silent lens inherits no sitting either — it is a third identity, not a mode", () => {
  seatSomebodyWithASitting("visitor");
  useApp.getState().setLens("silent");
  assert.deepEqual(sitting(), { query: "", answer: null, asks: [] });
});

test("and the owner does not inherit a visitor's questions on the way back", () => {
  seatSomebodyWithASitting("visitor");
  useApp.getState().setLens("owner");
  assert.deepEqual(sitting(), { query: "", answer: null, asks: [] });
});

test("re-choosing the lens already in use is not a change, and keeps the sitting", () => {
  // Otherwise every render that re-asserted the current identity would silently wipe the
  // answer on screen.
  seatSomebodyWithASitting("owner");
  useApp.getState().setLens("owner");
  const kept = sitting();
  assert.equal(kept.query, "阿宝的离职补偿谈到哪一步了？");
  assert.equal(kept.asks.length, 1);
});
