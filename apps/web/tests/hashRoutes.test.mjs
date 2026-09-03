/**
 * The route table, and who is allowed to reach each of its routes.
 *
 * `VIEW_LENSES` in lib/lenses.ts is the one declaration: its KEYS are every view a URL hash
 * may name (lib/hash.ts derives `ROUTED_VIEWS` from them, so the router keeps no list of its
 * own), and its VALUES are the identity lenses that may see each one. These tests read that
 * table and nothing else — no view names are spelled out here — and ask three things of it:
 * that the contents rail's own vocabulary parses as a deep link, that the rail offers each
 * lens exactly what the table says it may see, and that a route a lens may not see resolves
 * to somewhere that lens CAN see rather than to a broken page.
 *
 * `SHELL_CHROME_LENSES` beside it is the same declaration for the top bar's two controls,
 * and the last block below reads it and the two shell files: the library picker is on the
 * bench under every lens, the snapshot pin is the owner's alone, and the identity switcher
 * lives at the foot of the contents rail rather than in the top bar. Placement is asserted
 * against the source text because this app has no rendering harness — brittle on purpose:
 * a refactor that trips it should come back and re-read the reason.
 *
 * `ViewName` is a type and the rail is a table, so a view added to the navigation and
 * forgotten in one of these places type-checks perfectly and then fails silently: a link
 * nobody can share, or — since the lens landed — a cockpit page a visitor can deep-link to.
 * This is the mechanical guard the type system cannot be.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

/**
 * Transform one source file to an importable data: URL. The URL is returned rather than the
 * module, because a data: URL is also a valid module SPECIFIER — which is how a file that
 * imports lib/lenses gets the real lib/lenses instead of a copy of its table.
 */
