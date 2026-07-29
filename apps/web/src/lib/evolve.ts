/**
 * Evolve 派生逻辑（纯函数）——演化时间线、任务详情、Schema 快照轴三个面共用的
 * 数据变换。视图只做呈现，判断与推导全在这里，因此可以用 node --test 直接覆盖。
 *
 * 数据面只有两个端点（不新增持久化）：
 *   `GET /v1/users/{u}/evolve`（任务摘要列表）与 `GET /v1/users/{u}/skill`（当前 skill）。
 * Schema 快照轴不是另一份存储，而是「已采纳任务序列 × 当前 skill」的推导结果；
 * 推导不出来的部分（例如某次 adopted 加入的 family 已不在当前 skill 里）如实标为
 * 漂移，不补造、不静默吞掉。
 *
 * 所有 import 必须是 `import type`：测试把本文件单独 esbuild 成一个 data: URL 模块，
 * 任何运行期 import 都无法解析。
 */
import type {
  EvolveStatus,
  EvolveSummary,
  EvolveTaskSummary,
  SkillInfo,
  SkillPack,
} from "./api";

/* ------------------------------------------------------------------ 状态语义 */

/** 终态：不再变化，无需轮询。 */
const TERMINAL_STATUSES: readonly string[] = [
  "adopted",
  "dropped",
  "expired",
  "aborted",
  "no_change",
];

export const EVOLVE_STATUS_LABEL: Record<string, string> = {
  draft: "草案待审",
  adopted: "已采用",
  dropped: "已放弃",
  expired: "已过期",
  aborted: "已中止",
  no_change: "无变化",
};

export type EvolveStatusTone = "neutral" | "accent" | "ok" | "warn" | "danger";

/** 语义色只给真实状态（DESIGN.md §6.4）：待审=warn、已采用=ok、中止=danger、其余中性。 */
export function evolveStatusTone(status: string): EvolveStatusTone {
  switch (status) {
    case "draft":
      return "warn";
    case "adopted":
      return "ok";
    case "aborted":
      return "danger";
    default:
      return "neutral";
  }
}

export function evolveStatusLabel(status: string): string {
  return EVOLVE_STATUS_LABEL[status] ?? status;
}

export function isTerminalEvolveStatus(status: string): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/**
 * draft 评审窗口剩余毫秒（created_at + TTL − now）。纯 advisory：服务端的惰性过期
 * 扫描才是权威。`null` 表示无从推算（缺 created_at 或时间戳不可解析）。
 */
export function ttlRemainingMs(
  createdAt: string | null | undefined,
  ttlHours: number,
  now: number = Date.now(),
): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt).getTime();
  if (Number.isNaN(created)) return null;
  return created + ttlHours * 3600_000 - now;
}

export function fmtTtlRemaining(ms: number): string {
  if (ms <= 0) return "已超评审窗口";
  const h = Math.floor(ms / 3600_000);
  const m = Math.floor((ms % 3600_000) / 60_000);
  return h > 0 ? `剩约 ${h}h${m}m` : `剩约 ${m}m`;
}

/* ------------------------------------------------------------- 路径模板 → family */

/**
 * 归档 family 名：路径模板里最后一个非占位段。
 * `memory/people/{slug}.md` → `people`；`memory/profile.md` → `profile`；
 * `materials/{slug}.md` → `materials`。取不出来时回落整条模板（不猜）。
 */
export function familyFromTemplate(template: string): string {
  const segs = template
    .split("/")
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.includes("{slug}"));
  const last = segs[segs.length - 1];
  if (!last) return template.trim();
  return last.replace(/\.md$/i, "");
}

/** 归档区：模板的第一段（`memory` / `work` / `materials` / pack 自带的新顶层目录）。 */
export function areaFromTemplate(template: string): string {
  const first = template.split("/")[0]?.trim();
  return first && !first.includes("{slug}") ? first.replace(/\.md$/i, "") : "—";
}

/* ------------------------------------------------------------------- 时间线 */

export interface EvolveScale {
  newDocuments: number;
  movedClaims: number;
  mergedClaims: number;
  /** 收编了 claim 的文档数（summary.adopted_by_document 的键数）。 */
  adoptedDocuments: number;
  /** 规模合计：搬移 + 合并（"这次动了多少条"的一个数）。 */
  touchedClaims: number;
}

