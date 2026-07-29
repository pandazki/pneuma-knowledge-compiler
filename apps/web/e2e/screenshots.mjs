/**
 * E2E acceptance: drives every user journey of the Galley redesign in a real browser,
 * captures screenshots to docs/e2e/screenshots, records console output and mobile
 * horizontal-overflow checks. Requires:
 *   - seeded demo tenant (uv run python examples/seed_demo.py)
 *   - API on :18001 with scripted models + fake:64 embedding
 *   - vite dev on :5174 proxying to :18001 (PNEUMA_KNOWLEDGE_API_PORT=18001)
 *
 * Run: node e2e/screenshots.mjs   (from apps/web)
 * V2:  E2E_USER=<tenant> E2E_SCOPE=sources-v2 node e2e/screenshots.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  SOURCE_V2_KINDS,
  resolveE2EConfig,
  selectJourneyKeys,
} from "./screenshots-config.mjs";

const BASE = process.env.E2E_BASE ?? "http://127.0.0.1:5199";
const CONFIG = resolveE2EConfig();
const USER = CONFIG.user;
const SCOPE = CONFIG.scope;
const OUT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../docs/e2e/screenshots",
);
mkdirSync(OUT, { recursive: true });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const consoleLog = []; // {journey, type, text}
const overflowLog = []; // {journey, scrollWidth, viewportWidth, ok}
const assertionLog = []; // {journey, assertion, ok, detail?}
const sourceSelections = []; // {kind, label, title}
const journeysRun = [];
const failures = [];
const startedAt = new Date().toISOString();

let browser;
let journey = "boot";

async function newPage({ viewport = DESKTOP, theme = "light" } = {}) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  await context.addInitScript(
    ([user, theme]) => {
      localStorage.setItem("pneuma_knowledge-user", user);
      localStorage.setItem("pneuma-knowledge-theme", theme);
    },
    [USER, theme],
  );
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleLog.push({ journey, type: msg.type(), text: msg.text() });
    }
  });
  page.on("pageerror", (err) => {
    consoleLog.push({ journey, type: "pageerror", text: String(err) });
  });
  return { context, page };
}

async function go(page, hash) {
  await page.goto(`${BASE}/#${hash}`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name) });
  console.log(`shot ${name}`);
}

async function shotElement(locator, name) {
  await locator.screenshot({ path: path.join(OUT, name) });
  console.log(`shot ${name}`);
}

async function checkOverflow(page, name) {
  const { scrollWidth, viewportWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  const ok = scrollWidth <= viewportWidth;
  overflowLog.push({ journey: name, scrollWidth, viewportWidth, ok });
  if (!ok) {
    failures.push(
      `横向溢出: ${name} scrollWidth=${scrollWidth} viewportWidth=${viewportWidth}`,
    );
  }
}

async function assertVisible(locator, assertion) {
  try {
    await locator.waitFor({ state: "visible", timeout: 30000 });
    assertionLog.push({ journey, assertion, ok: true });
  } catch (error) {
    assertionLog.push({
      journey,
      assertion,
      ok: false,
      detail: error.message.split("\n")[0],
    });
    throw error;
  }
}

async function assertNonEmptyText(locator, assertion) {
  await assertVisible(locator, assertion);
  const text = (await locator.innerText()).trim();
  if (text.length === 0) {
    assertionLog.push({
      journey,
      assertion: `${assertion} has text`,
      ok: false,
      detail: "empty text",
    });
    throw new Error(`${assertion} 为空`);
  }
  assertionLog.push({
    journey,
    assertion: `${assertion} has text`,
    ok: true,
    detail: text,
  });
  return text;
}

async function assertHeatmap(page, title) {
  const heatmap = page.locator(`section[aria-label="${title}"]`);
  await assertVisible(heatmap, `${title} heatmap`);
  const activeCells = heatmap.getByRole("img");
  const activeCount = await activeCells.count();
  if (activeCount === 0) {
    assertionLog.push({
      journey,
      assertion: `${title} has active days`,
      ok: false,
      detail: "0 active cells",
    });
    throw new Error(`${title} 没有活跃日`);
  }
  assertionLog.push({
    journey,
    assertion: `${title} has active days`,
    ok: true,
    detail: `${activeCount} active cells`,
  });
  return heatmap;
}

async function step(name, fn) {
  journey = name;
  try {
    await fn();
  } catch (e) {
    failures.push(`${name}: ${e.message.split("\n")[0]}`);
    console.error(`FAIL ${name}: ${e.message.split("\n")[0]}`);
  }
}

function desktopSourceDirectory(page) {
  return page
    .locator("aside:visible")
    .filter({ has: page.getByText(/^目录 · \d+ 条$/) })
    .first();
}

async function waitForSourceDirectory(root) {
  await assertVisible(root.getByText(/^目录 · \d+ 条$/), "source directory");
  await assertVisible(root.locator("ul > li > button").first(), "source directory row");
}

async function waitForTextChange(locator, previousText) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const currentText = (await locator.innerText()).trim();
    if (currentText !== previousText) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`分页状态未变化：${previousText}`);
}

async function changeSourceDirectoryPage(root, buttonName) {
  const pagination = root.getByRole("navigation", { name: "分页" });
  const before = (await pagination.innerText()).trim();
  await root.getByRole("button", { name: buttonName }).click();
  await waitForTextChange(pagination, before);
  await assertVisible(root.locator("ul > li > button").first(), "source directory row");
}

async function resetSourceDirectory(root) {
  const previous = root.getByRole("button", { name: "上一页" });
  while (await previous.isEnabled()) {
    await changeSourceDirectoryPage(root, "上一页");
  }
}

async function selectSourceRow(page, row, expectedKind = null) {
  const button = row.getByRole("button").first();
  await button.click();
  const article = page.locator("article").filter({
    has: page.getByRole("tab", { name: "来源视图" }),
  });
  const title = await assertNonEmptyText(
    article.locator(":scope > header h2"),
    "selected source title",
  );
  if (expectedKind) {
    await assertVisible(
      article.getByText(expectedKind.label, { exact: true }).first(),
      `${expectedKind.kind} reader`,
    );
  }
  await assertVisible(
    article.getByRole("tab", { name: "来源视图" }),
    "source reader tab",
  );
  return title;
}

async function selectFirstSource(page, root) {
  await waitForSourceDirectory(root);
  return selectSourceRow(page, root.locator("ul > li").first());
}

async function selectSourceByKind(page, spec) {
  const root = desktopSourceDirectory(page);
  await waitForSourceDirectory(root);
  await resetSourceDirectory(root);

  for (let pageIndex = 0; pageIndex < 100; pageIndex += 1) {
    const rows = root.locator("ul > li");
    const rowCount = await rows.count();
    for (let index = 0; index < rowCount; index += 1) {
      const row = rows.nth(index);
      if (await row.getByText(spec.label, { exact: true }).count()) {
        return selectSourceRow(page, row, spec);
      }
    }
    const next = root.getByRole("button", { name: "下一页" });
    if (!(await next.isEnabled())) break;
    await changeSourceDirectoryPage(root, "下一页");
  }
  throw new Error(`未找到真实 ${spec.kind} source`);
}

async function toggleTheme(page) {
  await page.getByRole("button", { name: "切换主题" }).click();
  await page.waitForTimeout(200);
}

/* ---------------------------------------------------------------- journeys */

