import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/promptStudio.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  assembledPrompt,
  defaultExpandedPromptGroups,
  diffPromptText,
  groupPromptSurfaces,
  isFragmentFamily,
  missingPlaceholders,
  presentPlaceholders,
  promptGroupOverrideCount,
  promptPreview,
  segmentInCurrentRendering,
  segmentOverride,
  surfaceOverrideCount,
  tokenizePromptText,
} = await import(moduleUrl);

const fixture = JSON.parse(
  await readFile(new URL("../src/engine/fixtures/prompts.json", import.meta.url), "utf8"),
);

test("the prompt fixture matches the frozen API shape and covers real lifecycle contexts", () => {
  assert.deepEqual(Object.keys(fixture), ["surfaces"]);
  assert.equal(fixture.surfaces.length, 41);
  assert.deepEqual(
    new Set(fixture.surfaces.map((surface) => surface.group)),
    new Set([
      "intake",
      "compile",
      "challenge",
      "evolve",
      "recall",
      "persona",
      "skill",
      "feedback",
      "eval",
    ]),
  );
  const surfaceIds = new Set(fixture.surfaces.map((surface) => surface.id));
  let shared = 0;
  let overridden = 0;
  for (const surface of fixture.surfaces) {
    assert.deepEqual(
      Object.keys(surface).sort(),
      [
        "assembled_effective",
        "assembled_framework",
        "group",
        "id",
        "kind",
        "note",
        "segments",
        "summary",
        "title",
      ],
    );
    assert.ok(["assembled", "fragments"].includes(surface.kind), surface.id);
    assert.deepEqual(Object.keys(surface.title).sort(), ["en", "zh"]);
    assert.deepEqual(Object.keys(surface.summary).sort(), ["en", "zh"]);
    // `note` is the "you are looking at a template" banner: bilingual when present, and
    // only ever on an assembly, since a fragment family has no assembled text to caveat.
    if (surface.note !== null) {
      assert.deepEqual(Object.keys(surface.note).sort(), ["en", "zh"], surface.id);
      assert.equal(surface.kind, "assembled", surface.id);
    }
    assert.equal(typeof surface.assembled_framework, "string");
    assert.equal(typeof surface.assembled_effective, "string");
    for (const segment of surface.segments) {
      assert.deepEqual(
        Object.keys(segment).sort(),
        [
          "context",
          "framework_text",
          "key",
          "label",
          "override_text",
          "placeholders",
          "shared_with",
        ],
      );
      assert.deepEqual(Object.keys(segment.label).sort(), ["en", "zh"]);
      assert.deepEqual(
        [...presentPlaceholders(segment.framework_text)].sort(),
        [...segment.placeholders].sort(),
      );
      for (const target of segment.shared_with) assert.ok(surfaceIds.has(target), target);
      shared += segment.shared_with.length;
      overridden += segment.override_text === null ? 0 : 1;
    }
  }
  assert.ok(shared > 0, "fixture includes clauses shared across surfaces");
  assert.ok(overridden > 0, "fixture includes a live override");

  const fast = fixture.surfaces.find((surface) => surface.id === "recall.fast");
  assert.ok(
    fast.assembled_framework.includes(fast.segments[0].framework_text),
    "a rendered block is present verbatim even though its sibling glue is not a fixed separator",
  );
  const compileSystem = fixture.surfaces.find((surface) => surface.id === "compile.system");
  const ownerVariant = compileSystem.segments.find(
    (segment) => segment.key === "compile.owner_section",
  );
  assert.equal(segmentInCurrentRendering(compileSystem, ownerVariant), false);
  assert.ok(!compileSystem.assembled_framework.includes(ownerVariant.framework_text));
  const separatorVariant = compileSystem.segments.find(
    (segment) => segment.key === "compile.owner_field.list_separator",
  );
  assert.ok(
    compileSystem.assembled_framework.includes(separatorVariant.framework_text),
    "tiny variant text can occur coincidentally as punctuation elsewhere",
  );
  assert.equal(segmentInCurrentRendering(compileSystem, separatorVariant), false);
});