export const EMPTY_SCALE: EvolveScale = {
  newDocuments: 0,
  movedClaims: 0,
  mergedClaims: 0,
  adoptedDocuments: 0,
  touchedClaims: 0,
};

function int(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** 机械规模摘要（缺 summary 的任务给全零，不伪造）。 */
export function evolveScale(summary: EvolveSummary | null | undefined): EvolveScale {
  if (!summary) return { ...EMPTY_SCALE };
  const moved = int(summary.moved_claims);
  const merged = int(summary.merged_claims);
  return {
    newDocuments: int(summary.new_documents),
    movedClaims: moved,
    mergedClaims: merged,
    adoptedDocuments: Object.keys(summary.adopted_by_document ?? {}).length,
    touchedClaims: moved + merged,
  };
}

export interface EvolveTimelineEntry {
  task: EvolveTaskSummary;
  taskId: string;
  status: EvolveStatus;
  /** 时间正序序号（最早 = 1）：「第 n 次演化」。 */
  ordinal: number;
  createdAt: string | null;
  decidedAt: string | null;
  /** 排序用 epoch ms；时间戳缺失/不可解析时为 null（这些条目排在末尾）。 */
  sortKey: number | null;
  /** 本次提案新增的归档 family 名。 */
  families: string[];
  /** 本次提案新增的路径模板。 */
  pathTemplates: string[];
  scale: EvolveScale;
  /** 非终态：还在跑，或停在闸门上等人。 */
  pending: boolean;
  /** 停在闸门上等人裁决（可 adopt / drop）。 */
  awaitingReview: boolean;
}

/**
 * 提案新增的 family 名。优先用服务端派生字段 `families`；老服务端没有这个字段时，
 * 从 `path_templates` 反推；两者都没有就是空（渐进降级，不猜）。
 */
export function proposedFamilies(task: EvolveTaskSummary): string[] {
  const declared = Array.isArray(task.families) ? task.families : null;
  if (declared && declared.length > 0) {
    return dedupe(declared.map((f) => String(f).trim()).filter(Boolean));
  }
  return dedupe(proposedTemplates(task).map(familyFromTemplate));
}

export function proposedTemplates(task: EvolveTaskSummary): string[] {
  const declared = Array.isArray(task.path_templates) ? task.path_templates : null;
  if (!declared) return [];
  return dedupe(declared.map((t) => String(t).trim()).filter(Boolean));
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    if (v && !seen.has(v)) {
      seen.add(v);
      out.push(v);
    }
  }
  return out;
}

function epoch(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = new Date(ts).getTime();
  return Number.isNaN(ms) ? null : ms;
}

/**
 * 任务摘要 → 时间线条目，**最新在前**（服务端已是 created_at DESC，这里仍显式排序，
 * 顺序不依赖端点实现）。`ordinal` 按时间正序编号，所以同一次演化在时间线与快照轴上
 * 是同一个编号。时间戳缺失的条目排在最后，并拿到最大的 ordinal（不假装它们最早）。
 */
export function buildEvolveTimeline(
  tasks: readonly EvolveTaskSummary[],
): EvolveTimelineEntry[] {
  const rows = tasks.map((task) => ({
    task,
    sortKey: epoch(task.created_at),
  }));
  // 时间正序（无时间戳垫底），再按 task_id 定序，保证渲染稳定。
  const ascending = [...rows].sort((a, b) => {
    if (a.sortKey == null && b.sortKey == null)
      return a.task.task_id.localeCompare(b.task.task_id);
    if (a.sortKey == null) return 1;
    if (b.sortKey == null) return -1;
    if (a.sortKey !== b.sortKey) return a.sortKey - b.sortKey;
    return a.task.task_id.localeCompare(b.task.task_id);
  });

  const entries = ascending.map((row, index): EvolveTimelineEntry => {
    const status = row.task.status;
    return {
      task: row.task,
      taskId: row.task.task_id,
      status,
      ordinal: index + 1,
      createdAt: row.task.created_at ?? null,
      decidedAt: row.task.decided_at ?? null,
      sortKey: row.sortKey,
      families: proposedFamilies(row.task),
      pathTemplates: proposedTemplates(row.task),
      scale: evolveScale(row.task.summary),
      pending: !isTerminalEvolveStatus(status),
      awaitingReview: status === "draft",
    };
  });

  return entries.reverse();
}

