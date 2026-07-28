import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/model.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { patchChanges } = await import(moduleUrl);

test("history can describe changed paths without loading the canonical projection", () => {
  const changes = patchChanges(null, {
    patch_id: "ref-01",
    documents: [],
    changed_paths: ["domains/work/documents/projects/relay/status.md"],
  });

  assert.deepEqual(changes, [
    {
      document_id: null,
      path: "projects/relay/status.md",
      change_type: "modified",
    },
  ]);
});
