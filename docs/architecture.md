# pneuma-knowledge-compiler 架构规格

> 本文是全项目的权威设计规格。实施任何里程碑前先读完本文。
> 公共核心保持业务无关；默认 `opc_developer` 策略服务 AI-Native 一人公司开发者，
> 其他领域通过显式 strategy pack 扩展。

## 0. 定位与两条全程纪律

为 AI-Native 个人开发者提供可审计知识编译能力：对话与各类材料入库，
编译为结构化个人知识（canonical），支持多级检索与低延迟问答。

两条纪律（任何实现不得偏离）：

1. **机制化而非劝说**：凡靠 prompt 劝模型"记得做 X"的路线均已被实验证伪。
   约束必须是机械机制：写时拒绝、系统分配 ID、确定性正规化、类型区分。
   发现自己在写"请务必"类 prompt 文案时，就是走错了。
2. **成本线与分数线分开验收**：性能/成本指标与质量指标分开立项、分开度量；
   任何质量结论必须先有同 harness 对照；度量启用前先审"它在测什么"。

## 1. 仓库结构

```text
pneuma-knowledge-compiler/
├── pyproject.toml                  # uv workspace（虚拟根）
├── packages/
│   ├── pneuma-knowledge-core/               # 纯逻辑 + 端口抽象。零中间件依赖（pydantic + langchain-core + langchain）
│   │   └── src/pneuma_knowledge_core/
│   │       ├── domain/             # 领域模型：ids / source / canonical / intake / skill / snapshot
│   │       ├── ingest/             # SourceAdapter 注册表 + IntakePolicy + 归一化
│   │       ├── skill/              # 版本化策略 + 可组合 pack + 紧凑投影渲染
│   │       ├── compile/            # patch→gate→salvage + claim 级写机制（纯函数，store 走端口）
│   │       ├── recall/             # rag / fast / deep 三 mode + briefing
│   │       └── ports/              # 全部 Protocol 端口（见 §6）
│   └── pneuma-knowledge-service/            # 云原生服务：端口实现 + API + worker
│       └── src/pneuma_knowledge_service/
│           ├── api/                # FastAPI：/v1/users/{user_id}/…
│           ├── adapters/           # git_canonical / qdrant / meilisearch / postgres / content_mock
│           ├── workers/            # compile worker（消费 PG 任务队列）
│           └── settings.py         # 12-factor，全走环境变量
├── apps/web/                       # UI：Pneuma 证据台视觉语言，日/夜双主题
├── infra/                          # docker compose：qdrant + postgres + meilisearch
├── docs/                           # 本文 + adr/ + api / skill-authoring（随里程碑补齐）
├── examples/                       # 端到端脚本示例（每个里程碑至少一个）
└── tests/                          # 根级 e2e；单测/集成测试在各包内 tests/
```

依赖方向唯一合法：`service → core`、`apps/web → service API`。core 永不 import 任何
中间件客户端；LLM/Embeddings 不自建抽象，core 函数签名直接收 langchain-core 的
`BaseChatModel` / `Embeddings`，service 用 `init_chat_model` 从配置装配。agentic 循环
（deep / briefing ask）用 langchain 的 `create_agent`（langgraph ReAct），不手搓工具循环。

**全栈异步**（见 [adr/003](adr/003-full-stack-async.md)）：端口是 async `Protocol`，core 中
碰端口或模型的函数、全部 adapter、全部路由、compile worker 一路异步到底。边界纪律：**凡不
await 任何东西的就不是协程**——`spine` / `citation_alias` / `projection` / `gate` / `patch` /
`domain` 与各 render 助手保持同步。少数无法真异步的（git subprocess、langfuse flush、chonkie
分块）在 adapter 内 `to_thread`，并在代码里注明它不是真异步。

## 2. 领域不变式（违反任何一条 = review 打回）

- **I1 user_id 隔离**：一切数据、一切端口方法、一切存储布局都以 user_id
  为第一维隔离。git repo per-user、Meilisearch index per-user、Qdrant 单 collection +
  强制 tenant filter（adapter 层机械注入，业务层无法绕过）、PG 行级 user 键。
  不存在任何跨 user 读路径。
