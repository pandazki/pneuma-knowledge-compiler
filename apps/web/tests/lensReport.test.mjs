/**
 * The structure lens's report, as the console receives it.
 *
 * The findings, the score and the order are derived in core (docs/design/structure-lens.md
 * §3), so nothing here re-derives any of them. What is asserted is what the console is
 * actually responsible for: that a report which crossed a wire renders rather than blanking
 * the page, that the levels group in §3.4's order with an unknown one kept, and that two
 * reports subtract by finding KEY — which is what makes "still open" mean the same fault on
 * the same page and not merely the same lens firing twice.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/lensReport.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { compareReports, groupByLevel, headline, parseLensReport } = await import(moduleUrl);

/** One finding, spelled as the service spells it. */
function finding(key, lens, level, extra = {}) {
  return {
    key,
    lens,
    level,
    actor: level === "principle" ? "owner" : level === "shape" ? "mechanism" : "steward",
    paths: [`memory/topics/${lens.replace(/\W/g, "-")}.md`],
    targets: [],
    evidence: ["1 occurrence"],
    impact: {
      key: `lens.${lens}.impact`,
      fields: {},
      text: { en: `what ${lens} costs`, zh: `${lens} 的代价` },
    },
    action: {
      key: `lens.${lens}.action`,
      fields: {},
      text: { en: `what to do about ${lens}`, zh: `${lens} 该怎么办` },
    },
    weight: 0.1,
    decision: null,
    ...extra,
  };
}

function report(findings, counts = {}) {
  return {
    ref: "0f1e2d3c4b5a",
    read_at: "2026-09-14T08:00:00Z",
    subjects: 12,
    files: 14,
    claims: 100,
    edges: 20,
    score: 80,
    findings,
    families: [{ name: "memory/topics/{slug}.md", pages: 6, claims: 40, share: 0.4 }],
    ...counts,
  };
}

/* ------------------------------------------------------------------------ parsing */

test("a report that arrived half-written still renders: every absent field reads empty", () => {
  const parsed = parseLensReport({ ref: "abc", score: 61 });
  assert.equal(parsed.ref, "abc");
  assert.equal(parsed.score, 61);
  assert.equal(parsed.read_at, "");
  assert.deepEqual(parsed.findings, []);
  assert.deepEqual(parsed.families, []);
  assert.equal(parsed.claims, 0);
  // Not merely "does not throw": a null body is a report with nothing in it, not a crash.
  assert.deepEqual(parseLensReport(null).findings, []);
});

test("a sentence arrives rendered in both packs, beside the key it came from", () => {
  const [parsed] = parseLensReport({
    findings: [
      {
        key: "k",
        lens: "nav.hub_incomplete",
        level: "drift",
        impact: {
          key: "lens.nav.hub_incomplete.impact",
          fields: { targets: ["a.md", "b.md"], count: 2 },
          text: { en: "The hub leaves out two of its own pages.", zh: "族首页漏掉了自己的两页。" },
        },
      },
    ],
  }).findings;
  // The rendering is what a reader sees; the key and fields are what a DEGRADED report has
  // left to say something with, so both survive parsing.
  assert.equal(parsed.impact.text.en, "The hub leaves out two of its own pages.");
  assert.equal(parsed.impact.text.zh, "族首页漏掉了自己的两页。");
  assert.equal(parsed.impact.fields.targets, "a.md, b.md");
  assert.equal(parsed.impact.fields.count, 2);
  // A finding with no action still has an action object, so the row never reads `undefined`.
  assert.deepEqual(parsed.action, { key: "", fields: {}, text: { en: "", zh: "" } });
  assert.equal(parsed.decision, null);
});

test("a report from a service that sends no rendered text still parses to empty strings", () => {
  // The view's own fallback ladder (other language, then key · fields) needs these present
  // rather than undefined; a missing `text` must not make the row throw.
  const [parsed] = parseLensReport({
    findings: [{ key: "k", lens: "nav.island", level: "principle", impact: { key: "lens.nav.island.impact" } }],
  }).findings;
  assert.deepEqual(parsed.impact.text, { en: "", zh: "" });
  assert.deepEqual(parsed.impact.fields, {});
});

test("a level or actor this build never heard of survives as itself", () => {
  const parsed = parseLensReport({
    findings: [{ key: "k", lens: "new.lens", level: "posture", actor: "librarian" }],
  });
  assert.equal(parsed.findings[0].level, "posture");
  assert.equal(parsed.findings[0].actor, "librarian");
});

/* ----------------------------------------------------------------------- grouping */

