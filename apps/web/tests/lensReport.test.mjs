/**
 * The two model-free readings the console receives: the check's report (`GET /review`) and the
 * structure lens's reading (`GET /lens`).
 *
 * The findings, the bands, the metrics and their order are derived in core
 * (docs/design/structure-lens.md §3, §4), so nothing here re-derives any of them. What is
 * asserted is what the console is actually responsible for: that a reading which crossed a wire
 * renders rather than blanking the page, that the check's findings group under the page a
 * Steward would open while keeping the report's own order (legacy before judgement), that the
 * six dimensions read in §4.2's order with an unknown one kept at the end, and that the console
 * never invents which commit "previous" means.
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
const {
  LENS_DIMENSIONS,
  PREVIOUS_AUTO,
  catalogText,
  countByKind,
  groupByPage,
  isShareMetric,
  orderDimensions,
  parseCheckReport,
  parseLensReading,
  previousParam,
} = await import(moduleUrl);

// The console's own chrome table, loaded the way tests/i18n.test.mjs loads a bundle: the file
// imports nothing but `./define`, whose `defineMessages` is the identity function.
const lensBundleUrl = new URL("../src/i18n/lens.ts", import.meta.url);
const lensBundleText = (await readFile(lensBundleUrl, "utf8")).replace(
  /^import \{[^}]*\} from "\.\/define";$/m,
  "const defineMessages = (bundle) => bundle;",
);
const lensBundle = (
  await import(
    `data:text/javascript;base64,${Buffer.from(
      (
        await transformWithEsbuild(lensBundleText, lensBundleUrl.pathname, {
          loader: "ts",
          format: "esm",
          target: "es2022",
        })
      ).code,
    ).toString("base64")}`
  )
).lens;

/** One catalogue sentence, spelled as the service spells it. */
function sentence(key) {
  return { key, fields: {}, text: { en: `en ${key}`, zh: `zh ${key}` } };
}

/** One check finding, spelled as the service spells it. */
function finding(key, id, kind, paths, extra = {}) {
  return {
    key,
    id,
    kind,
    paths,
    targets: [],
    evidence: ["1 occurrence"],
    impact: sentence(`lens.${id}.impact`),
    action: sentence(`lens.${id}.action`),
    ...extra,
  };
}

function checkReport(findings, extra = {}) {
  return {
    ref: "0f1e2d3c4b5a",
    read_at: "2026-09-14T08:00:00Z",
    subjects: 12,
    files: 14,
    claims: 100,
    edges: 20,
    findings,
    ...extra,
  };
}

/** One lens dimension, spelled as the service spells it. */
function dimension(id, band, metrics = [], extra = {}) {
  return {
    id,
    band,
    statement: sentence(`lens.${id}.statement.${band}`),
    direction: sentence(`lens.${id}.direction.${band}`),
    metrics,
    evidence: [],
    ...extra,
  };
}

/* ------------------------------------------------------------------ the check report */

test("a check report that arrived half-written still renders: every absent field reads empty", () => {
  const parsed = parseCheckReport({ ref: "abc", claims: 7 });
  assert.equal(parsed.ref, "abc");
  assert.equal(parsed.claims, 7);
  assert.equal(parsed.read_at, "");
  assert.deepEqual(parsed.findings, []);
  assert.equal(parsed.subjects, 0);
  // Not merely "does not throw": a null body is a report with nothing in it, not a crash.
  assert.deepEqual(parseCheckReport(null).findings, []);
});

test("a finding missing everything but its key still renders as a row", () => {
  const [parsed] = parseCheckReport({ findings: [{ key: "k" }] }).findings;
  assert.equal(parsed.key, "k");
  assert.equal(parsed.id, "");
  assert.equal(parsed.kind, "");
  assert.deepEqual(parsed.paths, []);
  assert.deepEqual(parsed.evidence, []);
  assert.deepEqual(parsed.impact.text, { en: "", zh: "" });
});

test("a finding's fields survive the wire in a shape a last-resort rendering can use", () => {
  const [parsed] = parseCheckReport({
    findings: [
      {
        key: "k",
        impact: {
          key: "lens.nav.hub_incomplete.impact",
          // An array field is flattened rather than dropped: "[object Object]" in a fallback
          // line is worse than the list spelled out.
          fields: { missing: ["a.md", "b.md"], count: 2, nested: { deep: true } },
          text: { en: "three pages are unreachable", zh: "有三页走不到" },
        },
      },
    ],
  }).findings;
  assert.equal(parsed.impact.fields.missing, "a.md, b.md");
  assert.equal(parsed.impact.fields.count, 2);
  assert.equal(typeof parsed.impact.fields.nested, "string");
});