- **I2 canonical vs derived 类型区分**：canonical（git 权威层 + 原始 content）是唯一
  不可重建物；投影、索引、注记全部是 derived，声明为可全量重建。策略/渲染升级只触发
  derived 重建，**永不改写 canonical**（需求 6 的机制位）。两类对象在 domain 层用类型区分。
- **I3 L0/L1 无条件可达**：任何素材无论 IntakePlan 如何，raw 原文直取与词法全文检索
  永远可用。索引深度可随策略递减，可达性永不归零。
- **I4 provenance 统一**：一切知识回链 `source_id + ¶span`。claim citation、语义 chunk、
  词法命中、结构地图使用同一寻址体系，逐级钻取靠它白拿。
- **I5 上下文装配纪律**：SystemMessage 逐字节稳定，**绝不含时间戳等易变内容**；
  问题、as_of、会话增量全走 HumanMessage。cache 命中是装配顺序正确白拿的，不是优化出来的。
- **I6 泄漏纪律**：任何评测的答案/评分细则/证据字段永不进入 compile 或 recall 的输入。

## 3. 四级数据访问模型

同一 source 的四个平行视图（平行可用，不是只降级兜底）：

| 级 | 视图 | 覆盖 | 产生方 |
|---|---|---|---|
| L0 | raw 原文直取：`fetch(user, source_id, locator)`，locator 支持结构寻址（章/节/¶区间） | 无条件 | adapter 结构地图 |
| L1 | 词法全文检索（关键词/稀疏） | 无条件 | 入库即索引（Meilisearch） |
| L2 | 语义检索（embedding chunk，Qdrant） | 按 IntakePlan | projection indexer |
| L3 | canonical 知识（compile 后 claims，fast/deep 消费） | 按 IntakePlan | compile 管线 |

`recall(mode=rag)` = L2 + L1 双路召回 + RRF 融合；素材无 L2 时词法路仍覆盖，检索面无洞。
问答 agent 工具面 = 四级各一个工具，按意图选级（事实性→L3/L2，找原话→L1，要原件→L0）。

## 4. Intake：三层抽象

**纪律：数据类型的多样性只允许被吸收在 adapter 层；策略词表与执行路径封闭且极小。**

```text
任意输入（上下文流 / Pneuma app 第一方数据 / 用户上传第三方文件）
  → ① SourceAdapter（唯一允许随类型增长的层）
       产出 NormalizedSource：分块正文(blocks) + 结构地图(章节→¶span) + 元数据 + checksum
       只懂"这是什么形态"，不懂"该记住什么"
  → ② IntakePolicy（封闭词表）
       NormalizedSource + 用户覆盖 → IntakePlan（两旋钮）
       v1 判定 = adapter 申报默认 + 体量阈值等机械规则；LLM 分类器留待有真实误分样本
  → ③ 执行路径（固定三条，永不新增）
       workstream compile / reference compile（卡片+定向蒸馏）/ projection indexer
```

IntakePlan 两旋钮（只管 L2/L3；L0/L1 是不变式不在词表内）：

- `canonical_treatment`: `full | distill | card | none`
- `semantic_indexing`: `full | summary | none`

**用户面的处理意图（archetype）**：文档 intake 不让用户猜"体裁"（note/contract/novel 这类
开放且不可枚举的集合），而是选一个**命名的处理意图**——它就是两旋钮的一个预设：精读归档
（full/full）、要点蒸馏（distill/full）、存目索引（card/summary）、仅可检索（none/none），
外加「让系统判断」（走机械 `propose_intake`）。这套原型是单一事实源，定义在 core
（`domain/intake.py` 的 `INTAKE_ARCHETYPES`），经 `GET /v1/intake/archetypes` 提供给前端。
旧的 `declared_type`（note/contract/novel）降为后向兼容的机械 hint，不再是用户轴。

基准矩阵（机械 auto 路径的判定依据）：

| 数据 | treatment | semantic | 说明 |
|---|---|---|---|
| 上下文流（第一方） | full | full | 主路径 |
| 手写 note | full | full | 都重要，尽量全 compile |
| 合同类重要文书 | distill | full | 关键信息蒸馏进 canonical，正文外置为可检索资料 |
| 小说等大部头 | card | summary | 只留卡片与元信息；正文仍 L0/L1 可达 |
| 结构化流（日历/通知，未来） | distill | summary | 周期蒸馏成事实，不索原始流水 |

