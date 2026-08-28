import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/inlineMarkdown.ts", import.meta.url);
const transformed = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { splitInlineMarkdown, isExternalHref } = await import(moduleUrl);

test("plain prose is one text segment", () => {
  assert.deepEqual(splitInlineMarkdown("A sentence with no markup."), [
    { kind: "text", text: "A sentence with no markup." },
  ]);
  assert.deepEqual(splitInlineMarkdown(""), []);
});

test("a relative cross-link becomes a link segment with its label and href", () => {
  assert.deepEqual(
    splitInlineMarkdown("On 2026-05-07, [Project A](../projects/project-a.md) was paused."),
    [
      { kind: "text", text: "On 2026-05-07, " },
      { kind: "link", label: "Project A", href: "../projects/project-a.md" },
      { kind: "text", text: " was paused." },
    ],
  );
});

test("code spans and bold are their own segments; single asterisks stay literal", () => {
  assert.deepEqual(splitInlineMarkdown("run `make build` — **twice** — 3*4"), [
    { kind: "text", text: "run " },
    { kind: "code", text: "make build" },
    { kind: "text", text: " — " },
    { kind: "strong", text: "twice" },
    { kind: "text", text: " — 3*4" },
  ]);
});

test("adjacent markup with no text between yields no empty text segments", () => {
  assert.deepEqual(splitInlineMarkdown("[a](x.md)[b](y.md)"), [
    { kind: "link", label: "a", href: "x.md" },
    { kind: "link", label: "b", href: "y.md" },
  ]);
});

test("a link with a hash fragment keeps the whole href", () => {
  assert.deepEqual(splitInlineMarkdown("[x](../topics/t.md#section)"), [
    { kind: "link", label: "x", href: "../topics/t.md#section" },
  ]);
});

test("only absolute web URLs count as external", () => {
  assert.equal(isExternalHref("https://example.com/a"), true);
  assert.equal(isExternalHref("http://example.com"), true);
  assert.equal(isExternalHref("../people/x.md"), false);
  assert.equal(isExternalHref("mailto:a@b.c"), false);
});