test("a fragment family has no assembly to render and every clause says when it is used", () => {
  const preamble = fixture.surfaces.find(
    (surface) => surface.id === "intake.source_preamble",
  );
  assert.equal(preamble.kind, "fragments");
  assert.equal(isFragmentFamily(preamble), true);
  assert.equal(preamble.assembled_framework, "");
  assert.equal(preamble.assembled_effective, "");

  // The gibberish regression: "the owner" + "a conversation" were being glued into
  // "the ownera conversationThis is…". Neither the payload nor the view builds that.
  const byKey = Object.fromEntries(preamble.segments.map((s) => [s.key, s]));
  const glued =
    byKey["source.preamble.owner_default"].framework_text +
    byKey["source.preamble.stream_scene_default"].framework_text;
  for (const surface of fixture.surfaces) {
    for (const mode of ["framework", "effective"]) {
      assert.ok(!assembledPrompt(surface, {}, mode).includes(glued), surface.id);
    }
  }
  assert.equal(assembledPrompt(preamble, {}, "framework"), "");
  assert.equal(assembledPrompt(preamble, {}, "effective"), "");
  assert.equal(promptPreview(preamble, {}, "effective").text, "");

  // Every clause of every fragment family carries a bilingual applicability note, and no
  // clause is filtered out as "another rendering branch" — there is no rendering.
  const fragments = fixture.surfaces.filter(isFragmentFamily);
  assert.equal(fragments.length, 27);
  assert.equal(fixture.surfaces.filter((s) => !isFragmentFamily(s)).length, 14);
  for (const surface of fragments) {
    for (const segment of surface.segments) {
      assert.ok(segment.context, `${surface.id}:${segment.key}`);
      assert.ok(segment.context.en.length > 0 && segment.context.zh.length > 0);
      assert.equal(segmentInCurrentRendering(surface, segment), true);
    }
  }

  // Overrides still count and still render, per clause, with no assembly involved.
  const owner = byKey["source.preamble.owner_default"];
  const overlays = { [owner.key]: "the subject" };
  assert.equal(segmentOverride(owner, overlays), "the subject");
  assert.equal(surfaceOverrideCount(preamble, overlays), 1);
});

test("effective preview follows the engine draft map, including staged removal", () => {
  const surface = fixture.surfaces.find((candidate) => candidate.id === "recall.fast");
  const segment = surface.segments.find(
    (candidate) => candidate.key === "recall.close.answer_honestly",
  );
  const current = { [segment.key]: segment.override_text };
  assert.equal(segmentOverride(segment, current), segment.override_text);
  assert.equal(surfaceOverrideCount(surface, current), 1);
  const surfacesSharingOverride = fixture.surfaces.filter((candidate) =>
    candidate.segments.some((candidateSegment) => candidateSegment.key === segment.key),
  );
  assert.ok(surfacesSharingOverride.length > 1);
  assert.ok(
    surfacesSharingOverride.every((candidate) => surfaceOverrideCount(candidate, current) === 1),
    "each affected surface reports the shared override once",
  );
  assert.equal(Object.keys(current).length, 1, "the global count deduplicates the shared key");
  assert.match(
    assembledPrompt(surface, {}, "effective"),
    /nearest recorded fact/,
    "without a local draft the server's effective assembly is displayed verbatim",
  );
  assert.doesNotMatch(
    assembledPrompt(surface, { [segment.key]: null }, "effective"),
    /nearest recorded fact/,
  );
  const replacement = "State plainly when the evidence has no footing.";
  const preview = promptPreview(
    surface,
    { [segment.key]: replacement },
    "effective",
  );
  assert.equal(preview.parts.map((part) => part.value).join(""), preview.text);
  const located = preview.parts.find((part) => part.segment?.key === segment.key);
  assert.equal(located.value, replacement);
  assert.equal(preview.text.slice(located.start, located.end), replacement);
  assert.equal(
    segmentOverride(segment, {}),
    null,
    "an absent key in the draft-aware map means the override was removed",
  );
  assert.equal(surfaceOverrideCount(surface, {}), 0);
});

test("a draft for another rendering branch is a natural assembled-preview no-op", () => {
  const surface = fixture.surfaces.find((candidate) => candidate.id === "compile.system");
  const segment = surface.segments.find(
    (candidate) => candidate.key === "compile.owner_section",
  );
  assert.equal(segmentInCurrentRendering(surface, segment), false);
  assert.equal(
    assembledPrompt(surface, { [segment.key]: "A different owner branch." }, "effective"),
    surface.assembled_effective,
  );
});

test("placeholder checks understand format specs and the tokenizer exposes known slots", () => {
  const text = "Use {source_id!r} between {start:04d} and {end}.";
  assert.deepEqual([...presentPlaceholders(text)], ["source_id", "start", "end"]);
  assert.deepEqual(missingPlaceholders(text, ["source_id", "start", "end"]), []);
  assert.deepEqual(missingPlaceholders("Use {source_id}", ["source_id", "end"]), ["end"]);
  const tokens = tokenizePromptText(text, ["source_id", "end"]);
  assert.deepEqual(
    tokens.filter((token) => token.kind === "placeholder").map((token) => token.name),
    ["source_id", "end"],
  );
  assert.equal(tokens.map((token) => token.value).join(""), text);
});

