# Pneuma Knowledge Compiler · E2E 验收报告（Galley 重设计）

验收日期：2026-07-28
设计权威：根目录 `DESIGN.md`（2026-07 blank-slate 重设计，方向 A「校样 Galley」）
租户：`u-opc-lin`（`examples/seed_demo.py` 生成的 synthetic 中文 OPC 人设）

## 结论

**通过。** 全部 15 个旅程在真实浏览器（Google Chrome）中跑通并逐张人工审图；
浏览器 console 0 error / 0 warning；390px 视口无横向溢出；静态扫描（原生控件 /
hex 字面值 / 开源卫生 / git whitespace）全部干净；后端全套 pytest 453 通过；
`pnpm build` 绿。验收过程中修复 3 个真实 bug（见「修复清单」）。

## 环境

- 中间件：`infra/docker-compose.yml`（Postgres / Qdrant / Meilisearch 容器）。
- API：`scripts/dev-api.sh`，`127.0.0.1:18001`（uvicorn --reload），环境变量：
  - `PNEUMA_KNOWLEDGE_EMBEDDING_MODEL=fake:64`（与 seed 的 L2 向量维度一致）
  - `PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL=scripted:examples/data/opc-demo/recall-script.json`
  - `PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP=scripted:…/recall-script.json`
  - `PNEUMA_KNOWLEDGE_LLM_MODEL_LIVE_CONTEXT=scripted:examples/data/opc-demo/live-context-script.json`
  - `NO_PROXY=localhost,127.0.0.1`（本机有系统代理；不设则 httpx 把 localhost
    送进代理，Qdrant 返回 503——即 `examples/_bootstrap.py` 记录的同一个陷阱）
  - 注意：`llm_model` 基座一旦是 `scripted:` 会按 `wiring.resolve_model_name`
    覆盖所有角色路由，因此 suggestion 必须走 per-role env（`LLM_MODEL_LIVE_CONTEXT`）注入。
- Web：`cd apps/web && PNEUMA_KNOWLEDGE_API_PORT=18001 pnpm dev`，
  `127.0.0.1:5199`（本机 5173/5174/18000 被其他工作区的 dev server 占用）。
- 浏览器：Google Chrome（Playwright `channel: "chrome"`），桌面 1440×900、
  移动 390×844，deviceScaleFactor 2。主题经 UI「切换主题」按钮（即
  localStorage `pneuma-knowledge-theme`）切换。
- 驱动脚本：`apps/web/e2e/screenshots.mjs`（Playwright，可用
  `node e2e/screenshots.mjs [旅程编号…]` 全量或按号重跑；运行日志落在
  `docs/e2e/screenshots/e2e-run-log.json`）。

## 数据流水

`uv run python examples/seed_demo.py`（重置租户后完整跑真四层流水）：

```
ingest 2767ddce  Atlas MVP 决策记录
ingest 2565da6c  混合检索实验复盘
ingest ee5add10  一人公司发布检查
pipeline sources=3 jobs=6 docs=3 claims=9 snapshots=3
```

即 L0 3 条 source（各 3 blocks）、index+compile 共 6 个 job、L3 canonical
3 篇文档 / 9 条 claim / 3 个 Git 快照。ingest 旅程只做「机械预览」不确认导入，
数据集保持可复现。

## 旅程验收表