export interface EvolveTimelineCounts {
  total: number;
  awaitingReview: number;
  adopted: number;
  /** 放弃 + 过期 + 中止：人或系统否决掉的。 */
  declined: number;
  noChange: number;
}

export function evolveTimelineCounts(
  entries: readonly EvolveTimelineEntry[],
): EvolveTimelineCounts {
  let awaitingReview = 0;
  let adopted = 0;
  let declined = 0;
  let noChange = 0;
  for (const e of entries) {
    if (e.awaitingReview) awaitingReview += 1;
    else if (e.status === "adopted") adopted += 1;
    else if (e.status === "no_change") noChange += 1;
    else if (e.status === "dropped" || e.status === "expired" || e.status === "aborted")
      declined += 1;
  }
  return { total: entries.length, awaitingReview, adopted, declined, noChange };
}

/** 选中态解析：选中 id 不在当前列表里就落回 null（不指向不存在的任务）。 */
export function selectedTimelineEntry(
  entries: readonly EvolveTimelineEntry[],
  taskId: string | null | undefined,
): EvolveTimelineEntry | null {
  if (!taskId) return null;
  return entries.find((e) => e.taskId === taskId) ?? null;
}

/* --------------------------------------------------------------- pack 草案 */

export interface EvolvePackDraft {
  packId: string | null;
  /** family 名：pack_id 去掉 `evolved-` 前缀，取不到就从模板反推。 */
  family: string;
  origin: string | null;
  /** pack 追加的 instructions 全文（人审的正文）。 */
  instructions: string;
  pathTemplates: string[];
  contractRules: string[];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => str(v).trim()).filter(Boolean);
}

/**
 * 存下来的 proposal（`EvolveProposal.model_dump()`：`{packs, rationale}`）→ pack 草案列表。
 * 对形状宽容：坏结构降级为空列表，绝不抛。
 */
export function buildPackDrafts(
  proposal: Record<string, unknown> | null | undefined,
): EvolvePackDraft[] {
  if (!proposal || typeof proposal !== "object") return [];
  const packs = (proposal as { packs?: unknown }).packs;
  if (!Array.isArray(packs)) return [];
  return packs
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
    .map((p) => {
      const packId = str(p.pack_id).trim() || null;
      const templates = strList(p.extra_path_templates);
      const fromId = packId ? packId.replace(/^evolved-/, "") : "";
      return {
        packId,
        family: fromId || (templates[0] ? familyFromTemplate(templates[0]) : "—"),
        origin: str(p.origin).trim() || null,
        instructions: str(p.extra_instructions).trim(),
        pathTemplates: templates,
        contractRules: strList(p.extra_contract_rules),
      };
    });
}

export interface EvolveRationale {
  /** 提案自述（强模型给的总体理由）。 */
  lead: string;
  /** 证据行：phase 1 每个 family 追加一行指向增量里的具体聚簇。 */
  evidence: string[];
}

/**
 * 拆开 rationale 文本块。propose.py 的组装方式是
 * `rationale + "\n\n" + 每个 family 一行 evidence`，所以末尾至多 `packCount` 行
 * 非空行是证据行，其余归总体理由。切不准也不丢内容：两半都会渲染。
 */
export function parseRationale(
  rationale: string | null | undefined,
  packCount: number,
): EvolveRationale {
  const lines = str(rationale)
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length === 0) return { lead: "", evidence: [] };
  if (packCount <= 0) return { lead: lines.join("\n"), evidence: [] };
  const take = Math.min(packCount, lines.length);
  const evidence = lines.slice(lines.length - take);
  const lead = lines.slice(0, lines.length - take).join("\n");
  return { lead, evidence };
}

/* --------------------------------------------------------------- 行内 diff */

export type DiffRowType = "same" | "add" | "del";
export interface DiffRow {
  type: DiffRowType;
  text: string;
}

/** 最小 LCS 行 diff：输出统一 +/− 行流（墨阶呈现，禁彩色 diff）。 */
export function lineDiff(oldStr: string, newStr: string): DiffRow[] {
  const A = oldStr.split("\n");
  const B = newStr.split("\n");
  const n = A.length;
  const m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      rows.push({ type: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "del", text: A[i++] });
    } else {
      rows.push({ type: "add", text: B[j++] });
    }
  }
  while (i < n) rows.push({ type: "del", text: A[i++] });
  while (j < m) rows.push({ type: "add", text: B[j++] });
  return rows;
}