test("the rewrite diff can reconstruct both the original and latest draft", () => {
  const original = "Cite every claim and stop when evidence ends.";
  const draft = "Cite every material claim, then state plainly when evidence ends.";
  const parts = diffPromptText(original, draft);
  assert.equal(
    parts.filter((part) => part.kind !== "added").map((part) => part.value).join(""),
    original,
  );
  assert.equal(
    parts.filter((part) => part.kind !== "removed").map((part) => part.value).join(""),
    draft,
  );
  assert.ok(parts.some((part) => part.kind === "added"));
  assert.ok(parts.some((part) => part.kind === "removed"));
});

test("surface grouping preserves registry lifecycle order", () => {
  assert.deepEqual(
    groupPromptSurfaces(fixture.surfaces).map((group) => group.group),
    [
      "intake",
      "compile",
      "challenge",
      "evolve",
      "recall",
      "persona",
      "skill",
      "feedback",
      "eval",
    ],
  );
});

test("directory tree counts shared overrides once and opens only relevant groups by default", () => {
  const groups = groupPromptSurfaces(fixture.surfaces);
  const overlays = Object.fromEntries(
    fixture.surfaces.flatMap((surface) =>
      surface.segments
        .filter((segment) => segment.override_text !== null)
        .map((segment) => [segment.key, segment.override_text]),
    ),
  );
  const recall = groups.find((group) => group.group === "recall");
  assert.equal(promptGroupOverrideCount(recall, overlays), 1);
  assert.deepEqual(
    defaultExpandedPromptGroups(groups, overlays, fixture.surfaces[0].id),
    ["intake", "recall"],
  );
});

test("the studio view owns authoring while the stage face stays an explanatory entry", async () => {
  const [studio, entry, view, api, css, messages] = await Promise.all([
    readFile(new URL("../src/views/engine_console/PromptStudio.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/OverlaysPicker.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/EngineConsoleView.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/engine/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/engineConsole.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/engineConsole.ts", import.meta.url), "utf8"),
  ]);
  assert.match(entry, /engineConsole\.studio\.open/);
  assert.match(entry, /onClick=\{onOpen\}/);
  assert.doesNotMatch(entry, /<Select|<TextArea/);
  assert.match(view, /<PromptStudio/);
  assert.match(studio, /useState\(false\)/, "the override editor opens read-only");
  assert.match(studio, /draft\.setOverlay\(segment\.key/);
  assert.match(studio, /missingPlaceholders/);
  assert.match(studio, /diffPromptText/);
  assert.match(studio, /promptPreview/);
  assert.match(studio, /engineConsole\.studio\.variantNote/);
  assert.match(studio, /selectedSurface\.note \?/);
  assert.match(studio, /pickLocalized\(selectedSurface\.note, locale\)/);
  assert.match(studio, /data-template=/);
  assert.match(studio, /engineConsole\.studio\.modelNote/);
  // The fragment-family path: its own itemized renderer, the "one at a time" note, a
  // per-clause applicability line, and no assembly toggle in that branch.
  assert.match(studio, /function FragmentFamily\(/);
  assert.match(studio, /engineConsole\.studio\.fragmentNote/);
  assert.match(studio, /engineConsole\.studio\.whenUsed/);
  assert.match(studio, /engineConsole\.studio\.overrideInForce/);
  assert.match(studio, /<Badge tone="neutral" className="prompt-studio__kind-badge">/);
  assert.match(studio, /engineConsole\.studio\.kind\.assembled/);
  assert.match(studio, /engineConsole\.studio\.kind\.fragments/);
  assert.match(messages, /组装面 · 模型收到的连续消息/);
  assert.match(messages, /Fragment family · clauses chosen by condition/);
  assert.match(studio, /\{!fragments && \(\s*<SegmentedControl/);
  assert.match(studio, /segment\.context \?/, "the editor prefers the registry's own context");
  assert.match(css, /\.prompt-studio__fragment-context/);
  assert.match(css, /\.prompt-studio__kind-badge/);
  assert.match(
    css,
    /\.prompt-studio__preview-heading\s*\{[\s\S]*?flex-wrap: wrap;/,
    "the assembled toggle wraps instead of crushing the kind badge and title",
  );
  assert.match(studio, /aria-expanded=\{expanded\}/);
  assert.match(studio, /engineConsole\.studio\.expandAll/);
  assert.match(studio, /engineConsole\.studio\.collapseAll/);
  assert.match(api, /"\/v1\/engine\/prompts"/);
  assert.match(api, /"\/v1\/engine\/prompts\/rewrite"/);
  assert.match(css, /\.prompt-studio__grid[\s\S]*?grid-template-columns:/);
  assert.match(css, /\.prompt-studio[\s\S]*?overflow: hidden;/);
});