async function compile(url, replace = (code) => code) {
  const text = replace(await readFile(url, "utf8"));
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: url.pathname.endsWith(".tsx") ? "tsx" : "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const lensesUrl = await compile(new URL("../src/lib/lenses.ts", import.meta.url));
const {
  LENSES,
  LENS_HOME,
  ROUTED_VIEWS,
  SHELL_CHROME_LENSES,
  VIEW_LENSES,
  deriveVisitorClass,
  isViewVisible,
  resolveView,
  showsShellChrome,
} = await import(lensesUrl);

const { isViewName } = await import(
  await compile(new URL("../src/lib/hash.ts", import.meta.url), (code) =>
    code.replace('from "./lenses"', `from "${lensesUrl}"`),
  )
);

// TocNav is a component file; only its exported table and lens filter are wanted, so the
// React and project-alias imports are stripped rather than resolved — except the lens
// import, which is pointed at the very module loaded above.
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

const railViews = (groups) => groups.flatMap((group) => group.items).map((item) => item.view);

test("every view in the contents rail parses as a deep link", () => {
  assert.deepEqual(railViews(TOC).filter((view) => !isViewName(view)), []);
});

test("the rail's section numbers are unique and in order", () => {
  const numbers = TOC.flatMap((group) => group.items).map((item) => item.no);
  assert.deepEqual(numbers, [...numbers].sort());
  assert.equal(new Set(numbers).size, numbers.length);
});

/* ------------------------------------------------------------------- the lens guard */

test("every routable view declares which lenses may see it, and the owner sees them all", () => {
  assert.ok(ROUTED_VIEWS.length > 0);
  const undeclared = [];
  const strange = [];
  const ownerBlind = [];
  for (const view of ROUTED_VIEWS) {
    const lenses = VIEW_LENSES[view];
    if (!Array.isArray(lenses) || lenses.length === 0) undeclared.push(view);
    else {
      for (const lens of lenses) if (!LENSES.includes(lens)) strange.push(`${view}: ${lens}`);
      if (!lenses.includes("owner")) ownerBlind.push(view);
    }
  }
  assert.deepEqual(undeclared, [], "a routable view with no lens declaration");
  assert.deepEqual(strange, [], "a lens name no lens answers to");
  assert.deepEqual(ownerBlind, [], "the owner's console is the whole console");
});

test("a lens that cannot see a view lands on a view it CAN see, never on a broken page", () => {
  const wrong = [];
  for (const lens of LENSES) {
    // The landing itself must be visible, or the guard would redirect into its own redirect.
    assert.ok(isViewVisible(LENS_HOME[lens], lens), `${lens}'s home is invisible to it`);
    for (const view of ROUTED_VIEWS) {
      const expected = isViewVisible(view, lens) ? view : LENS_HOME[lens];
      const landed = resolveView(view, lens);
      if (landed !== expected) wrong.push(`${lens} + ${view} → ${landed}, expected ${expected}`);
      assert.ok(isViewVisible(landed, lens), `${lens} landed on ${landed}, which it cannot see`);
    }
  }
  assert.deepEqual(wrong, []);
});

test("the rail offers each lens exactly the views declared for it — no more, no fewer", () => {
  for (const lens of LENSES) {
    const offered = railViews(tocForLens(lens));
    const declared = railViews(TOC).filter((view) => isViewVisible(view, lens));
    assert.deepEqual(offered, declared, `the ${lens} rail diverged from the declaration`);
    for (const view of offered) {
      assert.ok(isViewVisible(view, lens), `the ${lens} rail offers ${view}`);
    }
  }
  // The reading room is a strict subset of the cockpit: subtraction, not a second app.
  const owner = new Set(railViews(tocForLens("owner")));
  for (const lens of LENSES) {
    for (const view of railViews(tocForLens(lens))) assert.ok(owner.has(view));
  }
});

test("the lens derives the visitor class; no lens at this console asks as an auditor", () => {
  assert.equal(deriveVisitorClass("owner"), "business");
  assert.equal(deriveVisitorClass("visitor"), "business");
  assert.equal(deriveVisitorClass("silent"), "silent");
  // `audit` is an API caller's stance — reconstructible, but never steering the Steward.
  // No person sitting at this console can take it, and nothing here may hand it out.
  for (const lens of LENSES) assert.notEqual(deriveVisitorClass(lens), "audit");
});

/* --------------------------------------------------- the shell chrome, and where it sits */

const appShellSource = await readFile(
  new URL("../src/components/AppShell.tsx", import.meta.url),
  "utf8",
);
const tocNavSource = await readFile(
  new URL("../src/components/TocNav.tsx", import.meta.url),
  "utf8",
);

test("the library picker is on the bench under every lens; the snapshot pin is the owner's", () => {
  for (const lens of LENSES) {
    assert.equal(showsShellChrome("userPicker", lens), true, `${lens} lost the library picker`);
  }
  assert.deepEqual([...SHELL_CHROME_LENSES.snapshotPin], ["owner"]);
  // A pin the reading room cannot see would answer from a frozen copy in silence, so a lens
  // that may pin must also be a lens that may choose which library it is pinning.
  for (const lens of SHELL_CHROME_LENSES.snapshotPin) {
    assert.ok(showsShellChrome("userPicker", lens));
  }
});

test("the top bar asks the declaration about both of its controls, and keeps no second list", () => {
  for (const item of Object.keys(SHELL_CHROME_LENSES)) {
    assert.match(
      appShellSource,
      new RegExp(`showsShellChrome\\("${item}"`),
      `the top bar renders ${item} without consulting the declaration`,
    );
  }
  // Every render of either picker is inside its own guard — no unguarded second one.
  for (const [component, item] of [
    ["UserPicker", "userPicker"],
    ["SnapshotPicker", "snapshotPin"],
  ]) {
    const rendered = appShellSource
      .split("\n")
      .filter((line) => line.includes(`<${component} />`));
    assert.equal(rendered.length, 1, `expected one <${component} /> in the top bar`);
    assert.ok(
      rendered[0].includes(`showsShellChrome("${item}"`),
      `<${component} /> is rendered without its lens guard`,
    );
  }
});

test("the identity switcher lives at the foot of the contents rail, not in the top bar", () => {
  // The top bar is global administration; identity decides what the whole app is, so it sits
  // under the chapters whose length it decided.
  assert.ok(!appShellSource.includes("LensBadge"), "the lens switcher is back in the top bar");
  assert.ok(tocNavSource.includes("<LensBadge />"), "the contents rail lost the lens switcher");
  assert.ok(
    tocNavSource.indexOf("<LensBadge />") > tocNavSource.indexOf("</nav>"),
    "the lens switcher must sit below the chapters, not among them",
  );
  // Same foot under every lens: the way back out of the reading room is not something the
  // reading room may subtract.
  assert.ok(
    !/lens === "owner"[\s\S]{0,200}<LensBadge \/>/.test(tocNavSource),
    "the lens switcher must not be conditioned on the lens",
  );
});
