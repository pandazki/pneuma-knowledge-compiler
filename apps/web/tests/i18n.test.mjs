/**
 * The i18n safety net.
 *
 * `defineMessages` already makes zh/en key parity a compile-time fact, so these tests cover
 * what the type system cannot see: a key declared in two bundles (one of them silently dead),
 * a namespace file that exists but was never wired into the catalogue, an English value that
 * is still Chinese, and the locale-resolution / enum-fallback ladders.
 *
 * Loading strategy: every file under src/i18n imports nothing but `./define`, whose
 * `defineMessages` is the identity function — so each bundle is made self-contained by
 * inlining that helper. lib/i18n.ts then gets the assembled catalogue injected in place of
 * its `@/i18n` imports, which means the real `translate` / `resolveLocale` code runs against
 * the real dictionary.
 */
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const I18N_DIR = new URL("../src/i18n/", import.meta.url);

async function importTs(sourceText, pathname) {
  const transformed = await transformWithEsbuild(sourceText, pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  const url = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
  return import(url);
}

const namespaces = (await readdir(I18N_DIR))
  .filter((name) => name.endsWith(".ts") && name !== "define.ts" && name !== "index.ts")
  .map((name) => name.slice(0, -3))
  .sort();

/** name → { zh, en } */
const bundles = new Map();
for (const name of namespaces) {
  const url = new URL(`${name}.ts`, I18N_DIR);
  const text = (await readFile(url, "utf8")).replace(
    /^import \{[^}]*\} from "\.\/define";$/m,
    "const defineMessages = (bundle) => bundle;",
  );
  const mod = await importTs(text, url.pathname);
  const bundle = mod[name];
  assert.ok(bundle, `${name}.ts must export a bundle named \`${name}\``);
  bundles.set(name, bundle);
}

const MESSAGES = { zh: {}, en: {} };
for (const bundle of bundles.values()) {
  Object.assign(MESSAGES.zh, bundle.zh);
  Object.assign(MESSAGES.en, bundle.en);
}

const indexSource = await readFile(new URL("index.ts", I18N_DIR), "utf8");

const libUrl = new URL("../src/lib/i18n.ts", import.meta.url);
const libSource = (await readFile(libUrl, "utf8"))
  .replace(
    /^import \{ MESSAGES, type MessageKey \} from "@\/i18n";$/m,
    `const MESSAGES = ${JSON.stringify(MESSAGES)};\ntype MessageKey = string;`,
  )
  .replace(
    /^import \{ LOCALES, type Locale \} from "@\/i18n\/define";$/m,
    'const LOCALES = ["zh", "en"];\ntype Locale = "zh" | "en";',
  );
const { resolveLocale, translate, translateOr, intlTag, isLocale, LOCALE_STORAGE_KEY } =
  await importTs(libSource, libUrl.pathname);

/* ------------------------------------------------------------------ catalogue */

test("the dictionary has bundles, and every namespace file is wired into the catalogue", () => {
  assert.ok(namespaces.length >= 5, `expected several namespaces, saw ${namespaces.length}`);
  for (const name of namespaces) {
    assert.match(
      indexSource,
      new RegExp(`import \\{ ${name} \\} from "\\./${name}";`),
      `${name}.ts is not imported by src/i18n/index.ts`,
    );
    assert.match(
      indexSource,
      new RegExp(`^  ${name},$`, "m"),
      `${name} is missing from the BUNDLES list in src/i18n/index.ts`,
    );
    for (const locale of ["zh", "en"]) {
      assert.match(
        indexSource,
        new RegExp(`^    \\.\\.\\.${name}\\.${locale},$`, "m"),
        `${name} is missing from MESSAGES.${locale} in src/i18n/index.ts`,
      );
    }
  }
});

test("zh and en declare exactly the same keys", () => {
  for (const [name, bundle] of bundles) {
    assert.deepEqual(
      Object.keys(bundle.zh).sort(),
      Object.keys(bundle.en).sort(),
      `${name}.ts: zh and en key sets diverged`,
    );
  }
  assert.deepEqual(Object.keys(MESSAGES.zh).sort(), Object.keys(MESSAGES.en).sort());
});

