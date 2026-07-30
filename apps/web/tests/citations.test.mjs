import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/citations.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { buildCitationNumbers, citationKey, presentCitationSource } = await import(moduleUrl);

/**
 * The wording is injected (the module stays import-free so it can be transpiled on its own),
 * so the tests supply the two locales they care about. The tables mirror src/i18n — the merged
 * catalogue's own integrity is covered by tests/i18n.test.mjs.
 */
function i18nFor(locale) {
  const table = {
    zh: {
      "enum.citationKind.email": "邮件",
      "common.citation.capturedTitle": "{capturedAt} 的{kind}",
      "common.citation.untitled": "未命名{kind}",
      "common.citation.missingTitle": "原始标题缺失",
      "common.citation.sourceNoun": "来源",
    },
    en: {
      "enum.citationKind.email": "Email",
      "common.citation.capturedTitle": "{kind} captured {capturedAt}",
      "common.citation.untitled": "Untitled {kind}",
      "common.citation.missingTitle": "Original title missing",
      "common.citation.sourceNoun": "source",
    },
  }[locale];
  return {
    intlTag: locale === "zh" ? "zh-CN" : "en-CA",
    tOr: (key, fallback, params) => {
      const template = table[key];
      if (template === undefined) return fallback;
      return params
        ? template.replace(/\{(\w+)\}/g, (whole, name) =>
            name in params ? String(params[name]) : whole,
          )
        : template;
    },
  };
}

test("citationKey identifies a document-level source span", () => {
  assert.equal(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    "source-a:3-4",
  );
  assert.equal(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
  );
  assert.notEqual(
    citationKey({ sourceId: "source-a", blockStart: 3, blockEnd: 4 }),
    citationKey({ sourceId: "source-a", blockStart: 4, blockEnd: 4 }),
  );
});

test("buildCitationNumbers keeps one document-wide ledger across claims", () => {
  const citations = [
    { sourceId: "source-a", blockStart: 0, blockEnd: 0 },
    { sourceId: "source-a", blockStart: 1, blockEnd: 1 },
    { sourceId: "source-b", blockStart: 3, blockEnd: 4 },
  ];
  const numbers = buildCitationNumbers(citations);

  assert.equal(numbers.get(citationKey(citations[0])), 1);
  assert.equal(numbers.get(citationKey(citations[1])), 2);
  assert.equal(numbers.get(citationKey(citations[2])), 3);
});

test("presentCitationSource prefers a real title and preserves readable metadata", () => {
  const source = {
    sourceId: "f3d9d7ae05b6bf12accc4f4e095ceec1",
    // A source's own title is DATA: it is never translated, whatever the interface language.
    title: "报价边界确认",
    kind: "email",
    capturedAt: "2026-07-29T10:50:55+00:00",
  };

  const zh = presentCitationSource(source, i18nFor("zh"));
  assert.equal(zh.title, "报价边界确认");
  assert.match(zh.description, /^邮件 · /);
  assert.match(zh.description, /2026/);

  const en = presentCitationSource(source, i18nFor("en"));
  assert.equal(en.title, "报价边界确认");
  assert.match(en.description, /^Email · /);
  assert.match(en.description, /2026/);
});

test("presentCitationSource synthesizes a readable fallback instead of exposing an id", () => {
  const sourceId = "f3d9d7ae05b6bf12accc4f4e095ceec1";
  const source = {
    sourceId,
    title: sourceId,
    kind: "email",
    capturedAt: "2026-07-29T10:50:55+00:00",
  };

  const zh = presentCitationSource(source, i18nFor("zh"));
  assert.doesNotMatch(zh.title, new RegExp(sourceId));
  assert.match(zh.title, /2026.*邮件/);
  assert.equal(zh.description, "原始标题缺失");

  const en = presentCitationSource(source, i18nFor("en"));
  assert.doesNotMatch(en.title, new RegExp(sourceId));
  assert.match(en.title, /^Email captured .*2026/);
  assert.equal(en.description, "Original title missing");
});

test("an unknown source kind and a missing timestamp both degrade instead of blanking", () => {
  const i18n = i18nFor("en");

  // A kind the dictionary does not carry surfaces as the raw kind, never as an empty chip.
  const unknownKind = presentCitationSource(
    { sourceId: "s-1", title: "s-1", kind: "voicemail", capturedAt: null },
    i18n,
  );
  assert.equal(unknownKind.title, "Untitled voicemail");

  // No kind and no timestamp: the generic noun carries the label.
  const bare = presentCitationSource({ sourceId: "s-2", title: "s-2" }, i18n);
  assert.equal(bare.title, "Untitled source");
  assert.equal(bare.description, "Original title missing");
});
