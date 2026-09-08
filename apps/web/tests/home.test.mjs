/**
 * The home face: the parser that decides whether this console is served by a personal
 * edition at all, and the one consequence of that decision the store owns.
 *
 * Three things are worth pinning here rather than in a browser:
 *
 * 1. **Absence is the ordinary answer.** Every project deployment answers `/home/status`
 *    with a 404, so a 404 body must parse to the same `null` a network failure gives — one
 *    absence, not two, and no console anywhere renders half a machine.
 * 2. **The document is read tolerantly.** A section the edition has not filled in (a queue
 *    nobody could read, a freshness nobody could decide) is a null, not a parse failure, and
 *    a field this client has not learned is dropped rather than fatal.
 * 3. **The machine decides which library is on the bench.** The engine serving this console
 *    serves ONE library; a tenant id persisted from another machine (or another library)
 *    must not win over it, or the health page would name one library while every other view
 *    read another's data.
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

/* ------------------------------------------------------------------ module loading */

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const ZUSTAND = fileURLToPath(new URL("../node_modules/zustand/esm/index.mjs", import.meta.url));
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "pkc-web-home-"));
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
  compiled.set(file, url);
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
  location: { hash: "", protocol: "http:", hostname: "127.0.0.1" },
  addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.document = {
  documentElement: { dataset: {}, setAttribute() {}, classList: { add() {}, remove() {} } },
  addEventListener() {},
};

const {
  HOME_STEPS,
  currentLibrary,
  formatUptime,
  libraryHref,
  parseHomeLibraries,
  parseHomeStatus,
  stepsDone,
} = await import(await load(path.join(SRC, "lib/home.ts")));

/* ------------------------------------------------------------------------ fixtures */

/** A full document, as `pkchome status --json` prints one (single-machine-edition §6). */
const FULL = {
  home: { path: "/Users/someone/.pkc", version: "0.1.0" },
  docker: { reachable: true },
  services: {
    postgres: { port: 20001, up: true },
    qdrant: { port: 20002, up: true },
    meili: { port: 20003, up: true },
    rustfs: { port: 20004, up: false },
  },
  libraries: [
    {
      name: "notes",
      tenant: "lib-notes",
      current: true,
      engine: { pid: 123, up: true, port: 20010, uptime: 3600 },
      queue: { pending: 0, failed: 1, last_compile_at: "2026-09-07T10:00:00Z" },
      key: true,
      engine_dir: "/Users/someone/.pkc/libraries/notes/engine",
      canonical_head: "abc123",
      skill_fresh: true,
      steps: {
        infra: "2026-09-01T09:00:00Z",
        credentials: "2026-09-01T09:01:00Z",
        profile: "2026-09-01T09:02:00Z",
        skill: "2026-09-01T09:03:00Z",
        first_compile: null,
      },
      last_used: "2026-09-07T09:00:00Z",
    },
    {
      name: "work",
      tenant: "lib-work",
      current: false,
      engine: { pid: null, up: false, port: 20011, uptime: null },
      queue: null,
      key: true,
      engine_dir: "/Users/someone/.pkc/libraries/work/engine",
      canonical_head: null,
      skill_fresh: null,
      steps: { infra: "2026-09-01T09:00:00Z" },
      last_used: null,
    },
  ],
};

/* --------------------------------------------------------------------- the parser */

test("a full status document parses into the shape the switcher and the health page read", () => {
  const status = parseHomeStatus(FULL);
  assert.ok(status);
  assert.deepEqual(status.home, { path: "/Users/someone/.pkc", version: "0.1.0" });
  assert.deepEqual(status.docker, { reachable: true });
  assert.deepEqual(status.services.postgres, { port: 20001, up: true });
  assert.deepEqual(status.services.rustfs, { port: 20004, up: false });
  assert.equal(status.libraries.length, 2);

  const notes = status.libraries[0];
  assert.equal(notes.name, "notes");
  assert.equal(notes.tenant, "lib-notes");
  assert.equal(notes.current, true);
  assert.deepEqual(notes.engine, { pid: 123, up: true, port: 20010, uptime: 3600 });
  assert.deepEqual(notes.queue, { pending: 0, failed: 1, failed_by_kind: {}, succeeded: null, last_compile_at: "2026-09-07T10:00:00Z" });
  assert.equal(notes.canonical_head, "abc123");
  assert.equal(notes.skill_fresh, true);
  // The five steps are a fixed row: one written, one still null, never a missing key.
  assert.deepEqual(Object.keys(notes.steps).sort(), [...HOME_STEPS].sort());
  assert.equal(notes.steps.first_compile, null);
  assert.equal(stepsDone(notes.steps), 4);

  assert.equal(currentLibrary(status).name, "notes");
});

