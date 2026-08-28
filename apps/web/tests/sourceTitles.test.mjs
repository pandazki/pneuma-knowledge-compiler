/**
 * The on-demand title cache: ask once per id, keep what a listing already knew, and collect
 * exactly the ids a recall result is about to print.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/sourceTitles.ts", import.meta.url);
const transformed = await transformWithEsbuild(
  await readFile(sourceUrl, "utf8"),
  sourceUrl.pathname,
  { loader: "ts", format: "esm", target: "es2022" },
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  emptyTitleCache,
  rememberTitles,
  claimTitleLookups,
  recordTitle,
  recallSourceIds,
} = await import(moduleUrl);

test("a listing's rows seed the cache and are never looked up again", () => {
  const cache = emptyTitleCache();
  assert.equal(rememberTitles(cache, [{ source_id: "s1", title: "Weekly note" }]), true);
  assert.equal(rememberTitles(cache, [{ source_id: "s1", title: "Weekly note" }]), false);
  assert.deepEqual(claimTitleLookups(cache, ["s1"]), []);
});

test("only unknown ids are claimed, and only once each", () => {
  const cache = emptyTitleCache();
  rememberTitles(cache, [{ source_id: "s1", title: "Known" }]);
  assert.deepEqual(claimTitleLookups(cache, ["s1", "s2", "s3", "s2"]), ["s2", "s3"]);
  // A second pass (a re-render, or the effect running twice) asks for nothing.
  assert.deepEqual(claimTitleLookups(cache, ["s1", "s2", "s3"]), []);
  recordTitle(cache, "s2", "Fetched");
  assert.equal(cache.titles.s2, "Fetched");
  // A lookup that failed stays asked: the row keeps showing the id rather than retrying.
  assert.equal("s3" in cache.titles, false);
  assert.deepEqual(claimTitleLookups(cache, ["s3"]), []);
});

test("recallSourceIds gathers every face a result prints, deduplicated", () => {
  const ids = recallSourceIds(
    { hits: [{ source_id: "hit" }] },
    {
      used_claims: [{ citations: [{ source_id: "claim" }, { source_id: "hit" }] }],
      used_episode_summaries: [{ source_id: "episode" }],
      used_windows: [{ source_id: "window" }],
      used_component_evidence: [
        { claims: [{ citations: [{ source_id: "component" }] }], windows: [{ source_id: "cwin" }] },
      ],
      citation_handles: { s0: "handle" },
    },
  );
  assert.deepEqual(ids.sort(), [
    "claim",
    "component",
    "cwin",
    "episode",
    "handle",
    "hit",
    "window",
  ]);
});

test("recallSourceIds tolerates an empty lane, a rag-only result and a missing face", () => {
  assert.deepEqual(recallSourceIds(null, null), []);
  assert.deepEqual(recallSourceIds({ hits: [{ source_id: "only" }] }, null), ["only"]);
  assert.deepEqual(recallSourceIds(null, { used_claims: [{}] }), []);
});
