import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/history.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { normalizeHistoryItem, selectedHistoryItem } = await import(moduleUrl);

test("history envelopes normalize into the three timeline detail shapes", () => {
  const patch = normalizeHistoryItem({
    kind: "patch",
    ref: "ref-patch",
    ts: "2026-07-28T10:00:00Z",
    payload: {
      patch_id: "stale",
      changed_paths: ["work/products/status.md"],
      sources_consumed: ["source-01"],
      claims: [
        {
          type: "claim_revised",
          path: "work/products/status.md",
          anchor: { document_id: null, anchor: "a001" },
          before: "旧状态",
          after: "新状态",
        },
      ],
    },
  });
  const job = normalizeHistoryItem({
    kind: "job",
    ref: "job-01",
    ts: "2026-07-28T09:00:00Z",
    payload: { status: "compiled", patch_id: "ref-patch" },
  });
  const snapshot = normalizeHistoryItem({
    kind: "snapshot",
    ref: "source-01",
    ts: "2026-07-28T08:00:00Z",
    payload: { source_type: "meeting", checksum: "abc" },
  });

  assert.equal(patch.patch.patch_id, "ref-patch");
  assert.equal(patch.patch.ts, "2026-07-28T10:00:00Z");
  assert.deepEqual(patch.patch.claims[0], {
    type: "claim_revised",
    path: "work/products/status.md",
    anchor: { document_id: null, anchor: "a001" },
    before: "旧状态",
    after: "新状态",
  });
  assert.equal(job.job.job_id, "job-01");
  assert.equal(job.job.ts, "2026-07-28T09:00:00Z");
  assert.equal(snapshot.snapshot.source_id, "source-01");
  assert.equal(snapshot.snapshot.captured_at, "2026-07-28T08:00:00Z");
});

test("selection resolves only inside the bounded current page", () => {
  const rows = [
    normalizeHistoryItem({
      kind: "job",
      ref: "job-01",
      ts: "2026-07-28T09:00:00Z",
      payload: { status: "compiled", patch_id: null },
    }),
  ];

  assert.equal(
    selectedHistoryItem(rows, { kind: "job", id: "job-01" })?.ref,
    "job-01",
  );
  assert.equal(
    selectedHistoryItem(rows, { kind: "patch", id: "off-page" }),
    null,
  );
  assert.equal(selectedHistoryItem(rows, { kind: "source", id: "source-01" }), null);
});
