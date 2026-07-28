/**
 * E2E acceptance: drives every user journey of the Galley redesign in a real browser,
 * captures screenshots to docs/e2e/screenshots, records console output and mobile
 * horizontal-overflow checks. Requires:
 *   - seeded demo tenant (uv run python examples/seed_demo.py)
 *   - API on :18001 with scripted models + fake:64 embedding
 *   - vite dev on :5174 proxying to :18001 (PNEUMA_KNOWLEDGE_API_PORT=18001)
 *
 * Run: node e2e/screenshots.mjs   (from apps/web)
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const BASE = process.env.E2E_BASE ?? "http://127.0.0.1:5199";
const USER = "u-opc-lin";
const OUT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../docs/e2e/screenshots",
);
mkdirSync(OUT, { recursive: true });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const consoleLog = []; // {journey, type, text}
const overflowLog = []; // {journey, scrollWidth, ok}
const failures = [];

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

async function checkOverflow(page, name) {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const ok = scrollWidth <= 390;
  overflowLog.push({ journey: name, scrollWidth, ok });
  if (!ok) failures.push(`横向溢出: ${name} scrollWidth=${scrollWidth}`);
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
  await page.getByRole("button", { name: /Atlas MVP 决策记录/ }).first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  await shot(page, "01-sources-light.png");
  await page.getByRole("button", { name: "切换主题" }).click();
  await page.waitForTimeout(300);
  await shot(page, "01-sources-dark.png");
  await context.close();

  const m = await newPage({ viewport: MOBILE, theme: "light" });
  await go(m.page, "/sources");
  await m.page.getByRole("button", { name: /Atlas MVP 决策记录/ }).first().click();
  await m.page.waitForLoadState("networkidle");
  await m.page.waitForTimeout(300);
  await checkOverflow(m.page, "01-sources-mobile");
  await shot(m.page, "01-sources-mobile.png");
  await m.context.close();
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
  try {
    browser = await chromium.launch({ channel: "chrome" });
    console.log("browser: channel chrome");
  } catch {
    browser = await chromium.launch();
    console.log("browser: bundled chromium");
  }

  const ALL = {
    "00": ["00-overview", j00Overview],
    "01": ["01-sources", j01Sources],
    "02": ["02-ingest", j02Ingest],
    "03": ["03-profile", j03Profile],
    "04": ["04-process", j04Process],
    "05": ["05-recall", j05Recall],
    "06": ["06-ask", j06Ask],
    "07": ["07-live-context", j07ContextSuggestion],
    "08": ["08-library", j08Library],
    "09": ["09-graph", j09Graph],
    "10": ["10-history", j10History],
    "11": ["11-evolve", j11Evolve],
    "12": ["12-snapshot", j12Snapshot],
    "13": ["13-components", j13Components],
    "14": ["14-graph-mobile", j14GraphMobile],
  };
  const only = process.argv.slice(2);
  for (const [key, [name, fn]] of Object.entries(ALL)) {
    if (only.length > 0 && !only.includes(key)) continue;
    await step(name, fn);
  }

  await browser.close();

  const report = { consoleLog, overflowLog, failures };
  writeFileSync(
    path.join(OUT, "e2e-run-log.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(`\nconsole entries: ${consoleLog.length}`);
  for (const c of consoleLog) console.log(`  [${c.type}] (${c.journey}) ${c.text.slice(0, 200)}`);
  console.log(`overflow: ${overflowLog.map((o) => `${o.journey}=${o.scrollWidth}`).join(" ")}`);
  console.log(`failures: ${failures.length}`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(failures.length || consoleLog.some((c) => c.type !== "warning") ? 1 : 0);
}

main();
