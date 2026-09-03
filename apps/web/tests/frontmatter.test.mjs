/**
 * Frontmatter, as a reader sees it.
 *
 * The property under test is a terminology rule with teeth: `archive` names ONE thing — the
 * place an owner puts what should leave every default retrieval. A CLOSED VOLUME is not that,
 * yet it carries two legacy on-disk spellings that say the word (`archived_from`, and a
 * `type` that falls back to `archive`). The keys are frozen — they are in every user's git
 * library — so the console is where the reading is corrected, and these tests pin both halves:
 * the legacy spellings get their decided words, and NOTHING else changes.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function importTs(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
  return import(moduleUrl);
}

const {
  DOC_ID_KEY,
  LEGACY_VOLUME_TYPE,
  VOLUME_OF_KEY,
  frontmatterField,
  frontmatterFields,
  frontmatterInline,
  frontmatterValue,
} = await importTs(new URL("../src/lib/frontmatter.ts", import.meta.url));

/** The dictionary, loaded the way tests/i18n.test.mjs does: `defineMessages` is identity. */
const libraryBundle = await (async () => {
  const url = new URL("../src/i18n/library.ts", import.meta.url);
  const text = (await readFile(url, "utf8")).replace(
    /^import \{[^}]*\} from "\.\/define";$/m,
    "const defineMessages = (bundle) => bundle;",
  );
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
  return (await import(moduleUrl)).library;
})();

/** A closed volume's frontmatter, exactly as core `compile/rollover.py` stamps it. */
const CLOSED_VOLUME = [
  ["doc_id", "8f2c1a0b"],
  ["type", "archive"],
  ["slug", "a01"],
  ["archived_from", "topics/ask-actions-before-features.md"],
  ["rollover_volume", "01"],
  ["rollover_span", "2026-01-04..2026-03-09"],
];

/* --------------------------------------------------- the two legacy spellings */

test("the volume's owning-page key is labelled, never printed as `archived_from`", () => {
  const field = frontmatterField(VOLUME_OF_KEY, "topics/ask-actions-before-features.md");
  assert.equal(field.labelKey, "library.frontmatter.volumeOf");
  assert.equal(field.kind, "path", "the value names a document, so it can be a door");
  assert.equal(field.text, "topics/ask-actions-before-features.md");
  assert.equal(field.textKey, null, "the path is the library's own data and stays verbatim");
});

test("the volume's `type: archive` fallback reads as a closed volume", () => {
  assert.equal(frontmatterField("type", "archive").textKey, "library.frontmatter.closedVolume");
});

test("both labels say `closed volume` in both columns, and neither says `archive`", () => {
  for (const key of ["library.frontmatter.volumeOf", "library.frontmatter.closedVolume"]) {
    assert.ok(libraryBundle.zh[key], `zh ${key}`);
    assert.ok(libraryBundle.en[key], `en ${key}`);
    assert.match(libraryBundle.en[key], /closed volume|Closed volume/);
    assert.doesNotMatch(libraryBundle.en[key], /archiv/i, `en ${key} still says "archive"`);
    assert.doesNotMatch(libraryBundle.zh[key], /归档/, `zh ${key} still says 「归档」`);
    assert.match(libraryBundle.zh[key], /卷/);
  }
});

test("a closed volume's whole strip has no `archive` left in it for a reader to read", () => {
  const fields = frontmatterFields(CLOSED_VOLUME);
  const shown = fields.map((f) => (f.labelKey ? libraryBundle.en[f.labelKey] : f.key));
  const values = fields.map((f) => (f.textKey ? libraryBundle.en[f.textKey] : f.text));
  for (const word of [...shown, ...values]) {
    assert.doesNotMatch(word, /archiv/i, `"${word}" still reads as an archive`);
  }
  assert.deepEqual(shown, [
    "type",
    "slug",
    "Closed volume of",
    "rollover_volume",
    "rollover_span",
  ]);
  assert.deepEqual(values, [
    "closed volume",
    "a01",
    "topics/ask-actions-before-features.md",
    "01",
    "2026-01-04..2026-03-09",
  ]);
});

/* ------------------------------------------------ and nothing else changes */

test("a page that declares its own type keeps it — the fallback is the only exception", () => {
  assert.equal(frontmatterField("type", "topic").textKey, null);
  assert.equal(frontmatterField("type", "topic").text, "topic");
  // Only `type` earns that reading: another key holding the same word is data.
  assert.equal(frontmatterField("slug", LEGACY_VOLUME_TYPE).textKey, null);
});

test("an ordinary key is its own label and its own value, as before", () => {
  const field = frontmatterField("rollover_volume", "01");
  assert.equal(field.labelKey, null);
  assert.equal(field.textKey, null);
  assert.equal(field.kind, "plain");
  assert.equal(field.text, "01");
});

test("list-valued component keys still become chips, and only those keys", () => {
  const identities = frontmatterField("identities", "lin-zhou, 林舟 ,");
  assert.equal(identities.kind, "chips");
  assert.deepEqual(identities.chips, ["lin-zhou", "林舟"]);
  assert.deepEqual(frontmatterField("aliases", ["Zhou", " Lin "]).chips, ["Zhou", "Lin"]);
  // A key outside the set keeps its one-line rendering however it is written.
  assert.equal(frontmatterField("owners", ["a", "b"]).kind, "plain");
});

test("an empty list falls back to the one-line rendering rather than to no value at all", () => {
  const field = frontmatterField("aliases", "  ,  ");
  assert.equal(field.kind, "plain");
  assert.equal(field.text, "  ,  ");
});

test("doc_id is left out of the fields: the strip prints the address apart", () => {
  const keys = frontmatterFields(CLOSED_VOLUME).map((f) => f.key);
  assert.ok(!keys.includes(DOC_ID_KEY));
  assert.equal(keys.length, CLOSED_VOLUME.length - 1);
  assert.deepEqual(keys, CLOSED_VOLUME.slice(1).map(([k]) => k), "declaration order is kept");
});

test("the two value spellings: JSON in the strip, members inline in the masthead", () => {
  assert.equal(frontmatterValue(["a", "b"]), '["a","b"]');
  assert.equal(frontmatterInline(["a", "b"]), "a, b");
  assert.equal(frontmatterValue({ n: 1 }), '{"n":1}');
  assert.equal(frontmatterInline({ n: 1 }), '{"n":1}');
  assert.equal(frontmatterInline("plain"), "plain");
});

test("an empty path value stays plain: there is nothing to open", () => {
  assert.equal(frontmatterField(VOLUME_OF_KEY, "   ").kind, "plain");
  assert.equal(
    frontmatterField(VOLUME_OF_KEY, "   ").labelKey,
    "library.frontmatter.volumeOf",
    "it is still not the word `archived_from`",
  );
});
