import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/evolve.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  areaFromTemplate,
  buildEvolveTimeline,
  buildPackDrafts,
  buildSchemaAxis,
  changedFileKind,
  diffStat,
  evolveScale,
  evolveStatusTone,
  evolveTimelineCounts,
  familyFromTemplate,
  fmtTtlRemaining,
  groupFamiliesByArea,
  isTerminalEvolveStatus,
  lineDiff,
  parseRationale,
  proposedFamilies,
  selectedTimelineEntry,
  ttlRemainingMs,
} = await import(moduleUrl);

/* ------------------------------------------------------------------- fixtures
 * 合成任务账：框架自带的归档语汇（people / topics / products …）+ 两个演化提案，
 * 不涉及任何具体业务或人名。
 */

const BASE_TEMPLATES = [
  "memory/profile.md",
  "memory/people/{slug}.md",
  "memory/topics/{slug}.md",
  "work/products/{slug}.md",
  "materials/{slug}.md",
];

function task(overrides) {
  return {
    task_id: "evolve-0000",
    status: "draft",
    detail: null,
    summary: null,
    created_at: null,
    decided_at: null,
    families: [],
    path_templates: [],
    ...overrides,
  };
}

const ADOPTED_RUNBOOKS = task({
  task_id: "evolve-0001",
  status: "adopted",
  created_at: "2026-05-02T09:00:00Z",
  decided_at: "2026-05-02T11:30:00Z",
  families: ["runbooks"],
  path_templates: ["work/runbooks/{slug}.md"],
  summary: {
    new_documents: 3,
    moved_claims: 12,
    merged_claims: 2,
    adopted_by_document: {
      "work/runbooks/deploy.md": 7,
      "work/runbooks/rollback.md": 5,
    },
  },
});

const ADOPTED_DECISIONS = task({
  task_id: "evolve-0002",
  status: "adopted",
  created_at: "2026-06-11T09:00:00Z",
  decided_at: "2026-06-11T10:00:00Z",
  families: ["decisions"],
  path_templates: ["memory/decisions/{slug}.md"],
  summary: {
    new_documents: 1,
    moved_claims: 4,
    merged_claims: 0,
    adopted_by_document: { "memory/decisions/storage.md": 4 },
  },
});

const DRAFT_GLOSSARY = task({
  task_id: "evolve-0003",
  status: "draft",
  created_at: "2026-07-20T08:00:00Z",
  families: ["glossary"],
  path_templates: ["memory/glossary/{slug}.md"],
  summary: {
    new_documents: 2,
    moved_claims: 6,
    merged_claims: 1,
    adopted_by_document: { "memory/glossary/terms.md": 6 },
  },
});

const DROPPED_NO_CHANGE = task({
  task_id: "evolve-0004",
  status: "no_change",
  created_at: "2026-07-25T08:00:00Z",
  decided_at: "2026-07-25T08:00:10Z",
});

const SKILL = {
  version: "v3+2",
  content_hash: "9f1c2ab4",
  base_version: "v3",
  path_templates: [
    ...BASE_TEMPLATES,
    "work/runbooks/{slug}.md",
    "memory/decisions/{slug}.md",
    "work/operations/{slug}.md",
  ],
  packs: [
    {
      pack_id: "role-engineering",
      origin: "matrix",
      extra_path_templates: ["work/operations/{slug}.md"],
    },
    {
      pack_id: "evolved-runbooks",
      origin: "evolved",
      extra_path_templates: ["work/runbooks/{slug}.md"],
    },
    {
      pack_id: "evolved-decisions",
      origin: "evolved",
      extra_path_templates: ["memory/decisions/{slug}.md"],
    },
  ],
};

/* --------------------------------------------------------------- 状态与 TTL */

test("status tone only colors real states, terminal set drives polling", () => {
  assert.equal(evolveStatusTone("draft"), "warn");
  assert.equal(evolveStatusTone("adopted"), "ok");
  assert.equal(evolveStatusTone("aborted"), "danger");
  assert.equal(evolveStatusTone("dropped"), "neutral");
  assert.equal(evolveStatusTone("running-something-new"), "neutral");

  assert.equal(isTerminalEvolveStatus("adopted"), true);
  assert.equal(isTerminalEvolveStatus("no_change"), true);
  assert.equal(isTerminalEvolveStatus("draft"), false);
  assert.equal(isTerminalEvolveStatus("phase2"), false);
});