| # | 旅程 | 验收点 | 结果 |
|---|---|---|---|
| 00 | 卷首 Overview | serif 题字、编者说明、§1–§4 标尺线流程图（实时计数 3 source / 6 job / 12 文档+claim / 快照）、L0–L3 DefinitionList、翻阅指引、synthetic 披露；light/dark 双主题；390px 流程图纵排、无溢出 | ✅ |
| 01 | 原料 Sources | 选中「Atlas MVP 决策记录」：结构地图（b0–b2）、原文 blocks（mono 块号 + serif 正文 + 说话人）、编译计划双栏；light/dark/390px | ✅ |
| 02 | 导入 Ingest | 四类 official source（会议 / 文档库 / IM / 邮件）均可选择、载入 JSON、schema 预检并导入；保留单篇文档入口 | ✅ |
| 03 | 画像 Profile | u-opc-lin 中文 OPC 人设：avatar 字标、SYNTHETIC Stamp、核心字段定义表（行业/角色/资历/兴趣/工作台/偏好） | ✅ |
| 04 | 工序 Process | job 账页：3 compile + 3 index，mono job_id、kind Badge、状态文字、时间、snapshot ref | ✅ |
| 05 | 检索 Recall | query `Atlas MVP 发布门禁`，rag 模式 9 条真实命中：score（mono）、source 标题、block 区间 b0–b0 等、Footnote 编号 | ✅ |
| 06 | 问答 Ask | scope.query 构建 Briefing（9 claims）→ 连续两轮提问：serif 问答线程、逐轮 token 账（in/out/total/cache） | ✅（见已知问题 1） |
| 07 | 即时上下文 Live Context | SSE 一次性 Tab 初始态（工作流窗口 + 评估参数 + 空态文案）；录入两条 Atlas 发布进度片段、min_confidence 调 5 → 评估：存活 1/已下发 1（confidence 9 提示 + 引用），GateLedger 门禁账 dropped：无引用 1 · 低置信 1 | ✅ |
| 08 | 正典 Canonical | 选中 atlas 文档：serif claims、Footnote 上标 [1]（accent、基线对齐正常）、锚点 mono、§03 出处账 | ✅ |
| 09 | 图谱 Graph | 选中 atlas 节点：邻域边高亮、其余节点淡出、右侧详情（类型/id/路径/相邻边）、图例 typeGlyph 形状冗余编码 | ✅ |
| 10 | 版本 History | patch/job/snapshot 统一账页；选中 patch → 变更文档、消化来源、Lineage（model/tokens，mono 定义表）、Claims trace | ✅ |
| 11 | 演化 Evolve | skill 信息（version v3、content_hash、7 条 path_templates）+ 空任务账 EmptyState | ✅ |
| 12 | 历史快照只读 | SnapshotPicker 选历史快照 → 档案戳横幅「历史快照 · 只读」+ mono ref +「回到 HEAD」，顶栏 ref 同步 | ✅ |
| 13 | 组件矩阵 `#/components` | 全 primitives 状态矩阵整页（fullPage 截图）：按钮/输入/选择/数值/开关/浮层/反馈/排版 | ✅ |
| 14 | 图谱 390px | 图在上详情在下纵向排；`scrollWidth=390` 无横向溢出 | ✅ |

每旅程同时断言：console 0 error（最终全量运行 0 error / 0 warning）、
移动端 `document.documentElement.scrollWidth <= 390`。

## 截图索引

全部位于 `docs/e2e/screenshots/`（旧设计截图已整目录清除后重拍）：

| 文件 | 内容 |
|---|---|
| [00-overview-light.png](e2e/screenshots/00-overview-light.png) / [00-overview-dark.png](e2e/screenshots/00-overview-dark.png) / [00-overview-mobile.png](e2e/screenshots/00-overview-mobile.png) | 卷首：题字 + 流程图 + L0–L3 + 翻阅指引，三形态 |
| [01-sources-light.png](e2e/screenshots/01-sources-light.png) / [01-sources-dark.png](e2e/screenshots/01-sources-dark.png) / [01-sources-mobile.png](e2e/screenshots/01-sources-mobile.png) | 原料：选中 source 的结构地图 + blocks，三形态 |
| [02-ingest-initial.png](e2e/screenshots/02-ingest-initial.png) / [02-ingest-dark.png](e2e/screenshots/02-ingest-dark.png) | 四类 official source 导入入口，亮/暗双主题 |
| [03-profile-light.png](e2e/screenshots/03-profile-light.png) | 画像：synthetic OPC 人设 |
| [04-process.png](e2e/screenshots/04-process.png) | 工序 job 账页 |
| [05-recall.png](e2e/screenshots/05-recall.png) | 检索 rag 命中账（score + block 区间） |
| [06-ask.png](e2e/screenshots/06-ask.png) | 问答：briefing + 两轮 serif 问答 + token 账 |
| [07-live-context-initial.png](e2e/screenshots/07-live-context-initial.png) / [07-live-context-gated.png](e2e/screenshots/07-live-context-gated.png) | 即时上下文初始态；评估后存活提示 + GateLedger 门禁账 |
| [08-library.png](e2e/screenshots/08-library.png) | 正典：claims + 脚注 + 出处 |
| [09-graph-selected.png](e2e/screenshots/09-graph-selected.png) | 图谱：选中节点 + 邻域 + 详情 |
| [10-history.png](e2e/screenshots/10-history.png) | 版本：patch 账页 + lineage |
| [11-evolve.png](e2e/screenshots/11-evolve.png) | 演化：skill 信息 + 空任务账 |
| [12-snapshot-readonly.png](e2e/screenshots/12-snapshot-readonly.png) | 历史快照档案戳只读横幅 |
| [13-components.png](e2e/screenshots/13-components.png) | 组件状态矩阵（fullPage） |
| [14-graph-mobile.png](e2e/screenshots/14-graph-mobile.png) | 图谱 390px 纵排 |

