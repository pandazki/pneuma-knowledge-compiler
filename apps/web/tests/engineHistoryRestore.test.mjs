import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("engine version inspection and restore use the frozen read route and ordinary draft review", async () => {
  const [api, timeline, documentEditor, consoleView, draft] = await Promise.all([
    readFile(new URL("../src/engine/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/VersionTimeline.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/ContractEditor.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/EngineConsoleView.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/engine/draft.ts", import.meta.url), "utf8"),
  ]);

  assert.match(api, /\/v1\/engine\/history\/\$\{encodeURIComponent\(sha\)\}\/files/);
  assert.match(api, /fixture\.history\.snapshots/);
  assert.match(timeline, /getHistoryFiles\(selectedSha\)/);
  assert.match(timeline, /engineConsole\.history\.restoreConfirm/);
  assert.match(timeline, /onLoadDraft\(Object\.fromEntries\(changedFiles\)\)/);
  assert.match(documentEditor, /getHistoryFiles\(sha\)/);
  assert.doesNotMatch(timeline, /\.snapshot/);
  assert.doesNotMatch(documentEditor, /\.snapshot/);
  assert.match(draft, /replaceWithFiles/);
  assert.match(consoleView, /draft\.replaceWithFiles\(files\)/);
  assert.match(consoleView, /setReviewOpen\(true\)/);
});