async function j00Overview() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/overview");
  await page.waitForTimeout(400);
  await shot(page, "00-overview-light.png");
  await page.getByRole("button", { name: "切换主题" }).click();
  await page.waitForTimeout(300);
  await shot(page, "00-overview-dark.png");
  await context.close();

  const m = await newPage({ viewport: MOBILE, theme: "light" });
  await go(m.page, "/overview");
  await m.page.waitForTimeout(400);
  await checkOverflow(m.page, "00-overview-mobile");
  await shot(m.page, "00-overview-mobile.png");
  await m.context.close();
}

async function j01Sources() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/sources");
  await selectFirstSource(page, desktopSourceDirectory(page));
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  await shot(page, "01-sources-light.png");
  await toggleTheme(page);
  await shot(page, "01-sources-dark.png");
  await context.close();

  const m = await newPage({ viewport: MOBILE, theme: "light" });
  await go(m.page, "/sources");
  await m.page.getByRole("button", { name: "切换来源" }).click();
  const mobileDirectory = m.page.getByRole("dialog", { name: "选择来源" });
  await selectFirstSource(m.page, mobileDirectory);
  await m.page.waitForLoadState("networkidle");
  await m.page.waitForTimeout(300);
  await checkOverflow(m.page, "01-sources-mobile");
  await shot(m.page, "01-sources-mobile.png");
  await m.context.close();
}