export interface DiffStat {
  adds: number;
  dels: number;
}

export function diffStat(rows: readonly DiffRow[]): DiffStat {
  let adds = 0;
  let dels = 0;
  for (const r of rows) {
    if (r.type === "add") adds += 1;
    else if (r.type === "del") dels += 1;
  }
  return { adds, dels };
}

/** 文件级变更种类（old/new 空串即新建/删除，服务端就是这么表达的）。 */
export type ChangedFileKind = "created" | "deleted" | "modified";

export function changedFileKind(oldBody: string, newBody: string): ChangedFileKind {
  if (oldBody === "" && newBody !== "") return "created";
  if (newBody === "" && oldBody !== "") return "deleted";
  return "modified";
}

/* ------------------------------------------------------------- Schema 快照轴 */

export type FamilyOrigin = "base" | "pack" | "evolved";

export interface SchemaFamily {
  family: string;
  area: string;
  template: string;
  origin: FamilyOrigin;
  /** 哪次已采纳的演化加入了它（origin === "evolved" 时才可能有）。 */
  addedByTask: string | null;
  addedAtOrdinal: number | null;
  addedAt: string | null;
  /** 注册期 pack 带来的（matrix / derived）。 */
  packId: string | null;
}

export type SchemaStationKind = "base" | "pack" | "adopted" | "pending";

export interface SchemaStation {
  kind: SchemaStationKind;
  /** base → base_version；pack → "packs"；adopted / pending → task_id。 */
  id: string;
  label: string;
  /** 与时间线共享的编号；base / pack 站为 null。 */
  ordinal: number | null;
  at: string | null;
  families: string[];
  templates: string[];
  /** adopted 站：仍在当前 skill 里的 family。 */
  liveFamilies: string[];
  /** adopted 站：当前 skill 里已找不到的 family（如实呈现漂移）。 */
  driftedFamilies: string[];
  status: EvolveStatus | null;
}

export interface SchemaAxis {
  stations: SchemaStation[];
  /** 当前全量 family 一览（当前 skill 的 path_templates 逐条解析）。 */
  families: SchemaFamily[];
  baseVersion: string | null;
  skillVersion: string | null;
  contentHash: string | null;
  /** 已采纳过、但当前 skill 里已不见的 family。 */
  drifted: string[];
  /** 还停在闸门上、尚未进入 schema 的 family。 */
  proposed: string[];
}

function packTemplates(packs: readonly SkillPack[], evolved: boolean): Map<string, string> {
  const out = new Map<string, string>();
  for (const pack of packs) {
    const isEvolved = pack.origin === "evolved";
    if (isEvolved !== evolved) continue;
    for (const template of pack.extra_path_templates ?? []) {
      const t = String(template).trim();
      if (t) out.set(t, pack.pack_id ?? "");
    }
  }
  return out;
}

/**
 * 「已采纳任务序列 × 当前 skill」→ Schema 快照轴。
 *
 * - 站点顺序：基线 skill → 注册期 pack（有才出现）→ 每次 adopted 演化（时间正序）
 *   → 闸门上待审的 draft（尚未进入 schema，单独标出）。
 * - family 一览完全由当前 skill 的 path_templates 推出，来源归因（base / pack /
 *   evolved + 哪次任务）由模板集合比对得到。
 * - adopted 站宣称过、但当前 skill 里查不到的 family 记为漂移，不静默丢弃。
 */
