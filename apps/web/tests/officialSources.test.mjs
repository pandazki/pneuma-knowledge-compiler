import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/views/ingest/officialSources.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  OFFICIAL_SOURCE_OPTIONS,
  detectOfficialSourceKind,
  parseOfficialSourcePayload,
  summarizeOfficialSourcePayload,
} = await import(moduleUrl);

/**
 * The module states WHAT to say (a message key plus its parameters) and the view says it in
 * the reader's language, so the injected translator here echoes both back — that keeps these
 * assertions about the module's own decisions rather than about a dictionary it cannot see.
 */
const i18n = {
  t: (key, params) => [key, ...Object.values(params ?? {})].join(" "),
};

test("the Web import surface publishes exactly the four official source contracts", () => {
  assert.deepEqual(
    OFFICIAL_SOURCE_OPTIONS.map(({ kind, schema }) => ({ kind, schema })),
    [
      { kind: "meeting", schema: "pneuma.source.meeting/v1" },
      {
        kind: "document_library",
        schema: "pneuma.source.document-library/v1",
      },
      { kind: "im", schema: "pneuma.source.im/v1" },
      { kind: "email", schema: "pneuma.source.email/v1" },
    ],
  );
});

test("source kind detection follows the contract schema", () => {
  assert.equal(
    detectOfficialSourceKind({ schema: "pneuma.source.document-library/v1" }),
    "document_library",
  );
  assert.equal(detectOfficialSourceKind({ schema: "pneuma.source.email/v1" }), "email");
  assert.equal(detectOfficialSourceKind({ schema: "unknown" }), null);
});

test("payload preflight rejects malformed JSON and a mismatched selected kind", () => {
  assert.throws(() => parseOfficialSourcePayload("{", "meeting", i18n), /jsonParse/);
  assert.throws(
    () =>
      parseOfficialSourcePayload(
        JSON.stringify({ schema: "pneuma.source.email/v1" }),
        "meeting",
        i18n,
      ),
    /kindMismatch meeting pneuma\.source\.meeting\/v1 pneuma\.source\.email\/v1/,
  );
});

test("payload preflight returns the unchanged canonical object", () => {
  const payload = {
    schema: "pneuma.source.im/v1",
    provider: "mock",
    archive_id: "im-test",
  };
  assert.deepEqual(
    parseOfficialSourcePayload(JSON.stringify(payload), "im", i18n),
    payload,
  );
});

test("every published option names a translatable label, description and citation unit", () => {
  for (const option of OFFICIAL_SOURCE_OPTIONS) {
    assert.equal(option.labelKey, `enum.sourceKind.${option.kind}`);
    assert.equal(option.descriptionKey, `ingest.official.${option.kind}.description`);
    assert.equal(option.citationUnitKey, `ingest.official.${option.kind}.citationUnit`);
  }
});

test("a payload without its own title falls back to a per-contract message key", () => {
  const summary = summarizeOfficialSourcePayload({ provider: "mock" }, "meeting", i18n);
  assert.equal(summary.title, "ingest.official.untitled.meeting");
  assert.equal(summary.itemLabel, "segments");
  assert.equal(summary.itemCount, 0);
  // A title in the payload is data and travels through untouched.
  assert.equal(
    summarizeOfficialSourcePayload({ title: "Q3 review" }, "meeting", i18n).title,
    "Q3 review",
  );
});