test("an unknown field is ignored rather than fatal — the edition may grow the document", () => {
  const status = parseHomeStatus({
    ...FULL,
    tray: { running: true },
    libraries: [{ ...FULL.libraries[0], unattended: true }],
  });
  assert.ok(status);
  assert.equal(status.libraries[0].name, "notes");
  assert.equal("tray" in status, false);
  assert.equal("unattended" in status.libraries[0], false);
});

test("a missing queue and an undecided freshness are nulls, not a broken parse", () => {
  const status = parseHomeStatus({
    libraries: [
      {
        name: "work",
        tenant: "lib-work",
        engine: { up: false },
      },
    ],
  });
  assert.ok(status);
  // Whole sections absent: the machine is simply not described, and the page says so.
  assert.equal(status.home, null);
  assert.equal(status.docker, null);
  assert.equal(status.services.postgres, null);

  const [work] = status.libraries;
  assert.equal(work.queue, null, "a queue nobody could read is null, never a zeroed one");
  assert.equal(work.skill_fresh, null, "unknown freshness is not 'stale'");
  assert.equal(work.current, false);
  assert.equal(work.key, false);
  assert.deepEqual(work.engine, { pid: null, up: false, port: null, uptime: null });
  assert.deepEqual(
    HOME_STEPS.map((step) => work.steps[step]),
    HOME_STEPS.map(() => null),
  );
  assert.equal(stepsDone(work.steps), 0);
  assert.equal(currentLibrary(status), null, "no library claims to be current");
});

test("a 404 body is an absence, exactly as an unreachable host is", () => {
  // What FastAPI answers on a deployment that never mounted the edition's routes.
  assert.equal(parseHomeStatus({ detail: "Not Found" }), null);
  assert.equal(parseHomeStatus(null), null);
  assert.equal(parseHomeStatus(undefined), null);
  assert.equal(parseHomeStatus("Not Found"), null);
  assert.equal(parseHomeStatus([]), null, "the array alone is /home/libraries, not a status");
  assert.equal(currentLibrary(null), null);
});

test("a library with no name or no tenant is dropped: it is a row nothing could reach", () => {
  const status = parseHomeStatus({
    libraries: [{ name: "notes" }, { tenant: "lib-notes" }, null, 7, FULL.libraries[1]],
  });
  assert.deepEqual(
    status.libraries.map((library) => library.name),
    ["work"],
  );
});

test("/home/libraries parses as the same rows, and anything else as an absence", () => {
  assert.deepEqual(
    parseHomeLibraries(FULL.libraries).map((library) => library.tenant),
    ["lib-notes", "lib-work"],
  );
  assert.equal(parseHomeLibraries({ detail: "Not Found" }), null);
});

/* -------------------------------------------------------------- switching is a navigation */

test("another library's console is the same host at that library's port, carrying the route", () => {
  const status = parseHomeStatus(FULL);
  const [notes, work] = status.libraries;
  const location = { protocol: "http:", hostname: "127.0.0.1" };
  assert.equal(libraryHref(work, location, "#/library/doc/abc"), "http://127.0.0.1:20011/#/library/doc/abc");
  assert.equal(libraryHref(notes, location, ""), "http://127.0.0.1:20010/");
  assert.equal(libraryHref(notes, location, "#"), "http://127.0.0.1:20010/");
  // A route without its "#" is still a route; a library with no port is nowhere to go.
  assert.equal(libraryHref(notes, location, "/recall"), "http://127.0.0.1:20010/#/recall");
  assert.equal(libraryHref({ ...work, engine: { ...work.engine, port: null } }, location), null);
});