test("no key is declared by two bundles", () => {
  const owner = new Map();
  const collisions = [];
  for (const [name, bundle] of bundles) {
    for (const key of Object.keys(bundle.zh)) {
      if (owner.has(key)) collisions.push(`${key} (${owner.get(key)} + ${name})`);
      else owner.set(key, name);
    }
  }
  assert.deepEqual(collisions, []);
  // A merged catalogue smaller than the sum of its parts means a silent overwrite.
  const declared = [...bundles.values()].reduce((n, b) => n + Object.keys(b.zh).length, 0);
  assert.equal(Object.keys(MESSAGES.zh).length, declared);
});

test("every message is non-empty and every en message is actually English", () => {
  const cjk = /[\u4e00-\u9fff]/;
  const blank = [];
  const notTranslated = [];
  for (const [key, value] of Object.entries(MESSAGES.en)) {
    if (value.trim() === "") blank.push(key);
    if (cjk.test(value)) notTranslated.push(key);
  }
  for (const [key, value] of Object.entries(MESSAGES.zh)) {
    if (value.trim() === "") blank.push(key);
  }
  assert.deepEqual(blank, []);
  assert.deepEqual(notTranslated, [], "these en values still contain Chinese");
});

test("interpolation placeholders match between the two languages", () => {
  // `{name|one|many}` plural tokens count as a use of `name`: English needs them and Chinese
  // does not, so the two columns legitimately differ in form while agreeing on the params.
  const names = (template) => {
    const plural = [...template.matchAll(/\{(\w+)\|[^{}|]*\|[^{}|]*\}/g)].map((m) => m[1]);
    const bare = [...template.replace(/\{\w+\|[^{}|]*\|[^{}|]*\}/g, "").matchAll(/\{(\w+)\}/g)]
      .map((m) => m[1]);
    return [...new Set([...plural, ...bare])].sort();
  };
  const mismatched = [];
  for (const key of Object.keys(MESSAGES.zh)) {
    const zh = names(MESSAGES.zh[key]);
    const en = names(MESSAGES.en[key]);
    if (zh.join(",") !== en.join(",")) mismatched.push(`${key}: zh=${zh} en=${en}`);
  }
  assert.deepEqual(mismatched, []);
});

test("plural tokens pick a form off the numeric param, and only in en", () => {
  assert.equal(translate("en", "sources.blockCount", { count: 1 }), "1 block");
  assert.equal(translate("en", "sources.blockCount", { count: 7 }), "7 blocks");
  assert.equal(translate("en", "sources.blockCount", { count: 0 }), "0 blocks");
  assert.equal(
    translate("en", "sources.meeting.participantCount", { count: 1 }),
    "1 person",
    "an irregular plural is spelled out in both slots",
  );
  assert.equal(translate("en", "sources.meeting.participantCount", { count: 3 }), "3 people");
  // Chinese has no number agreement, so its column never carries the token. The counted noun
  // is 「原文块」 — `block` stays a technical term in zh only where it ADDRESSES a unit (¶/blk).
  assert.equal(translate("zh", "sources.blockCount", { count: 1 }), "1 个原文块");
  assert.equal(translate("zh", "sources.meeting.participantCount", { count: 1 }), "1 人");
});

test("a plural token with no usable count is left visible, not silently resolved", () => {
  // No params at all, and a non-numeric param: both must leave the token alone rather than
  // guess a form. A visible `{count||s}` in the UI is a bug report; a wrong word is not.
  assert.equal(translate("en", "sources.blockCount"), "{count} block{count||s}");
  assert.equal(
    translate("en", "sources.blockCount", { count: "many" }),
    "many block{count||s}",
  );
});

/* ------------------------------------------------------ terminology consistency */

/**
 * One term per concept, in both columns. The two tables below are the wordings the
 * terminology pass RETIRED: each entry is a regex over message VALUES (never keys — a key is
 * an identifier, not copy) plus the term that replaced it, so a regression fails with the
 * decision rather than with a bare pattern.
 */
const RETIRED_ZH = [
  [/原料|语料|材料/, "the raw input is 「来源」 everywhere"],
  [/知识版本|版本快照|补丁/, "a compile patch is 「版次」; a git object is 「快照」"],
  [/闸门|门控|引用门(?!禁)/, "the write-time gate is 「引用门禁」"],
  [/技能|领域契约|模式重组|模式演进|演进/, "the process is 「演化」, the object stays `skill`"],
  [/[“”]/, "Chinese copy quotes with 「」"],
  [/顶栏/, "the user picker is 「在右上角」"],
];

