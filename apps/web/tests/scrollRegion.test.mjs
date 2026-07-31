/**
 * The scroll-region edge arithmetic: which edge is hiding content, and therefore which edge
 * fades.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/scrollRegion.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { isOverflowing, scrollFade } = await import(moduleUrl);

const m = (scrollTop, clientHeight, scrollHeight) => ({ scrollTop, clientHeight, scrollHeight });

test("a region that fits its content fades at neither edge", () => {
  assert.equal(isOverflowing(m(0, 400, 400)), false);
  assert.equal(scrollFade(m(0, 400, 400)), "none");
  assert.equal(scrollFade(m(0, 400, 380)), "none", "content shorter than the box");
});

test("an overflowing region fades at whichever edge still hides content", () => {
  assert.equal(scrollFade(m(0, 400, 1200)), "bottom", "parked at the top");
  assert.equal(scrollFade(m(300, 400, 1200)), "both", "mid-scroll");
  assert.equal(scrollFade(m(800, 400, 1200)), "top", "parked at the bottom");
});

test("sub-pixel layout noise is not overflow", () => {
  assert.equal(isOverflowing(m(0, 400, 400.5)), false);
  assert.equal(scrollFade(m(0.4, 400, 1200)), "bottom", "a fractional scrollTop is still the top");
  assert.equal(scrollFade(m(799.6, 400, 1200)), "top", "and a fractional gap is still the end");
});

test("a hairline overflow within the tolerance of both ends fades nothing", () => {
  // 1.5px of overflow, scrolled 0.8px: counted as overflowing, yet neither edge is far
  // enough from an end to be worth a fade.
  assert.equal(isOverflowing(m(0.8, 400, 401.5)), true);
  assert.equal(scrollFade(m(0.8, 400, 401.5)), "none");
});