职责边界：**intake 决定"怎么消化"，skill 决定"什么该记"**（准入/敏感/秘密排除在
compile 时的 skill 层）。IntakePlan 是提案：UI 预览、用户可改、落库留审计。
新类型无法用现有词表表达时 = 触发设计评审，不是加分支。词表每加一个值需项目主人确认。

## 5. 状态归属

| 状态 | 归属 | 性质 |
|---|---|---|
| canonical | per-user git repo（共享存储） | 权威，不可重建 |
| 原始 content + 结构地图 | PG（append-only）+ 文件/对象存储 payload | 权威输入 |
| 词法索引 | Meilisearch（index per user） | derived，可重建 |
| 语义索引 | Qdrant（tenant filter） | derived，可重建 |
| 投影/注记 | PG | derived，可重建 |
| compile 任务队列 | PG（`FOR UPDATE SKIP LOCKED`，按 user_id 串行） | 运行时 |
| service / worker 进程 | 无状态 | 任意扩缩 |

快照 = git commit/tag（`SnapshotRef`），白拿。v1 不引 Redis。

## 6. 端口（core/ports，全部 Protocol，第一参数一律 user_id）

- `ContentStore`：add / get / list / `fetch(user, source_id, locator)`（L0）
- `LexicalIndex`：index_blocks / search（L1，无条件覆盖全部素材，支持中日文分词）
- `VectorIndex`：upsert_chunks / search（L2；adapter 内机械注入 tenant filter）
- `ProjectionStore`：投影读写（derived）
- `CanonicalStore`：read/list documents（支持 `at: SnapshotRef`）/ commit_patch / snapshots / tag
- `JobQueue`：enqueue / claim_next（per-user 串行）/ complete
- `ContentProvider`：未来外部内容微服务的只读抽象（fetch by ref）
- `UserInfoProvider`：user_id → 用户画像（persisted-first 组合：已存画像优先，未设置时回落到 mock 具名人设）

## 7. recall 能力与 Briefing

`recall(user, query, mode)`，mode ∈ `rag | fast | deep`，另有 Briefing 连续问答：

- **rag**：L2+L1 双路 RRF 融合；命中经重叠去重（同区域的词法/向量命中合并成一条、分数相加）。
- **fast**：claim 注记 + 原文 window 双面融合作答。两面各自 RRF、**并行召回**；原文 window 走
  **后处理装配管线**——forward-only 上下文扩展 → 近邻合并/去重 → 每源限流 →
  lost-in-the-middle 排序 → 带「来源:材料名·¶块号」标注渲染。作答契约是"姿态陈述"而非规则清单，
  带入本人画像（含回复语言）与 ASR 音近容错，问题放 Human turn 末尾。
- **deep**：有界 **agentic 深查**——fast 的种子召回 + 三工具面（search_claims / search_content /
  fetch_verbatim），`create_agent` 循环 + recursion_limit 封顶；核验是 agentic 行为（回 L0 核对
  出处），每步经 SSE **流式**推到前端（`POST …/recall/stream`）。

### AI cue（context_stream 主动提词）

上面四种都由一个提问触发。**cue 的触发方向是反的**：context_stream 实时转录流进来，系统旁听，
没有人在提问，所以产物是零张或几张结构化卡片而非一段答案，**默认必须沉默**。

- **两种卡片**：`concept`（对话里出现了知识库里有的概念/人/事，说明它是什么）与
  `fact`（对话里出现了知识库能直接回答的问题，给出答案）。
- **focus** ∈ `general | owner | other`（通用 / 仅我的关键词 / 仅他人关键词）：
  **绝不按说话人过滤转录**——过滤会摧毁上下文理解。整段永远全量进入，focus 只表达为
  System 层三份定值契约的注意力指向。
- **沉默是机械的**（§0 纪律 1）：五道闸门——已展示去重 → 解析失败即沉默 →
  **引用闸门**（body 里没有可解析回真实来源的 `[cite:]` 即丢弃，未接地的提词按定义不是提词）
  → **信心闸门**（LLM 为每条打 1-10，阈值过滤在程序侧，故中途调阈值无需重跑）→ 按信心截断。