const RETIRED_EN = [
  [/\bpatch(es|ed)?\b/i, 'a compile patch is an "edition"'],
  [/\bcorpus\b|\bmaterial(s)?\b/i, 'the raw input is a "source"'],
  [/\bcatalog\b|\bneighbor(s|hood)?\b|\bafterward\b/i, "British spelling throughout"],
  [/\bschema (evolution|reorganisation)\b|\bdomain contract\b/i, 'the process is "evolve", the object is "skill"'],
  [/\bin the top bar\b/i, 'the user picker is "in the top right"'],
];

test("one term per concept: the retired wordings are gone from both columns", () => {
  const offences = [];
  for (const [locale, table] of [
    ["zh", RETIRED_ZH],
    ["en", RETIRED_EN],
  ]) {
    for (const [key, value] of Object.entries(MESSAGES[locale])) {
      for (const [pattern, decision] of table) {
        if (pattern.test(value)) offences.push(`${locale} ${key}: ${decision} — "${value}"`);
      }
    }
  }
  assert.deepEqual(offences, []);
});

test("the decided terms are pinned, so a rename cannot drift one surface at a time", () => {
  const pins = {
    // W1 — every contents entry carries the English suffix.
    "nav.view.library": ["正本 Canonical", "Canonical"],
    "nav.view.engine_console": ["引擎控制台 Engine Console", "Engine Console"],
    // W3 — occurred_on is the source's own date, on both surfaces that print it.
    "common.sourceSpan.metadata.occurredOn": ["来源日期", "Source date"],
    "sources.timeline.occurred": ["来源日期", "Source date"],
    // W2 — the counted noun, against `block` the addressing term.
    "sources.blockCount": ["{count} 个原文块", "{count} block{count||s}"],
    // W5 — a compile patch vs a git object.
    "history.tech.patch": ["版次", "Edition"],
    "history.tech.baseCommit": ["基于快照", "Base snapshot"],
    // W6 — the write-time gate.
    "common.gate.aria": ["引用门禁计数", "Citation gate counts"],
    // W8 — not to be confused with a briefing.
    "history.brief.label": ["编译纪要 · 派生叙述", "Compile brief · derived narration"],
    // W9 — one verb, and both directions of it.
    "history.claim.superseded": ["取代", "Superseded"],
    "library.supersession.supersededBy": ["被 c:{anchor} 取代", "superseded by c:{anchor}"],
    "library.supersession.supersedes": ["取代 c:{anchor}", "supersedes c:{anchor}"],
    // W11 — a preflight rejection is not an import failure.
    "ingest.official.preflightFailed": ["预检失败", "Preflight failed"],
  };
  for (const [key, [zh, en]] of Object.entries(pins)) {
    assert.equal(MESSAGES.zh[key], zh, `zh ${key}`);
    assert.equal(MESSAGES.en[key], en, `en ${key}`);
  }
});

/* -------------------------------------------------------------- locale ladder */

test("an explicit stored choice beats the browser language", () => {
  assert.equal(resolveLocale("zh", "en-US"), "zh");
  assert.equal(resolveLocale("en", "zh-CN"), "en");
});

test("without a stored choice, zh* falls to Chinese and everything else to English", () => {
  assert.equal(resolveLocale(null, "zh"), "zh");
  assert.equal(resolveLocale(null, "zh-CN"), "zh");
  assert.equal(resolveLocale(null, "ZH-Hant-TW"), "zh");
  assert.equal(resolveLocale(undefined, "zh_TW"), "zh");
  assert.equal(resolveLocale(null, "en-GB"), "en");
  assert.equal(resolveLocale(null, "ja-JP"), "en");
  assert.equal(resolveLocale(null, "zhuang"), "en", "a zh PREFIX is not a zh tag");
});

test("English is the default when nothing is known, and junk is not a locale", () => {
  assert.equal(resolveLocale(null, null), "en");
  assert.equal(resolveLocale(null, undefined), "en");
  assert.equal(resolveLocale("", ""), "en");
  assert.equal(resolveLocale("de", null), "en", "an unsupported stored value is ignored");
  assert.equal(isLocale("zh"), true);
  assert.equal(isLocale("de"), false);
  assert.equal(LOCALE_STORAGE_KEY, "pneuma-knowledge-locale");
});

test("Intl tags stay pinned per locale", () => {
  assert.equal(intlTag("zh"), "zh-CN");
  assert.equal(intlTag("en"), "en-CA");
});

/* -------------------------------------------------------------------- lookup */