async function j01SourcesV2() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/sources");
  await assertVisible(
    page.getByRole("heading", { name: "原料 Sources" }),
    "Sources heading",
  );

  const heatmap = await assertHeatmap(page, "来源密度");
  await checkOverflow(page, "01-sources-v2-heatmap-light");
  await shotElement(heatmap, "01-sources-v2-heatmap-light.png");
  await toggleTheme(page);
  await checkOverflow(page, "01-sources-v2-heatmap-dark");
  await shotElement(heatmap, "01-sources-v2-heatmap-dark.png");
  await toggleTheme(page);

  for (const spec of SOURCE_V2_KINDS) {
    const title = await selectSourceByKind(page, spec);
    sourceSelections.push({
      kind: spec.kind,
      label: spec.label,
      title,
    });
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(300);
    await checkOverflow(page, `01-sources-v2-${spec.slug}-light`);
    await shot(page, `01-sources-v2-${spec.slug}-light.png`);
    await toggleTheme(page);
    await checkOverflow(page, `01-sources-v2-${spec.slug}-dark`);
    await shot(page, `01-sources-v2-${spec.slug}-dark.png`);
    await toggleTheme(page);
  }
  await context.close();
}

const INGEST_MD = `# Atlas 公开预览演示笔记（synthetic）

## 背景

这是一段用于 UI 验收的合成材料，记录 Atlas 公开预览前的准备事项，与真实业务无关。

## 待办

- 完成依赖许可证扫描
- 确认演示环境可离线运行
- 复核 README 的能力边界说明
`;

async function j02Ingest() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/ingest");
  await shot(page, "02-ingest-initial.png");
  const panel = page.locator('[role="tabpanel"][data-state="active"]');
  await panel.getByLabel("标题", { exact: true }).fill("Atlas 公开预览演示笔记");
  await panel.getByLabel("正文", { exact: true }).fill(INGEST_MD);
  await page.getByRole("button", { name: "机械预览" }).click();
  await page.getByText("归一化结果").waitFor({ timeout: 20000 });
  // 预览在首屏以下：把 §02 机械预览滚到视口顶部再截
  await page.getByText("归一化结果").evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(300);
  await shot(page, "02-ingest-preview.png");
  // 故意不点「确认导入」，保持数据集可复现。
  await context.close();
}

async function j03Profile() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/profile");
  await page.waitForTimeout(400);
  await shot(page, "03-profile-light.png");
  await context.close();
}

async function j04Process() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/process");
  await page.waitForTimeout(400);
  await shot(page, "04-process.png");
  await context.close();
}

async function j05Recall() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/recall");
  await page.getByLabel("检索查询").fill("Atlas MVP 发布门禁");
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await page.getByText(/条命中/).waitFor({ timeout: 30000 });
  await page.waitForTimeout(300);
  await shot(page, "05-recall.png");
  await context.close();
}

async function j06Ask() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/ask");
  await page.getByLabel(/scope\.query/).fill("Atlas MVP 发布门禁");
  await page.getByRole("button", { name: "构建 Briefing" }).click();
  await page.getByLabel("提问").waitFor({ timeout: 30000 });
  // scripted recall-script.json turn 0 / turn 1 的答案文本
  await page.getByLabel("提问").fill("Atlas 发布前必须满足哪些门禁？");
  await page.getByRole("button", { name: "提问", exact: true }).click();
  await page.getByText(/Atlas 的首版范围是来源导入/).waitFor({ timeout: 30000 });
  await page.getByLabel("提问").fill("混合检索实验的结论是什么？");
  await page.getByRole("button", { name: "提问", exact: true }).click();
  await page.getByText(/证据显示发布门禁包含离线演示/).waitFor({ timeout: 30000 });
  await page.waitForTimeout(400);
  await shot(page, "06-ask.png");
  await context.close();
}

