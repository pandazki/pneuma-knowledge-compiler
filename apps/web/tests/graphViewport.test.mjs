import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/graphViewport.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { limitGraphNeighborhood, pickGraphHub, sliceGraph } = await import(moduleUrl);

const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];
const edges = [
  { source: "a", target: "b" },
  { source: "a", target: "c" },
  { source: "d", target: "a" },
  { source: "b", target: "missing" },
];

test("graph hub is a connected readable entry point", () => {
  assert.equal(pickGraphHub(nodes, edges), "a");
  assert.equal(pickGraphHub([], edges), null);
});

test("graph slice keeps only visible nodes and edges fully inside the slice", () => {
  const sliced = sliceGraph(nodes, edges, new Set(["a", "b", "missing"]));
  assert.deepEqual(
    sliced.nodes.map((node) => node.id),
    ["a", "b"],
  );
  assert.deepEqual(sliced.edges, [{ source: "a", target: "b" }]);
});

test("dense graph neighborhoods keep the center and a deterministic bounded slice", () => {
  const denseNodes = [
    { id: "hub", title: "中心" },
    { id: "a", title: "甲" },
    { id: "b", title: "乙" },
    { id: "c", title: "丙" },
  ];
  const denseEdges = [
    { source: "hub", target: "a" },
    { source: "hub", target: "b" },
    { source: "hub", target: "c" },
    { source: "a", target: "b" },
  ];
  const limited = limitGraphNeighborhood(
    denseNodes,
    denseEdges,
    "hub",
    new Set(denseNodes.map((node) => node.id)),
    3,
  );
  assert.deepEqual([...limited], ["hub", "a", "b"]);
});
