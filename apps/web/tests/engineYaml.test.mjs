/**
 * engineYaml: the minimal YAML plumbing behind the Engine Console. Round-trips the exact
 * shapes engine files use — top-level scalars with comments, and the prompt overlays' one
 * nested `overlays:` mapping of `key: |` literal blocks — and preserves every line it was
 * not asked to touch.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/engineYaml.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  getYamlScalar,
  setYamlScalar,
  quoteYamlString,
  unquoteYamlScalar,
  getOverlayMap,
  setOverlayEntry,
  removeOverlayEntry,
} = await import(moduleUrl);

const CHALLENGE = [
  "# Challenge: the post-compile gap audit.",
  "enabled: true",
  "max_rounds: 2",
  "max_questions: 4",
  "compensate: true",
  "",
].join("\n");

test("getYamlScalar reads a top-level scalar and reports absence honestly", () => {
  assert.equal(getYamlScalar(CHALLENGE, "enabled"), "true");
  assert.equal(getYamlScalar(CHALLENGE, "max_rounds"), "2");
  assert.equal(getYamlScalar(CHALLENGE, "missing"), null);
  assert.equal(getYamlScalar("profile: |\n  Some prose.\n", "profile"), null, "a block is not a scalar");
});

test("setYamlScalar replaces the value in place and keeps every other line", () => {
  const out = setYamlScalar(CHALLENGE, "enabled", false);
  assert.equal(getYamlScalar(out, "enabled"), "false");
  assert.ok(out.startsWith("# Challenge: the post-compile gap audit.\n"), "comment survives");
  assert.equal(getYamlScalar(out, "max_rounds"), "2", "neighbours survive");
  assert.equal(getYamlScalar(out, "compensate"), "true");
  assert.equal(out.split("\n").length, CHALLENGE.split("\n").length, "no lines added or lost");
});

test("setYamlScalar appends a missing key at the end", () => {
  const out = setYamlScalar("a: 1\n", "b", 2);
  assert.equal(out, "a: 1\nb: 2\n");
  const out2 = setYamlScalar("a: 1", "b", 2);
  assert.equal(out2, "a: 1\nb: 2\n", "a missing trailing newline is repaired first");
});

test("scalar set/get round-trips booleans and ints as their YAML spellings", () => {
  let out = setYamlScalar(CHALLENGE, "compensate", false);
  out = setYamlScalar(out, "max_questions", 7);
  assert.equal(getYamlScalar(out, "compensate"), "false");
  assert.equal(getYamlScalar(out, "max_questions"), "7");
});

/*
 * codex review #7: string knobs were written with `String(value)` and no quoting, so an empty
 * value became `key:` (YAML null, refused by the service), and a `: `, `#`, quote or newline
 * changed the file's meaning or broke it outright.
 */
test("a string knob is always quoted, so nothing about its content can change the shape", () => {
  assert.equal(setYamlScalar("rerank_model: x\n", "rerank_model", ""), 'rerank_model: ""\n');
  assert.equal(
    setYamlScalar("m: x\n", "m", "openrouter:qwen/qwen3-max"),
    'm: "openrouter:qwen/qwen3-max"\n',
  );
  assert.equal(setYamlScalar("m: x\n", "m", "a # b"), 'm: "a # b"\n');
  assert.equal(setYamlScalar("m: x\n", "m", 'say "no"'), 'm: "say \\"no\\""\n');
  assert.equal(setYamlScalar("m: x\n", "m", "a\\b"), 'm: "a\\\\b"\n');
  assert.equal(setYamlScalar("m: x\n", "m", "one\ntwo"), 'm: "one\\ntwo"\n');
  assert.equal(setYamlScalar("m: x\n", "m", "null"), 'm: "null"\n', "not YAML null");
  assert.equal(setYamlScalar("m: x\n", "m", "1.0"), 'm: "1.0"\n', "not a number");
  assert.equal(setYamlScalar("m: x\n", "m", "yes"), 'm: "yes"\n', "not a bool");
});

test("quoteYamlString and unquoteYamlScalar round-trip every awkward value", () => {
  for (const value of ["", " ", "a: b", "# c", 'q"q', "back\\slash", "l1\nl2", "\ttab", "null", "yes", "1.5"]) {
    assert.equal(unquoteYamlScalar(quoteYamlString(value)), value, JSON.stringify(value));
  }
  assert.equal(unquoteYamlScalar("plain"), "plain", "an unquoted scalar reads verbatim");
  assert.equal(unquoteYamlScalar("'single'"), "single");
});

/*
 * Prompt overlays live UNDER a top-level `overlays:` key — the shape the scaffold generates
 * and the service validates. codex review #4: these helpers used to treat catalog keys as
 * top-level entries, so reading a real file yielded one fake overlay named "overlays" and
 * every add wrote a key the service refuses. The fixtures below are the real nested shape,
 * and the two contract tests at the bottom pin it against the scaffold's own file.
 */
const OVERLAYS = [
  "# Prompt overlays: catalog key -> replacement clause.",
  "overlays:",
  "  recall.answer.style: |",
  "    Answer bluntly, numbered findings.",
  "    Name the system first.",
  "",
].join("\n");

const EMPTY_OVERLAYS = ["# Prompt overlays: catalog key -> replacement clause.", "overlays: {}", ""].join("\n");