async function j07ContextSuggestion() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/live_context");
  await page.waitForTimeout(400);
  await shot(page, "07-live-context-initial.png");

  // 两轮转录：本人同步 Atlas 发布进度，协作者追问门禁。
  await page.getByRole("button", { name: "追加一轮" }).click();
  await page.getByRole("button", { name: "追加一轮" }).click();
  const speakers = page.getByLabel("说话人", { exact: true });
  const texts = page.getByLabel("转录文本", { exact: true });
  await speakers.nth(0).fill("林知远");
  await texts.nth(0).fill("我在整理 Atlas 的公开发布清单，同步一下发布进度。");
  await speakers.nth(1).fill("协作者");
  await texts.nth(1).fill("依赖的许可证兼容性需要怎么确认？发布门禁还差哪几项？");
  // role：第一轮本人、第二轮参与者
  const roles = page.getByLabel("角色", { exact: true });
  await roles.nth(0).click();
  await page.getByRole("option", { name: "本人" }).click();
  await roles.nth(1).click();
  await page.getByRole("option", { name: "参与者" }).click();

  // focus：选词表第一项
  await page.getByLabel(/focus（注意力指向）/).click();
  await page.getByRole("option").first().click();

  // min_confidence 服务端闸门 1 → 5（点 track 粗调 + 方向键微调；
  // 让 confidence 3 的卡进 low_confidence 账）
  const slider = page.getByRole("slider").first();
  const box = await slider.locator("xpath=..").boundingBox();
  await page.mouse.click(box.x + box.width * (4 / 9), box.y + box.height / 2);
  await slider.focus();
  for (let i = 0; i < 12; i++) {
    const v = Number(await slider.getAttribute("aria-valuenow"));
    if (v === 5) break;
    await page.keyboard.press(v < 5 ? "ArrowRight" : "ArrowLeft");
  }
  const finalVal = await slider.getAttribute("aria-valuenow");
  if (finalVal !== "5") throw new Error(`min_confidence 未调到 5（当前 ${finalVal}）`);

  await page.getByRole("button", { name: "送整段评估一次" }).click();
  await page.getByText(/存活卡片（[1-9]/).waitFor({ timeout: 30000 });
  // 存活卡片 + GateLedger 门禁账在首屏以下，滚过去再截
  await page.getByLabel("门禁计数").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await shot(page, "07-live-context-gated.png");
  await context.close();
}

async function j08Library() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/library");
  await page.getByRole("button", { name: "atlas", exact: true }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  await shot(page, "08-library.png");
  await context.close();
}

async function j09Graph() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/graph");
  await page.locator(".react-flow__node").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(800); // dagre 布局稳定
  await page.locator(".react-flow__node", { hasText: "atlas" }).first().click();
  await page.waitForTimeout(400);
  await shot(page, "09-graph-selected.png");
  await context.close();
}

async function j10History() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/history");
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /处变更/ }).first().click();
  await page.waitForTimeout(400);
  await shot(page, "10-history.png");
  await context.close();
}

async function j10HistoryV2() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/history");
  await assertVisible(
    page.getByRole("heading", { name: "版本 History" }),
    "History heading",
  );

  const heatmap = await assertHeatmap(page, "版本编译密度");
  await checkOverflow(page, "10-history-v2-heatmap-light");
  await shotElement(heatmap, "10-history-v2-heatmap-light.png");
  await toggleTheme(page);
  await checkOverflow(page, "10-history-v2-heatmap-dark");
  await shotElement(heatmap, "10-history-v2-heatmap-dark.png");
  await toggleTheme(page);

  const firstTimelineRow = page.locator("ol > li > button").first();
  await assertVisible(firstTimelineRow, "History timeline row");
  await firstTimelineRow.click();
  await assertVisible(
    page.locator('ol > li > button[aria-current="true"]').first(),
    "selected History timeline row",
  );
  await page.waitForTimeout(300);
  await checkOverflow(page, "10-history-v2-light");
  await shot(page, "10-history-v2-light.png");
  await toggleTheme(page);
  await checkOverflow(page, "10-history-v2-dark");
  await shot(page, "10-history-v2-dark.png");
  await context.close();
}

async function j11Evolve() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/evolve");
  await page.waitForTimeout(500);
  await shot(page, "11-evolve.png");
  await context.close();
}

