# examples

可运行的端到端脚本。分三类：**keyless**（无需任何 key，只要 `docker compose up` 起中间件，
用确定性 mock 模型/embedding）、**需 OpenRouter key**（跑真实 LLM/embedding）、**维护脚本**。

先起中间件：`docker compose -f infra/docker-compose.yml up -d --wait`。

## Keyless（无需 key，跑真中间件 + mock 模型）

| 脚本 | 做什么 |
|---|---|
| `rag_e2e.py` | 入库两个用户的中/英/日对话 → `rag` 双路召回 + L0 原文直取 + 用户隔离自检。**新用户最快的 keyless 冒烟**。 |
| `compile_e2e.py` | 入库 → 用 scripted 模型 compile → git 快照 + 四视图投影（documents/graph/timeline/journal）。 |
| `briefing_e2e.py` | 入库 → scripted compile → `fast` / `deep`（agentic）/ 锚定来源的 `briefing` 连续问答。 |
| `upgrade_e2e.py` | 升级演练：Path A 换投影策略不动 canonical HEAD；Path B v2 前向新增 compile。 |
| `cue_e2e.py` | context_stream **主动提词**：入库 → 建索引 → 对一段转录窗口评估 → 五道机械闸门（看得见 `dropped` 计数）→ 句柄解析回真实来源 → `want_more` 按卡片自己的引用直取原文扩写。 |
| `seed_demo.py` | 重置并生成合成 OPC 用户 `u-opc-lin`：3 个上下文流 → L0/L1/L2 → scripted compile + 引用门禁 → Git canonical / L3 投影。UI 走查前运行。 |

```bash
uv run python examples/rag_e2e.py
```

## 预制数据集（一条命令导入已处理 OPC 用户，**无需 key**）

`data/preset/` 下打包了一个**已编译**的合成用户（四层齐全：L0 原文 + L1 词法 + L2 语义向量
+ L3 canonical claim），干净机器 `docker compose up` 后一条 import 命令即可浏览，**无需 key、无需编译**：

| friendly id | 来源 | 画像 |
|---|---|---|
| `u-opc-lin` | `opc-demo-v1` | 中文 AI-Native 一人公司开发者；3 源 / 9 claims / 3 Git snapshots |

```bash
# 干净中间件上导入合成用户（幂等，重跑先清同名 user；不打 OpenRouter）
uv run python examples/import_presets.py
uv run python examples/import_presets.py u-opc-lin
```

导入后打开 UI 即可浏览 Canonical / Graph / History；`.env` 配好 key 后可直接
`fast` / `deep` 问答（带 `[cite:]` 出处）——全程不触发任何编译。

> ship 的向量随包一起导入并**按 (source_id, char span) 重算 point_id**，所以 import 不调用
> embedding provider（无 key 也能导入 + 浏览）。仅**问答**需要 key。

**（维护者）重新导出预制包**：`uv run python examples/export_presets.py`——按 user 过滤 dump
四层到 `data/preset/<friendly-id>/`（PG 全表确定性排序 + gzip、Qdrant 带向量、Meili documents、
canonical git tar）。改选哪些 user 用 `export_presets.py <src_uid>=<friendly_id> …`。

## 需要 OpenRouter key（跑真实 LLM + embedding）

先配好根目录 `.env`（见 [`.env.example`](../.env.example)）。

| 脚本 | 做什么 |
|---|---|
| `smoke_openrouter.py` | 真 provider 端到端冒烟：真实 compile（claim 级工具）+ fast/deep/briefing，全程 trace 到 Langfuse。**验证「我的 key 能不能跑通整条链路」**。 |
| `context_stream_ab.py` | 第一方 context_stream source-type 的 A/B：同一份合成会议片段按 `upload` vs `context_stream` 各编译一次，对比 canonical 归属。`--show-prompt` **无需 key**、render 真实 compile prompt。复测指引见 [docs/first-party-context-stream.md](../docs/first-party-context-stream.md)。 |

```bash
uv run python examples/smoke_openrouter.py   # 真链路冒烟
```

`data/opc-demo/cue-script.json` 是 UI 闸门截图使用的无密钥脚本响应。只在本地复验时通过
`PNEUMA_KNOWLEDGE_LLM_MODEL_CUE=scripted:examples/data/opc-demo/cue-script.json`
显式启用，不参与默认运行配置。

## 维护脚本

| 脚本 | 做什么 |
|---|---|
| `rebuild_derived.py <user_id...> \| --all` | 从权威（L0 + canonical git）核对并**同时重建 L1 + L2 + L3** 全部派生索引，打印每层 before/after。中间件被清空、换容器版本、换 embedding（维度变）或换分块策略后跑它。L2 语义分块走 **chunk manifest** 回放 → 逐字确定性重建（见 [getting-started 运维节](../docs/getting-started.md)）。 |
| `reindex_l2.py <user_id...>` | 只重建 **L2** 向量（L1 词法、L3 canonical 不动）——上面那条的子集，快速冒烟够用。 |

```bash
# 中间件清空 / 换版本 / 换模型后，把某用户的派生层整体重建回来
uv run python examples/rebuild_derived.py u-opc-lin
# 或只重 L2 一层
uv run python examples/reindex_l2.py u-opc-lin
```