export function buildSchemaAxis(
  tasks: readonly EvolveTaskSummary[],
  skill: SkillInfo | null | undefined,
): SchemaAxis {
  const entries = buildEvolveTimeline(tasks);
  const chronological = [...entries].reverse(); // 时间正序

  const skillTemplates = dedupe((skill?.path_templates ?? []).map((t) => String(t).trim()));
  const packs = skill?.packs ?? [];
  const evolvedTemplates = packTemplates(packs, true);
  const registrationTemplates = packTemplates(packs, false);

  /** family → 当前 skill 里承载它的模板。 */
  const currentByFamily = new Map<string, string>();
  for (const template of skillTemplates) {
    const family = familyFromTemplate(template);
    if (!currentByFamily.has(family)) currentByFamily.set(family, template);
  }

  const adopted = chronological.filter((e) => e.status === "adopted");
  const awaiting = chronological.filter((e) => e.awaitingReview);

  /** family → 加入它的那次 adopted 演化（后来的覆盖先前的）。 */
  const addedBy = new Map<string, EvolveTimelineEntry>();
  for (const entry of adopted) {
    for (const family of entry.families) addedBy.set(family, entry);
  }

  const families: SchemaFamily[] = skillTemplates.map((template) => {
    const family = familyFromTemplate(template);
    const origin: FamilyOrigin = evolvedTemplates.has(template)
      ? "evolved"
      : registrationTemplates.has(template)
        ? "pack"
        : "base";
    const owner = origin === "evolved" ? (addedBy.get(family) ?? null) : null;
    return {
      family,
      area: areaFromTemplate(template),
      template,
      origin,
      addedByTask: owner?.taskId ?? null,
      addedAtOrdinal: owner?.ordinal ?? null,
      addedAt: owner?.decidedAt ?? owner?.createdAt ?? null,
      packId:
        origin === "pack"
          ? registrationTemplates.get(template) || null
          : origin === "evolved"
            ? evolvedTemplates.get(template) || null
            : null,
    };
  });

  const stations: SchemaStation[] = [];

  const baseTemplates = families
    .filter((f) => f.origin === "base")
    .map((f) => f.template);
  stations.push({
    kind: "base",
    id: skill?.base_version ?? "base",
    label: skill?.base_version ? `基线 skill ${skill.base_version}` : "基线 skill",
    ordinal: null,
    at: null,
    families: dedupe(families.filter((f) => f.origin === "base").map((f) => f.family)),
    templates: baseTemplates,
    liveFamilies: [],
    driftedFamilies: [],
    status: null,
  });

  const packFamilies = families.filter((f) => f.origin === "pack");
  if (packFamilies.length > 0) {
    stations.push({
      kind: "pack",
      id: "packs",
      label: "注册期定制 pack",
      ordinal: null,
      at: null,
      families: dedupe(packFamilies.map((f) => f.family)),
      templates: packFamilies.map((f) => f.template),
      liveFamilies: [],
      driftedFamilies: [],
      status: null,
    });
  }

  const drifted: string[] = [];
  for (const entry of adopted) {
    const live = entry.families.filter((f) => currentByFamily.has(f));
    const gone = entry.families.filter((f) => !currentByFamily.has(f));
    for (const f of gone) if (!drifted.includes(f)) drifted.push(f);
    stations.push({
      kind: "adopted",
      id: entry.taskId,
      label: `第 ${entry.ordinal} 次演化`,
      ordinal: entry.ordinal,
      at: entry.decidedAt ?? entry.createdAt,
      families: entry.families,
      templates: entry.pathTemplates,
      liveFamilies: live,
      driftedFamilies: gone,
      status: entry.status,
    });
  }

  const proposed: string[] = [];
  for (const entry of awaiting) {
    for (const f of entry.families) if (!proposed.includes(f)) proposed.push(f);
    stations.push({
      kind: "pending",
      id: entry.taskId,
      label: `第 ${entry.ordinal} 次演化 · 闸门待审`,
      ordinal: entry.ordinal,
      at: entry.createdAt,
      families: entry.families,
      templates: entry.pathTemplates,
      liveFamilies: [],
      driftedFamilies: [],
      status: entry.status,
    });
  }

  return {
    stations,
    families,
    baseVersion: skill?.base_version ?? null,
    skillVersion: skill?.version ?? null,
    contentHash: skill?.content_hash ?? null,
    drifted,
    proposed,
  };
}

/** family 一览按归档区分组（呈现用；区内按 family 名定序）。 */
export function groupFamiliesByArea(
  families: readonly SchemaFamily[],
): { area: string; families: SchemaFamily[] }[] {
  const byArea = new Map<string, SchemaFamily[]>();
  for (const family of families) {
    const bucket = byArea.get(family.area);
    if (bucket) bucket.push(family);
    else byArea.set(family.area, [family]);
  }
  return [...byArea.entries()]
    .map(([area, list]) => ({
      area,
      families: [...list].sort((a, b) => a.family.localeCompare(b.family)),
    }))
    .sort((a, b) => a.area.localeCompare(b.area));
}
