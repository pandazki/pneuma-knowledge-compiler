/**
 * The display formatters, pinned.
 *
 * `lib/format` reads its locale off `lib/i18n`, which imports the assembled dictionary — so
 * that import is stubbed with the two facts this file actually needs (the Intl tags and the
 * grouping function), exactly as `i18n.test.mjs` stubs the catalogue.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const formatUrl = new URL("../src/lib/format.ts", import.meta.url);
const stub = `
const TAGS = { zh: "zh-CN", en: "en-CA" };
const activeLocale = () => "en";
const intlTag = (locale = "en") => TAGS[locale];
const groupNumber = (n, locale) => (Number.isFinite(n) ? n.toLocaleString(TAGS[locale]) : "—");
`;
const source = (await readFile(formatUrl, "utf8")).replace(
  /^import \{[^}]*\} from "\.\/i18n";$/m,
  `${stub}\ntype Locale = "zh" | "en";`,
);
const transformed = await transformWithEsbuild(source, formatUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { fmtCount, fmtDay, fmtDateTime, fmtMoment, fmtMoney, squish, usageLine } =
  await import(moduleUrl);

test("counts are grouped per locale, and nothing else is", () => {
  assert.equal(fmtCount(5832, "en"), "5,832");
  assert.equal(fmtCount(999, "en"), "999");
  assert.equal(fmtCount(0, "en"), "0");
  assert.equal(fmtCount(Number.NaN, "en"), "—");
});

test("a day is a day; a full moment carries its year", () => {
  assert.equal(fmtDay("2026-07-29", "en"), "2026-07-29");
  assert.equal(fmtDay("not a day", "en"), "not a day");
  assert.equal(fmtDay(null, "en"), "—");
  // The galley stamp: the year is the whole point — it sits beside a corpus date.
  assert.match(fmtDateTime("2026-08-27T13:49:21Z", "en"), /^2026-08-27, \d\d:\d\d$/);
  assert.equal(fmtDateTime(null, "en"), "—");
  assert.equal(fmtDateTime("nonsense", "en"), "nonsense");
});

test("a moment of unknown shape reads as a day, a stamp, or itself", () => {
  assert.equal(fmtMoment("2026-07-29", "en"), "2026-07-29");
  assert.match(fmtMoment("2026-07-29T09:51:00+08:00", "en"), /^2026-07-29, \d\d:\d\d$/);
  // Source metadata carries whatever the provider wrote; prose is left alone.
  assert.equal(fmtMoment("last Tuesday", "en"), "last Tuesday");
  assert.equal(fmtMoment("2026", "en"), "2026");
  assert.equal(fmtMoment(null, "en"), "—");
});

test("display whitespace is collapsed, never reproduced", () => {
  assert.equal(squish("compile:  from        8 people pages"), "compile: from 8 people pages");
  assert.equal(squish("  padded \n line  "), "padded line");
  assert.equal(squish(null), "");
});

test("money carries the currency the deployment declared, and never a symbol we chose", () => {
  assert.equal(fmtMoney({ amount: 12.5, currency: "USD" }), "12.50 USD");
  assert.equal(fmtMoney({ amount: 3.2, currency: "CNY" }), "3.20 CNY");
});

test("the decimals follow the amount, so a cheap call does not print as free", () => {
  // A compile run costs dollars; one fast answer costs fractions of a cent. Two decimals
  // everywhere would round the second to 0.00 — money that was really spent, shown as none.
  assert.equal(fmtMoney({ amount: 0.0412, currency: "USD" }), "0.0412 USD");
  assert.equal(fmtMoney({ amount: 0.001238, currency: "USD" }), "0.001238 USD");
  assert.equal(fmtMoney({ amount: 0, currency: "USD" }), "0.000000 USD");
});

test("no cost is an em dash — the absence of a price is not a price of zero", () => {
  assert.equal(fmtMoney(null), "—");
  assert.equal(fmtMoney(undefined), "—");
  assert.equal(fmtMoney({ amount: Number.NaN, currency: "USD" }), "—");
});

const SPENT = {
  input_tokens: 4310,
  output_tokens: 182,
  total_tokens: 4492,
  cache_read: 1780,
  cache_creation: 2524,
};

test("the usage line reads as field names and grouped counts", () => {
  assert.equal(
    usageLine(SPENT, null, "en"),
    "in 4,310 · out 182 · total 4,492 · cache_read 1,780 · cache_creation 2,524",
  );
});

test("a declared price adds the money half; an undeclared one adds nothing at all", () => {
  assert.equal(
    usageLine(SPENT, { amount: 0.0412, currency: "USD" }, "en"),
    "in 4,310 · out 182 · total 4,492 · cache_read 1,780 · cache_creation 2,524 · cost 0.0412 USD",
  );
  // The whole point of the refusal: a deployment that declared no rate for this model gets
  // the tokens and NO cost segment — not `cost 0.00 USD`, which would be a claim.
  assert.ok(!usageLine(SPENT, undefined, "en").includes("cost"));
  assert.ok(!usageLine(SPENT, null, "en").includes("cost"));
});

test("a record written before usage was kept reports zeros rather than breaking the line", () => {
  assert.equal(
    usageLine({}, null, "en"),
    "in 0 · out 0 · total 0 · cache_read 0 · cache_creation 0",
  );
});