test("an unknown finding kind survives as itself rather than being dropped or renamed", () => {
  const report = parseCheckReport(checkReport([finding("k", "nav.dead_link", "prophecy", ["a.md"])]));
  assert.equal(report.findings[0].kind, "prophecy");
  assert.deepEqual(countByKind(report.findings), { prophecy: 1 });
});

test("findings group under the page a Steward would open, in the report's own order", () => {
  // The report orders legacy first (a hook fault is unambiguous), then judgement.
  const report = checkReport([
    finding("k1", "form.stray_heading", "legacy", ["topics/alpha.md"]),
    finding("k2", "form.collapsed_body", "legacy", ["topics/beta.md"]),
    finding("k3", "nav.hub_incomplete", "judgement", ["topics/alpha.md", "topics/beta.md"]),
    finding("k4", "id.title_duplicate", "judgement", []),
  ]);
  const pages = groupByPage(parseCheckReport(report).findings);
  assert.deepEqual(
    pages.map((page) => [page.path, page.findings.map((f) => f.key)]),
    [
      // alpha first because the report named it first; its judgement item follows its legacy
      // one, which is the order the report gave and not a second sort of the console's.
      ["topics/alpha.md", ["k1", "k3"]],
      ["topics/beta.md", ["k2"]],
      // A finding about no page in particular keeps a group of its own rather than vanishing.
      ["", ["k4"]],
    ],
  );
});

test("a finding is filed under its first path only — the rest are pages it also touches", () => {
  const pages = groupByPage([finding("k", "nav.hub_incomplete", "judgement", ["hub.md", "child.md"])]);
  assert.equal(pages.length, 1);
  assert.equal(pages[0].path, "hub.md");
  assert.deepEqual(pages[0].findings[0].paths, ["hub.md", "child.md"]);
});

test("the header counts each kind the report actually carried", () => {
  const findings = parseCheckReport(
    checkReport([
      finding("k1", "form.stray_heading", "legacy", ["a.md"]),
      finding("k2", "form.collapsed_body", "legacy", ["b.md"]),
      finding("k3", "nav.dead_link", "judgement", ["c.md"]),
    ]),
  ).findings;
  assert.deepEqual(countByKind(findings), { legacy: 2, judgement: 1 });
  assert.deepEqual(countByKind([]), {});
});

/* ------------------------------------------------------------------ the lens reading */

test("a lens reading that arrived half-written still renders: every absent field reads empty", () => {
  const parsed = parseLensReading({ ref: "abc" });
  assert.equal(parsed.ref, "abc");
  assert.equal(parsed.previous_ref, null);
  assert.deepEqual(parsed.dimensions, []);
  assert.equal(parsed.files, 0);
  assert.deepEqual(parseLensReading(null).dimensions, []);
});

test("a metric with no previous reading behind it reads as absent, not as zero", () => {
  const [dim] = parseLensReading({
    dimensions: [dimension("walkability", "thin", [{ name: "dead_end_share", value: 0.21 }])],
  }).dimensions;
  const [metric] = dim.metrics;
  assert.equal(metric.value, 0.21);
  assert.equal(metric.previous, null);
  // Null rather than 0: a movement of zero and no movement to speak of are different readings,
  // and a delta column of "0" would claim the library held still.
  assert.equal(metric.delta, null);
});

test("a delta the service did not send is the subtraction the two numbers already imply", () => {
  const [dim] = parseLensReading({
    dimensions: [
      dimension("liveness", "settling", [
        { name: "rollovers", value: 5, previous: 3 },
        // An explicit delta is the service's own and is never second-guessed here.
        { name: "edits_per_100", value: 2, previous: 1, delta: 9 },
      ]),
    ],
  }).dimensions;
  assert.equal(dim.metrics[0].delta, 2);
  assert.equal(dim.metrics[1].delta, 9);
});

test("the six dimensions read in the design's order, and an unknown one is kept at the end", () => {
  assert.deepEqual(LENS_DIMENSIONS, [
    "walkability",
    "shape",
    "knowledge_vs_log",
    "liveness",
    "type_structure",
    "demand_supply",
  ]);
  const ordered = orderDimensions([
    dimension("weather", "fine"),
    dimension("demand_supply", "unread"),
    dimension("walkability", "open"),
  ]);
  assert.deepEqual(
    ordered.map((d) => d.id),
    ["walkability", "demand_supply", "weather"],
  );
});

test("a reading carrying fewer than six dimensions renders the ones it has", () => {
  const reading = parseLensReading({ dimensions: [dimension("shape", "even")] });
  assert.equal(orderDimensions(reading.dimensions).length, 1);
});

