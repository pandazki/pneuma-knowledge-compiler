import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const [badgesSource, stageSource, overlaysSource, studioSource, tooltipSource, messagesSource] =
  await Promise.all([
    readFile(new URL("../src/views/engine_console/badges.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/StageDrawer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/OverlaysPicker.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/PromptStudio.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/ui/Tooltip.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/engineConsole.ts", import.meta.url), "utf8"),
  ]);

test("effect and origin semantics use one quiet Lucide icon vocabulary", () => {
  for (const icon of [
    "Zap",
    "RotateCw",
    "FastForward",
    "Database",
    "Lock",
    "FileCog",
    "CircleDashed",
  ]) {
    assert.match(badgesSource, new RegExp(`\\b${icon}\\b`));
  }
  assert.match(badgesSource, /text-ink-3/);
  assert.doesNotMatch(badgesSource, /<Badge\b/);
  assert.doesNotMatch(badgesSource, /\btitle=/);
});

test("semantic icon tooltips are keyboard reachable, accessible, themed, and shared", () => {
  assert.match(badgesSource, /<Tooltip content=\{note\}/);
  assert.match(badgesSource, /tabIndex=\{0\}/);
  assert.match(badgesSource, /role="img"/);
  assert.match(badgesSource, /aria-label=\{label\}/);
  assert.match(tooltipSource, /bg-raised/);
  assert.match(tooltipSource, /text-ink/);

  for (const source of [stageSource, overlaysSource, studioSource]) {
    assert.match(source, /EffectBadge/);
    assert.match(source, /OriginBadge/);
  }
});

test("tooltips carry complete bilingual semantics and env pins warn once per stage", () => {
  assert.match(
    messagesSource,
    /修改只对之后新编译的材料生效；已入正本的内容不会被改写。/,
  );
  assert.match(
    messagesSource,
    /The change applies only to material compiled afterward; content already in the canonical library is not rewritten\./,
  );
  assert.match(messagesSource, /被进程环境变量锁定，控制台改动对当前进程无效。/);
  assert.match(
    messagesSource,
    /Pinned by a process environment variable, so Console edits do not affect the current process\./,
  );

  assert.equal(stageSource.match(/engineConsole\.envOverrideSummary/g)?.length, 1);
  assert.doesNotMatch(stageSource, /engineConsole\.envOverride["`]/);
});