## 修复清单（本轮回合发现并修复，均限 `apps/web/src/**`）

1. **图谱移动端画布塌成 0 高**（骨架级）。`GraphView.tsx` 画布容器
   `flex-1` 在列向 flex 下 `flex-basis:0%` 压掉 `h-[420px]`，390px 时
   React Flow 报「parent container needs a width and a height」（console
   warning ×3）且节点不可点。修为 `lg:flex-1`（仅行向主轴生效），移动端
   恢复 420px 固定高。
2. **Select 受控告警**。`ui/Select.tsx` 把 `null` 值映射为 `undefined`
   （Radix 的非受控），ContextSuggestion 视图 focus 词表异步回填后从非受控跳到受控，React
   抛「changing from uncontrolled to controlled」warning。修为 `value ?? ""`
   （Radix 合法的受控空值，仍显示 placeholder）。
3. **DefinitionList 术语列溢出重叠**。sources「编译计划」中
   `canonical_treatment`（19 字符 mono）超过默认 `sm:w-28` 术语列，与定义列
   文字视觉重叠。按 primitive 既有参数在调用点加宽为 `sm:w-48`
   （`SourcesView.tsx`）。

## 自动回归与静态扫描

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全套测试 | `uv run pytest -q` | **453 passed** |
| 开源卫生 | `uv run pytest tests/test_open_source_hygiene.py -q` | 7 passed |
| 前端构建 | `cd apps/web && pnpm build` | ✅（tsc + vite，GraphCanvas 保持独立 lazy chunk 276.55 kB） |
| 浏览器 console | e2e 全程收集 error/warning/pageerror | **0 条** |
| 390px 横向溢出 | `scrollWidth <= 390`（00/01/14 三处移动旅程） | 全部 390 ✅ |
| 原生控件扫描 | `grep -rn "<select\|<input\|<textarea\|type=\"range\"…" apps/web/src --include="*.tsx" \| grep -v src/ui/ \| grep -v VisuallyHidden` | 空 ✅（业务层零裸原生控件） |
| hex/rgb 扫描 | `grep -rn "#[0-9a-fA-F]\{3,8\}\|rgb(\|hsl(" apps/web/src … \| grep -v tokens.css \| grep -v color-mix` | 空 ✅（颜色只在 tokens.css） |
| whitespace | `git diff --check` | clean ✅ |

## 已知非阻塞问题

1. **问答旅程无引用脚注**：scripted recall-script 的答案文本本身不含
   `[cite:]` 句柄，两轮回答因此没有脚注；UI 如实呈现「本轮没有返回 source
   引用；答案可阅读，但尚未完成证据绑定」的 notice——是演示数据的特征，
   不是组件缺陷（recall/suggestion/library 的 Footnote 在各自旅程均验证正常）。
2. ~~390px 顶栏字标截断~~（已修复）：移动端字标收窄为 `Pneuma`，
   `· Knowledge Compiler` 副题从 sm 断点起显示，不再截断。
3. **scripted 模型游标一次性**：`ScriptedChatModel` 按进程内游标顺序回放，
   重跑 ask/suggestion 旅程前需重启 API 复位游标（e2e 脚本全量运行时序已按
   recall-script 3 回合 / live-context-script 1 回合排好）。
4. **本机端口冲突**：5173/5174/18000 被其他工作区的常驻 dev server 占用，
   本次验收用 5199（vite）/18001（API）；CI/干净机器用默认端口即可。

## 复现

```bash
docker compose -f infra/docker-compose.yml up -d --wait
uv sync --all-packages
uv run python examples/seed_demo.py
NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
  PNEUMA_KNOWLEDGE_EMBEDDING_MODEL=fake:64 \
  PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL=scripted:examples/data/opc-demo/recall-script.json \
  PNEUMA_KNOWLEDGE_LLM_MODEL_LIVE_CONTEXT=scripted:examples/data/opc-demo/live-context-script.json \
  bash scripts/dev-api.sh                                   # 127.0.0.1:18000
cd apps/web && pnpm dev                                     # 代理 /v1 → 18000
node e2e/screenshots.mjs                                    # 全量旅程 + 截图
```
