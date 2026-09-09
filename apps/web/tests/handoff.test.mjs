/**
 * The face a visitor arrives with: `?locale=zh&theme=dark`, appended by a launcher
 * (such as a menu-bar tray) when it opens the console.
 *
 * Two things are being held here. A valid value is applied AND persisted into the console's
 * own keys, so a later visit without the parameters keeps it. Anything else is ignored
 * outright — a URL is not a place a preference may be invented from, and a stored choice is
 * never overwritten by a string nobody wrote.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/handoff.ts", import.meta.url);
const transformed = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  adoptPreferencesFrom,
  hasHandoffPreferences,
  HANDOFF_LOCALE_KEY,
  HANDOFF_THEME_KEY,
} = await import(moduleUrl);

function storageStub(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

test("a stated locale and theme are applied and persisted into the console's own keys", () => {
  const storage = storageStub();
  assert.deepEqual(adoptPreferencesFrom("?locale=zh&theme=dark", storage), {
    locale: "zh",
    theme: "dark",
  });
  assert.deepEqual(storage.data, {
    [HANDOFF_LOCALE_KEY]: "zh",
    [HANDOFF_THEME_KEY]: "dark",
  });
});

test("a handed-over preference replaces the stored one — the tray is the newer statement", () => {
  const storage = storageStub({ [HANDOFF_LOCALE_KEY]: "en", [HANDOFF_THEME_KEY]: "light" });
  assert.deepEqual(adoptPreferencesFrom("?locale=zh&theme=dark", storage), {
    locale: "zh",
    theme: "dark",
  });
  assert.equal(storage.getItem(HANDOFF_LOCALE_KEY), "zh");
  assert.equal(storage.getItem(HANDOFF_THEME_KEY), "dark");
});

test("an unrecognised value is ignored, and leaves what was stored exactly as it was", () => {
  const storage = storageStub({ [HANDOFF_LOCALE_KEY]: "en" });
  assert.deepEqual(adoptPreferencesFrom("?locale=fr&theme=neon", storage), {});
  assert.deepEqual(storage.data, { [HANDOFF_LOCALE_KEY]: "en" });
  // zh-CN is the TRAY's spelling; the console's vocabulary is `zh`, and the tray converts.
  assert.deepEqual(adoptPreferencesFrom("?locale=zh-CN", storage), {});
  assert.deepEqual(storage.data, { [HANDOFF_LOCALE_KEY]: "en" });
});

test("one valid parameter travels even when the other is missing or malformed", () => {
  const storage = storageStub();
  assert.deepEqual(adoptPreferencesFrom("?locale=en", storage), { locale: "en" });
  assert.deepEqual(storage.data, { [HANDOFF_LOCALE_KEY]: "en" });
  assert.deepEqual(adoptPreferencesFrom("?theme=light&locale=", storage), { theme: "light" });
  assert.equal(storage.getItem(HANDOFF_LOCALE_KEY), "en");
  assert.equal(storage.getItem(HANDOFF_THEME_KEY), "light");
});

test("no parameters, no writes — an ordinary visit resolves as it always did", () => {
  const storage = storageStub();
  assert.deepEqual(adoptPreferencesFrom("", storage), {});
  assert.deepEqual(adoptPreferencesFrom("?user=alice", storage), {});
  assert.deepEqual(storage.data, {});
  assert.equal(hasHandoffPreferences("?user=alice"), false);
  // Present but invalid still counts as present: it must not stay in the address either.
  assert.equal(hasHandoffPreferences("?theme=neon"), true);
  assert.equal(hasHandoffPreferences("?locale=zh&theme=dark"), true);
});

test("a browser that refuses to store still gets the preference for this visit", () => {
  const refusing = {
    getItem: () => null,
    setItem: () => {
      throw new Error("site data blocked");
    },
  };
  assert.deepEqual(adoptPreferencesFrom("?locale=zh&theme=dark", refusing), {
    locale: "zh",
    theme: "dark",
  });
  assert.deepEqual(adoptPreferencesFrom("?locale=zh", null), { locale: "zh" });
});

test("the handoff writes the very keys the store reads its preferences from", async () => {
  // The keys are literals in two files; this is what keeps them from drifting apart.
  const store = await readFile(new URL("../src/lib/store.ts", import.meta.url), "utf8");
  const i18n = await readFile(new URL("../src/lib/i18n.ts", import.meta.url), "utf8");
  assert.ok(
    store.includes(`localStorage.setItem("${HANDOFF_THEME_KEY}"`),
    "store.ts no longer persists the theme under the key the handoff writes",
  );
  assert.ok(
    i18n.includes(`export const LOCALE_STORAGE_KEY = "${HANDOFF_LOCALE_KEY}"`),
    "i18n.ts no longer reads the locale from the key the handoff writes",
  );
});
