import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/snapshotPagination.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { appendUniqueSnapshots } = await import(moduleUrl);

test("loading an older snapshot page preserves order and never duplicates refs", () => {
  assert.deepEqual(
    appendUniqueSnapshots(
      [
        { ref: "head", label: "latest" },
        { ref: "v2", label: "second" },
      ],
      [
        { ref: "v2", label: "duplicate boundary" },
        { ref: "v1", label: "oldest" },
      ],
    ),
    [
      { ref: "head", label: "latest" },
      { ref: "v2", label: "second" },
      { ref: "v1", label: "oldest" },
    ],
  );
});
