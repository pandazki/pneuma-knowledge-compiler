/**
 * Reading a consultation's manifest: what each address is, and which of them the answer
 * cited.
 *
 * The fixture is shaped around the two failures that motivated the module. An address is
 * dispatched on its SHAPE and never on `kind` — the same claim reaches a lane as `claim`
 * from a ranked face and as `component` from a routed lookup, and dispatching on `kind`
 * would render one address two different ways. And the citations are marked INSIDE the
 * manifest rather than listed beside it: they are a subset of it by construction, so two
 * lists would print most rows twice and hide the only relationship a reader came for.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/consultations.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { addressLabel, citedFirst, evidenceRows, parseAddress, parseSpan } =
  await import(moduleUrl);

const CLAIM = { kind: "claim", ref: "c:aa11", path: "memory/people/bao.md" };
const SPAN = { kind: "window", ref: "src-01 ¶2-4", path: "" };
const PAGE = { kind: "document", ref: "memory/topics/delivery.md", path: "" };

test("a span parses into its parts, and a bare paragraph is a one-block span", () => {
  assert.deepEqual(parseSpan("src-01 ¶2-4"), {
    sourceId: "src-01",
    start: 2,
    end: 4,
  });
  assert.deepEqual(parseSpan("src-01 ¶7"), { sourceId: "src-01", start: 7, end: 7 });
});

test("what is not a span says so, rather than being read as a broken one", () => {
  assert.equal(parseSpan("c:aa11"), null);
  assert.equal(parseSpan("memory/people/bao.md"), null);
  assert.equal(parseSpan(" ¶2-4"), null);
  assert.equal(parseSpan("src-01 ¶a-b"), null);
});

test("an address is read for what it IS, never for how the lane reached it", () => {
  // The same claim, arriving through a routed component path. `kind` differs; the address
  // does not, and it is the address that says what the thing is.
  assert.deepEqual(parseAddress({ kind: "component", ref: "c:aa11", path: "p.md" }), {
    shape: "claim",
    anchor: "aa11",
    path: "p.md",
  });
  assert.deepEqual(parseAddress({ kind: "component", ref: "src-01 ¶9", path: "" }), {
    shape: "span",
    sourceId: "src-01",
    start: 9,
    end: 9,
  });
  assert.deepEqual(parseAddress(PAGE), {
    shape: "document",
    path: "memory/topics/delivery.md",
  });
});

test("citations are marked inside the manifest, not listed beside it", () => {
  const rows = evidenceRows([CLAIM, SPAN, PAGE], [SPAN]);
  assert.deepEqual(
    rows.map((r) => [r.ref, r.cited]),
    [
      ["c:aa11", false],
      ["src-01 ¶2-4", true],
      ["memory/topics/delivery.md", false],
    ],
  );
});

test("one address is one row, however many faces reached it", () => {
  const viaComponent = { kind: "component", ref: "c:aa11", path: "memory/people/bao.md" };
  const rows = evidenceRows([CLAIM, viaComponent], []);
  assert.equal(rows.length, 1);
  // The first kind wins — a manifest lists the evidence items before the provenance spans
  // rendered with them, so the kind that says more about the item survives.
  assert.equal(rows[0].kind, "claim");
});

test("a citation the manifest does not carry is still shown, never dropped", () => {
  // The record is what happened. A page that quietly discarded a row would disagree with
  // the record it is showing — which is exactly what an audit chain must not do.
  const rows = evidenceRows([CLAIM], [SPAN]);
  assert.deepEqual(
    rows.map((r) => [r.ref, r.cited]),
    [
      ["c:aa11", false],
      ["src-01 ¶2-4", true],
    ],
  );
});

test("cited addresses come first, each half keeping the lane's own order", () => {
  const second = { kind: "window", ref: "src-02 ¶1", path: "" };
  const rows = evidenceRows([CLAIM, SPAN, second, PAGE], [SPAN, PAGE]);
  assert.deepEqual(
    citedFirst(rows).map((r) => r.ref),
    ["src-01 ¶2-4", "memory/topics/delivery.md", "c:aa11", "src-02 ¶1"],
  );
});

test("a page is labelled by its last segment; an anchor and a span keep their grammar", () => {
  assert.equal(addressLabel(parseAddress(CLAIM)), "c:aa11");
  assert.equal(addressLabel(parseAddress(SPAN)), "src-01 ¶2-4");
  assert.equal(addressLabel(parseAddress({ ...SPAN, ref: "src-01 ¶7" })), "src-01 ¶7");
  assert.equal(addressLabel(parseAddress(PAGE)), "delivery.md");
});