/* --------------------------------------------------------------- the previous reading */

test("the previous ref defaults to the service's own reading of it, not to a ref of ours", () => {
  // The console does not compute HEAD's parent. If it did, the console and `pkc lens` could
  // disagree about what "previous" means on a library whose HEAD has two of them.
  assert.equal(previousParam(PREVIOUS_AUTO), null);
  assert.equal(previousParam(""), null);
  assert.equal(previousParam("0f1e2d3c4b5a"), "0f1e2d3c4b5a");
});

test("the reading says which ref it actually stood against, and null when there was none", () => {
  assert.equal(parseLensReading({ previous_ref: "abc123" }).previous_ref, "abc123");
  assert.equal(parseLensReading({ previous_ref: "" }).previous_ref, null);
  assert.equal(parseLensReading({ previous_ref: 7 }).previous_ref, null);
});

/* ------------------------------------------------------------------ catalogue sentences */

test("a sentence is the reader's language, then the other, then the key spelled out", () => {
  const both = { key: "k", fields: {}, text: { en: "English", zh: "中文" } };
  assert.equal(catalogText("zh", both), "中文");
  assert.equal(catalogText("en", both), "English");

  // One pack empty: the other language beats a blank line.
  assert.equal(catalogText("zh", { key: "k", fields: {}, text: { en: "English", zh: "" } }), "English");

  // Neither: the key with its fields, which is what a degraded reading still has to say.
  assert.equal(
    catalogText("en", { key: "lens.shape.statement", fields: { lead: "alpha.md", share: 42 }, text: { en: "", zh: "" } }),
    "lens.shape.statement · lead=alpha.md · share=42",
  );
  assert.equal(catalogText("en", { key: "", fields: {}, text: { en: "", zh: "" } }), "");
});

/* --------------------------------------------------------------- the metric vocabulary */

/**
 * Every metric name the lens sends, by dimension (docs/design/structure-lens.md §4.2).
 *
 * The console renders a readable label for each; a name with no label falls through to the
 * humanized raw name, which on a Chinese page means an English metric in the middle of the
 * table. That fallback is the safety net for a name this build has never heard of — it must
 * not be how the ordinary reading renders — so the wire's own list is pinned here and a
 * rename on either side fails loudly instead of quietly showing `lead family claim share`.
 */
const WIRE_METRICS = [
  "edges_per_subject",
  "dead_end_share",
  "arrival_blind_share",
  "largest_component_share",
  "islands",
  "lead_share",
  "lead_ratio",
  "heaviest_family_ratio",
  "empty_families",
  "clusters",
  "narration_share",
  "log_subject_share",
  "lead_family_claim_share",
  "supersessions_per_100_claims",
  "rollovers",
  "overview_coverage",
  "untouched_subject_share",
  "median_days_since_write",
  "dated_outside_chronology_share",
  "decision_shaped_outside_share",
  "empty_family_share",
  "consultations",
  "uncited_share",
  "consulted_subject_share",
  "lead_family_demand_ratio",
];

/** A rename core has signalled but not shipped: labelled ahead of the wire, on purpose. */
const AHEAD_OF_THE_WIRE = ["lead_over_even"];

/** The four table-chrome keys under the same prefix, which name no metric. */
const METRIC_CHROME = ["name", "value", "previous", "noPrevious"];

test("every metric the lens sends has a label in both packs", () => {
  const missing = [];
  for (const name of WIRE_METRICS) {
    for (const locale of ["zh", "en"]) {
      const label = lensBundle[locale][`lens.metric.${name}`];
      if (!label) missing.push(`${locale}: ${name}`);
    }
  }
  assert.deepEqual(missing, [], "a metric with no label renders its raw name to the reader");
});

test("no label lingers for a metric nobody sends any more", () => {
  const known = new Set([...WIRE_METRICS, ...AHEAD_OF_THE_WIRE, ...METRIC_CHROME]);
  const stale = Object.keys(lensBundle.en)
    .filter((key) => key.startsWith("lens.metric."))
    .map((key) => key.slice("lens.metric.".length))
    .filter((name) => !known.has(name));
  // A label for a metric that no longer exists is copy nobody will ever read and the first
  // thing to go stale; a deliberate one ahead of the wire is listed above rather than left
  // to look like a leftover.
  assert.deepEqual(stale, []);
});

test("a share is known by its name, never by how big the number is", () => {
  for (const name of ["dead_end_share", "overview_coverage", "uncited_share"]) {
    assert.equal(isShareMetric(name), true, name);
  }
  for (const name of ["islands", "lead_ratio", "supersessions_per_100_claims", "shares"]) {
    assert.equal(isShareMetric(name), false, name);
  }
});