async function j12Snapshot() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/library");
  await page.getByRole("button", { name: "atlas", exact: true }).click();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "切换到历史快照" }).click();
  await page.getByRole("option").nth(1).click(); // 第一个历史快照（HEAD 之后）
  await page.getByText("历史快照 · 只读").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(400);
  await shot(page, "12-snapshot-readonly.png");
  await context.close();
}

async function j13Components() {
  const { context, page } = await newPage({ theme: "light" });
  await go(page, "/components");
  await page.waitForTimeout(400);
  await page.screenshot({
    path: path.join(OUT, "13-components.png"),
    fullPage: true,
  });
  console.log("shot 13-components.png");
  await context.close();
}

async function j14GraphMobile() {
  const m = await newPage({ viewport: MOBILE, theme: "light" });
  await go(m.page, "/graph");
  await m.page.locator(".react-flow__node").first().waitFor({ timeout: 30000 });
  await m.page.waitForTimeout(800);
  await m.page.locator(".react-flow__node").first().click();
  await m.page.waitForTimeout(400);
  await checkOverflow(m.page, "14-graph-mobile");
  await shot(m.page, "14-graph-mobile.png");
  await m.context.close();
}

/* ------------------------------------------------------------------- main */

async function main() {
  const ALL = {
    "00": ["00-overview", j00Overview],
    "01":
      SCOPE === "sources-v2"
        ? ["01-sources-v2", j01SourcesV2]
        : ["01-sources", j01Sources],
    "02": ["02-ingest", j02Ingest],
    "03": ["03-profile", j03Profile],
    "04": ["04-process", j04Process],
    "05": ["05-recall", j05Recall],
    "06": ["06-ask", j06Ask],
    "07": ["07-live-context", j07ContextSuggestion],
    "08": ["08-library", j08Library],
    "09": ["09-graph", j09Graph],
    "10":
      SCOPE === "sources-v2"
        ? ["10-history-v2", j10HistoryV2]
        : ["10-history", j10History],
    "11": ["11-evolve", j11Evolve],
    "12": ["12-snapshot", j12Snapshot],
    "13": ["13-components", j13Components],
    "14": ["14-graph-mobile", j14GraphMobile],
  };
  const selectedKeys = selectJourneyKeys(Object.keys(ALL), {
    scope: SCOPE,
    requested: process.argv.slice(2),
  });
  console.log(
    `e2e scope=${SCOPE} user=${USER} journeys=${selectedKeys.join(",")}`,
  );

  try {
    browser = await chromium.launch({ channel: "chrome" });
    console.log("browser: channel chrome");
  } catch {
    browser = await chromium.launch();
    console.log("browser: bundled chromium");
  }

  for (const key of selectedKeys) {
    const [name, fn] = ALL[key];
    journeysRun.push({ key, name });
    await step(name, fn);
  }

  await browser.close();

  if (consoleLog.length > 0) {
    failures.push(`console error/warning/pageerror: ${consoleLog.length}`);
  }
  if (SCOPE === "sources-v2" && selectedKeys.includes("01")) {
    const selectedKinds = new Set(sourceSelections.map(({ kind }) => kind));
    const missingKinds = SOURCE_V2_KINDS
      .map(({ kind }) => kind)
      .filter((kind) => !selectedKinds.has(kind));
    if (missingKinds.length > 0) {
      failures.push(`缺少真实 source family: ${missingKinds.join(", ")}`);
    }
  }

  const report = {
    run: {
      scope: SCOPE,
      user: USER,
      base: BASE,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      journeys: journeysRun,
      source_selections: sourceSelections,
    },
    assertions: assertionLog,
    consoleLog,
    overflowLog,
    failures,
  };
  writeFileSync(
    path.join(OUT, "e2e-run-log.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(`\nconsole entries: ${consoleLog.length}`);
  for (const c of consoleLog) console.log(`  [${c.type}] (${c.journey}) ${c.text.slice(0, 200)}`);
  console.log(`overflow: ${overflowLog.map((o) => `${o.journey}=${o.scrollWidth}`).join(" ")}`);
  console.log(`failures: ${failures.length}`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(failures.length ? 1 : 0);
}

main();
