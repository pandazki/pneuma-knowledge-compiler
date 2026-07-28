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
} = await import(moduleUrl);

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
  assert.throws(() => parseOfficialSourcePayload("{", "meeting"), /JSON/);
  assert.throws(
    () =>
      parseOfficialSourcePayload(
        JSON.stringify({ schema: "pneuma.source.email/v1" }),
        "meeting",
      ),
    /meeting/,
  );
});

test("payload preflight returns the unchanged canonical object", () => {
  const payload = {
    schema: "pneuma.source.im/v1",
    provider: "mock",
    archive_id: "im-test",
  };
  assert.deepEqual(parseOfficialSourcePayload(JSON.stringify(payload), "im"), payload);
});