test("TTL countdown is advisory and degrades honestly", () => {
  const now = Date.parse("2026-07-20T10:00:00Z");
  assert.equal(ttlRemainingMs("2026-07-20T08:00:00Z", 24, now), 22 * 3600_000);
  assert.equal(ttlRemainingMs(null, 24, now), null);
  assert.equal(ttlRemainingMs("not-a-date", 24, now), null);
  assert.equal(ttlRemainingMs("2026-07-18T08:00:00Z", 24, now) < 0, true);

  assert.equal(fmtTtlRemaining(22 * 3600_000), "剩约 22h0m");
  assert.equal(fmtTtlRemaining(45 * 60_000), "剩约 45m");
  assert.equal(fmtTtlRemaining(-1), "已超评审窗口");
});

/* --------------------------------------------------------------- 模板 → family */

test("family and area come out of the path template mechanically", () => {
  assert.equal(familyFromTemplate("memory/people/{slug}.md"), "people");
  assert.equal(familyFromTemplate("memory/profile.md"), "profile");
  assert.equal(familyFromTemplate("materials/{slug}.md"), "materials");
  assert.equal(familyFromTemplate("archive/legal/contracts/{slug}.md"), "contracts");
  assert.equal(familyFromTemplate("weird"), "weird");

  assert.equal(areaFromTemplate("memory/people/{slug}.md"), "memory");
  assert.equal(areaFromTemplate("materials/{slug}.md"), "materials");
  assert.equal(areaFromTemplate("{slug}.md"), "—");
});

/* ------------------------------------------------------------------- 时间线 */

test("timeline is newest-first while ordinals count forward in time", () => {
  // 输入故意乱序：顺序不能依赖端点。
  const entries = buildEvolveTimeline([
    DRAFT_GLOSSARY,
    ADOPTED_RUNBOOKS,
    DROPPED_NO_CHANGE,
    ADOPTED_DECISIONS,
  ]);

  assert.deepEqual(
    entries.map((e) => e.taskId),
    ["evolve-0004", "evolve-0003", "evolve-0002", "evolve-0001"],
  );
  assert.deepEqual(
    entries.map((e) => e.ordinal),
    [4, 3, 2, 1],
  );
  assert.equal(entries[1].awaitingReview, true);
  assert.equal(entries[1].pending, true);
  assert.equal(entries[0].pending, false);
  assert.deepEqual(entries[3].families, ["runbooks"]);
  assert.deepEqual(entries[3].pathTemplates, ["work/runbooks/{slug}.md"]);
});

test("tasks without a timestamp sort last instead of pretending to be oldest", () => {
  const undated = task({ task_id: "evolve-9999", status: "aborted" });
  const entries = buildEvolveTimeline([ADOPTED_RUNBOOKS, undated]);
  // 最新在前：无时间戳的条目垫底 → 拿到最大 ordinal → 排在时间线顶端。
  assert.equal(entries[0].taskId, "evolve-9999");
  assert.equal(entries[0].ordinal, 2);
  assert.equal(entries[0].sortKey, null);
  assert.equal(entries[1].taskId, "evolve-0001");
  assert.equal(entries[1].ordinal, 1);
});

test("scale summary tallies the mechanical reorg and tolerates a missing summary", () => {
  assert.deepEqual(evolveScale(ADOPTED_RUNBOOKS.summary), {
    newDocuments: 3,
    movedClaims: 12,
    mergedClaims: 2,
    adoptedDocuments: 2,
    touchedClaims: 14,
  });
  assert.deepEqual(evolveScale(null), {
    newDocuments: 0,
    movedClaims: 0,
    mergedClaims: 0,
    adoptedDocuments: 0,
    touchedClaims: 0,
  });
  assert.deepEqual(evolveScale({ moved_claims: "12" }), {
    newDocuments: 0,
    movedClaims: 0,
    mergedClaims: 0,
    adoptedDocuments: 0,
    touchedClaims: 0,
  });
});

test("timeline counts split the gate outcomes", () => {
  const entries = buildEvolveTimeline([
    ADOPTED_RUNBOOKS,
    ADOPTED_DECISIONS,
    DRAFT_GLOSSARY,
    DROPPED_NO_CHANGE,
    task({ task_id: "evolve-0005", status: "expired", created_at: "2026-07-26T08:00:00Z" }),
  ]);
  assert.deepEqual(evolveTimelineCounts(entries), {
    total: 5,
    awaitingReview: 1,
    adopted: 2,
    declined: 1,
    noChange: 1,
  });
});