- **检索不跨轮 RRF 融合**：RRF 是为「同一 query 多路」设计的，跨轮融合会让每轮都排中游的
  泛泛来源压过「只在某一轮排第一」的尖锐信号。改为每轮取 top-k 后并集并标记触发轮次
  （`trigger` 字段即由此而来），并集后再 coalesce 一次，`expand_and_merge` 只跑一次。
- **两种传输**：`POST …/context_stream/cue/stream`（一次性 SSE，去重在客户端）与
  `WS …/context_stream/cue/ws`（长连接，服务端持窗口与节流；**客户端仍是去重权威**，
  重连时回传近期轮次与已展示项——service 进程因此保持无状态，见 §5）。
- **want_more**：把已收到的卡片传回，按它自己的引用直取 L0 原文扩写。零检索、零 embedding。

**分块（L2）**：chonkie；`PNEUMA_KNOWLEDGE_CHUNK_STRATEGY` 默认 `semantic`（LLM 判「一人一段/一主题一段」
的块边界，只回整数边界），`sentence` 为机械回退；任何超长 chunk 按字符硬切（`enforce_max_chars`），
保证可嵌入且有界。语义边界是 LLM 输出、跨次调用不可复现，故首次分块把段边界连同内容 digest +
模型血缘落进 PG `chunk_manifests`；重建时（内容 × 策略 × 模型）不变即回放记录的边界而非重新检测——
使 derived L2 从「可重建」升为「字节确定性重建」（I2 仍成立：正文始终是 L0 逐字切片，manifest 只钉住
那一步非确定性）。

**入库异步**：`sources/conversation`、`sources/document` 只落 L0 + 入队 `index`（L1/L2）与
`compile`（L3）两类任务；worker 后台处理，并在重启时自愈卡住的任务。

**Briefing**（预加载问答会话）：`brief(user, scope, snapshot) → Briefing`，
`briefing.ask(question, as_of)` 连续问答复用稳定上下文包。

- `scope.query`：一次 recall 取料 + 预算截断；
- `scope.source_ids`：**锚定历史 raw data**——装入该 source 的 material 卡片 + 引用它的
  全部 canonical claims（citation 反查）+ 原文相关片段；
- 装配守 I5：知识包进 System（逐字节稳定），问题/as_of 走 Human turn；
- agent 工具面：search_knowledge（包内检索）+ fetch_verbatim（L0 逐字直取，"合同第一章原封发给我"场景）。

## 8. 复用的架构资产与明确拒绝的反模式

复用：git-canonical + 机械 Gate + claim 级 citation/provenance；claim 级写机制
（anchor preflight + edit_claim/append_block）；salvage 确定性打捞；Deep 有界核验；
紧凑投影渲染（render_v2 思路）；materials 三层框架；rag-v1 混合检索思路；
可组合 strategy pack（slug 形态：按主体与工作流分文件）。

不移植：Fusion 评审机器；skill YAML 整体 dump 进 prompt；固定 5 文件 ownership；
指令式 transition 簿记（transition 由系统从 diff 机械推导）；consumer/retrieval_intents
渲染进编译 prompt。

## 9. 已交付（0.1.0）

- **骨架**：uv workspace（core/service 两包）+ compose 三中间件 + keyless 测试脚手架。
- **入库**：对话 + 文档（处理意图 archetype）；**异步**入队，worker 处理 L1/L2/L3。
- **compile**：claim 级写工具 + 机械 gate + salvage + 四视图投影；git per-user canonical。
- **分块**：chonkie `sentence` + `semantic`（LLM 判「一人一段」边界）+ 超长硬切兜底。
- **embedding**：OpenRouter（`openai/text-embedding-3-small`，连接池复用）。
- **recall**：`rag` / `fast`（claim+window 融合 + 装配管线）/ `deep`（agentic + SSE 流式）/
  `Briefing`；作答契约带本人画像（回复语言）+ ASR 音近容错。
- **AI cue**：context_stream 旁听主动提词（concept / fact 两型，focus 三档，五道机械闸门，
  SSE + WebSocket 双传输，want_more 按引用直取原文扩写）。
- **UI**：Pneuma 瓷白城市导视图 / 午夜珐琅控制室双主题；工作画像、来源、入库、编译、
  召回、问答、提示、Canonical、图谱、历史与演化全流程。
- **可观测**：Langfuse（可选，优雅降级）。**升级演练**：skill v1→v2 零 canonical 重写、
  derived 全量重建。
