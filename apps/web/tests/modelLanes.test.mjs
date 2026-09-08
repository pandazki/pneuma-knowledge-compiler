/**
 * The model lanes are quality-testing tools, and a key is what opens them.
 *
 * In the personal edition the library holds no model: every judgement is the agent's, and
 * Recall / Ask / Live Context are the bench over the API's model lanes rather than the way
 * anyone retrieves anything day to day. Those lanes need an API key, so on a machine whose
 * current library has none the three pages render a notice instead of a form, and the daily
 * path — the Steward reading the library — is named on it.
 *
 * Four things are pinned here, and the fourth is the one that matters most:
 *
 * 1. `lib/modelLanes.ts` is the ONE declaration: the list of the three views, and the single
 *    condition that closes them.
 * 2. The gate is a ROUTER gate (App.tsx), so a deep link lands on the notice by the same
 *    road a click on the rail does, and the three view files never learn the concept exists.
 * 3. The rail keeps its entries and marks them — the map of the console must not change with
 *    the state of a credential.
 * 4. **Without a home, nothing is locked.** Every project deployment renders byte for byte
 *    as it did before this existed, and the rail's existing lens assertions are re-run here
 *    against the same table to say so.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

/** One source file as an importable data: URL — also a valid module specifier, which is how
 *  a file that imports lib/home gets the real lib/home rather than a copy of it. */
