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
const { fmtCount, fmtDay, fmtDateTime, fmtMoment, squish } = await import(moduleUrl);

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
