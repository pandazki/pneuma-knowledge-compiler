import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const url = new URL("../src/lib/sourceCollection.ts", import.meta.url);
const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname,
  { loader: "ts", format: "esm", target: "es2022" });
const { parseSourceCollection } = await import(
  `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`,
);

const observation = {
  transport: "remote", device_id: "device-test", device_label: "Development laptop",
  project_id: "project-test", project_name: "Atlas", project_path: "/work/atlas",
  remotes: ["git.example.test/team/atlas"],
  first_observed_at: "2026-09-07T10:00:00Z", last_observed_at: "2026-09-07T11:00:00Z",
};
const payload = (observations = [observation]) => ({
  user_id: "tenant-a", source_id: "source-test", relation: "session_observation", observations,
});

test("observations from another tenant or source are never accepted", () => {
  assert.equal(parseSourceCollection(payload(), "tenant-b", "source-test"), null);
  assert.equal(parseSourceCollection(payload(), "tenant-a", "source-other"), null);
});

test("all observed devices remain distinct, including a device with no friendly name", () => {
  const data = payload([observation, { ...observation, transport: "local", device_id: "local", device_label: null }]);
  assert.deepEqual(parseSourceCollection(data, "tenant-a", "source-test"), data);
});

test("missing observations or an unknown transport never become a local origin", () => {
  assert.deepEqual(parseSourceCollection(payload([]), "tenant-a", "source-test").observations, []);
  for (const transport of [undefined, null, "unknown", "r2"]) {
    assert.equal(parseSourceCollection(payload([{ ...observation, transport }]), "tenant-a", "source-test"), null);
  }
});

test("an unsupported edition or different relation supplies no collection observations", () => {
  for (const value of [null, [], "<!doctype html>", {}, { ...payload(), relation: "import_origin" },
    payload([{ ...observation, remotes: [null] }])]) {
    assert.equal(parseSourceCollection(value, "tenant-a", "source-test"), null);
  }
});

test("unrelated metadata cannot become source evidence through the projection", () => {
  const result = parseSourceCollection({ ...payload(), meta: { body: "not evidence" } }, "tenant-a", "source-test");
  assert.equal("meta" in result, false);
  assert.deepEqual(result.observations[0].remotes, observation.remotes);
});
