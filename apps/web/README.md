<!--
Pneuma Web 视觉方向：Knowledge Transit Atlas。
运行时 token 唯一事实来源为 src/styles/tokens.css；线路构图位于
src/styles/transit.css；规范见 ../../DESIGN.md 与 ../../docs/design/STYLE.md。
图标使用 lucide，无 emoji；日 / 夜双主题。
-->

# pneuma-knowledge-compiler Web

Pneuma Knowledge Compiler 的 Vite + React + TypeScript 操作界面，直接消费
`pneuma-knowledge-service` FastAPI。它以 **Knowledge Transit Atlas** 解释并运行
个人知识编译器：Source、PostgreSQL、Meilisearch L1、Qdrant L2、Compile Gate 与
Canonical Git 是一条可运行、可重建、可追溯的六站线路。

界面不是静态架构图。用户可以建/选画像、导入材料、观察异步索引与编译、运行多模式召回、
浏览 canonical、图谱和版本，并从真实 citation 一路查回 source、claim 与 patch/Git。

日间是瓷白城市导视图，夜间是午夜珐琅控制室。两套主题独立调校表面、线路、阴影与对比度；
主题选择持久化，不做机械反色。

> 完整从零启动链路见
> [`../../docs/getting-started.md`](../../docs/getting-started.md)。Web 不是独立 mock：
> 中间件、API 与 worker 需要按该文档启动。

## 设计资产

- [`src/styles/tokens.css`](./src/styles/tokens.css)：**运行时 design token 唯一事实来源**。
- [`src/styles/transit.css`](./src/styles/transit.css)：线路图、站点页、destination sheet、
  真实 evidence journey 与响应式构图。
- [`../../DESIGN.md`](../../DESIGN.md)：从当前实现提炼的可移植设计系统。
- [`../../docs/design/STYLE.md`](../../docs/design/STYLE.md)：工程使用约束。
- [`../../docs/design/tokens.css`](../../docs/design/tokens.css)：只导入运行时源的文档代理，
  不保存第二份 token 值。

不要手工同步 token 副本。修改主题或基础 token 时只编辑
`src/styles/tokens.css`，再验证日间、夜间与 390px 路线。

## 系统线路

默认首页在一个视口内说明权威层、可重建层与编译边界：

1. `S0` 原始材料
2. `P0` PostgreSQL
3. `L1` Meilisearch（词法，可重建）
4. `L2` Qdrant（语义，可重建）
5. `C1` 编译门
6. `G1` Canonical Git

桌面使用可键盘操作的 SVG 线路；820px 以下切换为完整六站纵向线路。390px 视口不裁站点，
并保留完整 `SYNTHETIC` 披露。

首页 destination sheet 与四段 journey 都从当前 dataset 读取 source/span、claim anchor、
canonical path 和 patch/ref。没有编译数据时显示真实空态，不生成 KPI 或占位证据。

## 线路导航

### 线路

| 视图 | 内容 |
|---|---|
| **系统线路** | 六站架构、层级图例、真实 trace、synthetic manifest 与下一步路线。 |

### 运行演示

| 视图 | 内容 |
|---|---|
| **导入材料** | 上传或粘贴材料，预览 intake plan，由后台 worker 异步索引与编译。 |
| **检索实验** | `rag / fast / deep / briefing` 四模式召回；deep 通过 SSE 展示 agentic 取证过程。 |
| **主动提示** | 模拟 context suggestion 的提示、沉默、丢弃与门禁结果。 |

### 核对证据

| 视图 | 内容 |
|---|---|
| **来源档案** | L0 原文、实时消化状态与 source → claim → compile/Git 证据路径。 |
| **Canonical** | Markdown、frontmatter、claim 级 citation 与 disputed / open-question / inferred 状态。 |
| **版本轨道** | snapshot、patch、单文档演化与只读历史视图。 |

### 探索内部

| 视图 | 内容 |
|---|---|
| **编译作业** | job、patch、lineage、token、来源、escalation 与 journal 回放。 |
| **关系换乘** | 基于 `@xyflow/react` + dagre 的 n 度子图，按需 code split。 |
| **连续问答** | 先冻结证据包，再进行带 citation 的 briefing 多轮问答。 |
| **工作画像** | OPC 工作语境、回答层级、语言与隐私偏好。 |
| **策略演化** | 审阅可比较、可回滚的策略结构建议。 |

视图间 document、graph node、patch、snapshot、claim 与 source 的跳转使用稳定 ID 契约。

## 服务连接

浏览器同源调用 API。`VITE_API_BASE` 默认空，开发时 `vite.config.ts` 将 `/v1` 与
`/healthz` 代理到本地服务：

- 默认 `http://127.0.0.1:18000`；
- 设置 `PNEUMA_KNOWLEDGE_API_PORT` 后使用该端口。

部署时可把构建产物挂在 API 同源路径。跨源部署则在构建时注入
`VITE_API_BASE=https://<api-host>`。

## 开发与构建

```bash
pnpm install
pnpm dev          # http://localhost:5173
pnpm build        # tsc -b && vite build → dist/
pnpm preview
```

## 技术栈

Vite、React、TypeScript、Tailwind v4、Lucide、`@xyflow/react`、dagre 与
react-markdown。UI 原语在 `src/components/ui.tsx`；主题 token 在
`src/styles/tokens.css`；Knowledge Transit Atlas 构图在
`src/styles/transit.css`。