test("translate resolves per locale and interpolates named placeholders", () => {
  assert.equal(translate("zh", "common.retry"), "重试");
  assert.equal(translate("en", "common.retry"), "Retry");
  assert.equal(
    translate("en", "common.pagination.page", { current: 2, total: 7 }),
    "Page 2 of 7",
  );
  assert.equal(
    translate("zh", "common.pagination.page", { current: 2, total: 7 }),
    "第 2 / 7 页",
  );
  // an unsupplied placeholder is left visible rather than rendered as "undefined"
  assert.equal(translate("en", "common.footnote.aria"), "Footnote {index}");
});

test("an undeclared key degrades to itself rather than to a blank", () => {
  assert.equal(translate("zh", "no.such.key"), "no.such.key");
});

/* ------------------------------------------------- server-vocabulary fallback */

test("a known enum key renders from the dictionary, in the active locale", () => {
  assert.equal(
    translateOr("zh", "enum.contextFocus.owner.label", "Focus on the owner"),
    "只看本人",
  );
  assert.equal(
    translateOr("en", "enum.intakeArchetype.digest.label", "SERVER TEXT"),
    "Study and file",
    "a key the dictionary knows must not fall through to the server label",
  );
});

test("an enum value the client does not know falls back to the server's label", () => {
  // The vocabularies are closed but extensible server-side; a new value must degrade to the
  // served English label, never to a blank or to the raw key.
  assert.equal(
    translateOr("zh", "enum.contextFocus.mentor.label", "Focus on the mentor"),
    "Focus on the mentor",
  );
  assert.equal(
    translateOr("zh", "enum.intakeArchetype.transcribe.summary", "kept verbatim"),
    "kept verbatim",
  );
  assert.equal(translateOr("en", "event.some_new_event", "some_new_event"), "some_new_event");
});

test("the source-kind families both cover the projection's kinds", () => {
  const kinds = ["meeting", "document_library", "im", "email", "conversation", "document", "structured"];
  for (const kind of kinds) {
    for (const family of ["enum.citationKind", "enum.sourceKind"]) {
      for (const locale of ["zh", "en"]) {
        assert.notEqual(
          translateOr(locale, `${family}.${kind}`, "__MISSING__"),
          "__MISSING__",
          `${family}.${kind} missing for ${locale}`,
        );
      }
    }
  }
});

/* ------------------------------------------------------ count grouping in messages */

test("count-like placeholders are grouped, and index-like ones are left alone", () => {
  // One policy for every number a message carries: what a page prints inside a sentence and
  // what it prints beside it (`fmtCount`) go through the same function.
  assert.equal(translate("en", "graph.anomaly.deadEnd", { count: 5832, share: "39.9%" }).includes("5,832"), true);
  assert.equal(translate("zh", "graph.anomaly.deadEnd", { count: 5832, share: "39.9%" }).includes("5,832"), true);
  // A block index, a year, a version and an id are not cardinal counts: "¶1,238" is wrong.
  assert.equal(translate("en", "sources.exactSpan.title", { block: 1238 }), "b1238 · exact source span");
  assert.equal(translate("en", "common.pagination.page", { current: 2, total: 7 }), "Page 2 of 7");
});

test("the grouping policy is a name denylist, applied to integers only", () => {
  // Pinned through a declared key so the test exercises the real path: `{count}` is grouped,
  // `{index}` is not, a float is untouched, and a non-numeric param is printed as given.
  assert.equal(translate("en", "common.footnote.aria", { index: 1238 }), "Footnote 1238");
  assert.equal(
    translate("en", "sources.block.fetchAria", { index: 2026 }),
    "Fetch the exact source span for block 2026",
  );
  assert.equal(translate("en", "sources.blockCount", { count: 4000 }), "4,000 blocks");
  // The denylist matches a NAME, not a spelling tail: `claims` is a count even though it
  // happens to end in "ms", and `elapsed_ms` / `elapsedMs` are not.
  assert.equal(
    translate("zh", "graph.health.summary", { files: 156, subjects: 153, claims: 2941, edges: 306 }),
    "156 个文件归并为 153 个主体 · 2,941 条断言（claim）· 306 条内链。",
  );
  // A non-numeric count still leaves its plural token visible (see above): grouping does
  // not repair a param that was never a number.
  assert.equal(translate("en", "sources.blockCount", { count: "many" }), "many block{count||s}");
});
