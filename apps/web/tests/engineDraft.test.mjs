/**
 * engineConsole pure logic: the draft → pending-changes → apply-payload derivation and the
 * edge-condition evaluation that wires/unwires the pipeline map. engineConsole.ts imports
 * engineYaml.ts, so the yaml module is transformed first and the import specifier is
 * rewritten to its data URL — same harness as the other pure-module tests, one extra hop.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

async function importTs(url) {
  const sourceText = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(sourceText, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const yamlUrl = await importTs(new URL("../src/lib/engineYaml.ts", import.meta.url));
const consoleUrl = new URL("../src/lib/engineConsole.ts", import.meta.url);
let consoleText = await readFile(consoleUrl, "utf8");
consoleText = consoleText.replaceAll('"./engineYaml"', JSON.stringify(yamlUrl));
const consoleTransformed = await transformWithEsbuild(consoleText, consoleUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const consoleModuleUrl = `data:text/javascript;base64,${Buffer.from(consoleTransformed.code).toString("base64")}`;
const {
  effectiveValues,
  isEdgeActive,
  knobValue,
  pathFromError,
  pendingChanges,
  buildApplyPayload,
  changedHistoryFiles,
  pickLocalized,
} = await import(consoleModuleUrl);

/* --------------------------------------------------------------- mini fixtures */

const loc = (en, zh = en) => ({ en, zh });

const schema = {
  schema_version: 1,
  stages: [
    {
      id: "intake",
      title: loc("Intake"),
      summary: loc("…"),
      doc: "docs/architecture.md#ingest",
      file: "intake/intake.yaml",
      knobs: [
        {
          key: "chunk_strategy",
          env: "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
          type: "enum",
          enum: ["semantic", "sentence"],
          default: "semantic",
          apply: "derived_rebuild",
          label: loc("Chunk strategy"),
          description: loc("…"),
        },
      ],
    },
    {
      id: "compile",
      title: loc("Compile"),
      summary: loc("…"),
      doc: "docs/architecture.md#compile",
      file: "compile/contract.md",
      knobs: [
        {
          key: "contract",
          env: "",
          type: "document",
          default: "",
          apply: "future_compiles",
          label: loc("Contract"),
          description: loc("…"),
        },
      ],
    },
    {
      id: "challenge",
      title: loc("Challenge"),
      summary: loc("…"),
      doc: "docs/architecture.md#challenge",
      file: "compile/challenge.yaml",
      knobs: [
        {
          key: "enabled",
          env: "PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED",
          type: "bool",
          default: false,
          apply: "future_compiles",
          label: loc("Enabled"),
          description: loc("…"),
        },
        {
          key: "max_rounds",
          env: "PNEUMA_KNOWLEDGE_CHALLENGE_MAX_ROUNDS",
          type: "int",
          default: 2,
          apply: "future_compiles",
          label: loc("Rounds"),
          description: loc("…"),
        },
      ],
    },
    {
      id: "recall",
      title: loc("Recall"),
      summary: loc("…"),
      doc: "docs/architecture.md#recall",
      file: "recall/recall.yaml",
      knobs: [
        {
          key: "rerank_model",
          env: "PNEUMA_KNOWLEDGE_RECALL_RERANK_MODEL",
          type: "string",
          default: "",
          apply: "hot",
          label: loc("Rerank model"),
          description: loc("…"),
        },
      ],
    },
    {
      id: "prompts",
      title: loc("Prompts"),
      summary: loc("…"),
      doc: "docs/architecture.md#prompts",
      file: "prompts/overlays.yaml",
      knobs: [
        {
          key: "overlays",
          env: "",
          type: "overlay_map",
          enum: ["recall.answer.style", "compile.gate.citation_rule"],
          default: {},
          apply: "hot",
          label: loc("Overlays"),
          description: loc("…"),
        },
      ],
    },
  ],
  edges: [
    { from: "intake", to: "compile", label: loc("chunks") },
    { from: "compile", to: "challenge", condition: "challenge.enabled", label: loc("audit") },
  ],
};

