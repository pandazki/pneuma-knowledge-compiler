import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const file = new URL("../src/lib/profilePresentation.ts", import.meta.url);
const { code } = await transformWithEsbuild(await readFile(file, "utf8"), file.pathname, {
  loader: "ts", format: "esm", target: "es2022",
});
const { profilePresentation } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("unstated and saved profiles are never described as synthetic", () => {
  assert.deepEqual(profilePresentation("unstated"), {
    description: "profile.header.unstatedDescription", synthetic: false,
  });
  assert.deepEqual(profilePresentation("user"), {
    description: "profile.header.savedDescription", synthetic: false,
  });
});

test("only explicit mock provenance carries the synthetic stamp", () => {
  assert.equal(profilePresentation("mock").synthetic, true);
  assert.deepEqual(profilePresentation("unrecognized"), {
    description: "profile.header.description", synthetic: false,
  });
});