test("families reverse-derive from templates when an older service omits them", () => {
  const legacy = task({
    task_id: "evolve-legacy",
    path_templates: ["memory/glossary/{slug}.md", "memory/glossary/{slug}.md"],
  });
  assert.deepEqual(proposedFamilies(legacy), ["glossary"]);
  // 两个字段都没有 → 空，不猜。
  assert.deepEqual(proposedFamilies(task({})), []);
});

test("selection resolves only against the tasks actually on hand", () => {
  const entries = buildEvolveTimeline([ADOPTED_RUNBOOKS, DRAFT_GLOSSARY]);
  assert.equal(selectedTimelineEntry(entries, "evolve-0003")?.ordinal, 2);
  assert.equal(selectedTimelineEntry(entries, "evolve-4242"), null);
  assert.equal(selectedTimelineEntry(entries, null), null);
});

/* -------------------------------------------------------------- pack 草案 */

test("pack drafts read the stored proposal and name the family", () => {
  const packs = buildPackDrafts({
    packs: [
      {
        pack_id: "evolved-runbooks",
        origin: "evolved",
        extra_instructions: "  收录可重复执行的操作流程。  ",
        extra_path_templates: ["work/runbooks/{slug}.md", ""],
        extra_contract_rules: ["每条 claim 必须带 cite"],
      },
      {
        pack_id: "",
        origin: "evolved",
        extra_instructions: "",
        extra_path_templates: ["memory/glossary/{slug}.md"],
      },
    ],
    rationale: "…",
  });

  assert.equal(packs.length, 2);
  assert.equal(packs[0].family, "runbooks");
  assert.equal(packs[0].packId, "evolved-runbooks");
  assert.equal(packs[0].instructions, "收录可重复执行的操作流程。");
  assert.deepEqual(packs[0].pathTemplates, ["work/runbooks/{slug}.md"]);
  assert.deepEqual(packs[0].contractRules, ["每条 claim 必须带 cite"]);
  // pack_id 缺失时回落到模板反推的 family。
  assert.equal(packs[1].packId, null);
  assert.equal(packs[1].family, "glossary");

  assert.deepEqual(buildPackDrafts(null), []);
  assert.deepEqual(buildPackDrafts({}), []);
  assert.deepEqual(buildPackDrafts({ packs: "nope" }), []);
});

test("rationale splits into a lead and one evidence line per pack", () => {
  const parsed = parseRationale(
    "增量里出现了两簇稳定的新材料。\n\nrunbooks：7 篇部署记录反复引用同一流程\ndecisions：4 条选型结论散落在 topics 下",
    2,
  );
  assert.equal(parsed.lead, "增量里出现了两簇稳定的新材料。");
  assert.deepEqual(parsed.evidence, [
    "runbooks：7 篇部署记录反复引用同一流程",
    "decisions：4 条选型结论散落在 topics 下",
  ]);

  // 只有证据行（模型没写总述）。
  assert.deepEqual(parseRationale("glossary：3 簇术语解释", 1), {
    lead: "",
    evidence: ["glossary：3 簇术语解释"],
  });
  // 没有 pack（no_change）→ 全文归总述，不伪造证据行。
  assert.deepEqual(parseRationale("没有足够证据支持新 family。", 0), {
    lead: "没有足够证据支持新 family。",
    evidence: [],
  });
  assert.deepEqual(parseRationale(null, 2), { lead: "", evidence: [] });
});

/* ---------------------------------------------------------------- 行内 diff */

test("line diff emits a single +/- stream and a stat", () => {
  const rows = lineDiff("a\nb\nc", "a\nB\nc\nd");
  assert.deepEqual(rows, [
    { type: "same", text: "a" },
    { type: "del", text: "b" },
    { type: "add", text: "B" },
    { type: "same", text: "c" },
    { type: "add", text: "d" },
  ]);
  assert.deepEqual(diffStat(rows), { adds: 2, dels: 1 });

  assert.equal(changedFileKind("", "new body"), "created");
  assert.equal(changedFileKind("old body", ""), "deleted");
  assert.equal(changedFileKind("old", "new"), "modified");
});

/* ------------------------------------------------------------- Schema 快照轴 */