const state = {
  files: {
    "intake/intake.yaml": "# intake\nchunk_strategy: semantic\n",
    "compile/contract.md": "# Contract\n\nEvery claim cites.\n",
    "compile/challenge.yaml": "# challenge\nenabled: true\nmax_rounds: 2\n",
    // The real shape: one top-level `overlays` key over the map (codex review #4 — this
    // fixture used to be flat, which is why 130 passing tests missed the contract break).
    "prompts/overlays.yaml": "# overlays\noverlays:\n  recall.answer.style: |\n    Be blunt.\n",
    "recall/recall.yaml": '# recall\nrerank_model: "openrouter:x/rerank"\n',
  },
  values: {
    "intake.chunk_strategy": "semantic",
    "challenge.enabled": true,
    "challenge.max_rounds": 2,
    "prompts.overlays": { "recall.answer.style": "Be blunt.\n" },
    "recall.rerank_model": "openrouter:x/rerank",
  },
  resolution: {
    "intake.chunk_strategy": "engine",
    "challenge.enabled": "engine",
    "challenge.max_rounds": "default",
    "prompts.overlays": "engine",
    "recall.rerank_model": "engine",
  },
  version: { head: "a1b2c3d", dirty: false },
};

const emptyDraft = { values: {}, files: {}, overlays: {} };

/* -------------------------------------------------------------------- the tests */

test("isEdgeActive: unconditional edges are always on; conditions read the values map", () => {
  const [plain, conditional] = schema.edges;
  assert.equal(isEdgeActive(plain, {}), true);
  assert.equal(isEdgeActive(conditional, { "challenge.enabled": true }), true);
  assert.equal(isEdgeActive(conditional, { "challenge.enabled": false }), false);
  assert.equal(isEdgeActive(conditional, {}), false, "an unknown condition value is off");
});

test("effectiveValues folds the draft over state, so the map rewires on a draft toggle", () => {
  const draft = { ...emptyDraft, values: { "challenge.enabled": false } };
  const values = effectiveValues(state, draft);
  assert.equal(values["challenge.enabled"], false);
  assert.equal(isEdgeActive(schema.edges[1], values), false, "edge unwires on the draft value");
  assert.equal(isEdgeActive(schema.edges[1], effectiveValues(state, emptyDraft)), true);
});

test("knobValue precedence: draft override → resolved state → schema default", () => {
  const knob = schema.stages[2].knobs[1]; // challenge.max_rounds
  assert.equal(knobValue(state, emptyDraft, "challenge", knob), 2);
  assert.equal(
    knobValue(state, { ...emptyDraft, values: { "challenge.max_rounds": 3 } }, "challenge", knob),
    3,
  );
  const noState = { ...state, values: {} };
  assert.equal(knobValue(noState, emptyDraft, "challenge", knob), 2, "schema default fills the gap");
});

test("pendingChanges: a knob edit reports path, old → new and its blast radius", () => {
  const draft = { ...emptyDraft, values: { "challenge.enabled": false, "challenge.max_rounds": 2 } };
  const rows = pendingChanges(schema, state, draft);
  assert.equal(rows.length, 1, "a value equal to the resolved one is not a change");
  assert.deepEqual(rows[0], {
    kind: "knob",
    key: "challenge.enabled",
    path: "compile/challenge.yaml",
    oldValue: true,
    newValue: false,
    apply: "future_compiles",
  });
});

test("pendingChanges: a contract edit is a whole-document change, never decomposed", () => {
  const draft = { ...emptyDraft, files: { "compile/contract.md": "# Contract v2\n" } };
  const rows = pendingChanges(schema, state, draft);
  assert.deepEqual(rows, [
    { kind: "document", key: "compile.contract", path: "compile/contract.md", apply: "future_compiles" },
  ]);
});

test("pendingChanges: overlay set and removal are per-catalog-key rows", () => {
  const draft = {
    ...emptyDraft,
    overlays: { "compile.gate.citation_rule": "Cite or die.", "recall.answer.style": null },
  };
  const rows = pendingChanges(schema, state, draft);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], {
    kind: "overlay",
    key: "prompts.overlays",
    path: "prompts/overlays.yaml",
    catalogKey: "compile.gate.citation_rule",
    clause: "Cite or die.",
    apply: "hot",
  });
  assert.equal(rows[1].clause, null);
});

test("pendingChanges: restoring an unsaved overlay to inherited is a no-op", () => {
  const draft = {
    ...emptyDraft,
    overlays: {
      "compile.gate.citation_rule": null,
      "recall.answer.style": "Be blunt.\n",
    },
  };
  assert.deepEqual(pendingChanges(schema, state, draft), []);
});

test("buildApplyPayload: knob edits compose into one file write with other lines intact", () => {
  const draft = { ...emptyDraft, values: { "challenge.enabled": false, "challenge.max_rounds": 5 } };
  const payload = buildApplyPayload(schema, state, draft);
  assert.equal(payload.length, 1);
  assert.equal(payload[0].path, "compile/challenge.yaml");
  assert.equal(
    payload[0].content,
    "# challenge\nenabled: false\nmax_rounds: 5\n",
    "both knobs land in one write; the comment survives",
  );
});