test("uptime reads as a glance, not as a stopwatch", () => {
  assert.equal(formatUptime(0), "0s");
  assert.equal(formatUptime(45), "45s");
  assert.equal(formatUptime(600), "10m");
  assert.equal(formatUptime(3600), "1h 0m");
  assert.equal(formatUptime(11_520), "3h 12m");
  assert.equal(formatUptime(187_200), "2d 4h");
  assert.equal(formatUptime(null), "—");
  assert.equal(formatUptime(-1), "—");
});

/* ------------------------------------------------------- the machine decides the tenant */

const { useApp } = await import(await load(path.join(SRC, "lib/store.ts")));

/** Answer `/home/status` with `body` (or a 404), and count the probes. */
function serve(body) {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    if (body === null) return { ok: false, status: 404, json: async () => ({ detail: "Not Found" }) };
    return { ok: true, status: 200, json: async () => body };
  };
  return calls;
}

function reset(currentUser) {
  useApp.setState({ home: null, homeTenant: null, homeAbsent: false, currentUser });
}

test("with a home, the console's tenant is the current library's — not a persisted id", () => {
  // A user id left in localStorage by another machine, or by another library on this one.
  localStorage.setItem("pneuma_knowledge-user", "someone-else");
  reset("someone-else");
  serve(FULL);
  return useApp
    .getState()
    .loadHome(true)
    .then(() => {
      const s = useApp.getState();
      assert.equal(s.currentUser, "lib-notes", "the bench followed the machine's current library");
      assert.equal(s.homeTenant, "lib-notes");
      assert.equal(s.home.libraries.length, 2);
      // And the adoption is persisted, so a reload does not flap back to the stale id.
      assert.equal(localStorage.getItem("pneuma_knowledge-user"), "lib-notes");
    });
});

test("a re-probe of the same machine does not re-switch the library under the reader", () => {
  reset("lib-notes");
  useApp.setState({ homeTenant: "lib-notes" });
  serve(FULL);
  return useApp
    .getState()
    .loadHome()
    .then(() => {
      assert.equal(useApp.getState().currentUser, "lib-notes");
      assert.equal(useApp.getState().home.libraries[1].name, "work");
    });
});

test("no home: nothing is adopted, nothing is touched, and the probe is never repeated", () => {
  reset("demo-user");
  const calls = serve(null);
  return useApp
    .getState()
    .loadHome(true)
    .then(() => {
      const s = useApp.getState();
      assert.equal(s.home, null);
      assert.equal(s.homeAbsent, true);
      assert.equal(s.currentUser, "demo-user", "a project deployment picks its own user");
      return useApp.getState().loadHome();
    })
    .then(() => {
      assert.equal(calls.length, 1, "a 404 is asked once per page load, not every thirty seconds");
    });
});

test("a derived step reported as a bare true counts as done", () => {
  const doc = parseHomeStatus({
    home: { path: "/h", version: "0" }, docker: { reachable: true }, services: {},
    libraries: [{ name: "n", tenant: "lib-n", current: true, engine: { pid: 1, up: true, port: 1, uptime: 1 },
      queue: null, key: true, engine_dir: "/e", canonical_head: null, skill_fresh: null,
      steps: { infra: "2026-09-01T09:00:00Z", profile: true }, last_used: null }],
  });
  assert.equal(doc.libraries[0].steps.profile, "done");
  assert.equal(stepsDone(doc.libraries[0].steps), 2);
});

test("failures are counted by kind and successes are read when the engine says them", () => {
  const doc = parseHomeStatus({
    home: { path: "/h", version: "0" }, docker: { reachable: true }, services: {},
    libraries: [{ name: "n", tenant: "lib-n", current: true, engine: { pid: 1, up: true, port: 1, uptime: 1 },
      queue: { pending: 0, failed: 40, failed_by_kind: { evolve: 40, index: 0 }, succeeded: 135, last_compile_at: null },
      key: false, engine_dir: "/e", canonical_head: null, skill_fresh: null, steps: {}, last_used: null }],
  });
  assert.deepEqual(doc.libraries[0].queue.failed_by_kind, { evolve: 40 });
  assert.equal(doc.libraries[0].queue.succeeded, 135);
});
