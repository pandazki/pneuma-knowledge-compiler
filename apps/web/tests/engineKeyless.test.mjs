import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const [types, fixtureText, stage, overview, messages, css] = await Promise.all([
  readFile(new URL("../src/engine/types.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/engine/fixtures/state.json", import.meta.url), "utf8"),
  readFile(new URL("../src/views/engine_console/StageDrawer.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/views/engine_console/EngineOverview.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/i18n/engineConsole.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/views/engine_console/engineConsole.css", import.meta.url), "utf8"),
]);

test("engine state carries the deployment keyless flag without changing fixture defaults", () => {
  const fixture = JSON.parse(fixtureText);
  assert.match(types, /keyless: boolean;/);
  assert.equal(fixture.keyless, false);
});

test("keyless model unavailability is quiet, conditional, bilingual, and shared with overview", () => {
  assert.match(stage, /state\?\.keyless && stage\.id === "models"/);
  assert.match(stage, /engineConsole\.models\.keylessNotice/);
  assert.match(stage, /engine-inspector__keyless-note" role="status"/);
  assert.match(overview, /if \(state\?\.keyless\)/);
  assert.match(overview, /engineConsole\.overview\.modelAvailability/);
  assert.match(overview, /t\("engineConsole\.models\.keylessNotice"\)/);
  assert.match(
    messages,
    /当前部署未配置 OPENROUTER_API_KEY——下列模型角色暂不可用（问答、编译、AI 改写需要密钥）；浏览与配置不受影响。/,
  );
  assert.match(messages, /browsing and configuration are unaffected\./);
  assert.match(css, /\.engine-inspector__keyless-note[\s\S]*?color: var\(--engine-ink-3\)/);
  assert.match(css, /\.engine-overview__rows > div\[data-keyless\]/);
});
