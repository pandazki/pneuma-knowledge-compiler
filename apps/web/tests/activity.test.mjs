import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/activity.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { buildActivityGrid } = await import(moduleUrl);

test("84-day Monday-to-Sunday activity fills exactly twelve heatmap weeks", () => {
  const start = Date.UTC(2026, 2, 2);
  const days = Array.from({ length: 84 }, (_, index) => ({
    date: new Date(start + index * 86_400_000).toISOString().slice(0, 10),
    count: index % 5,
    kinds: { meeting: index % 5 },
  }));

  const grid = buildActivityGrid(days);
  assert.equal(grid.weeks, 12);
  assert.equal(grid.cells.length, 84);
  assert.equal(grid.firstDate, "2026-03-02");
  assert.equal(grid.lastDate, "2026-05-24");
});

test("short histories keep a readable twelve-week context window", () => {
  const grid = buildActivityGrid([
    { date: "2026-07-29", count: 3, kinds: { job: 3 } },
  ]);

  assert.equal(grid.weeks, 12);
  assert.equal(grid.cells.length, 84);
  assert.equal(grid.cells.filter((cell) => cell.active).length, 1);
  assert.equal(grid.maxCount, 3);
});

test("long histories stay bounded to the latest eighteen weeks", () => {
  const grid = buildActivityGrid([
    { date: "2025-01-01", count: 4, kinds: { snapshot: 4 } },
    { date: "2026-07-29", count: 2, kinds: { patch: 2 } },
  ]);

  assert.equal(grid.weeks, 18);
  assert.equal(grid.cells.length, 126);
  assert.equal(grid.cells.some((cell) => cell.date === "2025-01-01"), false);
  assert.equal(grid.cells.some((cell) => cell.date === "2026-07-29"), true);
});