async function compile(url, replace = (code) => code) {
  const text = replace(await readFile(url, "utf8"));
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: url.pathname.endsWith(".tsx") ? "tsx" : "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const homeUrl = await compile(new URL("../src/lib/home.ts", import.meta.url));
const {
  MODEL_LANE_KEY_COMMAND,
  MODEL_LANE_VIEWS,
  isModelLaneView,
  modelLaneLocked,
  modelLanesLocked,
} = await import(
  await compile(new URL("../src/lib/modelLanes.ts", import.meta.url), (code) =>
    code.replace('from "./home"', `from "${homeUrl}"`),
  )
);

const lensesUrl = await compile(new URL("../src/lib/lenses.ts", import.meta.url));
const { LENSES, ROUTED_VIEWS, isViewVisible } = await import(lensesUrl);

// Only TocNav's exported table and lens filter are wanted; React and the project aliases are
// stripped rather than resolved, exactly as tests/hashRoutes.test.mjs does it.
const { TOC, tocForLens } = await import(
  await compile(new URL("../src/components/TocNav.tsx", import.meta.url), (code) =>
    code
      .split("\n")
      .filter((line) => !line.startsWith("import ") || line.includes("@/lib/lenses"))
      .join("\n")
      .replace('from "@/lib/lenses"', `from "${lensesUrl}"`)
      .replace(/export function TocNav[\s\S]*$/, ""),
  )
);

const [appSource, tocSource, noticeSource, homeViewSource, i18nHomeSource] = await Promise.all(
  [
    "../src/App.tsx",
    "../src/components/TocNav.tsx",
    "../src/views/_shared/ModelLaneNotice.tsx",
    "../src/views/home/HomeView.tsx",
    "../src/i18n/home.ts",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")),
);

/* ------------------------------------------------------------------------ fixtures */

const library = (over = {}) => ({
  name: "notes",
  tenant: "lib-notes",
  current: true,
  engine: { pid: 1, up: true, port: 20010, uptime: 60 },
  queue: null,
  key: true,
  engine_dir: "/e",
  canonical_head: null,
  skill_fresh: null,
  steps: {},
  last_used: null,
  ...over,
});

const home = (...libraries) => ({
  home: { path: "/h", version: "0.1.0" },
  docker: { reachable: true },
  services: {},
  libraries,
});

const WITH_KEY = home(library({ key: true }));
const WITHOUT_KEY = home(library({ key: false }));
// A machine that answered but named no current library: nobody said the key was missing.
const NO_CURRENT = home(library({ current: false, key: false }));

/* --------------------------------------------------------------- the one declaration */

test("the model lanes are exactly the three views that post into a lane — the Steward is not one", () => {
  assert.deepEqual([...MODEL_LANE_VIEWS], ["recall", "ask", "live_context"]);
  // Retrieval for daily use is an agent session, and an agent session needs no key from the
  // console: putting the Steward on this list would close the very door the notice opens.
  assert.equal(isModelLaneView("steward"), false);
  assert.equal(isModelLaneView("library"), false);
  for (const view of MODEL_LANE_VIEWS) {
    assert.ok(ROUTED_VIEWS.includes(view), `${view} is not a routable view`);
    assert.equal(isModelLaneView(view), true);
  }
  assert.ok(ROUTED_VIEWS.includes("steward"), "the notice points at a view that exists");
});

test("a key closes nothing; a missing key on the current library closes the three", () => {
  assert.equal(modelLanesLocked(WITH_KEY), false);
  assert.equal(modelLanesLocked(WITHOUT_KEY), true);
  for (const view of MODEL_LANE_VIEWS) {
    assert.equal(modelLaneLocked(view, WITHOUT_KEY), true, view);
    assert.equal(modelLaneLocked(view, WITH_KEY), false, view);
  }
  // Everything else renders regardless: this is a lane gate, not a degraded console.
  for (const view of ROUTED_VIEWS.filter((v) => !MODEL_LANE_VIEWS.includes(v))) {
    assert.equal(modelLaneLocked(view, WITHOUT_KEY), false, view);
  }
});

test("an absence is not a lock: no home, and no current library, decide nothing", () => {
  assert.equal(modelLanesLocked(null), false);
  assert.equal(modelLanesLocked(NO_CURRENT), false, "an unread key is not a missing one");
  for (const view of ROUTED_VIEWS) {
    assert.equal(modelLaneLocked(view, null), false, `${view} locked on a project deployment`);
  }
});

test("the command that fixes it is a command, not copy — the same in every language", () => {
  assert.equal(MODEL_LANE_KEY_COMMAND, "pkchome credentials set OPENROUTER_API_KEY");
  assert.ok(noticeSource.includes("MODEL_LANE_KEY_COMMAND"), "the notice must print it");
  assert.equal(
    i18nHomeSource.includes("pkchome credentials set"),
    false,
    "a shell command belongs in the module, not in the dictionary",
  );
});

/* ------------------------------------------------------------------- one gate, at the router */

test("the gate is the router's, so a deep link resolves to the notice too", () => {
  assert.match(appSource, /isModelLaneView\(view\) && modelLanesLocked\(home\)/);
  assert.match(appSource, /<ModelLaneNotice view=\{view\} \/>/);
  assert.match(appSource, /const home = useHome\(\);/);
});

test("the three views never learn the concept: they are the forms, unchanged", async () => {
  for (const path of [
    "../src/views/recall/RecallView.tsx",
    "../src/views/ask/AskView.tsx",
    "../src/views/live_context/LiveContextView.tsx",
  ]) {
    const source = await readFile(new URL(path, import.meta.url), "utf8");
    assert.equal(
      /modelLane|MODEL_LANE/i.test(source),
      false,
      `${path} grew a second copy of the gate`,
    );
  }
});

test("the notice says what the page is, why it is closed, and where retrieval went", () => {
  assert.match(noticeSource, /nav\.view\.\$\{view\}/, "the page keeps its own title");
  for (const key of [
    "modelLane.notice.what",
    "modelLane.notice.title",
    "modelLane.notice.why",
    "modelLane.notice.retrieval",
    "modelLane.notice.goSteward",
  ]) {
    assert.ok(noticeSource.includes(key), `the notice does not render ${key}`);
  }
  // The way out is offered only to a lens that may take it; the Steward is the owner's.
  assert.match(noticeSource, /isViewVisible\("steward", lens\)/);
  assert.match(noticeSource, /setView\("steward"\)/);
});

/* ---------------------------------------------------------------------- the rail keeps its map */

test("the rail marks the three entries and removes none of them", () => {
  assert.match(tocSource, /modelLaneLocked\(item\.view, home\)/);
  assert.match(tocSource, /nav\.modelLane\.badge/);
  assert.match(tocSource, /title=\{t\("nav\.modelLane\.title"\)\}/);
  // The badge is a mark ON an entry, never a filter over the table.
  assert.equal(
    /items\.filter\([^)]*modelLane/i.test(tocSource),
    false,
    "a credential must not edit the table of contents",
  );
  const railViews = TOC.flatMap((group) => group.items).map((item) => item.view);
  for (const view of MODEL_LANE_VIEWS) {
    assert.ok(railViews.includes(view), `${view} left the contents rail`);
  }
});

test("with no home the rail is the table it always was — the lens declaration, unchanged", () => {
  // The same assertion tests/hashRoutes.test.mjs makes, re-run from the side of this feature:
  // nothing here may subtract a row on a console that never had a home.
  const railViews = (groups) => groups.flatMap((group) => group.items).map((item) => item.view);
  for (const lens of LENSES) {
    assert.deepEqual(
      railViews(tocForLens(lens)),
      railViews(TOC).filter((view) => isViewVisible(view, lens)),
      `the ${lens} rail diverged from the declaration`,
    );
  }
  assert.deepEqual(tocForLens("owner"), TOC, "the owner's rail is the chapter table itself");
});

/* ------------------------------------------------------------------- the home view says it once */

test("the Home view's key row states what a missing key costs, and only when it is missing", () => {
  assert.match(homeViewSource, /!library\.key && \(/);
  assert.match(homeViewSource, /t\("home\.library\.keyModelLanes"\)/);
});

test("every string this feature needs is declared in both languages", () => {
  const keys = [
    "home.library.keyModelLanes",
    "nav.modelLane.badge",
    "nav.modelLane.title",
    "modelLane.notice.what",
    "modelLane.notice.title",
    "modelLane.notice.why",
    "modelLane.notice.retrieval",
    "modelLane.notice.goSteward",
  ];
  for (const key of keys) {
    const declared = [...i18nHomeSource.matchAll(new RegExp(`"${key.replace(/\./g, "\\.")}":`, "g"))];
    assert.equal(declared.length, 2, `${key} must be declared once in zh and once in en`);
  }
  assert.ok(i18nHomeSource.includes('"model lanes: quality tools, off without a key"'));
});
