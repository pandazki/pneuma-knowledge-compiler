/**
 * The sentence on a neighbourhood row: a connections line written by the overview slot
 * (list marker, path-shaped label, trailing ledger anchors) reads as prose that names the
 * document, and an ordinary claim still flattens to its labels.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/edgeSentence.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const { edgeSentence, canonicalPathOf } = await import(
  `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`
);

const titles = { "projects/flow.md": "Flow", "people/ada.md": "Ada" };
const titleOf = (path) => titles[path] ?? null;

test("a connections line names the document by title, not by its path", () => {
  const line =
    "- [../projects/flow.md](../../projects/flow.md) —— Ada joined the Flow merge. [cite: 63fce8a6 ¶5-19] <!-- c:600ee22a -->";
  assert.equal(edgeSentence(line, titleOf), "Flow —— Ada joined the Flow merge.");
});

test("the trailing ledger anchors an overview line rests on are not prose", () => {
  const line = "- [../people/ada.md](../people/ada.md) —— works with Ada. c:7dcb98b3 c:7408e2e6";
  assert.equal(edgeSentence(line, titleOf), "Ada —— works with Ada.");
});

test("an unknown path-shaped label falls back to its file stem", () => {
  assert.equal(
    edgeSentence("- [../projects/arena.md](../../projects/arena.md) —— why", titleOf),
    "arena —— why",
  );
  assert.equal(edgeSentence("- [../projects/arena.md](../../projects/arena.md) —— why"), "arena —— why");
});

test("an ordinary claim flattens to its labels and keeps its anchors out", () => {
  const claim =
    "【中】On the 7th, [Ada](../people/ada.md) explained **two** strategies for `L1`. [cite: 27af9014 ¶1-5] <!-- c:bf09ee3f -->";
  assert.equal(edgeSentence(claim, titleOf), "【中】On the 7th, Ada explained two strategies for L1.");
});

test("an anchor token inside the sentence is left alone; only the tail is trimmed", () => {
  assert.equal(edgeSentence("see c:abcdef12 for the reason, then act c:12345678"), "see c:abcdef12 for the reason, then act");
});

test("canonical paths drop the relative prefix and the fragment", () => {
  assert.equal(canonicalPathOf("../../projects/x.md#c:1"), "projects/x.md");
  assert.equal(canonicalPathOf("./y.md"), "y.md");
  assert.equal(canonicalPathOf("people/z.md"), "people/z.md");
});