test("levels group principle before drift before shape, and an unknown level is kept last", () => {
  const groups = groupByLevel([
    finding("a", "form.stray_heading", "shape"),
    finding("b", "nav.island", "principle"),
    finding("c", "nav.dead_end", "drift"),
    finding("d", "x.y", "posture"),
  ]);
  assert.deepEqual(
    groups.map((g) => g.level),
    ["principle", "drift", "shape", "posture"],
  );
  assert.deepEqual(groups[0].findings.map((f) => f.key), ["b"]);
  assert.deepEqual(groups[3].findings.map((f) => f.key), ["d"]);
  // A level with nothing in it is a group that says so, not a missing section.
  assert.deepEqual(groupByLevel([]).map((g) => g.findings.length), [0, 0, 0]);
});

test("the order within a level is the report's own — the console re-sorts nothing", () => {
  const given = [
    finding("a", "nav.dead_end", "drift", { weight: 0.01 }),
    finding("b", "nav.island", "drift", { weight: 0.9 }),
  ];
  assert.deepEqual(groupByLevel(given)[1].findings.map((f) => f.key), ["a", "b"]);
  assert.deepEqual(headline(given, 3).map((f) => f.key), ["a", "b"]);
  assert.equal(headline(given, 1).length, 1);
});

/* ----------------------------------------------------------------------- headline */

test("the headline is one finding per lens: three things, not one thing three times", () => {
  // A real library with three islands led with three identical island sentences and pushed
  // the duplicated subject and the malformed page off the list entirely (§3.4).
  const given = [
    finding("i1", "nav.island", "principle"),
    finding("i2", "nav.island", "principle"),
    finding("i3", "nav.island", "principle"),
    finding("d1", "id.title_duplicate", "principle"),
    finding("s1", "form.stray_heading", "shape"),
    finding("s2", "form.stray_heading", "shape"),
    finding("c1", "conc.catch_all", "principle"),
  ];
  assert.deepEqual(headline(given).map((f) => f.key), ["i1", "d1", "s1"]);
  // Report order decides which of a lens's findings leads, and which lenses make the cut.
  assert.deepEqual(headline(given, 4).map((f) => f.lens), [
    "nav.island",
    "id.title_duplicate",
    "form.stray_heading",
    "conc.catch_all",
  ]);
});

test("a report with fewer lenses than the headline wants gives what it has", () => {
  const given = [finding("a", "nav.island", "principle"), finding("b", "nav.island", "principle")];
  assert.deepEqual(headline(given).map((f) => f.key), ["a"]);
  assert.deepEqual(headline([]), []);
});

/* --------------------------------------------------------------------- comparing */

test("two reports subtract by finding key: resolved, new, still open", () => {
  const before = report([
    finding("nav.island:work/x:aa", "nav.island", "principle"),
    finding("nav.dead_end:memory/a:bb", "nav.dead_end", "drift"),
  ]);
  const after = report(
    [
      finding("nav.dead_end:memory/a:bb", "nav.dead_end", "drift"),
      finding("id.title_duplicate:memory/b:cc", "id.title_duplicate", "principle"),
    ],
    { score: 88, claims: 140, subjects: 15 },
  );
  const diff = compareReports(before, after);
  assert.deepEqual(diff.resolved.map((f) => f.key), ["nav.island:work/x:aa"]);
  assert.deepEqual(diff.added.map((f) => f.key), ["id.title_duplicate:memory/b:cc"]);
  assert.deepEqual(diff.stillOpen.map((f) => f.key), ["nav.dead_end:memory/a:bb"]);

  const by = (metric) => diff.counts.find((row) => row.metric === metric);
  assert.equal(by("score").delta, 8);
  assert.equal(by("claims").delta, 40);
  assert.equal(by("subjects").before, 12);
  assert.equal(by("edges").delta, 0);
  assert.deepEqual(diff.counts.map((row) => row.metric), [
    "score",
    "subjects",
    "files",
    "claims",
    "edges",
  ]);
});

test("the same lens on the same page with different evidence is a new question, not the old one", () => {
  // The key hashes the evidence, so a page whose fault CHANGED reports the old finding
  // resolved and a new one open — which is the honest reading of what happened to it.
  const before = report([finding("conc.catch_all:work/x:aa", "conc.catch_all", "principle")]);
  const after = report([finding("conc.catch_all:work/x:zz", "conc.catch_all", "principle")]);
  const diff = compareReports(before, after);
  assert.equal(diff.stillOpen.length, 0);
  assert.equal(diff.resolved.length, 1);
  assert.equal(diff.added.length, 1);
});

test("a round that changed nothing reports nothing moved", () => {
  const same = report([finding("k", "nav.dead_end", "drift")]);
  const diff = compareReports(same, same);
  assert.deepEqual(diff.resolved, []);
  assert.deepEqual(diff.added, []);
  assert.equal(diff.stillOpen.length, 1);
  assert.ok(diff.counts.every((row) => row.delta === 0));
});
