# 从 0 跑通 pneuma-knowledge-compiler Demo

这份文档带你从一个干净的机器开始，先用**零密钥 + 本地 Docker**，把
pneuma-knowledge-compiler 跑起来并玩到：建用户 → 入库对话/文档 → 后台编译成结构化知识 →
浏览来源、canonical、图谱与 Git 历史。真实模型问答是后续可选步骤。

> **pneuma-knowledge-compiler 是什么**：业务无关的开源个人知识编译器。
> 把对话、文档、决策和实验记录编译成带出处的结构化知识（存于 per-user 的 Git 仓库），
> 并支持四级数据访问（L0 原文直取 / L1 词法 / L2 语义 / L3 canonical claim）与低延迟问答。

---

## 0. 你需要什么

- **Docker**（跑三个中间件：Postgres / Qdrant / Meilisearch）。
- **[uv](https://docs.astral.sh/uv/)**（Python 包管理与运行）。
- **Node ≥ 18 + [pnpm](https://pnpm.io/)**（跑前端 UI）。
- **可选：OpenRouter API key**。只有真实 compile、fast/deep 问答与 AI 生成人设需要；
  mock 编译、preset 导入、浏览和测试均不需要。

---

## 1.（可选）配置真实模型

```bash
cp .env.example .env
```

如果只跑 keyless demo，可以跳过本节。要连接真实模型时，把 `OPENROUTER_API_KEY` 写入
本地 `.env`；不要把 `.env` 提交到 Git。

## 2. 起中间件（Docker）

```bash
docker compose -f infra/docker-compose.yml up -d --wait
```

拉起并等待三个服务健康（均只绑 `127.0.0.1`）：

| 服务 | 端口 | 作用 |
|---|---|---|
| Postgres | `15432` | L0 原文 + 任务队列 + 用户画像 + L3 claim 投影 |
| Qdrant | `16333` | L2 语义向量 |
| Meilisearch | `17700` | L1 词法检索（支持中日文） |

## 3. 装依赖

```bash
uv sync --all-packages          # Python：core + service 两个包
cd apps/web && pnpm install && cd ../..   # 前端
```

## 4. 生成 keyless OPC 演示数据

```bash
uv run python examples/seed_demo.py
```

这不是静态 UI 假数据：三段合成上下文会实际经过 L0 入库、L1/L2 索引、scripted compile、
引用门禁、Git canonical 与派生投影，最终生成 `u-opc-lin` 的 3 篇文档、9 条 claim 和
3 个 Git 快照。重跑默认先清理该合成租户；`--keep` 可验证去重。

## 5. 起服务

分别在两个终端跑：

```bash
# ① API（http://127.0.0.1:18000，autoreload）
bash scripts/dev-api.sh

# ② 前端 UI（http://localhost:5173，vite 把 /v1 反代到 API）
cd apps/web && pnpm dev
```

演示数据已经处理完成，因此浏览不需要 worker。手动从 UI 新增材料时，再启动
`bash scripts/dev-worker.sh` 消费异步队列。API 与 worker 都是无状态的。

## 6. 另一条路径：导入已处理 preset

仓库同时带有上述 `u-opc-lin` 的已处理四层 bundle；在干净中间件中可直接导入：

```bash
uv run python examples/import_presets.py
```

bundle 随包包含向量，import 不调用 embedding provider。导入是幂等替换。详见
[examples/README.md](../examples/README.md)。

## 7. 打开 UI

浏览器打开 **http://localhost:5173** ：

1. **工作画像**：检查 OPC 工作方式、技术栈、自动化水平和回答偏好。
2. **材料入库**：加一段对话，或上传一份文档并选**处理意图**（精读归档 / 要点蒸馏 / 存目索引 /
   仅可检索）。点「确认提交」——**秒回**（只入队），重活在后台跑。
3. **来源原文 / 编译流水**：看证据与 `索引中 → 编译中 → 已消化` 状态。
4. **证据召回 / 知识问答**：
   - `rag`：L1+L2 双路 RRF 融合的原始命中列表；
   - `fast`：claim + 原文窗口融合，直接作答，带出处；
   - `deep`：**agentic 深查**——模型自己调 search/fetch 工具多步取证，**过程流式一步步展示**，
     完成后折叠、答案落在下面；
   - `Ask`：对一个预加载的 Briefing 连续快速问答。
5. **Canonical / 证据图谱 / 版本历史**展示知识、引用关系和 Git 演化。
6. 右上角主题按钮在**瓷白线路图**与**午夜控制室**之间切换。

## 8.（可选）纯 API 玩法

```bash
U=u-opc-lin
# 入库一段对话（异步：返回 source_id + 入队，worker 后台编译）
curl -s -X POST "http://localhost:18000/v1/users/$U/sources/conversation" \
  -H 'content-type: application/json' \
  -d '{"title":"MVP 评审","turns":[{"speaker":"我","text":"Atlas 首版只做来源导入、混合检索和带引用回答"}]}'

# 入库是异步的：轮询来源，等 digested_at 非空（= 已编译进 canonical）再做 L3 召回。
# 队列本身可看 GET /v1/users/$U/jobs（queued/claimed/done）。
curl -s "http://localhost:18000/v1/users/$U/sources" | python3 -m json.tool

# 召回：fast（claim + 原文窗口，带出处）
curl -s -X POST "http://localhost:18000/v1/users/$U/recall" \
  -H 'content-type: application/json' \
  -d '{"query":"Atlas 的 MVP 范围是什么","mode":"fast"}'
```

- **交互式 API 文档**：服务起来后打开 **http://localhost:18000/docs**（Swagger UI）或
  取 `http://localhost:18000/openapi.json`——比读源码更快。探活用 `GET /healthz`。
- 想看完整实现见 `packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/v1.py`。

---

## 跑测试（无需任何 key）

```bash
uv run pytest
```

测试全程 keyless：一个 `conftest.py` 把 embedding 固定为确定性 mock（`fake:384`）、分块固定为
机械 `sentence`，并用独立的 Qdrant 测试 collection——不碰你的 app 数据、不打真实 provider。

---

## 运维：重建派生索引（L1 / L2 / L3）

**只有两样是权威**：PG 里的 L0（`sources` / `blocks`）和每用户 canonical git 仓库（L3 的源）。
其余全部**派生、可从权威重建**——L1 词法（Meili）、L2 向量（Qdrant）、L3 投影（PG `canonical_claims`
+ Meili claims + Qdrant claim 层）。所以中间件被清空、容器换版本、换 embedding 模型（维度变）、
换分块策略时，你**不会丢数据**，只需把派生层重建回来。

一条命令核对并同时重建某用户的三层：

```bash
uv run python examples/rebuild_derived.py u-opc-lin     # 单个用户
uv run python examples/rebuild_derived.py u-opc-lin
uv run python examples/rebuild_derived.py --all             # 所有有 L0/canonical 的用户
```

它会打印每层的 before/after（L2 chunk 数、L3 claim 数）供你核对。需要 `.env` 里的真实
`OPENROUTER_API_KEY`（L2 语义分块 + 重嵌要打 provider）。只想重建 L2 一层用
`examples/reindex_l2.py <user>`（`rebuild_derived` 的子集）。

**「可重建」≠「字节确定性重建」。** L1、L3 投影是纯机械的，同输入必得同输出。L2 的
**语义分块要问 LLM 边界**，而 LLM 跨次调用并不可复现（同一份源重跑可能给出 17 vs 19 个 chunk）。
为此每个源在首次分块时把 LLM 选定的段边界连同**内容 digest + 模型血缘**落进 PG `chunk_manifests`；
重建时只要（内容 × 策略 × 模型）没变，就**回放**记录的边界而非重新检测——于是重建**逐字一致**。
只有源被编辑（内容 digest 变）、换模型或换策略才会重新问 LLM 并刷新 manifest。无论走哪条路，
chunk 正文始终是 L0 的逐字切片（invariant I4）。

> 换 embedding 模型改变了向量维度时，Qdrant collection 会按新维度重建；跑一次
> `rebuild_derived`（或至少 `reindex_l2`）把两层向量重嵌回来即可。

---

## 架构一览

- **两个包**：`pneuma-knowledge-core`（纯领域逻辑 + Protocol 端口，零中间件依赖）、`pneuma-knowledge-service`
  （中间件 adapter + FastAPI + worker）。
- **四级数据访问**：L0 原文直取 · L1 词法（Meili，无条件覆盖全部素材）· L2 语义（Qdrant，
  按 IntakePlan）· L3 canonical claim（LLM 编译，带出处）。
- **入库异步**：请求只落 L0 + 入队；worker 按 `index`（L1/L2）与 `compile`（L3）两类任务处理，
  重启时自愈卡住的任务。
- **分块**：chonkie；默认 `semantic`（LLM 判「一人一段」边界），超长内容按长度硬切。
- **召回作答**：契约是「姿态陈述」而非规则清单，带入本人画像（含回复语言）与 ASR 音近容错；
  deep 是有界的 agentic 搜索并支持 SSE 流式。

深入细节见 [architecture.md](architecture.md)、关键决策见 [adr/](adr/)、可观测性见
[observability.md](observability.md)、知识库升级演练见 [upgrade.md](upgrade.md)。

---

## 常见问题

- **召回报 429 / Rate limit**：OpenRouter 那侧的每分钟 token 额度（TPM）被打满了，等十几秒重试即可。
  这是瞬时限流，生产环境会加退避重试。
- **`确认提交` 后一直「待编译」**：worker 没在跑，或它正在按 `索引 → 编译` 顺序处理（大文档需 1-2 分钟）。
  确认 `scripts/dev-worker.sh` 在跑；worker 重启会自愈卡住的任务。
- **换 embedding / LLM 模型**：改 `.env` 对应行即可。注意换 embedding 会改向量维度 → 需重建 Qdrant
  collection 并重嵌——见上面「运维：重建派生索引」（`rebuild_derived.py`，或只重 L2 的 `reindex_l2.py`）。
- **中间件被清空 / 换了容器版本 / 召回突然变空**：canonical 与 L0 是权威、没丢；跑
  `uv run python examples/rebuild_derived.py <user_id>` 把 L1/L2/L3 重建回来即可（见「运维」一节）。
