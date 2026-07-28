# Pneuma Knowledge Compiler · E2E 验收报告

验收日期：2026-07-28
环境：macOS · 浏览器真实渲染 · PostgreSQL + Qdrant + Meilisearch · FastAPI · Vite
租户：`u-opc-lin`（仓库内置、明确标记为 synthetic 的 OPC 中文人设）

## 结论

通过。无密钥 mock 从 L0 原文进入真实索引与编译流水，最终形成可浏览、可召回、
可追溯到 Git 快照的 canonical 知识。新版 Web 以 “Knowledge Transit Atlas”
呈现权威来源、可重建索引、编译门和 Git 版本，而非后台管理表格；全部入口、
瓷白日间 / 午夜蓝夜间主题、历史快照与 390px 移动端均完成真实浏览器验收。

## 数据流水

执行：

```bash
uv run python examples/seed_demo.py
uv run python examples/export_presets.py
```

结果：

| 层 | 结果 |
|---|---:|
| L0 来源 / blocks | 3 / 9 |
| jobs | 6（3 index + 3 compile） |
| L1 Meilisearch | 9 blocks + 9 claims |
| L2 Qdrant | 9 chunks + 9 claims，64 维 fake embedding |
| L3 canonical | 3 文档 + 9 claims + 3 Git commits |
| profile | 1 个中文 OPC synthetic persona |

第二次以 `--keep` 运行可验证来源去重；公开 preset 位于
`examples/data/preset/u-opc-lin/`，可在没有模型密钥时恢复四层数据。

## 浏览器旅程

| 旅程 | 验收点 | 结果 |
|---|---|---|
| System route | 首屏六站架构图、真实 source/span/claim/canonical/Git 线路、权威/可重建分层与数据计数 | 通过 |
| Sources | 三份 context stream、结构地图、原文块、消化状态 | 通过 |
| Ingest | 站点工作区中粘贴合成文档 → 两步预览 → 机械 IntakePlan 建议 | 通过 |
| Process | 六个真实 job、created 文档、来源与 portable model lineage | 通过 |
| Recall | `Atlas MVP 发布门禁` → L1/L2 RRF → 9 个可定位命中 | 通过 |
| Ask | 构建固定 briefing → 连续两轮提问 → token/cache 元数据 | 通过 |
| Context cue | 发布进度预置 → 无密钥 SSE → 2 张下发、1 张本地阈值过滤、1 张无引用拦截 | 通过 |
| Canonical | 3 篇文档、`pneuma_id`、claim 引用与 patch 轨迹 | 通过 |
| Graph | 选择 atlas → 展开 source 关系 → 文档/演化跳转 | 通过 |
| History | 3 个 Git patch、模型血缘、来源与 claim trace | 通过 |
| Evolve | base v3、7 个 OPC 路径模板、0 个扩展 pack 空态 | 通过 |
| Snapshot | 选择历史 commit → `READ ONLY` → 恢复 HEAD | 通过 |
| Theme | 瓷白线路图 ↔ 午夜蓝控制室，线路语义与选择持久化 | 通过 |
| Mobile | 390×844：完整六站线路、`SYNTHETIC` 披露、Sources、Graph 选中关系与纵向详情 | 通过 |
| Typography | 12px 中文字号下限、表单/正文层级、HEAD 选择器使用正文字体、桌面/移动端无溢出 | 通过 |

## 截图索引

| # | 画面 | 截图 |
|---:|---|---|
| 00a | System route · 瓷白日间 | [查看](./e2e/screenshots/00-system-route-light.png) |
| 00b | System route · 午夜蓝夜间 | [查看](./e2e/screenshots/00-system-route-dark.png) |
| 01 | Sources · 日间 | [查看](./e2e/screenshots/01-sources-light.png) |
| 02 | Sources · 夜间 | [查看](./e2e/screenshots/02-sources-dark.png) |
| 03 | OPC 中文工作画像 | [查看](./e2e/screenshots/03-profile-light.png) |
| 04a | Ingest 初始态 | [查看](./e2e/screenshots/04-ingest-light.png) |
| 04b | Ingest 机械预览 | [查看](./e2e/screenshots/04-ingest-preview-light.png) |
| 05 | Compile process | [查看](./e2e/screenshots/05-process-light.png) |
| 06 | RAG 真实召回 | [查看](./e2e/screenshots/06-recall-rag-light.png) |
| 07 | Briefing 连续问答 | [查看](./e2e/screenshots/07-briefing-ask-light.png) |
| 08a | Context cue 初始态 | [查看](./e2e/screenshots/08-context-cue-light.png) |
| 08b | Context cue 闸门结果 | [查看](./e2e/screenshots/08-context-cue-gated-light.png) |
| 09 | Canonical Library | [查看](./e2e/screenshots/09-library-light.png) |
| 10 | 选中节点的证据图谱 | [查看](./e2e/screenshots/10-graph-selected-light.png) |
| 11 | Git 版本历史 | [查看](./e2e/screenshots/11-history-light.png) |
| 12 | OPC 策略演化 | [查看](./e2e/screenshots/12-evolve-light.png) |
| 13 | Sources · 390px | [查看](./e2e/screenshots/13-sources-mobile-light.png) |
| 14 | Graph · 390px 纵向详情 | [查看](./e2e/screenshots/14-graph-mobile-light.png) |
| 15 | 历史快照只读态 | [查看](./e2e/screenshots/15-historical-snapshot-readonly-light.png) |
| 16 | Context cue · 全局字体层级复验 | [查看](./e2e/screenshots/16-typography-cue-light.png) |
| 17 | 快照选择器 · 正文字体复验 | [查看](./e2e/screenshots/17-snapshot-typography-fixed.png) |
| 18 | System route · 390px 完整六站线路 | [查看](./e2e/screenshots/18-system-route-mobile-light.png) |

## 自动回归

```text
Python: 425 passed
Web:    TypeScript + Vite production build passed
UI detector: 0 findings
Browser console: 0 warnings / 0 errors
Brand/hardware hygiene: 0 forbidden matches, including compressed preset assets
Typography: no Chinese microcopy below 12px; 2504px / 390px target viewports passed
```

Vite 仍报告主入口 minified chunk 约 568 kB 的性能提示；图谱已经独立拆包，
该提示不影响本次功能验收，作为后续 bundle-budget 优化项保留。
