import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const url = new URL("../src/lib/collection.ts", import.meta.url);
const source = await readFile(url, "utf8");
const transformed = await transformWithEsbuild(source, url.pathname, { loader: "ts", format: "esm", target: "es2022" });
const { collectionReadOnly, collectionScope, scopeDraft, invitationStatus } = await import(
  `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`,
);

test("a frozen base without a canonical commit still disables collection writes", () => {
  assert.equal(collectionReadOnly({ currentSnapshot: null, currentKbSnapshot: {
    snapshot_id: "frozen-empty-library", status: "ready", canonical_ref: null,
  } }), true);
  assert.equal(collectionReadOnly({ currentSnapshot: "commit-test", currentKbSnapshot: null }), true);
  assert.equal(collectionReadOnly({ currentSnapshot: null, currentKbSnapshot: null }), false);
});

test("an empty or sentinel-only restricted scope never becomes all projects", () => {
  const draft = { ...scopeDraft(), allProjects: false, projects: " \n " };
  assert.equal(collectionScope(draft), null);
  assert.equal(collectionScope({ ...draft, projects: "all" }), null);
  assert.deepEqual(collectionScope({ ...draft, projects: "/work/atlas\n/work/atlas\n/work/notes" }).projects,
    ["/work/atlas", "/work/notes"]);
});

test("a scope cannot silently enable a deselected harness", () => {
  assert.equal(collectionScope({ ...scopeDraft(), harnesses: [] }), null);
  assert.deepEqual(collectionScope({ ...scopeDraft(), harnesses: ["claude-code"] }).harnesses,
    ["claude-code"]);
});

test("an explicit starting day is UTC and invalid calendar dates are refused", () => {
  assert.equal(collectionScope({ ...scopeDraft(), since: "2026-02-31" }), null);
  assert.equal(collectionScope({ ...scopeDraft(), since: "2026-09-07" }).since,
    "2026-09-07T00:00:00.000Z");
  assert.equal(collectionScope(scopeDraft()).since, null);
});

test("editing an existing scope preserves its projects and selected session formats", () => {
  const original = { projects: ["/srv/work"], harnesses: ["codex"], since: "2026-09-07T00:00:00.000Z" };
  assert.deepEqual(collectionScope(scopeDraft(original)), original);
});

test("a home with no watches remains unconfigured rather than enabling every project", () => {
  const empty = scopeDraft({ projects: [], harnesses: [], since: null });
  assert.equal(empty.allProjects, false);
  assert.deepEqual(empty.harnesses, []);
  assert.equal(collectionScope(empty), null);
});

test("an expired or invalid expiry cannot leave an invitation copyable", () => {
  const now = Date.parse("2026-09-07T12:00:00Z");
  assert.equal(invitationStatus({ status: "pending", expires_at: "2026-09-07T12:00:00Z" }, now), "expired");
  assert.equal(invitationStatus({ status: "pending", expires_at: "invalid" }, now), "expired");
  assert.equal(invitationStatus({ status: "pending", expires_at: "2026-09-07T12:01:00Z" }, now), "pending");
});

test("server redemption and revocation win over the browser expiry clock", () => {
  const expired = "2026-09-07T11:00:00Z";
  const now = Date.parse("2026-09-07T12:00:00Z");
  assert.equal(invitationStatus({ status: "redeemed", expires_at: expired }, now), "redeemed");
  assert.equal(invitationStatus({ status: "revoked", expires_at: expired }, now), "revoked");
});
