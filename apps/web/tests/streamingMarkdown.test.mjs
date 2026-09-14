/**
 * Markdown that is still arriving.
 *
 * The Steward's prose is rendered on every delta, so the tail of it is always half-typed. The
 * two constructs that are FRAMES rather than sentences — a fenced code block and a GFM table —
 * make the parser guess while the frame is open, and the page jumps as it changes its mind.
 * `splitStreamingMarkdown` is the whole of the fix: settled Markdown on one side, the
 * unfinished frame on the other, rendered as the preformatted text it is about to become.
 *
 * What is asserted here is that nothing is ever LOST in that cut — every character typed so
 * far comes back out of one side or the other — and that a frame which has closed goes back to
 * being ordinary Markdown, so the reflow happens exactly once.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const { isDelimiterRow, splitStreamingMarkdown } = await import(
  await tsModuleUrl(new URL("../src/lib/streamingMarkdown.ts", import.meta.url))
);

test("settled prose passes through untouched", () => {
  const text = "Here is **what I found**, and a list:\n\n- one\n- two\n";
  assert.deepEqual(splitStreamingMarkdown(text), { body: text, pending: null });
  assert.deepEqual(splitStreamingMarkdown(""), { body: "", pending: null });
});

test("an unterminated fence is cut off the tail and kept as preformatted text", () => {
  const { body, pending } = splitStreamingMarkdown("I ran this:\n\n```bash\npkc jobs --limit 5\npkc dr");
  assert.equal(body, "I ran this:\n");
  assert.equal(pending.kind, "code");
  assert.equal(pending.info, "bash");
  assert.equal(pending.text, "pkc jobs --limit 5\npkc dr");
});

test("the moment the fence closes it is ordinary Markdown again", () => {
  const closed = "I ran this:\n\n```bash\npkc jobs\n```\n\nand it was fine.";
  assert.deepEqual(splitStreamingMarkdown(closed), { body: closed, pending: null });
  // A second block opening after the first one closed is the pending one.
  const { body, pending } = splitStreamingMarkdown(`${closed}\n\n~~~\nstill typ`);
  assert.equal(body, `${closed}\n`);
  assert.equal(pending.kind, "code");
  assert.equal(pending.text, "still typ");
});

test("a fence is cut even when it has only just opened, and nothing is lost either way", () => {
  for (const text of [
    "a paragraph\n\n```",
    "a paragraph\n\n```ts\n",
    "a paragraph\n\n```ts\nconst x = 1;",
    "```\nno prose at all",
  ]) {
    const { body, pending } = splitStreamingMarkdown(text);
    const seen = [body, pending?.info ?? "", pending?.text ?? ""].join("");
    // Every character that arrived is on one side of the cut or the other.
    assert.equal(seen.replace(/[\s`~]/g, ""), text.replace(/[\s`~]/g, ""), text);
  }
});

test("a table with no delimiter row yet is held back rather than flickering into a table", () => {
  const { body, pending } = splitStreamingMarkdown("Two jobs:\n\n| job | status |");
  assert.equal(body, "Two jobs:\n");
  assert.equal(pending.kind, "table");
  assert.equal(pending.text, "| job | status |");

  // Half a delimiter row is still not a table.
  assert.equal(splitStreamingMarkdown("| job | status |\n| --- | st").pending.kind, "table");

  // With the delimiter row complete, the renderer takes it — rows stream in without a cut.
  const settled = "| job | status |\n| --- | --- |\n| j-1 | done |";
  assert.deepEqual(splitStreamingMarkdown(settled), { body: settled, pending: null });
  assert.deepEqual(splitStreamingMarkdown("| job | status |\n|:--|--:|"), {
    body: "| job | status |\n|:--|--:|",
    pending: null,
  });
});

test("pipes inside an open fence are code, not a table", () => {
  const { pending } = splitStreamingMarkdown("```\n| a | b |\n| c");
  assert.equal(pending.kind, "code");
  assert.equal(pending.text, "| a | b |\n| c");
});

test("a delimiter row is what GFM says it is, and nothing looser", () => {
  assert.equal(isDelimiterRow("| --- | --- |"), true);
  assert.equal(isDelimiterRow("|:---|---:|:-:|"), true);
  assert.equal(isDelimiterRow("--- | ---"), true);
  assert.equal(isDelimiterRow("| job | status |"), false);
  assert.equal(isDelimiterRow("| -- x |"), false);
  assert.equal(isDelimiterRow(""), false);
});
