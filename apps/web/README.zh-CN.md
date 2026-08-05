# apps/web

[English](README.md) | **简体中文**

架在 HTTP API 之上的双语 Web 工作台：把整条流水线——原始材料、编译任务、带逐条引用的正本文库、三档检索、演进评审——走一遍，每一步都能下钻回证据。

## 运行

```bash
docker compose -f ../../infra/docker-compose.yml up -d --wait
bash ../../scripts/dev-api.sh        # API 于 127.0.0.1:18000
bash ../../scripts/dev-worker.sh     # 编译 worker（需要任务真跑起来时）
pnpm install && pnpm dev             # Vite 于 :5173，代理 /v1 与 /healthz
```

```bash
pnpm run build    # tsc -b && vite build——提交 web 改动前必须跑
pnpm test         # node --test tests/*.test.mjs（纯逻辑测试，无浏览器）
```

唯一的环境变量是 `VITE_API_BASE`（留空 = 同源走开发代理）。要一个完整打包的部署形态（nginx + API + worker + 预置演示数据，零 API key），见 [`examples/opc/`](../../examples/opc/)。

## 形状

React 18 + Zustand + Radix + Tailwind v4。没有 react-router：`src/App.tsx` 用一张视图名 → 懒加载组件的映射表，Zustand store 把选中状态双向同步到 `location.hash`——深链与前进后退都好使（`#/evolve/evolve-task/<id>`）。

外壳带租户切换器、快照选择器（HEAD / 冻结 KB 快照 / 正本历史，钉住时盖只读印）、中英 locale 切换（全量词典在 `src/i18n/`）和纸/灯箱主题切换。视图按侧栏分组：

| 组 | 视图 |
|---|---|
| 卷首 | overview（带实时计数的系统地图） |
| 原料 | sources（目录、校样、L0 直取）、ingest（契约 + 文档，先预览后落地） |
| 工序 | process（触发 + 任务队列）、history（编译时间线、逐 claim 差异） |
| 取用 | recall（rag / fast / deep-SSE）、ask（briefing）、live_context（SSE + WS、门禁账） |
| 正本 | library（文档、claim 徽章、引用、邻域）、graph（结构体检 + 快照对比） |
| 演化 | evolve（草稿评审：理由、文件 diff、消失锚点、采纳/丢弃） |
| 卷末 | components（设计系统画廊） |

## 设计规则

设计权威是 [`DESIGN.zh-CN.md`](DESIGN.zh-CN.md)；它的可执行形态在两个文件——[`src/styles/tokens.css`](src/styles/tokens.css)（所有颜色只住这里；组件零 hex/rgb 字面量；派生色只用 `color-mix`）和 [`src/index.css`](src/index.css)（阅读排版、分区滚动约定、原生控件重置）。速览版：

- 双主题独立调校、非反色：日间「纸 Paper」、夜间「灯箱 Lightbox」。
- 唯一强调色（蓝铅笔）用于链接、选中、focus 与脚注编号；状态用文字和墨色阶表达，不用红绿灯。
- 编辑部气质：近直角、只有 fade/2–4px 位移的动效、发丝分隔线、衬线阅读面（霞鹜文楷优先）+ 无衬线 UI + 等宽机器文本。
- `components` 视图是 `src/ui/` 下约 35 个原子组件的画廊——造新轮子前先去那儿看一眼。