test("buildApplyPayload: a document edit ships the whole file", () => {
  const draft = { ...emptyDraft, files: { "compile/contract.md": "# Contract v2\n" } };
  const payload = buildApplyPayload(schema, state, draft);
  assert.deepEqual(payload, [{ path: "compile/contract.md", content: "# Contract v2\n" }]);
});

test("historical whole-file restores stay exact and appear in the ordinary review", () => {
  const draft = {
    ...emptyDraft,
    files: {
      "recall/recall.yaml": '# recall\nrerank_model: ""\n',
      "README.md": "# Older engine\n",
    },
  };
  assert.deepEqual(pendingChanges(schema, state, draft), [
    {
      kind: "file",
      key: "recall/recall.yaml",
      path: "recall/recall.yaml",
      apply: "hot",
    },
    { kind: "file", key: "README.md", path: "README.md", apply: null },
  ]);
  assert.deepEqual(buildApplyPayload(schema, state, draft), [
    { path: "recall/recall.yaml", content: '# recall\nrerank_model: ""\n' },
    { path: "README.md", content: "# Older engine\n" },
  ]);
});

test("historical diff includes only files that would replace current HEAD", () => {
  assert.deepEqual(
    changedHistoryFiles(
      { "z.yaml": "old z", "a.yaml": "same", "b.yaml": "old b" },
      { "z.yaml": "new z", "a.yaml": "same", "b.yaml": "new b" },
    ),
    [["b.yaml", "old b"], ["z.yaml", "old z"]],
  );
});

test("buildApplyPayload: overlay add + remove compose over the base file", () => {
  const draft = {
    ...emptyDraft,
    overlays: { "compile.gate.citation_rule": "Cite or die.", "recall.answer.style": null },
  };
  const payload = buildApplyPayload(schema, state, draft);
  assert.equal(payload.length, 1);
  assert.equal(payload[0].path, "prompts/overlays.yaml");
  assert.ok(payload[0].content.startsWith("# overlays\n"), "header survives");
  assert.ok(!payload[0].content.includes("recall.answer.style"), "removal landed");
  assert.ok(
    payload[0].content.includes("overlays:\n  compile.gate.citation_rule: |\n    Cite or die.\n"),
    "the new override is nested under the overlays key the service validates",
  );
});

test("buildApplyPayload: clearing a string knob writes an empty string, not YAML null", () => {
  // codex review #7: the UI clearing `rerank_model` used to write `rerank_model:`, which is
  // null — the service refuses it as a non-string, and the person is told only that the apply
  // failed even though empty is the documented way to turn reranking off.
  const draft = { ...emptyDraft, values: { "recall.rerank_model": "" } };
  const payload = buildApplyPayload(schema, state, draft);
  assert.deepEqual(payload, [
    { path: "recall/recall.yaml", content: '# recall\nrerank_model: ""\n' },
  ]);
});

test("buildApplyPayload: a string knob's value cannot change the file's shape", () => {
  const draft = { ...emptyDraft, values: { "recall.rerank_model": "a: b # c" } };
  const payload = buildApplyPayload(schema, state, draft);
  assert.equal(payload[0].content, '# recall\nrerank_model: "a: b # c"\n');
});

test("buildApplyPayload: a draft value equal to the resolved value writes nothing", () => {
  const draft = { ...emptyDraft, values: { "challenge.enabled": true } };
  assert.deepEqual(buildApplyPayload(schema, state, draft), []);
});

test("pathFromError: a state failure that names a stage file points the repair at it", () => {
  // codex E2E suggestion 3: /state 400s on a hand-broken file and the console has to offer a
  // way back. The service's detail always carries the engine-relative path, so the file list is
  // matched against the message rather than the message being parsed.
  assert.equal(
    pathFromError(schema, "recall/recall.yaml is not valid YAML: while parsing a flow node"),
    "recall/recall.yaml",
  );
  assert.equal(pathFromError(schema, "something else entirely"), null, "no guessing");
  assert.equal(pathFromError(schema, null), null);
  assert.equal(pathFromError(null, "recall/recall.yaml is not valid YAML"), null);
});

test("pickLocalized: active locale wins, English is the fallback", () => {
  assert.equal(pickLocalized(loc("Intake", "导入"), "zh"), "导入");
  assert.equal(pickLocalized(loc("Intake", "导入"), "en"), "Intake");
  assert.equal(pickLocalized({ en: "Intake", zh: "" }, "zh"), "Intake");
});