test("getOverlayMap reads the nested mapping, not the top-level key", () => {
  const map = getOverlayMap(OVERLAYS);
  assert.deepEqual(map, {
    "recall.answer.style": "Answer bluntly, numbered findings.\nName the system first.\n",
  });
  assert.deepEqual(getOverlayMap(EMPTY_OVERLAYS), {}, "`overlays: {}` is no overrides");
  assert.deepEqual(getOverlayMap("# nothing yet\n"), {}, "no overlays key at all is no overrides");
  assert.deepEqual(getOverlayMap("overlays:\n"), {}, "a keyless overlays mapping is no overrides");
});

test("getOverlayMap unquotes a scalar clause", () => {
  const map = getOverlayMap('overlays:\n  gate.anchor_continuity: "an anchor never moves"\n');
  assert.deepEqual(map, { "gate.anchor_continuity": "an anchor never moves" });
});

test("setOverlayEntry adds a new override inside the mapping, comment intact", () => {
  const out = setOverlayEntry(OVERLAYS, "gate.claim_without_provenance", "Every claim cites.\nOr it is rejected.");
  const map = getOverlayMap(out);
  assert.equal(map["recall.answer.style"], "Answer bluntly, numbered findings.\nName the system first.\n");
  assert.equal(map["gate.claim_without_provenance"], "Every claim cites.\nOr it is rejected.\n");
  assert.ok(out.startsWith("# Prompt overlays"), "comment survives");
  assert.equal(out.split("\n").filter((l) => l === "overlays:").length, 1, "one overlays key");
  assert.ok(
    out.includes("  gate.claim_without_provenance: |\n    Every claim cites.\n    Or it is rejected."),
    "the entry is indented under overlays, its body one level deeper",
  );
});

test("setOverlayEntry turns `overlays: {}` into a real mapping", () => {
  const out = setOverlayEntry(EMPTY_OVERLAYS, "a.b", "one");
  assert.deepEqual(getOverlayMap(out), { "a.b": "one\n" });
  assert.equal(out, "# Prompt overlays: catalog key -> replacement clause.\noverlays:\n  a.b: |\n    one\n");
});

test("setOverlayEntry adds the overlays key to a file that has none", () => {
  const out = setOverlayEntry("# h\n", "a.b", "one");
  assert.equal(out, "# h\noverlays:\n  a.b: |\n    one\n");
});

test("setOverlayEntry replaces an existing override in place", () => {
  const out = setOverlayEntry(OVERLAYS, "recall.answer.style", "Terse.");
  assert.deepEqual(getOverlayMap(out), { "recall.answer.style": "Terse.\n" });
});

test("removeOverlayEntry drops the entry and restores `overlays: {}` when it was the last", () => {
  const out = removeOverlayEntry(OVERLAYS, "recall.answer.style");
  assert.deepEqual(getOverlayMap(out), {});
  assert.equal(out, EMPTY_OVERLAYS, "the file still states an empty override map");
  assert.equal(removeOverlayEntry(OVERLAYS, "nope"), OVERLAYS, "a missing key changes nothing");
  assert.equal(removeOverlayEntry(EMPTY_OVERLAYS, "a.b"), EMPTY_OVERLAYS);
});

test("overlay add → edit → remove composes like the picker drives it", () => {
  let out = setOverlayEntry(EMPTY_OVERLAYS, "a.b", "one");
  out = setOverlayEntry(out, "c.d", "two\nlines");
  out = setOverlayEntry(out, "a.b", "replaced");
  assert.deepEqual(getOverlayMap(out), { "a.b": "replaced\n", "c.d": "two\nlines\n" });
  out = removeOverlayEntry(out, "c.d");
  assert.deepEqual(getOverlayMap(out), { "a.b": "replaced\n" });
});

/* ------------------------------------------------------- the cross-surface contract */

const scaffoldOverlays = JSON.parse(
  await readFile(new URL("../src/engine/fixtures/state.json", import.meta.url), "utf8"),
).files["prompts/overlays.yaml"];

test("the scaffold's own overlays file reads as its overrides, not as one fake entry", () => {
  const map = getOverlayMap(scaffoldOverlays);
  assert.deepEqual(Object.keys(map), ["recall.close.answer_honestly"]);
  assert.ok(map["recall.close.answer_honestly"].startsWith("When the records do not answer"));
  assert.ok(!("overlays" in map), "the container key is not an overlay");
});

test("add → edit → remove over the scaffold file produces the pinned contract bytes", async () => {
  // The other half of this contract is a python test that POSTs this exact file to
  // /v1/engine/apply and requires a 200: tests/contract/overlays.expected.yaml is the one
  // artifact both surfaces read, so a helper that drifts out of the service's accepted shape
  // fails here or there rather than in a user's console.
  // The clause keeps `{preview}` and `{anchor}`: the service refuses an override that drops
  // a placeholder its original declares, so the pinned bytes have to be a legal override or
  // this contract would pin something the console can never save.
  let out = setOverlayEntry(scaffoldOverlays, "gate.claim_without_provenance", "Every claim cites its blocks: \"{preview}…\" (c:{anchor}).\nOr the gate rejects it.");
  out = setOverlayEntry(out, "gate.claim_without_provenance", "Every claim cites its blocks: \"{preview}…\" (c:{anchor}).");
  out = removeOverlayEntry(out, "recall.close.answer_honestly");
  const expected = await readFile(new URL("./contract/overlays.expected.yaml", import.meta.url), "utf8");
  assert.equal(out, expected);
  assert.deepEqual(getOverlayMap(out), {
    "gate.claim_without_provenance": "Every claim cites its blocks: \"{preview}…\" (c:{anchor}).\n",
  });
});