test("schema axis derives stations from adopted tasks and the current skill", () => {
  const axis = buildSchemaAxis(
    [DRAFT_GLOSSARY, ADOPTED_DECISIONS, ADOPTED_RUNBOOKS, DROPPED_NO_CHANGE],
    SKILL,
  );

  assert.deepEqual(
    axis.stations.map((s) => [s.kind, s.id]),
    [
      ["base", "v3"],
      ["pack", "packs"],
      ["adopted", "evolve-0001"],
      ["adopted", "evolve-0002"],
      ["pending", "evolve-0003"],
    ],
  );
  // 基线站 = 当前模板里既非 pack 也非 evolved 的部分。
  assert.deepEqual(axis.stations[0].families, [
    "profile",
    "people",
    "topics",
    "products",
    "materials",
  ]);
  assert.deepEqual(axis.stations[1].families, ["operations"]);
  // 采纳站按时间正序，编号与时间线一致（0001 是第 1 次）。
  assert.equal(axis.stations[2].ordinal, 1);
  assert.deepEqual(axis.stations[2].liveFamilies, ["runbooks"]);
  assert.deepEqual(axis.stations[2].driftedFamilies, []);
  assert.equal(axis.stations[3].ordinal, 2);
  // 闸门上待审的 family 尚未入册。
  assert.equal(axis.stations[4].status, "draft");
  assert.deepEqual(axis.proposed, ["glossary"]);
  assert.deepEqual(axis.drifted, []);

  assert.equal(axis.baseVersion, "v3");
  assert.equal(axis.skillVersion, "v3+2");
  assert.equal(axis.contentHash, "9f1c2ab4");
});

test("schema axis attributes every current family to its origin", () => {
  const axis = buildSchemaAxis([ADOPTED_RUNBOOKS, ADOPTED_DECISIONS], SKILL);
  const byFamily = new Map(axis.families.map((f) => [f.family, f]));

  assert.equal(axis.families.length, SKILL.path_templates.length);
  assert.equal(byFamily.get("people").origin, "base");
  assert.equal(byFamily.get("people").addedByTask, null);

  assert.equal(byFamily.get("operations").origin, "pack");
  assert.equal(byFamily.get("operations").packId, "role-engineering");

  const runbooks = byFamily.get("runbooks");
  assert.equal(runbooks.origin, "evolved");
  assert.equal(runbooks.addedByTask, "evolve-0001");
  assert.equal(runbooks.addedAtOrdinal, 1);
  assert.equal(runbooks.addedAt, "2026-05-02T11:30:00Z");
  assert.equal(runbooks.area, "work");
});

test("a family an adopted task added but the skill no longer declares is marked drifted", () => {
  const skillWithoutRunbooks = {
    ...SKILL,
    path_templates: SKILL.path_templates.filter((t) => t !== "work/runbooks/{slug}.md"),
    packs: SKILL.packs.filter((p) => p.pack_id !== "evolved-runbooks"),
  };
  const axis = buildSchemaAxis([ADOPTED_RUNBOOKS, ADOPTED_DECISIONS], skillWithoutRunbooks);

  const station = axis.stations.find((s) => s.id === "evolve-0001");
  assert.deepEqual(station.driftedFamilies, ["runbooks"]);
  assert.deepEqual(station.liveFamilies, []);
  assert.deepEqual(axis.drifted, ["runbooks"]);
  assert.equal(
    axis.families.some((f) => f.family === "runbooks"),
    false,
  );
});

test("schema axis stays readable with no skill and no tasks", () => {
  const axis = buildSchemaAxis([], null);
  assert.deepEqual(
    axis.stations.map((s) => s.kind),
    ["base"],
  );
  assert.deepEqual(axis.families, []);
  assert.equal(axis.baseVersion, null);
  assert.deepEqual(axis.drifted, []);
  assert.deepEqual(axis.proposed, []);
});

test("family roster groups by archive area in a stable order", () => {
  const axis = buildSchemaAxis([ADOPTED_RUNBOOKS, ADOPTED_DECISIONS], SKILL);
  const groups = groupFamiliesByArea(axis.families);
  assert.deepEqual(
    groups.map((g) => [g.area, g.families.map((f) => f.family)]),
    [
      ["materials", ["materials"]],
      ["memory", ["decisions", "people", "profile", "topics"]],
      ["work", ["operations", "products", "runbooks"]],
    ],
  );
});
