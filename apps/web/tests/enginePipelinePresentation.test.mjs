import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

async function transform(url, replacements = []) {
  let source = await readFile(url, "utf8");
  for (const [from, to] of replacements) source = source.replaceAll(from, to);
  const transformed = await transformWithEsbuild(source, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const yamlUrl = await transform(new URL("../src/lib/engineYaml.ts", import.meta.url));
const consoleUrl = await transform(new URL("../src/lib/engineConsole.ts", import.meta.url), [
  ['"./engineYaml"', JSON.stringify(yamlUrl)],
]);
const presentationUrl = await transform(
  new URL("../src/views/engine_console/pipelinePresentation.ts", import.meta.url),
  [['"@/lib/engineConsole"', JSON.stringify(consoleUrl)]],
);
const {
  accessRouteState,
  edgeVisualRole,
  placeAccessRouteMerge,
  placeAccessRoutes,
  placeEngineStages,
  stageRouteAvailable,
  isReversePair,
} =
  await import(presentationUrl);

const loc = (text) => ({ en: text, zh: text });
const stage = (id) => ({ id, title: loc(id), summary: loc(id), doc: "x", file: `${id}.yaml`, knobs: [] });

const schema = {
  schema_version: 1,
  stages: [stage("receive"), stage("judge"), stage("answer"), stage("audit"), stage("evolve"), stage("models")],
  edges: [
    { from: "receive", to: "judge", label: loc("blocks") },
    { from: "judge", to: "answer", label: loc("claims") },
    { from: "judge", to: "audit", condition: "audit.enabled", label: loc("audit") },
    { from: "audit", to: "judge", condition: "audit.compensate", label: loc("repair") },
    { from: "judge", to: "evolve", condition: "evolve.auto", label: loc("enough") },
  ],
  access_routes: [
    { id: "l0", from: "receive", to: "answer", title: loc("L0"), summary: loc("verbatim") },
    { id: "l1", from: "receive", to: "answer", title: loc("L1"), summary: loc("lexical") },
    {
      id: "l2",
      from: "receive",
      to: "answer",
      condition: "intake_plan.semantic_indexing",
      title: loc("L2"),
      summary: loc("semantic"),
    },
    {
      id: "l3",
      from: "judge",
      to: "answer",
      condition: "intake_plan.canonical_treatment",
      title: loc("L3"),
      summary: loc("canonical"),
    },
  ],
};

test("pipeline placement is derived from edge roles, not frozen stage ids", () => {
  const placements = placeEngineStages(schema);
  const byId = new Map(placements.map((placement) => [placement.id, placement]));
  assert.deepEqual(
    ["receive", "judge", "answer"].map((id) => byId.get(id).lane),
    ["spine", "spine", "spine"],
  );
  assert.equal(byId.get("audit").lane, "branch");
  assert.equal(byId.get("evolve").lane, "branch");
  assert.equal(byId.get("models").lane, "support");
  assert.ok(byId.get("audit").y < byId.get("judge").y, "the first branch sits above its anchor");
  assert.ok(byId.get("evolve").y > byId.get("judge").y, "the second branch sits below its anchor");
  assert.ok(
    byId.get("judge").x - byId.get("receive").x >= 400,
    "the lifecycle spine leaves enough room for an attached edge label",
  );
  assert.equal(
    byId.get("answer").x - byId.get("judge").x,
    420,
    "the channel band no longer consumes a fake column on the lifecycle spine",
  );
  assert.ok(
    byId.get("models").y - byId.get("evolve").y >= 200,
    "support configuration is a separate shelf rather than another flow row",
  );
});

test("route availability stays true when any incoming route is wired", () => {
  assert.equal(stageRouteAvailable("audit", schema.edges, { "audit.enabled": false }), false);
  assert.equal(stageRouteAvailable("audit", schema.edges, { "audit.enabled": true }), true);
  assert.equal(
    stageRouteAvailable("judge", schema.edges, { "audit.compensate": false }),
    true,
    "the unconditional receive route keeps judge available when the audit back-edge is off",
  );
});

test("only the later edge in a bidirectional pair is routed as the return path", () => {
  const forward = schema.edges[2];
  const back = schema.edges[3];
  assert.equal(isReversePair(forward, schema.edges), false);
  assert.equal(isReversePair(back, schema.edges), true);
});

test("edge roles give the lifecycle spine, branches, and compensation loop distinct grammar", () => {
  const placements = placeEngineStages(schema);
  assert.equal(edgeVisualRole(schema.edges[0], schema.edges, placements), "spine");
  assert.equal(edgeVisualRole(schema.edges[1], schema.edges, placements), "spine");
  assert.equal(edgeVisualRole(schema.edges[2], schema.edges, placements), "branch");
  assert.equal(edgeVisualRole(schema.edges[3], schema.edges, placements), "return");
  assert.equal(edgeVisualRole(schema.edges[4], schema.edges, placements), "branch");
});

test("access routes form an evenly spaced channel band and preserve per-source condition state", () => {
  const stages = placeEngineStages(schema);
  const routes = placeAccessRoutes(schema.access_routes, stages);
  const merge = placeAccessRouteMerge(schema.access_routes, stages, routes);
  const byStageId = new Map(stages.map((placement) => [placement.id, placement]));
  assert.equal(routes.length, 4);
  assert.deepEqual(
    routes.slice(1).map((route, index) => route.y - routes[index].y),
    [46, 46, 46],
  );
  assert.equal(
    new Set(routes.map((route) => route.x + route.width)).size,
    1,
    "every horizontal channel reaches the same merge approach",
  );
  assert.equal(routes[0].x, routes[1].x);
  assert.equal(routes[1].x, routes[2].x);
  assert.equal(routes[0].x, byStageId.get("receive").x + 108);
  assert.equal(routes[3].x, byStageId.get("judge").x + 108);
  assert.ok(
    routes[0].y > byStageId.get("evolve").y + 100,
    "the channel band clears the lower branch",
  );
  assert.ok(
    byStageId.get("models").y > routes[3].y + 100,
    "the support shelf clears the channel band",
  );
  assert.deepEqual(merge, {
    targetId: "answer",
    x: byStageId.get("answer").x + 108,
    y: routes[0].y - 58,
  });
  assert.equal(accessRouteState(schema.access_routes[0], {}), "active");
  assert.equal(accessRouteState(schema.access_routes[2], {}), "conditional");
  assert.equal(
    accessRouteState(schema.access_routes[2], { "intake_plan.semantic_indexing": "summary" }),
    "active",
  );
  assert.equal(
    accessRouteState(schema.access_routes[2], { "intake_plan.semantic_indexing": "none" }),
    "inactive",
  );
});

test("the Engine Console keeps nodes compact and selection fully controlled during inspector motion", async () => {
  const [pipelineSource, viewSource, cssSource] = await Promise.all([
    readFile(new URL("../src/views/engine_console/PipelineMap.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/EngineConsoleView.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/engineConsole.css", import.meta.url), "utf8"),
  ]);
  assert.match(pipelineSource, /nodesDraggable=\{false\}/);
  assert.doesNotMatch(pipelineSource, /engine-stage-node__values/);
  assert.match(pipelineSource, /nodes=\{computedNodes\}/);
  assert.match(pipelineSource, /schema\.access_routes/);
  assert.match(pipelineSource, /type: "accessRoute"/);
  assert.match(pipelineSource, /type: "accessMerge"/);
  assert.match(pipelineSource, /role: "access-trunk"/);
  assert.doesNotMatch(pipelineSource, /useNodesState/);
  assert.match(viewSource, /key=\{selectedStage\.id\}/);
  assert.match(cssSource, /\.engine-access-node__label/);
  assert.doesNotMatch(cssSource, /\.engine-access-node[\s\S]*?min-height:\s*68px/);
  assert.match(cssSource, /\.engine-inspector__swap[\s\S]*?pointer-events: auto;/);
});

test("document and knob faces pin preview-first and commit-on-blur safeguards", async () => {
  const [documentSource, drawerSource] = await Promise.all([
    readFile(new URL("../src/views/engine_console/ContractEditor.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/views/engine_console/StageDrawer.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(documentSource, /useState\("preview"\)/);
  assert.match(documentSource, /engineConsole\.editor\.modify/);
  assert.match(documentSource, /engineConsole\.editor\.saveDraft/);
  assert.match(documentSource, /engineConsole\.editor\.discard/);
  assert.doesNotMatch(documentSource, /onChange=\{\(event\) => draft\.setFile/);
  assert.match(drawerSource, /onBlur=\{commit\}/);
  assert.match(drawerSource, /engineConsole\.number\.invalid/);
  assert.doesNotMatch(drawerSource, /<NumberField/);
  assert.doesNotMatch(drawerSource, /EffectNote/);
  assert.equal(
    drawerSource.match(/t\("engineConsole\.i2"\)/g)?.length,
    1,
    "the selected-stage face states invariant I2 once",
  );
});
