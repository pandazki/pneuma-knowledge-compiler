/**
 * The suggestion-density table: three postures, and one honest fourth state.
 *
 * The round trip is the whole contract — a preset must resolve to numbers and those numbers
 * must resolve back to the same preset, or the pills would light up wrong the moment the
 * server echoed the policy back. And numbers matching no preset must come back as `null`
 * rather than being snapped to the nearest one: an older client's policy, or a hand-set
 * combination, is somebody's decision and the panel's job is to SAY it is custom, not to
 * quietly change it.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const { DENSITY_PRESETS, DEFAULT_DENSITY, densityValues, detectDensity } = await import(
  await tsModuleUrl(new URL("../src/lib/liveContextDensity.ts", import.meta.url))
);

test("every preset round-trips through its own numbers", () => {
  for (const preset of DENSITY_PRESETS) {
    assert.deepEqual(densityValues(preset.key), preset.values);
    assert.equal(detectDensity(densityValues(preset.key)), preset.key);
  }
});

test("the three postures are ordered loud to quiet on every axis at once", () => {
  const [eager, balanced, quiet] = DENSITY_PRESETS.map((p) => p.values);
  assert.ok(eager.min_confidence < balanced.min_confidence);
  assert.ok(balanced.min_confidence < quiet.min_confidence);
  assert.ok(eager.quiet_period < balanced.quiet_period);
  assert.ok(balanced.quiet_period < quiet.quiet_period);
  assert.ok(eager.max_pending_turns < balanced.max_pending_turns);
  assert.ok(balanced.max_pending_turns < quiet.max_pending_turns);
});

test("the default posture is the framework's own defaults", () => {
  assert.equal(DEFAULT_DENSITY, "balanced");
  assert.deepEqual(densityValues("balanced"), {
    min_confidence: 6,
    quiet_period: 6,
    max_pending_turns: 12,
  });
});

test("numbers matching no preset are custom, not corrected", () => {
  assert.equal(
    detectDensity({ min_confidence: 5, quiet_period: 6, max_pending_turns: 12 }),
    null,
  );
  // An older client's shape: the fields it never knew about arrive as undefined.
  assert.equal(
    detectDensity({ min_confidence: 6, quiet_period: 6, max_pending_turns: undefined }),
    null,
  );
});
